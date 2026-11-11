"""Phase 6C.1 SSP preview calculation — independent fixture algebra (not PCAF figure claims)."""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from fastapi_app.auth_models import User
from fastapi_app.auth_org import OrgContext
from fastapi_app.db import get_db
from fastapi_app.routers import ssp_calculate as ssp_calc_routes
from fastapi_app.routers.deps import require_org_context
from fastapi_app.ssp_calc import calculate_ssp_draft, compute_caf
from fastapi_app.ssp_drafts import is_ssp_formula_id


ORG_A = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
ORG_B = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
USER_A = uuid.UUID("11111111-1111-4111-8111-111111111111")


def _base_draft(**overrides):
    draft = {
        "eligibility": {
            "isStructuredProduct": "yes",
            "underlyingIdentifiable": "yes",
            "structureFamily": "true-sale",
            "collateralFamily": "residential-real-estate",
            "hasTranches": "yes",
            "hasPoolOfPools": "no",
            "poolsLinkedToSpecificTranches": "no",
        },
        "deal": {
            "dealName": "Fixture RMBS",
            "structureType": "rmbs",
            "reportingYear": "2024",
            "hasTranches": "yes",
            "hasPoolOfPools": "no",
        },
        "emissionsPath": "lookthrough",
        "collateral": [
            {
                "collateralId": "c1",
                "name": "House",
                "collateralType": "mortgage",
                "attributionDenominator": 100,
                "assetValueAtOrigination": 100,
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
                "name": "Bank",
                "trancheId": "t1",
                "bankOutstandingInvestment": 10,
            }
        ],
    }
    draft.update(overrides)
    return draft


def test_caf_cap_and_denom_selection():
    capped = compute_caf(
        collateral_type="mortgage",
        loan_coa=120,
        loan_ooa=None,
        avo=100,
        uav=None,
        equity_plus_debt=None,
        evic=None,
    )
    assert capped["status"] == "complete"
    assert capped["caf"] == 1.0
    assert capped["caf_capped"] is True
    assert capped["caf_basis"] == "coa_avo"

    biz = compute_caf(
        collateral_type="business-loan",
        loan_coa=20,
        loan_ooa=None,
        avo=None,
        uav=None,
        equity_plus_debt=100,
        evic=None,
    )
    assert biz["caf"] == 0.2
    assert biz["caf_basis"] == "coa_equity_debt"

    bond = compute_caf(
        collateral_type="corporate-bond",
        loan_coa=25,
        loan_ooa=None,
        avo=None,
        uav=None,
        equity_plus_debt=None,
        evic=200,
    )
    assert bond["caf"] == 0.125
    assert bond["caf_basis"] == "coa_evic"


def test_single_pool_lookthrough_pipeline():
    # Absolute = 10; CAF = 40/100 = 0.4; loan FE = 4; LAF=1; pool=4
    # TAF=1; IAF=10/40=0.25; holding FE = 1.0
    result = calculate_ssp_draft(_base_draft())
    assert result["status"] == "complete", result
    assert result["is_reportable"] is False
    assert result["include_in_portfolio"] is False
    assert result["loans"][0]["financed_emissions_tco2e"] == 4.0
    assert result["pools"][0]["financed_emissions_tco2e"] == 4.0
    assert result["tranches"][0]["taf"] == 1.0
    assert result["holdings"][0]["iaf"] == 0.25
    assert result["financed_emissions"] == 1.0
    assert abs(result["pool_financed_emissions"] - sum(t["financed_emissions_tco2e"] for t in result["tranches"])) < 1e-9


def test_multi_collateral_and_partial_laf():
    draft = _base_draft(
        collateral=[
            {
                "collateralId": "c1",
                "collateralType": "mortgage",
                "assetValueAtOrigination": 100,
                "emissionsPath": "reported",
                "scope1Emissions": 0,
                "scope2Emissions": 10,
                "dataQualityScore": 2,
            },
            {
                "collateralId": "c2",
                "collateralType": "mortgage",
                "assetValueAtOrigination": 50,
                "emissionsPath": "reported",
                "scope1Emissions": 0,
                "scope2Emissions": 5,
                "dataQualityScore": 3,
            },
        ],
        loans=[
            {
                "loanId": "l1",
                "collateralIds": ["c1", "c2"],
                "currentOutstandingAmount": 40,
            }
        ],
        pools=[
            {
                "poolId": "p1",
                "loanIds": ["l1"],
                "loanAllocations": [{"loanId": "l1", "amountInPool": 20}],  # LAF=0.5
            }
        ],
    )
    # CAF1=0.4 → 4; CAF2=min(1,40/50)=0.8 → 4; loan FE=8; pool=4
    result = calculate_ssp_draft(draft)
    assert result["status"] == "complete", result
    assert result["loans"][0]["financed_emissions_tco2e"] == 8.0
    assert result["pools"][0]["laf_rows"][0]["laf"] == 0.5
    assert result["pools"][0]["financed_emissions_tco2e"] == 4.0


