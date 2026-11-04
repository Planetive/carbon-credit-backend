"""
Phase 5D.1 isolated PostgreSQL UAT.

Never uses production DATABASE_URL / the EC2 rethinkcarbon host.
Applies prepared migration 0017 only to the disposable database.
"""

from __future__ import annotations

import time

import pytest
from sqlalchemy import text

from fastapi_app.uop_models import UopAssetCalculation
from tests.pg_isolated import (
    MIGRATION_0017,
    bootstrap_uop_schema,
    is_isolated_url,
    is_production_url,
    make_engine,
    make_session,
    start_isolated_postgres,
)
from tests.test_uop_calculate import _integrated, _separate
from tests.test_uop_drafts import COUNTERPARTY_ID, INSTANCE_A, INSTANCE_B, OTHER_ORG_ID
from tests.test_uop_reportable import (
    _calc,
    _client,
    _dashboard_total,
    _enable_save,
    _parents,
    _rows,
    _save,
)


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
def isolated_engine():
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
        bootstrap_uop_schema(engine, apply_0017=True)
        yield engine
        engine.dispose()
    finally:
        stop()


@pytest.fixture
def postgres_session(isolated_engine):
    session = make_session(isolated_engine)
    try:
        yield session
        session.rollback()
    finally:
        session.close()
        with isolated_engine.begin() as conn:
            conn.execute(text("TRUNCATE TABLE app.uop_asset_calculations CASCADE"))
            conn.execute(text("TRUNCATE TABLE app.uop_underlying_assets CASCADE"))
            conn.execute(text("TRUNCATE TABLE app.uop_investments CASCADE"))
            conn.execute(text("TRUNCATE TABLE app.uop_structures CASCADE"))
            conn.execute(text("TRUNCATE TABLE app.financed_emissions CASCADE"))


def test_0017_sql_is_additive_and_does_not_delete_history():
    script = MIGRATION_0017.read_text(encoding="utf-8")
    upper = " ".join(script.upper().split())
    assert "DELETE FROM" not in upper
    assert "DROP TABLE" not in upper
    lowered = script.lower()
    assert "add column if not exists reporting_year" in lowered
    assert "uq_financed_emissions_financing_instance_year" in lowered
    assert "drop index if exists app.uq_financed_emissions_financing_instance" in lowered
    update_tail = lowered.split("update app.financed_emissions", 1)[-1][:500]
    assert "set reporting_year" in update_tail
    assert "financed_emissions =" not in update_tail
    assert "status =" not in update_tail
    assert "inputs =" not in update_tail
    assert "results =" not in update_tail


def test_postgres_0017_index_replaced_0014(postgres_session, isolated_engine):
    with isolated_engine.connect() as conn:
        names = {
            row[0]
            for row in conn.execute(
                text(
                    """
                    SELECT indexname FROM pg_indexes
                    WHERE schemaname = 'app' AND tablename = 'financed_emissions'
                    """
                )
            )
        }
    assert "uq_financed_emissions_financing_instance_year" in names
    assert "uq_financed_emissions_financing_instance" not in names


def test_postgres_draft_reload_separate_save_and_upsert(postgres_session, monkeypatch):
    _enable_save(monkeypatch)
    client = _client(postgres_session)
    draft = _separate()
    created = _put_ok(client, INSTANCE_A, draft)
    reloaded = client.get(f"/api/v1/uop/drafts/by-instance/{INSTANCE_A}")
    assert reloaded.status_code == 200
    assert reloaded.json()["investment"]["id"] == created.json()["investment"]["id"]
    fp = _calc(client, INSTANCE_A, draft).json()["calculation_fingerprint"]
    saved = _save(client, INSTANCE_A, draft, fp)
    assert saved.status_code == 200, saved.text
    assert saved.json()["financed_emissions"] == pytest.approx(46.0)
    first_id = saved.json()["reportable_record_id"]
    fp2 = _calc(client, INSTANCE_A, draft).json()["calculation_fingerprint"]
    again = _save(client, INSTANCE_A, draft, fp2)
    assert again.status_code == 200
    assert again.json()["reportable_record_id"] == first_id
    assert len(_parents(postgres_session)) == 1
    for calc in _rows(postgres_session, UopAssetCalculation):
        assert calc.is_reportable is False
        assert calc.include_in_portfolio is False


