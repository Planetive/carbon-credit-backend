"""
SPA parity harness — assert backend ghg_calc against sibling SPA parity/cases.json.

Source of truth (preferred):
  ../carbon-credit-app-main/parity/cases.json
Fallback copy:
  tests/fixtures/spa_parity_cases.json

Explicit-factor cases only (no sheet lookup). Never change formulas to pass.
Live HTTP SPA↔API compare remains in the SPA repo (`npm run parity:api`).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from fastapi_app.ghg_calc.epa_fuel import calculate_epa_fuel
from fastapi_app.ghg_calc.epa_refrigerant import calculate_epa_refrigerant
from fastapi_app.ghg_calc.electricity import calculate_electricity
from fastapi_app.ghg_calc.heat_steam import calculate_heat_steam
from fastapi_app.ghg_calc.mobile_fuel import calculate_mobile_fuel
from fastapi_app.ghg_calc.non_road import calculate_non_road
from fastapi_app.ghg_calc.on_road import calculate_on_road_diesel, calculate_on_road_gasoline
from fastapi_app.ghg_calc.uk_fuel import calculate_uk_fuel, calculate_uk_fuel_emissions
from fastapi_app.ghg_calc.uk_transport import calculate_uk_delivery, calculate_uk_passenger
from fastapi_app.ghg_calc.waste import calculate_waste

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SIBLING_CASES = (
    BACKEND_ROOT.parent / "carbon-credit-app-main" / "parity" / "cases.json"
)
FIXTURE_CASES = Path(__file__).parent / "fixtures" / "spa_parity_cases.json"

# Suites present in cases.json (explicit-factor only).
SUITES = (
    "uk_fuel",
    "epa_fuel",
    "mobile_fuel",
    "on_road_gasoline",
    "on_road_diesel",
    "non_road",
    "heat_steam",
    "waste",
    "uk_passenger",
    "uk_delivery",
    "uk_refrigerant",
    "electricity",
    "epa_refrigerant",
)


def _load_cases() -> dict:
    """Prefer live sibling SPA file; keep fixtures copy in sync when sibling exists."""
    if SIBLING_CASES.is_file():
        data = json.loads(SIBLING_CASES.read_text(encoding="utf-8"))
        FIXTURE_CASES.parent.mkdir(parents=True, exist_ok=True)
        # Refresh fallback so CI / machines without the sibling stay current after a pull.
        if not FIXTURE_CASES.is_file() or FIXTURE_CASES.read_text(
            encoding="utf-8"
        ) != SIBLING_CASES.read_text(encoding="utf-8"):
            shutil.copyfile(SIBLING_CASES, FIXTURE_CASES)
        return data
    if FIXTURE_CASES.is_file():
        return json.loads(FIXTURE_CASES.read_text(encoding="utf-8"))
    raise FileNotFoundError(
        f"SPA parity cases not found at {SIBLING_CASES} or {FIXTURE_CASES}"
    )


@pytest.fixture(scope="module")
def cases() -> dict:
    return _load_cases()


def _assert_kg(case_id: str, got: float, expected: float) -> None:
    assert got == pytest.approx(expected, rel=1e-9, abs=1e-9), case_id


def _run_case(suite: str, case: dict) -> float:
    """Dispatch one cases.json row through the same ghg_calc entry the API routes use."""
    if suite == "uk_fuel":
        result = calculate_uk_fuel(quantity=case["quantity"], factor=case["factor"])
        assert result["success"] is True, case["id"]
        return float(result["emissions_kg"])

    if suite == "epa_fuel":
        result = calculate_epa_fuel(
            quantity=case["quantity"],
            unit=case["unit"],
            factor=case["factor"],
        )
        assert result["success"] is True, case["id"]
        return float(result["emissions_kg"])

    if suite == "mobile_fuel":
        # SPA MobileFuel factors are per-gallon; liter conversion only runs when unit
        # contains "gallon" (FuelEmissions/MobileFuel UI). cases.json omit unit — supply
        # the SPA reference unit so we exercise the same gate without changing formulas.
        result = calculate_mobile_fuel(
            quantity=case["quantity"],
            factor=case["factor"],
            unit=case.get("unit") or "gallon",
            input_unit=case.get("input_unit"),
        )
        assert result["success"] is True, case["id"]
        return float(result["emissions_kg"])

    if suite == "on_road_gasoline":
        result = calculate_on_road_gasoline(
            distance=case["distance"],
            distance_unit=case.get("distance_unit", "mile"),
            emission_selection=case.get("emission_selection", "ch4_only"),
            ch4_g_per_mile=case.get("ch4_g_per_mile"),
            n2o_g_per_mile=case.get("n2o_g_per_mile"),
        )
        assert result["success"] is True, case["id"]
        return float(result["emissions_kg"])

    if suite == "on_road_diesel":
        result = calculate_on_road_diesel(
            distance=case["distance"],
            distance_unit=case.get("distance_unit", "mile"),
            emission_selection=case.get("emission_selection", "ch4"),
            ch4_g_per_mile=case.get("ch4_g_per_mile"),
            n2o_g_per_mile=case.get("n2o_g_per_mile"),
        )
        assert result["success"] is True, case["id"]
        return float(result["emissions_kg"])

    if suite == "non_road":
        result = calculate_non_road(
            quantity=case["quantity"],
            unit=case.get("unit", "gallon"),
            emission_selection=case.get("emission_selection", "ch4"),
            ch4_g_per_gallon=case.get("ch4_g_per_gallon"),
            n2o_g_per_gallon=case.get("n2o_g_per_gallon"),
        )
        assert result["success"] is True, case["id"]
        return float(result["emissions_kg"])

    if suite == "heat_steam":
        # SPA MMSCF path requires mmBtu base unit (supportsMMSCF). cases omit unit.
        unit = case.get("unit")
        if case.get("quantity_unit") == "mmscf" and not unit:
            unit = "mmBtu"
        result = calculate_heat_steam(
            quantity=case["quantity"],
            gas=case.get("gas", "co2"),
            quantity_unit=case.get("quantity_unit", "base"),
            unit=unit,
            co2_factor=case.get("co2_factor"),
            ch4_factor=case.get("ch4_factor"),
            n2o_factor=case.get("n2o_factor"),
        )
        assert result["success"] is True, case["id"]
        return float(result["emissions_kg"])

    if suite == "waste":
        result = calculate_waste(
            volume=case["volume"],
            disposal_method=case["disposal_method"],
            factor=case["factor"],
        )
        assert result["success"] is True, case["id"]
        return float(result["emissions_kg"])

    if suite == "uk_passenger":
        result = calculate_uk_passenger(
            distance=case["distance"], factor=case["factor"]
        )
        assert result["success"] is True, case["id"]
        return float(result["emissions_kg"])

    if suite == "uk_delivery":
        result = calculate_uk_delivery(
            distance=case["distance"], factor=case["factor"]
        )
        assert result["success"] is True, case["id"]
        return float(result["emissions_kg"])

    if suite == "uk_refrigerant":
        # Same SPA qty×factor round6 as UK fuel / passenger / delivery.
        emissions_kg = calculate_uk_fuel_emissions(case["quantity"], case["factor"])
        return float(emissions_kg)

    if suite == "electricity":
        result = calculate_electricity(
            total_kwh=case["total_kwh"],
            grid_pct=case.get("grid_pct"),
            grid_factor=case.get("grid_factor"),
            other_pct=case.get("other_pct"),
            other_row_emissions_sum=case.get("other_row_emissions_sum"),
            renewable_pct=case.get("renewable_pct"),
        )
        assert result["success"] is True, case["id"]
        return float(result["emissions_kg"])

    if suite == "epa_refrigerant":
        result = calculate_epa_refrigerant(
            method=case["method"],
            gwp=case["gwp"],
            leakage_kg=case.get("leakage_kg"),
            charge_kg=case.get("charge_kg"),
            leakage_rate_percent=case.get("leakage_rate_percent"),
        )
        assert result["success"] is True, case["id"]
        if "expected_leakage_kg" in case:
            assert result["leakage_kg"] == pytest.approx(
                case["expected_leakage_kg"], rel=1e-9, abs=1e-9
            ), case["id"]
        return float(result["emissions_kg"])

    raise AssertionError(f"Unknown suite: {suite}")


def test_spa_parity_cases_loaded(cases):
    for suite in SUITES:
        assert suite in cases, f"missing suite {suite} in SPA parity cases.json"
        assert isinstance(cases[suite], list) and len(cases[suite]) > 0, suite


@pytest.mark.parametrize("suite", SUITES)
def test_spa_parity_suite(cases, suite):
    for case in cases[suite]:
        got = _run_case(suite, case)
        _assert_kg(f"{suite}/{case['id']}", got, case["expected_emissions_kg"])
