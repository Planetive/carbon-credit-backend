"""Parity tests for motor vehicle + sovereign PCAF calc (SPA-aligned)."""

from __future__ import annotations

import pytest

from fastapi_app.calculation_engine import CalculationEngine
from fastapi_app.finance_models import CompanyType
from fastapi_app.motor_vehicle_pcaf import (
    allocate_outstanding_per_vehicle,
    compute_motor_vehicle_pcaf_financed,
)


@pytest.fixture(scope="module")
def engine():
    return CalculationEngine()


def test_motor_formulas_include_3a_3b(engine):
    ids = {f.id for f in engine.formulas if f.category.value == "motor_vehicle_loan"}
    assert ids == {
        "1a-motor-vehicle",
        "1b-motor-vehicle",
        "2a-motor-vehicle",
        "2b-motor-vehicle",
        "3a-motor-vehicle",
        "3b-motor-vehicle",
    }
    scores = {
        f.option_code: f.data_quality_score
        for f in engine.formulas
        if f.category.value == "motor_vehicle_loan"
    }
    assert scores == {"1a": 1, "1b": 1, "2a": 2, "2b": 3, "3a": 4, "3b": 5}


def test_sovereign_formulas_include_3a_3b(engine):
    ids = {f.id for f in engine.formulas if f.category.value == "sovereign-debt"}
    assert "3a-sovereign-debt" in ids
    assert "3b-sovereign-debt" in ids
    scores = {
        f.option_code: f.data_quality_score
        for f in engine.formulas
        if f.category.value == "sovereign-debt"
    }
    assert scores["3a"] == 4
    assert scores["3b"] == 5


def test_allocate_outstanding_proportional():
    vehicles = [
        {"value_at_origination": 100, "emissions_tco2e": 1},
        {"value_at_origination": 300, "emissions_tco2e": 2},
    ]
    alloc = allocate_outstanding_per_vehicle(400, vehicles)
    assert alloc[0] == pytest.approx(100)
    assert alloc[1] == pytest.approx(300)


def test_motor_multi_vehicle_financed():
    vehicles = [
        {"id": "a", "name": "A", "value_at_origination": 1000, "emissions_tco2e": 10},
        {"id": "b", "name": "B", "value_at_origination": 3000, "emissions_tco2e": 30},
    ]
    # outstanding 2000 → A gets 500, B gets 1500 → financed = 0.5*10 + 0.5*30 = 20
    pcaf = compute_motor_vehicle_pcaf_financed(2000, vehicles)
    assert pcaf["total_financed_emissions"] == pytest.approx(20.0)


def test_engine_motor_3b_vehicle_entries(engine):
    result = engine.calculate(
        "3b-motor-vehicle",
        {
            "outstanding_amount": 2000,
            "vehicle_entries": [
                {
                    "id": "a",
                    "name": "A",
                    "value_at_origination": 1000,
                    "emissions_tco2e": 10,
                },
                {
                    "id": "b",
                    "name": "B",
                    "value_at_origination": 3000,
                    "emissions_tco2e": 30,
                },
            ],
        },
        CompanyType.PRIVATE,
    )
    assert result.financed_emissions == pytest.approx(20.0)
    assert result.data_quality_score == 5


def test_engine_motor_1a_legacy_aggregate(engine):
    # fuel 100 L × 0.002 tCO2e/L = 0.2; outstanding/value = 0.5 → financed 0.1
    result = engine.calculate(
        "1a-motor-vehicle",
        {
            "outstanding_amount": 500,
            "total_value_at_origination": 1000,
            "fuel_consumption": 100,
            "emission_factor": 0.002,
        },
        CompanyType.PRIVATE,
    )
    assert result.financed_emissions == pytest.approx(0.1)
    assert result.data_quality_score == 1


def test_engine_sovereign_3a_sector_revenue(engine):
    # attr = 1000/10000 = 0.1; intensity kg→t = 2/1000; sector = 5000*0.002 = 10; financed = 1
    result = engine.calculate(
        "3a-sovereign-debt",
        {
            "outstanding_amount": 1000,
            "pp_adjusted_gdp": 10000,
            "sector_revenue": 5000,
            "sector_intensity": 2,
            "sector_intensity_unit": "kgCO2e/PKR",
        },
        CompanyType.PRIVATE,
    )
    assert result.financed_emissions == pytest.approx(1.0)
    assert result.data_quality_score == 4


def test_engine_sovereign_3b_proxy(engine):
    # attr = 1000/10000 = 0.1; proxy intensity = 50/5000 = 0.01; country = 100; financed = 10
    result = engine.calculate(
        "3b-sovereign-debt",
        {
            "outstanding_amount": 1000,
            "pp_adjusted_gdp": 10000,
            "proxy_country_emissions": 50,
            "proxy_pp_adjusted_gdp": 5000,
        },
        CompanyType.PRIVATE,
    )
    assert result.financed_emissions == pytest.approx(10.0)
    assert result.data_quality_score == 5


def test_engine_sovereign_1a_alias_fields(engine):
    result = engine.calculate(
        "1a-sovereign-debt",
        {
            "outstanding_amount": 1000,
            "ppp_adjusted_gdp": 10000,
            "verified_emissions": 500,
        },
        CompanyType.PRIVATE,
    )
    assert result.financed_emissions == pytest.approx(50.0)
    assert result.data_quality_score == 1
