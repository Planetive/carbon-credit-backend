"""UoP calculation refuses drifted library snapshots and keeps PCAF option mapping."""

from __future__ import annotations

from fastapi_app.uop_underlying import calculate_underlying_asset


DENOM = dict(denom_kind="total_asset_value", denom_label="Total asset value", denom_ref="test")


def test_snapshot_mismatch_does_not_calculate():
    result = calculate_underlying_asset(
        {
            "underlyingAssetId": "office-lib",
            "name": "Office",
            "assetClass": "commercial-real-estate",
            "allocatedOutstanding": 5_000_000,
            "totalAssetValue": 10_000_000,
            "hasReportedEmissions": "no",
            "dataSource": "EPC",
            "estimation": {
                "pcafOption": "2a",
                "method": "physical",
                "labelEnergyIntensity": 20,
                "floorArea": 100,
                "emissionFactor": 0.5,
                "factorUnit": "tCO2e/kWh",
                "factorSource": "UK DESNZ",
                "factorGeography": "United Kingdom",
                "factorYear": "2026",
                "libraryEntryId": "11111111-1111-1111-1111-111111111111",
                "libraryFactorValue": 0.001,
                "libraryGeography": "United Kingdom",
                "libraryApplicableYear": "2026",
                "factorConfirmed": True,
            },
        },
        **DENOM,
    )
    assert result["status"] == "incomplete"
    assert result["code"] == "factor_snapshot_mismatch"
    assert result["structure_financed_emissions"] is None
    assert result["factor_snapshot"]["library_entry_id"]


def test_typed_factor_without_library_is_not_used():
    result = calculate_underlying_asset(
        {
            "underlyingAssetId": "office-typed",
            "name": "Office",
            "assetClass": "commercial-real-estate",
            "allocatedOutstanding": 5_000_000,
            "totalAssetValue": 10_000_000,
            "hasReportedEmissions": "no",
            "dataSource": "EPC",
            "estimation": {
                "pcafOption": "2a",
                "method": "physical",
                "labelEnergyIntensity": 20,
                "floorArea": 100,
                "emissionFactor": 0.001,
                "factorUnit": "tCO2e/kWh",
                "factorSource": "published table",
                "factorGeography": "PK",
                "factorYear": "2024",
            },
        },
        **DENOM,
    )
    assert result["status"] == "incomplete"
    assert result["code"] == "factor_not_bound"
    assert result["structure_financed_emissions"] is None
    assert result["factor_snapshot"]["library_entry_id"] is None
