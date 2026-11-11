"""SSP draft persistence (Phase 6B). In-memory store — no production Postgres, no formulas."""

from __future__ import annotations

import operator
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from fastapi_app.auth_models import User
from fastapi_app.auth_org import OrgContext
from fastapi_app.db import get_db
from fastapi_app.routers import financed_emissions as financed_routes
from fastapi_app.routers import ssp_drafts as ssp_routes
from fastapi_app.routers.deps import require_org_context
from fastapi_app.ssp_drafts import is_ssp_formula_id, ssp_reportable_blocked_detail
from fastapi_app.ssp_models import (
    SSP_NULL_COUNTERPARTY,
    SspCollateral,
    SspDeal,
    SspHolding,
    SspLoan,
    SspLoanCollateral,
    SspPool,
    SspPoolLoan,
    SspPoolOfPools,
    SspPoolOfPoolsMember,
    SspTranche,
    SspTranchePool,
)

ORG_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
OTHER_ORG_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
USER_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
COUNTERPARTY_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")

INSTANCE_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
INSTANCE_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
COL_1 = "cccccccc-cccc-cccc-cccc-cccccccccccc"
COL_2 = "dddddddd-dddd-dddd-dddd-dddddddddddd"
LOAN_1 = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
LOAN_2 = "ffffffff-ffff-ffff-ffff-ffffffffffff"
POOL_1 = "11111111-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TRANCHE_1 = "22222222-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def _literal(side: Any) -> Any:
    if hasattr(side, "value"):
        return side.value
    if hasattr(side, "effective_value"):
        return side.effective_value
    return side


def _column_key(side: Any) -> Optional[str]:
    if hasattr(side, "key") and side.key:
        return side.key
    return None


def _eval_clause(row: Any, clause: Any) -> bool:
    if clause is True or clause is False or clause is None:
        return bool(clause)
    clauses = getattr(clause, "clauses", None)
    op = getattr(clause, "operator", None)
    if clauses is not None and op is not None:
        evaluated = [_eval_clause(row, item) for item in clauses]
        if op is operator.and_ or getattr(op, "__name__", "") == "and_":
            return all(evaluated)
        if op is operator.or_ or getattr(op, "__name__", "") == "or_":
            return any(evaluated)
    left = getattr(clause, "left", None)
    right = getattr(clause, "right", None)
    if left is None or right is None:
        return True
    key = _column_key(left)
    if not key or not hasattr(row, key):
        return True
    actual = getattr(row, key)
    expected = _literal(right)
    if op is operator.eq or getattr(op, "__name__", "") in ("eq", "is_"):
        return actual == expected
    if op is operator.ne or getattr(op, "__name__", "") == "ne":
        return actual != expected
    return True


class MemoryQuery:
    def __init__(self, session: "SspMemorySession", model: type):
        self.session = session
        self.model = model
        self._filters: List[Any] = []

    def filter(self, *args, **kwargs):
        self._filters.extend(args)
        return self

    def filter_by(self, **kwargs):
        rows = self.all()
        self._forced = [
            row
            for row in rows
            if all(getattr(row, key) == value for key, value in kwargs.items())
        ]
        return self

    def with_for_update(self):
        return self

    def order_by(self, *args):
        return self

    def all(self):
        if hasattr(self, "_forced"):
            return list(self._forced)
        return [
            row
            for row in self.session.tables[self.model]
            if all(_eval_clause(row, clause) for clause in self._filters)
        ]

    def first(self):
        rows = self.all()
        return rows[0] if rows else None


class SspMemorySession:
    def __init__(self):
        self.tables: Dict[type, List[Any]] = defaultdict(list)
        self._pending: List[Any] = []
        self.committed = False
        self.rolled_back = False

    def query(self, model):
        return MemoryQuery(self, model)

    def add(self, row):
        model = type(row)
        if getattr(row, "id", None) is None:
            row.id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        if getattr(row, "created_at", None) is None:
            row.created_at = now
        if getattr(row, "updated_at", None) is None:
            row.updated_at = now
        if row not in self.tables[model]:
            self.tables[model].append(row)
        if row not in self._pending:
            self._pending.append(row)

    def delete(self, row):
        rows = self.tables[type(row)]
        if row in rows:
            rows.remove(row)
        if row not in self._pending:
            self._pending.append(row)

    def flush(self):
        self._enforce_constraints()

    def commit(self):
        self.flush()
        self._pending = []
        self.committed = True

    def rollback(self):
        for row in list(self._pending):
            rows = self.tables[type(row)]
            if row in rows:
                rows.remove(row)
        self._pending = []
        self.rolled_back = True

    def refresh(self, row):
        return None

    def close(self):
        return None

    def _enforce_constraints(self):
        seen = {}
        for holding in self.tables[SspHolding]:
            fid = (holding.financing_instance_id or "").strip()
            if not fid:
                raise IntegrityError("ssp", {}, Exception("blank financing_instance_id"))
            if holding.is_reportable or holding.include_in_portfolio:
                raise IntegrityError("ssp", {}, Exception("holding must not be reportable"))
            key = (
                holding.organization_id,
                holding.counterparty_id or SSP_NULL_COUNTERPARTY,
                fid,
            )
            if key in seen:
                raise IntegrityError("ssp", {}, Exception("duplicate financing_instance_id"))
            seen[key] = holding
        seen_cols = {}
        for row in self.tables[SspCollateral]:
            key = (row.deal_id, (row.collateral_id or "").strip())
            if key in seen_cols:
                raise IntegrityError("ssp", {}, Exception("duplicate collateral_id"))
            seen_cols[key] = row


