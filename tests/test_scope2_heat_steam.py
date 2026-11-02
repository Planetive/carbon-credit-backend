"""EPA purchased heat and steam. Factors are the stated EPA Table 7 values, not a fallback."""

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
from fastapi_app.ghg_calc.scope2_heat_steam import calculate_purchased_heat_steam
from fastapi_app.ghg_calc.scope2_heat_steam_records import save_scope2_heat_steam_record
from fastapi_app.ghg_models import EmissionActivity, EmissionAssessment
from fastapi_app.portfolio_models import Counterparty
from fastapi_app.routers import calc as calc_routes
from fastapi_app.routers.deps import require_org_context

ORG_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
OTHER_ORG = uuid.UUID("22222222-2222-2222-2222-222222222222")
USER_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
ASSESSMENT_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
COUNTERPARTY_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")

# 10 mmBtu:
# CO2 663.3 kg, CH4 0.0125 kg, N2O 0.00125 kg
# CO2e kg = 663.3 + 0.0125*28 + 0.00125*265 = 663.98125
# tCO2e = 0.66398125
TEN_MMBTU = Decimal("10")
TEN_TONNES = "0.66398125"
ONE_TONNES = "0.06639813"


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
    def __init__(self, lookup=None):
        self.lookup = lookup or {}
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
        user=User(id=USER_ID, email="heat@example.com", password_hash="x"),
        organization_id=org_id,
        role="admin",
    )


def _owned_session(activity=None, reporting_period="2026", assessment_org=ORG_ID, counterparty_org=ORG_ID):
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
    return FakeSession(lookup)


def _save(session, **overrides):
    payload = dict(
        db=session,
        ctx=_ctx(),
        energy_form="purchased_steam",
        quantity=TEN_MMBTU,
        unit="mmBtu",
        period="2026-06",
        assessment_id=ASSESSMENT_ID,
        counterparty_id=COUNTERPARTY_ID,
        supplier_name="District plant",
    )
    payload.update(overrides)
    return save_scope2_heat_steam_record(**payload)


def test_heat_and_steam_use_the_same_table_7_gases_and_ar5():
    steam = calculate_purchased_heat_steam(
        energy_form="purchased steam",
        quantity=TEN_MMBTU,
        unit="MMBtu",
        period="2026-06",
        co2_factor=Decimal("0.17355"),
        ch4_factor=Decimal("9"),
        n2o_factor=Decimal("9"),
        emission_factor=Decimal("0.17529"),
        emissions_tco2e=Decimal("99"),
    )
    heat = calculate_purchased_heat_steam(
        energy_form="purchased_heat",
        quantity=Decimal("1"),
        unit="mmBtu",
        period="2026-06",
        supplier_name="Another supplier",
    )
    assert steam["save_allowed"] is True
    assert steam["total_t_co2e"] == TEN_TONNES
    assert steam["total_kg_co2e"] == "663.98125000"
    assert steam["gases"]["co2"]["mass_kg"] == "663.30000000"
    assert steam["gases"]["ch4"]["mass_kg"] == "0.01250000"
    assert steam["gases"]["n2o"]["mass_kg"] == "0.00125000"
    assert steam["factor"]["co2_kg_per_mmbtu"] == "66.33000000"
    assert steam["factor"]["ch4_g_per_mmbtu"] == "1.25000000"
    assert steam["factor"]["n2o_g_per_mmbtu"] == "0.12500000"
    assert steam["factor"]["gwp_ch4"] == 28
    assert steam["factor"]["gwp_n2o"] == 265
    assert steam["factor"]["publisher"] == "US EPA"
    assert steam["factor"]["thermal_efficiency"] == "80%"
    assert steam["factor"]["supplier_specific"] is False
    assert heat["total_t_co2e"] == ONE_TONNES
    assert heat["total_t_co2e"] != steam["total_t_co2e"]
    assert heat["factor"]["co2_kg_per_mmbtu"] == steam["factor"]["co2_kg_per_mmbtu"]


def test_onsite_combustion_and_other_units_are_refused():
    onsite = calculate_purchased_heat_steam(
        energy_form="Onsite heat and steam",
        quantity=TEN_MMBTU,
        unit="mmBtu",
        period="2026-06",
    )
    kwh = calculate_purchased_heat_steam(
        energy_form="purchased_heat",
        quantity=TEN_MMBTU,
        unit="kWh",
        period="2026-06",
    )
    mmscf = calculate_purchased_heat_steam(
        energy_form="purchased_steam",
        quantity=Decimal("1"),
        unit="mmscf",
        period="2026-06",
    )
    assert onsite["status"] == "onsite_combustion"
    assert kwh["status"] == "invalid_quantity"
    assert mmscf["status"] == "invalid_quantity"
    assert "total_t_co2e" not in onsite


