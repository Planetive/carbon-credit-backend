"""Isolated Postgres tests against real catalog row copies. Never uses production."""

from __future__ import annotations

import time
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text

from fastapi_app.factor_library import LibraryFactor, MatchQuery, match_factors
from fastapi_app.factor_library_models import FactorLibraryEntry
from fastapi_app.factor_models import FactorDataset, FactorRow
from fastapi_app.factor_service import factor_row_to_legacy_record, load_legacy_sheet
from fastapi_app.ghg_calc.scope2_uk_electricity import resolve_uk_location_factor
from fastapi_app.ghg_calc.scope2_uk_heat_steam import resolve_uk_heat_factor
from fastapi_app.ghg_calc.stationary_combustion import calculate_stationary_combustion
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

# Live production copies, read-only on 2026-11-05. Values are not invented.
LIVE_EPA_NATURAL_GAS = {
    "CH4 Unit": "g CH4 per mmBtu",
    "CO2 Unit": "kg CO2 per mmBtu",
    "Category": "Natural Gas",
    "HIV Unit": "mmBtu per scf",
    "N2O Unit": "g N2O per mmBtu",
    "Fuel Type": "Natural Gas",
    "CH4 Factor": 1,
    "CH4 Unit_1": "g CH4 per scf",
    "CO2 Factor": 53.06,
    "CO2 Unit_1": "kg CO2 per scf",
    "N2O Factor": 0.1,
    "N2O Unit_1": "g N2O per scf",
    "CH4 Factor_1": 0.00103,
    "CO2 Factor_1": 0.05444,
    "N2O Factor_1": 0.0001,
    "Heat Content (HHV)": 0.001026,
}
LIVE_UK_BUTANE = {
    "Fuel": "Butane",
    "Unit": "tonnes",
    "kg CO2e": 3033.38067,
    "Activity": "Gaseous fuels",
    "kg CO2e of CH4 per unit": 2.52,
    "kg CO2e of CO2 per unit": 3029.26,
    "kg CO2e of N2O per unit": 1.60067,
}
LIVE_MOBILE_AVGAS = {
    "Unit": "gallon",
    "Fuel Type": "Aviation Gasoline",
    "kg CO2 per unit": 8.31,
}
LIVE_REFRIGERANT = {
    "ASHRAE #": "R-401A",
    "100-year GWP": " 18 ",
    "Blend Composition": "53% HCFC-22 , 34% HCFC-124 , 13% HFC-152a",
}
LIVE_CBECS = {
    "row_id": 1,
    "intensity_median_kbtu_sqft": 45.0,
    "energy_intensity_kwh_per_sqft": 13.1882,
    "energy_per_building_kwh_score5": 336152.52,
    "consumption_per_sqft_thousand_btu": 70.4,
    "energy_intensity_kwh_per_m2_score4": 141.9566,
    "consumption_per_building_million_btu": 1147.0,
}
LIVE_VEHICLE_EFFICIENCY = {
    "unit": "km/L",
    "fuel_type": "Petrol",
    "geography": "local",
    "efficiency": "18",
    "vehicle_type": "Kei car / micro hatch",
}


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
def catalog_engine():
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
def db(catalog_engine):
    session = make_session(catalog_engine)
    try:
        yield session
        session.rollback()
    finally:
        session.close()


def _insert_dataset(db, code: str, publisher: str, title: str) -> FactorDataset:
    existing = db.query(FactorDataset).filter(FactorDataset.code == code).first()
    if existing:
        return existing
    row = FactorDataset(
        id=uuid.uuid4(),
        code=code,
        publisher=publisher,
        title=title,
        version_label="live_copy",
        is_active=True,
    )
    db.add(row)
    db.flush()
    return row


def _insert_row(db, dataset: FactorDataset, **kwargs) -> FactorRow:
    row = FactorRow(id=uuid.uuid4(), dataset_id=dataset.id, **kwargs)
    db.add(row)
    db.flush()
    return row


def test_desnz_electricity_row_is_retrieved_by_id_not_client_value(db):
    resolved = resolve_uk_location_factor(
        db, country="United Kingdom", grid_region="national", reporting_year=2026
    )
    assert resolved["ok"] is True
    assert resolved["row"].id == DESNZ_ELECTRICITY_ID
    assert resolved["factor_per_kwh"] == Decimal("0.13096")
    assert resolved["dataset"].code == "desnz_ghg_conversion_factors_2026"


