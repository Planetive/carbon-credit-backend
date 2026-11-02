"""Stage 6 — idempotent verified saves and fingerprint identity."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException

from fastapi_app.auth_models import User
from fastapi_app.auth_org import OrgContext
from fastapi_app.ghg_calc.scope3_records import (
    activity_input_fingerprint,
    save_scope3_record,
)
from fastapi_app.ghg_calc.scope3_verified_calc import ACCOUNTING_VERSION
from fastapi_app.ghg_models import EmissionActivity, EmissionAssessment
from fastapi_app.portfolio_models import Counterparty

ORG_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
OTHER_ORG = uuid.UUID("99999999-9999-9999-9999-999999999999")
USER_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
ASSESSMENT_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
COUNTERPARTY_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")


class FakeQuery:
    def __init__(self, session, model):
        self.session = session
        self.model = model

    def filter(self, *a, **k):
        return self

    def with_for_update(self):
        return self

    def first(self):
        if self.model is EmissionActivity and self.session.lookup_activity is not None:
            return self.session.lookup_activity
        return self.session.lookup.get(self.model)

    def all(self):
        if self.model is EmissionActivity:
            return list(self.session.activities)
        row = self.session.lookup.get(self.model)
        return [row] if row is not None else []


class FakeSession:
    def __init__(self, org_id=ORG_ID, reporting_period="2026"):
        self.lookup = {
            EmissionAssessment: EmissionAssessment(
                id=ASSESSMENT_ID,
                organization_id=org_id,
                user_id=USER_ID,
                framework="uk",
                reporting_period=reporting_period,
            ),
            Counterparty: Counterparty(
                id=COUNTERPARTY_ID,
                user_id=USER_ID,
                name="Branch",
                sector="Banking",
                geography="UK",
                organization_id=org_id,
            ),
        }
        self.lookup_activity = None
        self.added = []
        self.activities = []
        self.committed = False

    def query(self, *models):
        return FakeQuery(self, models[0])

    def add(self, row):
        self.added.append(row)
        if isinstance(row, EmissionActivity):
            self.activities.append(row)

    def flush(self):
        return None

    def commit(self):
        self.committed = True

    def rollback(self):
        return None

    def refresh(self, row):
        return None


def _ctx(org_id=ORG_ID):
    return OrgContext(
        user=User(id=USER_ID, email="a@b.c", password_hash="x"),
        organization_id=org_id,
        role="owner",
    )


def _calc(**overrides):
    base = {
        "ok": True,
        "save_allowed": True,
        "period": "2026-04",
        "reporting_year": 2026,
        "category": "purchased_goods",
        "method": "scope3_spend_v1",
        "quantity": 1000,
        "unit": "USD",
        "total_t_co2e": "0.488",
        "total_kg_co2e": "488",
        "factor": {"dataset_id": None, "factor_row_id": None, "factor_value": 0.488},
        "inputs": {
            "amount": 1000,
            "supplier_code": "111110",
            "activity_currency": "USD",
            "activity_price_year": 2022,
        },
        "methodology": ACCOUNTING_VERSION,
        "accounting": {"version": ACCOUNTING_VERSION},
    }
    base.update(overrides)
    return base


def test_fingerprint_ignores_emission_totals_and_distinguishes_inputs():
    a = activity_input_fingerprint(
        category="purchased_goods",
        method="scope3_spend_v1",
        period="2026-04",
        counterparty_id=None,
        inputs={"amount": 1000, "supplier_code": "111110"},
    )
    b = activity_input_fingerprint(
        category="purchased_goods",
        method="scope3_spend_v1",
        period="2026-04",
        counterparty_id=None,
        inputs={"supplier_code": "111110", "amount": 1000},
    )
    c = activity_input_fingerprint(
        category="purchased_goods",
        method="scope3_spend_v1",
        period="2026-04",
        counterparty_id=None,
        inputs={"amount": 2000, "supplier_code": "111110"},
    )
    assert a == b
    assert a != c


def test_repeated_save_same_inputs_updates_one_row():
    session = FakeSession()
    first = save_scope3_record(
        session,
        _ctx(),
        calculation=_calc(),
        assessment_id=ASSESSMENT_ID,
    )
    assert first["idempotent_replay"] is False
    assert len(session.activities) == 1
    activity_id = first["activity_id"]

    second = save_scope3_record(
        session,
        _ctx(),
        calculation=_calc(total_t_co2e="0.488"),
        assessment_id=ASSESSMENT_ID,
    )
    assert second["idempotent_replay"] is True
    assert second["activity_id"] == activity_id
    assert len(session.activities) == 1


def test_distinct_activities_same_month_are_not_collapsed():
    session = FakeSession()
    first = save_scope3_record(
        session,
        _ctx(),
        calculation=_calc(inputs={"amount": 1000, "supplier_code": "111110"}),
        assessment_id=ASSESSMENT_ID,
    )
    second = save_scope3_record(
        session,
        _ctx(),
        calculation=_calc(inputs={"amount": 500, "supplier_code": "222220"}),
        assessment_id=ASSESSMENT_ID,
    )
    assert first["activity_id"] != second["activity_id"]
    assert len(session.activities) == 2


def test_identical_inputs_with_distinct_client_entry_ids_create_two_rows():
    session = FakeSession()
    inputs = {"amount": 1000, "supplier_code": "111110"}
    first = save_scope3_record(
        session,
        _ctx(),
        calculation=_calc(inputs=inputs),
        assessment_id=ASSESSMENT_ID,
        client_entry_id="row-a",
    )
    second = save_scope3_record(
        session,
        _ctx(),
        calculation=_calc(inputs=inputs),
        assessment_id=ASSESSMENT_ID,
        client_entry_id="row-b",
    )
    assert first["activity_id"] != second["activity_id"]
    assert len(session.activities) == 2
    retry = save_scope3_record(
        session,
        _ctx(),
        calculation=_calc(inputs=inputs),
        assessment_id=ASSESSMENT_ID,
        client_entry_id="row-a",
    )
    assert retry["idempotent_replay"] is True
    assert retry["activity_id"] == first["activity_id"]
    assert len(session.activities) == 2


def test_identical_inputs_with_distinct_client_entry_ids_create_two_rows():
    session = FakeSession()
    inputs = {"amount": 1000, "supplier_code": "111110"}
    first = save_scope3_record(
        session,
        _ctx(),
        calculation=_calc(inputs=inputs),
        assessment_id=ASSESSMENT_ID,
        client_entry_id="row-a",
    )
    second = save_scope3_record(
        session,
        _ctx(),
        calculation=_calc(inputs=inputs),
        assessment_id=ASSESSMENT_ID,
        client_entry_id="row-b",
    )
    assert first["activity_id"] != second["activity_id"]
    assert len(session.activities) == 2
    retry = save_scope3_record(
        session,
        _ctx(),
        calculation=_calc(inputs=inputs),
        assessment_id=ASSESSMENT_ID,
        client_entry_id="row-a",
    )
    assert retry["idempotent_replay"] is True
    assert retry["activity_id"] == first["activity_id"]
    assert len(session.activities) == 2


def test_activity_id_edit_updates_authorized_row_only():
    session = FakeSession()
    created = save_scope3_record(
        session,
        _ctx(),
        calculation=_calc(),
        assessment_id=ASSESSMENT_ID,
    )
    existing = session.activities[0]
    session.lookup_activity = existing
    updated = save_scope3_record(
        session,
        _ctx(),
        calculation=_calc(total_t_co2e="1.0", total_kg_co2e="1000"),
        assessment_id=ASSESSMENT_ID,
        activity_id=uuid.UUID(created["activity_id"]),
    )
    assert updated["idempotent_replay"] is True
    assert existing.emissions_tco2e == Decimal("1.0")
    assert len(session.activities) == 1


def test_foreign_org_counterparty_still_forbidden():
    session = FakeSession()
    session.lookup[Counterparty] = Counterparty(
        id=COUNTERPARTY_ID,
        user_id=USER_ID,
        name="Other",
        sector="Banking",
        geography="UK",
        organization_id=OTHER_ORG,
    )
    with pytest.raises(HTTPException) as exc:
        save_scope3_record(
            session,
            _ctx(),
            calculation=_calc(),
            assessment_id=ASSESSMENT_ID,
            counterparty_id=COUNTERPARTY_ID,
        )
    assert exc.value.status_code == 403