def test_postgres_integrated_save(postgres_session, monkeypatch):
    _enable_save(monkeypatch)
    client = _client(postgres_session)
    draft = _integrated()
    _put_ok(client, INSTANCE_A, draft)
    fp = _calc(client, INSTANCE_A, draft).json()["calculation_fingerprint"]
    saved = _save(client, INSTANCE_A, draft, fp)
    assert saved.status_code == 200, saved.text
    assert saved.json()["formula_id"] == "uop-integrated-lookthrough"
    assert saved.json()["financed_emissions"] == pytest.approx(5.0)
    selected, total = _dashboard_total(postgres_session)
    assert len(selected) == 1
    assert total == pytest.approx(5.0)


def test_postgres_two_holdings_same_fund(postgres_session, monkeypatch):
    _enable_save(monkeypatch)
    client = _client(postgres_session)
    first_draft = _separate(outstandingInvestment=50_000_000)
    first = _put_ok(client, INSTANCE_A, first_draft)
    structure_id = first.json()["structure"]["id"]
    second_draft = _separate(
        outstandingInvestment=20_000_000,
        financingInstanceId=INSTANCE_B,
        instanceKey="use-of-proceeds#2",
    )
    second = client.put(
        "/api/v1/uop/drafts",
        json={
            "financing_instance_id": INSTANCE_B,
            "instance_key": "use-of-proceeds#2",
            "counterparty_id": str(COUNTERPARTY_ID),
            "structure_id": structure_id,
            "draft": second_draft,
        },
    )
    assert second.status_code in (200, 201), second.text
    ts = client.get(f"/api/v1/uop/drafts/by-instance/{INSTANCE_A}").json()["structure"][
        "updated_at"
    ]
    blocked = client.put(
        "/api/v1/uop/drafts",
        json={
            "financing_instance_id": INSTANCE_B,
            "counterparty_id": str(COUNTERPARTY_ID),
            "structure_id": structure_id,
            "update_shared": True,
            "draft": _separate(
                financingInstanceId=INSTANCE_B,
                structureName="Hijacked fund name",
            ),
        },
    )
    assert blocked.status_code == 409
    fp_a = _calc(
        client, INSTANCE_A, first_draft, expected_structure_updated_at=ts
    ).json()["calculation_fingerprint"]
    saved_a = _save(
        client,
        INSTANCE_A,
        first_draft,
        fp_a,
        expected_structure_updated_at=ts,
    )
    assert saved_a.status_code == 200, saved_a.text
    ts = client.get(f"/api/v1/uop/drafts/by-instance/{INSTANCE_B}").json()["structure"][
        "updated_at"
    ]
    fp_b = _calc(
        client, INSTANCE_B, second_draft, expected_structure_updated_at=ts
    ).json()["calculation_fingerprint"]
    saved_b = _save(
        client,
        INSTANCE_B,
        second_draft,
        fp_b,
        expected_structure_updated_at=ts,
    )
    assert saved_b.status_code == 200, saved_b.text
    assert saved_a.json()["financed_emissions"] == pytest.approx(46.0)
    assert saved_b.json()["financed_emissions"] == pytest.approx(18.4)
    assert len(_parents(postgres_session)) == 2
    selected, total = _dashboard_total(postgres_session)
    assert len(selected) == 2
    assert total == pytest.approx(64.4)


