"""Saving EPA mobile combustion records. No live database and no factor writes."""

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
from fastapi_app.ghg_calc.mobile_records import save_epa_mobile_record
from fastapi_app.ghg_models import EmissionActivity, EmissionAssessment
from fastapi_app.portfolio_models import Counterparty
from fastapi_app.routers import calc as calc_routes
from fastapi_app.routers.deps import require_org_context
from tests.test_mobile_combustion import _sheets

ORG_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
OTHER_ORG_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
USER_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
ASSESSMENT_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
COUNTERPARTY_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")


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
    return User(id=USER_ID, email="mobile@example.com", password_hash="x")


def _ctx(org_id=ORG_ID):
    return OrgContext(user=_user(), organization_id=org_id, role="admin")


def _factor_sheets():
    sheets = []
    for index, sheet in enumerate(_sheets(), start=1):
        copy = dict(sheet)
        dataset_id = uuid.UUID(int=index)
        copy["dataset_id"] = str(dataset_id)
        copy["rows"] = []
        for row_index, row in enumerate(sheet["rows"], start=1):
            stamped = dict(row)
            stamped["_factor_dataset_id"] = str(dataset_id)
            stamped["_factor_row_id"] = str(uuid.UUID(int=index * 100 + row_index))
            copy["rows"].append(stamped)
        sheets.append(copy)
    return sheets


def _session(activity=None, counterparty=True, assessment=True, assessment_org=ORG_ID, counterparty_org=ORG_ID, reporting_period="2026"):
    lookup = {}
    if assessment:
        lookup[EmissionAssessment] = EmissionAssessment(
            id=ASSESSMENT_ID,
            organization_id=assessment_org,
            user_id=USER_ID,
            framework="epa",
            reporting_period=reporting_period,
        )
    if counterparty:
        lookup[Counterparty] = Counterparty(
            id=COUNTERPARTY_ID,
            user_id=USER_ID,
            name="Fleet",
            sector="Transport",
            geography="US",
            organization_id=counterparty_org,
        )
    if activity is not None:
        lookup[EmissionActivity] = activity
    return FakeSession(lookup)


def _save(session, **overrides):
    payload = dict(
        db=session,
        ctx=_ctx(),
        sheets=_factor_sheets(),
        road_class="on_road",
        vehicle_type="Passenger Cars",
        fuel_type="Motor Gasoline",
        fuel_quantity=Decimal("10"),
        fuel_unit="gallon",
        distance=Decimal("100"),
        distance_unit="mile",
        model_year=2020,
        assessment_id=ASSESSMENT_ID,
        counterparty_id=COUNTERPARTY_ID,
        equipment_id="VAN-1",
        site="Depot",
        period="2026-10",
        factor=1,
        total_t_co2e=Decimal("999"),
    )
    payload.update(overrides)
    return save_epa_mobile_record(**payload)


def _mobile_row(**overrides):
    values = dict(
        id=uuid.uuid4(),
        assessment_id=ASSESSMENT_ID,
        organization_id=ORG_ID,
        user_id=USER_ID,
        scope=1,
        category="mobile_combustion",
        method="epa_mobile_v1",
        legacy_source="epa_mobile_v1",
        emissions_tco2e=Decimal("1"),
        quantity=Decimal("1"),
        unit="gallon",
        raw={"old": True},
    )
    values.update(overrides)
    return EmissionActivity(**values)


