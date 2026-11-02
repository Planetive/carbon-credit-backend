"""Saving EPA refrigerant leakage records. No live database and no factor writes."""

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
from fastapi_app.ghg_calc.refrigerant_records import save_epa_refrigerant_record
from fastapi_app.ghg_models import EmissionActivity, EmissionAssessment
from fastapi_app.portfolio_models import Counterparty
from fastapi_app.routers import calc as calc_routes
from fastapi_app.routers.deps import require_org_context
from tests.test_refrigerant_leakage import _blend_row, _sheet

ORG_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
OTHER_ORG_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
USER_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
ASSESSMENT_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
COUNTERPARTY_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")
DATASET_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


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
    return User(id=USER_ID, email="refrigerant@example.com", password_hash="x")


def _ctx(org_id=ORG_ID):
    return OrgContext(user=_user(), organization_id=org_id, role="admin")


def _factor_sheets():
    sheet = dict(_sheet())
    sheet["dataset_id"] = str(DATASET_ID)
    rows = []
    for index, row in enumerate(sheet["rows"], start=1):
        stamped = dict(row)
        stamped["_factor_dataset_id"] = str(DATASET_ID)
        stamped["_factor_row_id"] = str(uuid.UUID(int=index))
        rows.append(stamped)
    sheet["rows"] = rows
    return [sheet]


def _session(
    activity=None,
    counterparty=True,
    assessment=True,
    assessment_org=ORG_ID,
    counterparty_org=ORG_ID,
    reporting_period="2026",
):
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
            name="Plant",
            sector="Facilities",
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
        method="leakage_record",
        gas="R-404A",
        leakage_kg=Decimal("2"),
        assessment_id=ASSESSMENT_ID,
        counterparty_id=COUNTERPARTY_ID,
        equipment_type="chiller",
        equipment_id="CH-1",
        site="North plant",
        period="2026-10",
        gwp=1,
        factor=3922,
        factor_row_id=uuid.uuid4(),
        emissions_tco2e=Decimal("0"),
        emissions_kg_co2e=Decimal("1"),
        organization_id=OTHER_ORG_ID,
    )
    payload.update(overrides)
    return save_epa_refrigerant_record(**payload)


def _refrigerant_row(**overrides):
    values = dict(
        id=uuid.uuid4(),
        assessment_id=ASSESSMENT_ID,
        organization_id=ORG_ID,
        user_id=USER_ID,
        scope=1,
        category="refrigerant_leakage",
        method="epa_refrigerant_v1",
        legacy_source="epa_refrigerant_v1",
        emissions_tco2e=Decimal("1"),
        quantity=Decimal("1"),
        unit="kg",
        raw={"old": True},
    )
    values.update(overrides)
    return EmissionActivity(**values)


def test_measured_r404a_stores_scope1_tonnes_and_one_row():
    session = _session()
    saved = _save(session)
    row = session.added[0]

    assert session.committed is True
    assert len(session.added) == 1
    assert isinstance(row, EmissionActivity)
    assert saved["emissions_kg_co2e"] == "7886"
    assert saved["emissions_tco2e"] == "7.886"
    assert row.emissions_tco2e == Decimal("7.886")
    assert row.emissions_tco2e != Decimal("7886")
    assert row.quantity == Decimal("2")
    assert row.unit == "kg"
    assert row.scope == 1
    assert row.category == "refrigerant_leakage"
    assert row.method == "epa_refrigerant_v1"
    assert row.legacy_source == "epa_refrigerant_v1"
    assert row.organization_id == ORG_ID
    assert row.organization_id != OTHER_ORG_ID
    assert row.counterparty_id == COUNTERPARTY_ID
    assert row.assessment_id == ASSESSMENT_ID
    assert row.user_id == USER_ID
    assert row.raw["inputs"]["method"] == "leakage_record"
    assert row.raw["inputs"]["refrigerant"] == "R-404A"
    assert row.raw["inputs"]["leakage_kg"] == "2"
    assert row.raw["inputs"]["leakage_rate_source"] is None
    assert row.raw["gwp"] == "3943"
    assert row.raw["emissions_kg_co2e"] == "7886"
    assert row.raw["emissions_tco2e"] == "7.886"
    assert row.raw["accounting"]["version"] == "epa_refrigerant_v1"
    assert row.raw["dataset_code"] == "epa_refrigerant_gwp"
    assert row.raw["factor_attribute"] == "100-year GWP"
    assert "Table 12" in row.raw["gwp_publication"]
    assert row.factor_dataset_id == DATASET_ID
    assert row.factor_row_id == uuid.UUID(row.raw["factor_row_id"])
    assert row.factor_dataset_id == uuid.UUID(row.raw["dataset_id"])
    meta = row.raw["activity_meta"]
    assert meta["period"] == "2026-10"
    assert meta["equipment_type"] == "chiller"
    assert meta["equipment_id"] == "CH-1"
    assert meta["site"] == "North plant"
    assert meta["method_version"] == "epa_refrigerant_v1"


