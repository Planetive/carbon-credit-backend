"""UoP draft persistence. In-memory store only — no production Postgres, no formulas."""

from __future__ import annotations

import operator
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from fastapi_app.auth_models import User
from fastapi_app.auth_org import OrgContext
from fastapi_app.db import get_db
from fastapi_app.routers import financed_emissions as financed_routes
from fastapi_app.routers import uop_drafts as uop_routes
from fastapi_app.routers.deps import require_org_context
from fastapi_app.uop_drafts import is_uop_formula_id
from fastapi_app.financing_instance import (
    extract_financing_instance_id,
    extract_reporting_year,
    is_aggregate_formula,
)
from fastapi_app.ghg_models import FinancedEmission
from fastapi_app.uop_models import (
    UOP_NULL_COUNTERPARTY,
    UopAssetCalculation,
    UopInvestment,
    UopStructure,
    UopUnderlyingAsset,
)

ORG_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
OTHER_ORG_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
USER_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
COUNTERPARTY_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")

INSTANCE_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
INSTANCE_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
ASSET_M1 = "cccccccc-cccc-cccc-cccc-cccccccccccc"
ASSET_M2 = "dddddddd-dddd-dddd-dddd-dddddddddddd"


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
    def __init__(self, session: "UopMemorySession", model: type):
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


class UopMemorySession:
    def __init__(self, year_aware_identity: bool = False):
        self.tables: Dict[type, List[Any]] = defaultdict(list)
        self._pending: List[Any] = []
        self.committed = False
        self.rolled_back = False
        self.year_aware_identity = year_aware_identity

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
        seen_instances = {}
        for inv in self.tables[UopInvestment]:
            fid = (inv.financing_instance_id or "").strip()
            if not fid:
                raise IntegrityError("uop", {}, Exception("blank financing_instance_id"))
            key = (
                inv.organization_id,
                inv.counterparty_id or UOP_NULL_COUNTERPARTY,
                fid,
            )
            if key in seen_instances:
                raise IntegrityError("uop", {}, Exception("duplicate financing_instance_id"))
            seen_instances[key] = inv
        seen_assets = {}
        for asset in self.tables[UopUnderlyingAsset]:
            key = (asset.structure_id, (asset.underlying_asset_id or "").strip())
            if key in seen_assets:
                raise IntegrityError("uop", {}, Exception("duplicate underlying_asset_id"))
            seen_assets[key] = asset
        for calc in self.tables[UopAssetCalculation]:
            if calc.is_reportable or calc.include_in_portfolio:
                raise IntegrityError(
                    "uop", {}, Exception("underlying calculation must not be reportable")
                )
        seen_financed = {}
        for row in self.tables.get(FinancedEmission, []):
            if is_aggregate_formula(row.formula_id):
                continue
            fid = extract_financing_instance_id(getattr(row, "inputs", None))
            if not fid:
                continue
            year_key = (
                extract_reporting_year(row) or ""
                if self.year_aware_identity
                else ""
            )
            key = (
                row.organization_id,
                row.counterparty_id or UOP_NULL_COUNTERPARTY,
                row.calc_kind,
                fid,
                year_key,
            )
            if key in seen_financed:
                raise IntegrityError(
                    "financed_emissions",
                    {},
                    Exception("duplicate financing_instance_id"),
                )
            seen_financed[key] = row


def _user():
    return User(id=USER_ID, email="uop@example.com", password_hash="x")


def _ctx(org_id=ORG_ID):
    return OrgContext(user=_user(), organization_id=org_id, role="admin")


def _client(session, org_id=ORG_ID):
    app = FastAPI()
    app.include_router(uop_routes.router, prefix="/api/v1")
    app.include_router(financed_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_org_context] = lambda: _ctx(org_id)
    app.dependency_overrides[get_db] = lambda: session
    return TestClient(app)


