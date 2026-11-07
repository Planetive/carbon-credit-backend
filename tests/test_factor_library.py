"""Unit tests for approved-factor matching. No production database."""

from __future__ import annotations

import pytest

from fastapi_app.factor_library import (
    NO_FACTOR,
    LibraryFactor,
    MatchQuery,
    compatible_mass_factor,
    match_factors,
    require_confirmed_snapshot,
)


def _factor(**overrides) -> LibraryFactor:
    payload = dict(
        id="11111111-1111-1111-1111-111111111111",
        publication_id="22222222-2222-2222-2222-222222222222",
        dataset_code="desnz_ghg_conversion_factors_2026",
        dataset_version="2026",
        category="purchased_electricity",
        library_class="physical",
        geography="United Kingdom",
        country_code="GB",
        sector_or_activity="electricity",
        activity_key="electricity",
        factor_value=0.13096,
        unit="kg CO2e/kWh",
        numerator_unit="kg CO2e",
        denominator_unit="kWh",
        applicable_year=2026,
        publication_year=2026,
        gas="CO2e",
        source_organization="UK DESNZ",
        source_document="GHG conversion factors 2026",
        source_url="",
        provenance="verified catalog row",
        license_name="UK government conversion factors",
        permitted_use="catalog_verified",
        currency_code="",
        price_year=None,
        status="approved",
    )
    payload.update(overrides)
    return LibraryFactor(**payload)


def test_exact_country_year_activity_match():
    result = match_factors(
        MatchQuery("physical", "United Kingdom", "electricity", 2026),
        [_factor()],
    )
    assert result.status == "ok"
    assert len(result.factors) == 1
    assert result.factors[0].factor_value == 0.13096


def test_no_silent_geography_substitution():
    result = match_factors(
        MatchQuery("physical", "Pakistan", "electricity", 2026),
        [_factor()],
    )
    assert result.status == NO_FACTOR
    assert result.factors == ()
    assert "No verified factor available" in result.message


def test_no_silent_year_substitution():
    result = match_factors(
        MatchQuery("physical", "United Kingdom", "electricity", 2025),
        [_factor()],
    )
    assert result.status == NO_FACTOR


def test_physical_economic_separation():
    economic = _factor(
        id="33333333-3333-3333-3333-333333333333",
        library_class="economic",
        activity_key="manufacturing",
        sector_or_activity="manufacturing",
        factor_value=0.4,
        unit="kgCO2e/USD",
        currency_code="USD",
        price_year=2022,
    )
    physical_query = MatchQuery("physical", "United Kingdom", "manufacturing", 2026)
    assert match_factors(physical_query, [economic]).status == NO_FACTOR
    economic_query = MatchQuery(
        "economic",
        "United Kingdom",
        "manufacturing",
        2026,
        currency_code="USD",
        price_year=2022,
    )
    assert match_factors(economic_query, [economic]).status == "ok"


def test_currency_and_price_year_must_match():
    economic = _factor(
        library_class="economic",
        activity_key="manufacturing",
        sector_or_activity="manufacturing",
        factor_value=0.4,
        unit="kgCO2e/USD",
        currency_code="USD",
        price_year=2022,
    )
    wrong_ccy = MatchQuery(
        "economic", "United Kingdom", "manufacturing", 2026, currency_code="PKR", price_year=2022
    )
    wrong_year = MatchQuery(
        "economic", "United Kingdom", "manufacturing", 2026, currency_code="USD", price_year=2019
    )
    assert match_factors(wrong_ccy, [economic]).status == NO_FACTOR
    assert match_factors(wrong_year, [economic]).status == NO_FACTOR


def test_multiple_valid_factors_require_confirmation():
    a = _factor(id="a", publication_id="pa", source_organization="DESNZ")
    b = _factor(id="b", publication_id="pb", source_organization="National Grid", dataset_code="other")
    result = match_factors(MatchQuery("physical", "United Kingdom", "electricity", 2026), [a, b])
    assert result.status == "multiple"
    assert len(result.factors) == 2


def test_unapproved_factors_are_ignored():
    draft = _factor(status="pending_review")
    result = match_factors(MatchQuery("physical", "United Kingdom", "electricity", 2026), [draft])
    assert result.status == NO_FACTOR


def test_mass_unit_conversion_does_not_change_geography():
    assert compatible_mass_factor(130.96, "kgCO2e") == pytest.approx(0.13096)
    assert compatible_mass_factor(0.13096, "tCO2e") == pytest.approx(0.13096)
    assert compatible_mass_factor(0.13096, "kg CO2e/kWh") is None


def test_historical_snapshot_mismatch_is_blocked():
    estimation = {
        "libraryEntryId": "11111111-1111-1111-1111-111111111111",
        "factorConfirmed": True,
        "emissionFactor": 0.2,
        "libraryFactorValue": 0.13096,
        "factorGeography": "United Kingdom",
        "libraryGeography": "United Kingdom",
        "factorYear": "2026",
        "libraryApplicableYear": "2026",
    }
    assert require_confirmed_snapshot(estimation) == "FACTOR_SNAPSHOT_MISMATCH"


def test_unconfirmed_library_factor_is_blocked():
    estimation = {
        "libraryEntryId": "11111111-1111-1111-1111-111111111111",
        "factorConfirmed": False,
        "emissionFactor": 0.13096,
        "libraryFactorValue": 0.13096,
    }
    assert require_confirmed_snapshot(estimation) == "FACTOR_NOT_CONFIRMED"


def test_typed_factor_without_library_id_is_unchanged():
    assert require_confirmed_snapshot({"emissionFactor": 0.5, "factorSource": "sector table"}) is None


def test_building_query_can_reuse_physical_electricity_row():
    physical = _factor()
    result = match_factors(
        MatchQuery("building", "United Kingdom", "electricity", 2026),
        [physical],
    )
    assert result.status == "ok"
    assert result.factors[0].library_class == "physical"
