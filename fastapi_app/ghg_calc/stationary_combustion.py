"""
Backend-authoritative EPA Scope 1 stationary combustion.

Looks up CO2, CH4, and N2O on Fuel EPA 1/2/3. The caller cannot supply the
factor or the total. CH4 and N2O sheet values are grams of that gas; CO2 sheet
values are kilograms of CO2. GWP is applied after the gram-to-kilogram conversion.

Accounting, version epa_stationary_biogenic_v1:
- GHG Protocol Corporate Standard: CO2 from biomass combustion is reported
  outside the scopes. CH4 and N2O from that combustion stay in Scope 1.
  Peat is not biomass, so peat CO2 stays in Scope 1.
- IPCC 2006 Volume 2, Chapter 1, Table 1.1: peat is grouped with fossil fuels
  because it accumulates on geological timescales. Chapter 2 treats biomass CO2
  as a memo item.
- EPA Emission Factors for Greenhouse Gas Inventories, Table 1, supplies the
  factors. Its biomass heading is a lookup group. A fuel in that heading is
  biogenic only when its name is one of the documented biomass rows below.
  Peat is the exception and stays in Scope 1.

Older epa_stationary_v1 records keep the totals already stored. This module
does not rewrite them. Fuels with no documented biogenic fraction, including
municipal solid waste and percentage blends, are returned for review and are
not saved as a guessed Scope 1 or biogenic total.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Mapping, Optional, Sequence

GWP_SETS = {
    "AR5": {
        "CO2": Decimal("1"),
        "CH4": Decimal("28"),
        "N2O": Decimal("265"),
    }
}

_UNIT_ALIASES = {
    "mmbtu": "mmBtu",
    "mm btu": "mmBtu",
    "short ton": "short ton",
    "short tons": "short ton",
    "shortton": "short ton",
    "us short ton": "short ton",
    "gallon": "gallon",
    "gallons": "gallon",
    "us gallon": "gallon",
    "gal": "gallon",
    "mmscf": "MMSCF",
    "mm scf": "MMSCF",
}

_FACTOR_UNITS = {
    "mmBtu": {
        "co2": "kg CO2 / mmBtu",
        "ch4": "g CH4 / mmBtu",
        "n2o": "g N2O / mmBtu",
    },
    "short ton": {
        "co2": "kg CO2 / short ton",
        "ch4": "g CH4 / short ton",
        "n2o": "g N2O / short ton",
    },
    "gallon": {
        "co2": "kg CO2 / gallon",
        "ch4": "g CH4 / gallon",
        "n2o": "g N2O / gallon",
    },
    "MMSCF": {
        "co2": "kg CO2 / MMSCF",
        "ch4": "g CH4 / MMSCF",
        "n2o": "g N2O / MMSCF",
    },
}

_GRAM_GASES = ("ch4", "n2o")
_GASES = ("co2", "ch4", "n2o")
_MILLION = Decimal("1000000")
_THOUSAND = Decimal("1000")

# New saves use this version. Older epa_stationary_v1 records keep their stored totals.
ACCOUNTING_VERSION = "epa_stationary_biogenic_v1"
METHODOLOGY = (
    "GHG Protocol Corporate Standard: CO2 from qualifying biomass is reported "
    "outside Scope 1, while CH4 and N2O from that combustion stay in Scope 1. "
    "Masses use the EPA stationary combustion factors on the fuel row. "
    "Peat is not biomass under the GHG Protocol or IPCC 2006 Volume 2, so peat CO2 stays in Scope 1 "
    "even when an EPA factor table files peat with biomass fuels."
)

# EPA Emission Factors for Greenhouse Gas Inventories, Table 1 biomass rows whose
# carbon is biogenic. The sheet category is not used by itself.
_BIOGENIC_FUELS = frozenset(
    {
        "wood and wood residuals",
        "wood",
        "agricultural byproducts",
        "solid byproducts",
        "landfill gas",
        "other biomass gases",
        "biodiesel (100%)",
        "ethanol (100%)",
        "rendered animal fat",
        "vegetable oil",
        "bagasse",
        "black liquor",
        "kraft black liquor",
    }
)
_PEAT_FUELS = frozenset({"peat"})
_REVIEW_FUELS = frozenset(
    {
        "municipal solid waste",
        "msw",
        "mixed municipal solid waste",
        "b20",
        "e85",
    }
)


def canonical_consumption_unit(unit: str) -> Optional[str]:
    key = " ".join(str(unit).strip().lower().split())
    return _UNIT_ALIASES.get(key)


def _parse_decimal(value: Any) -> Optional[Decimal]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return None if value.is_nan() or not value.is_finite() else value
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (value != value or abs(value) == float("inf")):
            return None
        try:
            parsed = Decimal(str(value))
        except InvalidOperation:
            return None
        return None if not parsed.is_finite() else parsed
    text = str(value).replace(",", "").strip()
    if not text:
        return None
    try:
        parsed = Decimal(text)
    except InvalidOperation:
        return None
    return None if not parsed.is_finite() else parsed


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _unit_text(value: Any) -> str:
    return str(value).lower() if isinstance(value, str) else ""


def _contains(unit_text: str, token: str) -> bool:
    return token in unit_text


def factors_for_row(row: Mapping[str, Any]) -> Dict[str, Dict[str, Decimal]]:
    """Physical unit -> gas -> sheet factor. CH4 and N2O stay in grams."""
    hhv = _parse_decimal(
        row.get("Heat Content (HHV)")
        or row.get("Heat Content")
        or row.get("HeatContent")
        or row.get("heat_content_hhv")
        or row.get("hhv")
    )
    hhv_unit = _unit_text(
        row.get("HHV Unit")
        or row.get("HIV Unit")
        or row.get("hhv_unit")
        or row.get("hiv_unit")
        or row.get("heat_content_unit")
    )

    co2_per_mmbtu = (
        _parse_decimal(row.get("CO2 Factor"))
        if _contains(_unit_text(row.get("CO2 Unit")), "mmbtu")
        else None
    )
    ch4_per_mmbtu = (
        _parse_decimal(row.get("CH4 Factor"))
        if _contains(_unit_text(row.get("CH4 Unit")), "mmbtu")
        else None
    )
    n2o_unit_first = _unit_text(row.get("N20 Unit") or row.get("N2O Unit"))
    n2o_per_mmbtu = (
        _parse_decimal(row.get("N2O Factor"))
        if _contains(n2o_unit_first, "mmbtu")
        else None
    )

    co2_unit_1 = _unit_text(row.get("CO2 Unit_1"))
    ch4_unit_1 = _unit_text(row.get("CH4 Unit_1"))
    n2o_unit_1_raw = row.get("N2O Unit_1")
    if n2o_unit_1_raw is None or (isinstance(n2o_unit_1_raw, str) and not n2o_unit_1_raw.strip()):
        n2o_unit_1_raw = row.get("N2O Unit")
    n2o_unit_1 = _unit_text(n2o_unit_1_raw)
    co2_factor_1 = _parse_decimal(row.get("CO2 Factor_1"))
    ch4_factor_1 = _parse_decimal(row.get("CH4 Factor_1"))
    n2o_factor_1 = _parse_decimal(row.get("N2O Factor_1"))

    by_unit: Dict[str, Dict[str, Decimal]] = {}

    mmbtu = {
        "co2": co2_per_mmbtu,
        "ch4": ch4_per_mmbtu,
        "n2o": n2o_per_mmbtu,
    }
    if all(mmbtu[gas] is not None for gas in _GASES):
        by_unit["mmBtu"] = mmbtu  # type: ignore[assignment]

    def _second(token: str, unit_name: str) -> None:
        picked = {
            "co2": co2_factor_1 if _contains(co2_unit_1, token) else None,
            "ch4": ch4_factor_1 if _contains(ch4_unit_1, token) else None,
            "n2o": n2o_factor_1 if _contains(n2o_unit_1, token) else None,
        }
        if all(picked[gas] is not None for gas in _GASES):
            by_unit[unit_name] = picked  # type: ignore[assignment]

    _second("short ton", "short ton")
    _second("gallon", "gallon")

    if hhv is not None and _contains(hhv_unit, "scf") and "mmBtu" in by_unit:
        by_unit["MMSCF"] = {
            gas: by_unit["mmBtu"][gas] * hhv * _MILLION for gas in _GASES
        }
    elif (
        _contains(co2_unit_1, "scf")
        and _contains(ch4_unit_1, "scf")
        and _contains(n2o_unit_1, "scf")
        and all(value is not None for value in (co2_factor_1, ch4_factor_1, n2o_factor_1))
        and "MMSCF" not in by_unit
    ):
        by_unit["MMSCF"] = {
            "co2": co2_factor_1 * _MILLION,  # type: ignore[operator]
            "ch4": ch4_factor_1 * _MILLION,  # type: ignore[operator]
            "n2o": n2o_factor_1 * _MILLION,  # type: ignore[operator]
        }

    return by_unit


def _sheet_source(sheet: Mapping[str, Any]) -> Dict[str, Optional[str]]:
    return {
        "publisher": sheet.get("publisher") or "EPA",
        "dataset_code": sheet.get("dataset_code"),
        "dataset_title": sheet.get("dataset_title"),
        "version_label": sheet.get("version_label"),
        "dataset_id": sheet.get("dataset_id"),
        "effective_from": sheet.get("effective_from"),
        "effective_to": sheet.get("effective_to"),
        "source_notes": sheet.get("source_notes"),
    }


def index_stationary_sheets(
    sheets: Sequence[Mapping[str, Any]],
) -> Dict[tuple, Dict[str, Any]]:
    """category/fuel -> factors and the dataset that supplied the row."""
    index: Dict[tuple, Dict[str, Any]] = {}
    for sheet in sheets:
        source = _sheet_source(sheet)
        for row in sheet.get("rows") or []:
            if not isinstance(row, Mapping):
                continue
            category = str(
                row.get("Category") or row.get("category") or ""
            ).strip()
            fuel = str(
                row.get("Fuel Type") or row.get("Fuel") or row.get("fuel") or ""
            ).strip()
            if not category or not fuel:
                continue
            parsed = factors_for_row(row)
            if not parsed:
                continue
            key = (category.casefold(), fuel.casefold())
            entry = index.setdefault(
                key,
                {
                    "category": category,
                    "fuel": fuel,
                    "by_unit": {},
                    "source": source,
                },
            )
            entry["by_unit"].update(parsed)
            entry["source"] = source
            if row.get("_factor_dataset_id"):
                entry["factor_dataset_id"] = str(row.get("_factor_dataset_id"))
            if row.get("_factor_row_id"):
                entry["factor_row_id"] = str(row.get("_factor_row_id"))
    return index


def _fail(message: str) -> Dict[str, Any]:
    return {
        "success": False,
        "error": message,
        "gases": None,
        "total_kg_co2e": None,
        "total_t_co2e": None,
    }


def _gwp_set(version: str) -> Optional[Dict[str, Decimal]]:
    return GWP_SETS.get(str(version).strip().upper())


def _fuel_key(value: str) -> str:
    return " ".join(str(value).casefold().split())


def classify_stationary_fuel(fuel: str, category: str) -> str:
    """
    fossil_scope1, peat_fossil_scope1, biogenic_co2_outside_scope1, or needs_review.

    A fuel filed under an EPA biomass heading is not biogenic unless its name is
    one of the documented biomass rows. Blends and mixed waste have no biogenic
    fraction on these factor rows, so they are not split.
    """
    name = _fuel_key(fuel)
    group = _fuel_key(category)
    if name in _PEAT_FUELS or name.startswith("peat "):
        return "peat_fossil_scope1"
    if name in _BIOGENIC_FUELS:
        return "biogenic_co2_outside_scope1"
    if name in _REVIEW_FUELS or "%" in name or " blend" in f" {name}":
        return "needs_review"
    if "biomass" in group:
        return "needs_review"
    return "fossil_scope1"


def calculate_stationary_combustion(
    *,
    fuel: str,
    quantity: Any,
    unit: str,
    sheets: Sequence[Mapping[str, Any]],
    category: Optional[str] = None,
    gwp_version: str = "AR5",
    factor: Any = None,
    emissions: Any = None,
    emissions_kg: Any = None,
    total_kg_co2e: Any = None,
    total_t_co2e: Any = None,
    **_ignored: Any,
) -> Dict[str, Any]:
    """
    Calculate all three gases from the factor sheets.

    `factor`, `emissions`, `emissions_kg`, and the total arguments are accepted
    and discarded so a frontend value cannot replace the dataset.
    """
    del factor, emissions, emissions_kg, total_kg_co2e, total_t_co2e, _ignored

    gwp = _gwp_set(gwp_version)
    if gwp is None:
        known = ", ".join(sorted(GWP_SETS))
        return _fail(f"gwp_version must be one of: {known}")

    amount = _parse_decimal(quantity)
    if amount is None or amount < 0:
        return _fail("quantity must be a finite number greater than or equal to 0")

    physical = canonical_consumption_unit(unit)
    if physical is None:
        allowed = "mmBtu, short ton, gallon, MMSCF"
        return _fail(f"unit is not a supported consumption unit ({allowed})")

    fuel_name = str(fuel or "").strip()
    if not fuel_name:
        return _fail("fuel is required")

    index = index_stationary_sheets(sheets)
    fuel_key = fuel_name.casefold()
    category_key = str(category).strip().casefold() if category and str(category).strip() else None
    hits = [
        entry
        for (cat_key, name_key), entry in index.items()
        if name_key == fuel_key and (category_key is None or cat_key == category_key)
    ]
    if not hits:
        return _fail("No EPA stationary factor matches this fuel")
    if len(hits) > 1:
        return _fail("fuel matches more than one category; category is required")

    entry = hits[0]
    bundle = entry["by_unit"].get(physical)
    if not bundle or any(bundle.get(gas) is None for gas in _GASES):
        return _fail(f"{entry['fuel']} has no complete CO2, CH4, and N2O factors for {physical}")

    gases: Dict[str, Dict[str, str]] = {}
    factors: Dict[str, Dict[str, str]] = {}
    total = Decimal("0")
    co2_mass = Decimal("0")
    co2_co2e = Decimal("0")
    for gas in _GASES:
        sheet_factor = bundle[gas]
        mass = amount * sheet_factor
        if gas in _GRAM_GASES:
            mass = mass / _THOUSAND
        gwp_value = gwp["CO2"] if gas == "co2" else gwp[gas.upper()]
        co2e = mass * gwp_value
        total += co2e
        if gas == "co2":
            co2_mass = mass
            co2_co2e = co2e
        gases[gas] = {
            "mass_kg": _decimal_text(mass),
            "gwp": _decimal_text(gwp_value),
            "co2e_kg": _decimal_text(co2e),
        }
        factors[gas] = {
            "value": _decimal_text(sheet_factor),
            "unit": _FACTOR_UNITS[physical][gas],
        }

    treatment = classify_stationary_fuel(entry["fuel"], entry["category"])
    source = dict(entry["source"])
    source["gwp_version"] = str(gwp_version).strip().upper()
    source["gwp"] = {name: _decimal_text(value) for name, value in gwp.items()}
    if entry.get("factor_dataset_id"):
        source["dataset_id"] = entry["factor_dataset_id"]
    if entry.get("factor_row_id"):
        source["factor_row_id"] = entry["factor_row_id"]

    if treatment == "needs_review":
        gases["co2"]["reporting"] = "unassigned"
        return {
            "success": False,
            "review_required": True,
            "error": (
                f"{entry['fuel']} has no documented biogenic fraction. "
                "Its CO2 is not added to Scope 1 and is not reported as biogenic CO2."
            ),
            "fuel": entry["fuel"],
            "category": entry["category"],
            "quantity": _decimal_text(amount),
            "unit": physical,
            "gases": gases,
            "total_kg_co2e": None,
            "total_t_co2e": None,
            "biogenic_co2_kg": None,
            "biogenic_co2_t": None,
            "factors": factors,
            "factor_source": source,
            "accounting": {
                "version": ACCOUNTING_VERSION,
                "treatment": treatment,
                "methodology": METHODOLOGY,
                "gwp_version": source["gwp_version"],
            },
        }

    if treatment == "biogenic_co2_outside_scope1":
        scope_total = total - co2_co2e
        biogenic_kg = co2_mass
        gases["co2"]["reporting"] = "biogenic_outside_scope1"
    else:
        scope_total = total
        biogenic_kg = Decimal("0")
        gases["co2"]["reporting"] = "scope1"

    accounting = {
        "version": ACCOUNTING_VERSION,
        "treatment": treatment,
        "methodology": METHODOLOGY,
        "gwp_version": source["gwp_version"],
        "biogenic_co2_kg": _decimal_text(biogenic_kg),
        "biogenic_co2_t": _decimal_text(biogenic_kg / _THOUSAND),
        "scope1_kg_co2e": _decimal_text(scope_total),
        "scope1_t_co2e": _decimal_text(scope_total / _THOUSAND),
    }
    return {
        "success": True,
        "review_required": False,
        "fuel": entry["fuel"],
        "category": entry["category"],
        "quantity": _decimal_text(amount),
        "unit": physical,
        "gases": gases,
        "total_kg_co2e": accounting["scope1_kg_co2e"],
        "total_t_co2e": accounting["scope1_t_co2e"],
        "biogenic_co2_kg": accounting["biogenic_co2_kg"],
        "biogenic_co2_t": accounting["biogenic_co2_t"],
        "factors": factors,
        "factor_source": source,
        "accounting": accounting,
    }
