"""
Phase D continued — golden parity for mobile / on-road / non-road / heat / waste / UK transport.

Rule: do not change formula implementations to make tests pass.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fastapi_app.ghg_calc.heat_steam import build_heat_steam_rows, calculate_heat_steam
from fastapi_app.ghg_calc.mobile_fuel import build_mobile_options, calculate_mobile_fuel
from fastapi_app.ghg_calc.non_road import calculate_non_road
from fastapi_app.ghg_calc.on_road import (
    build_on_road_diesel_rows,
    build_on_road_gasoline_rows,
    calculate_on_road_diesel,
    calculate_on_road_gasoline,
)
from fastapi_app.ghg_calc.uk_transport import (
    build_uk_delivery_map,
    build_uk_passenger_map,
    calculate_uk_delivery,
    calculate_uk_passenger,
)
from fastapi_app.ghg_calc.waste import build_waste_materials, calculate_waste

FIXTURES = Path(__file__).parent / "fixtures" / "ghg_expanded_golden.json"


@pytest.fixture(scope="module")
def golden():
    with FIXTURES.open(encoding="utf-8") as f:
        return json.load(f)


def test_mobile_fuel(golden):
    for case in golden["mobile_fuel"]:
        if "sheet_rows" in case:
            options = build_mobile_options(case["sheet_rows"])
            result = calculate_mobile_fuel(
                quantity=case["quantity"],
                fuel_type=case["fuel_type"],
                input_unit=case.get("input_unit"),
                options=options,
            )
        else:
            result = calculate_mobile_fuel(
                quantity=case["quantity"],
                factor=case["factor"],
                unit=case.get("unit"),
                input_unit=case.get("input_unit"),
            )
        assert result["success"] is True, case["id"]
        assert result["emissions_kg"] == pytest.approx(
            case["expected_emissions_kg"], rel=1e-9, abs=1e-9
        ), case["id"]


def test_on_road_gasoline(golden):
    for case in golden["on_road_gasoline"]:
        if "sheet_rows" in case:
            rows = build_on_road_gasoline_rows(case["sheet_rows"])
            result = calculate_on_road_gasoline(
                distance=case["distance"],
                distance_unit=case.get("distance_unit", "mile"),
                vehicle_type=case["vehicle_type"],
                model_year=case["model_year"],
                emission_selection=case["emission_selection"],
                factor_rows=rows,
            )
        else:
            result = calculate_on_road_gasoline(
                distance=case["distance"],
                distance_unit=case.get("distance_unit", "mile"),
                emission_selection=case["emission_selection"],
                ch4_g_per_mile=case.get("ch4_g_per_mile"),
                n2o_g_per_mile=case.get("n2o_g_per_mile"),
            )
        assert result["success"] is True, case["id"]
        assert result["emissions_kg"] == pytest.approx(
            case["expected_emissions_kg"], rel=1e-9, abs=1e-9
        ), case["id"]


def test_on_road_diesel(golden):
    for case in golden["on_road_diesel"]:
        if "sheet_rows" in case:
            rows = build_on_road_diesel_rows(case["sheet_rows"])
            result = calculate_on_road_diesel(
                distance=case["distance"],
                distance_unit=case.get("distance_unit", "mile"),
                vehicle_type=case["vehicle_type"],
                fuel_type=case["fuel_type"],
                emission_selection=case["emission_selection"],
                factor_rows=rows,
            )
        else:
            result = calculate_on_road_diesel(
                distance=case["distance"],
                distance_unit=case.get("distance_unit", "mile"),
                emission_selection=case["emission_selection"],
                ch4_g_per_mile=case.get("ch4_g_per_mile"),
                n2o_g_per_mile=case.get("n2o_g_per_mile"),
            )
        assert result["success"] is True, case["id"]
        assert result["emissions_kg"] == pytest.approx(
            case["expected_emissions_kg"], rel=1e-9, abs=1e-9
        ), case["id"]


def test_non_road(golden):
    for case in golden["non_road"]:
        result = calculate_non_road(
            quantity=case["quantity"],
            unit=case["unit"],
            emission_selection=case["emission_selection"],
            ch4_g_per_gallon=case.get("ch4_g_per_gallon"),
            n2o_g_per_gallon=case.get("n2o_g_per_gallon"),
        )
        assert result["success"] is True, case["id"]
        assert result["emissions_kg"] == pytest.approx(
            case["expected_emissions_kg"], rel=1e-9, abs=1e-9
        ), case["id"]


def test_heat_steam(golden):
    for case in golden["heat_steam"]:
        if "sheet_rows" in case:
            rows = build_heat_steam_rows(case["sheet_rows"])
            result = calculate_heat_steam(
                quantity=case["quantity"],
                gas=case["gas"],
                entry_type=case["entry_type"],
                factor_rows=rows,
            )
        else:
            result = calculate_heat_steam(
                quantity=case["quantity"],
                gas=case["gas"],
                quantity_unit=case.get("quantity_unit", "base"),
                unit=case.get("unit"),
                co2_factor=case.get("co2_factor"),
                ch4_factor=case.get("ch4_factor"),
                n2o_factor=case.get("n2o_factor"),
            )
        assert result["success"] is True, case["id"]
        assert result["emissions_kg"] == pytest.approx(
            case["expected_emissions_kg"], rel=1e-9, abs=1e-9
        ), case["id"]


def test_waste(golden):
    for case in golden["waste"]:
        if "sheet_rows" in case:
            materials = build_waste_materials(case["sheet_rows"])
            result = calculate_waste(
                volume=case["volume"],
                disposal_method=case["disposal_method"],
                material=case["material"],
                materials=materials,
            )
        else:
            result = calculate_waste(
                volume=case["volume"],
                disposal_method=case["disposal_method"],
                factor=case["factor"],
            )
        assert result["success"] is True, case["id"]
        assert result["emissions_kg"] == pytest.approx(
            case["expected_emissions_kg"], rel=1e-9, abs=1e-9
        ), case["id"]


def test_uk_passenger(golden):
    for case in golden["uk_passenger"]:
        if "sheet_rows" in case:
            factors_map = build_uk_passenger_map(case["sheet_rows"])
            result = calculate_uk_passenger(
                distance=case["distance"],
                activity=case["activity"],
                vehicle_type=case["vehicle_type"],
                unit=case["unit"],
                fuel_type=case["fuel_type"],
                uk_factor_basis=case.get("uk_factor_basis", "total"),
                factors_map=factors_map,
            )
        else:
            result = calculate_uk_passenger(
                distance=case["distance"], factor=case["factor"]
            )
        assert result["success"] is True, case["id"]
        assert result["emissions_kg"] == pytest.approx(
            case["expected_emissions_kg"], rel=1e-9, abs=1e-9
        ), case["id"]


def test_uk_delivery(golden):
    for case in golden["uk_delivery"]:
        if "sheet_rows" in case:
            factors_map = build_uk_delivery_map(case["sheet_rows"])
            result = calculate_uk_delivery(
                distance=case["distance"],
                activity=case["activity"],
                vehicle_type=case["vehicle_type"],
                unit=case["unit"],
                fuel_type=case["fuel_type"],
                laden_level=case.get("laden_level"),
                factors_map=factors_map,
            )
        else:
            result = calculate_uk_delivery(
                distance=case["distance"], factor=case["factor"]
            )
        assert result["success"] is True, case["id"]
        assert result["emissions_kg"] == pytest.approx(
            case["expected_emissions_kg"], rel=1e-9, abs=1e-9
        ), case["id"]