def test_estimated_hfc134a_uses_the_table11_allowlist():
    session = _session()
    saved = _save(
        session,
        method="estimated_leakage",
        gas="R-134a",
        leakage_kg=None,
        charge_kg=Decimal("10"),
        leakage_rate_percent=Decimal("10"),
        sheets=[],
        equipment_type="vehicle AC",
    )
    row = session.added[0]
    assert len(session.added) == 1
    assert saved["emissions_kg_co2e"] == "1300"
    assert saved["emissions_tco2e"] == "1.3"
    assert row.emissions_tco2e == Decimal("1.3")
    assert row.quantity == Decimal("1")
    assert row.unit == "kg"
    assert row.factor_dataset_id is None
    assert row.factor_row_id is None
    assert row.raw["inputs"]["refrigerant"] == "HFC-134a"
    assert row.raw["inputs"]["method"] == "estimated_leakage"
    assert row.raw["inputs"]["charge_kg"] == "10"
    assert row.raw["inputs"]["leakage_rate_percent"] == "10"
    assert row.raw["inputs"]["leakage_rate_source"] == "user_assumption"
    assert row.raw["gwp"] == "1300"
    assert row.raw["dataset_id"] is None
    assert row.raw["factor_row_id"] is None
    assert "Table 11" in row.raw["table11_reference"]
    assert "not a ref.factor_rows" in row.raw["table11_reference"]
    assert row.raw["activity_meta"]["equipment_type"] == "vehicle AC"


def test_update_recalculates_the_same_row():
    existing = _refrigerant_row()
    session = _session(activity=existing)
    saved = _save(session, activity_id=existing.id, leakage_kg=Decimal("1"))
    assert session.locked is True
    assert session.committed is True
    assert session.added == []
    assert saved["activity_id"] == str(existing.id)
    assert existing.emissions_tco2e == Decimal("3.943")
    assert existing.quantity == Decimal("1")
    assert existing.raw["inputs"]["leakage_kg"] == "1"
    assert existing.raw["emissions_kg_co2e"] == "3943"
    assert existing.id == saved["activity_id"] or existing.id == uuid.UUID(saved["activity_id"])


def test_explicit_zero_rate_stores_zero_tonnes_as_an_assumption():
    session = _session()
    saved = _save(
        session,
        method="estimated_leakage",
        leakage_kg=None,
        charge_kg=Decimal("8"),
        leakage_rate_percent=Decimal("0"),
    )
    row = session.added[0]
    assert saved["emissions_tco2e"] == "0"
    assert saved["emissions_kg_co2e"] == "0"
    assert row.emissions_tco2e == Decimal("0")
    assert row.quantity == Decimal("0")
    assert row.raw["inputs"]["method"] == "estimated_leakage"
    assert row.raw["inputs"]["leakage_rate_percent"] == "0"
    assert row.raw["inputs"]["leakage_rate_source"] == "user_assumption"
    assert row.raw["gwp"] == "3943"


def test_unsupported_and_zero_gwp_blends_are_not_saved():
    hcfc = _session()
    with pytest.raises(HTTPException) as unsupported:
        _save(hcfc, gas="R-401A")
    assert unsupported.value.status_code == 422
    assert "HCFC" in unsupported.value.detail
    assert hcfc.added == []
    assert hcfc.committed is False
    assert hcfc.rolled_back is True

    zero = _session()
    with pytest.raises(HTTPException) as rejected:
        _save(zero, gas="R-406A")
    assert rejected.value.status_code == 422
    assert "zero-GWP" in rejected.value.detail
    assert zero.added == []
    assert zero.committed is False


