"""Stage 5 — period validation, verified calc gates, kg→tCO2e, ownership."""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from fastapi_app.auth_models import User
from fastapi_app.auth_org import OrgContext
from fastapi_app.ghg_calc.scope3_period import (
    parse_period_month,
    period_error,
    period_matches_assessment,
)
from fastapi_app.ghg_calc.scope3_records import save_scope3_record
from fastapi_app.ghg_calc.scope3_verified_calc import (
    ACCOUNTING_VERSION,
    calculate_verified_freight,
    calculate_verified_spend,
    calculate_verified_waste,
)
from fastapi_app.ghg_models import EmissionActivity, EmissionAssessment
from fastapi_app.portfolio_models import Counterparty

ORG_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
USER_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
ASSESSMENT_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
OTHER_ORG = uuid.UUID("99999999-9999-9999-9999-999999999999")
COUNTERPARTY_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")


def test_period_month_valid_and_invalid():
    assert parse_period_month("2026-06") == (2026, 6)
    assert parse_period_month("2026") is None
    assert parse_period_month("2026-13") is None
    assert parse_period_month("") is None
    assert parse_period_month("created_at") is None


def test_period_matches_assessment_year():
    assert period_matches_assessment("2026-01", "2026") is True
    assert period_matches_assessment("2026-12", "2026-06") is True
    assert period_matches_assessment("2025-01", "2026") is False
    assert period_error("2026-01", "2025") is not None
    assert period_error("bad", "2026") is not None
    assert period_error(None, "2026") is not None


def test_freight_rejects_bad_period_without_db_factors():
    class EmptyDb:
        def query(self, *a, **k):
            raise AssertionError("should fail period before factor lookup")

    r = calculate_verified_freight(
        EmptyDb(),  # type: ignore[arg-type]
        vehicle_type="Rail",
        distance_km=10,
        weight_kg=100,
        period="2026",
    )
    assert r["ok"] is False
    assert "YYYY-MM" in r["error"]


def test_waste_blocked_without_structured_metadata():
    class MetaDb:
        def execute(self, *a, **k):
            raise RuntimeError("no metadata table")

        def query(self, *a, **k):
            class Q:
                def filter(self, *a, **k):
                    return self

                def limit(self, *a, **k):
                    return self

                def first(self):
                    return None

                def all(self):
                    return []

            return Q()

    r = calculate_verified_waste(
        MetaDb(),  # type: ignore[arg-type]
        material="Aluminum Cans",
        disposal_method="Landfilled",
        mass_kg=100,
        period="2026-06",
    )
    assert r["ok"] is False
    assert "metadata" in r["error"].lower()


def test_spend_refuses_wrong_currency_and_ignores_client_totals():
    class SupplierDb:
        def query(self, *a, **k):
            class Q:
                def filter(self, *a, **k):
                    return self

                def limit(self, *a, **k):
                    return self

                def first(self):
                    return None

                def all(self):
                    return []

            return Q()

        def execute(self, *a, **k):
            return SimpleNamespace(
                mappings=lambda: SimpleNamespace(
                    first=lambda: {
                        "id": str(uuid.uuid4()),
                        "code": "111110",
                        "supplier_name": "Soybean Farming",
                        "unit": "kg CO2e/2022 USD, purchaser price",
                        "emission_factor": 0.488,
                    }
                )
            )

    ok = calculate_verified_spend(
        SupplierDb(),  # type: ignore[arg-type]
        amount=1000,
        period="2026-03",
        supplier_code="111110",
        activity_currency="USD",
        activity_price_year=2022,
        client_emission_factor=999.0,
        client_emissions=1.0,
    )
    assert ok["ok"] is True
    assert float(ok["emissions_kg"]) == pytest.approx(488.0)
    assert float(ok["total_t_co2e"]) == pytest.approx(0.488)

    bad_fx = calculate_verified_spend(
        SupplierDb(),  # type: ignore[arg-type]
        amount=1000,
        period="2026-03",
        supplier_code="111110",
        activity_currency="PKR",
        activity_price_year=2022,
    )
    assert bad_fx["ok"] is False

    bad_year = calculate_verified_spend(
        SupplierDb(),  # type: ignore[arg-type]
        amount=1000,
        period="2026-03",
        supplier_code="111110",
        activity_currency="USD",
        activity_price_year=2020,
    )
    assert bad_year["ok"] is False


