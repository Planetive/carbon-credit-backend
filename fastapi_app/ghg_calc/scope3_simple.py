"""
Scope 3 simple explicit-factor calcs — ported from SPA Scope3Section / category sections.

freight:           co2_factor × distance × weight
business_travel:   distance × factorPerKm  (mile factors ÷ 1.60934)
employee_commuting: employees × distance × factorPerKm
spend_based:       amount × emission_factor
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ._common import fail_payload, success_payload

MILES_TO_KM = 1.60934


def _factor_per_km(co2_factor: float, unit: Optional[str] = None) -> float:
    u = str(unit or "").lower()
    if "mile" in u:
        return float(co2_factor) / MILES_TO_KM
    return float(co2_factor)


def calculate_freight(
    *,
    distance: float,
    weight: float,
    co2_factor: float,
) -> Dict[str, Any]:
    if not (distance > 0 and weight > 0):
        return fail_payload("distance and weight must be > 0")
    emissions_kg = float(co2_factor) * float(distance) * float(weight)
    return success_payload(
        emissions_kg,
        factor=float(co2_factor),
        extra={"distance": distance, "weight": weight},
    )


def calculate_business_travel(
    *,
    distance: float,
    co2_factor: float,
    unit: Optional[str] = None,
) -> Dict[str, Any]:
    if not (distance > 0):
        return fail_payload("distance must be > 0")
    factor_per_km = _factor_per_km(co2_factor, unit)
    emissions_kg = float(distance) * factor_per_km
    return success_payload(
        emissions_kg,
        factor=factor_per_km,
        extra={
            "distance": distance,
            "co2_factor": co2_factor,
            "unit": unit,
            "factor_per_km": factor_per_km,
        },
    )


def calculate_employee_commuting(
    *,
    employees: float,
    distance: float,
    co2_factor: float,
    unit: Optional[str] = None,
) -> Dict[str, Any]:
    if not (distance > 0 and employees > 0):
        return fail_payload("employees and distance must be > 0")
    factor_per_km = _factor_per_km(co2_factor, unit)
    emissions_kg = float(employees) * float(distance) * factor_per_km
    return success_payload(
        emissions_kg,
        factor=factor_per_km,
        extra={
            "employees": employees,
            "distance": distance,
            "co2_factor": co2_factor,
            "unit": unit,
            "factor_per_km": factor_per_km,
        },
    )


def calculate_spend_based(
    *,
    amount: float,
    emission_factor: float,
) -> Dict[str, Any]:
    if not (amount > 0):
        return fail_payload("amount must be > 0")
    emissions_kg = float(amount) * float(emission_factor)
    return success_payload(
        emissions_kg,
        factor=float(emission_factor),
        extra={"amount": amount},
    )
