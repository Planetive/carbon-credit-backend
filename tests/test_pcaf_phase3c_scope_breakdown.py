"""Phase 3C financed Scope 1/2/3 breakdown."""

from __future__ import annotations

import pytest

from fastapi_app.calculation_engine import CalculationEngine
from fastapi_app.finance_models import CompanyType
from fastapi_app.financed_scope_breakdown import (
    build_scope_breakdown,
    optional_number,
)


@pytest.fixture
def engine():
    return CalculationEngine()


def listed_inputs(**extra):
    base = {
        "outstanding_amount": 1_000_000,
        "share_price": 10,
        "outstanding_shares": 100_000,
        "total_debt": 2_000_000,
        "minority_interest": 0,
        "preferred_stock": 0,
        "total_assets": 10_000_000,
        "evic": 3_000_000,
    }
    base.update(extra)
    return base


def test_optional_number_keeps_zero_and_missing():
    assert optional_number({"scope3_emissions": 0}, "scope3_emissions") == 0.0
    assert optional_number({}, "scope3_emissions") is None
    assert optional_number({"scope3_emissions": None}, "scope3_emissions") is None


def test_1_scope1_only(engine):
    result = engine.calculate(
        "1a-listed-equity",
        listed_inputs(scope1_emissions=90, verified_emissions=90),
        CompanyType.LISTED,
    )
    bd = result.metadata["scope_breakdown"]
    assert bd["financed_scope1_tco2e"] == pytest.approx(result.financed_emissions)
    assert bd["financed_scope2_tco2e"] is None
    assert bd["financed_scope3_tco2e"] is None
    assert bd["missing_scopes"] == ["scope2", "scope3"]
    assert result.financed_emissions == pytest.approx((1_000_000 / 3_000_000) * 90)


def test_2_scope1_and_2(engine):
    result = engine.calculate(
        "1a-listed-equity",
        listed_inputs(scope1_emissions=60, scope2_emissions=30, verified_emissions=90),
        CompanyType.LISTED,
    )
    bd = result.metadata["scope_breakdown"]
    af = 1_000_000 / 3_000_000
    assert bd["financed_scope1_tco2e"] == pytest.approx(af * 60)
    assert bd["financed_scope2_tco2e"] == pytest.approx(af * 30)
    assert bd["financed_scope3_tco2e"] is None
    assert "scope3" in bd["missing_scopes"]
    assert result.financed_emissions == pytest.approx(af * 90)


def test_3_scope1_2_and_3(engine):
    result = engine.calculate(
        "1a-listed-equity",
        listed_inputs(
            scope1_emissions=50,
            scope2_emissions=20,
            scope3_emissions=30,
            verified_emissions=100,
        ),
        CompanyType.LISTED,
    )
    bd = result.metadata["scope_breakdown"]
    af = 1 / 3
    assert bd["financed_scope1_tco2e"] == pytest.approx(af * 50)
    assert bd["financed_scope2_tco2e"] == pytest.approx(af * 20)
    assert bd["financed_scope3_tco2e"] == pytest.approx(af * 30)
    assert bd["scope_completeness"] == "complete"
    assert result.financed_emissions == pytest.approx(af * 100)


def test_4_missing_scope3_is_not_zero(engine):
    result = engine.calculate(
        "1a-listed-equity",
        listed_inputs(scope1_emissions=40, scope2_emissions=10, verified_emissions=50),
        CompanyType.LISTED,
    )
    bd = result.metadata["scope_breakdown"]
    assert bd["financed_scope3_tco2e"] is None
    assert bd["scope_status"]["scope3"] == "missing"
    assert 0 not in (bd["financed_scope3_tco2e"],)
    assert result.financed_emissions == pytest.approx((1 / 3) * 50)


def test_5_explicit_zero_emissions(engine):
    result = engine.calculate(
        "1a-listed-equity",
        listed_inputs(
            scope1_emissions=0,
            scope2_emissions=0,
            verified_emissions=0,
        ),
        CompanyType.LISTED,
    )
    bd = result.metadata["scope_breakdown"]
    assert result.financed_emissions == 0
    assert bd["financed_scope1_tco2e"] == 0
    assert bd["financed_scope2_tco2e"] == 0
    assert bd["scope_status"]["scope1"] == "zero"
    assert bd["financed_scope3_tco2e"] is None


def test_6_total_only_estimated_results(engine):
    result = engine.calculate(
        "3a-listed-equity",
        listed_inputs(
            company_revenue=8_000_000,
            sector_intensity=0.5,
            sector_intensity_unit="kgCO2e/PKR",
        ),
        CompanyType.LISTED,
    )
    bd = result.metadata["scope_breakdown"]
    assert bd["financed_scope1_tco2e"] is None
    assert bd["financed_unallocated_tco2e"] == pytest.approx(result.financed_emissions)
    assert bd["estimated"] is True
    assert bd["scope_completeness"] == "total_only"