def test_multiple_tranches_conservation_and_holdings():
    draft = _base_draft(
        tranches=[
            {"trancheId": "t1", "currentOutstandingAmount": 30, "linkedPoolIds": []},
            {"trancheId": "t2", "currentOutstandingAmount": 10, "linkedPoolIds": []},
        ],
        holdings=[
            {"holdingId": "h1", "trancheId": "t1", "bankOutstandingInvestment": 15},
            {"holdingId": "h2", "trancheId": "t2", "bankOutstandingInvestment": 5},
        ],
    )
    result = calculate_ssp_draft(draft)
    assert result["status"] == "complete", result
    pool_fe = result["pool_financed_emissions"]
    assert abs(sum(t["financed_emissions_tco2e"] for t in result["tranches"]) - pool_fe) < 1e-9
    # TAF t1=0.75, t2=0.25; pool FE=4 → tranche FE 3 and 1
    # IAF h1=0.5 → 1.5; h2=0.5 → 0.5
    by_h = {h["holding_id"]: h for h in result["holdings"]}
    assert by_h["h1"]["financed_emissions_tco2e"] == 1.5
    assert by_h["h2"]["financed_emissions_tco2e"] == 0.5


def test_untranched_and_reported_pool_exclusivity():
    look = calculate_ssp_draft(
        _base_draft(
            deal={
                "dealName": "U",
                "structureType": "untranched",
                "hasTranches": "no",
                "hasPoolOfPools": "no",
            },
            eligibility={
                "hasTranches": "no",
                "hasPoolOfPools": "no",
                "poolsLinkedToSpecificTranches": "no",
            },
            tranches=[],
            holdings=[{"holdingId": "h1", "trancheId": "", "bankOutstandingInvestment": 10}],
        )
    )
    assert look["status"] == "complete", look
    assert look["tranches"][0]["tranche_id"] == "__untranched__"

    reported = calculate_ssp_draft(
        _base_draft(
            emissionsPath="reported_pool",
            pools=[
                {
                    "poolId": "p1",
                    "loanIds": ["l1"],
                    "reportedEmissionsTotal": 8,
                    "reportedSource": "Trustee report",
                    "reportedEmissionsPeriod": "2024",
                    "loanAllocations": [{"loanId": "l1", "amountInPool": 40}],
                }
            ],
        )
    )
    assert reported["status"] == "complete", reported
    assert reported["pools"][0]["path"] == "reported_pool"
    assert reported["collateral"] == []
    # IAF 10/40 * TAF 1 * 8 = 2
    assert reported["financed_emissions"] == 2.0


def test_zero_denom_missing_coa_duplicate_and_pop_blocked():
    zero = calculate_ssp_draft(
        _base_draft(
            collateral=[
                {
                    "collateralId": "c1",
                    "collateralType": "mortgage",
                    "assetValueAtOrigination": 0,
                    "emissionsPath": "reported",
                    "scope2Emissions": 10,
                }
            ]
        )
    )
    assert zero["status"] == "error"
    assert zero["code"] == "zero_denominator"

    missing = calculate_ssp_draft(
        _base_draft(
            loans=[{"loanId": "l1", "collateralIds": ["c1"], "currentOutstandingAmount": None}],
            pools=[{"poolId": "p1", "loanIds": ["l1"], "loanAllocations": [{"loanId": "l1", "amountInPool": 10}]}],
        )
    )
    assert missing["status"] in ("incomplete", "error")

    pop = calculate_ssp_draft(_base_draft(deal={**_base_draft()["deal"], "hasPoolOfPools": "yes"}))
    assert pop["status"] == "unsupported"
    assert pop["code"] == "unsupported_pool_of_pools"

    multi = calculate_ssp_draft(
        _base_draft(
            pools=[
                {"poolId": "p1", "loanIds": ["l1"], "loanAllocations": [{"loanId": "l1", "amountInPool": 40}]},
                {"poolId": "p2", "loanIds": ["l1"], "loanAllocations": [{"loanId": "l1", "amountInPool": 40}]},
            ]
        )
    )
    assert multi["status"] == "unsupported"
    assert multi["code"] == "single_pool_required"