def test_on_road_save_stores_scope1_tonnes_and_one_row():
    session = _session()
    saved = _save(session)
    row = session.added[0]

    assert session.committed is True
    assert len(session.added) == 1
    assert saved["emissions_tco2e"] == "0.088358"
    assert saved["biogenic_co2_t"] == "0"
    assert row.emissions_tco2e == Decimal("0.088358")
    assert row.emissions_tco2e != Decimal("88.358")
    assert row.quantity == Decimal("10")
    assert row.unit == "gallon"
    assert row.scope == 1
    assert row.category == "mobile_combustion"
    assert row.method == "epa_mobile_v1"
    assert row.legacy_source == "epa_mobile_v1"
    assert row.organization_id == ORG_ID
    assert row.counterparty_id == COUNTERPARTY_ID
    assert row.assessment_id == ASSESSMENT_ID
    assert row.raw["gases"]["co2"]["mass_kg"] == "87.8"
    assert row.raw["gases"]["ch4"]["mass_kg"] == "0.001"
    assert row.raw["gases"]["n2o"]["mass_kg"] == "0.002"
    assert row.raw["total_t_co2e"] == "0.088358"
    assert Decimal(row.raw["gases"]["co2"]["mass_kg"]) / Decimal("1000") != row.emissions_tco2e
    assert row.factor_row_id == uuid.UUID(row.raw["factors"]["co2"]["factor_row_id"])
    assert row.factor_dataset_id == uuid.UUID(row.raw["factors"]["co2"]["dataset_id"])
    assert row.raw["factors"]["co2"]["dataset_code"] == "mobile_combustion"
    assert row.raw["factors"]["co2"]["unit"] == "kg CO2 / gallon"
    assert row.raw["factors"]["ch4"]["dataset_code"] == "on_road_gasoline"
    assert row.raw["factors"]["ch4"]["factor_row_id"] != row.raw["factors"]["co2"]["factor_row_id"]
    assert row.raw["factors"]["n2o"]["factor_row_id"] == row.raw["factors"]["ch4"]["factor_row_id"]
    assert row.raw["accounting"]["gwp_version"] == "AR5"
    assert row.raw["accounting"]["methodology"]
    assert row.raw["accounting"]["version"] == "epa_mobile_biogenic_v1"
    assert row.raw["accounting"]["treatment"] == "fossil_scope1"
    meta = row.raw["activity_meta"]
    assert meta["period"] == "2026-10"
    assert meta["road_class"] == "on_road"
    assert meta["vehicle_type"] == "Passenger Cars"
    assert meta["equipment_id"] == "VAN-1"
    assert meta["source_id"] == "VAN-1"
    assert meta["site"] == "Depot"
    assert meta["model_year"] == "2020"
    assert meta["method_version"] == "epa_mobile_biogenic_v1"
    assert row.raw["inputs"]["model_year"] == "2020"
    assert row.raw["inputs"]["distance_unit"] == "mile"


def test_non_road_save_uses_fuel_based_gases_and_one_row():
    session = _session(counterparty=False)
    saved = _save(
        session,
        road_class="non_road",
        vehicle_type="Agricultural Equipment",
        fuel_type="Diesel Fuel",
        fuel_quantity=Decimal("5"),
        fuel_unit="gallon",
        distance=None,
        distance_unit=None,
        model_year=None,
        counterparty_id=None,
        equipment_id="TRACTOR-4",
        site=None,
    )
    row = session.added[0]
    assert len(session.added) == 1
    assert saved["emissions_tco2e"] == "0.05172"
    assert row.emissions_tco2e == Decimal("0.05172")
    assert row.quantity == Decimal("5")
    assert row.unit == "gallon"
    assert row.counterparty_id is None
    assert row.raw["inputs"]["distance"] is None
    assert row.raw["inputs"]["road_class"] == "non_road"
    assert row.raw["factors"]["ch4"]["dataset_code"] == "non_road_vehicle"
    assert row.raw["factors"]["ch4"]["unit"] == "g / gallon"
    assert row.raw["activity_meta"]["equipment_id"] == "TRACTOR-4"
    assert "site" not in row.raw["activity_meta"]
    assert row.raw["biogenic_co2_t"] == "0"


def test_biodiesel_keeps_biogenic_co2_out_of_the_scope_1_column():
    session = _session()
    saved = _save(
        session,
        vehicle_type="Light-Duty Cars",
        fuel_type="Biodiesel (100%)",
        fuel_quantity=Decimal("1"),
        distance=Decimal("10"),
        model_year=None,
    )
    row = session.added[0]
    assert saved["emissions_tco2e"] == "0.0000558"
    assert saved["biogenic_co2_t"] == "0.00945"
    assert row.emissions_tco2e == Decimal("0.0000558")
    assert row.raw["biogenic_co2_t"] == "0.00945"
    assert row.raw["gases"]["co2"]["mass_kg"] == "9.45"
    assert row.raw["gases"]["co2"]["reporting"] == "biogenic_outside_scope1"
    assert row.raw["accounting"]["treatment"] == "biogenic_co2_outside_scope1"
    assert row.emissions_tco2e != Decimal(row.raw["biogenic_co2_t"])