def test_postgres_same_instance_two_reporting_years(postgres_session, monkeypatch):
    _enable_save(monkeypatch)
    client = _client(postgres_session)
    draft_2026 = _separate(reportingYear="2026")
    _put_ok(client, INSTANCE_A, draft_2026)
    fp = _calc(client, INSTANCE_A, draft_2026).json()["calculation_fingerprint"]
    saved_2026 = _save(client, INSTANCE_A, draft_2026, fp)
    assert saved_2026.status_code == 200, saved_2026.text
    draft_2025 = _separate(reportingYear="2025")
    _put_ok(client, INSTANCE_A, draft_2025)
    fp_2025 = _calc(client, INSTANCE_A, draft_2025).json()["calculation_fingerprint"]
    saved_2025 = _save(client, INSTANCE_A, draft_2025, fp_2025)
    assert saved_2025.status_code == 200, saved_2025.text
    assert saved_2025.json()["reportable_record_id"] != saved_2026.json()["reportable_record_id"]
    parents = _parents(postgres_session)
    assert len(parents) == 2
    fp_again = _calc(client, INSTANCE_A, draft_2025).json()["calculation_fingerprint"]
    again = _save(client, INSTANCE_A, draft_2025, fp_again)
    assert again.json()["reportable_record_id"] == saved_2025.json()["reportable_record_id"]
    assert len(_parents(postgres_session)) == 2
    selected, total = _dashboard_total(postgres_session)
    assert len(selected) == 1
    assert total == pytest.approx(46.0)


def test_postgres_fingerprint_incomplete_auth_and_overlap(postgres_session, monkeypatch):
    _enable_save(monkeypatch)
    client = _client(postgres_session)
    other = _client(postgres_session, OTHER_ORG_ID)
    draft = _separate()
    _put_ok(client, INSTANCE_A, draft)
    preview = _calc(client, INSTANCE_A, draft)
    stale = _save(client, INSTANCE_A, draft, "not-a-real-fingerprint")
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "UOP_STALE_CALCULATION"
    hijack = other.post(
        "/api/v1/uop/calculate",
        json={
            "financing_instance_id": INSTANCE_A,
            "draft": draft,
            "persist_reportable": True,
            "expected_fingerprint": preview.json()["calculation_fingerprint"],
        },
    )
    assert hijack.status_code in (404, 422)
    incomplete = _separate(
        assets=[
            {
                "underlyingAssetId": "asset-missing",
                "name": "Missing",
                "assetClass": "mortgage",
                "allocatedOutstanding": 6_000_000,
                "totalAssetValue": 10_000_000,
                "hasReportedEmissions": "yes",
                "verificationStatus": "verified",
                "dataSource": "allocation report",
                "estimation": {},
            }
        ]
    )
    _put_ok(client, INSTANCE_B, incomplete, instance_key="use-of-proceeds#2")
    incomplete_preview = _calc(client, INSTANCE_B, incomplete)
    blocked_incomplete = _save(
        client,
        INSTANCE_B,
        incomplete,
        incomplete_preview.json()["calculation_fingerprint"],
    )
    assert blocked_incomplete.status_code == 422
    gp = client.post(
        "/api/v1/financed-emissions",
        json={
            "calc_kind": "finance",
            "formula_id": "mortgage",
            "company_type": "listed",
            "counterparty_id": str(COUNTERPARTY_ID),
            "inputs": {
                "financing_instance_id": "gp-pg-1",
                "reporting_year": "2026",
                "companyName": "City Issuer",
            },
            "financed_emissions": 12,
            "status": "completed",
        },
    )
    assert gp.status_code == 201, gp.text
    overlap_preview = _calc(client, INSTANCE_A, draft)
    overlap = _save(
        client, INSTANCE_A, draft, overlap_preview.json()["calculation_fingerprint"]
    )
    assert overlap.status_code == 409
    assert overlap.json()["detail"]["code"] == "UOP_OVERLAP_REVIEW_REQUIRED"
    selected, total = _dashboard_total(postgres_session)
    assert total == pytest.approx(12.0)


def _put_ok(client, instance, draft, instance_key="use-of-proceeds#1"):
    from tests.test_uop_drafts import _put

    created = _put(
        client,
        instance,
        instance_key=instance_key,
        draft=draft,
    )
    assert created.status_code in (200, 201), created.text
    return created
