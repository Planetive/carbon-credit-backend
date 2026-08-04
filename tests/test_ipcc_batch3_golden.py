"""Batch 3 IPCC golden parity."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fastapi_app.ghg_calc.ipcc_flaring import calculate_ipcc_flaring
from fastapi_app.ghg_calc.ipcc_operational import (
    calculate_ipcc_heating,
    calculate_ipcc_kitchen,
    calculate_ipcc_power,
    calculate_ipcc_vehicular,
)
from fastapi_app.ghg_calc.ipcc_road import (
    calculate_ipcc_alt_fuel,
    calculate_ipcc_industry,
    calculate_ipcc_road,
    calculate_ipcc_road_vehicle,
    calculate_ipcc_usa_vehicles,
)
from fastapi_app.ghg_calc.ipcc_stationary import calculate_ipcc_stationary
from fastapi_app.ghg_calc.ipcc_venting import calculate_ipcc_venting

FIXTURES = Path(__file__).parent / "fixtures" / "ipcc_batch3_golden.json"


@pytest.fixture(scope="module")
def golden():
    with FIXTURES.open(encoding="utf-8") as f:
        return json.load(f)


def test_stationary(golden):
    for case in golden["stationary"]:
        r = calculate_ipcc_stationary(quantity=case["quantity"], factor=case["factor"])
        assert r["emissions_kg"] == pytest.approx(
            case["expected_emissions_kg"], rel=1e-9, abs=1e-9
        ), case["id"]


def test_vehicular(golden):
    for case in golden["vehicular"]:
        r = calculate_ipcc_vehicular(
            diesel_liters=case["diesel_liters"], petrol_liters=case["petrol_liters"]
        )
        assert r["emissions_kg"] == pytest.approx(
            case["expected_emissions_kg"], rel=1e-9, abs=1e-9
        ), case["id"]
        assert r["emissions_tco2e"] == pytest.approx(
            case["expected_tco2e"], rel=1e-9, abs=1e-9
        ), case["id"]


def test_kitchen(golden):
    for case in golden["kitchen"]:
        r = calculate_ipcc_kitchen(
            lpg_kg=case["lpg_kg"], ng_mmscf=case["ng_mmscf"], ghv=case["ghv"]
        )
        assert r["emissions_kg"] == pytest.approx(
            case["expected_emissions_kg"], rel=1e-9, abs=1e-9
        ), case["id"]


def test_power(golden):
    for case in golden["power"]:
        r = calculate_ipcc_power(
            diesel_liters=case["diesel_liters"],
            ng_mmscf=case["ng_mmscf"],
            ghv=case["ghv"],
        )
        assert r["emissions_kg"] == pytest.approx(
            case["expected_emissions_kg"], rel=1e-9, abs=1e-9
        ), case["id"]


def test_heating(golden):
    for case in golden["heating"]:
        r = calculate_ipcc_heating(ng_mmscf=case["ng_mmscf"], ghv=case["ghv"])
        assert r["emissions_kg"] == pytest.approx(
            case["expected_emissions_kg"], rel=1e-9, abs=1e-9
        ), case["id"]


def test_road(golden):
    for case in golden["road"]:
        r = calculate_ipcc_road(quantity=case["quantity"], factor=case["factor"])
        assert r["emissions_kg"] == pytest.approx(
            case["expected_emissions_kg"], rel=1e-9, abs=1e-9
        ), case["id"]


def test_road_vehicle(golden):
    for case in golden["road_vehicle"]:
        r = calculate_ipcc_road_vehicle(
            quantity=case["quantity"],
            ch4_factor=case.get("ch4_factor"),
            n2o_factor=case.get("n2o_factor"),
            selected_factor=case["selected_factor"],
        )
        assert r["emissions_kg"] == pytest.approx(
            case["expected_emissions_kg"], rel=1e-9, abs=1e-9
        ), case["id"]


def test_usa(golden):
    for case in golden["usa_vehicles"]:
        r = calculate_ipcc_usa_vehicles(
            quantity=case["quantity"], factor=case["factor"]
        )
        assert r["emissions_kg"] == pytest.approx(
            case["expected_emissions_kg"], rel=1e-9, abs=1e-9
        ), case["id"]


def test_alt(golden):
    for case in golden["alt_fuel"]:
        r = calculate_ipcc_alt_fuel(
            quantity=case["quantity"],
            ch4_factor=case.get("ch4_factor"),
            n2o_factor=case.get("n2o_factor"),
            selected_factor=case["selected_factor"],
        )
        assert r["emissions_kg"] == pytest.approx(
            case["expected_emissions_kg"], rel=1e-9, abs=1e-9
        ), case["id"]


def test_industry(golden):
    for case in golden["industry"]:
        r = calculate_ipcc_industry(
            quantity=case["quantity"],
            ef_co2=case.get("ef_co2"),
            ef_ch4=case.get("ef_ch4"),
            ef_n2o=case.get("ef_n2o"),
            selected_factor=case["selected_factor"],
        )
        assert r["emissions_kg"] == pytest.approx(
            case["expected_emissions_kg"], rel=1e-9, abs=1e-9
        ), case["id"]


def test_flaring(golden):
    for case in golden["flaring"]:
        r = calculate_ipcc_flaring(
            volume=case["volume"],
            unit=case["unit"],
            composition=case["composition"],
        )
        assert r["emissions_kg"] == pytest.approx(
            case["expected_emissions_kg"], rel=1e-9, abs=1e-9
        ), case["id"]


def test_venting(golden):
    for case in golden["venting"]:
        r = calculate_ipcc_venting(
            volume=case["volume"],
            unit=case["unit"],
            composition=case["composition"],
        )
        assert r["emissions_kg"] == pytest.approx(
            case["expected_emissions_kg"], rel=1e-9, abs=1e-9
        ), case["id"]
