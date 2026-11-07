"""Phase 5E.1 — methodology verification + sub-sovereign §5.10."""

from __future__ import annotations

from fastapi_app.uop_calc import calculate_uop_draft
from fastapi_app.uop_nested import detect_circular_nested, detect_duplicate_nested_ids
from fastapi_app.uop_reportable import UOP_REPORTABLE_SAVE_ENABLED
from fastapi_app.uop_sovereign import calculate_uop_sovereign_asset
from fastapi_app.uop_sub_sovereign import (
    calculate_uop_sub_sovereign_asset,
    resolve_regional_ppp_gdp,
)
from fastapi_app.sovereign_pcaf import run_sovereign_calculation


def _separate(**overrides):
    draft = {
        "eligibility": {
            "proceedsAllocatedToSpecificAssets": "yes",
            "isSecuritized": "no",
            "structureHasControl": "no",
            "debtBasedWithOneFullyAllocatedAsset": "no",
            "assetsOnIssuerBalanceSheet": "no",
        },
        "structureName": "Fund",
        "issuerName": "Issuer",
        "structureKind": "debt-fund",
        "investmentType": "debt",
        "outstandingInvestment": 50,
        "totalStructureDebt": 100,
        "totalStructureEquity": 0,
        "reportingYear": "2025",
        "currency": "PKR",
        "evidenceSource": "prospectus",
        "emissionsPath": "underlying_assets",
        "allocationStatus": "known",
        "allocatedProceeds": 50,
        "financingInstanceId": "fin-parent",
        "assets": [],
    }
    draft.update(overrides)
    return draft


def test_sovereign_uop_matches_standalone_engine():
    inputs = {
        "outstanding_amount": 10,
        "pp_adjusted_gdp": 1000,
        "verified_country_emissions": 200,
    }
    standalone = run_sovereign_calculation(
        formula_id="1a-sovereign-debt",
        option_code="1a",
        data_quality_score=1,
        methodology="standalone",
        inputs=inputs,
        company_type="sovereign",
    )
    uop = calculate_uop_draft(
        _separate(
            assets=[
                {
                    "underlyingAssetId": "sov-parity",
                    "name": "Gilt",
                    "assetClass": "sovereign-debt",
                    "allocatedOutstanding": 10,
                    "dataSource": "UNFCCC",
                    "hasReportedEmissions": "no",
                    "estimation": {
                        "pcafOption": "1a",
                        "sovereignCountryName": "United Kingdom",
                        "ppAdjustedGdp": 1000,
                        "pppGdpYear": 2025,
                        "pppGdpSource": "ref.ppp_adjusted_gdp",
                        "preferredPppGdpYear": 2025,
                        "verifiedCountryEmissions": 200,
                        "emissionFactor": 200,
                        "factorSource": "UNFCCC",
                        "factorUnit": "tCO2e",
                        "libraryEntryId": "11111111-1111-1111-1111-111111111111",
                        "factorConfirmed": True,
                    },
                }
            ]
        )
    )
    assert uop["status"] == "complete"
    assert uop["assets"][0]["structure_financed_emissions"] == standalone["financed_emissions"]
    assert uop["assets"][0]["asset_attribution_factor"] == standalone["attribution_factor"]


def test_ppp_2024_not_silently_used_for_2025():
    result = calculate_uop_sovereign_asset(
        {"underlying_asset_id": "sov-fb", "name": "Bond", "status": "complete"},
        asset={},
        estimation={
            "pcafOption": "1a",
            "sovereignCountryName": "Testland",
            "ppAdjustedGdp": 500,
            "pppGdpYear": 2024,
            "pppGdpSource": "ref.ppp_adjusted_gdp",
            "preferredPppGdpYear": 2025,
            "ppp_gdp_used_fallback": True,
            "verifiedCountryEmissions": 100,
        },
        allocated=10,
        name="Bond",
        db=None,
    )
    # build_sovereign_inputs does not set used_fallback from estimation; year 2024 vs preferred 2025 triggers.
    assert result["status"] == "incomplete"
    assert result["code"] == "ppp_gdp_year_fallback_unconfirmed"

    confirmed = calculate_uop_sovereign_asset(
        {"underlying_asset_id": "sov-fb2", "name": "Bond", "status": "complete"},
        asset={},
        estimation={
            "pcafOption": "1a",
            "sovereignCountryName": "Testland",
            "ppAdjustedGdp": 500,
            "pppGdpYear": 2024,
            "pppGdpSource": "ref.ppp_adjusted_gdp",
            "preferredPppGdpYear": 2025,
            "allowPppGdpFallback": True,
            "verifiedCountryEmissions": 100,
        },
        allocated=10,
        name="Bond",
        db=None,
    )
    assert confirmed["status"] == "complete"
    assert confirmed["ppp_gdp_fallback_confirmed"] is True


