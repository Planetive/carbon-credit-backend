"""Parity tests for commercial real estate + mortgage PCAF calc."""

from __future__ import annotations

import pytest

from fastapi_app.calculation_engine import CalculationEngine
from fastapi_app.finance_models import CompanyType


@pytest.fixture(scope="module")
def engine():
    return CalculationEngine()


def test_cre_formulas_include_option_3(engine):
    scores = {
        f.option_code: f.data_quality_score
        for f in engine.formulas
        if f.category.value == "commercial_real_estate"
    }
    assert scores == {"1a": 1, "1b": 2, "2a": 3, "2b": 4, "3": 5}
    assert engine.get_formula_by_id("3-commercial-real-estate") is not None


def test_mortgage_formulas_include_option_3(engine):
    scores = {
        f.option_code: f.data_quality_score
        for f in engine.formulas
        if f.category.value == "mortgage"
    }
    assert scores == {"1a": 1, "1b": 2, "2a": 3, "2b": 4, "3": 5}
    assert engine.get_formula_by_id("3-mortgage") is not None


def test_cre_1a_energy_times_ef(engine):
    # attr = 1000/10000 = 0.1; emissions = 5000*0.002 = 10; financed = 1
    result = engine.calculate(
        "1a-commercial-real-estate",
        {
            "outstanding_amount": 1000,
            "property_value_at_origination": 10000,
            "energy_consumption": 5000,
            "emission_factor": 0.002,
        },
        CompanyType.PRIVATE,
    )
    assert result.financed_emissions == pytest.approx(1.0)
    assert result.data_quality_score == 1


def test_cre_legacy_field_aliases(engine):
    result = engine.calculate(
        "1a-commercial-real-estate",
        {
            "outstanding_amount": 1000,
            "property_value_at_origination": 10000,
            "actual_energy_consumption": 5000,
            "supplier_specific_emission_factor": 0.002,
        },
        CompanyType.PRIVATE,
    )
    assert result.financed_emissions == pytest.approx(1.0)


def test_cre_2a_labels_floor_area(engine):
    # attr 0.1; energy = 100*50 = 5000; emissions = 10; financed = 1
    result = engine.calculate(
        "2a-commercial-real-estate",
        {
            "outstanding_amount": 1000,
            "property_value_at_origination": 10000,
            "estimated_energy_consumption_from_labels": 100,
            "floor_area": 50,
            "average_emission_factor": 0.002,
        },
        CompanyType.PRIVATE,
    )
    assert result.financed_emissions == pytest.approx(1.0)
    assert result.data_quality_score == 3


def test_cre_3_buildings(engine):
    # attr 0.1; energy = 2000*5 = 10000; emissions = 20; financed = 2
    result = engine.calculate(
        "3-commercial-real-estate",
        {
            "outstanding_amount": 1000,
            "property_value_at_origination": 10000,
            "estimated_energy_consumption_from_statistics": 2000,
            "number_of_buildings": 5,
            "average_emission_factor": 0.002,
        },
        CompanyType.PRIVATE,
    )
    assert result.financed_emissions == pytest.approx(2.0)
    assert result.data_quality_score == 5


def test_mortgage_2b_score_and_math(engine):
    result = engine.calculate(
        "2b-mortgage",
        {
            "outstanding_amount": 1000,
            "property_value_at_origination": 10000,
            "estimated_energy_consumption_from_statistics": 10,
            "floor_area": 100,
            "average_emission_factor": 0.002,
        },
        CompanyType.PRIVATE,
    )
    # energy 1000, emissions 2, financed 0.2
    assert result.financed_emissions == pytest.approx(0.2)
    assert result.data_quality_score == 4


def test_mortgage_3(engine):
    result = engine.calculate(
        "3-mortgage",
        {
            "outstanding_amount": 2000,
            "property_value_at_origination": 10000,
            "estimated_energy_consumption_from_statistics": 1000,
            "number_of_buildings": 2,
            "average_emission_factor": 0.001,
        },
        CompanyType.PRIVATE,
    )
    # attr 0.2; energy 2000; emissions 2; financed 0.4
    assert result.financed_emissions == pytest.approx(0.4)
    assert result.data_quality_score == 5
