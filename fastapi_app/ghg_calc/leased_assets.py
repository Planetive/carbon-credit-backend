"""
Leased assets (Cat 8 / 13) — transport/refrigerant qty×factor; electricity via
Scope 3 grid helper that refuses placeholders and legacy mixing.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ._common import fail_payload, round6, success_payload
from .scope3_grid_electricity import calculate_scope3_grid_electricity
from .uk_fuel import calculate_uk_fuel_emissions


def calculate_leased_electricity(**kwargs: Any) -> Dict[str, Any]:
    return calculate_scope3_grid_electricity(**kwargs)


def calculate_leased_transport_row(
    *,
    distance: float,
    factor: float,
) -> Dict[str, Any]:
    if not (distance > 0) or factor is None:
        return fail_payload("leased transport requires distance > 0 and factor")
    emissions_kg = calculate_uk_fuel_emissions(distance, factor)
    return success_payload(
        emissions_kg, factor=float(factor), extra={"distance": distance}
    )


def calculate_leased_refrigerant(
    *,
    quantity: float,
    factor: float,
) -> Dict[str, Any]:
    """
    Explicit quantity × verified GWP/factor only. Does not call Scope 1 leakage
    engines; callers must supply a verified factor for the leased boundary.
    """
    if not (quantity > 0) or factor is None:
        return fail_payload("leased refrigerant requires quantity > 0 and factor")
    emissions_kg = calculate_uk_fuel_emissions(quantity, factor)
    return success_payload(
        emissions_kg, factor=float(factor), extra={"quantity": quantity}
    )


def calculate_leased_category_total(
    *,
    category: str,
    electricity_kg: Optional[float] = None,
    transport_rows_kg: Optional[List[float]] = None,
    refrigerant_kg: Optional[float] = None,
) -> Dict[str, Any]:
    cat = (category or "").lower()
    elec = float(electricity_kg or 0)
    transport = sum(float(x) for x in (transport_rows_kg or []))
    refrig = float(refrigerant_kg or 0)

    if cat in ("buildings", "building"):
        total = elec
    elif cat in ("transport",):
        total = transport
    elif cat in ("equipment",):
        total = elec + transport
    elif cat in ("infrastructure",):
        total = elec + refrig
    else:
        total = elec + transport + refrig

    emissions_kg = round6(total) if cat != "transport" else float(total)
    if cat in ("buildings", "equipment", "infrastructure"):
        emissions_kg = round6(total)

    return success_payload(
        emissions_kg,
        extra={
            "category": category,
            "electricity_kg": elec,
            "transport_kg": transport,
            "refrigerant_kg": refrig,
        },
    )