def _draft(**overrides):
    payload = {
        "financingInstanceId": INSTANCE_A,
        "instanceKey": "use-of-proceeds#1",
        "eligibility": {
            "proceedsAllocatedToSpecificAssets": "yes",
            "isSecuritized": "no",
            "structureHasControl": "no",
            "structureListing": "",
            "controlOneFullyAllocatedAsset": "",
            "controlAssetIsProject": "",
            "debtBasedWithOneFullyAllocatedAsset": "",
            "singleAssetClass": "",
            "assetsOnIssuerBalanceSheet": "yes",
        },
        "structureName": "Green Bond 2026",
        "issuerName": "City Issuer",
        "structureKind": "labeled-bond",
        "classification": "separate",
        "investmentType": "debt",
        "outstandingInvestment": 1_000_000,
        "totalStructureDebt": 10_000_000,
        "totalStructureEquity": 0,
        "reportingYear": "2026",
        "currency": "PKR",
        "evidenceSource": "bond prospectus",
        "evidenceNotes": "use-of-proceeds schedule",
        "emissionsPath": "underlying_assets",
        "issuerLevelReason": "",
        "issuerReportedFinancedEmissions": None,
        "issuerReportYear": "",
        "issuerReportVerification": "",
        "issuerReportSource": "",
        "allocationStatus": "known",
        "allocatedProceeds": 8_000_000,
        "unallocatedProceeds": 2_000_000,
        "expectedAllocationEvidence": "annual allocation report",
        "unallocatedUsesAssetLevelEstimate": "no",
        "assets": [
            {
                "underlyingAssetId": ASSET_M1,
                "name": "Mortgage pool A",
                "assetClass": "mortgage",
                "allocatedOutstanding": 4_000_000,
                "totalAssetValue": 5_000_000,
                "hasReportedEmissions": "yes",
                "verificationStatus": "verified",
                "verifierName": "Verifier Co",
                "scope1Emissions": 10,
                "scope2Emissions": 2,
                "scope3Emissions": None,
                "dataSource": "issuer report",
                "evidenceNotes": "page 12",
                "estimation": {},
            },
            {
                "underlyingAssetId": ASSET_M2,
                "name": "Mortgage pool B",
                "assetClass": "mortgage",
                "allocatedOutstanding": 4_000_000,
                "totalAssetValue": 4_500_000,
                "hasReportedEmissions": "no",
                "verificationStatus": "",
                "verifierName": "",
                "scope1Emissions": None,
                "scope2Emissions": None,
                "scope3Emissions": None,
                "dataSource": "",
                "evidenceNotes": "",
                "estimation": {"method": "economic"},
            },
        ],
    }
    payload.update(overrides)
    return payload


def _amount(value) -> Decimal:
    return Decimal(str(value))


def _put(client, financing_instance_id=INSTANCE_A, **overrides):
    body = {
        "financing_instance_id": financing_instance_id,
        "instance_key": "use-of-proceeds#1",
        "counterparty_id": str(COUNTERPARTY_ID),
        "draft": _draft(financingInstanceId=financing_instance_id),
    }
    body.update(overrides)
    return client.put("/api/v1/uop/drafts", json=body)


def test_is_uop_formula_id_does_not_match_existing_pcaf_keys():
    assert is_uop_formula_id("uop-separate") is True
    assert is_uop_formula_id("use-of-proceeds") is True
    assert is_uop_formula_id("1a-business-loans") is False
    assert is_uop_formula_id("mortgage") is False
    assert is_uop_formula_id("aggregate") is False


