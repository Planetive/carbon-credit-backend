"""
EPA mobile combustion — ported from SPA MobileFuelEmissions / localMobileFuelEmissionsKg.

Formula:
  if input_unit starts with liter/litre:
    qty = quantity / 3.78541
  else:
    qty = quantity
  emissions_kg = Number((qty * factor).toFixed(6))
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ._common import fail_payload, norm_cell, parse_number, round6, success_payload

LITERS_PER_GALLON = 3.78541


def build_mobile_options(table_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Flat list {fuel_type, unit, factor} from Mobile Combustion sheet."""
    options: List[Dict[str, Any]] = []
    for row in table_rows:
        fuel_type = norm_cell(
            row.get("Fuel Type")
            or row.get("FuelType")
            or row.get("fuel_type")
            or row.get("fuelType")
        )
        unit = norm_cell(row.get("Unit") or row.get("unit") or "unit") or "unit"
        kg = parse_number(
            row.get("kg CO2 per unit")
            or row.get("kg co2 per unit")
            or row.get("kg_co2_per_unit")
            or row.get("kgCo2PerUnit")
        )
        if not fuel_type or kg is None:
            continue
        options.append({"fuel_type": fuel_type, "unit": unit, "factor": kg})
    return options


def resolve_mobile_factor(
    options: List[Dict[str, Any]], fuel_type: str
) -> Optional[Dict[str, Any]]:
    for opt in options:
        if opt["fuel_type"] == fuel_type:
            return opt
    return None


def calculate_mobile_fuel(
    *,
    quantity: float,
    fuel_type: Optional[str] = None,
    unit: Optional[str] = None,
    input_unit: Optional[str] = None,
    factor: Optional[float] = None,
    options: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    resolved_factor = factor
    resolved_unit = unit

    if resolved_factor is None and options and fuel_type:
        opt = resolve_mobile_factor(options, fuel_type)
        if opt:
            resolved_factor = opt["factor"]
            resolved_unit = resolved_unit or opt["unit"]

    if resolved_factor is None:
        return fail_payload("Could not resolve mobile combustion factor")

    # SPA localMobileFuelEmissionsKg: conversion driven only by input_unit
    # (liter/litre → /3.78541). Does not require factor unit to contain "gallon".
    iu_raw = input_unit
    iu = str(iu_raw or "").lower()
    if iu.startswith("liter") or iu.startswith("litre"):
        effective = float(quantity) / LITERS_PER_GALLON
    else:
        effective = float(quantity)

    emissions_kg = round6(effective * float(resolved_factor))
    return success_payload(
        emissions_kg,
        factor=float(resolved_factor),
        extra={
            "fuel_type": fuel_type,
            "unit": resolved_unit,
            "input_unit": iu_raw,
            "quantity": quantity,
            "effective_quantity": effective,
        },
    )