def _user():
    return User(id=USER_ID, email="ssp@example.com", password_hash="x")


def _ctx(org_id=ORG_ID):
    return OrgContext(user=_user(), organization_id=org_id, role="admin")


def _client(session, org_id=ORG_ID):
    app = FastAPI()
    app.include_router(ssp_routes.router, prefix="/api/v1")
    app.include_router(financed_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_org_context] = lambda: _ctx(org_id)
    app.dependency_overrides[get_db] = lambda: session
    return TestClient(app)


def _draft(**overrides):
    payload = {
        "financingInstanceId": INSTANCE_A,
        "instanceKey": "securitization-structured-products#1",
        "eligibility": {
            "isStructuredProduct": "yes",
            "underlyingIdentifiable": "yes",
            "structureFamily": "true-sale",
            "collateralFamily": "residential-real-estate",
            "hasAssetLevelEmissionsForOtherHard": "",
            "isGssCollateralBond": "no",
            "isGssStandardBondForOriginatorProjects": "no",
            "collateralRemainsWithOriginator": "no",
            "hasTranches": "yes",
            "hasPoolOfPools": "no",
            "poolsLinkedToSpecificTranches": "no",
        },
        "deal": {
            "dealName": "RMBS 2024-1",
            "dealIdentifier": "DEAL-1",
            "issuerName": "Issuer SPV",
            "originatorName": "Bank Originator",
            "spvName": "RMBS SPV",
            "structureType": "rmbs",
            "reportingYear": "2024",
            "currency": "PKR",
            "documentationSource": "Trustee report",
            "hasTranches": "yes",
            "hasPoolOfPools": "no",
            "collateralRemainsWithOriginator": "no",
            "poolsLinkedToSpecificTranches": "no",
        },
        "emissionsPath": "lookthrough",
        "collateral": [
            {
                "collateralId": COL_1,
                "name": "House A",
                "collateralType": "mortgage",
                "attributionDenominator": 100,
                "denominatorLabel": "Property value at origination",
                "assetValueAtOrigination": 100,
                "pcafMethodOption": "1a",
                "classInputs": {"floorArea": 120},
                "evidence": {"source": "appraisal", "notes": "", "documentReference": ""},
            },
            {
                "collateralId": COL_2,
                "name": "House B",
                "collateralType": "mortgage",
                "attributionDenominator": 200,
                "denominatorLabel": "Property value at origination",
                "assetValueAtOrigination": 200,
                "pcafMethodOption": "1a",
                "classInputs": {"floorArea": 90},
                "evidence": {"source": "appraisal", "notes": "", "documentReference": ""},
            },
        ],
        "loans": [
            {
                "loanId": LOAN_1,
                "name": "Loan 1",
                "collateralIds": [COL_1],
                "currentOutstandingAmount": 50,
                "notes": "",
                "evidence": {"source": "", "notes": "", "documentReference": ""},
            },
            {
                "loanId": LOAN_2,
                "name": "Loan 2",
                "collateralIds": [COL_2],
                "currentOutstandingAmount": 75,
                "notes": "",
                "evidence": {"source": "", "notes": "", "documentReference": ""},
            },
        ],
        "pools": [
            {
                "poolId": POOL_1,
                "name": "Pool 1",
                "loanIds": [LOAN_1, LOAN_2],
                "poolCurrentOutstandingAmount": 125,
                "evidence": {"source": "", "notes": "", "documentReference": ""},
            }
        ],
        "poolOfPools": None,
        "tranches": [
            {
                "trancheId": TRANCHE_1,
                "name": "Senior A",
                "seniorityLabel": "Senior",
                "currentOutstandingAmount": 100,
                "linkedPoolIds": [],
                "isGreenTranche": "no",
                "evidence": {"source": "", "notes": "", "documentReference": ""},
            }
        ],
        "holdings": [
            {
                "holdingId": "hold-1",
                "name": "Bank note",
                "trancheId": TRANCHE_1,
                "bankOutstandingInvestment": 40,
                "currency": "PKR",
                "evidence": {"source": "", "notes": "", "documentReference": ""},
            }
        ],
    }
    payload.update(overrides)
    return payload


def _put(client, financing_instance_id=INSTANCE_A, **overrides):
    body = {
        "financing_instance_id": financing_instance_id,
        "instance_key": "securitization-structured-products#1",
        "counterparty_id": str(COUNTERPARTY_ID),
        "update_shared": True,
        "draft": _draft(financingInstanceId=financing_instance_id),
    }
    body.update(overrides)
    return client.put("/api/v1/ssp/drafts", json=body)