def test_national_gdp_rejected_as_regional_denominator():
    blocked = calculate_uop_sub_sovereign_asset(
        {"underlying_asset_id": "reg-1", "name": "Province", "status": "complete"},
        asset={"regionName": "Punjab"},
        estimation={
            "pcafOption": "1a",
            "regionName": "Punjab",
            "sovereignCountryName": "Pakistan",
            "ppAdjustedGdp": 1000,
            "pppGdpYear": "2025",
            "regionalGdpCurrency": "PKR",
            "regionalGdpSource": "national catalog ref.ppp_adjusted_gdp",
            "verifiedRegionalEmissions": 50,
            "regionalEmissionsSource": "inventory",
            "regionalEmissionsYear": "2025",
        },
        allocated=10,
        name="Province",
    )
    assert blocked["status"] == "incomplete"
    assert "national" in (blocked.get("message") or "").lower()

    gdp, prov = resolve_regional_ppp_gdp(
        {
            "regionalNominalGdp": 100,
            "countryPppAdjustmentFactor": 1.2,
            "regionalGdpCurrency": "PKR",
            "regionalGdpYear": "2025",
            "regionalGdpSource": "provincial statistics bureau",
        },
        {},
    )
    assert gdp == 120.0
    assert prov["method"] == "annex_10_3_ppp_factor"


def test_sub_sovereign_1a_with_user_regional_inputs_and_af_cap():
    result = calculate_uop_draft(
        _separate(
            assets=[
                {
                    "underlyingAssetId": "sub-1",
                    "name": "Punjab sukuk",
                    "assetClass": "sub-sovereign-debt",
                    "allocatedOutstanding": 200,
                    "dataSource": "provincial inventory",
                    "hasReportedEmissions": "no",
                    "estimation": {
                        "pcafOption": "1a",
                        "regionName": "Punjab",
                        "sovereignCountryName": "Pakistan",
                        "regionalPppAdjustedGdp": 100,
                        "regionalGdpCurrency": "PKR",
                        "regionalGdpYear": "2025",
                        "regionalGdpSource": "Punjab Bureau of Statistics PPP-adjusted estimate",
                        "verifiedRegionalEmissions": 50,
                        "regionalEmissionsSource": "Punjab GHG inventory",
                        "regionalEmissionsYear": "2025",
                        "regionalEmissionsUnit": "tCO2e",
                        "libraryEntryId": "11111111-1111-1111-1111-111111111111",
                        "factorConfirmed": True,
                    },
                }
            ]
        )
    )
    assert result["status"] == "complete"
    asset = result["assets"][0]
    assert asset["reused_formula_id"] == "1a-sub-sovereign-debt"
    assert asset["denominator_kind"] == "regional_ppp_adjusted_gdp"
    # Outstanding 200 / GDP 100 = 2 → capped at 1; FE = 1 × 50 = 50 structure; investor 0.5 → 25
    assert asset["attribution_capped_at_one"] is True
    assert asset["structure_financed_emissions"] == 50.0
    assert result["financed_emissions"] == 25.0


