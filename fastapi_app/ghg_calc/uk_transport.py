"""
UK passenger / delivery factor maps — ported from ukPassengerFactors.ts / ukDeliveryFactors.ts.

Formula (both): emissions_kg = Number((distance * factor).toFixed(6))
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from ._common import fail_payload, norm_cell, parse_number, round6, success_payload

UkFactorBasis = Literal["total", "co2", "ch4", "n2o"]
UK_BASIS_ORDER: List[UkFactorBasis] = ["total", "co2", "ch4", "n2o"]


def uk_emission_factor_cell_from_row(row: Dict[str, Any]) -> Dict[str, float]:
    total = parse_number(
        row.get("kg CO2e")
        or row.get("kg_co2e")
        or row.get("kgCO2e")
        or row.get("Kg CO2e")
        or row.get("kg co2e")
    )
    co2 = parse_number(
        row.get("kg CO2e of CO2 per unit") or row.get("kg_co2e_of_co2_per_unit")
    )
    ch4 = parse_number(
        row.get("kg CO2e of CH4 per unit") or row.get("kg_co2e_of_ch4_per_unit")
    )
    n2o = parse_number(
        row.get("kg CO2e of N2O per unit") or row.get("kg_co2e_of_n2o_per_unit")
    )
    cell: Dict[str, float] = {}
    if total is not None:
        cell["total"] = total
    if co2 is not None:
        cell["co2"] = co2
    if ch4 is not None:
        cell["ch4"] = ch4
    if n2o is not None:
        cell["n2o"] = n2o
    return cell


def uk_basis_value(cell: Optional[Dict[str, float]], basis: UkFactorBasis) -> Optional[float]:
    if not cell:
        return None
    v = cell.get(basis)
    return float(v) if isinstance(v, (int, float)) else None


def available_basises(cell: Optional[Dict[str, float]]) -> List[UkFactorBasis]:
    if not cell:
        return []
    return [b for b in UK_BASIS_ORDER if uk_basis_value(cell, b) is not None]


def build_uk_passenger_map(
    rows: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Dict[str, Dict[str, Dict[str, float]]]]]:
    """activity → type → unit → fuel_type → cell."""
    factors_map: Dict[str, Dict[str, Dict[str, Dict[str, Dict[str, float]]]]] = {}
    for row in rows:
        activity = norm_cell(row.get("activity") or row.get("Activity"))
        typ = norm_cell(
            row.get("type")
            or row.get("Type")
            or row.get("vehicle_type")
            or row.get("vehicleType")
        )
        unit = norm_cell(row.get("unit") or row.get("Unit"))
        fuel = norm_cell(
            row.get("fuel_type")
            or row.get("fuelType")
            or row.get("Fuel type")
            or row.get("Fuel Type")
        )
        if not activity or not typ or not unit or not fuel:
            continue
        parts = uk_emission_factor_cell_from_row(row)
        if not available_basises(parts):
            continue
        factors_map.setdefault(activity, {}).setdefault(typ, {}).setdefault(unit, {})
        prev = dict(factors_map[activity][typ][unit].get(fuel) or {})
        prev.update(parts)
        factors_map[activity][typ][unit][fuel] = prev
    return factors_map


def build_uk_delivery_map(
    rows: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Dict[str, Dict[str, Dict[str, Dict[str, float]]]]]]:
    """activity → type → unit → fuel → laden → cell."""
    factors_map: Dict[
        str, Dict[str, Dict[str, Dict[str, Dict[str, Dict[str, float]]]]]
    ] = {}
    for row in rows:
        activity = norm_cell(row.get("activity") or row.get("Activity"))
        typ = norm_cell(
            row.get("type")
            or row.get("Type")
            or row.get("vehicle_type")
            or row.get("vehicleType")
        )
        unit = norm_cell(row.get("unit") or row.get("Unit"))
        fuel = norm_cell(
            row.get("fuel_type")
            or row.get("fuelType")
            or row.get("Fuel type")
            or row.get("Fuel Type")
        )
        laden = norm_cell(
            row.get("laden_lev")
            or row.get("ladenLev")
            or row.get("laden_level")
            or row.get("laden lev")
            or row.get("Laden lev")
            or row.get("Laden level")
            or row.get("laden level")
        )
        if not activity or not typ or not unit or not fuel:
            continue
        parts = uk_emission_factor_cell_from_row(row)
        if not available_basises(parts):
            continue
        factors_map.setdefault(activity, {}).setdefault(typ, {}).setdefault(
            unit, {}
        ).setdefault(fuel, {})
        prev = dict(factors_map[activity][typ][unit][fuel].get(laden) or {})
        prev.update(parts)
        factors_map[activity][typ][unit][fuel][laden] = prev
    return factors_map


def calculate_uk_passenger(
    *,
    distance: float,
    activity: Optional[str] = None,
    vehicle_type: Optional[str] = None,
    unit: Optional[str] = None,
    fuel_type: Optional[str] = None,
    uk_factor_basis: UkFactorBasis = "total",
    factor: Optional[float] = None,
    factors_map: Optional[
        Dict[str, Dict[str, Dict[str, Dict[str, Dict[str, float]]]]]
    ] = None,
) -> Dict[str, Any]:
    resolved = factor
    basis: UkFactorBasis = uk_factor_basis
    if resolved is None and factors_map and activity and vehicle_type and unit and fuel_type:
        cell = (
            factors_map.get(activity, {})
            .get(vehicle_type, {})
            .get(unit, {})
            .get(fuel_type)
        )
        avail = available_basises(cell)
        if avail and basis not in avail:
            basis = avail[0]
        resolved = uk_basis_value(cell, basis)

    if resolved is None:
        return fail_payload("Could not resolve UK passenger factor")

    emissions_kg = round6(float(distance) * float(resolved))
    return success_payload(
        emissions_kg,
        factor=float(resolved),
        extra={
            "activity": activity,
            "vehicle_type": vehicle_type,
            "unit": unit,
            "fuel_type": fuel_type,
            "uk_factor_basis": basis,
            "distance": distance,
            "quantity": distance,
        },
    )


def calculate_uk_delivery(
    *,
    distance: float,
    activity: Optional[str] = None,
    vehicle_type: Optional[str] = None,
    unit: Optional[str] = None,
    fuel_type: Optional[str] = None,
    laden_level: Optional[str] = None,
    uk_factor_basis: UkFactorBasis = "total",
    factor: Optional[float] = None,
    factors_map: Optional[
        Dict[str, Dict[str, Dict[str, Dict[str, Dict[str, Dict[str, float]]]]]]
    ] = None,
) -> Dict[str, Any]:
    resolved = factor
    basis: UkFactorBasis = uk_factor_basis
    laden_key = norm_cell(laden_level)
    if (
        resolved is None
        and factors_map
        and activity
        and vehicle_type
        and unit
        and fuel_type
    ):
        cell = (
            factors_map.get(activity, {})
            .get(vehicle_type, {})
            .get(unit, {})
            .get(fuel_type, {})
            .get(laden_key)
        )
        avail = available_basises(cell)
        if avail and basis not in avail:
            basis = avail[0]
        resolved = uk_basis_value(cell, basis)

    if resolved is None:
        return fail_payload("Could not resolve UK delivery factor")

    emissions_kg = round6(float(distance) * float(resolved))
    return success_payload(
        emissions_kg,
        factor=float(resolved),
        extra={
            "activity": activity,
            "vehicle_type": vehicle_type,
            "unit": unit,
            "fuel_type": fuel_type,
            "laden_level": laden_key,
            "uk_factor_basis": basis,
            "distance": distance,
            "quantity": distance,
        },
    )