def test_browser_supplied_gwp_and_total_are_ignored():
    session = _session()
    saved = _save(session, gwp=1, emissions_tco2e=Decimal("0"), emissions_kg_co2e=Decimal("1"), factor=3922)
    row = session.added[0]
    assert saved["emissions_tco2e"] == "7.886"
    assert saved["calculation"]["gwp"] == "3943"
    assert row.emissions_tco2e == Decimal("7.886")
    assert row.raw["gwp"] == "3943"
    assert row.factor_row_id != uuid.UUID(int=0)


def test_organization_and_counterparty_isolation():
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
    assert foreign_assessment.added == []
    assert foreign_assessment.committed is False

    foreign_activity = _refrigerant_row(organization_id=OTHER_ORG_ID, emissions_tco2e=Decimal("4"))
    session = _session(activity=foreign_activity)
    with pytest.raises(HTTPException) as missing:
        _save(session, activity_id=foreign_activity.id)
    assert missing.value.status_code == 404
    assert foreign_activity.emissions_tco2e == Decimal("4")
    assert foreign_activity.raw == {"old": True}
    assert session.added == []
    assert session.committed is False


def test_reporting_month_must_match_the_assessment_year():
    bad_month = _session()
    with pytest.raises(HTTPException) as month:
        _save(bad_month, period="2026-13")
    assert month.value.status_code == 422
    assert month.value.detail == "period must be YYYY-MM"
    assert bad_month.added == []
    assert bad_month.committed is False

    other_year = _session()
    with pytest.raises(HTTPException) as year:
        _save(other_year, period="2025-10")
    assert year.value.status_code == 422
    assert "reporting year" in year.value.detail
    assert other_year.added == []
    assert other_year.committed is False

    blank = _session(reporting_period=None)
    with pytest.raises(HTTPException) as missing_year:
        _save(blank, period="2026-10")
    assert missing_year.value.status_code == 422
    assert blank.added == []
    assert blank.committed is False

    same_year = _session(reporting_period="2026-01")
    saved = _save(same_year, period="2026-02")
    assert saved["raw"]["activity_meta"]["period"] == "2026-02"


def test_missing_and_ambiguous_gwp_factors_do_not_write():
    missing = _session()
    with pytest.raises(HTTPException) as absent:
        _save(
            missing,
            sheets=[
                {
                    "dataset_code": "epa_refrigerant_gwp",
                    "dataset_id": str(DATASET_ID),
                    "version_label": "imported_from_sheet",
                    "is_active": True,
                    "rows": [_blend_row("R-410A", "1,924", "50% HFC-32, 50% HFC-125", str(uuid.uuid4()))],
                }
            ],
        )
    assert absent.value.status_code == 422
    assert "not treated as zero" in absent.value.detail
    assert missing.added == []
    assert missing.committed is False

    malformed = _session()
    with pytest.raises(HTTPException) as bad_text:
        _save(
            malformed,
            gas="R-410A",
            sheets=[
                {
                    "dataset_code": "epa_refrigerant_gwp",
                    "dataset_id": str(DATASET_ID),
                    "version_label": "imported_from_sheet",
                    "is_active": True,
                    "rows": [
                        {
                            "ASHRAE #": "R-410A",
                            "100-year GWP": "not-a-number",
                            "_factor_row_id": str(uuid.uuid4()),
                            "_factor_dataset_id": str(DATASET_ID),
                            "kg_co2e": 1924,
                        }
                    ],
                }
            ],
        )
    assert bad_text.value.status_code == 422
    assert "malformed" in bad_text.value.detail
    assert malformed.added == []

    duplicate = _session()
    row_id = str(uuid.uuid4())
    with pytest.raises(HTTPException) as ambiguous:
        _save(
            duplicate,
            sheets=[
                {
                    "dataset_code": "epa_refrigerant_gwp",
                    "dataset_id": str(DATASET_ID),
                    "version_label": "imported_from_sheet",
                    "is_active": True,
                    "rows": [
                        _blend_row("R-404A", "3943", "44% HFC-125, 4% HFC-134a, 52% HFC-143a", row_id),
                        _blend_row("R-404A", "3922", "44% HFC-125, 4% HFC-134a, 52% HFC-143a", str(uuid.uuid4())),
                    ],
                }
            ],
        )
    assert ambiguous.value.status_code == 422
    assert "More than one" in ambiguous.value.detail
    assert duplicate.added == []
    assert duplicate.committed is False
    assert duplicate.rolled_back is True