def test_update_recalculates_only_the_existing_mobile_record():
    existing = _mobile_row()
    session = _session(activity=existing)
    saved = _save(session, activity_id=existing.id, fuel_quantity=Decimal("1"))
    assert session.locked is True
    assert session.committed is True
    assert session.added == []
    assert existing.emissions_tco2e == Decimal("0.009338")
    assert saved["activity_id"] == str(existing.id)
    assert saved["emissions_tco2e"] == "0.009338"
    assert existing.raw["gases"]["co2"]["mass_kg"] == "8.78"
    assert existing.raw["activity_meta"]["period"] == "2026-10"
    assert existing.quantity == Decimal("1")


def test_client_supplied_total_does_not_change_the_stored_result():
    session = _session()
    saved = _save(session, emissions_tco2e="0", factor=999, total_t_co2e="0.1")
    assert saved["emissions_tco2e"] == "0.088358"
    assert session.added[0].emissions_tco2e == Decimal("0.088358")
    assert len(session.added) == 1


def test_invalid_input_and_missing_factors_do_not_write():
    session = _session()
    with pytest.raises(HTTPException) as missing:
        _save(session, vehicle_type="Motorcycles")
    assert missing.value.status_code == 422
    assert session.added == []
    assert session.committed is False

    with pytest.raises(HTTPException) as bad_unit:
        _save(_session(), fuel_unit="kg")
    assert bad_unit.value.status_code == 422

    with pytest.raises(HTTPException) as bad_period:
        _save(_session(), period="2026")
    assert bad_period.value.status_code == 422
    assert bad_period.value.detail == "period must be YYYY-MM"

    optional = _session()
    saved_optional = _save(optional, equipment_id="  ")
    assert saved_optional["emissions_tco2e"] == "0.088358"
    assert "equipment_id" not in optional.added[0].raw["activity_meta"]
    assert len(optional.added) == 1

    blend_session = _session()
    with pytest.raises(HTTPException) as blend:
        _save(blend_session, fuel_type="B20", vehicle_type="Light-Duty Cars", model_year=None)
    assert blend.value.status_code == 422
    assert blend_session.added == []
    assert blend_session.committed is False


def test_counterparty_and_assessment_from_another_organization_are_rejected():
    foreign_counterparty = _session(counterparty_org=OTHER_ORG_ID)
    with pytest.raises(HTTPException) as denied:
        _save(foreign_counterparty)
    assert denied.value.status_code == 403
    assert foreign_counterparty.committed is False
    assert foreign_counterparty.rolled_back is True
    assert foreign_counterparty.added == []

    foreign_assessment = _session(assessment_org=OTHER_ORG_ID)
    with pytest.raises(HTTPException) as missing_assessment:
        _save(foreign_assessment)
    assert missing_assessment.value.status_code == 404
    assert foreign_assessment.committed is False
    assert foreign_assessment.added == []


def test_period_year_must_match_the_assessment_on_create_and_update():
    created = _session(reporting_period="2025")
    with pytest.raises(HTTPException) as mismatch:
        _save(created, period="2026-10")
    assert mismatch.value.status_code == 422
    assert "does not match the assessment reporting year" in mismatch.value.detail
    assert created.added == []
    assert created.committed is False

    existing = _mobile_row()
    original_total = existing.emissions_tco2e
    original_raw = dict(existing.raw)
    updated = _session(activity=existing, reporting_period="2025")
    with pytest.raises(HTTPException) as update_mismatch:
        _save(updated, activity_id=existing.id, period="2026-10")
    assert update_mismatch.value.status_code == 422
    assert existing.emissions_tco2e == original_total
    assert existing.raw == original_raw
    assert updated.committed is False
    assert updated.added == []


def test_record_from_another_organization_is_not_edited():
    foreign = _mobile_row(organization_id=OTHER_ORG_ID, emissions_tco2e=Decimal("4"))
    session = _session(activity=foreign)
    with pytest.raises(HTTPException) as missing:
        _save(session, activity_id=foreign.id)
    assert missing.value.status_code == 404
    assert foreign.emissions_tco2e == Decimal("4")
    assert foreign.raw == {"old": True}
    assert session.committed is False
    assert session.rolled_back is True
    assert session.added == []