def test_create_draft_persists_parent_child_and_not_reportable():
    session = UopMemorySession()
    client = _client(session)
    created = _put(client)
    assert created.status_code == 201
    body = created.json()
    assert body["created"] is True
    assert body["investment"]["financing_instance_id"] == INSTANCE_A
    assert body["investment"]["formula_id"] is None
    assert body["investment"]["is_reportable"] is False
    assert body["investment"]["include_in_portfolio"] is False
    assert _amount(body["investment"]["outstanding_amount"]) == Decimal("1000000")
    assert body["structure"]["classification"] == "separate"
    assert body["structure"]["name"] == "Green Bond 2026"
    assert body["structure"]["methodology_version"] == "PCAF-2025-PartA-5.7"
    assert body["structure"]["reporting_year"] == "2026"
    classes = [asset["asset_class"] for asset in body["assets"]]
    assert classes == ["mortgage", "mortgage"]
    assert len(body["calculations"]) == 2
    for calc in body["calculations"]:
        assert calc["is_reportable"] is False
        assert calc["include_in_portfolio"] is False
        assert calc["status"] == "draft"
        assert calc["financed_emissions"] is None
        assert calc["provenance"]["formula_implemented"] is False
    assert len(session.tables[UopStructure]) == 1
    assert len(session.tables[UopInvestment]) == 1
    assert len(session.tables[UopUnderlyingAsset]) == 2
    assert len(session.tables[UopAssetCalculation]) == 2
    assert session.committed is True


