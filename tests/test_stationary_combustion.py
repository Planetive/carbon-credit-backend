"""Authoritative EPA stationary combustion. Factors are the confirmed live sheet rows."""

from __future__ import annotations

from fastapi_app.ghg_calc.stationary_combustion import calculate_stationary_combustion

ANTHRACITE = {
    "Category": "Coal and Coke",
    "Fuel Type": "Anthracite",
    "Heat Content (HHV)": 25.09,
    "HIV Unit": "mmBtu per short ton",
    "CO2 Factor": 103.69,
    "CO2 Unit": "kg CO2 per mmBtu",
    "CH4 Factor": 11,
    "CH4 Unit": "g CH4 per mmBtu",
    "N2O Factor": 1.6,
    "N20 Unit": "g N2O per mmBtu",
    "CO2 Factor_1": " 2,602 ",
    "CO2 Unit_1": "kg CO2 per short ton",
    "CH4 Factor_1": " 276 ",
    "CH4 Unit_1": "g CH4 per short ton",
    "N2O Factor_1": 40,
    "N2O Unit": "g N2O per short ton",
}

NATURAL_GAS = {
    "Category": "Natural Gas",
    "Fuel Type": "Natural Gas",
    "Heat Content (HHV)": 0.001026,
    "HIV Unit": "mmBtu per scf",
    "CO2 Factor": 53.06,
    "CO2 Unit": "kg CO2 per mmBtu",
    "CH4 Factor": 1,
    "CH4 Unit": "g CH4 per mmBtu",
    "N2O Factor": 0.1,
    "N2O Unit": "g N2O per mmBtu",
    "CO2 Factor_1": 0.05444,
    "CO2 Unit_1": "kg CO2 per scf",
    "CH4 Factor_1": 0.00103,
    "CH4 Unit_1": "g CH4 per scf",
    "N2O Factor_1": 0.0001,
    "N2O Unit_1": "g N2O per scf",
}

DISTILLATE = {
    "Category": " Petroleum Products ",
    "Fuel Type": "Distillate Fuel Oil No. 2",
    "Heat Content (HHV)": 0.138,
    "HIV Unit": "mmBtu per gallon",
    "CO2 Factor": 73.96,
    "CO2 Unit": "kg CO2 per mmBtu",
    "CH4 Factor": 3,
    "CH4 Unit": "g CH4 per mmBtu",
    "N2O Factor": 0.6,
    "N2O Unit": "g N2O per mmBtu",
    "CO2 Factor_1": 10.21,
    "CO2 Unit_1": "kg CO2 per gallon",
    "CH4 Factor_1": 0.41,
    "CH4 Unit_1": "g CH4 per gallon",
    "N2O Factor_1": 0.08,
    "N2O Unit_1": "g N2O per gallon",
}

SHEETS = [
    {
        "publisher": "EPA",
        "dataset_code": "fuel_epa_1",
        "dataset_title": "Fuel EPA 1",
        "version_label": "imported_from_sheet",
        "effective_from": None,
        "effective_to": None,
        "source_notes": "ETL from ref.Fuel EPA 1",
        "rows": [ANTHRACITE],
    },
    {
        "publisher": "EPA",
        "dataset_code": "fuel_epa_2",
        "dataset_title": "Fuel EPA 2",
        "version_label": "imported_from_sheet",
        "effective_from": None,
        "effective_to": None,
        "source_notes": "ETL from ref.Fuel EPA 2",
        "rows": [NATURAL_GAS],
    },
    {
        "publisher": "EPA",
        "dataset_code": "fuel_epa_3",
        "dataset_title": "Fuel EPA 3",
        "version_label": "imported_from_sheet",
        "effective_from": None,
        "effective_to": None,
        "source_notes": "ETL from ref.Fuel EPA 3",
        "rows": [DISTILLATE],
    },
]


def _calc(**overrides):
    payload = {"sheets": SHEETS, "gwp_version": "AR5"}
    payload.update(overrides)
    return calculate_stationary_combustion(**payload)


def test_natural_gas_100_mmbtu():
    result = _calc(fuel="Natural Gas", quantity=100, unit="mmBtu")
    assert result["success"] is True
    assert result["gases"]["co2"] == {
        "mass_kg": "5306",
        "gwp": "1",
        "co2e_kg": "5306",
        "reporting": "scope1",
    }
    assert result["gases"]["ch4"] == {"mass_kg": "0.1", "gwp": "28", "co2e_kg": "2.8"}
    assert result["gases"]["n2o"] == {"mass_kg": "0.01", "gwp": "265", "co2e_kg": "2.65"}
    assert result["total_kg_co2e"] == "5311.45"
    assert result["total_t_co2e"] == "5.31145"
    assert result["factors"]["co2"]["value"] == "53.06"
    assert result["factor_source"]["dataset_code"] == "fuel_epa_2"
    assert result["factor_source"]["version_label"] == "imported_from_sheet"
    assert result["factor_source"]["gwp_version"] == "AR5"
    assert result["factor_source"]["gwp"] == {"CO2": "1", "CH4": "28", "N2O": "265"}


