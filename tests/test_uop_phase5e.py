"""Phase 5E — remaining UoP calculation capabilities (unit-level)."""

from __future__ import annotations

from fastapi_app.uop_calc import calculate_uop_draft
from fastapi_app.uop_nested import detect_circular_nested, detect_duplicate_nested_ids
from fastapi_app.uop_sovereign import (
    SUB_SOVEREIGN_UNSUPPORTED,
    calculate_uop_sovereign_asset,
    refuse_national_gdp_as_regional,
)
from fastapi_app.uop_overlap_review import enrich_overlap_payload
from fastapi_app.uop_reportable import UOP_REPORTABLE_SAVE_ENABLED


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
        "reportingYear": "2026",
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


def test_sovereign_inside_uop_reuses_pcaf_59_engine_with_supplied_ppp():
    result = calculate_uop_draft(
        _separate(
            assets=[
                {
                    "underlyingAssetId": "sov-1",
                    "name": "UK gilt sleeve",
                    "assetClass": "sovereign-debt",
                    "allocatedOutstanding": 10,
                    "dataSource": "UNFCCC",
                    "hasReportedEmissions": "no",
                    "estimation": {
                        "pcafOption": "1a",
                        "method": "physical",
                        "sovereignCountryName": "United Kingdom",
                        "ppAdjustedGdp": 1000,
                        "pppGdpYear": 2025,
                        "pppGdpSource": "ref.ppp_adjusted_gdp",
                        "verifiedCountryEmissions": 200,
                        "factorSource": "UNFCCC",
                        "factorGeography": "United Kingdom",
                        "factorYear": "2025",
                        "factorUnit": "tCO2e",
                        "emissionFactor": 200,
                        "libraryEntryId": "11111111-1111-1111-1111-111111111111",
                        "factorConfirmed": True,
                    },
                }
            ]
        )
    )
    assert result["status"] == "complete"
    asset = result["assets"][0]
    assert asset["reused_formula_id"] == "1a-sovereign-debt"
    assert asset["denominator_kind"] == "ppp_adjusted_gdp"
    # Outstanding 10 / GDP 1000 × 200 = 2 structure FE; investor AF = 50/100 = 0.5 → 1.0
    assert asset["structure_financed_emissions"] == 2.0
    assert result["financed_emissions"] == 1.0


def test_national_gdp_rejected_for_regional_denominator():
    assert refuse_national_gdp_as_regional(regional_requested=True, used_national_ppp=True)
    blocked = calculate_uop_sovereign_asset(
        {
            "underlying_asset_id": "reg-1",
            "name": "Province bond",
            "asset_class": "sovereign-debt",
            "allocated_outstanding": 10,
            "status": "complete",
        },
        asset={"sovereignLevel": "regional", "regionName": "Punjab"},
        estimation={
            "pcafOption": "1a",
            "regionName": "Punjab",
            "sovereignCountryName": "Pakistan",
            "ppAdjustedGdp": 1000,
            "pppGdpYear": 2025,
            "regionalGdpCurrency": "PKR",
            "regionalGdpSource": "national catalog ref.ppp_adjusted_gdp",
            "verifiedRegionalEmissions": 10,
            "regionalEmissionsSource": "national inventory",
            "regionalEmissionsYear": "2025",
        },
        allocated=10,
        name="Province bond",
        db=None,
    )
    # Routes to §5.10 and refuses national catalog GDP as regional denominator.
    assert blocked["status"] == "incomplete"
    assert "national" in (blocked.get("message") or "").lower()
    assert "national" in SUB_SOVEREIGN_UNSUPPORTED.lower()


def test_nested_uop_lookthrough_applies_each_attribution_once():
    result = calculate_uop_draft(
        _separate(
            assets=[
                {
                    "underlyingAssetId": "nested-1",
                    "name": "Child fund holding",
                    "assetClass": "use-of-proceeds",
                    "allocatedOutstanding": 40,
                    "totalAssetValue": 100,
                    "hasReportedEmissions": "no",
                    "dataSource": "child allocation report",
                    "estimation": {
                        "childStructureId": "fin-child",
                        "childTotalCapital": 100,
                        "childAssets": [
                            {
                                "underlyingAssetId": "child-mortgage",
                                "name": "Child home",
                                "assetClass": "mortgage",
                                "allocatedOutstanding": 20,
                                "totalAssetValue": 40,
                                "hasReportedEmissions": "yes",
                                "verificationStatus": "verified",
                                "scope1Emissions": 10,
                                "dataSource": "operator",
                                "estimation": {},
                            }
                        ],
                        "factorSource": "child look-through",
                        "factorGeography": "PK",
                        "factorYear": "2026",
                        "factorUnit": "tCO2e",
                        "emissionFactor": 1,
                        "libraryEntryId": "11111111-1111-1111-1111-111111111111",
                        "factorConfirmed": True,
                    },
                }
            ]
        )
    )
    assert result["status"] == "complete"
    nested = result["assets"][0]
    assert nested["reused_formula_id"] == "uop-nested-lookthrough"
    # Child structure FE = 20/40 * 10 = 5; parent AF = 40/100 = 0.4 → 2.0
    assert nested["structure_financed_emissions"] == 2.0
    assert result["financed_emissions"] == 1.0  # investor AF 0.5


