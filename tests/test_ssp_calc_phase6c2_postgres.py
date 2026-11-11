"""
Phase 6C.2 isolated PostgreSQL + JWT API verification for POST /api/v1/ssp/calculate.

Disposable Postgres only. Never staging/production. Never writes app.financed_emissions for SSP.
"""

from __future__ import annotations

import os
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from tests.pg_isolated import (
    bootstrap_ssp_fullstack_schema,
    is_isolated_url,
    is_production_url,
    make_engine,
    start_isolated_postgres,
)

ORG_A = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
ORG_B = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
USER_A = uuid.UUID("11111111-1111-4111-8111-111111111111")
USER_B = uuid.UUID("22222222-2222-4222-8222-222222222222")
CP_A = uuid.UUID("33333333-3333-4333-8333-333333333333")
INSTANCE_A = "ssp-6c2-calc-a"
PASSWORD = "SspE2ePass!234"
EMAIL_A = "ssp.6c2a@planetive.com"
EMAIL_B = "ssp.6c2b@planetive.com"
JWT_SECRET = "ssp-6c2-isolated-jwt-secret"


def _wait_ready(url: str, attempts: int = 12) -> None:
    last = None
    for _ in range(attempts):
        try:
            eng = make_engine(url)
            with eng.connect() as conn:
                conn.execute(text("SELECT 1"))
            eng.dispose()
            return
        except Exception as exc:
            last = exc
            time.sleep(0.5)
    raise RuntimeError(f"Isolated Postgres not ready: {last}")


def _hash(plain: str) -> str:
    try:
        from fastapi_app.auth_security import hash_password

        return hash_password(plain)
    except Exception:
        import bcrypt

        return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


