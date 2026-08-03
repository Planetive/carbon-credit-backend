"""
UK fuel emissions calc — ported from SPA FuelEmissions.tsx (uk_supabase mode).

Formula (unchanged):
  factor = cell[uk_factor_basis]   # kg CO2e per activity unit
  emissions_kg = round6(quantity * factor)
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, TypedDict

UkFactorBasis = Literal["total", "co2", "ch4", "n2o"]

UK_BASIS_ORDER: List[UkFactorBasis] = ["total", "co2", "ch4", "n2o"]


class UkFactorCell(TypedDict, total=False):
    total: float
    co2: float
    ch4: float
    n2o: float


def parse_number(value: Any) -> Optional[float]:
    """Match SPA parseNumber in FuelEmissions.tsx."""
    if isinstance(value, (int, float)):
        n = float(value)
        return n if n == n and abs(n) != float("inf") else None  # isFinite
    if value is None:
        return None
    cleaned = str(value).replace(",", "")
    try:
        n = float(cleaned)
    except (TypeError, ValueError):
        return None
    return n if n == n and abs(n) != float("inf") else None


def uk_basis_value(cell: Optional[UkFactorCell], basis: UkFactorBasis) -> Optional[float]:
    if not cell:
        return None
    v = (
        cell.get("total")
        if basis == "total"
        else cell.get("co2")
        if basis == "co2"
        else cell.get("ch4")
        if basis == "ch4"
        else cell.get("n2o")
    )
    return v if isinstance(v, (int, float)) and v == v and abs(float(v)) != float("inf") else None


def available_uk_basises(cell: Optional[UkFactorCell]) -> List[UkFactorBasis]:
    if not cell:
        return []
    return [b for b in UK_BASIS_ORDER if uk_basis_value(cell, b) is not None]


def build_uk_factors_map(table_rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Dict[str, UkFactorCell]]]:
    """Build Activity → Fuel → Unit → {total,co2,ch4,n2o} from legacy sheet rows."""
    factors_map: Dict[str, Dict[str, Dict[str, UkFactorCell]]] = {}
    for row in table_rows:
        activity = str(row.get("Activity") or row.get("activity") or "").strip()
        fuel = str(row.get("Fuel") or row.get("fuel") or "").strip()
        unit = str(row.get("Unit") or row.get("unit") or "").strip()
        if not activity or not fuel or not unit:
            continue

        total = parse_number(
            row.get("kg CO2e")
            or row.get("kg_co2e")
            or row.get("kgCO2e")
            or row.get("Kg CO2e")
        )
        co2 = parse_number(
            row.get("kg CO2e of CO2 per unit")
            or row.get("kg_co2e_of_co2_per_unit")
        )
        ch4 = parse_number(
            row.get("kg CO2e of CH4 per unit")
            or row.get("kg_co2e_of_ch4_per_unit")
        )
        n2o = parse_number(
            row.get("kg CO2e of N2O per unit")
            or row.get("kg_co2e_of_n2o_per_unit")
        )

        factors_map.setdefault(activity, {}).setdefault(fuel, {})
        prev = dict(factors_map[activity][fuel].get(unit) or {})
        if total is not None:
            prev["total"] = total
        if co2 is not None:
            prev["co2"] = co2
        if ch4 is not None:
            prev["ch4"] = ch4
        if n2o is not None:
            prev["n2o"] = n2o
        factors_map[activity][fuel][unit] = prev  # type: ignore[assignment]
    return factors_map


def calculate_uk_fuel_emissions(
    quantity: float,
    factor: float,
) -> float:
    """emissions_kg = Number((quantity * factor).toFixed(6)) — SPA FuelEmissions.tsx."""
    return float(f"{(quantity * factor):.6f}")


def resolve_uk_fuel_factor(
    factors_map: Dict[str, Dict[str, Dict[str, UkFactorCell]]],
    activity: str,
    fuel: str,
    unit: str,
    uk_factor_basis: UkFactorBasis = "total",
) -> Dict[str, Any]:
    cell = factors_map.get(activity, {}).get(fuel, {}).get(unit)
    if not cell:
        return {"factor": None, "uk_factor_basis": uk_factor_basis, "cell": None}
    avail = available_uk_basises(cell)
    basis: UkFactorBasis = uk_factor_basis
    if avail and basis not in avail:
        basis = avail[0]
    factor = uk_basis_value(cell, basis)
    return {"factor": factor, "uk_factor_basis": basis, "cell": cell}


def calculate_uk_fuel(
    *,
    quantity: float,
    activity: Optional[str] = None,
    fuel: Optional[str] = None,
    unit: Optional[str] = None,
    uk_factor_basis: UkFactorBasis = "total",
    factor: Optional[float] = None,
    factors_map: Optional[Dict[str, Dict[str, Dict[str, UkFactorCell]]]] = None,
) -> Dict[str, Any]:
    """
    Port of SPA updateRow UK branch.
    Prefer explicit factor; else look up in factors_map.
    """
    resolved_basis: UkFactorBasis = uk_factor_basis
    resolved_factor = factor

    if resolved_factor is None and factors_map and activity and fuel and unit:
        looked = resolve_uk_fuel_factor(
            factors_map, activity, fuel, unit, uk_factor_basis
        )
        resolved_factor = looked["factor"]
        resolved_basis = looked["uk_factor_basis"]

    if resolved_factor is None:
        return {
            "success": False,
            "error": "Could not resolve factor",
            "emissions": None,
            "emissions_kg": None,
            "emissions_tco2e": None,
            "factor": None,
            "uk_factor_basis": resolved_basis,
        }

    emissions_kg = calculate_uk_fuel_emissions(quantity, float(resolved_factor))
    return {
        "success": True,
        "emissions": emissions_kg,  # same field name / unit (kg) as SPA FuelRow.emissions
        "emissions_kg": emissions_kg,
        "emissions_tco2e": float(f"{(emissions_kg / 1000.0):.9f}"),
        "factor": float(resolved_factor),
        "uk_factor_basis": resolved_basis,
        "activity": activity,
        "fuel": fuel,
        "unit": unit,
        "quantity": quantity,
    }
