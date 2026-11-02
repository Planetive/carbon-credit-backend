"""Location-based purchased electricity. Factors in these tests are fixtures, not published grid factors."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from fastapi_app.auth_models import User
from fastapi_app.auth_org import OrgContext
from fastapi_app.db import get_db
from fastapi_app.factor_models import FactorDataset, FactorRow
from fastapi_app.ghg_calc.scope2_electricity import calculate_location_electricity
from fastapi_app.ghg_calc.scope2_electricity_records import save_scope2_electricity_record
from fastapi_app.ghg_models import EmissionActivity, EmissionAssessment
from fastapi_app.portfolio_models import Counterparty
from fastapi_app.routers import calc as calc_routes
from fastapi_app.routers.deps import require_org_context

ORG_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
OTHER_ORG = uuid.UUID("22222222-2222-2222-2222-222222222222")
USER_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
ASSESSMENT_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
COUNTERPARTY_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")
DATASET_ID = uuid.UUID("66666666-6666-6666-6666-666666666666")
ROW_ID = uuid.UUID("77777777-7777-7777-7777-777777777777")

# Independent reference: 2,500 kWh × 0.4 kg CO2e/kWh / 1,000 = 1 t CO2e.
# 2.5 MWh is the same 2,500 kWh.
FIXTURE_FACTOR = Decimal("0.4")
FIXTURE_KWH = Decimal("2500")
FIXTURE_MWH = Decimal("2.5")
FIXTURE_TONNES = "1.00000000"


def _attributes(**overrides):
    base = {
        "verification": "verified",
        "method": "location_based",
        "boundary": "consumption",
        "source_document": "Grid Factor Fixture 2024",
        "publication_year": 2024,
        "reporting_year": 2026,
        "country": "Pakistan",
        "grid_region": "national",
        "gas_coverage": "CO2, CH4 and N2O expressed as CO2e",
    }
    base.update(overrides)
    return base


def _dataset(**overrides):
    values = dict(
        id=DATASET_ID,
        code="scope2_grid_electricity_fixture",
        publisher="Fixture Publisher",
        title="Purchased electricity fixture",
        version_label="fixture-2024",
        is_active=True,
        source_notes="Test fixture. Not a NEPRA or IGCEP factor.",
    )
    values.update(overrides)
    return FactorDataset(**values)


def _row(**overrides):
    values = dict(
        id=ROW_ID,
        dataset_id=DATASET_ID,
        category="purchased_electricity",
        label="Pakistan national consumption fixture",
        attributes=_attributes(),
        unit="kg CO2e/kWh",
        kg_co2e=FIXTURE_FACTOR,
        kg_co2=Decimal("0.39"),
        kg_ch4=Decimal("0.00001"),
        kg_n2o=Decimal("0.000002"),
    )
    values.update(overrides)
    return FactorRow(**values)


class FakeQuery:
    def __init__(self, session, model):
        self.session = session
        self.model = model

    def join(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def with_for_update(self):
        self.session.locked = True
        return self

    def all(self):
        return list(self.session.pairs)

    def first(self):
        return self.session.lookup.get(self.model)


class FakeSession:
    def __init__(self, lookup=None, pairs=None):
        self.lookup = lookup or {}
        self.pairs = pairs if pairs is not None else [(_row(), _dataset())]
        self.added = []
        self.committed = False
        self.rolled_back = False
        self.locked = False
        self.flush_error = None

    def query(self, *models):
        return FakeQuery(self, models[0])

    def add(self, row):
        self.added.append(row)

    def flush(self):
        if self.flush_error is not None:
            raise self.flush_error

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def refresh(self, row):
        return None


def _ctx(org_id=ORG_ID):
    return OrgContext(
        user=User(id=USER_ID, email="electricity@example.com", password_hash="x"),
        organization_id=org_id,
        role="admin",
    )


def _owned_session(pairs=None, activity=None, reporting_period="2026", assessment_org=ORG_ID, counterparty_org=ORG_ID):
    lookup = {
        EmissionAssessment: EmissionAssessment(
            id=ASSESSMENT_ID,
            organization_id=assessment_org,
            user_id=USER_ID,
            framework="epa",
            reporting_period=reporting_period,
        ),
        Counterparty: Counterparty(
            id=COUNTERPARTY_ID,
            user_id=USER_ID,
            name="Branch",
            sector="Banking",
            geography="Pakistan",
            organization_id=counterparty_org,
        ),
    }
    if activity is not None:
        lookup[EmissionActivity] = activity
    return FakeSession(lookup, pairs=pairs)


def _save(session, **overrides):
    payload = dict(
        db=session,
        ctx=_ctx(),
        country="Pakistan",
        quantity=FIXTURE_KWH,
        unit="kWh",
        period="2026-06",
        assessment_id=ASSESSMENT_ID,
        counterparty_id=COUNTERPARTY_ID,
        grid_region="national",
    )
    payload.update(overrides)
    return save_scope2_electricity_record(**payload)


def test_kwh_and_mwh_use_the_same_verified_factor():
    kwh = calculate_location_electricity(
        FakeSession(),
        country="Pakistan",
        quantity=FIXTURE_KWH,
        unit="kWh",
        period="2026-06",
        grid_factor=Decimal("0.425"),
        emissions_tco2e=Decimal("99"),
    )
    mwh = calculate_location_electricity(
        FakeSession(),
        country="pakistan",
        quantity=FIXTURE_MWH,
        unit="MWh",
        period="2026-06",
    )
    assert kwh["save_allowed"] is True
    assert kwh["total_t_co2e"] == FIXTURE_TONNES
    assert kwh["total_kg_co2e"] == "1000.00000000"
    assert mwh["total_t_co2e"] == FIXTURE_TONNES
    assert mwh["electricity_kwh"] == "2500.00000000"
    assert kwh["factor"]["value"] == "0.40000000"
    assert kwh["factor"]["source_document"] == "Grid Factor Fixture 2024"
    assert kwh["gases"]["co2"]["mass_kg"] == "975.00000000"
    assert kwh["renewable_applied"] is False


def test_renewable_claim_does_not_reduce_location_based_emissions():
    claimed = calculate_location_electricity(
        FakeSession(),
        country="Pakistan",
        quantity=FIXTURE_KWH,
        unit="kWh",
        period="2026-06",
        renewable_kwh=FIXTURE_KWH,
    )
    assert claimed["total_t_co2e"] == FIXTURE_TONNES
    assert claimed["renewable_kwh"] == "2500.00000000"
    assert claimed["renewable_applied"] is False


def test_desnz_electricity_generated_is_not_an_epa_consumption_factor():
    row = _row(
        label="Electricity generated, Electricity: UK",
        kg_co2e=Decimal("0.17700"),
        kg_co2=None,
        kg_ch4=None,
        kg_n2o=None,
        attributes=_attributes(
            boundary="electricity_generated",
            source_document="Greenhouse gas reporting: conversion factors 2025, Electricity generated",
            publication_year=2025,
            reporting_year=2025,
            country="United Kingdom",
            grid_region="national",
        ),
    )
    dataset = _dataset(
        code="desnz_ghg_conversion_factors_2025",
        publisher="Department for Energy Security and Net Zero (DESNZ)",
        title="Greenhouse gas reporting: conversion factors 2025",
    )
    result = calculate_location_electricity(
        FakeSession(pairs=[(row, dataset)]),
        country="United Kingdom",
        grid_region="national",
        quantity=Decimal("1000"),
        unit="kWh",
        period="2025-06",
    )
    assert result["status"] == "missing_factor"
    assert result["ok"] is False


def test_missing_factor_does_not_invent_a_result():
    result = calculate_location_electricity(
        FakeSession(pairs=[]),
        country="Pakistan",
        quantity=FIXTURE_KWH,
        unit="kWh",
        period="2026-06",
        grid_factor=Decimal("0.425"),
    )
    assert result["ok"] is False
    assert result["status"] == "missing_factor"
    assert "0.425" not in result["error"]
    assert "not calculated" in result["error"]


def test_generation_intensity_and_placeholder_rows_are_not_used():
    generation = _row(
        id=uuid.uuid4(),
        attributes=_attributes(boundary="generation", source_document="IGCEP-like fixture"),
        kg_co2e=Decimal("0.278"),
    )
    placeholder = _row(
        id=uuid.uuid4(),
        attributes=_attributes(verification="placeholder"),
        kg_co2e=Decimal("0.425"),
    )
    session = FakeSession(pairs=[(generation, _dataset()), (placeholder, _dataset(publisher="placeholder"))])
    result = calculate_location_electricity(
        session,
        country="Pakistan",
        quantity=Decimal("1000"),
        unit="kWh",
        period="2026-06",
    )
    assert result["status"] == "missing_factor"


def test_co2_only_factor_is_disclosed_and_not_relabelled():
    row = _row(
        unit="kg CO2/kWh",
        kg_co2e=None,
        kg_co2=Decimal("0.2"),
        attributes=_attributes(gas_coverage="CO2 only"),
    )
    result = calculate_location_electricity(
        FakeSession(pairs=[(row, _dataset())]),
        country="Pakistan",
        quantity=Decimal("1000"),
        unit="kWh",
        period="2026-06",
    )
    assert result["save_allowed"] is False
    assert result["status"] == "disclosed_co2_not_co2e"
    assert result["total_t_co2"] == "0.20000000"
    assert result["total_t_co2e"] is None
    assert "not reported as tCO2e" in result["error"]


def test_wrong_reporting_year_is_rejected_without_a_write():
    row = _row(attributes=_attributes(reporting_year=2025))
    session = _owned_session(pairs=[(row, _dataset())])
    with pytest.raises(HTTPException) as failed:
        _save(session, period="2025-06")
    assert failed.value.status_code == 422
    assert "does not match" in failed.value.detail
    assert session.added == []
    assert session.committed is False
    assert session.rolled_back is True


def test_other_organization_assessment_and_counterparty_are_rejected():
    other_assessment = _owned_session(assessment_org=OTHER_ORG)
    with pytest.raises(HTTPException) as assessment_error:
        _save(other_assessment)
    assert assessment_error.value.status_code == 404
    assert other_assessment.added == []

    other_counterparty = _owned_session(counterparty_org=OTHER_ORG)
    with pytest.raises(HTTPException) as counterparty_error:
        _save(other_counterparty)
    assert counterparty_error.value.status_code == 403
    assert other_counterparty.committed is False


def test_client_factor_does_not_override_the_stored_factor():
    session = _owned_session()
    saved = _save(session, grid_factor=Decimal("9"), emissions_tco2e=Decimal("9"))
    row = session.added[0]
    assert saved["emissions_tco2e"] == FIXTURE_TONNES
    assert row.emissions_tco2e == Decimal(FIXTURE_TONNES)
    assert row.raw["factor"]["value"] == "0.40000000"
    assert row.scope == 2
    assert row.category == "purchased_electricity"
    assert row.method == "location_based"
    assert row.legacy_source == "scope2_location_electricity_v1"
    assert row.unit == "kWh"
    assert row.quantity == FIXTURE_KWH
    assert row.factor_dataset_id == DATASET_ID
    assert row.factor_row_id == ROW_ID
    assert row.raw["contractual_renewable"]["applied_to_location_total"] is False
    assert row.raw["accounting"]["status"] == "verified"


def test_update_replaces_the_same_activity_and_does_not_add_another():
    existing = EmissionActivity(
        id=uuid.uuid4(),
        assessment_id=ASSESSMENT_ID,
        organization_id=ORG_ID,
        user_id=USER_ID,
        scope=2,
        category="purchased_electricity",
        method="location_based",
        legacy_source="scope2_location_electricity_v1",
        emissions_tco2e=Decimal("9"),
        raw={"old": True},
    )
    session = _owned_session(activity=existing)
    saved = _save(session, activity_id=existing.id, quantity=Decimal("1000"), unit="kWh")
    assert session.added == []
    assert session.locked is True
    assert existing.emissions_tco2e == Decimal("0.40000000")
    assert saved["activity_id"] == str(existing.id)


def test_co2_only_and_missing_factor_do_not_write():
    co2_row = _row(
        unit="kg CO2/kWh",
        kg_co2e=None,
        kg_co2=Decimal("0.2"),
        attributes=_attributes(gas_coverage="CO2 only"),
    )
    co2_session = _owned_session(pairs=[(co2_row, _dataset())])
    with pytest.raises(HTTPException) as co2_error:
        _save(co2_session, quantity=Decimal("1000"))
    assert co2_error.value.status_code == 422
    assert co2_session.added == []
    assert co2_session.committed is False

    empty = _owned_session(pairs=[])
    with pytest.raises(HTTPException):
        _save(empty)
    assert empty.added == []
    assert empty.committed is False


def test_legacy_activity_cannot_be_overwritten():
    legacy = EmissionActivity(
        id=uuid.uuid4(),
        assessment_id=ASSESSMENT_ID,
        organization_id=ORG_ID,
        user_id=USER_ID,
        scope=2,
        category="electricity",
        method="electricity",
        legacy_source="api",
        emissions_tco2e=Decimal("3"),
        raw={"legacy": True},
    )
    session = _owned_session(activity=legacy)
    with pytest.raises(HTTPException) as failed:
        _save(session, activity_id=legacy.id)
    assert failed.value.status_code == 409
    assert legacy.emissions_tco2e == Decimal("3")
    assert session.committed is False


def test_dataset_outside_its_effective_dates_is_not_used():
    dataset = _dataset(effective_from=date(2027, 1, 1), effective_to=date(2027, 12, 31))
    result = calculate_location_electricity(
        FakeSession(pairs=[(_row(), dataset)]),
        country="Pakistan",
        quantity=FIXTURE_KWH,
        unit="kWh",
        period="2026-06",
    )
    assert result["status"] == "missing_factor"


def test_ambiguous_factors_fail_closed():
    second = _row(id=uuid.uuid4())
    result = calculate_location_electricity(
        FakeSession(pairs=[(_row(), _dataset()), (second, _dataset())]),
        country="Pakistan",
        quantity=Decimal("1"),
        unit="kWh",
        period="2026-06",
    )
    assert result["status"] == "ambiguous_factor"


def test_failed_flush_rolls_back():
    session = _owned_session()
    session.flush_error = IntegrityError("INSERT", {}, Exception("constraint"))
    with pytest.raises(HTTPException) as failed:
        _save(session)
    assert failed.value.status_code == 422
    assert session.rolled_back is True
    assert session.committed is False


def test_create_endpoint_ignores_the_client_factor(monkeypatch):
    _ = monkeypatch
    session = _owned_session()
    app = FastAPI()
    app.include_router(calc_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_org_context] = lambda: _ctx()
    app.dependency_overrides[get_db] = lambda: session
    client = TestClient(app)
    response = client.post(
        "/api/v1/calc/scope2/electricity/records",
        json={
            "country": "Pakistan",
            "quantity": "2500",
            "unit": "kWh",
            "period": "2026-06",
            "assessment_id": str(ASSESSMENT_ID),
            "counterparty_id": str(COUNTERPARTY_ID),
            "grid_factor": "0.425",
            "emissions_tco2e": "9",
            "renewable_kwh": "2500",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["emissions_tco2e"] == FIXTURE_TONNES
    assert body["calculation"]["factor"]["value"] == "0.40000000"
    assert body["calculation"]["renewable_applied"] is False
    assert session.added[0].legacy_source == "scope2_location_electricity_v1"


def test_calculate_endpoint_returns_missing_factor_without_writing():
    session = _owned_session(pairs=[])
    app = FastAPI()
    app.include_router(calc_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_org_context] = lambda: _ctx()
    app.dependency_overrides[get_db] = lambda: session
    client = TestClient(app)
    response = client.post(
        "/api/v1/calc/scope2/electricity",
        json={
            "country": "Pakistan",
            "quantity": "1000",
            "unit": "kWh",
            "period": "2026-06",
            "grid_factor": "0.425",
        },
    )
    assert response.status_code == 422
    assert session.added == []
    assert "0.425" not in response.json()["detail"]