def test_multiple_loans_missing_ef_duplicate_and_advanced_blocks():
    multi_loan = calculate_ssp_draft(
        _base_draft(
            collateral=[
                {
                    "collateralId": "c1",
                    "collateralType": "mortgage",
                    "assetValueAtOrigination": 100,
                    "emissionsPath": "reported",
                    "scope2Emissions": 10,
                    "dataQualityScore": 2,
                },
                {
                    "collateralId": "c2",
                    "collateralType": "mortgage",
                    "assetValueAtOrigination": 200,
                    "emissionsPath": "reported",
                    "scope2Emissions": 20,
                    "dataQualityScore": 3,
                },
            ],
            loans=[
                {"loanId": "l1", "collateralIds": ["c1"], "currentOutstandingAmount": 40},
                {"loanId": "l2", "collateralIds": ["c2"], "currentOutstandingAmount": 50},
            ],
            pools=[
                {
                    "poolId": "p1",
                    "loanIds": ["l1", "l2"],
                    "loanAllocations": [
                        {"loanId": "l1", "amountInPool": 40},
                        {"loanId": "l2", "amountInPool": 50},
                    ],
                }
            ],
            tranches=[{"trancheId": "t1", "currentOutstandingAmount": 90, "linkedPoolIds": []}],
            holdings=[{"holdingId": "h1", "trancheId": "t1", "bankOutstandingInvestment": 45}],
        )
    )
    # l1 FE=4, l2 FE=5, pool=9; TAF=1; IAF=0.5 → holding FE=4.5
    assert multi_loan["status"] == "complete", multi_loan
    assert multi_loan["pools"][0]["financed_emissions_tco2e"] == 9.0
    assert multi_loan["financed_emissions"] == 4.5

    missing_ef = calculate_ssp_draft(
        _base_draft(
            collateral=[
                {
                    "collateralId": "c1",
                    "collateralType": "mortgage",
                    "assetValueAtOrigination": 100,
                    "classInputs": {
                        "formData": {"energyConsumption": 1000},
                        "methodSelection": {"calculationMethod": "2a"},
                    },
                }
            ]
        )
    )
    assert missing_ef["status"] == "incomplete"
    assert missing_ef["financed_emissions"] is None

    dup = calculate_ssp_draft(
        _base_draft(
            pools=[
                {
                    "poolId": "p1",
                    "loanIds": ["l1"],
                    "loanAllocations": [
                        {"loanId": "l1", "amountInPool": 20},
                        {"loanId": "l1", "amountInPool": 20},
                    ],
                }
            ]
        )
    )
    assert dup["status"] == "error"
    assert dup["code"] == "duplicate_relationship"

    master = calculate_ssp_draft(
        _base_draft(deal={**_base_draft()["deal"], "structureType": "master-trust"})
    )
    assert master["status"] == "unsupported"
    assert master["code"] == "unsupported_structure"

    hard = calculate_ssp_draft(
        _base_draft(
            collateral=[
                {
                    "collateralId": "c1",
                    "collateralType": "other-hard-asset",
                    "assetValueAtOrigination": 100,
                }
            ]
        )
    )
    assert hard["status"] == "unsupported"


def test_ssp_formula_id_still_blocked_from_financed_emissions_router_contract():
    assert is_ssp_formula_id("ssp-lookthrough") is True
    assert is_ssp_formula_id("ssp-reported-pool") is True


def test_calculate_endpoint_preview_and_org_isolation():
    app = FastAPI()
    app.include_router(ssp_calc_routes.router, prefix="/api/v1")

    def _db():
        class _Dummy:
            def add(self, *_a, **_k):
                return None

            def commit(self):
                return None

            def refresh(self, *_a, **_k):
                return None

        yield _Dummy()

    def _org_a():
        return OrgContext(
            user=User(id=USER_A, email="a@planetive.com", password_hash="x"),
            organization_id=ORG_A,
            role="admin",
        )

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[require_org_context] = _org_a
    client = TestClient(app)

    res = client.post("/api/v1/ssp/calculate", json={"draft": _base_draft()})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "complete"
    assert body["is_reportable"] is False
    assert body["include_in_portfolio"] is False
    assert body["financed_emissions"] == 1.0
    assert body["persisted_preview"] is False
