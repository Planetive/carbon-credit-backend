"""
Phase 5D — reportable UoP parent Save, overlap gates, and dashboard selection.

In-memory coverage of the 16 required flows. Isolated Postgres lives in
test_uop_reportable_postgres.py and must not use the production DATABASE_URL.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fastapi_app.calculation_engine import CalculationEngine
from fastapi_app.db import get_db
from fastapi_app.finance_models import CompanyType
from fastapi_app.ghg_models import FinancedEmission
from fastapi_app.routers import financed_emissions as financed_routes
from fastapi_app.routers import uop_calculate as uop_calc_routes
from fastapi_app.routers import uop_drafts as uop_routes
from fastapi_app.routers.deps import require_org_context
from fastapi_app.uop_models import UopAssetCalculation, UopInvestment
from fastapi_app.uop_reportable import (
    UOP_REPORTABLE_SAVE_ENABLED,
    _row_year,
    calculation_fingerprint,
    reportable_save_enabled,
    select_component_rows,
)
from tests.test_uop_calculate import (
    ASSET_A,
    ASSET_B,
    ASSET_C,
    _integrated,
    _separate,
)
from tests.test_uop_drafts import (
    COUNTERPARTY_ID,
    INSTANCE_A,
    INSTANCE_B,
    ORG_ID,
    OTHER_ORG_ID,
    UopMemorySession,
    _ctx,
    _put,
)

GP_INSTANCE = "gp-general-purpose-1"


def _client(session, org_id=ORG_ID):
    app = FastAPI()
    app.include_router(uop_routes.router, prefix="/api/v1")
    app.include_router(uop_calc_routes.router, prefix="/api/v1")
    app.include_router(financed_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_org_context] = lambda: _ctx(org_id)
    app.dependency_overrides[get_db] = lambda: session
    return TestClient(app)


def _enable_save(monkeypatch):
    monkeypatch.delenv("UOP_REPORTABLE_SAVE_ENABLED", raising=False)
    monkeypatch.setattr("fastapi_app.uop_reportable.UOP_REPORTABLE_SAVE_ENABLED", True)


def _calc(client, instance, draft, **extra):
    body = {
        "financing_instance_id": instance,
        "counterparty_id": str(COUNTERPARTY_ID),
        "draft": draft,
        "persist": True,
    }
    body.update(extra)
    return client.post("/api/v1/uop/calculate", json=body)


def _save(client, instance, draft, fingerprint, **extra):
    return _calc(
        client,
        instance,
        draft,
        persist_reportable=True,
        expected_fingerprint=fingerprint,
        **extra,
    )


def _rows(session, model):
    tables = getattr(session, "tables", None)
    if tables is not None:
        return list(tables.get(model, []))
    return session.query(model).all()


def _parents(session):
    return _rows(session, FinancedEmission)


def _dashboard_total(session):
    selected, total = select_component_rows(_parents(session))
    return selected, total


def test_release_flag_defaults_off():
    assert UOP_REPORTABLE_SAVE_ENABLED is False
    assert reportable_save_enabled() is False


def test_13_flag_off_blocks_reportable_save(monkeypatch):
    monkeypatch.delenv("UOP_REPORTABLE_SAVE_ENABLED", raising=False)
    monkeypatch.setattr("fastapi_app.uop_reportable.UOP_REPORTABLE_SAVE_ENABLED", False)
    session = UopMemorySession()
    client = _client(session)
    _put(client, INSTANCE_A, draft=_separate())
    preview = _calc(client, INSTANCE_A, _separate())
    assert preview.status_code == 200
    blocked = _save(
        client,
        INSTANCE_A,
        _separate(),
        preview.json()["calculation_fingerprint"],
    )
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "UOP_REPORTABLE_SAVE_DISABLED"
    assert _parents(session) == []


def test_01_separate_calculate_save_dashboard(monkeypatch):
    _enable_save(monkeypatch)
    session = UopMemorySession()
    client = _client(session)
    _put(client, INSTANCE_A, draft=_separate())
    preview = _calc(client, INSTANCE_A, _separate())
    assert preview.status_code == 200
    body = preview.json()
    assert body["financed_emissions"] == pytest.approx(46.0)
    assert body["data_quality_score"] == pytest.approx(1.4)
    assert body["is_reportable"] is False
    saved = _save(client, INSTANCE_A, _separate(), body["calculation_fingerprint"])
    assert saved.status_code == 200, saved.text
    payload = saved.json()
    assert payload["is_reportable"] is True
    assert payload["include_in_portfolio"] is True
    assert payload["persisted_reportable"] is True
    assert payload["formula_id"] == "uop-separate-lookthrough"
    parents = _parents(session)
    assert len(parents) == 1
    row = parents[0]
    assert row.organization_id == ORG_ID
    assert row.counterparty_id == COUNTERPARTY_ID
    assert row.inputs["financing_instance_id"] == INSTANCE_A
    assert row.inputs["reporting_year"] == "2026"
    assert row.formula_id == "uop-separate-lookthrough"
    assert float(row.financed_emissions) == pytest.approx(46.0)
    assert float(row.data_quality_score) == pytest.approx(1.4)
    assert row.results["reporting_role"] == "uop_parent"
    assert row.results["include_underlying_independently"] is False
    for calc in _rows(session, UopAssetCalculation):
        assert calc.is_reportable is False
        assert calc.include_in_portfolio is False
    selected, total = _dashboard_total(session)
    assert len(selected) == 1
    assert total == pytest.approx(46.0)


def test_02_integrated_calculate_save_dashboard(monkeypatch):
    _enable_save(monkeypatch)
    session = UopMemorySession()
    client = _client(session)
    draft = _integrated()
    _put(client, INSTANCE_A, draft=draft)
    preview = _calc(client, INSTANCE_A, draft)
    saved = _save(client, INSTANCE_A, draft, preview.json()["calculation_fingerprint"])
    assert saved.status_code == 200, saved.text
    assert saved.json()["formula_id"] == "uop-integrated-lookthrough"
    assert saved.json()["financed_emissions"] == pytest.approx(5.0)
    selected, total = _dashboard_total(session)
    assert total == pytest.approx(5.0)
    assert selected[0].formula_id == "uop-integrated-lookthrough"


def test_03_issuer_reported_parent(monkeypatch):
    _enable_save(monkeypatch)
    session = UopMemorySession()
    client = _client(session)
    draft = _separate(
        emissionsPath="issuer_reported",
        issuerReportedFinancedEmissions=200,
        issuerReportYear="2026",
        issuerReportSource="Green Bond allocation and impact report",
        issuerReportVerification="verified",
        outstandingInvestment=10_000_000,
        assets=[],
    )
    _put(client, INSTANCE_A, draft=draft)
    preview = _calc(client, INSTANCE_A, draft)
    saved = _save(client, INSTANCE_A, draft, preview.json()["calculation_fingerprint"])
    assert saved.status_code == 200, saved.text
    assert saved.json()["formula_id"] == "uop-issuer-reported"
    assert saved.json()["financed_emissions"] == pytest.approx(20.0)
    assert saved.json()["data_quality_score"] == pytest.approx(1.0)
    assert len(_parents(session)) == 1
    assert _rows(session, UopAssetCalculation) == [] or all(
        row.is_reportable is False for row in _rows(session, UopAssetCalculation)
    )


def test_04_two_investments_same_fund_independent(monkeypatch):
    _enable_save(monkeypatch)
    session = UopMemorySession()
    client = _client(session)
    first_draft = _separate(outstandingInvestment=50_000_000)
    first = _put(client, INSTANCE_A, draft=first_draft)
    structure_id = first.json()["structure"]["id"]
    second_draft = _separate(
        outstandingInvestment=20_000_000,
        financingInstanceId=INSTANCE_B,
        instanceKey="use-of-proceeds#2",
    )
    _put(
        client,
        INSTANCE_B,
        instance_key="use-of-proceeds#2",
        structure_id=structure_id,
        draft=second_draft,
    )
    structure_ts = client.get(f"/api/v1/uop/drafts/by-instance/{INSTANCE_A}").json()[
        "structure"
    ]["updated_at"]
    preview_a = _calc(
        client,
        INSTANCE_A,
        first_draft,
        expected_structure_updated_at=structure_ts,
    )
    saved_a = _save(
        client,
        INSTANCE_A,
        first_draft,
        preview_a.json()["calculation_fingerprint"],
        expected_structure_updated_at=preview_a.json().get("structure_updated_at")
        or structure_ts,
    )
    assert saved_a.status_code == 200, saved_a.text
    structure_ts = client.get(f"/api/v1/uop/drafts/by-instance/{INSTANCE_B}").json()[
        "structure"
    ]["updated_at"]
    preview_b = _calc(
        client,
        INSTANCE_B,
        second_draft,
        expected_structure_updated_at=structure_ts,
    )
    saved_b = _save(
        client,
        INSTANCE_B,
        second_draft,
        preview_b.json()["calculation_fingerprint"],
        expected_structure_updated_at=preview_b.json().get("structure_updated_at")
        or structure_ts,
    )
    assert saved_b.status_code == 200, saved_b.text
    assert saved_a.json()["financed_emissions"] == pytest.approx(46.0)
    assert saved_b.json()["financed_emissions"] == pytest.approx(18.4)
    parents = _parents(session)
    assert len(parents) == 2
    selected, total = _dashboard_total(session)
    assert len(selected) == 2
    assert total == pytest.approx(64.4)


def test_05_two_underlying_same_class_one_parent(monkeypatch):
    _enable_save(monkeypatch)
    session = UopMemorySession()
    client = _client(session)
    draft = _separate(
        assets=[
            {
                "underlyingAssetId": ASSET_A,
                "name": "Mortgage pool A",
                "assetClass": "mortgage",
                "allocatedOutstanding": 6_000_000,
                "totalAssetValue": 10_000_000,
                "hasReportedEmissions": "yes",
                "verificationStatus": "verified",
                "scope1Emissions": 100,
                "scope2Emissions": 20,
                "dataSource": "allocation report",
                "estimation": {},
            },
            {
                "underlyingAssetId": ASSET_C,
                "name": "Mortgage pool C",
                "assetClass": "mortgage",
                "allocatedOutstanding": 4_000_000,
                "totalAssetValue": 8_000_000,
                "hasReportedEmissions": "yes",
                "verificationStatus": "unverified",
                "scope1Emissions": 40,
                "dataSource": "borrower report",
                "estimation": {},
            },
        ]
    )
    _put(client, INSTANCE_A, draft=draft)
    preview = _calc(client, INSTANCE_A, draft)
    saved = _save(client, INSTANCE_A, draft, preview.json()["calculation_fingerprint"])
    assert saved.status_code == 200, saved.text
    assert len(saved.json()["assets"]) == 2
    assert len(_parents(session)) == 1
    selected, total = _dashboard_total(session)
    assert len(selected) == 1
    assert total == pytest.approx(saved.json()["financed_emissions"])


def test_06_recalculate_save_does_not_duplicate(monkeypatch):
    _enable_save(monkeypatch)
    session = UopMemorySession()
    client = _client(session)
    draft = _separate()
    _put(client, INSTANCE_A, draft=draft)
    first_fp = _calc(client, INSTANCE_A, draft).json()["calculation_fingerprint"]
    first = _save(client, INSTANCE_A, draft, first_fp)
    assert first.status_code == 200
    first_id = first.json()["reportable_record_id"]
    second_fp = _calc(client, INSTANCE_A, draft).json()["calculation_fingerprint"]
    second = _save(client, INSTANCE_A, draft, second_fp)
    assert second.status_code == 200, second.text
    assert second.json()["reportable_record_id"] == first_id
    assert len(_parents(session)) == 1


def test_07b_year_aware_identity_saves_years_independently(monkeypatch):
    _enable_save(monkeypatch)
    session = UopMemorySession(year_aware_identity=True)
    client = _client(session)
    draft_2026 = _separate(reportingYear="2026")
    _put(client, INSTANCE_A, draft=draft_2026)
    fp = _calc(client, INSTANCE_A, draft_2026).json()["calculation_fingerprint"]
    saved_2026 = _save(client, INSTANCE_A, draft_2026, fp)
    assert saved_2026.status_code == 200, saved_2026.text
    original_id = saved_2026.json()["reportable_record_id"]
    draft_2025 = _separate(reportingYear="2025")
    _put(client, INSTANCE_A, draft=draft_2025)
    fp_2025 = _calc(client, INSTANCE_A, draft_2025).json()["calculation_fingerprint"]
    saved_2025 = _save(client, INSTANCE_A, draft_2025, fp_2025)
    assert saved_2025.status_code == 200, saved_2025.text
    assert saved_2025.json()["reportable_record_id"] != original_id
    parents = _parents(session)
    assert len(parents) == 2
    years = {row.inputs.get("reporting_year") for row in parents}
    assert years == {"2025", "2026"}
    selected, total = _dashboard_total(session)
    assert len(selected) == 1
    assert total == pytest.approx(46.0)
    fp_2025_again = _calc(client, INSTANCE_A, draft_2025).json()["calculation_fingerprint"]
    again = _save(client, INSTANCE_A, draft_2025, fp_2025_again)
    assert again.status_code == 200
    assert again.json()["reportable_record_id"] == saved_2025.json()["reportable_record_id"]
    assert len(_parents(session)) == 2


def test_07_reporting_year_conflict_does_not_overwrite(monkeypatch):
    _enable_save(monkeypatch)
    session = UopMemorySession()
    client = _client(session)
    draft_2026 = _separate(reportingYear="2026")
    created = _put(client, INSTANCE_A, draft=draft_2026)
    fp = _calc(client, INSTANCE_A, draft_2026).json()["calculation_fingerprint"]
    saved = _save(client, INSTANCE_A, draft_2026, fp)
    assert saved.status_code == 200
    original_total = saved.json()["financed_emissions"]
    draft_2025 = _separate(reportingYear="2025")
    updated = _put(client, INSTANCE_A, draft=draft_2025)
    assert updated.status_code == 200
    fp_2025 = _calc(client, INSTANCE_A, draft_2025).json()["calculation_fingerprint"]
    conflict = _save(client, INSTANCE_A, draft_2025, fp_2025)
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "REPORTING_YEAR_CONFLICT"
    parents = _parents(session)
    assert len(parents) == 1
    assert parents[0].inputs["reporting_year"] == "2026"
    assert float(parents[0].financed_emissions) == pytest.approx(original_total)
    assert created.json()["investment"]["id"]


def test_08_scope_reconciliation_on_parent(monkeypatch):
    _enable_save(monkeypatch)
    session = UopMemorySession()
    client = _client(session)
    draft = _separate()
    _put(client, INSTANCE_A, draft=draft)
    fp = _calc(client, INSTANCE_A, draft).json()["calculation_fingerprint"]
    saved = _save(client, INSTANCE_A, draft, fp).json()
    breakdown = saved["scope_breakdown"]
    included = (breakdown["financed_scope1_tco2e"] or 0) + (
        breakdown["financed_scope2_tco2e"] or 0
    )
    unallocated = breakdown["financed_unallocated_tco2e"] or 0
    assert included + unallocated == pytest.approx(saved["financed_emissions"])
    row = _parents(session)[0]
    assert row.results["financed_scope1_tco2e"] == pytest.approx(40.0)
    assert row.results["financed_scope2_tco2e"] == pytest.approx(6.0)
    assert row.results["financed_scope3_tco2e"] is None


def test_09_weighted_data_quality_on_parent(monkeypatch):
    _enable_save(monkeypatch)
    session = UopMemorySession()
    client = _client(session)
    draft = _separate()
    _put(client, INSTANCE_A, draft=draft)
    fp = _calc(client, INSTANCE_A, draft).json()["calculation_fingerprint"]
    saved = _save(client, INSTANCE_A, draft, fp)
    assert saved.json()["data_quality_score"] == pytest.approx(1.4)
    assert float(_parents(session)[0].data_quality_score) == pytest.approx(1.4)


def test_10_category_15_includes_parent_once(monkeypatch):
    _enable_save(monkeypatch)
    session = UopMemorySession()
    client = _client(session)
    draft = _separate()
    _put(client, INSTANCE_A, draft=draft)
    fp = _calc(client, INSTANCE_A, draft).json()["calculation_fingerprint"]
    _save(client, INSTANCE_A, draft, fp)
    listed = client.get("/api/v1/financed-emissions").json()
    assert len(listed) == 1
    selected, total = _dashboard_total(session)
    assert len(selected) == 1
    assert total == pytest.approx(46.0)
    assert listed[0]["formula_id"] == "uop-separate-lookthrough"
    assert listed[0]["results"]["reporting_role"] == "uop_parent"


def test_11_export_fields_match_parent(monkeypatch):
    _enable_save(monkeypatch)
    session = UopMemorySession()
    client = _client(session)
    draft = _separate()
    _put(client, INSTANCE_A, draft=draft)
    fp = _calc(client, INSTANCE_A, draft).json()["calculation_fingerprint"]
    saved = _save(client, INSTANCE_A, draft, fp).json()
    row = client.get("/api/v1/financed-emissions").json()[0]
    csv_line = ",".join(
        [
            row["formula_id"],
            row["inputs"]["reporting_year"],
            str(row["financed_emissions"]),
            str(row["data_quality_score"]),
            row["results"]["scope_completeness"],
            row["status"],
        ]
    )
    assert saved["formula_id"] in csv_line
    assert "2026" in csv_line
    assert str(saved["financed_emissions"]) in csv_line or "46" in csv_line
    assert row["results"]["methodology_version"] == saved["methodology_version"]


def test_12_uop_plus_general_purpose_overlap_flagged(monkeypatch):
    _enable_save(monkeypatch)
    session = UopMemorySession()
    client = _client(session)
    gp = client.post(
        "/api/v1/financed-emissions",
        json={
            "calc_kind": "finance",
            "company_type": "listed",
            "formula_id": "mortgage",
            "formula_name": "Mortgage",
            "counterparty_id": str(COUNTERPARTY_ID),
            "inputs": {
                "financing_instance_id": GP_INSTANCE,
                "reporting_year": "2026",
                "companyName": "City Issuer",
            },
            "results": {"financed_emissions": 12},
            "financed_emissions": 12,
            "attribution_factor": 0.2,
            "data_quality_score": 2,
            "status": "completed",
        },
    )
    assert gp.status_code == 201, gp.text
    draft = _separate()
    _put(client, INSTANCE_A, draft=draft)
    preview = _calc(client, INSTANCE_A, draft)
    assert preview.json()["overlap"]["detected"] is True
    blocked = _save(client, INSTANCE_A, draft, preview.json()["calculation_fingerprint"])
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "UOP_OVERLAP_REVIEW_REQUIRED"
    assert blocked.json()["detail"]["redistribution"] == "none"
    selected, total = _dashboard_total(session)
    assert total == pytest.approx(12.0)
    assert all(row.formula_id != "uop-separate-lookthrough" for row in selected)


def test_13_incomplete_and_unsupported_blocked(monkeypatch):
    _enable_save(monkeypatch)
    session = UopMemorySession()
    client = _client(session)
    incomplete = _separate(
        assets=[
            {
                "underlyingAssetId": ASSET_A,
                "name": "Missing emissions",
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
    _put(client, INSTANCE_A, draft=incomplete)
    preview = _calc(client, INSTANCE_A, incomplete)
    assert preview.json()["status"] == "incomplete"
    blocked = _save(
        client, INSTANCE_A, incomplete, preview.json()["calculation_fingerprint"]
    )
    assert blocked.status_code == 422
    assert blocked.json()["detail"]["code"] == "UOP_CALCULATION_INCOMPLETE"
    assert _parents(session) == []

    nested = _separate(
        assets=[
            {
                "underlyingAssetId": "nested-uop",
                "name": "Nested fund",
                "assetClass": "use-of-proceeds",
                "allocatedOutstanding": 6_000_000,
                "totalAssetValue": 10_000_000,
                "hasReportedEmissions": "no",
                "dataSource": "n/a",
                "estimation": {},
            }
        ]
    )
    _put(client, INSTANCE_B, instance_key="use-of-proceeds#2", draft=nested)
    nested_preview = _calc(client, INSTANCE_B, nested)
    assert nested_preview.json()["status"] in ("unsupported", "incomplete")
    nested_blocked = _save(
        client, INSTANCE_B, nested, nested_preview.json()["calculation_fingerprint"]
    )
    assert nested_blocked.status_code in (409, 422)
    assert _parents(session) == []


def test_14_unauthorized_and_cross_org_blocked(monkeypatch):
    _enable_save(monkeypatch)
    session = UopMemorySession()
    owner = _client(session, ORG_ID)
    other = _client(session, OTHER_ORG_ID)
    draft = _separate()
    _put(owner, INSTANCE_A, draft=draft)
    preview = _calc(owner, INSTANCE_A, draft)
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
    assert _parents(session) == []
    listed = other.get("/api/v1/financed-emissions")
    assert listed.status_code == 200
    assert listed.json() == []


def test_15_stale_fingerprint_and_edited_draft_blocked(monkeypatch):
    _enable_save(monkeypatch)
    session = UopMemorySession()
    client = _client(session)
    draft = _separate()
    _put(client, INSTANCE_A, draft=draft)
    preview = _calc(client, INSTANCE_A, draft)
    stale = _save(client, INSTANCE_A, draft, "not-the-real-fingerprint")
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "UOP_STALE_CALCULATION"
    edited = _separate(outstandingInvestment=40_000_000)
    _put(client, INSTANCE_A, draft=edited)
    stale_after_edit = _save(
        client, INSTANCE_A, edited, preview.json()["calculation_fingerprint"]
    )
    assert stale_after_edit.status_code == 409
    assert stale_after_edit.json()["detail"]["code"] == "UOP_STALE_CALCULATION"
    assert _parents(session) == []


def test_16_existing_financed_emissions_regression_untouched():
    engine = CalculationEngine()
    sample_ids = {formula.id for formula in engine.formulas}
    assert "uop-separate-lookthrough" not in sample_ids
    sample = {
        "outstanding_amount": 1_000_000,
        "evic": 3_000_000,
        "verified_emissions": 90,
        "scope1_emissions": 90,
    }
    result = engine.calculate("1a-listed-equity", sample, CompanyType.LISTED)
    assert result.attribution_factor == pytest.approx(1 / 3)
    assert result.data_quality_score == 1


def test_fingerprint_is_stable_for_equivalent_payload():
    payload = {
        "formula_id": "uop-separate-lookthrough",
        "financed_emissions": 46.0,
        "allocated_financed_emissions": 46.0,
        "unallocated_financed_emissions": 0.0,
        "data_quality_score": 1.4,
        "investor_attribution": {"attribution_factor": 0.5},
        "scope_breakdown": {
            "financed_scope1_tco2e": 40,
            "financed_scope2_tco2e": 6,
            "financed_scope3_tco2e": None,
            "financed_unallocated_tco2e": 0,
            "scope_completeness": "partial",
        },
        "methodology_version": "PCAF-2025-PartA-5.7",
        "reporting_year": "2026",
        "assets": [
            {
                "underlying_asset_id": ASSET_B,
                "investor_financed_emissions": 10,
                "data_quality_score": 2,
            },
            {
                "underlying_asset_id": ASSET_A,
                "investor_financed_emissions": 36,
                "data_quality_score": 1,
            },
        ],
    }
    assert calculation_fingerprint(payload) == calculation_fingerprint(dict(payload))


def test_generic_financed_emissions_path_still_rejects_uop(monkeypatch):
    _enable_save(monkeypatch)
    session = UopMemorySession()
    client = _client(session)
    blocked = client.post(
        "/api/v1/financed-emissions/calculate",
        json={
            "formula_id": "uop-separate-lookthrough",
            "company_type": "listed",
            "inputs": {"financing_instance_id": INSTANCE_A},
        },
    )
    assert blocked.status_code == 400
    assert _parents(session) == []
    assert uuid.UUID(INSTANCE_A)
