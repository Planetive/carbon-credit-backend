"""Batch 2 Scope 3 golden parity (fixtures until synced to SPA cases.json)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fastapi_app.ghg_calc.leased_assets import (
    calculate_leased_category_total,
    calculate_leased_transport_row,
)
from fastapi_app.ghg_calc.scope3_simple import (
    calculate_business_travel,
    calculate_employee_commuting,
    calculate_freight,
    calculate_spend_based,
)
from fastapi_app.ghg_calc.sold_products import calculate_sold_products_qty_factor

FIXTURES = Path(__file__).parent / "fixtures" / "scope3_batch2_golden.json"


@pytest.fixture(scope="module")
def golden():
    with FIXTURES.open(encoding="utf-8") as f:
        return json.load(f)


def test_freight(golden):
    for case in golden["freight"]:
        r = calculate_freight(
            distance=case["distance"],
            weight=case["weight"],
            co2_factor=case["co2_factor"],
            factor_unit=case.get("factor_unit"),
        )
        assert r["success"] is True, case["id"]
        assert r["emissions_kg"] == pytest.approx(
            case["expected_emissions_kg"], rel=1e-9, abs=1e-9
        ), case["id"]


def test_freight_refuses_missing_unit():
    r = calculate_freight(distance=100, weight=50, co2_factor=0.12)
    assert r["success"] is False
    assert r["emissions_kg"] is None


def test_freight_1000kg_is_not_one_short_ton():
    """Regression: 1000 kg must not be treated as 1 short ton or 1 tonne."""
    r = calculate_freight(
        distance=100,
        weight=1000,
        co2_factor=1.0,
        factor_unit="short ton-mile",
    )
    assert r["success"] is True
    # 1 short ton at 100 km would be 1.0 * (100/1.60934) * 1 ≈ 62.14
    one_short_ton = 1.0 * (100 / 1.60934)
    assert r["emissions_kg"] != pytest.approx(one_short_ton, rel=1e-6)
    # 1 tonne at 100 km would be wrong if mis-applied as short ton
    assert r["emissions_kg"] == pytest.approx(
        1.0 * (100 / 1.60934) * (1000 / 907.18474), rel=1e-9
    )


def test_business_travel(golden):
    for case in golden["business_travel"]:
        r = calculate_business_travel(
            distance=case["distance"],
            co2_factor=case["co2_factor"],
            unit=case.get("unit"),
        )
        assert r["emissions_kg"] == pytest.approx(
            case["expected_emissions_kg"], rel=1e-9, abs=1e-9
        ), case["id"]


def test_employee_commuting(golden):
    for case in golden["employee_commuting"]:
        r = calculate_employee_commuting(
            employees=case["employees"],
            distance=case["distance"],
            co2_factor=case["co2_factor"],
            unit=case.get("unit"),
            distance_basis=case.get("distance_basis"),
            working_days_per_year=case.get("working_days_per_year"),
        )
        assert r["success"] is True, case["id"]
        assert r["emissions_kg"] == pytest.approx(
            case["expected_emissions_kg"], rel=1e-9, abs=1e-9
        ), case["id"]


def test_spend_based(golden):
    for case in golden["spend_based"]:
        r = calculate_spend_based(
            amount=case["amount"],
            emission_factor=case["emission_factor"],
            factor_unit=case.get("factor_unit"),
            activity_currency=case.get("activity_currency"),
            activity_price_year=case.get("activity_price_year"),
        )
        assert r["success"] is True, case["id"]
        assert r["emissions_kg"] == pytest.approx(
            case["expected_emissions_kg"], rel=1e-9, abs=1e-9
        ), case["id"]


def test_spend_based_refuses_missing_unit():
    r = calculate_spend_based(
        amount=1000,
        emission_factor=0.35,
        activity_currency="USD",
        activity_price_year=2022,
    )
    assert r["success"] is False
    assert r["emissions_kg"] is None


def test_sold_products(golden):
    for case in golden["sold_products"]:
        r = calculate_sold_products_qty_factor(
            quantity=case["quantity"], factor=case["factor"]
        )
        assert r["emissions_kg"] == pytest.approx(
            case["expected_emissions_kg"], rel=1e-9, abs=1e-9
        ), case["id"]


def test_leased(golden):
    for case in golden["leased"]:
        if "distance" in case:
            r = calculate_leased_transport_row(
                distance=case["distance"], factor=case["factor"]
            )
        else:
            r = calculate_leased_category_total(
                category=case["category"],
                electricity_kg=case.get("electricity_kg"),
                transport_rows_kg=case.get("transport_rows_kg"),
                refrigerant_kg=case.get("refrigerant_kg"),
            )
        assert r["emissions_kg"] == pytest.approx(
            case["expected_emissions_kg"], rel=1e-9, abs=1e-9
        ), case["id"]