def test_update_same_instance_reloads_without_duplicating():
    session = UopMemorySession()
    client = _client(session)
    created = _put(client)
    investment_id = created.json()["investment"]["id"]
    structure_id = created.json()["structure"]["id"]
    updated = _put(
        client,
        draft=_draft(structureName="Green Bond 2026 amended", outstandingInvestment=1_250_000),
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["created"] is False
    assert body["investment"]["id"] == investment_id
    assert body["structure"]["id"] == structure_id
    assert body["structure"]["name"] == "Green Bond 2026 amended"
    assert _amount(body["investment"]["outstanding_amount"]) == Decimal("1250000")
    assert len(session.tables[UopInvestment]) == 1
    assert len(session.tables[UopStructure]) == 1
    reloaded = client.get(f"/api/v1/uop/drafts/by-instance/{INSTANCE_A}")
    assert reloaded.status_code == 200
    assert reloaded.json()["draft"]["structureName"] == "Green Bond 2026 amended"
    assert reloaded.json()["draft"]["financingInstanceId"] == INSTANCE_A


def test_multiple_investments_in_same_structure_do_not_overwrite_each_other():
    session = UopMemorySession()
    client = _client(session)
    first = _put(client, INSTANCE_A)
    structure_id = first.json()["structure"]["id"]
    second = _put(
        client,
        INSTANCE_B,
        instance_key="use-of-proceeds#2",
        structure_id=structure_id,
        draft=_draft(
            financingInstanceId=INSTANCE_B,
            instanceKey="use-of-proceeds#2",
            outstandingInvestment=500_000,
            structureName="Green Bond 2026",
        ),
    )
    assert second.status_code == 201
    assert second.json()["structure"]["id"] == structure_id
    assert second.json()["investment"]["financing_instance_id"] == INSTANCE_B
    assert _amount(second.json()["investment"]["outstanding_amount"]) == Decimal("500000")
    assert len(session.tables[UopInvestment]) == 2
    assert len(session.tables[UopStructure]) == 1

    hijack = client.put(
        "/api/v1/uop/drafts",
        json={
            "financing_instance_id": INSTANCE_B,
            "counterparty_id": str(COUNTERPARTY_ID),
            "structure_id": structure_id,
            "draft": _draft(
                financingInstanceId=INSTANCE_B,
                outstandingInvestment=750_000,
                structureName="Shared structure",
            ),
        },
    )
    assert hijack.status_code == 409
    assert hijack.json()["detail"]["code"] == "shared_structure_conflict"

    investment_only = _put(
        client,
        INSTANCE_B,
        structure_id=structure_id,
        draft=_draft(
            financingInstanceId=INSTANCE_B,
            outstandingInvestment=750_000,
            structureName="Green Bond 2026",
        ),
    )
    assert investment_only.status_code == 200
    assert investment_only.json()["shared_write_applied"] is False
    first_reload = client.get(f"/api/v1/uop/drafts/by-instance/{INSTANCE_A}")
    second_reload = client.get(f"/api/v1/uop/drafts/by-instance/{INSTANCE_B}")
    assert _amount(first_reload.json()["investment"]["outstanding_amount"]) == Decimal("1000000")
    assert _amount(second_reload.json()["investment"]["outstanding_amount"]) == Decimal("750000")
    assert first_reload.json()["structure"]["name"] == "Green Bond 2026"
    assert second_reload.json()["structure"]["name"] == "Green Bond 2026"
    assert first_reload.json()["draft"]["structureName"] == "Green Bond 2026"
    assert first_reload.json()["investment"]["id"] != second_reload.json()["investment"]["id"]
    listed = client.get(f"/api/v1/uop/drafts?structure_id={structure_id}")
    assert listed.status_code == 200
    assert len(listed.json()) == 2


def test_multiple_same_class_assets_are_distinct():
    session = UopMemorySession()
    client = _client(session)
    body = _put(client).json()
    ids = [asset["underlying_asset_id"] for asset in body["assets"]]
    assert ids == [ASSET_M1, ASSET_M2]
    assert [asset["asset_class"] for asset in body["assets"]] == ["mortgage", "mortgage"]
    assert body["assets"][0]["id"] != body["assets"][1]["id"]
    calcs_by_asset = {calc["asset_id"] for calc in body["calculations"]}
    assert calcs_by_asset == {body["assets"][0]["id"], body["assets"][1]["id"]}


def test_formula_id_is_not_a_unique_exposure_key():
    session = UopMemorySession()
    client = _client(session)
    first = _put(client, INSTANCE_A, formula_id="uop-separate")
    second = _put(
        client,
        INSTANCE_B,
        instance_key="use-of-proceeds#2",
        formula_id="uop-separate",
        draft=_draft(financingInstanceId=INSTANCE_B, outstandingInvestment=2),
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["investment"]["formula_id"] == "uop-separate"
    assert second.json()["investment"]["formula_id"] == "uop-separate"
    assert first.json()["investment"]["id"] != second.json()["investment"]["id"]
    assert len(session.tables[UopInvestment]) == 2


def test_authorization_boundary_hides_other_org_drafts():
    session = UopMemorySession()
    owner = _client(session, ORG_ID)
    created = _put(owner)
    investment_id = created.json()["investment"]["id"]
    foreign = _client(session, OTHER_ORG_ID)
    missing = foreign.get(f"/api/v1/uop/drafts/{investment_id}")
    assert missing.status_code == 404
    listed = foreign.get("/api/v1/uop/drafts")
    assert listed.status_code == 200
    assert listed.json() == []
    by_instance = foreign.get(f"/api/v1/uop/drafts/by-instance/{INSTANCE_A}")
    assert by_instance.status_code == 404
    patched = foreign.patch(
        f"/api/v1/uop/drafts/{investment_id}",
        json={"draft": {"structureName": "hijack"}},
    )
    assert patched.status_code == 404
    assert created.json()["structure"]["name"] == "Green Bond 2026"


def test_unauthenticated_draft_is_rejected():
    app = FastAPI()
    app.include_router(uop_routes.router, prefix="/api/v1")
    client = TestClient(app)
    response = client.put(
        "/api/v1/uop/drafts",
        json={"financing_instance_id": INSTANCE_A, "draft": _draft()},
    )
    assert response.status_code in (401, 403)


def test_whitespace_instance_id_normalizes_and_resumes():
    session = UopMemorySession()
    client = _client(session)
    created = _put(client, financing_instance_id=f"  {INSTANCE_A}  ")
    assert created.status_code == 201
    assert created.json()["investment"]["financing_instance_id"] == INSTANCE_A
    resumed = client.get(f"/api/v1/uop/drafts/by-instance/{INSTANCE_A}")
    assert resumed.status_code == 200
    assert resumed.json()["investment"]["id"] == created.json()["investment"]["id"]


def test_integrated_equity_is_rejected():
    session = UopMemorySession()
    client = _client(session)
    response = _put(
        client,
        draft=_draft(classification="integrated", investmentType="equity"),
    )
    assert response.status_code == 422
    assert "debt-only" in response.json()["detail"]
    assert session.tables[UopInvestment] == []


def test_blank_financing_instance_id_is_rejected():
    session = UopMemorySession()
    client = _client(session)
    response = client.put(
        "/api/v1/uop/drafts",
        json={"financing_instance_id": "   ", "draft": _draft()},
    )
    assert response.status_code == 422
    assert session.tables[UopInvestment] == []


def test_financed_emissions_rejects_uop_formula_without_writing():
    session = UopMemorySession()
    client = _client(session)
    created = client.post(
        "/api/v1/financed-emissions",
        json={
            "formula_id": "uop-separate",
            "inputs": {"financing_instance_id": INSTANCE_A},
        },
    )
    assert created.status_code == 400
    assert "uop/drafts" in created.json()["detail"]
    calculated = client.post(
        "/api/v1/financed-emissions/calculate",
        json={
            "formula_id": "use-of-proceeds",
            "company_type": "listed",
            "inputs": {"financing_instance_id": INSTANCE_A},
        },
    )
    assert calculated.status_code == 400
    assert session.tables[UopInvestment] == []


def test_delete_one_investment_keeps_sibling_and_shared_assets():
    session = UopMemorySession()
    client = _client(session)
    first = _put(client, INSTANCE_A)
    structure_id = first.json()["structure"]["id"]
    second = _put(
        client,
        INSTANCE_B,
        structure_id=structure_id,
        draft=_draft(financingInstanceId=INSTANCE_B, outstandingInvestment=9),
    )
    deleted = client.delete(f"/api/v1/uop/drafts/{second.json()['investment']['id']}")
    assert deleted.status_code == 200
    remaining = client.get(f"/api/v1/uop/drafts/by-instance/{INSTANCE_A}")
    assert remaining.status_code == 200
    assert remaining.json()["structure"]["id"] == structure_id
    assert len(remaining.json()["assets"]) == 2
    missing = client.get(f"/api/v1/uop/drafts/by-instance/{INSTANCE_B}")
    assert missing.status_code == 404


def test_attach_ignores_shared_payload_unless_authorized():
    session = UopMemorySession()
    client = _client(session)
    first = _put(client, INSTANCE_A)
    structure_id = first.json()["structure"]["id"]
    attached = _put(
        client,
        INSTANCE_B,
        structure_id=structure_id,
        draft=_draft(
            financingInstanceId=INSTANCE_B,
            outstandingInvestment=250_000,
            structureName="Attempted overwrite",
            issuerName="Other issuer",
        ),
    )
    assert attached.status_code == 201
    assert attached.json()["shared_write_applied"] is False
    assert attached.json()["structure"]["name"] == "Green Bond 2026"
    assert attached.json()["draft"]["structureName"] == "Green Bond 2026"
    assert attached.json()["draft"]["issuerName"] == "City Issuer"
    assert _amount(attached.json()["investment"]["outstanding_amount"]) == Decimal("250000")
    original = client.get(f"/api/v1/uop/drafts/by-instance/{INSTANCE_A}")
    assert original.json()["structure"]["name"] == "Green Bond 2026"
    assert _amount(original.json()["investment"]["outstanding_amount"]) == Decimal("1000000")


def test_authorized_shared_update_requires_structure_timestamp():
    session = UopMemorySession()
    client = _client(session)
    first = _put(client, INSTANCE_A)
    structure_id = first.json()["structure"]["id"]
    structure_ts = first.json()["structure"]["updated_at"]
    _put(
        client,
        INSTANCE_B,
        structure_id=structure_id,
        draft=_draft(financingInstanceId=INSTANCE_B, outstandingInvestment=9),
    )
    missing_ts = client.put(
        "/api/v1/uop/drafts",
        json={
            "financing_instance_id": INSTANCE_B,
            "counterparty_id": str(COUNTERPARTY_ID),
            "structure_id": structure_id,
            "update_shared": True,
            "draft": _draft(
                financingInstanceId=INSTANCE_B,
                outstandingInvestment=9,
                structureName="Renamed fund",
            ),
        },
    )
    assert missing_ts.status_code == 409
    assert missing_ts.json()["detail"]["code"] == "stale_structure"

    stale = client.put(
        "/api/v1/uop/drafts",
        json={
            "financing_instance_id": INSTANCE_B,
            "counterparty_id": str(COUNTERPARTY_ID),
            "structure_id": structure_id,
            "update_shared": True,
            "expected_structure_updated_at": "2020-01-01T00:00:00Z",
            "draft": _draft(
                financingInstanceId=INSTANCE_B,
                outstandingInvestment=9,
                structureName="Renamed fund",
            ),
        },
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "stale_structure"

    applied = client.put(
        "/api/v1/uop/drafts",
        json={
            "financing_instance_id": INSTANCE_B,
            "counterparty_id": str(COUNTERPARTY_ID),
            "structure_id": structure_id,
            "update_shared": True,
            "expected_structure_updated_at": structure_ts,
            "draft": _draft(
                financingInstanceId=INSTANCE_B,
                outstandingInvestment=9,
                structureName="Renamed fund",
            ),
        },
    )
    assert applied.status_code == 200
    assert applied.json()["shared_write_applied"] is True
    assert applied.json()["structure"]["name"] == "Renamed fund"
    first_reload = client.get(f"/api/v1/uop/drafts/by-instance/{INSTANCE_A}")
    assert first_reload.json()["structure"]["name"] == "Renamed fund"
    assert _amount(first_reload.json()["investment"]["outstanding_amount"]) == Decimal("1000000")


def test_stale_investment_timestamp_is_conflict():
    session = UopMemorySession()
    client = _client(session)
    created = _put(client)
    response = client.put(
        "/api/v1/uop/drafts",
        json={
            "financing_instance_id": INSTANCE_A,
            "counterparty_id": str(COUNTERPARTY_ID),
            "expected_investment_updated_at": "2020-01-01T00:00:00Z",
            "draft": _draft(outstandingInvestment=1_250_000),
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "stale_investment"
    assert created.json()["investment"]["id"] == client.get(
        f"/api/v1/uop/drafts/by-instance/{INSTANCE_A}"
    ).json()["investment"]["id"]


def test_reportable_flags_in_draft_payload_are_rejected():
    session = UopMemorySession()
    client = _client(session)
    response = _put(client, draft=_draft(is_reportable=True, include_in_portfolio=True))
    assert response.status_code == 422
    assert session.tables[UopInvestment] == []


def test_invalid_classification_is_rejected():
    session = UopMemorySession()
    client = _client(session)
    response = _put(client, draft=_draft(classification="not-a-pcaf-class"))
    assert response.status_code == 422
    assert session.tables[UopInvestment] == []


def test_reporting_year_change_keeps_prior_year_calc_snapshot():
    session = UopMemorySession()
    client = _client(session)
    created = _put(client)
    assert created.status_code == 201
    updated = _put(client, draft=_draft(reportingYear="2025"))
    assert updated.status_code == 200
    years = {row.reporting_year for row in session.tables[UopAssetCalculation]}
    assert years == {"2026", "2025"}
    for calc in session.tables[UopAssetCalculation]:
        assert calc.is_reportable is False
        assert calc.include_in_portfolio is False


def test_get_composes_shared_tables_over_stale_snapshot():
    session = UopMemorySession()
    client = _client(session)
    created = _put(client)
    investment = session.tables[UopInvestment][0]
    investment.draft_snapshot = {
        **investment.draft_snapshot,
        "structureName": "Stale local name",
        "outstandingInvestment": 1,
    }
    reloaded = client.get(f"/api/v1/uop/drafts/{created.json()['investment']['id']}")
    assert reloaded.status_code == 200
    assert reloaded.json()["draft"]["structureName"] == "Green Bond 2026"
    assert _amount(reloaded.json()["draft"]["outstandingInvestment"]) == Decimal("1000000")
    assert reloaded.json()["draft"]["financingInstanceId"] == INSTANCE_A
    assert [asset["underlyingAssetId"] for asset in reloaded.json()["draft"]["assets"]] == [
        ASSET_M1,
        ASSET_M2,
    ]
