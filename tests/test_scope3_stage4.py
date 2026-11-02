"""Stage 4 — Cat 3 refuse, spend currency/year gates, category readiness helpers."""

from __future__ import annotations

import pytest

from fastapi_app.ghg_calc.scope3_category3 import (
    CATEGORY3_REQUIRED_DATASETS,
    calculate_category3_fuel_energy,
)
from fastapi_app.ghg_calc.scope3_simple import calculate_spend_based


def test_category3_always_refuses_manual_and_missing_datasets():
    r = calculate_category3_fuel_energy(method="manual_kg")
    assert r["success"] is False
    assert r["emissions_kg"] is None
    assert "WTT" in (r.get("error") or "") or "unavailable" in (r.get("error") or "").lower()
    assert len(CATEGORY3_REQUIRED_DATASETS) >= 2


def test_category3_does_not_accept_scope1_or_scope2_reuse_kwargs():
    r = calculate_category3_fuel_energy(
        method="reuse_scope2_grid",
        grid_factor=0.177,
        fuel_combustion_factor=2.0,
    )
    assert r["success"] is False


def test_spend_requires_matching_usd_2022():
    ok = calculate_spend_based(
        amount=1000,
        emission_factor=0.488,
        factor_unit="kg CO2e/2022 USD, purchaser price",
        activity_currency="USD",
        activity_price_year=2022,
    )
    assert ok["success"] is True
    assert ok["emissions_kg"] == pytest.approx(488.0)


def test_spend_refuses_pkr_without_fx():
    r = calculate_spend_based(
        amount=1000,
        emission_factor=0.488,
        factor_unit="kg CO2e/2022 USD, purchaser price",
        activity_currency="PKR",
        activity_price_year=2022,
    )
    assert r["success"] is False


def test_spend_refuses_other_price_year_without_inflation():
    r = calculate_spend_based(
        amount=1000,
        emission_factor=0.488,
        factor_unit="kg CO2e/2022 USD, purchaser price",
        activity_currency="USD",
        activity_price_year=2024,
    )
    assert r["success"] is False


def test_spend_refuses_missing_currency_or_year():
    r = calculate_spend_based(
        amount=1000,
        emission_factor=0.488,
        factor_unit="kg CO2e/2022 USD, purchaser price",
    )
    assert r["success"] is False