def test_anthracite_1_short_ton_parses_comma_factors():
    result = _calc(fuel="Anthracite", quantity=1, unit="short ton")
    assert result["success"] is True
    assert result["category"] == "Coal and Coke"
    assert result["factors"]["co2"] == {"value": "2602", "unit": "kg CO2 / short ton"}
    assert result["factors"]["ch4"] == {"value": "276", "unit": "g CH4 / short ton"}
    assert result["factors"]["n2o"] == {"value": "40", "unit": "g N2O / short ton"}
    assert result["gases"]["co2"]["mass_kg"] == "2602"
    assert result["gases"]["ch4"] == {"mass_kg": "0.276", "gwp": "28", "co2e_kg": "7.728"}
    assert result["gases"]["n2o"] == {"mass_kg": "0.04", "gwp": "265", "co2e_kg": "10.6"}
    assert result["total_kg_co2e"] == "2620.328"
    assert result["total_t_co2e"] == "2.620328"
    assert result["factor_source"]["dataset_code"] == "fuel_epa_1"


def test_distillate_100_gallons():
    """
    100 * 10.21 kg CO2
    + 100 * 0.41 g CH4 / 1000 * 28
    + 100 * 0.08 g N2O / 1000 * 265
    = 1024.268 kg = 1.024268 t CO2e.

    1.02103268 is that CO2 term in tonnes plus the CH4/N2O term divided by an
    extra 100. The natural-gas and anthracite cases use one gram-to-kilogram
    conversion, so this test follows that same rule.
    """
    result = _calc(fuel="Distillate Fuel Oil No. 2", quantity="100", unit="gallons")
    assert result["success"] is True
    assert result["category"] == "Petroleum Products"
    assert result["unit"] == "gallon"
    assert result["factors"]["co2"]["value"] == "10.21"
    assert result["gases"]["co2"]["co2e_kg"] == "1021"
    assert result["gases"]["ch4"]["co2e_kg"] == "1.148"
    assert result["gases"]["n2o"]["co2e_kg"] == "2.12"
    assert result["total_kg_co2e"] == "1024.268"
    assert result["total_t_co2e"] == "1.024268"
    assert result["factor_source"]["dataset_code"] == "fuel_epa_3"


def test_client_factor_and_total_are_ignored():
    trusted = _calc(fuel="Natural Gas", quantity=100, unit="mmBtu")
    injected = _calc(
        fuel="Natural Gas",
        quantity=100,
        unit="mmBtu",
        factor=1,
        emissions=1,
        emissions_kg=1,
        total_kg_co2e="1",
        total_t_co2e="1",
    )
    assert injected["total_t_co2e"] == trusted["total_t_co2e"]
    assert injected["factors"]["co2"]["value"] == "53.06"


def test_invalid_unit_quantity_fuel_and_gwp_are_rejected():
    assert _calc(fuel="Natural Gas", quantity=100, unit="kg")["success"] is False
    assert _calc(fuel="Natural Gas", quantity=-1, unit="mmBtu")["success"] is False
    assert _calc(fuel="Diesel", quantity=1, unit="gallon")["success"] is False
    assert _calc(fuel="Anthracite", quantity=1, unit="gallon")["success"] is False
    assert _calc(fuel="Natural Gas", quantity=100, unit="mmBtu", gwp_version="AR6")[
        "success"
    ] is False


WOOD = {
    "Category": "Biomass Fuels",
    "Fuel Type": "Wood and Wood Residuals",
    "CO2 Factor": 93.80,
    "CO2 Unit": "kg CO2 per mmBtu",
    "CH4 Factor": 7.2,
    "CH4 Unit": "g CH4 per mmBtu",
    "N2O Factor": 3.6,
    "N2O Unit": "g N2O per mmBtu",
    "CO2 Factor_1": 1640,
    "CO2 Unit_1": "kg CO2 per short ton",
    "CH4 Factor_1": 126,
    "CH4 Unit_1": "g CH4 per short ton",
    "N2O Factor_1": 63,
    "N2O Unit_1": "g N2O per short ton",
}

PEAT = {
    "Category": "Biomass Fuels",
    "Fuel Type": "Peat",
    "CO2 Factor": 111.84,
    "CO2 Unit": "kg CO2 per mmBtu",
    "CH4 Factor": 32,
    "CH4 Unit": "g CH4 per mmBtu",
    "N2O Factor": 4.2,
    "N2O Unit": "g N2O per mmBtu",
}