def test_nested_two_levels_multiple_assets_and_guards():
    assert detect_duplicate_nested_ids(
        [{"underlyingAssetId": "a"}, {"underlyingAssetId": "a"}]
    )
    assert detect_circular_nested(parent_id="P", child_id="P", stack=set())

    result = calculate_uop_draft(
        _separate(
            financingInstanceId="fin-L1",
            assets=[
                {
                    "underlyingAssetId": "nest-L1",
                    "name": "Child fund",
                    "assetClass": "use-of-proceeds",
                    "allocatedOutstanding": 40,
                    "dataSource": "LP report",
                    "hasReportedEmissions": "no",
                    "estimation": {
                        "childStructureId": "fin-L2",
                        "childTotalCapital": 100,
                        "childAssets": [
                            {
                                "underlyingAssetId": "nest-L2",
                                "name": "Grandchild fund sleeve",
                                "assetClass": "use-of-proceeds",
                                "allocatedOutstanding": 50,
                                "hasReportedEmissions": "no",
                                "dataSource": "grandchild",
                                "estimation": {
                                    "childStructureId": "fin-L3",
                                    "childTotalCapital": 80,
                                    "childAssets": [
                                        {
                                            "underlyingAssetId": "asset-a",
                                            "name": "Home A",
                                            "assetClass": "mortgage",
                                            "allocatedOutstanding": 20,
                                            "totalAssetValue": 40,
                                            "hasReportedEmissions": "yes",
                                            "verificationStatus": "verified",
                                            "scope1Emissions": 8,
                                            "dataSource": "EPC",
                                            "estimation": {},
                                        },
                                        {
                                            "underlyingAssetId": "asset-b",
                                            "name": "Home B",
                                            "assetClass": "mortgage",
                                            "allocatedOutstanding": 20,
                                            "totalAssetValue": 40,
                                            "hasReportedEmissions": "yes",
                                            "verificationStatus": "unverified",
                                            "scope1Emissions": 4,
                                            "dataSource": "EPC",
                                            "estimation": {},
                                        },
                                    ],
                                },
                            }
                        ],
                        "libraryEntryId": "11111111-1111-1111-1111-111111111111",
                        "factorConfirmed": True,
                        "factorSource": "look-through",
                        "factorUnit": "tCO2e",
                        "emissionFactor": 1,
                        "factorGeography": "PK",
                        "factorYear": "2025",
                    },
                }
            ],
        )
    )
    assert result["status"] == "complete"
    # L3 object FE: 20/40*8 + 20/40*4 = 4+2 = 6
    # L2 AF into L3: 50/80 = 0.625 → 3.75
    # L1 AF into L2: 40/100 = 0.4 → 1.5
    # Investor AF 0.5 → 0.75
    assert abs(result["assets"][0]["structure_financed_emissions"] - 1.5) < 1e-9
    assert abs(result["financed_emissions"] - 0.75) < 1e-9

    circular = calculate_uop_draft(
        _separate(
            financingInstanceId="fin-loop",
            assets=[
                {
                    "underlyingAssetId": "loop",
                    "name": "Loop",
                    "assetClass": "use-of-proceeds",
                    "allocatedOutstanding": 10,
                    "hasReportedEmissions": "no",
                    "dataSource": "x",
                    "estimation": {
                        "childStructureId": "fin-loop",
                        "childTotalCapital": 20,
                        "childAssets": [
                            {
                                "underlyingAssetId": "inner",
                                "name": "Inner",
                                "assetClass": "mortgage",
                                "allocatedOutstanding": 5,
                                "totalAssetValue": 10,
                                "hasReportedEmissions": "yes",
                                "verificationStatus": "verified",
                                "scope1Emissions": 1,
                                "dataSource": "x",
                                "estimation": {},
                            }
                        ],
                        "libraryEntryId": "11111111-1111-1111-1111-111111111111",
                        "factorConfirmed": True,
                        "factorSource": "x",
                        "factorUnit": "tCO2e",
                        "emissionFactor": 1,
                        "factorGeography": "PK",
                        "factorYear": "2025",
                    },
                }
            ],
        )
    )
    assert circular["status"] == "unsupported"

    dup = calculate_uop_draft(
        _separate(
            assets=[
                {
                    "underlyingAssetId": "dup-parent",
                    "name": "Dup",
                    "assetClass": "use-of-proceeds",
                    "allocatedOutstanding": 10,
                    "hasReportedEmissions": "no",
                    "dataSource": "x",
                    "estimation": {
                        "childStructureId": "fin-child",
                        "childTotalCapital": 20,
                        "childAssets": [
                            {
                                "underlyingAssetId": "same",
                                "name": "A",
                                "assetClass": "mortgage",
                                "allocatedOutstanding": 5,
                                "totalAssetValue": 10,
                                "hasReportedEmissions": "yes",
                                "verificationStatus": "verified",
                                "scope1Emissions": 1,
                                "dataSource": "x",
                                "estimation": {},
                            },
                            {
                                "underlyingAssetId": "same",
                                "name": "A again",
                                "assetClass": "mortgage",
                                "allocatedOutstanding": 5,
                                "totalAssetValue": 10,
                                "hasReportedEmissions": "yes",
                                "verificationStatus": "verified",
                                "scope1Emissions": 1,
                                "dataSource": "x",
                                "estimation": {},
                            },
                        ],
                        "libraryEntryId": "11111111-1111-1111-1111-111111111111",
                        "factorConfirmed": True,
                        "factorSource": "x",
                        "factorUnit": "tCO2e",
                        "emissionFactor": 1,
                        "factorGeography": "PK",
                        "factorYear": "2025",
                    },
                }
            ]
        )
    )
    assert dup["status"] in ("incomplete", "unsupported")
    assert "duplicate" in (dup.get("message") or "").lower()


def test_economic_rejects_fuel_unit_and_save_stays_off():
    result = calculate_uop_draft(
        _separate(
            assets=[
                {
                    "underlyingAssetId": "econ-1",
                    "name": "Corp",
                    "assetClass": "listed-equity",
                    "allocatedOutstanding": 10,
                    "totalAssetValue": 100,
                    "hasReportedEmissions": "no",
                    "dataSource": "filings",
                    "estimation": {
                        "pcafOption": "3a",
                        "method": "economic",
                        "companyRevenue": 50,
                        "activityCurrency": "PKR",
                        "priceYear": "2024",
                        "emissionFactor": 0.1,
                        "factorUnit": "kgCO2e/kWh",
                        "factorSource": "EPA",
                        "factorGeography": "PK",
                        "factorYear": "2024",
                        "libraryEntryId": "11111111-1111-1111-1111-111111111111",
                        "factorConfirmed": True,
                    },
                }
            ]
        )
    )
    assert result["status"] == "incomplete"
    assert "electricity" in (result.get("message") or "").lower() or "fuel" in (
        result.get("message") or ""
    ).lower() or "economic" in (result.get("message") or "").lower()
    assert UOP_REPORTABLE_SAVE_ENABLED is False
