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
        )
        assert r["emissions_kg"] == pytest.approx(
            case["expected_emissions_kg"], rel=1e-9, abs=1e-9
        ), case["id"]


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
        )
        assert r["emissions_kg"] == pytest.approx(
            case["expected_emissions_kg"], rel=1e-9, abs=1e-9
        ), case["id"]


def test_spend_based(golden):
    for case in golden["spend_based"]:
        r = calculate_spend_based(
            amount=case["amount"], emission_factor=case["emission_factor"]
        )
        assert r["emissions_kg"] == pytest.approx(
            case["expected_emissions_kg"], rel=1e-9, abs=1e-9
        ), case["id"]


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
