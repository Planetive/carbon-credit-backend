"""Stage 2 — unit-aware freight / waste / spend for Categories 1,2,4,5,9,12."""

from __future__ import annotations

import pytest

from fastapi_app.ghg_calc.scope3_factor_units import (
    KG_PER_SHORT_TON,
    WASTE_DATASET_FACTOR_UNIT,
)
from fastapi_app.ghg_calc.scope3_simple import calculate_freight, calculate_spend_based
from fastapi_app.ghg_calc.waste import build_waste_materials, calculate_waste


def test_waste_mtco2e_per_short_ton_from_kg():
    r = calculate_waste(
        volume=100,
        disposal_method="Landfilled",
        factor=0.05,
        factor_unit=WASTE_DATASET_FACTOR_UNIT,
        mass_unit="kg",
    )
    assert r["success"] is True
    assert r["emissions_kg"] == pytest.approx(
        (100 / KG_PER_SHORT_TON) * 0.05 * 1000, rel=1e-9
    )


def test_waste_1000kg_is_not_one_short_ton():
    r = calculate_waste(
        volume=1000,
        disposal_method="Landfilled",
        factor=1.0,
        factor_unit=WASTE_DATASET_FACTOR_UNIT,
        mass_unit="kg",
    )
    assert r["success"] is True
    # Wrong old formula: volume * factor = 1000
    assert r["emissions_kg"] != pytest.approx(1000.0)
    # Correct: ~1.102 short tons × 1 MTCO2e × 1000 kg
    assert r["emissions_kg"] == pytest.approx(
        (1000 / KG_PER_SHORT_TON) * 1.0 * 1000, rel=1e-9
    )


def test_waste_refuses_missing_factor_unit():
    r = calculate_waste(
        volume=100,
        disposal_method="Landfilled",
        factor=0.05,
        mass_unit="kg",
    )
    assert r["success"] is False


def test_waste_refuses_ambiguous_factor_unit():
    r = calculate_waste(
        volume=100,
        disposal_method="Landfilled",
        factor=0.05,
        factor_unit="per unit",
        mass_unit="kg",
    )
    assert r["success"] is False


def test_waste_sheet_lookup_with_wet_digestate_double_space():
    materials = build_waste_materials(
        [
            {
                "Material": "Food Waste (non-meat)",
                "Landfilled": 0.67,
                "Anaerobically Digested (Wet  Digestate with Curing)": 0.11,
            }
        ]
    )
    r = calculate_waste(
        volume=907.18474,
        disposal_method="Anaerobically Digested (Wet Digestate with Curing)",
        material="Food Waste (non-meat)",
        materials=materials,
        factor_unit=WASTE_DATASET_FACTOR_UNIT,
        mass_unit="kg",
    )
    assert r["success"] is True
    # 1 short ton × 0.11 MTCO2e = 110 kg
    assert r["emissions_kg"] == pytest.approx(110.0, rel=1e-9)


def test_freight_vehicle_mile_ignores_weight():
    a = calculate_freight(
        distance=50, weight=0, co2_factor=0.297, factor_unit="vehicle-mile"
    )
    b = calculate_freight(
        distance=50, weight=9999, co2_factor=0.297, factor_unit="vehicle-mile"
    )
    assert a["success"] and b["success"]
    assert a["emissions_kg"] == pytest.approx(b["emissions_kg"], rel=1e-12)


def test_spend_supplier_usd_unit():
    r = calculate_spend_based(
        amount=25000,
        emission_factor=0.488,
        factor_unit="kg CO2e/2022 USD, purchaser price",
        activity_currency="USD",
        activity_price_year=2022,
    )
    assert r["success"] is True
    assert r["emissions_kg"] == pytest.approx(12200.0, rel=1e-9)
