"""
Phase D — golden parity for UK / EPA fuel calculators (SPA FuelEmissions.tsx).

Rule: do not change formula implementations to make tests pass.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fastapi_app.ghg_calc.epa_fuel import (
    build_epa_fuel_map,
    calculate_epa_fuel,
    calculate_epa_fuel_emissions,
)
from fastapi_app.ghg_calc.uk_fuel import (
    build_uk_factors_map,
    calculate_uk_fuel,
    calculate_uk_fuel_emissions,
)

UK_FIXTURES = Path(__file__).parent / "fixtures" / "uk_fuel_golden.json"
EPA_FIXTURES = Path(__file__).parent / "fixtures" / "epa_fuel_golden.json"


@pytest.fixture(scope="module")
def uk_golden():
    with UK_FIXTURES.open(encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def epa_golden():
    with EPA_FIXTURES.open(encoding="utf-8") as f:
        return json.load(f)


def test_uk_explicit_factor(uk_golden):
    for case in uk_golden["explicit_factor"]:
        got = calculate_uk_fuel_emissions(case["quantity"], case["factor"])
        assert got == pytest.approx(
            case["expected_emissions_kg"], rel=1e-9, abs=1e-9
        ), case["id"]


def test_uk_map_lookup(uk_golden):
    for case in uk_golden["map_lookup"]:
        factors_map = build_uk_factors_map(case["sheet_rows"])
        result = calculate_uk_fuel(
            quantity=case["quantity"],
            activity=case["activity"],
            fuel=case["fuel"],
            unit=case["unit"],
            uk_factor_basis=case["uk_factor_basis"],
            factors_map=factors_map,
        )
        assert result["success"] is True, case["id"]
        assert result["factor"] == pytest.approx(
            case["expected_factor"], rel=1e-9, abs=1e-9
        ), case["id"]
        assert result["emissions_kg"] == pytest.approx(
            case["expected_emissions_kg"], rel=1e-9, abs=1e-9
        ), case["id"]


def test_epa_explicit_factor(epa_golden):
    for case in epa_golden["explicit_factor"]:
        got = calculate_epa_fuel_emissions(
            case["quantity"], case["factor"], case["unit"]
        )
        assert got == pytest.approx(
            case["expected_emissions_kg"], rel=1e-9, abs=1e-9
        ), case["id"]


def test_epa_map_lookup(epa_golden):
    for sheet_case in epa_golden["map_lookup"]:
        factors_map = build_epa_fuel_map(sheet_case["sheet_rows"])
        for case in sheet_case["cases"]:
            result = calculate_epa_fuel(
                quantity=case["quantity"],
                unit=case["unit"],
                category=sheet_case["category"],
                fuel=sheet_case["fuel"],
                factors_map=factors_map,
            )
            assert result["success"] is True, f"{sheet_case['id']}:{case['unit']}"
            assert result["factor"] == pytest.approx(
                case["expected_factor"], rel=1e-9, abs=1e-9
            ), f"{sheet_case['id']}:{case['unit']}"
            assert result["emissions_kg"] == pytest.approx(
                case["expected_emissions_kg"], rel=1e-9, abs=1e-9
            ), f"{sheet_case['id']}:{case['unit']}"
