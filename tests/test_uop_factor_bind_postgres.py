"""Isolated PostgreSQL tests for UoP factor binding. Never uses production."""

from __future__ import annotations

import time
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text

from fastapi_app.factor_library_models import FactorLibraryEntry
from fastapi_app.uop_underlying import calculate_underlying_asset
from tests.pg_isolated import (
    bootstrap_desnz_verified_rows,
    bootstrap_factor_library,
    is_isolated_url,
    is_production_url,
    make_engine,
    make_session,
    start_isolated_postgres,
)

DESNZ_ELECTRICITY_ID = uuid.UUID("fabac5f1-e547-52a3-b3d2-394eaa1c679d")
DESNZ_HEAT_ID = uuid.UUID("134a44da-d317-5773-bafc-e1a7734851b6")
DENOM = dict(denom_kind="total_asset_value", denom_label="Total asset value", denom_ref="test")


def _wait_ready(url: str, attempts: int = 10) -> None:
    last_error = None
    for _ in range(attempts):
        try:
            engine = make_engine(url)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            engine.dispose()
            return
        except Exception as exc:
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"Isolated Postgres did not become ready: {last_error}")


@pytest.fixture(scope="session")
def bind_engine():
    try:
        url, stop = start_isolated_postgres()
    except Exception as exc:
        pytest.skip(f"Isolated PostgreSQL is unavailable ({exc})")
        return
    if is_production_url(url) or not is_isolated_url(url):
        pytest.fail("Refusing production or non-isolated DATABASE_URL")
    try:
        _wait_ready(url)
        engine = make_engine(url)
        bootstrap_factor_library(engine)
        bootstrap_desnz_verified_rows(engine)
        yield engine
        engine.dispose()
    finally:
        stop()


@pytest.fixture
def bind_session(bind_engine):
    session = make_session(bind_engine)
    try:
        yield session
        session.rollback()
    finally:
        session.close()
        with bind_engine.begin() as conn:
            conn.execute(
                text(
                    "TRUNCATE TABLE ref.factor_library_audit, ref.factor_library_entries "
                    "RESTART IDENTITY CASCADE"
                )
            )


def _promote_desnz_electricity(**overrides) -> FactorLibraryEntry:
    payload = dict(
        id=uuid.uuid4(),
        publication_id=uuid.uuid4(),
        factor_row_id=DESNZ_ELECTRICITY_ID,
        dataset_code="desnz_ghg_conversion_factors_2026",
        dataset_version="2026",
        category="purchased_electricity",
        library_class="physical",
        country_code="GB",
        geography="United Kingdom",
        sector_or_activity="electricity",
        activity_key="electricity",
        factor_value=Decimal("0.13096000"),
        numerator_unit="kg CO2e",
        denominator_unit="kWh",
        unit="kg CO2e/kWh",
        applicable_year=2026,
        publication_year=2026,
        gas="CO2e",
        source_organization="UK DESNZ",
        status="approved",
    )
    payload.update(overrides)
    return FactorLibraryEntry(**payload)


def _office(estimation: dict) -> dict:
    return {
        "underlyingAssetId": "office-bound",
        "name": "Office",
        "assetClass": "commercial-real-estate",
        "allocatedOutstanding": 5_000_000,
        "totalAssetValue": 10_000_000,
        "hasReportedEmissions": "no",
        "dataSource": "EPC",
        "estimation": estimation,
    }


def test_authoritative_desnz_value_is_used_and_catalog_row_is_not_duplicated(bind_session):
    entry = _promote_desnz_electricity()
    bind_session.add(entry)
    bind_session.commit()
    result = calculate_underlying_asset(
        _office(
            {
                "pcafOption": "2a",
                "method": "physical",
                "labelEnergyIntensity": 20,
                "floorArea": 100,
                "libraryEntryId": str(entry.id),
                "factorConfirmed": True,
                "factorSource": "UK DESNZ",
                "factorGeography": "United Kingdom",
                "factorYear": "2026",
                "factorUnit": "kg CO2e/kWh",
            }
        ),
        db=bind_session,
        **DENOM,
    )
    assert result["status"] == "complete"
    snap = result["factor_snapshot"]
    assert snap["factor_value"] == pytest.approx(0.13096)
    assert snap["unit"] == "kg CO2e/kWh"
    assert snap["geography"] == "United Kingdom"
    assert snap["applicable_year"] == 2026
    assert snap["source"] == "UK DESNZ"
    assert snap["dataset_version"] == "2026"
    assert snap["client_value_used"] is False
    assert snap["factor_row_id"] == str(DESNZ_ELECTRICITY_ID)
    catalog_count = bind_session.execute(
        text("SELECT count(*) FROM ref.factor_rows WHERE id = :id"),
        {"id": str(DESNZ_ELECTRICITY_ID)},
    ).scalar()
    assert catalog_count == 1


def test_tampered_client_value_is_rejected(bind_session):
    entry = _promote_desnz_electricity()
    bind_session.add(entry)
    bind_session.commit()
    result = calculate_underlying_asset(
        _office(
            {
                "pcafOption": "2a",
                "method": "physical",
                "labelEnergyIntensity": 20,
                "floorArea": 100,
                "libraryEntryId": str(entry.id),
                "factorConfirmed": True,
                "emissionFactor": 0.5,
                "factorSource": "UK DESNZ",
                "factorGeography": "United Kingdom",
                "factorYear": "2026",
                "factorUnit": "kg CO2e/kWh",
            }
        ),
        db=bind_session,
        **DENOM,
    )
    assert result["status"] == "incomplete"
    assert result["code"] == "factor_snapshot_mismatch"
    assert result["structure_financed_emissions"] is None