def test_7_asset_specific_scope_exclusions(engine):
    mortgage = engine.get_formula_by_id("1a-mortgage")
    bd = build_scope_breakdown(mortgage, {}, 0.5, 10.0)
    assert "scope3" in bd["excluded_scopes"]
    assert bd["financed_scope3_tco2e"] is None
    assert bd["financed_unallocated_tco2e"] == 10.0

    motor = engine.get_formula_by_id("1a-motor-vehicle")
    motor_bd = build_scope_breakdown(motor, {}, 0.5, 4.0)
    assert "scope3" in motor_bd["excluded_scopes"]


def test_8_facilitated_weighting(engine):
    inputs = listed_inputs(
        facilitated_amount=500_000,
        weighting_factor=0.33,
        scope1_emissions=60,
        scope2_emissions=30,
        verified_emissions=90,
    )
    result = engine.calculate(
        "1a-facilitated-verified-listed", inputs, CompanyType.LISTED
    )
    bd = result.metadata["scope_breakdown"]
    af = 500_000 / 3_000_000
    assert bd["financed_scope1_tco2e"] == pytest.approx(af * 0.33 * 60)
    assert bd["financed_scope2_tco2e"] == pytest.approx(af * 0.33 * 30)
    assert result.financed_emissions == pytest.approx(af * 0.33 * 90)


def test_9_two_loans_same_formula_independent(engine):
    a = engine.calculate(
        "1a-listed-equity",
        listed_inputs(scope1_emissions=90, verified_emissions=90, financing_instance_id="a"),
        CompanyType.LISTED,
    )
    b = engine.calculate(
        "1a-listed-equity",
        listed_inputs(
            outstanding_amount=2_000_000,
            scope1_emissions=90,
            verified_emissions=90,
            financing_instance_id="b",
        ),
        CompanyType.LISTED,
    )
    assert a.financed_emissions != b.financed_emissions
    assert a.metadata["scope_breakdown"]["financed_scope1_tco2e"] != b.metadata[
        "scope_breakdown"
    ]["financed_scope1_tco2e"]


def test_10_reporting_total_equals_included_scopes(engine):
    result = engine.calculate(
        "1a-listed-equity",
        listed_inputs(scope1_emissions=70, scope2_emissions=20, verified_emissions=90),
        CompanyType.LISTED,
    )
    bd = result.metadata["scope_breakdown"]
    included = bd["financed_scope1_tco2e"] + bd["financed_scope2_tco2e"]
    assert included == pytest.approx(result.financed_emissions)


def test_11_category_15_uses_attributed_total_not_investee_scope3(engine):
    result = engine.calculate(
        "1a-listed-equity",
        listed_inputs(
            scope1_emissions=40,
            scope2_emissions=10,
            scope3_emissions=200,
            verified_emissions=250,
        ),
        CompanyType.LISTED,
    )
    bd = result.metadata["scope_breakdown"]
    # Category 15 imports financed_emissions once — not investee Scope 3 as an extra line.
    assert result.financed_emissions == pytest.approx((1 / 3) * 250)
    assert bd["financed_scope3_tco2e"] == pytest.approx((1 / 3) * 200)
    assert result.financed_emissions != bd["financed_scope3_tco2e"]


def test_12_historical_total_only_records(engine):
    formula = engine.get_formula_by_id("1a-listed-equity")
    bd = build_scope_breakdown(formula, {"verified_emissions": 50_000}, 1 / 3, 50_000 / 3)
    assert bd["scope_completeness"] == "total_only"
    assert bd["financed_scope1_tco2e"] is None
    assert bd["financed_unallocated_tco2e"] == pytest.approx(50_000 / 3)


def test_13_finite_and_unit_consistent(engine):
    result = engine.calculate(
        "2a-listed-equity",
        listed_inputs(
            energy_consumption=1000,
            emission_factor=0.4,
            process_emissions=10,
        ),
        CompanyType.LISTED,
    )
    bd = result.metadata["scope_breakdown"]
    assert bd["emissions_unit"] == "tCO2e"
    assert bd["financed_scope2_tco2e"] == pytest.approx((1 / 3) * 400)
    assert bd["financed_scope1_tco2e"] == pytest.approx((1 / 3) * 10)
    assert bd["financed_scope3_tco2e"] is None
    assert "scope3" in bd["excluded_scopes"]
    assert result.financed_emissions == pytest.approx((1 / 3) * 410)


def test_14_inconsistent_backend_scopes_are_rejected(engine):
    with pytest.raises(ValueError, match="do not match"):
        engine.calculate(
            "1a-listed-equity",
            listed_inputs(
                scope1_emissions=10,
                scope2_emissions=10,
                scope3_emissions=10,
                verified_emissions=5,
            ),
            CompanyType.LISTED,
        )


def test_sovereign_production_is_scope1_not_inferred_s2_s3(engine):
    result = engine.calculate(
        "1a-sovereign-debt",
        {
            "outstanding_amount": 1_000_000,
            "pp_adjusted_gdp": 10_000_000,
            "verified_country_emissions": 5000,
        },
        CompanyType.LISTED,
    )
    bd = result.metadata["scope_breakdown"]
    assert bd["financed_scope1_tco2e"] == pytest.approx(result.financed_emissions)
    assert bd["financed_scope2_tco2e"] is None
    assert bd["financed_scope3_tco2e"] is None