def test_historical_stationary_and_uk_records_are_not_modified():
    historical = _mobile_row(
        method="activity_data",
        legacy_source="scope1_mobile_fuel_entries",
        category="mobile",
        emissions_tco2e=Decimal("88.358"),
        raw={"legacy_kg": True},
    )
    stationary = _mobile_row(
        method="epa_stationary",
        legacy_source="epa_stationary",
        category="stationary_combustion",
        emissions_tco2e=Decimal("5.31145"),
    )
    uk = _mobile_row(
        method="uk_fuel",
        legacy_source="uk_fuel",
        category="stationary_combustion",
        emissions_tco2e=Decimal("2"),
    )
    for existing in (historical, stationary, uk):
        session = _session(activity=existing)
        original_total = existing.emissions_tco2e
        original_raw = dict(existing.raw)
        with pytest.raises(HTTPException) as conflict:
            _save(session, activity_id=existing.id)
        assert conflict.value.status_code == 409
        assert existing.emissions_tco2e == original_total
        assert existing.raw == original_raw
        assert session.committed is False
        assert session.added == []


def test_failed_persistence_rolls_back_without_a_second_row():
    session = _session()
    session.flush_error = IntegrityError("INSERT", {}, Exception("constraint"))
    with pytest.raises(HTTPException) as failed:
        _save(session)
    assert failed.value.status_code == 422
    assert session.committed is False
    assert session.rolled_back is True
    assert len(session.added) == 1


def test_create_endpoint_rejects_missing_credentials():
    app = FastAPI()
    app.include_router(calc_routes.router, prefix="/api/v1")
    client = TestClient(app)
    response = client.post(
        "/api/v1/calc/epa/mobile/records",
        json={
            "road_class": "on_road",
            "vehicle_type": "Passenger Cars",
            "fuel_type": "Motor Gasoline",
            "fuel_quantity": "10",
            "fuel_unit": "gallon",
            "distance": "100",
            "distance_unit": "mile",
            "model_year": 2020,
            "assessment_id": str(ASSESSMENT_ID),
            "equipment_id": "VAN-1",
            "period": "2026-10",
            "total_t_co2e": "999",
            "factor": 1,
        },
    )
    assert response.status_code in (401, 403)


def test_create_and_update_endpoints_store_the_backend_total(monkeypatch):
    session = _session()
    monkeypatch.setattr(calc_routes, "load_mobile_factor_sheets", lambda db: _factor_sheets())
    app = FastAPI()
    app.include_router(calc_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_org_context] = lambda: _ctx()
    app.dependency_overrides[get_db] = lambda: session
    client = TestClient(app)
    created = client.post(
        "/api/v1/calc/epa/mobile/records",
        json={
            "road_class": "on_road",
            "vehicle_type": "Passenger Cars",
            "fuel_type": "Motor Gasoline",
            "fuel_quantity": "10",
            "fuel_unit": "gallon",
            "distance": "100",
            "distance_unit": "mile",
            "model_year": 2020,
            "assessment_id": str(ASSESSMENT_ID),
            "counterparty_id": str(COUNTERPARTY_ID),
            "equipment_id": "VAN-1",
            "site": "Depot",
            "period": "2026-10",
            "total_t_co2e": "999",
            "factor": 1,
            "emissions": "0",
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["emissions_tco2e"] == "0.088358"
    assert body["biogenic_co2_t"] == "0"
    assert body["calculation"]["total_kg_co2e"] == "88.358"
    assert len(session.added) == 1
    assert session.added[0].emissions_tco2e == Decimal("0.088358")

    incomplete = client.post(
        "/api/v1/calc/epa/mobile/records",
        json={"road_class": "on_road", "fuel_quantity": "10"},
    )
    assert incomplete.status_code == 422
    assert len(session.added) == 1

    existing = session.added[0]
    session.lookup[EmissionActivity] = existing
    session.added = []
    updated = client.patch(
        f"/api/v1/calc/epa/mobile/records/{existing.id}",
        json={
            "road_class": "on_road",
            "vehicle_type": "Passenger Cars",
            "fuel_type": "Motor Gasoline",
            "fuel_quantity": "1",
            "fuel_unit": "gallon",
            "distance": "100",
            "distance_unit": "mile",
            "model_year": 2020,
            "assessment_id": str(ASSESSMENT_ID),
            "equipment_id": "VAN-1",
            "period": "2026-10",
            "total_t_co2e": "0",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["activity_id"] == str(existing.id)
    assert updated.json()["emissions_tco2e"] == "0.009338"
    assert session.added == []
    assert existing.emissions_tco2e == Decimal("0.009338")