def test_failed_persistence_rolls_back_without_a_second_row():
    session = _session()
    session.flush_error = IntegrityError("INSERT", {}, Exception("constraint"))
    with pytest.raises(HTTPException) as failed:
        _save(session)
    assert failed.value.status_code == 422
    assert session.committed is False
    assert session.rolled_back is True
    assert len(session.added) == 1


def test_legacy_and_unrelated_methods_cannot_be_edited():
    cases = [
        ("epa_refrigerant", "api", "refrigerant"),
        ("epa_stationary", "epa_stationary", "stationary_combustion"),
        ("epa_mobile_v1", "epa_mobile_v1", "mobile_combustion"),
        ("uk_fuel", "uk_fuel", "stationary_combustion"),
    ]
    for method, legacy_source, category in cases:
        existing = _refrigerant_row(
            method=method,
            legacy_source=legacy_source,
            category=category,
            emissions_tco2e=Decimal("9"),
            raw={"legacy": True},
        )
        session = _session(activity=existing)
        with pytest.raises(HTTPException) as conflict:
            _save(session, activity_id=existing.id, leakage_kg=Decimal("1"))
        assert conflict.value.status_code == 409
        assert existing.emissions_tco2e == Decimal("9")
        assert existing.raw == {"legacy": True}
        assert session.added == []
        assert session.committed is False
        assert session.rolled_back is True


def test_create_and_update_endpoints_store_the_backend_total(monkeypatch):
    session = _session()
    monkeypatch.setattr(calc_routes, "load_refrigerant_factor_sheets", lambda db: _factor_sheets())
    app = FastAPI()
    app.include_router(calc_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_org_context] = lambda: _ctx()
    app.dependency_overrides[get_db] = lambda: session
    client = TestClient(app)
    created = client.post(
        "/api/v1/calc/epa/refrigerant-leakage/records",
        json={
            "method": "leakage_record",
            "gas": "R-404A",
            "leakage_kg": "2",
            "assessment_id": str(ASSESSMENT_ID),
            "counterparty_id": str(COUNTERPARTY_ID),
            "equipment_type": "chiller",
            "equipment_id": "CH-1",
            "site": "North plant",
            "period": "2026-10",
            "gwp": "1",
            "emissions_tco2e": "0",
            "organization_id": str(OTHER_ORG_ID),
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["emissions_tco2e"] == "7.886"
    assert body["emissions_kg_co2e"] == "7886"
    assert body["organization_id"] == str(ORG_ID)
    assert len(session.added) == 1
    created_id = body["activity_id"]

    existing = session.added[0]
    session.lookup[EmissionActivity] = existing
    session.added = []
    updated = client.patch(
        f"/api/v1/calc/epa/refrigerant-leakage/records/{created_id}",
        json={
            "method": "leakage_record",
            "gas": "R-410A",
            "leakage_kg": "1",
            "assessment_id": str(ASSESSMENT_ID),
            "period": "2026-10",
            "gwp": "1",
            "emissions_tco2e": "0",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["activity_id"] == created_id
    assert updated.json()["emissions_tco2e"] == "1.924"
    assert updated.json()["calculation"]["gwp"] == "1924"
    assert session.added == []
    assert existing.emissions_tco2e == Decimal("1.924")
    assert existing.raw["inputs"]["refrigerant"] == "R-410A"


def test_unauthenticated_save_is_rejected():
    app = FastAPI()
    app.include_router(calc_routes.router, prefix="/api/v1")
    client = TestClient(app)
    response = client.post(
        "/api/v1/calc/epa/refrigerant-leakage/records",
        json={
            "method": "leakage_record",
            "gas": "R-404A",
            "leakage_kg": "2",
            "assessment_id": str(ASSESSMENT_ID),
            "period": "2026-10",
        },
    )
    assert response.status_code in (401, 403)
