"""Stage 3 — Cats 6,7,8,10,11,13 travel units, commuting, leased/sold electricity."""

from __future__ import annotations

import pytest

from fastapi_app.ghg_calc.leased_assets import calculate_leased_electricity
from fastapi_app.ghg_calc.scope3_factor_units import (
    KM_PER_MILE,
    classify_travel_distance_unit,
)
from fastapi_app.ghg_calc.scope3_simple import (
    calculate_business_travel,
    calculate_employee_commuting,
)
from fastapi_app.ghg_calc.sold_products import (
    calculate_sold_products_electricity,
    calculate_sold_products_hybrid,
    calculate_sold_products_qty_factor,
)


def test_classify_passenger_vs_vehicle_mile():
    assert classify_travel_distance_unit("passenger-mile") == "passenger_mile"
    assert classify_travel_distance_unit("vehicle-mile") == "vehicle_mile"
    assert classify_travel_distance_unit("passenger-km") == "passenger_km"
    assert classify_travel_distance_unit("vehicle-km") == "vehicle_km"
    assert classify_travel_distance_unit("mile") is None


def test_business_travel_mile_km_conversion():
    mile = calculate_business_travel(
        distance=160.934, co2_factor=0.207, unit="passenger-mile"
    )
    # 160.934 km = 100 miles → 20.7 kg
    assert mile["success"] is True
    assert mile["emissions_kg"] == pytest.approx(0.207 * 100, rel=1e-9)

    km = calculate_business_travel(
        distance=100, co2_factor=0.15, unit="vehicle-km"
    )
    assert km["success"] is True
    assert km["emissions_kg"] == pytest.approx(15.0, rel=1e-9)


def test_business_travel_refuses_missing_unit():
    r = calculate_business_travel(distance=100, co2_factor=0.2, unit=None)
    assert r["success"] is False


def test_commuting_one_way_vs_round_trip():
    one_way = calculate_employee_commuting(
        employees=1,
        distance=10,
        co2_factor=0.2,
        unit="kg CO2e/km",
        distance_basis="one_way",
        working_days_per_year=100,
    )
    round_trip = calculate_employee_commuting(
        employees=1,
        distance=20,
        co2_factor=0.2,
        unit="kg CO2e/km",
        distance_basis="round_trip",
        working_days_per_year=100,
    )
    assert one_way["success"] and round_trip["success"]
    # one_way 10km × 2 × 100 × 0.2 = 400; round_trip 20 × 100 × 0.2 = 400
    assert one_way["emissions_kg"] == pytest.approx(400.0)
    assert round_trip["emissions_kg"] == pytest.approx(400.0)
    assert one_way["emissions_kg"] == pytest.approx(round_trip["emissions_kg"])


def test_commuting_does_not_auto_double_round_trip():
    r = calculate_employee_commuting(
        employees=1,
        distance=15,
        co2_factor=0.1,
        unit="kg CO2e/km",
        distance_basis="round_trip",
        working_days_per_year=10,
    )
    assert r["emissions_kg"] == pytest.approx(15.0)  # not 30


def test_commuting_requires_days_for_one_way():
    r = calculate_employee_commuting(
        employees=1,
        distance=10,
        co2_factor=0.1,
        unit="kg CO2e/km",
        distance_basis="one_way",
    )
    assert r["success"] is False


def test_leased_electricity_refuses_placeholders():
    for factor in (0.4041, 0.425, 0.17355):
        r = calculate_leased_electricity(
            total_kwh=1000, grid_pct=100, grid_factor=factor
        )
        assert r["success"] is False, factor


def test_leased_electricity_refuses_other_mixing():
    r = calculate_leased_electricity(
        total_kwh=1000,
        grid_pct=80,
        grid_factor=0.2,
        other_pct=20,
        other_row_emissions_sum=0.5,
    )
    assert r["success"] is False


def test_leased_electricity_accepts_verified_factor():
    r = calculate_leased_electricity(
        total_kwh=1000, grid_pct=100, grid_factor=0.177
    )
    assert r["success"] is True
    assert r["emissions_kg"] == pytest.approx(177.0)


def test_sold_products_electricity_refuses_missing_factor():
    r = calculate_sold_products_electricity(total_kwh=500, grid_pct=100)
    assert r["success"] is False


def test_sold_products_qty_and_tco2e():
    r = calculate_sold_products_qty_factor(quantity=2.5, factor=400)
    assert r["success"] is True
    assert r["emissions_kg"] == pytest.approx(1000.0)
    assert r["emissions_tco2e"] == pytest.approx(1.0)


def test_sold_products_hybrid_blocks_placeholder_elec():
    r = calculate_sold_products_hybrid(
        fuel_quantity=10,
        fuel_factor=2.0,
        total_kwh=100,
        grid_pct=100,
        grid_factor=0.4041,
    )
    assert r["success"] is False


def test_mile_conversion_constant():
    assert KM_PER_MILE == pytest.approx(1.60934)