def test_pending_review_is_not_used(bind_session):
    entry = _promote_desnz_electricity(status="pending_review", activity_key="electricity-pending")
    bind_session.add(entry)
    bind_session.commit()
    result = calculate_underlying_asset(
        _office(
            {
                "pcafOption": "2a",
                "method": "physical",
                "labelEnergyIntensity": 20,
                "floorArea": 100,
                "libraryEntryId": str(entry.id),
                "factorConfirmed": True,
                "emissionFactor": 0.13096,
                "factorSource": "manual",
                "factorGeography": "United Kingdom",
                "factorYear": "2026",
                "factorUnit": "kg CO2e/kWh",
            }
        ),
        db=bind_session,
        **DENOM,
    )
    assert result["status"] == "incomplete"
    assert result["code"] == "factor_not_approved"


def test_pakistan_geography_does_not_use_uk_factor(bind_session):
    entry = _promote_desnz_electricity()
    bind_session.add(entry)
    bind_session.commit()
    result = calculate_underlying_asset(
        _office(
            {
                "pcafOption": "2a",
                "method": "physical",
                "labelEnergyIntensity": 20,
                "floorArea": 100,
                "libraryEntryId": str(entry.id),
                "factorConfirmed": True,
                "emissionFactor": 0.13096,
                "factorSource": "UK DESNZ",
                "factorGeography": "Pakistan",
                "factorYear": "2026",
                "factorUnit": "kg CO2e/kWh",
            }
        ),
        db=bind_session,
        **DENOM,
    )
    assert result["status"] == "incomplete"
    assert result["code"] == "factor_geography_mismatch"


def test_year_mismatch_is_rejected(bind_session):
    entry = _promote_desnz_electricity()
    bind_session.add(entry)
    bind_session.commit()
    result = calculate_underlying_asset(
        _office(
            {
                "pcafOption": "2a",
                "method": "physical",
                "labelEnergyIntensity": 20,
                "floorArea": 100,
                "libraryEntryId": str(entry.id),
                "factorConfirmed": True,
                "emissionFactor": 0.13096,
                "factorSource": "UK DESNZ",
                "factorGeography": "United Kingdom",
                "factorYear": "2025",
                "factorUnit": "kg CO2e/kWh",
            }
        ),
        db=bind_session,
        **DENOM,
    )
    assert result["status"] == "incomplete"
    assert result["code"] == "factor_year_mismatch"


def test_gallon_vehicle_factor_is_rejected(bind_session):
    entry = FactorLibraryEntry(
        id=uuid.uuid4(),
        publication_id=uuid.uuid4(),
        category="mobile_fuel",
        library_class="vehicle",
        country_code="US",
        geography="United States",
        sector_or_activity="vehicle-fuel",
        activity_key="vehicle-fuel",
        factor_value=Decimal("8.31000000"),
        numerator_unit="kg CO2e",
        denominator_unit="gallon",
        unit="kg CO2e/gallon",
        applicable_year=2024,
        publication_year=2024,
        gas="CO2e",
        source_organization="US EPA",
        status="approved",
    )
    bind_session.add(entry)
    bind_session.commit()
    result = calculate_underlying_asset(
        {
            "underlyingAssetId": "car-1",
            "name": "Fleet car",
            "assetClass": "motor-vehicle-loan",
            "allocatedOutstanding": 10_000,
            "totalAssetValue": 20_000,
            "hasReportedEmissions": "no",
            "dataSource": "odometer",
            "estimation": {
                "pcafOption": "1a",
                "method": "physical",
                "fuelConsumed": 100,
                "libraryEntryId": str(entry.id),
                "factorConfirmed": True,
                "emissionFactor": 8.31,
                "factorSource": "US EPA",
                "factorGeography": "United States",
                "factorYear": "2024",
                "factorUnit": "kg CO2e/gallon",
            },
        },
        db=bind_session,
        denom_kind="total_asset_value",
        denom_label="Total vehicle value",
        denom_ref="test",
    )
    assert result["status"] == "incomplete"
    assert result["code"] == "factor_unit_mismatch"


def test_heat_row_can_be_bound_without_duplicating_catalog(bind_session):
    entry = _promote_desnz_electricity(
        factor_row_id=DESNZ_HEAT_ID,
        category="purchased_heat",
        activity_key="heat",
        sector_or_activity="heat",
        factor_value=Decimal("0.17529000"),
        unit="kg CO2e/kWh",
    )
    bind_session.add(entry)
    bind_session.commit()
    result = calculate_underlying_asset(
        _office(
            {
                "pcafOption": "2a",
                "method": "physical",
                "labelEnergyIntensity": 20,
                "floorArea": 100,
                "libraryEntryId": str(entry.id),
                "factorConfirmed": True,
                "factorSource": "UK DESNZ",
                "factorGeography": "United Kingdom",
                "factorYear": "2026",
                "factorUnit": "kg CO2e/kWh",
            }
        ),
        db=bind_session,
        **DENOM,
    )
    assert result["status"] == "complete"
    assert result["factor_snapshot"]["factor_value"] == pytest.approx(0.17529)
    assert result["factor_snapshot"]["factor_row_id"] == str(DESNZ_HEAT_ID)
    assert bind_session.execute(
        text("SELECT count(*) FROM ref.factor_rows WHERE id = :id"),
        {"id": str(DESNZ_HEAT_ID)},
    ).scalar() == 1
