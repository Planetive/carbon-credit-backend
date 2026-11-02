"""
Scope 3 factor unit parsing for Categories 1, 2, 4, 5, 9, 12.

Refuse missing/ambiguous units. Do not invent factors.
Conversion constants are standard SI/US customary (not emission factors).
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

# Distance / mass conversions (not emission factors).
KM_PER_MILE = 1.60934
KG_PER_SHORT_TON = 907.18474
KG_PER_METRIC_TONNE = 1000.0

# EPA GHG Emission Factors Hub / WARM Table 9 style waste sheet has no Units
# column in public.waste; values match MTCO2e per short ton. Callers must pass
# this string explicitly — never invent a different waste unit silently.
WASTE_DATASET_FACTOR_UNIT = "MTCO2e/short ton"


def _norm_unit(unit: Optional[str]) -> str:
    return re.sub(r"\s+", " ", str(unit or "").strip().lower())


def classify_freight_factor_unit(factor_unit: Optional[str]) -> Optional[str]:
    """
    Return one of: short_ton_mile | vehicle_mile | tonne_km | kg_km
    or None if unsupported / missing.
    """
    u = _norm_unit(factor_unit)
    if not u:
        return None
    compact = u.replace(" ", "").replace("_", "-")
    if "vehicle-mile" in compact or "vehiclemile" in compact.replace("-", ""):
        return "vehicle_mile"
    if "shortton-mile" in compact.replace(" ", "") or "short-ton-mile" in compact:
        return "short_ton_mile"
    if "short ton-mile" in u or "short ton mile" in u:
        return "short_ton_mile"
    if "tonne-km" in compact or "tonnekm" in compact.replace("-", "") or u in (
        "tkm",
        "t-km",
    ):
        return "tonne_km"
    if "kg-km" in compact or "kgkm" in compact.replace("-", ""):
        return "kg_km"
    # Ambiguous bare "ton-mile" without short/metric → refuse
    return None


def freight_emissions_kg(
    *,
    distance_km: float,
    weight_kg: float,
    co2_factor: float,
    factor_unit: Optional[str],
) -> Tuple[Optional[float], Optional[str]]:
    """
    Activity distance is kilometres; mass is kilograms (form convention).
    Returns (emissions_kg, error).
    """
    kind = classify_freight_factor_unit(factor_unit)
    if kind is None:
        return None, "Freight factor unit missing or unsupported; refuse calculation"

    if not (distance_km > 0):
        return None, "distance must be > 0"

    if kind == "vehicle_mile":
        miles = float(distance_km) / KM_PER_MILE
        return float(co2_factor) * miles, None

    if not (weight_kg > 0):
        return None, "weight must be > 0 for this freight factor unit"

    if kind == "short_ton_mile":
        miles = float(distance_km) / KM_PER_MILE
        short_tons = float(weight_kg) / KG_PER_SHORT_TON
        return float(co2_factor) * miles * short_tons, None

    if kind == "tonne_km":
        tonnes = float(weight_kg) / KG_PER_METRIC_TONNE
        return float(co2_factor) * float(distance_km) * tonnes, None

    if kind == "kg_km":
        return float(co2_factor) * float(distance_km) * float(weight_kg), None

    return None, "Freight factor unit missing or unsupported; refuse calculation"


def classify_waste_factor_unit(factor_unit: Optional[str]) -> Optional[str]:
    """
    Return mtco2e_per_short_ton | kg_per_kg | kg_per_short_ton | None.
    """
    u = _norm_unit(factor_unit)
    if not u:
        return None
    compact = re.sub(r"[^a-z0-9/]", "", u)
    # MTCO2e / short ton (EPA Hub / WARM)
    if "mtco2e" in compact and "shortton" in compact:
        return "mtco2e_per_short_ton"
    if "metric ton" in u and "co2" in u and "short ton" in u:
        return "mtco2e_per_short_ton"
    if compact in ("mtco2e/shortton",):
        return "mtco2e_per_short_ton"
    if "kgco2e/kg" in compact or "kgco2/kg" in compact:
        return "kg_per_kg"
    if "kgco2e/shortton" in compact or "kgco2/shortton" in compact:
        return "kg_per_short_ton"
    return None


def waste_mass_to_short_tons(mass: float, mass_unit: Optional[str]) -> Tuple[Optional[float], Optional[str]]:
    u = _norm_unit(mass_unit)
    if not u:
        return None, "Waste mass unit missing; refuse calculation"
    if u in ("kg", "kilogram", "kilograms"):
        return float(mass) / KG_PER_SHORT_TON, None
    if u in ("short ton", "short tons", "short-ton", "uston", "us ton", "us tons"):
        return float(mass), None
    if u in ("tonne", "tonnes", "metric ton", "metric tons", "t", "mt"):
        return (float(mass) * KG_PER_METRIC_TONNE) / KG_PER_SHORT_TON, None
    return None, f"Unsupported waste mass unit: {mass_unit}"


def waste_emissions_kg(
    *,
    mass: float,
    mass_unit: Optional[str],
    factor: float,
    factor_unit: Optional[str],
) -> Tuple[Optional[float], Optional[str]]:
    if not (mass > 0):
        return None, "mass must be > 0"

    kind = classify_waste_factor_unit(factor_unit)
    if kind is None:
        return None, "Waste factor unit missing or unsupported; refuse calculation"

    if kind == "kg_per_kg":
        mu = _norm_unit(mass_unit)
        if mu not in ("kg", "kilogram", "kilograms"):
            return None, "Waste mass must be kg when factor is per kg"
        return float(mass) * float(factor), None

    short_tons, err = waste_mass_to_short_tons(mass, mass_unit)
    if err or short_tons is None:
        return None, err

    if kind == "mtco2e_per_short_ton":
        # factor is metric tonnes CO2e per short ton → kg CO2e
        return short_tons * float(factor) * KG_PER_METRIC_TONNE, None

    if kind == "kg_per_short_ton":
        return short_tons * float(factor), None

    return None, "Waste factor unit missing or unsupported; refuse calculation"


def parse_spend_factor_basis(
    factor_unit: Optional[str],
) -> Optional[Tuple[str, Optional[int], str]]:
    """
    Parse suppliers-style unit 'kg CO2e/2022 USD, purchaser price'.
    Returns (intensity_kind, price_year, currency) or None.
    intensity_kind: kg_per_currency | t_per_currency
    """
    u = _norm_unit(factor_unit)
    if not u:
        return None
    year_match = re.search(r"\b(19|20)\d{2}\b", u)
    price_year = int(year_match.group(0)) if year_match else None
    currency: Optional[str] = None
    if re.search(r"\busd\b|\$|dollar", u):
        currency = "usd"
    elif re.search(r"\bgbp\b|£|pound", u):
        currency = "gbp"
    elif re.search(r"\beur\b|€|euro", u):
        currency = "eur"
    elif re.search(r"\bpkr\b|rupee", u):
        currency = "pkr"
    if currency is None:
        return None
    if re.search(r"\b(tco2e|t co2e|tonne|mtco2e)\b", u) and "kg" not in (
        u.split("/")[0] if "/" in u else u
    ):
        kind = "t_per_currency"
    elif "kg" in u and "co2" in u:
        kind = "kg_per_currency"
    else:
        return None
    return kind, price_year, currency


def classify_spend_factor_unit(factor_unit: Optional[str]) -> Optional[str]:
    """Return kg_per_currency | t_per_currency | None."""
    parsed = parse_spend_factor_basis(factor_unit)
    return parsed[0] if parsed else None


def spend_emissions_kg(
    *,
    amount: float,
    emission_factor: float,
    factor_unit: Optional[str],
    activity_currency: Optional[str] = None,
    activity_price_year: Optional[int] = None,
) -> Tuple[Optional[float], Optional[str]]:
    """
    Spend × intensity only when activity currency and price year match the
    factor basis. No FX or inflation adjustments are invented.
    """
    if not (amount > 0):
        return None, "amount must be > 0"
    parsed = parse_spend_factor_basis(factor_unit)
    if parsed is None:
        return None, "Spend factor unit missing or unsupported; refuse calculation"
    kind, factor_year, factor_currency = parsed

    act_cur = _norm_unit(activity_currency)
    if not act_cur:
        return None, (
            "Spend activity currency required and must match factor currency "
            f"({factor_currency.upper()}); FX conversion is not available"
        )
    if act_cur != factor_currency:
        return None, (
            f"Spend currency {act_cur.upper()} does not match factor "
            f"{factor_currency.upper()}; exchange rates are not invented"
        )

    if factor_year is not None:
        if activity_price_year is None:
            return None, (
                f"Spend price year required to match factor year {factor_year}; "
                "inflation adjustments are not invented"
            )
        if int(activity_price_year) != int(factor_year):
            return None, (
                f"Spend price year {activity_price_year} does not match factor "
                f"year {factor_year}; inflation adjustments are not invented"
            )

    raw = float(amount) * float(emission_factor)
    if kind == "t_per_currency":
        return raw * KG_PER_METRIC_TONNE, None
    return raw, None


def classify_travel_distance_unit(factor_unit: Optional[str]) -> Optional[str]:
    """
    Return passenger_mile | vehicle_mile | per_mile | passenger_km | vehicle_km |
    per_km | None.

    Sheet factors already encode passenger vs vehicle intensity for the selected
    mode; this classifier drives distance conversion only. Bare "mile"/"km"
    without passenger/vehicle or CO2 intensity context is refused — occupancy is
    never invented.
    """
    u = _norm_unit(factor_unit)
    if not u:
        return None
    compact = u.replace(" ", "").replace("_", "-")
    if "passenger-mile" in compact or "passengermile" in compact.replace("-", ""):
        return "passenger_mile"
    if "vehicle-mile" in compact or "vehiclemile" in compact.replace("-", ""):
        return "vehicle_mile"
    if "passenger-km" in compact or "passengerkm" in compact.replace("-", ""):
        return "passenger_km"
    if "vehicle-km" in compact or "vehiclekm" in compact.replace("-", ""):
        return "vehicle_km"
    if "mile" in u and ("co2" in u or "kg" in u):
        return "per_mile"
    if ("/km" in u or compact.endswith("km")) and "mile" not in u and (
        "co2" in u or "kg" in u
    ):
        return "per_km"
    return None


def travel_distance_emissions_kg(
    *,
    distance_km: float,
    co2_factor: float,
    factor_unit: Optional[str],
) -> Tuple[Optional[float], Optional[str]]:
    """Activity distance is kilometres. Convert using the factor's distance unit."""
    if not (distance_km > 0):
        return None, "distance must be > 0"
    kind = classify_travel_distance_unit(factor_unit)
    if kind is None:
        return None, "Travel factor unit missing or unsupported; refuse calculation"
    if kind in ("passenger_mile", "vehicle_mile", "per_mile"):
        miles = float(distance_km) / KM_PER_MILE
        return float(co2_factor) * miles, None
    # passenger_km | vehicle_km | per_km
    return float(co2_factor) * float(distance_km), None


def annualize_commuting_distance_km(
    *,
    distance_km: float,
    distance_basis: Optional[str] = None,
    working_days_per_year: Optional[float] = None,
) -> Tuple[Optional[float], Optional[str]]:
    """
    distance_basis:
      annual_total — distance already annual (default when days omitted)
      one_way — multiply by 2 trips/day × working days (do not double again)
      round_trip — multiply by working days only (never auto-double)
    """
    if not (distance_km > 0):
        return None, "distance must be > 0"
    basis = _norm_unit(distance_basis) if distance_basis else "annual_total"
    if basis in ("", "annual", "annual_total", "annual-total", "total"):
        return float(distance_km), None
    if working_days_per_year is None or not (float(working_days_per_year) > 0):
        return None, "working_days_per_year required for one_way/round_trip commuting"
    days = float(working_days_per_year)
    if basis in ("one_way", "one-way", "oneway"):
        return float(distance_km) * 2.0 * days, None
    if basis in ("round_trip", "round-trip", "roundtrip"):
        return float(distance_km) * days, None
    return None, f"Unsupported commuting distance_basis: {distance_basis}"