class FakeQuery:
    def __init__(self, session, model):
        self.session = session
        self.model = model

    def filter(self, *a, **k):
        return self

    def with_for_update(self):
        return self

    def first(self):
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
    user = User(id=USER_ID, email="a@b.c", password_hash="x")
    return OrgContext(user=user, organization_id=org_id, role="owner")


def _ok_calc(**overrides):
    base = {
        "ok": True,
        "save_allowed": True,
        "period": "2026-04",
        "reporting_year": 2026,
        "category": "upstream_transportation",
        "method": "scope3_freight_v1",
        "quantity": 100,
        "unit": "km",
        "total_t_co2e": "1.5",
        "total_kg_co2e": "1500",
        "factor": {
            "dataset_id": str(uuid.uuid4()),
            "factor_row_id": str(uuid.uuid4()),
            "factor_unit": "short ton-mile",
            "factor_value": 0.12,
        },
        "inputs": {"distance_km": 100, "weight_kg": 50},
        "methodology": ACCOUNTING_VERSION,
        "accounting": {"version": ACCOUNTING_VERSION},
    }
    base.update(overrides)
    return base


def test_save_scope3_rejects_period_mismatch_and_wrong_counterparty_org():
    calc = _ok_calc(period="2025-01", reporting_year=2025)
    with pytest.raises(HTTPException) as exc:
        save_scope3_record(
            FakeSession(reporting_period="2026"),
            _ctx(),
            calculation=calc,
            assessment_id=ASSESSMENT_ID,
        )
    assert exc.value.status_code == 422

    calc = _ok_calc()
    session = FakeSession()
    session.lookup[Counterparty] = Counterparty(
        id=COUNTERPARTY_ID,
        user_id=USER_ID,
        name="Other",
        sector="Banking",
        geography="UK",
        organization_id=OTHER_ORG,
    )
    with pytest.raises(HTTPException) as exc2:
        save_scope3_record(
            session,
            _ctx(),
            calculation=calc,
            assessment_id=ASSESSMENT_ID,
            counterparty_id=COUNTERPARTY_ID,
        )
    assert exc2.value.status_code == 403


def test_save_scope3_persists_tonnes_and_period_meta():
    calc = _ok_calc()
    session = FakeSession(reporting_period="2026")
    out = save_scope3_record(
        session,
        _ctx(),
        calculation=calc,
        assessment_id=ASSESSMENT_ID,
    )
    assert session.committed is True
    assert len(session.added) == 1
    row: EmissionActivity = session.added[0]
    assert row.scope == 3
    assert row.emissions_tco2e == Decimal("1.5")
    assert row.raw["activity_meta"]["period"] == "2026-04"
    assert row.legacy_source == ACCOUNTING_VERSION
    assert out["activity_id"] == str(row.id)


def test_save_refuses_when_calculation_not_allowed():
    with pytest.raises(HTTPException):
        save_scope3_record(
            FakeSession(),
            _ctx(),
            calculation={"ok": False, "save_allowed": False, "error": "missing factor"},
            assessment_id=ASSESSMENT_ID,
        )


def test_save_refuses_missing_org_context():
    user = User(id=USER_ID, email="a@b.c", password_hash="x")
    ctx = OrgContext(user=user, organization_id=None, role="owner")
    with pytest.raises(HTTPException) as exc:
        save_scope3_record(
            FakeSession(),
            ctx,
            calculation=_ok_calc(),
            assessment_id=ASSESSMENT_ID,
        )
    assert exc.value.status_code == 403


def test_kg_to_tco2e_conversion_in_ok_calc_path():
    """1000 kg → 1 tCO2e via verified spend math when factor resolves."""
    class SupplierDb:
        def query(self, *a, **k):
            class Q:
                def filter(self, *a, **k):
                    return self

                def limit(self, *a, **k):
                    return self

                def first(self):
                    return None

                def all(self):
                    return []

            return Q()

        def execute(self, *a, **k):
            return SimpleNamespace(
                mappings=lambda: SimpleNamespace(
                    first=lambda: {
                        "id": str(uuid.uuid4()),
                        "code": "111110",
                        "supplier_name": "Soybean Farming",
                        "unit": "kg CO2e/2022 USD, purchaser price",
                        "emission_factor": 1.0,
                    }
                )
            )

    r = calculate_verified_spend(
        SupplierDb(),  # type: ignore[arg-type]
        amount=1000,
        period="2026-01",
        supplier_code="111110",
        activity_currency="USD",
        activity_price_year=2022,
    )
    assert r["ok"] is True
    assert float(r["emissions_kg"]) == pytest.approx(1000.0)
    assert float(r["total_t_co2e"]) == pytest.approx(1.0)
