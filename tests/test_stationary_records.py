"""Saving EPA stationary combustion records. No live database and no factor writes."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from fastapi_app.auth_models import User
from fastapi_app.auth_org import OrgContext
from fastapi_app.db import get_db
from fastapi_app.ghg_calc.stationary_records import save_epa_stationary_record
from fastapi_app.ghg_models import EmissionActivity, EmissionAssessment
from fastapi_app.portfolio_models import Counterparty
from fastapi_app.routers import calc as calc_routes
from fastapi_app.routers.deps import require_org_context
from tests.test_stationary_combustion import MSW, SHEETS, WOOD

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

    def filter(self, *args, **kwargs):
        return self

    def with_for_update(self):
        self.session.locked = True
        return self

    def first(self):
        return self.session.lookup.get(self.model)


class FakeSession:
    def __init__(self, lookup):
        self.lookup = lookup
        self.added = []
        self.committed = False
        self.rolled_back = False
        self.locked = False
        self.flush_error = None

    def query(self, model):
        return FakeQuery(self, model)

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

    def close(self):
        return None


def _user():
    return User(id=USER_ID, email="stationary@example.com", password_hash="x")


def _ctx(org_id=ORG_ID):
    return OrgContext(user=_user(), organization_id=org_id, role="admin")


def _sheets():
    sheets = []
    for sheet in SHEETS:
        copy = dict(sheet)
        copy["rows"] = [dict(row) for row in sheet["rows"]]
        if copy["dataset_code"] == "fuel_epa_2":
            copy["dataset_id"] = str(DATASET_ID)
            copy["rows"][0]["_factor_dataset_id"] = str(DATASET_ID)
            copy["rows"][0]["_factor_row_id"] = str(ROW_ID)
        sheets.append(copy)
    return sheets


def _session(activity=None, counterparty=True, assessment=True, reporting_period="2026"):
    lookup = {}
    if assessment:
        lookup[EmissionAssessment] = EmissionAssessment(
            id=ASSESSMENT_ID,
            organization_id=ORG_ID,
            user_id=USER_ID,
            framework="epa",
            reporting_period=reporting_period,
        )
    if counterparty:
        lookup[Counterparty] = Counterparty(
            id=COUNTERPARTY_ID,
            user_id=USER_ID,
            name="Plant",
            sector="Energy",
            geography="US",
            organization_id=ORG_ID,
        )
    if activity is not None:
        lookup[EmissionActivity] = activity
    return FakeSession(lookup)


def _save(session, **overrides):
    payload = dict(
        db=session,
        ctx=_ctx(),
        sheets=_sheets(),
        fuel="Natural Gas",
        quantity=Decimal("100"),
        unit="mmBtu",
        assessment_id=ASSESSMENT_ID,
        counterparty_id=COUNTERPARTY_ID,
        equipment_type="Boiler",
        site="North plant",
        equipment_id="BLR-1",
        period="2026-10",
    )
    payload.update(overrides)
    return save_epa_stationary_record(**payload)


def test_save_stores_calculated_tonnes_and_metadata():
    session = _session()
    saved = _save(session, emissions_tco2e=Decimal("0"), factor=1)
    row = session.added[0]

    assert session.committed is True
    assert saved["emissions_tco2e"] == "5.31145"
    assert row.emissions_tco2e == Decimal("5.31145")
    assert row.organization_id == ORG_ID
    assert row.counterparty_id == COUNTERPARTY_ID
    assert row.scope == 1
    assert row.method == "epa_stationary"
    assert row.legacy_source == "epa_stationary"
    assert row.quantity == Decimal("100")
    assert row.unit == "mmBtu"
    assert row.factor_dataset_id == DATASET_ID
    assert row.factor_row_id == ROW_ID
    assert row.raw["gases"]["ch4"]["mass_kg"] == "0.1"
    assert row.raw["gases"]["n2o"]["co2e_kg"] == "2.65"
    assert row.raw["factors"]["co2"]["value"] == "53.06"
    assert row.raw["factor_source"]["version_label"] == "imported_from_sheet"
    assert row.raw["factor_source"]["gwp_version"] == "AR5"
    assert "publication_year" not in row.raw["factor_source"]
    meta = row.raw["activity_meta"]
    assert meta["equipment_type"] == "Boiler"
    assert meta["site"] == "North plant"
    assert meta["equipment_id"] == "BLR-1"
    assert meta["source_id"] == "BLR-1"
    assert meta["period"] == "2026-10"
    assert meta["method_version"] == "epa_stationary_biogenic_v1"
    assert row.raw["accounting"]["treatment"] == "fossil_scope1"
    assert row.raw["biogenic_co2_t"] == "0"
    assert row.raw["accounting"]["gwp_version"] == "AR5"


def test_wood_save_keeps_biogenic_co2_out_of_the_scope_1_column():
    sheets = _sheets()
    sheets.append(
        {
            "publisher": "EPA",
            "dataset_code": "fuel_epa_1",
            "dataset_title": "Fuel EPA 1",
            "version_label": "imported_from_sheet",
            "rows": [dict(WOOD)],
        }
    )
    session = _session()
    saved = _save(
        session,
        sheets=sheets,
        fuel="Wood and Wood Residuals",
        quantity=Decimal("1"),
        unit="short ton",
    )
    row = session.added[0]
    assert saved["emissions_tco2e"] == "0.020223"
    assert row.emissions_tco2e == Decimal("0.020223")
    assert row.raw["biogenic_co2_t"] == "1.64"
    assert row.raw["accounting"]["treatment"] == "biogenic_co2_outside_scope1"
    assert row.raw["gases"]["co2"]["mass_kg"] == "1640"
    assert Decimal(row.raw["total_t_co2e"]) + Decimal(row.raw["biogenic_co2_t"]) != row.emissions_tco2e


def test_municipal_solid_waste_is_not_saved():
    sheets = _sheets()
    sheets.append(
        {
            "publisher": "EPA",
            "dataset_code": "fuel_epa_1",
            "dataset_title": "Fuel EPA 1",
            "version_label": "imported_from_sheet",
            "rows": [dict(MSW)],
        }
    )
    session = _session()
    with pytest.raises(HTTPException) as raised:
        _save(session, sheets=sheets, fuel="Municipal Solid Waste", quantity=Decimal("1"), unit="mmBtu")
    assert raised.value.status_code == 422
    assert session.added == []
    assert session.committed is False


def test_client_supplied_total_does_not_change_the_stored_result():
    session = _session()
    saved = _save(session, emissions_tco2e="0", factor=999, total_t_co2e="0.1")
    assert saved["emissions_tco2e"] == "5.31145"
    assert session.added[0].emissions_tco2e == Decimal("5.31145")


def test_invalid_input_does_not_write():
    session = _session()
    with pytest.raises(HTTPException) as bad_unit:
        _save(session, unit="kg")
    assert bad_unit.value.status_code == 422
    assert session.added == []
    assert session.committed is False

    with pytest.raises(HTTPException) as bad_period:
        _save(_session(), period="2026/10")
    assert bad_period.value.status_code == 422
    assert bad_period.value.detail == "period must be YYYY-MM"

    session = _session()
    with pytest.raises(HTTPException) as missing_period:
        _save(session, period=None)
    assert missing_period.value.status_code == 422
    assert missing_period.value.detail == "period must be YYYY-MM"
    assert session.added == []
    assert session.committed is False

    invalid_month = _session()
    with pytest.raises(HTTPException) as month:
        _save(invalid_month, period="2026-13")
    assert month.value.status_code == 422
    assert month.value.detail == "period must be YYYY-MM"
    assert invalid_month.added == []
    assert invalid_month.committed is False


def test_period_year_must_match_the_assessment_and_writes_nothing():
    session = _session(reporting_period="2025")
    with pytest.raises(HTTPException) as mismatch:
        _save(session, period="2026-10")
    assert mismatch.value.status_code == 422
    assert "does not match the assessment reporting year" in mismatch.value.detail
    assert session.added == []
    assert session.committed is False
    assert session.rolled_back is True


def test_counterparty_from_another_organization_is_rejected():
    session = _session(counterparty=False)
    with pytest.raises(HTTPException) as denied:
        _save(session)
    assert denied.value.status_code == 403
    assert session.committed is False
    assert session.rolled_back is True
    assert session.added == []


def test_historical_record_is_not_modified():
    historical = EmissionActivity(
        id=uuid.uuid4(),
        assessment_id=ASSESSMENT_ID,
        organization_id=ORG_ID,
        user_id=USER_ID,
        scope=1,
        category="stationary_combustion",
        method="epa_fuel",
        legacy_source="scope1_fuel_entries",
        emissions_tco2e=Decimal("9"),
        quantity=Decimal("1"),
        unit="mmBtu",
        raw={"old": True},
    )
    session = _session(activity=historical)
    with pytest.raises(HTTPException) as conflict:
        _save(session, activity_id=historical.id)
    assert conflict.value.status_code == 409
    assert historical.emissions_tco2e == Decimal("9")
    assert historical.raw == {"old": True}
    assert session.committed is False
    assert session.added == []


def test_failed_persistence_rolls_back():
    session = _session()
    session.flush_error = IntegrityError("INSERT", {}, Exception("constraint"))
    with pytest.raises(HTTPException) as failed:
        _save(session)
    assert failed.value.status_code == 422
    assert session.committed is False
    assert session.rolled_back is True


def test_update_recalculates_an_existing_stationary_record():
    existing = EmissionActivity(
        id=uuid.uuid4(),
        assessment_id=ASSESSMENT_ID,
        organization_id=ORG_ID,
        user_id=USER_ID,
        scope=1,
        category="stationary_combustion",
        method="epa_stationary",
        legacy_source="epa_stationary",
        emissions_tco2e=Decimal("1"),
        raw={},
    )
    session = _session(activity=existing)
    saved = _save(session, activity_id=existing.id, quantity=Decimal("1"))
    assert session.locked is True
    assert session.committed is True
    assert session.added == []
    assert existing.emissions_tco2e == Decimal("0.0531145")
    assert saved["emissions_tco2e"] == "0.0531145"


def test_create_endpoint_rejects_missing_credentials():
    app = FastAPI()
    app.include_router(calc_routes.router, prefix="/api/v1")
    client = TestClient(app)
    response = client.post(
        "/api/v1/calc/epa/stationary/records",
        json={
            "fuel": "Natural Gas",
            "quantity": "100",
            "unit": "mmBtu",
            "assessment_id": str(ASSESSMENT_ID),
            "equipment_type": "Boiler",
            "period": "2026-10",
            "emissions_tco2e": "0",
            "factor": 1,
        },
    )
    assert response.status_code in (401, 403)


def test_create_endpoint_rejects_a_missing_period_without_writing(monkeypatch):
    session = _session()
    monkeypatch.setattr(calc_routes, "_stationary_factor_sheets", lambda db: _sheets())
    app = FastAPI()
    app.include_router(calc_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_org_context] = lambda: _ctx()
    app.dependency_overrides[get_db] = lambda: session
    client = TestClient(app)
    response = client.post(
        "/api/v1/calc/epa/stationary/records",
        json={
            "fuel": "Natural Gas",
            "quantity": "100",
            "unit": "mmBtu",
            "assessment_id": str(ASSESSMENT_ID),
            "equipment_type": "Boiler",
        },
    )
    assert response.status_code == 422
    assert session.added == []
    assert session.committed is False


def test_create_endpoint_stores_backend_total(monkeypatch):
    session = _session()
    monkeypatch.setattr(calc_routes, "_stationary_factor_sheets", lambda db: _sheets())
    app = FastAPI()
    app.include_router(calc_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_org_context] = lambda: _ctx()
    app.dependency_overrides[get_db] = lambda: session
    client = TestClient(app)
    response = client.post(
        "/api/v1/calc/epa/stationary/records",
        json={
            "fuel": "Natural Gas",
            "quantity": "100",
            "unit": "mmBtu",
            "assessment_id": str(ASSESSMENT_ID),
            "counterparty_id": str(COUNTERPARTY_ID),
            "equipment_type": "Boiler",
            "site": "North plant",
            "equipment_id": "BLR-1",
            "period": "2026-10",
            "emissions_tco2e": "0",
            "factor": 1,
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["emissions_tco2e"] == "5.31145"
    assert body["calculation"]["total_kg_co2e"] == "5311.45"
    assert session.added[0].emissions_tco2e == Decimal("5.31145")
    assert session.added[0].organization_id == ORG_ID
