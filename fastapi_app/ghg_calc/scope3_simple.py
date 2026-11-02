"""
Scope 3 simple explicit-factor calcs — Categories 1/2 spend, 4/9 freight,
6 business travel, 7 employee commuting.

Freight/spend/travel require verified factor units; refuse ambiguous units.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ._common import fail_payload, success_payload
from .scope3_factor_units import (
    annualize_commuting_distance_km,
    freight_emissions_kg,
    spend_emissions_kg,
    travel_distance_emissions_kg,
)


def calculate_freight(
    *,
    distance: float,
    weight: float,
    co2_factor: float,
    factor_unit: Optional[str] = None,
) -> Dict[str, Any]:
    emissions_kg, err = freight_emissions_kg(
        distance_km=float(distance),
        weight_kg=float(weight) if weight is not None else 0.0,
        co2_factor=float(co2_factor),
        factor_unit=factor_unit,
    )
    if err or emissions_kg is None:
        return fail_payload(err or "Freight calculation failed")
    return success_payload(
        emissions_kg,
        factor=float(co2_factor),
        extra={
            "distance": distance,
            "weight": weight,
            "factor_unit": factor_unit,
        },
    )


def calculate_business_travel(
    *,
    distance: float,
    co2_factor: float,
    unit: Optional[str] = None,
) -> Dict[str, Any]:
    emissions_kg, err = travel_distance_emissions_kg(
        distance_km=float(distance),
        co2_factor=float(co2_factor),
        factor_unit=unit,
    )
    if err or emissions_kg is None:
        return fail_payload(err or "Business travel calculation failed")
    return success_payload(
        emissions_kg,
        factor=float(co2_factor),
        extra={
            "distance": distance,
            "co2_factor": co2_factor,
            "unit": unit,
        },
    )


def calculate_employee_commuting(
    *,
    employees: float,
    distance: float,
    co2_factor: float,
    unit: Optional[str] = None,
    distance_basis: Optional[str] = None,
    working_days_per_year: Optional[float] = None,
) -> Dict[str, Any]:
    if not (employees > 0):
        return fail_payload("employees must be > 0")
    annual_km, err = annualize_commuting_distance_km(
        distance_km=float(distance),
        distance_basis=distance_basis,
        working_days_per_year=working_days_per_year,
    )
    if err or annual_km is None:
        return fail_payload(err or "Commuting distance annualization failed")
    trip_kg, err2 = travel_distance_emissions_kg(
        distance_km=annual_km,
        co2_factor=float(co2_factor),
        factor_unit=unit,
    )
    if err2 or trip_kg is None:
        return fail_payload(err2 or "Employee commuting calculation failed")
    emissions_kg = float(employees) * float(trip_kg)
    return success_payload(
        emissions_kg,
        factor=float(co2_factor),
        extra={
            "employees": employees,
            "distance": distance,
            "annual_distance_km": annual_km,
            "distance_basis": distance_basis or "annual_total",
            "working_days_per_year": working_days_per_year,
            "co2_factor": co2_factor,
            "unit": unit,
        },
    )


def calculate_spend_based(
    *,
    amount: float,
    emission_factor: float,
    factor_unit: Optional[str] = None,
    activity_currency: Optional[str] = None,
    activity_price_year: Optional[int] = None,
) -> Dict[str, Any]:
    emissions_kg, err = spend_emissions_kg(
        amount=float(amount),
        emission_factor=float(emission_factor),
        factor_unit=factor_unit,
        activity_currency=activity_currency,
        activity_price_year=activity_price_year,
    )
    if err or emissions_kg is None:
        return fail_payload(err or "Spend-based calculation failed")
    return success_payload(
        emissions_kg,
        factor=float(emission_factor),
        extra={
            "amount": amount,
            "factor_unit": factor_unit,
            "activity_currency": activity_currency,
            "activity_price_year": activity_price_year,
        },
    )
