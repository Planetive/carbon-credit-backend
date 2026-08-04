"""
Leased assets — compose electricity + UK passenger/delivery + refrigerant (SPA LeasedAssetsSection).

Category totals:
  buildings / equipment / infrastructure electricity: spaElectricity
  transport rows: distance × factor round6
  infrastructure refrigerant: quantity × factor round6
  equipment = electricity + transport
  infrastructure = electricity + refrigerant
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ._common import round6, success_payload
from .electricity import calculate_electricity
from .uk_fuel import calculate_uk_fuel_emissions


def calculate_leased_electricity(**kwargs: Any) -> Dict[str, Any]:
    return calculate_electricity(**kwargs)


def calculate_leased_transport_row(
    *,
    distance: float,
    factor: float,
) -> Dict[str, Any]:
    emissions_kg = calculate_uk_fuel_emissions(distance, factor)
    return success_payload(
        emissions_kg, factor=float(factor), extra={"distance": distance}
    )


def calculate_leased_refrigerant(
    *,
    quantity: float,
    factor: float,
) -> Dict[str, Any]:
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

    # SPA displays category totals with toFixed(6) for electricity/refrigerant paths
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
