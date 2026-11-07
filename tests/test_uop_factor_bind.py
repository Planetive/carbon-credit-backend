"""Unit tests for UoP server-side factor binding. No production database."""

from __future__ import annotations

from fastapi_app.uop_factor_bind import (
    UOP_OPTION_BINDINGS,
    allow_unbound_typed_factors,
    reset_unbound_typed_factors,
    resolve_uop_library_factor,
    unit_compatible,
)
from fastapi_app.uop_underlying import calculate_underlying_asset


DENOM = dict(denom_kind="total_asset_value", denom_label="Total asset value", denom_ref="test")


def test_typed_factor_without_library_id_is_rejected():
    result = resolve_uop_library_factor(
        {"emissionFactor": 0.5, "factorSource": "typed table", "pcafOption": "2a"},
        asset_class="commercial-real-estate",
        option="2a",
    )
    assert result.ok is False
    assert result.code == "FACTOR_NOT_BOUND"


def test_economic_option_without_library_id_is_unavailable():
    result = resolve_uop_library_factor(
        {"emissionFactor": 0.4, "pcafOption": "3a"},
        asset_class="listed-equity",
        option="3a",
    )
    assert result.ok is False
    assert result.code == "ECONOMIC_FACTOR_UNAVAILABLE"


def test_formula_seam_does_not_invent_a_verified_row():
    token = allow_unbound_typed_factors(True)
    try:
        result = resolve_uop_library_factor(
            {"emissionFactor": 0.001, "pcafOption": "2a"},
            asset_class="mortgage",
            option="2a",
        )
        assert result.ok is True
        assert result.factor is None
        assert result.code == "TEST_SEAM_UNBOUND"
    finally:
        reset_unbound_typed_factors(token)


def test_gallon_is_not_a_litre_vehicle_factor():
    assert unit_compatible("motor-vehicle-loan", "1a", "kgCO2e/litre") is True
    assert unit_compatible("motor-vehicle-loan", "1a", "kgCO2e/gallon") is False


def test_option_bindings_keep_economic_unavailable():
    economic = [item for item in UOP_OPTION_BINDINGS if item["library_class"] == "economic"]
    assert economic
    assert all("none" in item["available_now"] for item in economic)


def test_calculate_rejects_unbound_typed_office():
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
                "factorSource": "typed table",
                "factorGeography": "Pakistan",
                "factorYear": "2026",
            },
        },
        **DENOM,
    )
    assert result["status"] == "incomplete"
    assert result["code"] == "factor_not_bound"
    assert result["structure_financed_emissions"] is None
