"""
Phase 3A — PCAF formula inventory, frontend/backend parity, and validation.

Sample inputs: tests/fixtures/pcaf_phase3a_parity.json
Expected values are independently computed from PCAF 2nd edition (Dec 2022) formulas.
Matching frontend output is not treated as proof of PCAF compliance.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fastapi_app.calculation_engine import CalculationEngine
from fastapi_app.finance_models import (
    CompanyType,
    FormulaCategory,
    FormulaConfig,
    FormulaInput,
    FormulaInputType,
)
from fastapi_app.shared_formula_utils import calculate_financed_emissions

FIXTURES = Path(__file__).parent / "fixtures" / "pcaf_phase3a_parity.json"

# Independently computed from the documented sample:
# EVIC=3e6, equity+debt=5e6, project=1e7, intensity=0.0005 tCO2e/PKR
EQUITY_PROJECT_CASES = [
    ("1a-listed-equity", "listed", 1 / 3, 50000 / 3, 1),
    ("1b-listed-equity", "listed", 1 / 3, 20000.0, 2),
    ("2a-listed-equity", "listed", 1 / 3, 410 / 3, 2),
    ("2b-listed-equity", "listed", 1 / 3, 200 / 3, 3),
    ("3a-listed-equity", "listed", 1 / 3, 4000 / 3, 4),
    ("3c-listed-equity", "listed", 1.0, 400.0, 5),
    ("1a-unlisted-equity", "private", 0.2, 10000.0, 1),
    ("1b-unlisted-equity", "private", 0.2, 12000.0, 2),
    ("2a-unlisted-equity", "private", 0.2, 82.0, 2),
    ("2b-unlisted-equity", "private", 0.2, 40.0, 3),
    ("3a-unlisted-equity", "private", 0.2, 800.0, 4),
    ("3c-unlisted-equity", "private", 1.0, 400.0, 5),
    ("1a-project-finance", "private", 0.1, 5000.0, 1),
    ("1b-project-finance", "private", 0.1, 6000.0, 2),
    ("2a-project-finance", "private", 0.1, 41.0, 2),
    ("2b-project-finance", "private", 0.1, 20.0, 3),
    ("3a-project-finance", "private", 0.1, 400.0, 4),
    ("3c-project-finance", "private", 1.0, 400.0, 5),
]

# Facilitated 2a uses process_emissions=0 in these cases (see remaining-issue note).
FACILITATED_CASES = [
    ("1a-facilitated-verified-listed", "listed", 1 / 6, 2750.0, 1),
    ("1a-facilitated-verified-unlisted", "private", 0.1, 1650.0, 1),
    ("1b-facilitated-unverified-listed", "listed", 1 / 6, 3300.0, 2),
    ("1b-facilitated-unverified-unlisted", "private", 0.1, 1980.0, 2),
    ("2a-facilitated-energy-listed", "listed", 1 / 6, 22.0, 2),
    ("2a-facilitated-energy-unlisted", "private", 0.1, 13.2, 2),
    ("2b-facilitated-production-listed", "listed", 1 / 6, 11.0, 3),
    ("2b-facilitated-production-unlisted", "private", 0.1, 6.6, 3),
    ("3a-facilitated-revenue-listed", "listed", 1 / 6, 220.0, 4),
    ("3a-facilitated-revenue-unlisted", "private", 0.1, 132.0, 4),
    ("3c-facilitated-atr-listed", "listed", 1.0, 66.0, 5),
    ("3c-facilitated-atr-unlisted", "private", 1.0, 66.0, 5),
]

EXPECTED_SCORES = {
    "listed_equity": {"1a": 1, "1b": 2, "2a": 2, "2b": 3, "3a": 4, "3c": 5},
    "business_loans": {"1a": 1, "1b": 2, "2a": 2, "2b": 3, "3a": 4, "3c": 5},
    "project_finance": {"1a": 1, "1b": 2, "2a": 2, "2b": 3, "3a": 4, "3c": 5},
    "facilitated_emission": {"1a": 1, "1b": 2, "2a": 2, "2b": 3, "3a": 4, "3c": 5},
    "commercial_real_estate": {"1a": 1, "1b": 2, "2a": 3, "2b": 4, "3": 5},
    "mortgage": {"1a": 1, "1b": 2, "2a": 3, "2b": 4, "3": 5},
    "motor_vehicle_loan": {"1a": 1, "1b": 1, "2a": 2, "2b": 3, "3a": 4, "3b": 5},
    "sovereign-debt": {"1a": 1, "1b": 2, "2a": 3, "3a": 4, "3b": 5},
}


@pytest.fixture(scope="module")
def engine():
    return CalculationEngine()


@pytest.fixture(scope="module")
def sample():
    with FIXTURES.open(encoding="utf-8") as f:
        return json.load(f)["sample"]


def _company_type(value: str) -> CompanyType:
    return CompanyType.LISTED if value == "listed" else CompanyType.PRIVATE


def _equity_inputs(sample: dict, include_process: bool) -> dict:
    data = dict(sample)
    if not include_process:
        data["process_emissions"] = 0
    return data


def test_formula_inventory_and_data_quality_scores(engine):
    by_category: dict[str, dict[str, int]] = {}
    for formula in engine.formulas:
        by_category.setdefault(formula.category.value, {})[formula.option_code] = (
            formula.data_quality_score
        )
    for category, expected in EXPECTED_SCORES.items():
        assert by_category[category] == expected, category


def test_option_3b_not_implemented_for_equity_project_facilitated(engine):
    ids = {f.id for f in engine.formulas}
    assert "3b-listed-equity" not in ids
    assert "3b-unlisted-equity" not in ids
    assert "3b-project-finance" not in ids
    assert not any(
        f.category.value in {"listed_equity", "business_loans", "project_finance", "facilitated_emission"}
        and f.option_code == "3b"
        for f in engine.formulas
    )


@pytest.mark.parametrize(
    "formula_id,company_type,attr,emissions,score",
    EQUITY_PROJECT_CASES,
    ids=[c[0] for c in EQUITY_PROJECT_CASES],
)
def test_equity_project_formula_parity(
    engine, sample, formula_id, company_type, attr, emissions, score
):
    include_process = formula_id.startswith("2a-")
    result = engine.calculate(
        formula_id, _equity_inputs(sample, include_process), _company_type(company_type)
    )
    assert result.attribution_factor == pytest.approx(attr, rel=1e-9, abs=1e-9)
    assert result.financed_emissions == pytest.approx(emissions, rel=1e-9, abs=1e-9)
    assert result.data_quality_score == score


@pytest.mark.parametrize(
    "formula_id,company_type,attr,emissions,score",
    FACILITATED_CASES,
    ids=[c[0] for c in FACILITATED_CASES],
)
def test_facilitated_formula_parity(
    engine, sample, formula_id, company_type, attr, emissions, score
):
    inputs = _equity_inputs(sample, include_process=False)
    result = engine.calculate(formula_id, inputs, _company_type(company_type))
    assert result.attribution_factor == pytest.approx(attr, rel=1e-9, abs=1e-9)
    assert result.financed_emissions == pytest.approx(emissions, rel=1e-9, abs=1e-9)
    assert result.data_quality_score == score


def test_facilitated_2a_process_emissions_are_attributed(engine, sample):
    """PCAF: add process emissions to company energy emissions, then attribute."""
    inputs = _equity_inputs(sample, include_process=True)
    result = engine.calculate(
        "2a-facilitated-energy-listed", inputs, CompanyType.LISTED
    )
    # energy 410; AF 1/6; weighting 0.33 → 22.55
    assert result.financed_emissions == pytest.approx((1 / 6) * 0.33 * 410, rel=1e-9)


def test_project_finance_uses_project_denominator_even_if_listed(engine, sample):
    result = engine.calculate(
        "1a-project-finance",
        _equity_inputs(sample, include_process=False),
        CompanyType.LISTED,
    )
    assert result.attribution_factor == pytest.approx(0.1)
    assert result.financed_emissions == pytest.approx(5000.0)


def test_kg_and_tco2e_sector_intensity_are_equivalent(engine, sample):
    kg_inputs = _equity_inputs(sample, False)
    t_inputs = dict(kg_inputs)
    t_inputs["sector_intensity"] = 0.0005
    t_inputs["sector_intensity_unit"] = "tCO2e/PKR"
    kg = engine.calculate("3a-listed-equity", kg_inputs, CompanyType.LISTED)
    tonnes = engine.calculate("3a-listed-equity", t_inputs, CompanyType.LISTED)
    assert kg.financed_emissions == pytest.approx(tonnes.financed_emissions, rel=1e-9)
    assert kg.financed_emissions == pytest.approx(4000 / 3, rel=1e-9)


def test_zero_emissions_yield_zero_financed(engine, sample):
    inputs = _equity_inputs(sample, False)
    inputs["verified_emissions"] = 0
    result = engine.calculate("1a-listed-equity", inputs, CompanyType.LISTED)
    assert result.financed_emissions == pytest.approx(0.0)
    assert result.attribution_factor == pytest.approx(1 / 3)


def test_missing_denominator_is_rejected(engine, sample):
    inputs = {
        "outstanding_amount": 1000,
        "verified_emissions": 50,
        "share_price": 0,
        "outstanding_shares": 0,
        "total_debt": 0,
        "evic": 0,
        "total_assets": 10000,
    }
    with pytest.raises(ValueError, match="EVIC"):
        engine.calculate("1a-listed-equity", inputs, CompanyType.LISTED)


def test_zero_denominator_helper_is_rejected():
    with pytest.raises(ValueError, match="greater than zero"):
        calculate_financed_emissions(100, 0, 50)


def test_unsupported_option_code_is_rejected(engine):
    dummy = FormulaConfig(
        id="3b-listed-equity",
        name="Unsupported",
        description="Not implemented",
        category=FormulaCategory.LISTED_EQUITY,
        option_code="3b",
        data_quality_score=5,
        inputs=[
            FormulaInput(
                name="outstanding_amount",
                label="Outstanding",
                type=FormulaInputType.NUMBER,
                required=True,
            )
        ],
    )
    with pytest.raises(ValueError, match="Unsupported PCAF option"):
        engine._company_emissions(dummy, {})
    with pytest.raises(ValueError, match="not found"):
        engine.calculate("3b-listed-equity", {"outstanding_amount": 1}, CompanyType.LISTED)


def test_invalid_negative_outstanding_is_rejected(engine, sample):
    inputs = _equity_inputs(sample, False)
    inputs["outstanding_amount"] = -1
    with pytest.raises(ValueError, match="Validation failed"):
        engine.calculate("1a-listed-equity", inputs, CompanyType.LISTED)


def test_option_3a_rejects_zero_revenue(engine, sample):
    inputs = _equity_inputs(sample, False)
    inputs["company_revenue"] = 0
    with pytest.raises(ValueError, match="revenue"):
        engine.calculate("3a-listed-equity", inputs, CompanyType.LISTED)


def test_option_3c_rejects_zero_atr(engine, sample):
    inputs = _equity_inputs(sample, False)
    inputs["asset_turnover_ratio"] = 0
    with pytest.raises(ValueError, match="asset turnover"):
        engine.calculate("3c-listed-equity", inputs, CompanyType.LISTED)


def test_option_2b_accepts_emission_factor_alias(engine, sample):
    inputs = _equity_inputs(sample, False)
    inputs.pop("production_emission_factor", None)
    result = engine.calculate("2b-listed-equity", inputs, CompanyType.LISTED)
    assert result.financed_emissions == pytest.approx(200 / 3)


def test_cre_mortgage_motor_sovereign_supported_options(engine):
    """Every remaining asset-class/method combination is registered and runnable."""
    cre_1a = engine.calculate(
        "1a-commercial-real-estate",
        {
            "outstanding_amount": 1000,
            "property_value_at_origination": 10000,
            "energy_consumption": 5000,
            "emission_factor": 0.002,
        },
        CompanyType.PRIVATE,
    )
    assert cre_1a.financed_emissions == pytest.approx(1.0)
    assert cre_1a.data_quality_score == 1

    mortgage_1b = engine.calculate(
        "1b-mortgage",
        {
            "outstanding_amount": 1000,
            "property_value_at_origination": 10000,
            "energy_consumption": 5000,
            "emission_factor": 0.002,
        },
        CompanyType.PRIVATE,
    )
    assert mortgage_1b.financed_emissions == pytest.approx(1.0)
    assert mortgage_1b.data_quality_score == 2

    motor_2a = engine.calculate(
        "2a-motor-vehicle",
        {
            "outstanding_amount": 2000,
            "vehicle_entries": [
                {"id": "a", "name": "A", "value_at_origination": 1000, "emissions_tco2e": 10},
                {"id": "b", "name": "B", "value_at_origination": 3000, "emissions_tco2e": 30},
            ],
        },
        CompanyType.PRIVATE,
    )
    assert motor_2a.financed_emissions == pytest.approx(20.0)
    assert motor_2a.data_quality_score == 2

    sovereign_2a = engine.calculate(
        "2a-sovereign-debt",
        {
            "outstanding_amount": 1000,
            "pp_adjusted_gdp": 10000,
            "energy_consumption": 5000,
            "emission_factor": 0.002,
        },
        CompanyType.PRIVATE,
    )
    assert sovereign_2a.financed_emissions == pytest.approx(1.0)
    assert sovereign_2a.data_quality_score == 3
