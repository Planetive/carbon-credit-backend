"""
Sold products processing / use — qty×factor plus Scope 3 electricity that
refuses placeholders and legacy other×kWh mixing.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ._common import fail_payload, round6, success_payload
from .scope3_grid_electricity import calculate_scope3_grid_electricity


def calculate_sold_products_qty_factor(
    *,
    quantity: float,
    factor: float,
) -> Dict[str, Any]:
    if quantity is None or factor is None:
        return fail_payload("quantity and factor required")
    if not (float(quantity) > 0):
        return fail_payload("quantity must be > 0")
    emissions_kg = round6(float(quantity) * float(factor))
    return success_payload(
        emissions_kg,
        factor=float(factor),
        extra={"quantity": quantity},
    )


def calculate_sold_products_electricity(
    *,
    total_kwh: float,
    grid_pct: Optional[float] = None,
    grid_factor: Optional[float] = None,
    other_pct: Optional[float] = None,
    other_row_emissions_sum: Optional[float] = None,
) -> Dict[str, Any]:
    return calculate_scope3_grid_electricity(
        total_kwh=total_kwh,
        grid_pct=grid_pct,
        grid_factor=grid_factor,
        other_pct=other_pct,
        other_row_emissions_sum=other_row_emissions_sum,
    )


def calculate_sold_products_hybrid(
    *,
    fuel_quantity: float,
    fuel_factor: float,
    total_kwh: float,
    grid_pct: Optional[float] = None,
    grid_factor: Optional[float] = None,
    other_pct: Optional[float] = None,
    other_row_emissions_sum: Optional[float] = None,
) -> Dict[str, Any]:
    fuel = calculate_sold_products_qty_factor(
        quantity=fuel_quantity, factor=fuel_factor
    )
    if not fuel.get("success"):
        return fuel
    elec = calculate_sold_products_electricity(
        total_kwh=total_kwh,
        grid_pct=grid_pct,
        grid_factor=grid_factor,
        other_pct=other_pct,
        other_row_emissions_sum=other_row_emissions_sum,
    )
    if not elec.get("success"):
        return elec
    fuel_kg = float(fuel["emissions_kg"])
    elec_kg = float(elec["emissions_kg"])
    emissions_kg = round6(fuel_kg + elec_kg)
    return success_payload(
        emissions_kg,
        factor=float(fuel_factor),
        extra={
            "fuel_emissions_kg": fuel_kg,
            "electricity_emissions_kg": elec_kg,
            "electricity": elec,
        },
    )