@pytest.fixture(scope="module")
def isolated_stack():
    try:
        url, stop = start_isolated_postgres()
    except Exception as exc:
        pytest.skip(f"Isolated PostgreSQL unavailable ({exc})")
        return
    if is_production_url(url) or not is_isolated_url(url):
        stop()
        pytest.fail("Refusing production or non-isolated DATABASE_URL")

    prev_db = os.environ.get("DATABASE_URL")
    prev_jwt = os.environ.get("JWT_SECRET")
    try:
        _wait_ready(url)
        os.environ["DATABASE_URL"] = url
        os.environ["JWT_SECRET"] = JWT_SECRET
        os.environ["PGGSSENCMODE"] = "disable"
        os.environ["PGSSLMODE"] = "disable"

        import fastapi_app.db as dbmod

        if getattr(dbmod, "engine", None) is not None:
            try:
                dbmod.engine.dispose()
            except Exception:
                pass
        dbmod.engine = make_engine(url)
        dbmod.SessionLocal = sessionmaker(bind=dbmod.engine, autoflush=False, autocommit=False)

        engine = dbmod.engine
        bootstrap_ssp_fullstack_schema(engine)
        pw = _hash(PASSWORD)
        with engine.begin() as conn:
            for org_id, name in ((ORG_A, "Org A"), (ORG_B, "Org B")):
                conn.execute(
                    text(
                        "INSERT INTO public.organizations (id, name, is_active) "
                        "VALUES (CAST(:id AS uuid), :name, true) "
                        "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name"
                    ),
                    {"id": str(org_id), "name": name},
                )
            for uid, email in ((USER_A, EMAIL_A), (USER_B, EMAIL_B)):
                conn.execute(
                    text(
                        """
                        INSERT INTO public.users (id, email, password_hash, email_confirmed)
                        VALUES (CAST(:id AS uuid), :email, :pw, true)
                        ON CONFLICT (email) DO UPDATE
                        SET password_hash = EXCLUDED.password_hash, id = EXCLUDED.id
                        """
                    ),
                    {"id": str(uid), "email": email, "pw": pw},
                )
            conn.execute(
                text(
                    """
                    INSERT INTO public.profiles (
                      id, user_id, display_name, user_type, current_organization_id, organization_name
                    ) VALUES
                      (gen_random_uuid(), CAST(:ua AS uuid), 'User A', 'financial_institution',
                       CAST(:oa AS uuid), 'Org A'),
                      (gen_random_uuid(), CAST(:ub AS uuid), 'User B', 'financial_institution',
                       CAST(:ob AS uuid), 'Org B')
                    ON CONFLICT (user_id) DO UPDATE
                      SET current_organization_id = EXCLUDED.current_organization_id
                    """
                ),
                {"ua": str(USER_A), "ub": str(USER_B), "oa": str(ORG_A), "ob": str(ORG_B)},
            )
            conn.execute(
                text(
                    "DELETE FROM public.user_organizations WHERE user_id IN "
                    "(CAST(:ua AS uuid), CAST(:ub AS uuid))"
                ),
                {"ua": str(USER_A), "ub": str(USER_B)},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO public.user_organizations (id, user_id, organization_id, role, status)
                    VALUES
                      (gen_random_uuid(), CAST(:ua AS uuid), CAST(:oa AS uuid), 'admin', 'active'),
                      (gen_random_uuid(), CAST(:ub AS uuid), CAST(:ob AS uuid), 'admin', 'active')
                    """
                ),
                {"ua": str(USER_A), "ub": str(USER_B), "oa": str(ORG_A), "ob": str(ORG_B)},
            )
            # counterparties may live in public (6B.4 seed) or app schema
            try:
                conn.execute(
                    text(
                        """
                        INSERT INTO public.counterparties (
                          id, user_id, organization_id, name, sector, geography, counterparty_type
                        ) VALUES (
                          CAST(:id AS uuid), CAST(:uid AS uuid), CAST(:oid AS uuid),
                          'SSP 6C2 CP', 'Financials', 'PK', 'corporate'
                        )
                        ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
                        """
                    ),
                    {"id": str(CP_A), "uid": str(USER_A), "oid": str(ORG_A)},
                )
            except Exception:
                conn.execute(
                    text(
                        """
                        INSERT INTO app.counterparties (id, organization_id, name)
                        VALUES (CAST(:id AS uuid), CAST(:org AS uuid), 'SSP 6C2 CP')
                        ON CONFLICT (id) DO NOTHING
                        """
                    ),
                    {"id": str(CP_A), "org": str(ORG_A)},
                )

        with engine.begin() as conn:
            names = {
                r[0]
                for r in conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema='app' AND table_name='ssp_pool_loans'"
                    )
                ).fetchall()
            }
            assert "amount_in_pool" in names

        from fastapi_app.main import app

        yield {"client": TestClient(app), "engine": engine, "url": url}
    finally:
        if prev_db is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = prev_db
        if prev_jwt is None:
            os.environ.pop("JWT_SECRET", None)
        else:
            os.environ["JWT_SECRET"] = prev_jwt
        stop()


def _token_for(user_id: uuid.UUID, email: str) -> str:
    from fastapi_app.auth_security import create_access_token

    return create_access_token(user_id, extra_claims={"email": email})


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _calc_draft(**overrides):
    draft = {
        "financingInstanceId": INSTANCE_A,
        "instanceKey": "securitization-structured-products#6c2",
        "eligibility": {
            "isStructuredProduct": "yes",
            "underlyingIdentifiable": "yes",
            "structureFamily": "true-sale",
            "collateralFamily": "residential-real-estate",
            "hasTranches": "yes",
            "hasPoolOfPools": "no",
            "poolsLinkedToSpecificTranches": "no",
            "isGssCollateralBond": "no",
            "isGssStandardBondForOriginatorProjects": "no",
            "collateralRemainsWithOriginator": "no",
            "hasAssetLevelEmissionsForOtherHard": "",
        },
        "deal": {
            "dealName": "6C2 RMBS",
            "dealIdentifier": "DEAL-6C2",
            "structureType": "rmbs",
            "reportingYear": "2024",
            "currency": "USD",
            "hasTranches": "yes",
            "hasPoolOfPools": "no",
        },
        "emissionsPath": "lookthrough",
        "collateral": [
            {
                "collateralId": "c1",
                "name": "House",
                "collateralType": "mortgage",
                "assetValueAtOrigination": 100,
                "attributionDenominator": 100,
                "emissionsPath": "reported",
                "scope1Emissions": 0,
                "scope2Emissions": 10,
                "dataQualityScore": 2,
            }
        ],
        "loans": [
            {
                "loanId": "l1",
                "name": "L1",
                "collateralIds": ["c1"],
                "currentOutstandingAmount": 40,
            }
        ],
        "pools": [
            {
                "poolId": "p1",
                "name": "P1",
                "loanIds": ["l1"],
                "loanAllocations": [{"loanId": "l1", "amountInPool": 40}],
            }
        ],
        "poolOfPools": None,
        "tranches": [
            {
                "trancheId": "t1",
                "name": "Senior",
                "currentOutstandingAmount": 40,
                "linkedPoolIds": [],
            }
        ],
        "holdings": [
            {
                "holdingId": "h1",
                "name": "Bank A",
                "trancheId": "t1",
                "bankOutstandingInvestment": 10,
                "financingInstanceId": INSTANCE_A,
            }
        ],
    }
    draft.update(overrides)
    return draft


def test_draft_save_reload_calculate_jwt(isolated_stack):
    client = isolated_stack["client"]
    # Real JWT via auth login path when available; fall back to signed token.
    login = client.post("/auth/login", json={"email": EMAIL_A, "password": PASSWORD})
    if login.status_code == 200:
        token = login.json().get("access_token") or login.json().get("token")
    else:
        token = _token_for(USER_A, EMAIL_A)
    headers = _auth(token)

    put = client.put(
        "/api/v1/ssp/drafts",
        headers=headers,
        json={**_calc_draft(), "counterpartyId": str(CP_A)},
    )
    assert put.status_code in (200, 201), put.text
    saved = put.json()
    holding_updated = saved.get("holdingUpdatedAt") or saved.get("holding_updated_at")
    deal_updated = saved.get("dealUpdatedAt") or saved.get("deal_updated_at")

    got = client.get(f"/api/v1/ssp/drafts/by-instance/{INSTANCE_A}", headers=headers)
    assert got.status_code == 200, got.text

    calc = client.post(
        "/api/v1/ssp/calculate",
        headers=headers,
        json={
            "financing_instance_id": INSTANCE_A,
            "counterparty_id": str(CP_A),
            "expected_holding_updated_at": holding_updated,
            "expected_deal_updated_at": deal_updated,
            "persist_preview": True,
        },
    )
    assert calc.status_code == 200, calc.text
    body = calc.json()
    assert body["status"] == "complete"
    assert body["financed_emissions"] == 1.0
    assert body["is_reportable"] is False
    assert body["include_in_portfolio"] is False
    assert body["persisted_preview"] is True
    assert body["scope_breakdown"]["scope2"] == pytest.approx(1.0)

    engine = isolated_stack["engine"]
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT is_reportable, include_in_portfolio FROM app.ssp_calculations "
                "WHERE organization_id = CAST(:org AS uuid) ORDER BY created_at DESC LIMIT 1"
            ),
            {"org": str(ORG_A)},
        ).fetchone()
        assert row is not None
        assert row[0] is False
        assert row[1] is False
        fe_count = conn.execute(text("SELECT COUNT(*) FROM app.financed_emissions")).scalar()
        assert int(fe_count or 0) == 0


def test_org_isolation_and_invalid_jwt(isolated_stack):
    client = isolated_stack["client"]
    token_a = _token_for(USER_A, EMAIL_A)
    token_b = _token_for(USER_B, EMAIL_B)

    client.put(
        "/api/v1/ssp/drafts",
        headers=_auth(token_a),
        json={**_calc_draft(), "counterpartyId": str(CP_A)},
    )

    denied = client.get(
        f"/api/v1/ssp/drafts/by-instance/{INSTANCE_A}",
        headers=_auth(token_b),
    )
    assert denied.status_code in (404, 403)

    calc_denied = client.post(
        "/api/v1/ssp/calculate",
        headers=_auth(token_b),
        json={"financing_instance_id": INSTANCE_A},
    )
    assert calc_denied.status_code in (404, 403)

    bad = client.post(
        "/api/v1/ssp/calculate",
        headers={"Authorization": "Bearer not-a-real-token"},
        json={"draft": _calc_draft()},
    )
    assert bad.status_code in (401, 403)


def test_stale_draft_and_unsupported_structure(isolated_stack):
    client = isolated_stack["client"]
    token = _token_for(USER_A, EMAIL_A)
    headers = _auth(token)
    instance = INSTANCE_A + "-stale"

    put = client.put(
        "/api/v1/ssp/drafts",
        headers=headers,
        json={
            **_calc_draft(),
            "financingInstanceId": instance,
            "counterpartyId": str(CP_A),
            "holdings": [
                {
                    "holdingId": "h1",
                    "trancheId": "t1",
                    "bankOutstandingInvestment": 10,
                    "financingInstanceId": instance,
                }
            ],
        },
    )
    assert put.status_code in (200, 201), put.text
    saved = put.json()
    conflict = client.post(
        "/api/v1/ssp/calculate",
        headers=headers,
        json={
            "financing_instance_id": instance,
            "expected_holding_updated_at": "2000-01-01T00:00:00+00:00",
            "expected_deal_updated_at": saved.get("dealUpdatedAt") or saved.get("deal_updated_at"),
        },
    )
    assert conflict.status_code in (409, 412, 422), conflict.text

    unsupported = client.post(
        "/api/v1/ssp/calculate",
        headers=headers,
        json={
            "draft": _calc_draft(
                deal={
                    "dealName": "MT",
                    "structureType": "master-trust",
                    "hasTranches": "yes",
                    "hasPoolOfPools": "no",
                }
            )
        },
    )
    assert unsupported.status_code == 200
    body = unsupported.json()
    assert body["status"] == "unsupported"
    assert body["code"] == "unsupported_structure"
    assert body["financed_emissions"] is None