def test_desnz_heat_row_is_retrieved_by_id(db):
    resolved = resolve_uk_heat_factor(db, country="United Kingdom", reporting_year=2026)
    assert resolved["ok"] is True
    assert resolved["row"].id == DESNZ_HEAT_ID
    assert resolved["factor_per_kwh"] == Decimal("0.17529")


@pytest.mark.parametrize(
    "country,year",
    [
        ("Pakistan", 2026),
        ("United Arab Emirates", 2026),
        ("United Kingdom", 2025),
        ("United States", 2026),
    ],
)
def test_electricity_does_not_substitute_uk_factor(db, country, year):
    resolved = resolve_uk_location_factor(
        db, country=country, grid_region="national", reporting_year=year
    )
    assert resolved["ok"] is False
    assert resolved["status"] == "missing_factor"


def test_heat_does_not_apply_uk_factor_to_pakistan(db):
    resolved = resolve_uk_heat_factor(db, country="Pakistan", reporting_year=2026)
    assert resolved["ok"] is False
    assert "United Kingdom" not in (resolved.get("error") or "") or "not applied" in (
        resolved.get("error") or ""
    ).lower() or "no verified" in (resolved.get("error") or "").lower()


def test_epa_natural_gas_sheet_discards_client_factor(db):
    dataset = _insert_dataset(db, "fuel_epa_2", "EPA", "Fuel EPA 2")
    stored = _insert_row(
        db,
        dataset,
        category="fuel",
        label="Natural Gas",
        unit="mmBtu per scf",
        kg_co2e=None,
        attributes=LIVE_EPA_NATURAL_GAS,
    )
    db.commit()
    rows = load_legacy_sheet(db, ["fuel_epa_2"])
    assert rows
    assert rows[0]["Fuel Type"] == "Natural Gas"
    assert rows[0]["CO2 Factor"] == 53.06
    result = calculate_stationary_combustion(
        fuel="Natural Gas",
        quantity=1,
        unit="mmBtu",
        sheets=[{"rows": rows}],
        category="Natural Gas",
        factor=9999,
    )
    assert result.get("success") is True, result
    assert Decimal(str(result["total_kg_co2e"])) != Decimal("9999")
    assert Decimal(str(result["factors"]["co2"]["value"])) == Decimal("53.06")
    legacy = factor_row_to_legacy_record(db.get(FactorRow, stored.id))
    assert legacy["CO2 Factor"] == 53.06
    assert stored.kg_co2e is None


def test_uk_fuel_co2e_lives_in_attributes_not_kg_co2e_column(db):
    dataset = _insert_dataset(db, "uk_fuel_factors", "UK", "UK_Fuel_Factors")
    stored = _insert_row(
        db,
        dataset,
        category="fuel",
        label="Butane",
        unit="tonnes",
        kg_co2e=None,
        attributes=LIVE_UK_BUTANE,
    )
    db.commit()
    sheets = load_legacy_sheet(db, ["uk_fuel_factors"])
    assert sheets[0]["kg CO2e"] == 3033.38067
    assert stored.kg_co2e is None


def test_mobile_aviation_gasoline_is_kg_co2_not_co2e(db):
    dataset = _insert_dataset(db, "mobile_combustion", "legacy", "Mobile Combustion")
    stored = _insert_row(
        db,
        dataset,
        category="mobile",
        label="Aviation Gasoline",
        unit="gallon",
        kg_co2e=None,
        attributes=LIVE_MOBILE_AVGAS,
    )
    db.commit()
    sheets = load_legacy_sheet(db, ["mobile_combustion"])
    assert sheets[0]["Fuel Type"] == "Aviation Gasoline"
    assert sheets[0]["kg CO2 per unit"] == 8.31
    assert stored.kg_co2e is None


def test_refrigerant_gwp_is_not_an_emission_factor_column(db):
    dataset = _insert_dataset(db, "epa_refrigerant_gwp", "EPA", "EPA Refrigerant GWP")
    stored = _insert_row(
        db,
        dataset,
        category="refrigerant",
        label=None,
        unit=None,
        kg_co2e=None,
        attributes=LIVE_REFRIGERANT,
    )
    db.commit()
    sheets = load_legacy_sheet(db, ["epa_refrigerant_gwp"])
    assert sheets[0]["ASHRAE #"] == "R-401A"
    assert "18" in str(sheets[0]["100-year GWP"])
    assert stored.kg_co2e is None


