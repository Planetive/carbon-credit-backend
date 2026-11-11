"""
Phase 6C.2 — absolute emissions parity (standalone FE vs SSP) + hierarchy fixtures.

Compares ABSOLUTE emissions before CAF. Independent algebra for attribution stages.
Does not claim official PCAF worked-figure parity.
"""

from __future__ import annotations

import pytest

from fastapi_app.absolute_emissions import (
    AbsoluteEmissionsError,
    absolute_building_emissions_tco2e,
    absolute_company_emissions_tco2e,
    absolute_motor_fleet_emissions_tco2e,
)
from fastapi_app.property_pcaf import run_property_loan_calculation
from fastapi_app.motor_vehicle_pcaf import compute_motor_vehicle_pcaf_financed, resolve_vehicle_rows
from fastapi_app.ssp_calc import calculate_ssp_draft, compute_caf
from fastapi_app.ssp_underlying import absolute_emissions_for_collateral


def test_property_1a_absolute_parity_with_standalone():
    inputs = {
        "outstanding_amount": 40,
        "property_value_at_origination": 100,
        "energy_consumption": 5000,
        "emission_factor": 0.0002,  # tCO2e/kWh → absolute 1.0
    }
    standalone = run_property_loan_calculation(
        formula_id="1a-mortgage",
        option_code="1a",
        data_quality_score=1,
        methodology="PCAF",
        category="mortgage",
        inputs=inputs,
        company_type="listed",
    )
    shared = absolute_building_emissions_tco2e("1a", inputs)
    assert shared["absolute_total_tco2e"] == pytest.approx(1.0)
    assert standalone["metadata"]["totalEmissions"] == pytest.approx(shared["absolute_total_tco2e"])
    # Standalone FE = AF × absolute; AF = 0.4 → FE 0.4
    assert standalone["financed_emissions"] == pytest.approx(0.4)

    ssp = absolute_emissions_for_collateral(
        {
            "collateralId": "c1",
            "collateralType": "mortgage",
            "classInputs": {
                "methodSelection": {"calculationMethod": "1a"},
                "formData": {
                    "energyConsumption": 5000,
                    "emissionFactor": 0.0002,
                },
            },
        }
    )
    assert ssp["status"] == "complete"
    assert ssp["absolute_total_tco2e"] == pytest.approx(shared["absolute_total_tco2e"])
    assert ssp["data_quality_score"] == 1


def test_property_2a_2b_3_absolute_parity():
    cases = [
        (
            "2a",
            {
                "estimated_energy_consumption_from_labels": 100,
                "floor_area": 50,
                "average_emission_factor": 0.0002,
            },
            100 * 50 * 0.0002,
            3,
        ),
        (
            "2b",
            {
                "estimated_energy_consumption_from_statistics": 80,
                "floor_area": 25,
                "average_emission_factor": 0.0004,
            },
            80 * 25 * 0.0004,
            4,
        ),
        (
            "3",
            {
                "estimated_energy_consumption_from_statistics": 1000,
                "number_of_buildings": 2,
                "average_emission_factor": 0.0003,
            },
            1000 * 2 * 0.0003,
            5,
        ),
    ]
    for option, fields, expected, dq in cases:
        inputs = {
            "outstanding_amount": 10,
            "property_value_at_origination": 100,
            **fields,
        }
        shared = absolute_building_emissions_tco2e(option, inputs)
        fe = run_property_loan_calculation(
            formula_id=f"{option}-mortgage",
            option_code=option,
            data_quality_score=dq,
            methodology="PCAF",
            category="mortgage",
            inputs=inputs,
            company_type="listed",
        )
        assert shared["absolute_total_tco2e"] == pytest.approx(expected)
        assert fe["metadata"]["totalEmissions"] == pytest.approx(expected)
        assert shared["data_quality_score"] == dq


def test_motor_absolute_parity_not_financed_total():
    vehicles = [
        {
            "id": "v1",
            "name": "V1",
            "value_at_origination": 20000,
            "distance_traveled": 10000,
            "efficiency": 0.08,
            "emission_factor": 0.0025,
        }
    ]
    # Absolute = 10000 × 0.08 × 0.0025 = 2.0
    abs_motor = absolute_motor_fleet_emissions_tco2e(
        {"vehicle_entries": vehicles},
        option_code="1b",
        fuel_path=False,
    )
    assert abs_motor["absolute_total_tco2e"] == pytest.approx(2.0)

    rows = resolve_vehicle_rows(
        {
            "vehicle_entries": [
                {
                    **vehicles[0],
                    "emissions_tco2e": 2.0,
                }
            ]
        },
        fuel_path=False,
    )
    financed = compute_motor_vehicle_pcaf_financed(10000, rows)
    # Absolute must equal sum of vehicle emissions, NOT financed
    assert financed["total_vehicle_emissions"] == pytest.approx(2.0)
    assert financed["total_financed_emissions"] == pytest.approx(10000 / 20000 * 2.0)
    assert abs_motor["absolute_total_tco2e"] == pytest.approx(financed["total_vehicle_emissions"])
    assert abs_motor["absolute_total_tco2e"] != pytest.approx(financed["total_financed_emissions"])

    ssp = absolute_emissions_for_collateral(
        {
            "collateralId": "c1",
            "collateralType": "motor-vehicle-loan",
            "classInputs": {
                "methodSelection": {"calculationMethod": "1b"},
                "formData": {"vehicle_entries": [{**vehicles[0], "emissions_tco2e": 2.0}]},
            },
        }
    )
    assert ssp["status"] == "complete"
    assert ssp["absolute_total_tco2e"] == pytest.approx(2.0)
    assert ssp["data_quality_score"] == 1


