"""Factor-library HTTP permissions and missing-table behaviour. No production DB."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from fastapi_app.auth_org import OrgContext
from fastapi_app.db import get_db
from fastapi_app.routers import factor_library as library_routes
from fastapi_app.routers.deps import require_org_context
from tests.test_uop_drafts import ORG_ID, UopMemorySession, _ctx, _user


def _client(role: str = "member", table_ready: bool = False):
    app = FastAPI()
    app.include_router(library_routes.router, prefix="/api/v1")
    ctx = OrgContext(user=_user(), organization_id=ORG_ID, role=role)
    app.dependency_overrides[require_org_context] = lambda: ctx
    app.dependency_overrides[get_db] = lambda: UopMemorySession()
    original = library_routes.table_exists
    library_routes.table_exists = lambda *args, **kwargs: table_ready
    client = TestClient(app)
    client._restore = lambda: setattr(library_routes, "table_exists", original)
    return client


def test_match_without_library_tables_returns_no_verified_factor():
    client = _client(table_ready=False)
    try:
        response = client.get(
            "/api/v1/factor-library/match",
            params={
                "library_class": "physical",
                "geography": "Pakistan",
                "activity_key": "electricity",
                "reporting_year": 2026,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "NO_VERIFIED_FACTOR"
        assert body["factors"] == []
        assert body["silent_substitution"] is False
        assert "No verified factor available" in body["message"]
    finally:
        client._restore()


def test_member_cannot_list_or_approve():
    client = _client(role="analyst", table_ready=True)
    try:
        pending = client.get("/api/v1/factor-library/pending")
        assert pending.status_code == 403
        approve = client.post(
            "/api/v1/factor-library/11111111-1111-1111-1111-111111111111/approve",
            json={"notes": "no"},
        )
        assert approve.status_code == 403
        preview = client.get("/api/v1/factor-library/preview-catalog")
        assert preview.status_code == 403
    finally:
        client._restore()


def test_sources_list_does_not_claim_blocked_datasets_are_integrated():
    client = _client(role="admin", table_ready=False)
    try:
        response = client.get("/api/v1/factor-library/sources")
        assert response.status_code == 200
        codes = {item["code"]: item for item in response.json()["sources"]}
        assert codes["exiobase"]["integrated"] is False
        assert codes["ice_eeio_educational"]["integrated"] is False
        assert codes["pakistan_uae_electricity"]["status"] == "unsupported"
        assert codes["desnz_ghg_conversion_factors_2026"]["integrated"] is False
    finally:
        client._restore()