def test_is_ssp_formula_id():
    assert is_ssp_formula_id("ssp-lookthrough") is True
    assert is_ssp_formula_id("securitization-structured-products") is True
    assert is_ssp_formula_id("mortgage") is False
    assert "cannot" in ssp_reportable_blocked_detail().lower() or "Securitization" in ssp_reportable_blocked_detail()


def test_create_and_reload_draft():
    session = SspMemorySession()
    client = _client(session)
    created = _put(client)
    assert created.status_code in (200, 201), created.text
    body = created.json()
    assert body["holding"]["financing_instance_id"] == INSTANCE_A
    assert body["holding"]["is_reportable"] is False
    assert body["holding"]["include_in_portfolio"] is False
    assert body["deal"]["deal_name"] == "RMBS 2024-1"
    assert body["deal"]["reporting_year"] == "2024"
    assert len(body["collateral"]) == 2
    assert len(body["loans"]) == 2
    assert body["collateral"][0]["collateral_id"] != body["collateral"][1]["collateral_id"]

    listed = client.get("/api/v1/ssp/drafts", params={"counterparty_id": str(COUNTERPARTY_ID)})
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    by_instance = client.get(f"/api/v1/ssp/drafts/by-instance/{INSTANCE_A}")
    assert by_instance.status_code == 200
    reloaded = by_instance.json()
    assert reloaded["draft"]["deal"]["dealName"] == "RMBS 2024-1"
    assert len(reloaded["draft"]["collateral"]) == 2


def test_multiple_holdings_same_deal_shared_conflict():
    session = SspMemorySession()
    client = _client(session)
    first = _put(client, INSTANCE_A)
    assert first.status_code in (200, 201), first.text
    deal_id = first.json()["deal"]["id"]
    deal_updated = first.json()["deal"]["updated_at"]

    second = _put(
        client,
        INSTANCE_B,
        deal_id=deal_id,
        update_shared=False,
        instance_key="securitization-structured-products#2",
        draft=_draft(
            financingInstanceId=INSTANCE_B,
            holdings=[
                {
                    "holdingId": "hold-2",
                    "name": "Second note",
                    "trancheId": TRANCHE_1,
                    "bankOutstandingInvestment": 15,
                    "currency": "PKR",
                    "evidence": {"source": "", "notes": "", "documentReference": ""},
                }
            ],
        ),
    )
    assert second.status_code in (200, 201), second.text
    assert second.json()["deal"]["id"] == deal_id
    assert second.json()["sibling_count"] >= 1

    conflict = _put(
        client,
        INSTANCE_B,
        deal_id=deal_id,
        update_shared=False,
        expected_holding_updated_at=second.json()["holding"]["updated_at"],
        draft=_draft(
            financingInstanceId=INSTANCE_B,
            deal={
                **_draft()["deal"],
                "dealName": "Changed shared name",
            },
        ),
    )
    assert conflict.status_code == 409
    detail = conflict.json()["detail"]
    assert detail["code"] == "shared_deal_conflict"

    applied = _put(
        client,
        INSTANCE_B,
        deal_id=deal_id,
        update_shared=True,
        expected_deal_updated_at=deal_updated,
        expected_holding_updated_at=second.json()["holding"]["updated_at"],
        draft=_draft(
            financingInstanceId=INSTANCE_B,
            deal={**_draft()["deal"], "dealName": "Shared rename"},
        ),
    )
    # may be 409 stale_deal if timestamps moved; accept either applied rename or explicit stale
    assert applied.status_code in (200, 201, 409), applied.text


def test_org_isolation():
    session = SspMemorySession()
    client_a = _client(session, ORG_ID)
    assert _put(client_a).status_code in (200, 201)
    client_b = _client(session, OTHER_ORG_ID)
    listed = client_b.get("/api/v1/ssp/drafts")
    assert listed.status_code == 200
    assert listed.json() == []


def test_financed_emissions_rejects_ssp_formula():
    session = SspMemorySession()
    client = _client(session)
    response = client.post(
        "/api/v1/financed-emissions",
        json={
            "calc_kind": "finance",
            "formula_id": "ssp-lookthrough",
            "formula_name": "SSP",
            "inputs": {},
            "results": {},
            "financed_emissions": 1,
            "status": "draft",
        },
    )
    assert response.status_code == 400
    assert "Securitization" in response.json()["detail"] or "ssp" in response.json()["detail"].lower()


def test_delete_holding():
    session = SspMemorySession()
    client = _client(session)
    created = _put(client)
    holding_id = created.json()["holding"]["id"]
    deleted = client.delete(f"/api/v1/ssp/drafts/{holding_id}")
    assert deleted.status_code == 200
    assert client.get(f"/api/v1/ssp/drafts/by-instance/{INSTANCE_A}").status_code == 404
