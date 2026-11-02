"""UK purchased electricity and heat. Official values are acceptance checks for stored rows."""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi_app.auth_models import User
from fastapi_app.auth_org import OrgContext
from fastapi_app.factor_models import FactorDataset, FactorRow
from fastapi_app.ghg_calc.scope2_uk_electricity import calculate_uk_location_electricity
from fastapi_app.ghg_calc.scope2_uk_heat_steam import calculate_uk_purchased_heat_steam
from fastapi_app.ghg_calc.scope2_uk_records import save_uk_electricity_record
from fastapi_app.ghg_models import EmissionActivity, EmissionAssessment
from fastapi_app.portfolio_models import Counterparty

ORG_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
USER_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
ASSESSMENT_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
COUNTERPARTY_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")
DATASET_ID = uuid.UUID("66666666-6666-6666-6666-666666666666")
ROW_ID = uuid.UUID("77777777-7777-7777-7777-777777777777")


class FakeQuery:
    def __init__(self, session, model):
        self.session = session
        self.model = model

    def join(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def with_for_update(self):
        return self

    def all(self):
        return list(self.session.pairs)

    def first(self):
        return self.session.lookup.get(self.model)


class FakeSession:
    def __init__(self, pairs, reporting_period="2025", framework="uk"):
        self.pairs = pairs
        self.lookup = {
            EmissionAssessment: EmissionAssessment(
                id=ASSESSMENT_ID,
                organization_id=ORG_ID,
                user_id=USER_ID,
                framework=framework,
                reporting_period=reporting_period,
            ),
            Counterparty: Counterparty(
                id=COUNTERPARTY_ID,
                user_id=USER_ID,
                name="Branch",
                sector="Banking",
                geography="United Kingdom",
                organization_id=ORG_ID,
            ),
        }
        self.added = []
        self.committed = False

    def query(self, *models):
        return FakeQuery(self, models[0])

    def add(self, row):
        self.added.append(row)

    def flush(self):
        return None

    def commit(self):
        self.committed = True

    def rollback(self):
        return None

    def refresh(self, row):
        return None


def _ctx():
    return OrgContext(
        user=User(id=USER_ID, email="uk@example.com", password_hash="x"),
        organization_id=ORG_ID,
        role="admin",
    )


def _dataset(**overrides):
    values = dict(
        id=DATASET_ID,
        code="desnz_ghg_cf",
        publisher="DESNZ",
        title="Greenhouse gas reporting: conversion factors",
        version_label="2025",
        is_active=True,
        source_notes="Authorized import fixture.",
    )
    values.update(overrides)
    return FactorDataset(**values)


def _electricity(**overrides):
    attributes = {
        "verification": "verified",
        "method": "location_based",
        "boundary": "electricity_generated",
        "source_document": "DESNZ conversion factors 2025, UK electricity generated",
        "publication_year": 2025,
        "reporting_year": 2025,
        "country": "United Kingdom",
        "grid_region": "national",
        "gas_coverage": "CO2, CH4 and N2O expressed as CO2e",
    }
    attributes.update(overrides.pop("attributes", {}))
    values = dict(
        id=ROW_ID,
        dataset_id=DATASET_ID,
        category="purchased_electricity",
        label="UK electricity generated",
        attributes=attributes,
        unit="kg CO2e/kWh",
        kg_co2e=Decimal("0.17700"),
    )
    values.update(overrides)
    return FactorRow(**values)


def _heat(**overrides):
    attributes = {
        "verification": "verified",
        "method": "purchased_energy",
        "boundary": "district_heat",
        "source_document": "DESNZ conversion factors 2025, district heat and steam",
        "publication_year": 2025,
        "reporting_year": 2025,
        "country": "United Kingdom",
        "gas_coverage": "CO2, CH4 and N2O expressed as CO2e",
    }
    attributes.update(overrides.pop("attributes", {}))
    values = dict(
        id=ROW_ID,
        dataset_id=DATASET_ID,
        category="purchased_heat_steam",
        label="District heat and steam",
        attributes=attributes,
        unit="kg CO2e/kWh",
        kg_co2e=Decimal("0.17529"),
    )
    values.update(overrides)
    return FactorRow(**values)


def test_uk_2025_generation_factor_is_used_and_renewables_are_not_deducted():
    session = FakeSession([(_electricity(), _dataset())])
    result = calculate_uk_location_electricity(
        session,
        country="UK",
        grid_region="national",
        quantity=Decimal("1000"),
        unit="kWh",
        period="2025-06",
        renewable_kwh=Decimal("400"),
        grid_factor=Decimal("0.425"),
        other_pct=Decimal("10"),
        other_row_emissions_sum=Decimal("999"),
    )
    assert result["total_t_co2e"] == "0.17700000"
    assert result["renewable_applied"] is False
    assert result["on_site_fuel_included"] is False
    assert result["factor"]["value"] == "0.17700000"
    assert result["factor"]["factor_row_id"] == str(ROW_ID)


def test_desnz_import_metadata_uses_the_published_co2e_total():
    electricity = _electricity(
        attributes={
            "source_document": (
                "Greenhouse gas reporting: conversion factors 2025, full set and flat file, "
                "UK electricity, Electricity generated, Electricity: UK, kWh. Flat-file ID 7_400_4000_5_1."
            ),
            "flat_file_id": "7_400_4000_5_1",
            "official_grid_name": "Electricity: UK",
            "kg_co2e_of_co2": "0.17489",
        },
    )
    dataset = _dataset(
        code="desnz_ghg_conversion_factors_2025",
        publisher="Department for Energy Security and Net Zero (DESNZ)",
        title="Greenhouse gas reporting: conversion factors 2025",
    )
    result = calculate_uk_location_electricity(
        FakeSession([(electricity, dataset)]),
        country="United Kingdom",
        grid_region="national",
        quantity=Decimal("1000"),
        unit="kWh",
        period="2025-03",
    )
    assert result["total_t_co2e"] == "0.17700000"

    heat = _heat(
        kg_co2=None,
        attributes={
            "kg_co2e_of_co2": "0.17355",
            "treatment": "complete_co2e",
            "flat_file_id": "10_401_4003_5_1",
        },
    )
    heat_result = calculate_uk_purchased_heat_steam(
        FakeSession([(heat, dataset)]),
        country="United Kingdom",
        energy_form="purchased_heat",
        quantity=Decimal("10"),
        unit="kWh",
        period="2025-03",
        co2_factor=Decimal("0.17355"),
    )
    assert heat_result["total_kg_co2e"] == "1.75290000"
    assert heat_result["total_t_co2e"] == "0.00175290"


def test_uk_2026_generation_factor_matches_the_2026_edition():
    row = _electricity(
        kg_co2e=Decimal("0.13096"),
        attributes={"publication_year": 2026, "reporting_year": 2026},
    )
    session = FakeSession([ (row, _dataset(version_label="2026")) ])
    result = calculate_uk_location_electricity(
        session,
        country="United Kingdom",
        grid_region="national",
        quantity=Decimal("1"),
        unit="MWh",
        period="2026-01",
    )
    assert result["electricity_kwh"] == "1000.00000000"
    assert result["total_t_co2e"] == "0.13096000"


def test_transmission_losses_and_the_wrong_edition_are_rejected():
    losses = _electricity(
        label="T&D UK electricity",
        kg_co2e=Decimal("0.01853"),
        attributes={"boundary": "transmission_and_distribution"},
    )
    session = FakeSession([(losses, _dataset())])
    result = calculate_uk_location_electricity(
        session, country="UK", grid_region="national", quantity=1, unit="kWh", period="2025-01"
    )
    assert result["status"] == "missing_factor"

    wrong = _electricity(kg_co2e=Decimal("0.13096"))
    session = FakeSession([(wrong, _dataset())])
    result = calculate_uk_location_electricity(
        session, country="UK", grid_region="national", quantity=1, unit="kWh", period="2025-01"
    )
    assert result["ok"] is False
    assert "DESNZ 2025" in result["error"]


def test_dubai_dewa_is_accepted_and_national_uae_and_04041_are_not():
    dewa = _electricity(
        label="DEWA Dubai electricity generated",
        kg_co2e=Decimal("0.3833"),
        attributes={
            "country": "United Arab Emirates",
            "grid_region": "Dubai",
            "source_document": "DEWA Sustainability Report, electricity grid emission factor",
            "publication_year": 2025,
            "reporting_year": 2025,
        },
    )
    session = FakeSession([(dewa, _dataset(publisher="DEWA", code="dewa_sustainability"))])
    result = calculate_uk_location_electricity(
        session, country="UAE", grid_region="Dubai", quantity=1000, unit="kWh", period="2025-03"
    )
    assert result["total_t_co2e"] == "0.38330000"

    national = calculate_uk_location_electricity(
        session, country="UAE", grid_region="national", quantity=1000, unit="kWh", period="2025-03"
    )
    assert national["ok"] is False

    placeholder = _electricity(
        kg_co2e=Decimal("0.4041"),
        attributes={"country": "United Arab Emirates", "grid_region": "Dubai"},
    )
    rejected = calculate_uk_location_electricity(
        FakeSession([(placeholder, _dataset(publisher="DEWA"))]),
        country="UAE",
        grid_region="Dubai",
        quantity=1,
        unit="kWh",
        period="2025-03",
    )
    assert rejected["ok"] is False


def test_pakistan_placeholder_igcep_and_ember_are_not_used():
    placeholder = _electricity(
        kg_co2e=Decimal("0.425"),
        attributes={"country": "Pakistan", "grid_region": "national", "source_document": "Undocumented grid factor"},
    )
    result = calculate_uk_location_electricity(
        FakeSession([(placeholder, _dataset(publisher="Unknown"))]),
        country="Pakistan",
        grid_region="national",
        quantity=1,
        unit="kWh",
        period="2025-01",
    )
    assert result["ok"] is False

    igcep = _electricity(
        kg_co2e=Decimal("0.278"),
        attributes={
            "country": "Pakistan",
            "grid_region": "national",
            "source_document": "IGCEP generation intensity",
        },
    )
    result = calculate_uk_location_electricity(
        FakeSession([(igcep, _dataset(publisher="NEPRA", code="igcep"))]),
        country="Pakistan",
        grid_region="national",
        quantity=1,
        unit="kWh",
        period="2025-01",
    )
    assert "IGCEP" in result["error"]

    ember = _electricity(
        kg_co2e=Decimal("0.4697"),
        attributes={
            "country": "Pakistan",
            "grid_region": "national",
            "source_document": "Ember lifecycle electricity intensity",
        },
    )
    result = calculate_uk_location_electricity(
        FakeSession([(ember, _dataset(publisher="Ember"))]),
        country="Pakistan",
        grid_region="national",
        quantity=1,
        unit="kWh",
        period="2025-01",
    )
    assert "Ember" in result["error"]


def test_missing_country_does_not_receive_an_invented_factor():
    result = calculate_uk_location_electricity(
        FakeSession([]),
        country="France",
        grid_region="national",
        quantity=10,
        unit="kWh",
        period="2025-01",
    )
    assert result["status"] == "missing_factor"


def test_uk_heat_uses_the_complete_co2e_factor_and_ignores_client_gases():
    session = FakeSession([(_heat(), _dataset())])
    result = calculate_uk_purchased_heat_steam(
        session,
        country="United Kingdom",
        energy_form="purchased steam",
        quantity=Decimal("10"),
        unit="kWh",
        period="2025-04",
        co2_factor=Decimal("0.17355"),
        ch4_factor=Decimal("1.25"),
        emission_factor=Decimal("66.33"),
        emissions_tco2e=Decimal("99"),
    )
    assert result["total_kg_co2e"] == "1.75290000"
    assert result["total_t_co2e"] == "0.00175290"
    assert result["gases"]["co2e"]["mass_kg"] == "1.75290000"
    assert "ch4" not in result["gases"]
    assert result["factor"]["value"] == "0.17529000"


def test_co2_only_fallback_epa_steam_and_pakistan_do_not_calculate():
    co2_only = _heat(kg_co2e=Decimal("0.17355"))
    result = calculate_uk_purchased_heat_steam(
        FakeSession([(co2_only, _dataset())]),
        country="UK",
        energy_form="district heat",
        quantity=1,
        unit="kWh",
        period="2025-01",
    )
    assert result["ok"] is False

    epa = _heat(
        unit="kg CO2 / mmBtu",
        kg_co2e=Decimal("66.33"),
        attributes={"source_document": "US EPA Table 7 Steam and Heat"},
    )
    result = calculate_uk_purchased_heat_steam(
        FakeSession([(epa, _dataset(publisher="US EPA", code="heat_and_steam_ebt"))]),
        country="UK",
        energy_form="purchased heat",
        quantity=1,
        unit="mmBtu",
        period="2025-01",
    )
    assert result["ok"] is False

    pakistan = _heat(attributes={"country": "Pakistan"})
    result = calculate_uk_purchased_heat_steam(
        FakeSession([(pakistan, _dataset())]),
        country="Pakistan",
        energy_form="purchased heat",
        quantity=100,
        unit="kWh",
        period="2025-01",
    )
    assert result["ok"] is False
    assert "not applied" in result["error"]

    onsite = calculate_uk_purchased_heat_steam(
        FakeSession([(_heat(), _dataset())]),
        country="UK",
        energy_form="onsite combustion",
        quantity=1,
        unit="kWh",
        period="2025-01",
    )
    assert onsite["status"] == "onsite_combustion"


def test_save_keeps_the_factor_row_and_does_not_use_an_epa_assessment():
    session = FakeSession([(_electricity(), _dataset())])
    saved = save_uk_electricity_record(
        session,
        _ctx(),
        country="UK",
        grid_region="national",
        quantity=Decimal("1000"),
        unit="kWh",
        period="2025-06",
        assessment_id=ASSESSMENT_ID,
        counterparty_id=COUNTERPARTY_ID,
    )
    row = session.added[0]
    assert isinstance(row, EmissionActivity)
    assert row.legacy_source == "scope2_uk_location_electricity_v1"
    assert row.factor_row_id == ROW_ID
    assert row.factor_dataset_id == DATASET_ID
    assert row.emissions_tco2e == Decimal("0.17700000")
    assert saved["emissions_tco2e"] == "0.17700000"
    assert row.raw["contractual_renewable"]["applied_to_location_total"] is False
    assert session.committed is True

    epa_session = FakeSession([(_electricity(), _dataset())], framework="epa")
    try:
        save_uk_electricity_record(
            epa_session,
            _ctx(),
            country="UK",
            grid_region="national",
            quantity=Decimal("1000"),
            unit="kWh",
            period="2025-06",
            assessment_id=ASSESSMENT_ID,
        )
    except Exception as exc:
        assert exc.status_code == 409
    else:
        raise AssertionError("An EPA assessment accepted a UK electricity record")
