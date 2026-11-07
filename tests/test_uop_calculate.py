"""
Phase 5C — PCAF 2025 Part A §5.7 Use of Proceeds calculation engine.

Expected values are computed from the official Third Edition equations
(pages 98–109), not from matching frontend output.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fastapi_app.calculation_engine import CalculationEngine
from fastapi_app.db import get_db
from fastapi_app.finance_models import CompanyType
from fastapi_app.routers import financed_emissions as financed_routes
from fastapi_app.routers import uop_calculate as uop_calc_routes
from fastapi_app.routers import uop_drafts as uop_routes
from fastapi_app.routers.deps import require_org_context
from fastapi_app.uop_calc import calculate_uop_draft, investor_attribution
from fastapi_app.uop_models import UopAssetCalculation, UopInvestment
from tests.test_uop_drafts import (
    COUNTERPARTY_ID,
    INSTANCE_A,
    INSTANCE_B,
    ORG_ID,
    OTHER_ORG_ID,
    UopMemorySession,
    _ctx,
    _draft as _base_draft,
    _put,
)

FIXTURES = Path(__file__).parent / "fixtures" / "pcaf_phase3a_parity.json"
ASSET_A = "asset-mortgage-a"
ASSET_B = "asset-loan-b"
ASSET_C = "asset-mortgage-c"


def _client(session, org_id=ORG_ID):
    app = FastAPI()
    app.include_router(uop_routes.router, prefix="/api/v1")
    app.include_router(uop_calc_routes.router, prefix="/api/v1")
    app.include_router(financed_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_org_context] = lambda: _ctx(org_id)
    app.dependency_overrides[get_db] = lambda: session
    return TestClient(app)


def _separate(**overrides):
    payload = _base_draft(
        eligibility={
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
        structureKind="debt-fund",
        allocationStatus="known",
        allocatedProceeds=10_000_000,
        unallocatedProceeds=90_000_000,
        outstandingInvestment=50_000_000,
        totalStructureDebt=100_000_000,
        totalStructureEquity=0,
        emissionsPath="underlying_assets",
        assets=[
            {
                "underlyingAssetId": ASSET_A,
                "name": "Mortgage pool A",
                "assetClass": "mortgage",
                "allocatedOutstanding": 6_000_000,
                "totalAssetValue": 10_000_000,
                "hasReportedEmissions": "yes",
                "verificationStatus": "verified",
                "verifierName": "Verifier Co",
                "scope1Emissions": 100,
                "scope2Emissions": 20,
                "scope3Emissions": None,
                "dataSource": "allocation report",
                "evidenceNotes": "",
                "estimation": {},
            },
            {
                "underlyingAssetId": ASSET_B,
                "name": "Business loan B",
                "assetClass": "business-loan",
                "allocatedOutstanding": 4_000_000,
                "totalAssetValue": 8_000_000,
                "hasReportedEmissions": "yes",
                "verificationStatus": "unverified",
                "verifierName": "",
                "scope1Emissions": 40,
                "scope2Emissions": None,
                "scope3Emissions": None,
                "dataSource": "borrower report",
                "evidenceNotes": "",
                "estimation": {},
            },
        ],
    )
    payload.update(overrides)
    return payload


def _integrated(**overrides):
    payload = _separate(
        eligibility={
            "proceedsAllocatedToSpecificAssets": "yes",
            "isSecuritized": "no",
            "structureHasControl": "no",
            "debtBasedWithOneFullyAllocatedAsset": "no",
            "assetsOnIssuerBalanceSheet": "yes",
        },
        structureKind="labeled-bond",
        outstandingInvestment=10_000_000,
        totalStructureDebt=100_000_000,
        totalStructureEquity=0,
        allocatedProceeds=80_000_000,
        unallocatedProceeds=20_000_000,
        unallocatedUsesAssetLevelEstimate="no",
        issuerCompanyType="listed",
        issuerEvic=200_000_000,
        issuerScope1Emissions=100,
        issuerVerificationStatus="verified",
        assets=[
            {
                "underlyingAssetId": ASSET_A,
                "name": "Green building",
                "assetClass": "commercial-real-estate",
                "allocatedOutstanding": 80_000_000,
                "totalAssetValue": 100_000_000,
                "hasReportedEmissions": "yes",
                "verificationStatus": "verified",
                "verifierName": "Verifier Co",
                "scope1Emissions": 50,
                "scope2Emissions": None,
                "scope3Emissions": None,
                "dataSource": "allocation report",
                "evidenceNotes": "",
                "estimation": {},
            }
        ],
    )
    payload.update(overrides)
    return payload


def test_01_separate_two_underlying_assets_independent_pcaf_math():
    """
    AF_investor = 50 / 100 = 0.5
    Mortgage AF = 6/10 = 0.6 → structure 72 → investor 36 (S1 30, S2 6)
    Loan AF = 4/8 = 0.5 → structure 20 → investor 10 (S1 10)
    Total = 46 tCO2e. Unallocated cash is not added.
    """
    result = calculate_uop_draft(_separate())
    assert result["status"] == "complete"
    assert result["formula_id"] == "uop-separate-lookthrough"
    assert result["investor_attribution"]["attribution_factor"] == pytest.approx(0.5)
    assert result["financed_emissions"] == pytest.approx(46.0)
    assert result["unallocated_financed_emissions"] == pytest.approx(0.0)
    assert result["data_quality_score"] == pytest.approx(1.4)
    by_id = {row["underlying_asset_id"]: row for row in result["assets"]}
    assert by_id[ASSET_A]["asset_class"] == "mortgage"
    assert by_id[ASSET_A]["investor_financed_emissions"] == pytest.approx(36.0)
    assert by_id[ASSET_B]["asset_class"] == "business-loan"
    assert by_id[ASSET_B]["investor_financed_emissions"] == pytest.approx(10.0)
    breakdown = result["scope_breakdown"]
    assert breakdown["financed_scope1_tco2e"] == pytest.approx(40.0)
    assert breakdown["financed_scope2_tco2e"] == pytest.approx(6.0)
    assert breakdown["financed_scope3_tco2e"] is None
    included = (breakdown["financed_scope1_tco2e"] or 0) + (breakdown["financed_scope2_tco2e"] or 0)
    unallocated = breakdown["financed_unallocated_tco2e"] or 0
    assert included + unallocated == pytest.approx(result["financed_emissions"])
    assert result["is_reportable"] is False
    assert result["include_in_portfolio"] is False


def test_02_two_investments_same_fund_different_outstanding():
    first = calculate_uop_draft(_separate(outstandingInvestment=50_000_000))
    second = calculate_uop_draft(_separate(outstandingInvestment=20_000_000, financingInstanceId=INSTANCE_B))
    assert first["financed_emissions"] == pytest.approx(46.0)
    assert second["investor_attribution"]["attribution_factor"] == pytest.approx(0.2)
    assert second["financed_emissions"] == pytest.approx(18.4)
    assert first["financed_emissions"] != second["financed_emissions"]


def test_03_integrated_allocated_plus_unallocated_issuer_level():
    """
    AF_investor = 10/100 = 0.1
    CRE AF = 80/100 = 0.8 → allocated investor FE = 0.1 * 40 = 4
    Unallocated investor outstanding = 10 * (20/100) = 2
    Issuer AF = 2/200 = 0.01 → unallocated FE = 1
    Total = 5
    """
    result = calculate_uop_draft(_integrated())
    assert result["status"] == "complete"
    assert result["formula_id"] == "uop-integrated-lookthrough"
    assert result["allocated_financed_emissions"] == pytest.approx(4.0)
    assert result["unallocated_financed_emissions"] == pytest.approx(1.0)
    assert result["financed_emissions"] == pytest.approx(5.0)
    assert result["data_quality_score"] == pytest.approx(1.0)


def test_04_issuer_reported_structure_emissions_not_corporate_inventory():
    draft = _separate(
        emissionsPath="issuer_reported",
        issuerReportedFinancedEmissions=200,
        issuerReportYear="2026",
        issuerReportSource="Green Bond allocation and impact report",
        issuerReportVerification="verified",
        outstandingInvestment=10_000_000,
        assets=[],
    )
    result = calculate_uop_draft(draft)
    assert result["status"] == "complete"
    assert result["formula_id"] == "uop-issuer-reported"
    assert result["financed_emissions"] == pytest.approx(20.0)
    assert result["data_quality_score"] == pytest.approx(1.0)
    assert "corporate" in " ".join(result["notes"]).lower()
    missing = calculate_uop_draft(
        _separate(
            emissionsPath="issuer_reported",
            issuerReportedFinancedEmissions=None,
            issuerReportYear="2026",
            issuerReportSource="GHG inventory",
            assets=[],
        )
    )
    assert missing["status"] == "incomplete"
    assert missing["code"] == "missing_issuer_reported_emissions"


def test_05_permitted_economic_estimation_requires_published_factor():
    draft = _separate(
        outstandingInvestment=10_000_000,
        totalStructureDebt=50_000_000,
        assets=[
            {
                "underlyingAssetId": ASSET_B,
                "name": "Sector loan",
                "assetClass": "business-loan",
                "allocatedOutstanding": 50_000_000,
                "totalAssetValue": 50_000_000,
                "hasReportedEmissions": "no",
                "dataSource": "EEIO table",
                "estimation": {
                    "method": "economic",
                    "sectorName": "electricity",
                    "sectorAllocationPercent": 100,
                    "emissionFactor": 0.000002,
                    "factorUnit": "tCO2e/currency",
                    "factorSource": "published EEIO table X",
                },
            }
        ],
    )
    result = calculate_uop_draft(draft)
    assert result["status"] == "complete"
    assert result["financed_emissions"] == pytest.approx(20.0)
    assert result["data_quality_score"] == pytest.approx(5.0)


def test_06_activity_based_underlying_estimation():
    draft = _separate(
        outstandingInvestment=25_000_000,
        totalStructureDebt=100_000_000,
        assets=[
            {
                "underlyingAssetId": "asset-project",
                "name": "Solar project",
                "assetClass": "project-finance",
                "allocatedOutstanding": 20_000_000,
                "totalAssetValue": 40_000_000,
                "hasReportedEmissions": "no",
                "dataSource": "generation statement",
                "estimation": {
                    "method": "physical",
                    "physicalActivityAmount": 1000,
                    "physicalActivityUnit": "MWh",
                    "emissionFactor": 0.4,
                    "factorUnit": "tCO2e/MWh",
                    "factorSource": "published grid factor",
                },
            }
        ],
    )
    result = calculate_uop_draft(draft)
    assert result["status"] == "complete"
    assert result["assets"][0]["reused_formula_id"] == "2a-project-finance"
    assert result["assets"][0]["data_quality_score"] == pytest.approx(2.0)
    assert result["assets"][0]["option_code"] == "2a"
    assert result["financed_emissions"] == pytest.approx(50.0)


def test_07_weighted_data_quality_decimal():
    draft = _separate(
        assets=[
            {
                "underlyingAssetId": ASSET_A,
                "name": "A",
                "assetClass": "mortgage",
                "allocatedOutstanding": 3,
                "totalAssetValue": 10,
                "hasReportedEmissions": "yes",
                "verificationStatus": "verified",
                "scope1Emissions": 10,
                "dataSource": "report",
                "estimation": {},
            },
            {
                "underlyingAssetId": ASSET_B,
                "name": "B",
                "assetClass": "business-loan",
                "allocatedOutstanding": 1,
                "totalAssetValue": 10,
                "hasReportedEmissions": "no",
                "dataSource": "EEIO",
                "estimation": {
                    "method": "economic",
                    "sectorAllocationPercent": 100,
                    "emissionFactor": 0.1,
                    "factorSource": "published EEIO",
                    "factorUnit": "tCO2e/currency",
                },
            },
        ]
    )
    result = calculate_uop_draft(draft)
    assert result["data_quality_score"] == pytest.approx(2.0)


def test_08_missing_emissions_or_factors_are_incomplete_not_zero():
    missing_scope = calculate_uop_draft(
        _separate(
            assets=[
                {
                    "underlyingAssetId": ASSET_A,
                    "name": "Blank scopes",
                    "assetClass": "mortgage",
                    "allocatedOutstanding": 1,
                    "totalAssetValue": 2,
                    "hasReportedEmissions": "yes",
                    "verificationStatus": "verified",
                    "scope1Emissions": None,
                    "scope2Emissions": None,
                    "scope3Emissions": None,
                    "dataSource": "report",
                    "estimation": {},
                }
            ]
        )
    )
    assert missing_scope["status"] == "incomplete"
    assert missing_scope["financed_emissions"] is None
    missing_factor = calculate_uop_draft(
        _separate(
            assets=[
                {
                    "underlyingAssetId": ASSET_B,
                    "name": "No factor",
                    "assetClass": "business-loan",
                    "allocatedOutstanding": 1,
                    "totalAssetValue": 2,
                    "hasReportedEmissions": "no",
                    "dataSource": "note",
                    "estimation": {
                        "method": "economic",
                        "sectorAllocationPercent": 100,
                        "factorSource": "EEIO",
                    },
                }
            ]
        )
    )
    assert missing_factor["status"] == "incomplete"
    assert missing_factor["code"] == "missing_economic_factor"
    assert missing_factor["financed_emissions"] is None


def test_09_valid_zero_when_separate_has_no_allocation_yet():
    result = calculate_uop_draft(_separate(allocationStatus="none_yet", assets=[]))
    assert result["status"] == "complete"
    assert result["financed_emissions"] == 0.0
    assert result["data_quality_score"] is None
    assert result["formula_id"] == "uop-separate-zero-unallocated"


def test_10_negative_equity_and_invalid_denominator():
    debt_attr = investor_attribution(
        outstanding=20,
        investment_type="debt",
        total_debt=100,
        total_equity=-10,
    )
    assert debt_attr["total_structure_equity_used"] == 0.0
    assert debt_attr["attribution_factor"] == pytest.approx(0.2)
    equity_attr = investor_attribution(
        outstanding=5,
        investment_type="equity",
        total_debt=100,
        total_equity=-10,
    )
    assert equity_attr["attribution_factor"] == 0.0
    fallback = investor_attribution(
        outstanding=10,
        investment_type="debt",
        total_debt=0,
        total_equity=-4,
        total_assets_fallback=50,
    )
    assert fallback["denominator_kind"] == "total_assets_fallback"
    assert fallback["attribution_factor"] == pytest.approx(0.2)
    with pytest.raises(Exception):
        investor_attribution(
            outstanding=10,
            investment_type="debt",
            total_debt=0,
            total_equity=-4,
        )


def test_11_and_12_different_classes_and_multiple_same_class():
    result = calculate_uop_draft(
        _separate(
            assets=[
                {
                    "underlyingAssetId": ASSET_A,
                    "name": "Home 1",
                    "assetClass": "mortgage",
                    "allocatedOutstanding": 2_000_000,
                    "totalAssetValue": 4_000_000,
                    "hasReportedEmissions": "yes",
                    "verificationStatus": "verified",
                    "scope1Emissions": 8,
                    "dataSource": "report",
                    "estimation": {},
                },
                {
                    "underlyingAssetId": ASSET_C,
                    "name": "Home 2",
                    "assetClass": "mortgage",
                    "allocatedOutstanding": 2_000_000,
                    "totalAssetValue": 8_000_000,
                    "hasReportedEmissions": "yes",
                    "verificationStatus": "verified",
                    "scope1Emissions": 8,
                    "dataSource": "report",
                    "estimation": {},
                },
                {
                    "underlyingAssetId": "asset-vehicle",
                    "name": "Fleet loan",
                    "assetClass": "motor-vehicle-loan",
                    "allocatedOutstanding": 1_000_000,
                    "totalAssetValue": 2_000_000,
                    "hasReportedEmissions": "yes",
                    "verificationStatus": "unverified",
                    "scope1Emissions": 4,
                    "dataSource": "report",
                    "estimation": {},
                },
            ]
        )
    )
    by_id = {row["underlying_asset_id"]: row for row in result["assets"]}
    assert by_id[ASSET_A]["denominator_kind"] == "property_value_at_origination"
    assert by_id[ASSET_C]["denominator_kind"] == "property_value_at_origination"
    assert by_id["asset-vehicle"]["denominator_kind"] == "total_value_at_origination"
    assert by_id[ASSET_A]["investor_financed_emissions"] == pytest.approx(2.0)
    assert by_id[ASSET_C]["investor_financed_emissions"] == pytest.approx(1.0)
    assert by_id["asset-vehicle"]["investor_financed_emissions"] == pytest.approx(1.0)
    assert result["financed_emissions"] == pytest.approx(4.0)


def test_13_unknown_allocation_estimates_only_the_residual():
    """
    AF = 0.5. Known mortgage look-through = 0.5 * (10/10) * 10 = 5.
    Residual ratio = 1 - 10/100 = 0.9. Outstanding relevant = 45m.
    Score 5: 45m * 0.000001 = 45. Total = 50.
    """
    result = calculate_uop_draft(
        _separate(
            allocationStatus="unknown",
            expectedAllocationEvidence="PCAF unknown allocation assumed 100%",
            assets=[
                {
                    "underlyingAssetId": ASSET_B,
                    "name": "Known pool",
                    "assetClass": "business-loan",
                    "allocatedOutstanding": 10_000_000,
                    "totalAssetValue": 10_000_000,
                    "hasReportedEmissions": "yes",
                    "verificationStatus": "verified",
                    "scope1Emissions": 10,
                    "dataSource": "report",
                    "estimation": {
                        "method": "economic",
                        "sectorAllocationPercent": 100,
                        "emissionFactor": 0.000001,
                        "factorUnit": "tCO2e/currency",
                        "factorSource": "published EEIO",
                    },
                }
            ],
        )
    )
    assert result["status"] == "complete"
    assert result["allocated_financed_emissions"] == pytest.approx(5.0)
    assert result["unallocated_financed_emissions"] == pytest.approx(45.0)
    assert result["financed_emissions"] == pytest.approx(50.0)


def test_14_scope_breakdown_reconciles_and_does_not_zero_missing():
    result = calculate_uop_draft(_separate())
    breakdown = result["scope_breakdown"]
    present = [
        value
        for value in (
            breakdown["financed_scope1_tco2e"],
            breakdown["financed_scope2_tco2e"],
            breakdown["financed_scope3_tco2e"],
            breakdown["financed_unallocated_tco2e"],
        )
        if value is not None
    ]
    assert sum(present) == pytest.approx(result["financed_emissions"])
    assert breakdown["financed_scope3_tco2e"] is None
    assert "scope3" in breakdown["missing_scopes"]


def test_15_16_17_18_http_reload_conflict_auth_and_no_double_count():
    session = UopMemorySession()
    client = _client(session)
    created = _put(client, INSTANCE_A, draft=_separate())
    assert created.status_code in (200, 201)
    investment_id = created.json()["investment"]["id"]
    structure_id = created.json()["structure"]["id"]
    structure_ts = created.json()["structure"]["updated_at"]

    preview = client.post(
        "/api/v1/uop/calculate",
        json={"draft": _separate(), "persist": False},
    )
    assert preview.status_code == 200
    assert preview.json()["financed_emissions"] == pytest.approx(46.0)
    assert preview.json()["persisted"] is False
    assert preview.json()["is_reportable"] is False

    persisted = client.post(
        "/api/v1/uop/calculate",
        json={
            "financing_instance_id": INSTANCE_A,
            "counterparty_id": str(COUNTERPARTY_ID),
            "persist": True,
            "draft": _separate(),
        },
    )
    assert persisted.status_code == 200
    assert persisted.json()["persisted"] is True
    assert persisted.json()["is_reportable"] is False
    reloaded = client.get(f"/api/v1/uop/drafts/by-instance/{INSTANCE_A}")
    assert reloaded.status_code == 200
    last = reloaded.json()["draft"]["lastCalculation"]
    assert last["financed_emissions"] == pytest.approx(46.0)
    again = client.post(
        "/api/v1/uop/calculate",
        json={"financing_instance_id": INSTANCE_A, "persist": True, "draft": _separate()},
    )
    assert again.json()["financed_emissions"] == pytest.approx(46.0)

    sibling = _put(
        client,
        INSTANCE_B,
        instance_key="use-of-proceeds#2",
        structure_id=structure_id,
        draft=_separate(financingInstanceId=INSTANCE_B, outstandingInvestment=20_000_000),
    )
    assert sibling.status_code in (200, 201)
    conflict = client.post(
        "/api/v1/uop/calculate",
        json={
            "financing_instance_id": INSTANCE_B,
            "persist": True,
            "draft": _separate(financingInstanceId=INSTANCE_B, outstandingInvestment=20_000_000),
        },
    )
    assert conflict.status_code == 409

    other = _client(session, OTHER_ORG_ID)
    cross = other.post(
        "/api/v1/uop/calculate",
        json={"financing_instance_id": INSTANCE_A, "persist": False, "draft": _separate()},
    )
    assert cross.status_code == 200
    stored_cross = other.get(f"/api/v1/uop/drafts/by-instance/{INSTANCE_A}")
    assert stored_cross.status_code == 404

    for calc in session.tables[UopAssetCalculation]:
        assert calc.is_reportable is False
        assert calc.include_in_portfolio is False
    for inv in session.tables[UopInvestment]:
        assert inv.is_reportable is False
        assert inv.include_in_portfolio is False
        if inv.financing_instance_id == INSTANCE_A:
            assert str(inv.id) == investment_id
    rejected = client.post(
        "/api/v1/financed-emissions",
        json={"formula_id": "uop-separate-lookthrough", "inputs": {"financing_instance_id": INSTANCE_A}},
    )
    assert rejected.status_code == 400
    assert structure_ts  # lock token exists for shared writes


def test_19_existing_asset_class_regression_untouched():
    engine = CalculationEngine()
    ids = {formula.id for formula in engine.formulas}
    assert "uop-separate-lookthrough" not in ids
    assert "uop-issuer-reported" not in ids
    sample = json.loads(FIXTURES.read_text(encoding="utf-8"))["sample"]
    result = engine.calculate("1a-listed-equity", sample, CompanyType.LISTED)
    assert result.attribution_factor == pytest.approx(1 / 3)
    assert result.financed_emissions == pytest.approx(50000 / 3)
    assert result.data_quality_score == 1


def test_20_reportable_save_remains_blocked_on_uop_path():
    session = UopMemorySession()
    client = _client(session)
    created = _put(client, INSTANCE_A, draft=_separate())
    calc = client.post(
        "/api/v1/uop/calculate",
        json={"financing_instance_id": INSTANCE_A, "persist": True, "draft": _separate()},
    )
    assert calc.json()["is_reportable"] is False
    assert calc.json()["include_in_portfolio"] is False
    body = client.get(f"/api/v1/uop/drafts/{created.json()['investment']['id']}")
    for row in body.json()["calculations"]:
        assert row["is_reportable"] is False
        assert row["include_in_portfolio"] is False
    blocked = client.post(
        "/api/v1/financed-emissions/calculate",
        json={"formula_id": "uop-integrated-lookthrough", "company_type": "listed", "inputs": {}},
    )
    assert blocked.status_code == 400


def test_21_independent_listed_equity_matches_uop_lookthrough():
    """Same 1a-listed-equity inputs independently and inside a UoP structure."""
    inputs = {
        "outstanding_amount": 6_000_000,
        "total_assets": 10_000_000,
        "evic": 10_000_000,
        "verified_emissions": 120,
        "scope1_emissions": 100,
        "scope2_emissions": 20,
    }
    independent = CalculationEngine().calculate("1a-listed-equity", inputs, CompanyType.LISTED)
    result = calculate_uop_draft(
        _separate(
            assets=[
                {
                    "underlyingAssetId": "listed-a",
                    "name": "Listed holding",
                    "assetClass": "listed-equity",
                    "allocatedOutstanding": 6_000_000,
                    "totalAssetValue": 10_000_000,
                    "hasReportedEmissions": "yes",
                    "verificationStatus": "verified",
                    "verifierName": "Verifier Co",
                    "scope1Emissions": 100,
                    "scope2Emissions": 20,
                    "scope3Emissions": None,
                    "dataSource": "report",
                    "estimation": {},
                }
            ]
        )
    )
    assert result["status"] == "complete"
    assert result["assets"][0]["reused_formula_id"] == "1a-listed-equity"
    assert result["assets"][0]["structure_financed_emissions"] == pytest.approx(
        independent.financed_emissions
    )
    assert result["assets"][0]["asset_attribution_factor"] == pytest.approx(
        independent.attribution_factor
    )
    assert result["financed_emissions"] == pytest.approx(
        result["investor_attribution"]["attribution_factor"] * independent.financed_emissions
    )
    assert result["assets"][0]["data_quality_score"] == independent.data_quality_score


def test_22_independent_project_2a_matches_uop_lookthrough():
    inputs = {
        "outstanding_amount": 20_000_000,
        "total_project_equity_plus_debt": 40_000_000,
        "energy_consumption": 1000,
        "emission_factor": 0.4,
    }
    independent = CalculationEngine().calculate(
        "2a-project-finance", inputs, CompanyType.PRIVATE
    )
    result = calculate_uop_draft(
        _separate(
            outstandingInvestment=25_000_000,
            totalStructureDebt=100_000_000,
            assets=[
                {
                    "underlyingAssetId": "asset-project",
                    "name": "Solar project",
                    "assetClass": "project-finance",
                    "allocatedOutstanding": 20_000_000,
                    "totalAssetValue": 40_000_000,
                    "hasReportedEmissions": "no",
                    "dataSource": "generation statement",
                    "estimation": {
                        "method": "physical",
                        "physicalActivityAmount": 1000,
                        "physicalActivityUnit": "MWh",
                        "emissionFactor": 0.4,
                        "factorUnit": "tCO2e/MWh",
                        "factorSource": "published grid factor",
                    },
                }
            ],
        )
    )
    assert result["assets"][0]["reused_formula_id"] == "2a-project-finance"
    assert result["assets"][0]["structure_financed_emissions"] == pytest.approx(
        independent.financed_emissions
    )
    assert result["financed_emissions"] == pytest.approx(
        result["investor_attribution"]["attribution_factor"] * independent.financed_emissions
    )
    assert result["assets"][0]["data_quality_score"] == 2


def test_23_independent_mortgage_energy_is_option_1a_not_score_3():
    inputs = {
        "outstanding_amount": 5_000_000,
        "property_value_at_origination": 10_000_000,
        "energy_consumption": 1000,
        "emission_factor": 0.01,
    }
    independent = CalculationEngine().calculate("1a-mortgage", inputs, CompanyType.PRIVATE)
    result = calculate_uop_draft(
        _separate(
            outstandingInvestment=10_000_000,
            totalStructureDebt=20_000_000,
            assets=[
                {
                    "underlyingAssetId": ASSET_A,
                    "name": "Home energy",
                    "assetClass": "mortgage",
                    "allocatedOutstanding": 5_000_000,
                    "totalAssetValue": 10_000_000,
                    "hasReportedEmissions": "no",
                    "verificationStatus": "verified",
                    "dataSource": "utility bill",
                    "estimation": {
                        "method": "physical",
                        "physicalActivityAmount": 1000,
                        "physicalActivityUnit": "kWh",
                        "emissionFactor": 0.01,
                        "factorUnit": "tCO2e/kWh",
                        "factorSource": "supplier-specific factor",
                    },
                }
            ],
        )
    )
    assert result["status"] == "complete"
    assert result["assets"][0]["reused_formula_id"] == "1a-mortgage"
    assert result["assets"][0]["data_quality_score"] == pytest.approx(1.0)
    assert result["assets"][0]["structure_financed_emissions"] == pytest.approx(
        independent.financed_emissions
    )
    assert result["financed_emissions"] == pytest.approx(
        0.5 * independent.financed_emissions
    )


def test_24_score4_floor_area_and_building_economic_stay_unavailable():
    floor = calculate_uop_draft(
        _separate(
            assets=[
                {
                    "underlyingAssetId": ASSET_A,
                    "name": "Floor-area building",
                    "assetClass": "commercial-real-estate",
                    "allocatedOutstanding": 1,
                    "totalAssetValue": 2,
                    "hasReportedEmissions": "no",
                    "dataSource": "note",
                    "estimation": {
                        "method": "physical",
                        "physicalActivityAmount": 100,
                        "physicalActivityUnit": "m2",
                        "emissionFactor": 0.05,
                        "factorUnit": "tCO2e/m2",
                        "factorSource": "published table",
                    },
                }
            ]
        )
    )
    assert floor["status"] == "unsupported"
    assert floor["code"] in ("unsupported_underlying_asset", "unsupported_physical_option")
    economic_building = calculate_uop_draft(
        _separate(
            assets=[
                {
                    "underlyingAssetId": ASSET_A,
                    "name": "Mortgage EEIO",
                    "assetClass": "mortgage",
                    "allocatedOutstanding": 1,
                    "totalAssetValue": 2,
                    "hasReportedEmissions": "no",
                    "dataSource": "EEIO",
                    "estimation": {
                        "method": "economic",
                        "sectorAllocationPercent": 100,
                        "emissionFactor": 0.1,
                        "factorUnit": "tCO2e/currency",
                        "factorSource": "published EEIO",
                    },
                }
            ]
        )
    )
    assert economic_building["status"] == "unsupported"
    unknown_unit = calculate_uop_draft(
        _separate(
            assets=[
                {
                    "underlyingAssetId": ASSET_B,
                    "name": "Unmapped activity",
                    "assetClass": "business-loan",
                    "allocatedOutstanding": 1,
                    "totalAssetValue": 2,
                    "hasReportedEmissions": "no",
                    "dataSource": "note",
                    "estimation": {
                        "method": "physical",
                        "physicalActivityAmount": 10,
                        "physicalActivityUnit": "widget",
                        "emissionFactor": 1,
                        "factorUnit": "tCO2e/widget",
                        "factorSource": "published",
                    },
                }
            ]
        )
    )
    assert unknown_unit["status"] == "unsupported"
    assert unknown_unit["assets"][0].get("data_quality_score") is None


def test_25_footnote_168_issuer_level_without_assets():
    """Issuer-level on full outstanding: 10m / 200m EVIC × 100 t = 5 tCO2e."""
    result = calculate_uop_draft(
        _integrated(
            emissionsPath="estimation",
            issuerLevelReason="practically_not_feasible",
            assets=[],
            unallocatedProceeds=20_000_000,
        )
    )
    assert result["status"] == "complete"
    assert result["formula_id"] == "uop-integrated-issuer-level"
    assert result["financed_emissions"] == pytest.approx(5.0)
    assert result["data_quality_score"] == pytest.approx(1.0)
    assert result["is_reportable"] is False


def test_26_valid_zero_reported_emissions_are_not_missing():
    result = calculate_uop_draft(
        _separate(
            assets=[
                {
                    "underlyingAssetId": ASSET_B,
                    "name": "Zero loan",
                    "assetClass": "business-loan",
                    "allocatedOutstanding": 4_000_000,
                    "totalAssetValue": 8_000_000,
                    "hasReportedEmissions": "yes",
                    "verificationStatus": "verified",
                    "scope1Emissions": 0,
                    "scope2Emissions": 0,
                    "scope3Emissions": None,
                    "dataSource": "report",
                    "estimation": {},
                }
            ]
        )
    )
    assert result["status"] == "complete"
    assert result["financed_emissions"] == pytest.approx(0.0)
    assert result["scope_breakdown"]["financed_scope1_tco2e"] == pytest.approx(0.0)
    assert result["scope_breakdown"]["financed_scope3_tco2e"] is None
    assert "scope3" in result["scope_breakdown"]["missing_scopes"]


def test_27_production_activity_is_option_2b_score_3_not_score_4():
    """Listed/unlisted/project production × EF is option 2b (score 3). Score 4 is option 3a."""
    inputs = {
        "outstanding_amount": 4_000_000,
        "total_assets": 8_000_000,
        "total_equity_plus_debt": 8_000_000,
        "production": 100,
        "production_emission_factor": 2,
    }
    independent = CalculationEngine().calculate(
        "2b-unlisted-equity", inputs, CompanyType.PRIVATE
    )
    result = calculate_uop_draft(
        _separate(
            outstandingInvestment=10_000_000,
            totalStructureDebt=20_000_000,
            assets=[
                {
                    "underlyingAssetId": ASSET_B,
                    "name": "Cement production",
                    "assetClass": "business-loan",
                    "allocatedOutstanding": 4_000_000,
                    "totalAssetValue": 8_000_000,
                    "hasReportedEmissions": "no",
                    "dataSource": "production report",
                    "estimation": {
                        "method": "physical",
                        "physicalActivityAmount": 100,
                        "physicalActivityUnit": "tonne",
                        "emissionFactor": 2,
                        "factorUnit": "tCO2e/tonne",
                        "factorSource": "published production factor",
                    },
                }
            ],
        )
    )
    assert result["status"] == "complete"
    assert result["assets"][0]["reused_formula_id"] == "2b-unlisted-equity"
    assert result["assets"][0]["data_quality_score"] == pytest.approx(3.0)
    assert result["assets"][0]["option_code"] == "2b"
    assert result["assets"][0]["structure_financed_emissions"] == pytest.approx(
        independent.financed_emissions
    )
    assert independent.financed_emissions == pytest.approx(100.0)
    assert result["financed_emissions"] == pytest.approx(50.0)


def _factor_meta(**extra):
    payload = {
        "factorSource": "published table",
        "factorGeography": "PK",
        "factorYear": "2024",
        "factorUnit": extra.pop("factorUnit", "tCO2e/unit"),
        "emissionFactor": extra.pop("emissionFactor", 0.4),
    }
    payload.update(extra)
    return payload


def test_28_option_3a_revenue_matches_independent_engine():
    inputs = {
        "outstanding_amount": 1_000_000,
        "evic": 3_000_000,
        "company_revenue": 8_000_000,
        "sector_intensity": 0.5,
        "sector_intensity_unit": "kgCO2e/PKR",
    }
    independent = CalculationEngine().calculate("3a-listed-equity", inputs, CompanyType.LISTED)
    result = calculate_uop_draft(
        _separate(
            outstandingInvestment=10_000_000,
            totalStructureDebt=20_000_000,
            assets=[
                {
                    "underlyingAssetId": "listed-3a",
                    "name": "Listed 3a",
                    "assetClass": "listed-equity",
                    "allocatedOutstanding": 1_000_000,
                    "totalAssetValue": 3_000_000,
                    "hasReportedEmissions": "no",
                    "dataSource": "financials",
                    "estimation": _factor_meta(
                        pcafOption="3a",
                        method="economic",
                        companyRevenue=8_000_000,
                        emissionFactor=0.5,
                        factorUnit="kgCO2e/PKR",
                        factorSource="published sector intensity",
                    ),
                }
            ],
        )
    )
    assert result["status"] == "complete"
    assert result["assets"][0]["reused_formula_id"] == "3a-listed-equity"
    assert result["assets"][0]["data_quality_score"] == 4
    assert result["assets"][0]["structure_financed_emissions"] == pytest.approx(
        independent.financed_emissions
    )
    assert result["financed_emissions"] == pytest.approx(
        0.5 * independent.financed_emissions
    )


def test_29_cre_label_and_mortgage_buildings_match_independent_engine():
    cre_inputs = {
        "outstanding_amount": 5_000_000,
        "property_value_at_origination": 10_000_000,
        "estimated_energy_consumption_from_labels": 20,
        "floor_area": 100,
        "average_emission_factor": 0.001,
    }
    mortgage_inputs = {
        "outstanding_amount": 2_000_000,
        "property_value_at_origination": 8_000_000,
        "estimated_energy_consumption_from_statistics": 1000,
        "number_of_buildings": 2,
        "average_emission_factor": 0.001,
    }
    cre_independent = CalculationEngine().calculate(
        "2a-commercial-real-estate", cre_inputs, CompanyType.PRIVATE
    )
    mortgage_independent = CalculationEngine().calculate(
        "3-mortgage", mortgage_inputs, CompanyType.PRIVATE
    )
    result = calculate_uop_draft(
        _separate(
            outstandingInvestment=10_000_000,
            totalStructureDebt=20_000_000,
            assets=[
                {
                    "underlyingAssetId": "cre-labels",
                    "name": "Office",
                    "assetClass": "commercial-real-estate",
                    "allocatedOutstanding": 5_000_000,
                    "totalAssetValue": 10_000_000,
                    "hasReportedEmissions": "no",
                    "dataSource": "EPC",
                    "estimation": _factor_meta(
                        pcafOption="2a",
                        method="physical",
                        labelEnergyIntensity=20,
                        floorArea=100,
                        emissionFactor=0.001,
                        factorUnit="tCO2e/kWh",
                    ),
                },
                {
                    "underlyingAssetId": "home-stats",
                    "name": "Homes",
                    "assetClass": "mortgage",
                    "allocatedOutstanding": 2_000_000,
                    "totalAssetValue": 8_000_000,
                    "hasReportedEmissions": "no",
                    "dataSource": "statistics",
                    "estimation": _factor_meta(
                        pcafOption="3",
                        method="physical",
                        statsEnergyIntensity=1000,
                        numberOfBuildings=2,
                        emissionFactor=0.001,
                        factorUnit="tCO2e/kWh",
                    ),
                },
            ],
        )
    )
    by_id = {row["underlying_asset_id"]: row for row in result["assets"]}
    assert by_id["cre-labels"]["reused_formula_id"] == "2a-commercial-real-estate"
    assert by_id["cre-labels"]["data_quality_score"] == 3
    assert by_id["cre-labels"]["structure_financed_emissions"] == pytest.approx(
        cre_independent.financed_emissions
    )
    assert by_id["home-stats"]["reused_formula_id"] == "3-mortgage"
    assert by_id["home-stats"]["data_quality_score"] == 5
    assert by_id["home-stats"]["structure_financed_emissions"] == pytest.approx(
        mortgage_independent.financed_emissions
    )
    assert result["financed_emissions"] == pytest.approx(
        0.5 * (cre_independent.financed_emissions + mortgage_independent.financed_emissions)
    )
    assert result["is_reportable"] is False


def test_30_motor_distance_option_and_3c_atr_match_independent_engine():
    motor_inputs = {
        "outstanding_amount": 1_000_000,
        "total_value_at_origination": 2_000_000,
        "distance_traveled": 1000,
        "efficiency": 0.05,
        "emission_factor": 0.002,
    }
    atr_inputs = {
        "outstanding_amount": 1_000_000,
        "asset_turnover_ratio": 0.8,
        "sector_intensity": 0.5,
        "sector_intensity_unit": "kgCO2e/PKR",
    }
    motor_independent = CalculationEngine().calculate(
        "2a-motor-vehicle", motor_inputs, CompanyType.PRIVATE
    )
    atr_independent = CalculationEngine().calculate(
        "3c-unlisted-equity", atr_inputs, CompanyType.PRIVATE
    )
    result = calculate_uop_draft(
        _separate(
            outstandingInvestment=10_000_000,
            totalStructureDebt=20_000_000,
            assets=[
                {
                    "underlyingAssetId": "fleet",
                    "name": "Fleet",
                    "assetClass": "motor-vehicle-loan",
                    "allocatedOutstanding": 1_000_000,
                    "totalAssetValue": 2_000_000,
                    "hasReportedEmissions": "no",
                    "dataSource": "local stats",
                    "estimation": _factor_meta(
                        pcafOption="2a",
                        method="physical",
                        distanceTraveled=1000,
                        efficiency=0.05,
                        emissionFactor=0.002,
                        factorUnit="tCO2e/L",
                    ),
                },
                {
                    "underlyingAssetId": "loan-3c",
                    "name": "ATR loan",
                    "assetClass": "business-loan",
                    "allocatedOutstanding": 1_000_000,
                    "totalAssetValue": 5_000_000,
                    "hasReportedEmissions": "no",
                    "dataSource": "sector table",
                    "estimation": _factor_meta(
                        pcafOption="3c",
                        method="economic",
                        assetTurnoverRatio=0.8,
                        emissionFactor=0.5,
                        factorUnit="kgCO2e/PKR",
                    ),
                },
            ],
        )
    )
    by_id = {row["underlying_asset_id"]: row for row in result["assets"]}
    assert by_id["fleet"]["reused_formula_id"] == "2a-motor-vehicle"
    assert by_id["fleet"]["data_quality_score"] == 2
    assert by_id["fleet"]["structure_financed_emissions"] == pytest.approx(
        motor_independent.financed_emissions
    )
    assert by_id["loan-3c"]["reused_formula_id"] == "3c-unlisted-equity"
    assert by_id["loan-3c"]["data_quality_score"] == 5
    assert by_id["loan-3c"]["structure_financed_emissions"] == pytest.approx(
        atr_independent.financed_emissions
    )
    assert result["financed_emissions"] == pytest.approx(
        0.5 * (motor_independent.financed_emissions + atr_independent.financed_emissions)
    )


def test_31_wrong_class_option_stays_unavailable():
    wrong = calculate_uop_draft(
        _separate(
            assets=[
                {
                    "underlyingAssetId": ASSET_A,
                    "name": "Mortgage 3a",
                    "assetClass": "mortgage",
                    "allocatedOutstanding": 1,
                    "totalAssetValue": 2,
                    "hasReportedEmissions": "no",
                    "dataSource": "note",
                    "estimation": _factor_meta(
                        pcafOption="3a",
                        method="economic",
                        companyRevenue=100,
                        emissionFactor=0.5,
                        factorUnit="kgCO2e/PKR",
                    ),
                }
            ]
        )
    )
    assert wrong["status"] == "unsupported"


def test_32_mortgage_statistical_floor_area_is_option_2b_score_4():
    inputs = {
        "outstanding_amount": 4_000_000,
        "property_value_at_origination": 8_000_000,
        "estimated_energy_consumption_from_statistics": 10,
        "floor_area": 200,
        "average_emission_factor": 0.0005,
    }
    independent = CalculationEngine().calculate("2b-mortgage", inputs, CompanyType.PRIVATE)
    result = calculate_uop_draft(
        _separate(
            outstandingInvestment=10_000_000,
            totalStructureDebt=20_000_000,
            assets=[
                {
                    "underlyingAssetId": ASSET_A,
                    "name": "Stats home",
                    "assetClass": "mortgage",
                    "allocatedOutstanding": 4_000_000,
                    "totalAssetValue": 8_000_000,
                    "hasReportedEmissions": "no",
                    "dataSource": "CBECS",
                    "estimation": _factor_meta(
                        pcafOption="2b",
                        method="physical",
                        statsEnergyIntensity=10,
                        floorArea=200,
                        emissionFactor=0.0005,
                        factorUnit="tCO2e/kWh",
                    ),
                }
            ],
        )
    )
    assert result["assets"][0]["reused_formula_id"] == "2b-mortgage"
    assert result["assets"][0]["data_quality_score"] == 4
    assert result["assets"][0]["structure_financed_emissions"] == pytest.approx(
        independent.financed_emissions
    )
    assert result["financed_emissions"] == pytest.approx(0.5 * independent.financed_emissions)


def test_unsupported_nested_uop_and_sovereign_are_not_guessed():
    nested = calculate_uop_draft(
        _separate(
            assets=[
                {
                    "underlyingAssetId": "child-uop",
                    "name": "Nested fund",
                    "assetClass": "use-of-proceeds",
                    "allocatedOutstanding": 1,
                    "totalAssetValue": 2,
                    "hasReportedEmissions": "yes",
                    "scope1Emissions": 1,
                    "dataSource": "report",
                    "estimation": {},
                }
            ]
        )
    )
    # Nested UoP is supported only with child look-through assets — not a collapsed guess.
    assert nested["status"] in ("incomplete", "unsupported")
    assert "child" in (nested.get("message") or "").lower() or nested["status"] == "incomplete"
    sovereign = calculate_uop_draft(
        _separate(
            assets=[
                {
                    "underlyingAssetId": "sov",
                    "name": "Sovereign",
                    "assetClass": "sovereign-debt",
                    "allocatedOutstanding": 1,
                    "totalAssetValue": 2,
                    "hasReportedEmissions": "yes",
                    "scope1Emissions": 1,
                    "dataSource": "report",
                    "estimation": {},
                }
            ]
        )
    )
    # Sovereign reuse needs a PCAF option + PPP GDP; no invented collapsed path.
    assert sovereign["status"] in ("incomplete", "unsupported")


def test_ineligible_financing_is_rejected():
    from fastapi_app.uop_calc import UopCalcError

    with pytest.raises(UopCalcError):
        calculate_uop_draft(
            _separate(
                eligibility={
                    "proceedsAllocatedToSpecificAssets": "no",
                    "isSecuritized": "",
                    "structureHasControl": "",
                }
            )
        )
