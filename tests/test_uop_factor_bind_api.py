"""Authenticated factor match + UoP preview. Isolated Postgres only. Never production."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from fastapi_app.auth_org import OrgContext
from fastapi_app.db import get_db
from fastapi_app.factor_library_models import FactorLibraryEntry
from fastapi_app.routers import factor_library as library_routes
from fastapi_app.routers import uop_calculate as uop_calc_routes
from fastapi_app.routers.deps import require_org_context
from fastapi_app.uop_reportable import UOP_REPORTABLE_SAVE_ENABLED
from tests.pg_isolated import (
    BACKEND_ROOT,
    apply_sql_file,
    bootstrap_desnz_verified_rows,
    bootstrap_factor_library,
    bootstrap_uop_schema,
    is_isolated_url,
    is_production_url,
    make_engine,
    make_session,
    start_isolated_postgres,
)
from tests.test_uop_drafts import ORG_ID, _user

DESNZ_ELECTRICITY_ID = uuid.UUID("fabac5f1-e547-52a3-b3d2-394eaa1c679d")
SUBMIT_SQL = BACKEND_ROOT / "db" / "sql" / "0018_desnz_library_submit_pending.sql"
APPROVE_SQL = BACKEND_ROOT / "db" / "sql" / "0018_desnz_library_approve.sql"


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
def bind_api_engine():
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
        bootstrap_factor_library(engine)
        bootstrap_desnz_verified_rows(engine)
        apply_sql_file(engine, SUBMIT_SQL)
        apply_sql_file(engine, APPROVE_SQL)
        yield engine
        engine.dispose()
    finally:
        stop()


@pytest.fixture
def bind_api_session(bind_api_engine):
    session = make_session(bind_api_engine)
    try:
        yield session
        session.rollback()
    finally:
        session.close()


def _client(session, role: str = "admin"):
    app = FastAPI()
    app.include_router(library_routes.router, prefix="/api/v1")
    app.include_router(uop_calc_routes.router, prefix="/api/v1")
    ctx = OrgContext(user=_user(), organization_id=ORG_ID, role=role)
    app.dependency_overrides[require_org_context] = lambda: ctx
    app.dependency_overrides[get_db] = lambda: session
    return TestClient(app)


def _preview_draft(library_entry_id: str, emission_factor: float | None = 0.13096) -> dict:
    estimation = {
        "pcafOption": "2a",
        "method": "physical",
        "labelEnergyIntensity": 20,
        "floorArea": 100,
        "libraryEntryId": library_entry_id,
        "factorConfirmed": True,
        "factorSource": "UK DESNZ",
        "factorGeography": "United Kingdom",
        "factorYear": "2026",
        "factorUnit": "kg CO2e/kWh",
    }
    if emission_factor is not None:
        estimation["emissionFactor"] = emission_factor
    return {
        "financingInstanceId": "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
        "eligibility": {
            "proceedsAllocatedToSpecificAssets": "yes",
            "isSecuritized": "no",
            "structureHasControl": "no",
            "structureListing": "",
            "controlOneFullyAllocatedAsset": "",
            "controlAssetIsProject": "",
            "debtBasedWithOneFullyAllocatedAsset": "no",
            "singleAssetClass": "",
            "assetsOnIssuerBalanceSheet": "no",
        },
        "structureKind": "debt-fund",
        "investmentType": "debt",
        "allocationStatus": "known",
        "allocatedProceeds": 10_000_000,
        "unallocatedProceeds": 0,
        "outstandingInvestment": 5_000_000,
        "totalStructureDebt": 10_000_000,
        "totalStructureEquity": 0,
        "reportingYear": "2026",
        "emissionsPath": "underlying_assets",
        "assets": [
            {
                "underlyingAssetId": "uk-office-1",
                "name": "UK office",
                "assetClass": "commercial-real-estate",
                "allocatedOutstanding": 5_000_000,
                "totalAssetValue": 10_000_000,
                "hasReportedEmissions": "no",
                "dataSource": "EPC",
                "estimation": estimation,
            }
        ],
    }


def test_save_flag_remains_disabled():
    assert UOP_REPORTABLE_SAVE_ENABLED is False
    assert Path(SUBMIT_SQL).is_file()
    assert Path(APPROVE_SQL).is_file()


def test_ops_sql_promotes_catalog_rows_without_duplicating_factor_rows(bind_api_session):
    rows = bind_api_session.query(FactorLibraryEntry).filter(
        FactorLibraryEntry.factor_row_id.in_(
            [
                DESNZ_ELECTRICITY_ID,
                uuid.UUID("134a44da-d317-5773-bafc-e1a7734851b6"),
            ]
        )
    ).all()
    assert len(rows) == 2
    assert {row.status for row in rows} == {"approved"}
    assert {float(row.factor_value) for row in rows} == {0.13096, 0.17529}
    assert all(row.factor_row_id is not None for row in rows)
    catalog = bind_api_session.execute(text("SELECT count(*) FROM ref.factor_rows")).scalar()
    assert catalog == 2


def test_authenticated_match_and_uop_preview_uses_desnz_electricity(bind_api_session):
    client = _client(bind_api_session, role="admin")
    pakistan = client.get(
        "/api/v1/factor-library/match",
        params={
            "library_class": "building",
            "geography": "Pakistan",
            "activity_key": "electricity",
            "reporting_year": 2026,
        },
    )
    assert pakistan.status_code == 200
    assert pakistan.json()["factors"] == []
    assert pakistan.json()["silent_substitution"] is False

    matched = client.get(
        "/api/v1/factor-library/match",
        params={
            "library_class": "building",
            "geography": "United Kingdom",
            "activity_key": "electricity",
            "reporting_year": 2026,
            "unit": "kg CO2e/kWh",
        },
    )
    assert matched.status_code == 200
    body = matched.json()
    assert body["status"] == "ok"
    assert len(body["factors"]) == 1
    factor = body["factors"][0]
    assert factor["factor_value"] == pytest.approx(0.13096)
    assert factor["status"] == "approved"
    assert factor["geography"] == "United Kingdom"

    preview = client.post(
        "/api/v1/uop/calculate",
        json={"draft": _preview_draft(factor["id"]), "persist": False, "persist_reportable": False},
    )
    assert preview.status_code == 200
    result = preview.json()
    assert result["status"] == "complete"
    assert result.get("persisted_reportable") in (None, False)
    snap = result["assets"][0]["factor_snapshot"]
    assert snap["factor_value"] == pytest.approx(0.13096)
    assert snap["client_value_used"] is False
    assert snap["factor_row_id"] == str(DESNZ_ELECTRICITY_ID)

    tampered = client.post(
        "/api/v1/uop/calculate",
        json={
            "draft": _preview_draft(factor["id"], emission_factor=0.5),
            "persist": False,
        },
    )
    assert tampered.status_code == 200
    assert tampered.json()["status"] == "incomplete"
    assert tampered.json()["assets"][0]["code"] == "factor_snapshot_mismatch"

    blocked = client.post(
        "/api/v1/uop/calculate",
        json={
            "draft": _preview_draft(factor["id"]),
            "persist_reportable": True,
            "expected_fingerprint": result.get("calculation_fingerprint"),
        },
    )
    assert blocked.status_code in (403, 422)
    detail = blocked.json()["detail"]
    code = detail.get("code") if isinstance(detail, dict) else None
    assert code in {"UOP_REPORTABLE_SAVE_DISABLED", "UOP_DRAFT_REQUIRED"}
    assert UOP_REPORTABLE_SAVE_ENABLED is False


def test_member_cannot_approve_catalog_promotion(bind_api_session):
    client = _client(bind_api_session, role="analyst")
    pending = client.get("/api/v1/factor-library/pending")
    assert pending.status_code == 403
    preview = client.get("/api/v1/factor-library/preview-catalog")
    assert preview.status_code == 403