def test_circular_and_duplicate_nested_references_are_blocked():
    assert detect_circular_nested(parent_id="A", child_id="A", stack=set())
    assert detect_circular_nested(parent_id="A", child_id="B", stack={"B"})
    assert detect_duplicate_nested_ids(
        [
            {"underlyingAssetId": "x"},
            {"underlyingAssetId": "x"},
        ]
    )
    circular = calculate_uop_draft(
        _separate(
            financingInstanceId="fin-loop",
            assets=[
                {
                    "underlyingAssetId": "nested-loop",
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
                                "verificationStatus": "unverified",
                                "scope1Emissions": 1,
                                "dataSource": "x",
                                "estimation": {},
                            }
                        ],
                        "factorSource": "x",
                        "factorGeography": "PK",
                        "factorYear": "2026",
                        "factorUnit": "tCO2e",
                        "emissionFactor": 1,
                        "libraryEntryId": "11111111-1111-1111-1111-111111111111",
                        "factorConfirmed": True,
                    },
                }
            ],
        )
    )
    assert circular["status"] == "unsupported"
    assert "nest itself" in (circular.get("message") or "").lower() or "circular" in (
        circular.get("message") or ""
    ).lower()


def test_multi_vehicle_rows_reuse_motor_vehicle_engine():
    result = calculate_uop_draft(
        _separate(
            assets=[
                {
                    "underlyingAssetId": "fleet-1",
                    "name": "Fleet sleeve",
                    "assetClass": "motor-vehicle-loan",
                    "allocatedOutstanding": 30,
                    "totalAssetValue": 60,
                    "hasReportedEmissions": "no",
                    "dataSource": "fleet log",
                    "estimation": {
                        "pcafOption": "1a",
                        "method": "physical",
                        "emissionFactor": 0.002,
                        "factorUnit": "tCO2e/litre",
                        "factorSource": "DESNZ",
                        "factorGeography": "United Kingdom",
                        "factorYear": "2026",
                        "libraryEntryId": "11111111-1111-1111-1111-111111111111",
                        "factorConfirmed": True,
                        "vehicles": [
                            {
                                "id": "v1",
                                "name": "Van 1",
                                "value_at_origination": 40,
                                "outstanding_amount": 20,
                                "fuel_consumption": 1000,
                                "fuel_unit": "litre",
                            },
                            {
                                "id": "v2",
                                "name": "Van 2",
                                "value_at_origination": 20,
                                "outstanding_amount": 10,
                                "fuel_consumption": 500,
                                "fuel_unit": "litre",
                            },
                        ],
                    },
                }
            ]
        )
    )
    assert result["status"] == "complete"
    asset = result["assets"][0]
    assert asset["reused_formula_id"] == "motor-vehicle-pcaf"
    assert len(asset.get("vehicle_results") or []) == 2
    # v1: (20/40)*2.0 = 1.0; v2: (10/20)*1.0 = 0.5; total structure 1.5; investor 0.75
    assert asset["structure_financed_emissions"] == 1.5


def test_gallon_fuel_unit_is_rejected():
    result = calculate_uop_draft(
        _separate(
            assets=[
                {
                    "underlyingAssetId": "gal-1",
                    "name": "US fleet",
                    "assetClass": "motor-vehicle-loan",
                    "allocatedOutstanding": 10,
                    "totalAssetValue": 20,
                    "hasReportedEmissions": "no",
                    "dataSource": "log",
                    "estimation": {
                        "pcafOption": "1a",
                        "method": "physical",
                        "emissionFactor": 0.01,
                        "factorUnit": "tCO2e/gallon",
                        "factorSource": "EPA",
                        "factorGeography": "United States",
                        "factorYear": "2024",
                        "libraryEntryId": "11111111-1111-1111-1111-111111111111",
                        "factorConfirmed": True,
                        "vehicles": [
                            {
                                "id": "v1",
                                "value_at_origination": 20,
                                "fuel_consumption": 10,
                                "fuel_unit": "gallon",
                            }
                        ],
                    },
                }
            ]
        )
    )
    assert result["status"] == "incomplete"
    assert "gallon" in (result.get("message") or "").lower()


def test_overlap_enrichment_does_not_auto_redistribute_and_save_stays_off():
    payload = enrich_overlap_payload(
        [{"kind": "uop_and_general_purpose", "financing_instance_id": "gp-1"}],
        [],
    )
    assert payload["detected"] is True
    assert payload["status"] == "review_required"
    assert payload["auto_redistribution"] == "none"
    assert payload["unresolved"] is True
    approved = enrich_overlap_payload(
        [{"kind": "uop_and_general_purpose", "financing_instance_id": "gp-1"}],
        [{"status": "approved", "uop_outstanding_adjustment": 1}],
    )
    assert approved["status"] == "approved"
    assert approved["auto_redistribution"] == "none"
    assert UOP_REPORTABLE_SAVE_ENABLED is False