def test_cbecs_is_energy_intensity_not_an_emission_factor(db):
    dataset = _insert_dataset(db, "cbecs_table_c4", "EIA", "CBECS Table C4")
    stored = _insert_row(
        db,
        dataset,
        category="All buildings",
        label="All buildings",
        unit="kWh/sqft",
        kg_co2e=None,
        attributes=LIVE_CBECS,
    )
    db.commit()
    assert stored.kg_co2e is None
    assert stored.attributes["energy_intensity_kwh_per_sqft"] == 13.1882
    resolved = resolve_uk_location_factor(
        db, country="United States", grid_region="national", reporting_year=2026
    )
    assert resolved["ok"] is False


def test_vehicle_efficiency_row_is_not_a_fuel_emission_factor(db):
    dataset = _insert_dataset(db, "motor_vehicle_type_efficiency", "internal", "Vehicle type efficiency")
    stored = _insert_row(
        db,
        dataset,
        category="local",
        label="Kei car / micro hatch — Petrol",
        unit="km/L",
        kg_co2e=None,
        attributes=LIVE_VEHICLE_EFFICIENCY,
    )
    db.commit()
    assert stored.kg_co2e is None
    assert stored.attributes["efficiency"] == "18"


def test_same_desnz_row_can_be_promoted_to_library_without_duplicating_factor_rows(db):
    catalog_row = db.get(FactorRow, DESNZ_ELECTRICITY_ID)
    assert catalog_row is not None
    entry = FactorLibraryEntry(
        id=uuid.uuid4(),
        publication_id=uuid.uuid4(),
        factor_row_id=catalog_row.id,
        dataset_id=catalog_row.dataset_id,
        dataset_code="desnz_ghg_conversion_factors_2026",
        dataset_version="2026",
        category="purchased_electricity",
        library_class="physical",
        country_code="GB",
        geography="United Kingdom",
        sector_or_activity="electricity",
        activity_key="electricity",
        factor_value=catalog_row.kg_co2e,
        numerator_unit="kg CO2e",
        denominator_unit="kWh",
        unit="kg CO2e/kWh",
        applicable_year=2026,
        publication_year=2026,
        gas="CO2e",
        source_organization="UK DESNZ",
        status="approved",
    )
    db.add(entry)
    db.commit()
    matched = match_factors(
        MatchQuery("physical", "United Kingdom", "electricity", 2026),
        [
            LibraryFactor(
                id=str(entry.id),
                publication_id=str(entry.publication_id),
                dataset_code="desnz_ghg_conversion_factors_2026",
                dataset_version="2026",
                category="purchased_electricity",
                library_class="physical",
                geography="United Kingdom",
                country_code="GB",
                sector_or_activity="electricity",
                activity_key="electricity",
                factor_value=float(catalog_row.kg_co2e),
                unit="kg CO2e/kWh",
                numerator_unit="kg CO2e",
                denominator_unit="kWh",
                applicable_year=2026,
                publication_year=2026,
                gas="CO2e",
                source_organization="UK DESNZ",
                source_document="",
                source_url="",
                provenance="verified catalog row",
                license_name="",
                permitted_use="catalog_verified",
                currency_code="",
                price_year=None,
                status="approved",
            )
        ],
    )
    assert matched.status == "ok"
    assert matched.factors[0].factor_value == 0.13096
    still = db.get(FactorRow, DESNZ_ELECTRICITY_ID)
    assert still.kg_co2e == Decimal("0.13096000")
    pakistan = match_factors(
        MatchQuery("physical", "Pakistan", "electricity", 2026),
        matched.factors,
    )
    assert pakistan.status == "NO_VERIFIED_FACTOR"


def test_uop_rejects_typed_value_without_approved_library_id():
    result = calculate_underlying_asset(
        {
            "underlyingAssetId": "office-typed",
            "name": "Office",
            "assetClass": "commercial-real-estate",
            "allocatedOutstanding": 5_000_000,
            "totalAssetValue": 10_000_000,
            "hasReportedEmissions": "no",
            "dataSource": "EPC",
            "estimation": {
                "pcafOption": "2a",
                "method": "physical",
                "labelEnergyIntensity": 20,
                "floorArea": 100,
                "emissionFactor": 0.001,
                "factorUnit": "tCO2e/kWh",
                "factorSource": "typed table",
                "factorGeography": "Pakistan",
                "factorYear": "2026",
            },
        },
        denom_kind="total_asset_value",
        denom_label="Total asset value",
        denom_ref="test",
    )
    assert result["status"] == "incomplete"
    assert result["code"] == "factor_not_bound"
    assert result["structure_financed_emissions"] is None
    assert result["factor_snapshot"]["library_entry_id"] is None
