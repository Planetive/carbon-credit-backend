"""
Sold products processing / use — explicit-factor ports from SPA helpers.

Processing fuel row: quantity × factor (round6)
Use ICE / fuels / refrigerant: quantity × factor (round6)
Electricity mix for sold products (use path, no ÷totalKwh on other):
  grid = (grid_pct/100)*total_kwh*grid_factor
  other = (other_pct/100)*total_kwh*other_row_emissions_sum
  total = round6(grid+other)
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ._common import fail_payload, round6, success_payload
from .electricity import calculate_electricity


def calculate_sold_products_qty_factor(
    *,
    quantity: float,
    factor: float,
) -> Dict[str, Any]:
    """Shared: Number((quantity * factor).toFixed(6))."""
    if quantity is None or factor is None:
        return fail_payload("quantity and factor required")
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
    """Use-of-sold-products electricity path (same shape as leased/scope2 spaMath)."""
    return calculate_electricity(
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
    """Hybrid use: fuel qty×factor + electricity mix; sum round6."""
    fuel_kg = round6(float(fuel_quantity) * float(fuel_factor))
    elec = calculate_electricity(
        total_kwh=total_kwh,
        grid_pct=grid_pct,
        grid_factor=grid_factor,
        other_pct=other_pct,
        other_row_emissions_sum=other_row_emissions_sum,
    )
    elec_kg = float(elec["emissions_kg"] or 0)
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