def test_save_writes_one_verified_activity_and_ignores_the_client_factor():
    session = _owned_session()
    saved = _save(session, co2_factor=Decimal("0.17355"), emissions_tco2e=Decimal("99"))
    row = session.added[0]
    assert saved["emissions_tco2e"] == TEN_TONNES
    assert row.scope == 2
    assert row.category == "purchased_heat_steam"
    assert row.method == "purchased_energy"
    assert row.legacy_source == "scope2_purchased_heat_steam_v1"
    assert row.factor_dataset_id is None
    assert row.raw["on_site_combustion"]["included"] is False
    assert row.raw["factor"]["source_document"].startswith("Emission Factors for Greenhouse Gas Inventories")
    assert row.raw["inputs"]["supplier_name"] == "District plant"
    assert session.committed is True


def test_wrong_year_rolls_back_and_unauthorized_records_are_refused():
    mismatch = _owned_session(reporting_period="2025")
    with pytest.raises(HTTPException) as year_error:
        _save(mismatch)
    assert year_error.value.status_code == 422
    assert mismatch.rolled_back is True
    assert mismatch.added == []

    other_assessment = _owned_session(assessment_org=OTHER_ORG)
    with pytest.raises(HTTPException) as missing:
        _save(other_assessment)
    assert missing.value.status_code == 404
    assert other_assessment.committed is False

    other_counterparty = _owned_session(counterparty_org=OTHER_ORG)
    with pytest.raises(HTTPException) as forbidden:
        _save(other_counterparty)
    assert forbidden.value.status_code == 403
    assert other_counterparty.committed is False


def test_onsite_and_bad_period_write_nothing():
    session = _owned_session()
    with pytest.raises(HTTPException):
        _save(session, energy_form="on-site combustion")
    assert session.added == []
    assert session.committed is False

    blank = _owned_session()
    with pytest.raises(HTTPException) as period_error:
        _save(blank, period="2026-13")
    assert period_error.value.status_code == 422
    assert blank.added == []


def test_legacy_activity_cannot_be_overwritten():
    legacy = EmissionActivity(
        id=uuid.uuid4(),
        assessment_id=ASSESSMENT_ID,
        organization_id=ORG_ID,
        user_id=USER_ID,
        scope=2,
        category="heat_steam",
        method="heat_steam",
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


def test_update_replaces_the_verified_record():
    existing = EmissionActivity(
        id=uuid.uuid4(),
        assessment_id=ASSESSMENT_ID,
        organization_id=ORG_ID,
        user_id=USER_ID,
        scope=2,
        category="purchased_heat_steam",
        method="purchased_energy",
        legacy_source="scope2_purchased_heat_steam_v1",
        emissions_tco2e=Decimal("1"),
        raw={},
    )
    session = _owned_session(activity=existing)
    saved = _save(session, activity_id=existing.id, energy_form="purchased_heat", quantity=Decimal("1"))
    assert saved["emissions_tco2e"] == ONE_TONNES
    assert existing.emissions_tco2e == Decimal(ONE_TONNES)
    assert session.added == []
    assert session.locked is True


def test_failed_flush_rolls_back():
    session = _owned_session()
    session.flush_error = IntegrityError("INSERT", {}, Exception("constraint"))
    with pytest.raises(HTTPException) as failed:
        _save(session)
    assert failed.value.status_code == 422
    assert session.rolled_back is True
    assert session.committed is False


def test_create_endpoint_ignores_the_client_factor():
    session = _owned_session()
    app = FastAPI()
    app.include_router(calc_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_org_context] = lambda: _ctx()
    app.dependency_overrides[get_db] = lambda: session
    client = TestClient(app)
    response = client.post(
        "/api/v1/calc/scope2/heat-steam/records",
        json={
            "energy_form": "purchased_steam",
            "quantity": "10",
            "unit": "mmBtu",
            "period": "2026-06",
            "assessment_id": str(ASSESSMENT_ID),
            "counterparty_id": str(COUNTERPARTY_ID),
            "co2_factor": "0.17355",
            "emissions_tco2e": "99",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["emissions_tco2e"] == TEN_TONNES
    assert body["calculation"]["factor"]["co2_kg_per_mmbtu"] == "66.33000000"
    assert session.added[0].legacy_source == "scope2_purchased_heat_steam_v1"


def test_calculate_endpoint_refuses_onsite_without_writing():
    session = _owned_session()
    app = FastAPI()
    app.include_router(calc_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_org_context] = lambda: _ctx()
    app.dependency_overrides[get_db] = lambda: session
    client = TestClient(app)
    response = client.post(
        "/api/v1/calc/scope2/heat-steam",
        json={
            "energy_form": "Onsite heat and steam",
            "quantity": "10",
            "unit": "mmBtu",
            "period": "2026-06",
        },
    )
    assert response.status_code == 422
    assert "Scope 1" in response.json()["detail"]
    assert session.added == []
    assert session.committed is False