MIXED_INDUSTRIAL = {
    "Category": "Coal and Coke",
    "Fuel Type": "Mixed (Industrial Sector)",
    "CO2 Factor": 94.67,
    "CO2 Unit": "kg CO2 per mmBtu",
    "CH4 Factor": 11,
    "CH4 Unit": "g CH4 per mmBtu",
    "N2O Factor": 1.6,
    "N2O Unit": "g N2O per mmBtu",
}

MSW = {
    "Category": "Biomass Fuels",
    "Fuel Type": "Municipal Solid Waste",
    "CO2 Factor": 90.7,
    "CO2 Unit": "kg CO2 per mmBtu",
    "CH4 Factor": 32,
    "CH4 Unit": "g CH4 per mmBtu",
    "N2O Factor": 4.2,
    "N2O Unit": "g N2O per mmBtu",
}


def _with_rows(*rows):
    sheets = [dict(sheet) for sheet in SHEETS]
    sheets.append(
        {
            "publisher": "EPA",
            "dataset_code": "fuel_epa_1",
            "dataset_title": "Fuel EPA 1",
            "version_label": "imported_from_sheet",
            "rows": list(rows),
        }
    )
    return sheets


def test_natural_gas_mmscf_uses_unrounded_hhv_product():
    result = _calc(fuel="Natural Gas", quantity=1, unit="MMSCF")
    assert result["success"] is True
    assert result["factors"]["co2"]["value"] == "54439.56"
    assert result["factors"]["ch4"]["value"] == "1026"
    assert result["factors"]["n2o"]["value"] == "102.6"


def test_natural_gas_keeps_co2_in_scope_1_and_records_zero_biogenic():
    result = _calc(fuel="Natural Gas", quantity=100, unit="mmBtu")
    assert result["total_t_co2e"] == "5.31145"
    assert result["biogenic_co2_t"] == "0"
    assert result["accounting"]["treatment"] == "fossil_scope1"
    assert result["accounting"]["version"] == "epa_stationary_biogenic_v1"
    assert result["gases"]["co2"]["reporting"] == "scope1"
    assert result["factor_source"]["gwp_version"] == "AR5"


def test_wood_reports_biogenic_co2_outside_scope_1():
    result = _calc(fuel="Wood and Wood Residuals", quantity=1, unit="short ton", sheets=_with_rows(WOOD))
    assert result["success"] is True
    assert result["gases"]["co2"]["mass_kg"] == "1640"
    assert result["gases"]["co2"]["reporting"] == "biogenic_outside_scope1"
    assert result["gases"]["ch4"]["co2e_kg"] == "3.528"
    assert result["gases"]["n2o"]["co2e_kg"] == "16.695"
    assert result["total_kg_co2e"] == "20.223"
    assert result["total_t_co2e"] == "0.020223"
    assert result["biogenic_co2_t"] == "1.64"
    assert result["accounting"]["treatment"] == "biogenic_co2_outside_scope1"
    assert result["total_t_co2e"] != "1.660223"


def test_peat_co2_stays_in_scope_1():
    result = _calc(fuel="Peat", quantity=1, unit="mmBtu", sheets=_with_rows(PEAT))
    assert result["success"] is True
    assert result["category"] == "Biomass Fuels"
    assert result["accounting"]["treatment"] == "peat_fossil_scope1"
    assert result["gases"]["co2"]["mass_kg"] == "111.84"
    assert result["gases"]["co2"]["reporting"] == "scope1"
    assert result["biogenic_co2_t"] == "0"
    assert result["total_kg_co2e"] == "113.849"
    assert result["total_t_co2e"] == "0.113849"


def test_mixed_industrial_coal_is_fossil_not_a_biogenic_split():
    result = _calc(
        fuel="Mixed (Industrial Sector)",
        quantity=1,
        unit="mmBtu",
        sheets=_with_rows(MIXED_INDUSTRIAL),
    )
    assert result["success"] is True
    assert result["accounting"]["treatment"] == "fossil_scope1"
    assert result["biogenic_co2_t"] == "0"
    assert result["gases"]["co2"]["co2e_kg"] == "94.67"
    assert result["total_kg_co2e"] == "95.402"


def test_municipal_solid_waste_is_flagged_instead_of_split():
    result = _calc(fuel="Municipal Solid Waste", quantity=1, unit="mmBtu", sheets=_with_rows(MSW))
    assert result["success"] is False
    assert result["review_required"] is True
    assert result["total_t_co2e"] is None
    assert result["biogenic_co2_t"] is None
    assert result["gases"]["co2"]["mass_kg"] == "90.7"
    assert result["accounting"]["treatment"] == "needs_review"