def test_company_1a_2a_3a_and_block_3c():
    verified = absolute_company_emissions_tco2e(
        "1a",
        {"verified_emissions": 100, "scope1_emissions": 60, "scope2_emissions": 40},
    )
    assert verified["absolute_total_tco2e"] == pytest.approx(100)

    energy = absolute_company_emissions_tco2e(
        "2a",
        {"energy_consumption": 1000, "emission_factor": 0.05, "process_emissions": 2},
    )
    assert energy["absolute_total_tco2e"] == pytest.approx(52.0)

    econ = absolute_company_emissions_tco2e(
        "3a",
        {
            "company_revenue": 1_000_000,
            "sector_intensity": 0.01,  # kgCO2e/currency → 0.00001 tCO2e
            "sector_intensity_unit": "kgCO2e/PKR",
        },
    )
    assert econ["absolute_total_tco2e"] == pytest.approx(10.0)

    with pytest.raises(AbsoluteEmissionsError) as blocked:
        absolute_company_emissions_tco2e(
            "3c",
            {"outstanding_amount": 100, "asset_turnover_ratio": 1, "sector_intensity": 0.1},
        )
    assert blocked.value.code == "unsupported_company_option"

    ssp = absolute_emissions_for_collateral(
        {
            "collateralId": "c1",
            "collateralType": "business-loan",
            "classInputs": {
                "methodSelection": {"calculationMethod": "1b"},
                "formData": {"unverified_emissions": 25, "scope1Emissions": 25},
            },
        }
    )
    assert ssp["status"] == "complete"
    assert ssp["absolute_total_tco2e"] == pytest.approx(25.0)


def test_ssp_pipeline_uses_absolute_not_standalone_fe():
    # Absolute 10 via reported; CAF 0.4 → loan FE 4 (not AF from standalone)
    draft = {
        "eligibility": {"hasTranches": "yes", "hasPoolOfPools": "no", "poolsLinkedToSpecificTranches": "no"},
        "deal": {"structureType": "rmbs", "hasTranches": "yes", "hasPoolOfPools": "no"},
        "emissionsPath": "lookthrough",
        "collateral": [
            {
                "collateralId": "c1",
                "collateralType": "mortgage",
                "assetValueAtOrigination": 100,
                "emissionsPath": "reported",
                "scope2Emissions": 10,
                "dataQualityScore": 2,
            }
        ],
        "loans": [{"loanId": "l1", "collateralIds": ["c1"], "currentOutstandingAmount": 40}],
        "pools": [{"poolId": "p1", "loanIds": ["l1"], "loanAllocations": [{"loanId": "l1", "amountInPool": 40}]}],
        "tranches": [{"trancheId": "t1", "currentOutstandingAmount": 40}],
        "holdings": [{"holdingId": "h1", "trancheId": "t1", "bankOutstandingInvestment": 10}],
    }
    result = calculate_ssp_draft(draft)
    assert result["status"] == "complete"
    assert result["collateral"][0]["absolute_total_tco2e"] == 10.0
    assert result["loans"][0]["financed_emissions_tco2e"] == 4.0
    assert result["financed_emissions"] == 1.0


def test_hierarchy_dq_coa_weight_and_conservation():
    draft = {
        "eligibility": {"hasTranches": "yes", "hasPoolOfPools": "no"},
        "deal": {"structureType": "rmbs", "hasTranches": "yes", "hasPoolOfPools": "no"},
        "emissionsPath": "lookthrough",
        "collateral": [
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
                "dataQualityScore": 4,
            },
        ],
        "loans": [
            {"loanId": "l1", "collateralIds": ["c1"], "currentOutstandingAmount": 40},
            {"loanId": "l2", "collateralIds": ["c2"], "currentOutstandingAmount": 60},
        ],
        "pools": [
            {
                "poolId": "p1",
                "loanIds": ["l1", "l2"],
                "loanAllocations": [
                    {"loanId": "l1", "amountInPool": 40},
                    {"loanId": "l2", "amountInPool": 30},  # LAF 0.5
                ],
            }
        ],
        "tranches": [
            {"trancheId": "t1", "currentOutstandingAmount": 70},
            {"trancheId": "t2", "currentOutstandingAmount": 30},
        ],
        "holdings": [
            {"holdingId": "h1", "trancheId": "t1", "bankOutstandingInvestment": 35},
            {"holdingId": "h2", "trancheId": "t2", "bankOutstandingInvestment": 15},
        ],
    }
    # l1 FE=4; l2 FE=6; pool = 4 + 0.5*6 = 7
    result = calculate_ssp_draft(draft)
    assert result["status"] == "complete", result
    assert result["pools"][0]["financed_emissions_tco2e"] == 7.0
    assert abs(sum(t["financed_emissions_tco2e"] for t in result["tranches"]) - 7.0) < 1e-9
    # DQ: COA-weighted at pool using LAF-scaled COA → 40*2 + 30*4 = 200 / 70 ≈ 2.8571
    assert result["data_quality_score"] == pytest.approx(200 / 70, rel=1e-4)


def test_kg_unit_conversion_on_reported_path():
    ssp = absolute_emissions_for_collateral(
        {
            "collateralId": "c1",
            "collateralType": "mortgage",
            "emissionsPath": "reported",
            "scope2Emissions": 2500,
            "emissionsUnit": "kgCO2e",
        }
    )
    assert ssp["status"] == "complete"
    assert ssp["absolute_total_tco2e"] == pytest.approx(2.5)


def test_caf_cap_still_independent():
    capped = compute_caf(
        collateral_type="mortgage",
        loan_coa=150,
        loan_ooa=None,
        avo=100,
        uav=None,
        equity_plus_debt=None,
        evic=None,
    )
    assert capped["caf"] == 1.0
    assert capped["caf_capped"] is True
