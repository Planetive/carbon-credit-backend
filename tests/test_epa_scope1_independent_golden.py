"""
Independent golden checks for the three live EPA Scope 1 engines.

Expected totals below were calculated by hand from EPA GHG Emission Factors
Hub, last modified 15 January 2025, Tables 1, 2, 3, 4, 5, 11, and 12, and
from AR5 GWPs printed in that hub (CO2 1, CH4 28, N2O 265). They are not
produced by calling the engine and copying its output.

The sheet rows in this file are copies of those published numbers, passed in
as data. They are not a read of the live factor database.
"""

from fastapi_app.ghg_calc.mobile_combustion import calculate_mobile_combustion
from fastapi_app.ghg_calc.refrigerant_leakage import calculate_refrigerant_leakage
from fastapi_app.ghg_calc.stationary_combustion import calculate_stationary_combustion

DATASET_ID = "22222222-2222-2222-2222-222222222222"


def _stationary_row(**fields):
    return fields


def _stationary_sheets(*rows):
    return [
        {
            "publisher": "EPA",
            "dataset_code": "fuel_epa_hub_2025",
            "dataset_title": "EPA GHG Emission Factors Hub Table 1",
            "version_label": "2025-01-15",
            "rows": list(rows),
        }
    ]


NATURAL_GAS = _stationary_row(
    **{
        "Category": "Natural Gas",
        "Fuel Type": "Natural Gas",
        "Heat Content (HHV)": "0.001026",
        "HIV Unit": "mmBtu per scf",
        "CO2 Factor": "53.06",
        "CO2 Unit": "kg CO2 per mmBtu",
        "CH4 Factor": "1.0",
        "CH4 Unit": "g CH4 per mmBtu",
        "N2O Factor": "0.10",
        "N2O Unit": "g N2O per mmBtu",
        "CO2 Factor_1": "0.05444",
        "CO2 Unit_1": "kg CO2 per scf",
        "CH4 Factor_1": "0.00103",
        "CH4 Unit_1": "g CH4 per scf",
        "N2O Factor_1": "0.00010",
        "N2O Unit_1": "g N2O per scf",
    }
)

DISTILLATE = _stationary_row(
    **{
        "Category": "Petroleum Products",
        "Fuel Type": "Distillate Fuel Oil No. 2",
        "Heat Content (HHV)": "0.138",
        "HIV Unit": "mmBtu per gallon",
        "CO2 Factor": "73.96",
        "CO2 Unit": "kg CO2 per mmBtu",
        "CH4 Factor": "3.0",
        "CH4 Unit": "g CH4 per mmBtu",
        "N2O Factor": "0.60",
        "N2O Unit": "g N2O per mmBtu",
        "CO2 Factor_1": "10.21",
        "CO2 Unit_1": "kg CO2 per gallon",
        "CH4 Factor_1": "0.41",
        "CH4 Unit_1": "g CH4 per gallon",
        "N2O Factor_1": "0.08",
        "N2O Unit_1": "g N2O per gallon",
    }
)

ANTHRACITE = _stationary_row(
    **{
        "Category": "Coal and Coke",
        "Fuel Type": "Anthracite",
        "Heat Content (HHV)": "25.09",
        "HIV Unit": "mmBtu per short ton",
        "CO2 Factor": "103.69",
        "CO2 Unit": "kg CO2 per mmBtu",
        "CH4 Factor": "11",
        "CH4 Unit": "g CH4 per mmBtu",
        "N2O Factor": "1.6",
        "N20 Unit": "g N2O per mmBtu",
        "CO2 Factor_1": "2,602",
        "CO2 Unit_1": "kg CO2 per short ton",
        "CH4 Factor_1": "276",
        "CH4 Unit_1": "g CH4 per short ton",
        "N2O Factor_1": "40",
        "N2O Unit": "g N2O per short ton",
    }
)

WOOD = _stationary_row(
    **{
        "Category": "Biomass Fuels - Solid",
        "Fuel Type": "Wood and Wood Residuals",
        "Heat Content (HHV)": "17.48",
        "HIV Unit": "mmBtu per short ton",
        "CO2 Factor": "93.80",
        "CO2 Unit": "kg CO2 per mmBtu",
        "CH4 Factor": "7.2",
        "CH4 Unit": "g CH4 per mmBtu",
        "N2O Factor": "3.6",
        "N2O Unit": "g N2O per mmBtu",
        "CO2 Factor_1": "1,640",
        "CO2 Unit_1": "kg CO2 per short ton",
        "CH4 Factor_1": "126",
        "CH4 Unit_1": "g CH4 per short ton",
        "N2O Factor_1": "63",
        "N2O Unit_1": "g N2O per short ton",
    }
)

PEAT = _stationary_row(
    **{
        "Category": "Biomass Fuels - Solid",
        "Fuel Type": "Peat",
        "Heat Content (HHV)": "8.00",
        "HIV Unit": "mmBtu per short ton",
        "CO2 Factor": "111.84",
        "CO2 Unit": "kg CO2 per mmBtu",
        "CH4 Factor": "32",
        "CH4 Unit": "g CH4 per mmBtu",
        "N2O Factor": "4.2",
        "N2O Unit": "g N2O per mmBtu",
        "CO2 Factor_1": "895",
        "CO2 Unit_1": "kg CO2 per short ton",
        "CH4 Factor_1": "256",
        "CH4 Unit_1": "g CH4 per short ton",
        "N2O Factor_1": "34",
        "N2O Unit_1": "g N2O per short ton",
    }
)

MSW = _stationary_row(
    **{
        "Category": "Other Fuels - Solid",
        "Fuel Type": "Municipal Solid Waste",
        "CO2 Factor": "90.70",
        "CO2 Unit": "kg CO2 per mmBtu",
        "CH4 Factor": "32",
        "CH4 Unit": "g CH4 per mmBtu",
        "N2O Factor": "4.2",
        "N2O Unit": "g N2O per mmBtu",
    }
)


def _stationary(fuel, quantity, unit, sheets):
    return calculate_stationary_combustion(
        fuel=fuel,
        quantity=quantity,
        unit=unit,
        sheets=sheets,
        gwp_version="AR5",
        total_t_co2e="999",
        factor="0",
    )


def test_natural_gas_100_mmbtu_matches_hand_calculation():
    # 100 * 53.06 = 5306 kg CO2
    # 100 * 1.0 g = 0.1 kg CH4 * 28 = 2.8
    # 100 * 0.10 g = 0.01 kg N2O * 265 = 2.65
    # Scope 1 = 5311.45 kg = 5.31145 t
    result = _stationary("Natural Gas", "100", "mmBtu", _stationary_sheets(NATURAL_GAS))
    assert result["success"] is True
    assert result["gases"]["co2"]["mass_kg"] == "5306"
    assert result["gases"]["ch4"]["mass_kg"] == "0.1"
    assert result["gases"]["n2o"]["mass_kg"] == "0.01"
    assert result["gases"]["co2"]["reporting"] == "scope1"
    assert result["total_kg_co2e"] == "5311.45"
    assert result["total_t_co2e"] == "5.31145"
    assert result["biogenic_co2_t"] == "0"
    assert result["accounting"]["version"] == "epa_stationary_biogenic_v1"
    assert result["accounting"]["gwp_version"] == "AR5"
    assert result["total_t_co2e"] != "999"


def test_distillate_uses_printed_per_gallon_factors():
    # 10 gal * 10.21 = 102.1 kg CO2
    # 10 * 0.41 g = 0.0041 kg CH4 * 28 = 0.1148
    # 10 * 0.08 g = 0.0008 kg N2O * 265 = 0.212
    # Scope 1 = 102.4268 kg = 0.1024268 t
    result = _stationary(
        "Distillate Fuel Oil No. 2",
        "10",
        "gallon",
        _stationary_sheets(DISTILLATE),
    )
    assert result["success"] is True
    assert result["gases"]["co2"]["mass_kg"] == "102.1"
    assert result["factors"]["co2"]["value"] == "10.21"
    assert result["factors"]["ch4"]["value"] == "0.41"
    assert result["factors"]["n2o"]["value"] == "0.08"
    assert result["total_kg_co2e"] == "102.4268"
    assert result["total_t_co2e"] == "0.1024268"
    assert result["biogenic_co2_t"] == "0"


def test_anthracite_short_ton_uses_printed_solid_factors():
    # 2602 kg CO2
    # 276 g CH4 = 0.276 kg * 28 = 7.728
    # 40 g N2O = 0.040 kg * 265 = 10.6
    # Scope 1 = 2620.328 kg = 2.620328 t
    result = _stationary("Anthracite", "1", "short ton", _stationary_sheets(ANTHRACITE))
    assert result["success"] is True
    assert result["gases"]["co2"]["mass_kg"] == "2602"
    assert result["total_kg_co2e"] == "2620.328"
    assert result["total_t_co2e"] == "2.620328"
    assert result["accounting"]["treatment"] == "fossil_scope1"


def test_wood_keeps_biogenic_co2_out_of_scope1():
    # Printed short-ton row: 1640 kg CO2, 126 g CH4, 63 g N2O
    # CH4 CO2e = 0.126 * 28 = 3.528
    # N2O CO2e = 0.063 * 265 = 16.695
    # Scope 1 = 20.223 kg = 0.020223 t
    # Biogenic CO2 = 1.64 t
    result = _stationary(
        "Wood and Wood Residuals",
        "1",
        "short ton",
        _stationary_sheets(WOOD),
    )
    assert result["success"] is True
    assert result["gases"]["co2"]["mass_kg"] == "1640"
    assert result["gases"]["co2"]["reporting"] == "biogenic_outside_scope1"
    assert result["total_t_co2e"] == "0.020223"
    assert result["biogenic_co2_kg"] == "1640"
    assert result["biogenic_co2_t"] == "1.64"
    assert result["accounting"]["treatment"] == "biogenic_co2_outside_scope1"


def test_peat_co2_stays_in_scope1():
    # 895 + 0.256 * 28 + 0.034 * 265 = 911.178 kg = 0.911178 t
    result = _stationary("Peat", "1", "short ton", _stationary_sheets(PEAT))
    assert result["success"] is True
    assert result["gases"]["co2"]["reporting"] == "scope1"
    assert result["total_kg_co2e"] == "911.178"
    assert result["total_t_co2e"] == "0.911178"
    assert result["biogenic_co2_t"] == "0"
    assert result["accounting"]["treatment"] == "peat_fossil_scope1"


def test_municipal_solid_waste_fails_closed():
    result = _stationary("Municipal Solid Waste", "1", "mmBtu", _stationary_sheets(MSW))
    assert result["success"] is False
    assert result["review_required"] is True
    assert result["total_t_co2e"] is None


def test_unknown_fuel_and_bad_unit_fail_closed():
    sheets = _stationary_sheets(NATURAL_GAS)
    missing = _stationary("Unobtainium", "1", "mmBtu", sheets)
    assert missing["success"] is False
    assert missing["total_t_co2e"] is None
    bad_unit = _stationary("Natural Gas", "1", "therm", sheets)
    assert bad_unit["success"] is False
    assert bad_unit["total_kg_co2e"] is None


def _mobile_sheets():
    return [
        {
            "dataset_code": "mobile_combustion",
            "publisher": "EPA",
            "title": "Hub Table 2",
            "version_label": "2025-01-15",
            "rows": [
                {"Fuel Type": "Motor Gasoline", "Unit": "gallon", "kg CO2 per unit": "8.78"},
                {"Fuel Type": "Diesel Fuel", "Unit": "gallon", "kg CO2 per unit": "10.21", "_factor_row_id": "table2-diesel"},
                {
                    "Fuel Type": "Compressed Natural Gas (CNG)",
                    "Unit": "scf",
                    "_factor_row_id": "table2-cng",
                    "kg CO2 per unit": "0.05444",
                },
                {"Fuel Type": "Biodiesel (100%)", "Unit": "gallon", "kg CO2 per unit": "9.45"},
            ],
        },
        {
            "dataset_code": "on_road_gasoline",
            "publisher": "EPA",
            "title": "Hub Table 3",
            "version_label": "2025-01-15",
            "rows": [
                {
                    "Vehicle Type": "Passenger Cars",
                    "Model Year": "2020",
                    "CH4 Factor (g CH4 / vehicle-mile)": "0.0050",
                    "N2O Factor (g N2O / vehicle-mile)": "0.0014",
                }
            ],
        },
        {
            "dataset_code": "on_road_diesel_alt_fuel",
            "publisher": "EPA",
            "title": "Hub Table 4",
            "version_label": "2025-01-15",
            "rows": [
                {
                    "Vehicle Type": "Passenger Cars",
                    "Fuel Type": "Diesel",
                    "Model Year": "2007-2022",
                    "_factor_row_id": "table4-diesel",
                    "CH4 Factor (g CH4 / vehicle-mile)": "0.0302",
                    "N2O Factor (g N2O / vehicle-mile)": "0.0192",
                },
                {
                    "Vehicle Type": "Light-Duty Cars",
                    "Fuel Type": "CNG",
                    "_factor_row_id": "table4-cng",
                    "CH4 Factor (g CH4 / vehicle-mile)": "0.1200",
                    "N2O Factor (g N2O / vehicle-mile)": "0.0040",
                },
            ],
        },
        {
            "dataset_code": "non_road_vehicle",
            "publisher": "EPA",
            "title": "Hub Table 5",
            "version_label": "2025-01-15",
            "rows": [
                {
                    "Vehicle Type": "Agricultural Equipment",
                    "Fuel Type": "Diesel Equipment",
                    "_factor_row_id": "table5-diesel-equipment",
                    "CH4 Factor (g CH4 / gallon)": "1.26",
                    "N2O Factor (g N2O / gallon)": "1.07",
                }
            ],
        },
    ]


def _mobile(**overrides):
    payload = dict(
        road_class="on_road",
        vehicle_type="Passenger Cars",
        fuel_type="Motor Gasoline",
        fuel_quantity="10",
        fuel_unit="gallon",
        distance="100",
        distance_unit="mile",
        model_year=2020,
        sheets=_mobile_sheets(),
        gwp_version="AR5",
        total_t_co2e="999",
    )
    payload.update(overrides)
    return calculate_mobile_combustion(**payload)


def test_on_road_gasoline_2020_passenger_car():
    # 10 gal * 8.78 = 87.8 kg CO2
    # 100 mi * 0.0050 g = 0.0005 kg CH4 * 28 = 0.014
    # 100 mi * 0.0014 g = 0.00014 kg N2O * 265 = 0.0371
    # Scope 1 = 87.8511 kg = 0.0878511 t
    result = _mobile()
    assert result["success"] is True
    assert result["gases"]["co2"]["mass_kg"] == "87.8"
    assert result["gases"]["ch4"]["co2e_kg"] == "0.014"
    assert result["gases"]["n2o"]["co2e_kg"] == "0.0371"
    assert result["total_kg_co2e"] == "87.8511"
    assert result["total_t_co2e"] == "0.0878511"
    assert result["biogenic_co2_t"] == "0"
    assert result["accounting"]["version"] == "epa_mobile_biogenic_v1"
    assert result["factors"]["co2"]["dataset_code"] == "mobile_combustion"
    assert result["factors"]["co2"]["sheet_fuel"] == "Motor Gasoline"
    assert result["factors"]["ch4"]["dataset_code"] == "on_road_gasoline"
    assert "sheet_fuel" not in result["factors"]["ch4"]
    assert result["total_t_co2e"] != "999"


def test_on_road_diesel_passenger_car_2007_2022():
    # 1 gal * 10.21 = 10.21 kg CO2
    # 10 mi * 0.0302 g * 28 / 1000 = 0.008456
    # 10 mi * 0.0192 g * 265 / 1000 = 0.05088
    # Scope 1 = 10.269336 kg = 0.010269336 t
    result = _mobile(
        fuel_type="Diesel Fuel",
        fuel_quantity="1",
        distance="10",
        model_year=2010,
    )
    assert result["success"] is True
    assert result["gases"]["co2"]["mass_kg"] == "10.21"
    assert result["total_kg_co2e"] == "10.269336"
    assert result["total_t_co2e"] == "0.010269336"
    assert result["factors"]["ch4"]["value"] == "0.0302"
    assert result["factors"]["co2"]["sheet_fuel"] == "Diesel Fuel"
    assert result["factors"]["co2"]["factor_row_id"] == "table2-diesel"
    assert result["factors"]["ch4"]["sheet_fuel"] == "Diesel"
    assert result["factors"]["ch4"]["factor_row_id"] == "table4-diesel"


def test_non_road_diesel_agricultural_equipment():
    # Hub Table 5 diesel equipment: 1.26 g CH4/gal and 1.07 g N2O/gal
    # 5 * 10.21 = 51.05
    # 5 * 1.26 g * 28 / 1000 = 0.1764
    # 5 * 1.07 g * 265 / 1000 = 1.41775
    # Scope 1 = 52.64415 kg = 0.05264415 t
    result = _mobile(
        road_class="non_road",
        vehicle_type="Agricultural Equipment",
        fuel_type="Diesel Fuel",
        fuel_quantity="5",
        distance=None,
        model_year=None,
    )
    assert result["success"] is True
    assert result["gases"]["co2"]["mass_kg"] == "51.05"
    assert result["factors"]["ch4"]["unit"] == "g / gallon"
    assert result["total_kg_co2e"] == "52.64415"
    assert result["total_t_co2e"] == "0.05264415"
    assert result["factors"]["co2"]["sheet_fuel"] == "Diesel Fuel"
    assert result["factors"]["ch4"]["sheet_fuel"] == "Diesel Equipment"
    assert result["factors"]["ch4"]["factor_row_id"] == "table5-diesel-equipment"


def test_cng_standard_cubic_feet_when_fuel_names_agree():
    # 1000 scf * 0.05444 = 54.44 kg CO2
    # 50 mi * 0.1200 g * 28 / 1000 = 0.168
    # 50 mi * 0.0040 g * 265 / 1000 = 0.053
    # Scope 1 = 54.661 kg = 0.054661 t
    result = _mobile(
        vehicle_type="Light-Duty Cars",
        fuel_type="Compressed Natural Gas (CNG)",
        fuel_quantity="1000",
        fuel_unit="scf",
        distance="50",
        model_year=None,
    )
    assert result["success"] is True
    assert result["gases"]["co2"]["mass_kg"] == "54.44"
    assert result["fuel_unit"] == "scf"
    assert result["total_kg_co2e"] == "54.661"
    assert result["total_t_co2e"] == "0.054661"
    assert result["factors"]["co2"]["sheet_fuel"] == "Compressed Natural Gas (CNG)"
    assert result["factors"]["co2"]["factor_row_id"] == "table2-cng"
    assert result["factors"]["ch4"]["sheet_fuel"] == "CNG"
    assert result["factors"]["ch4"]["factor_row_id"] == "table4-cng"


def test_hub_cng_short_name_uses_the_table_2_row():
    result = _mobile(
        vehicle_type="Light-Duty Cars",
        fuel_type="CNG",
        fuel_quantity="1000",
        fuel_unit="scf",
        distance="50",
        model_year=None,
    )
    assert result["success"] is True
    assert result["total_t_co2e"] == "0.054661"
    assert result["factors"]["co2"]["factor_row_id"] == "table2-cng"
    assert result["factors"]["ch4"]["sheet_fuel"] == "CNG"
    assert result["fuel"] == "CNG"


def test_similar_fuel_names_are_not_mapped():
    lng = _mobile(
        vehicle_type="Light-Duty Cars",
        fuel_type="LNG",
        fuel_quantity="1000",
        fuel_unit="scf",
        distance="50",
        model_year=None,
    )
    assert lng["success"] is False
    assert lng["total_t_co2e"] is None
    off_road_name = _mobile(
        road_class="non_road",
        vehicle_type="Agricultural Equipment",
        fuel_type="Diesel Off-Road Trucks",
        fuel_quantity="5",
        distance=None,
        model_year=None,
    )
    assert off_road_name["success"] is False
    assert off_road_name["total_t_co2e"] is None
    sheets = _mobile_sheets()
    sheets[2]["rows"].append(
        {
            "Vehicle Type": "Light-Duty Cars",
            "Fuel Type": "Compressed Natural Gas (CNG)",
            "CH4 Factor (g CH4 / vehicle-mile)": "0.1200",
            "N2O Factor (g N2O / vehicle-mile)": "0.0040",
        }
    )
    duplicate = _mobile(
        vehicle_type="Light-Duty Cars",
        fuel_type="CNG",
        fuel_quantity="1000",
        fuel_unit="scf",
        distance="50",
        model_year=None,
        sheets=sheets,
    )
    assert duplicate["success"] is False
    assert duplicate["total_t_co2e"] is None


def test_pure_biodiesel_and_ethanol_map_without_accepting_blends():
    sheets = _mobile_sheets()
    for row in sheets[0]["rows"]:
        if row["Fuel Type"] == "Biodiesel (100%)":
            row["_factor_row_id"] = "table2-biodiesel"
    sheets[0]["rows"].append(
        {
            "Fuel Type": "Ethanol (100%)",
            "Unit": "gallon",
            "kg CO2 per unit": "5.75",
            "_factor_row_id": "table2-ethanol",
        }
    )
    sheets[2]["rows"].extend(
        [
            {
                "Vehicle Type": "Light-Duty Cars",
                "Fuel Type": "Biodiesel",
                "_factor_row_id": "table4-biodiesel",
                "CH4 Factor (g CH4 / vehicle-mile)": "0.0300",
                "N2O Factor (g N2O / vehicle-mile)": "0.0010",
            },
            {
                "Vehicle Type": "Light-Duty Cars",
                "Fuel Type": "Ethanol",
                "_factor_row_id": "table4-ethanol",
                "CH4 Factor (g CH4 / vehicle-mile)": "0.0130",
                "N2O Factor (g N2O / vehicle-mile)": "0.0050",
            },
        ]
    )
    biodiesel = _mobile(
        vehicle_type="Light-Duty Cars",
        fuel_type="Biodiesel (100%)",
        fuel_quantity="1",
        distance="10",
        model_year=None,
        sheets=sheets,
    )
    # CO2 9.45 kg is biogenic. Scope 1 is CH4 0.0084 + N2O 0.00265 = 0.01105 kg.
    assert biodiesel["success"] is True
    assert biodiesel["gases"]["co2"]["reporting"] == "biogenic_outside_scope1"
    assert biodiesel["gases"]["co2"]["mass_kg"] == "9.45"
    assert biodiesel["total_kg_co2e"] == "0.01105"
    assert biodiesel["biogenic_co2_t"] == "0.00945"
    assert biodiesel["factors"]["co2"]["sheet_fuel"] == "Biodiesel (100%)"
    assert biodiesel["factors"]["co2"]["factor_row_id"] == "table2-biodiesel"
    assert biodiesel["factors"]["ch4"]["sheet_fuel"] == "Biodiesel"
    assert biodiesel["factors"]["ch4"]["factor_row_id"] == "table4-biodiesel"

    ethanol = _mobile(
        vehicle_type="Light-Duty Cars",
        fuel_type="Ethanol (100%)",
        fuel_quantity="1",
        distance="10",
        model_year=None,
        sheets=sheets,
    )
    assert ethanol["success"] is True
    assert ethanol["total_kg_co2e"] == "0.01689"
    assert ethanol["factors"]["co2"]["factor_row_id"] == "table2-ethanol"
    assert ethanol["factors"]["ch4"]["sheet_fuel"] == "Ethanol"
    assert ethanol["factors"]["ch4"]["factor_row_id"] == "table4-ethanol"

    blend = _mobile(fuel_type="B20", sheets=sheets)
    assert blend["success"] is False
    assert blend["review_required"] is True
    e85 = _mobile(fuel_type="E85", sheets=sheets)
    assert e85["success"] is False
    assert e85["review_required"] is True


def test_lng_and_lpg_use_their_own_gallon_factors_and_not_cng():
    sheets = _mobile_sheets()
    sheets[0]["rows"].extend(
        [
            {
                "Fuel Type": "Liquefied Natural Gas (LNG)",
                "Unit": "gallon",
                "kg CO2 per unit": "4.50",
                "_factor_row_id": "table2-lng",
            },
            {
                "Fuel Type": "Liquefied Petroleum Gases (LPG)",
                "Unit": "gallon",
                "kg CO2 per unit": "5.68",
                "_factor_row_id": "table2-lpg",
            },
        ]
    )
    sheets[2]["rows"].extend(
        [
            {
                "Vehicle Type": "Light-Duty Trucks",
                "Fuel Type": "LNG",
                "_factor_row_id": "table4-lng",
                "CH4 Factor (g CH4 / vehicle-mile)": "0.1300",
                "N2O Factor (g N2O / vehicle-mile)": "0.0050",
            },
            {
                "Vehicle Type": "Light-Duty Cars",
                "Fuel Type": "LPG",
                "_factor_row_id": "table4-lpg",
                "CH4 Factor (g CH4 / vehicle-mile)": "0.0120",
                "N2O Factor (g N2O / vehicle-mile)": "0.0040",
            },
        ]
    )
    lng = _mobile(
        vehicle_type="Light-Duty Trucks",
        fuel_type="LNG",
        fuel_quantity="1",
        fuel_unit="gallon",
        distance="10",
        model_year=None,
        sheets=sheets,
    )
    # 4.50 + 10 mi * 0.1300 g * 28 / 1000 + 10 mi * 0.0050 g * 265 / 1000 = 4.54965
    assert lng["success"] is True
    assert lng["fuel_unit"] == "gallon"
    assert lng["distance_unit"] == "mile"
    assert lng["total_kg_co2e"] == "4.54965"
    assert lng["factors"]["co2"]["sheet_fuel"] == "Liquefied Natural Gas (LNG)"
    assert lng["factors"]["co2"]["factor_row_id"] == "table2-lng"
    assert lng["factors"]["ch4"]["sheet_fuel"] == "LNG"
    assert lng["factors"]["ch4"]["factor_row_id"] == "table4-lng"
    assert lng["factors"]["co2"]["factor_row_id"] != "table2-cng"

    lpg = _mobile(
        vehicle_type="Light-Duty Cars",
        fuel_type="Liquefied Petroleum Gases (LPG)",
        fuel_quantity="1",
        distance="10",
        model_year=None,
        sheets=sheets,
    )
    assert lpg["success"] is True
    assert lpg["factors"]["ch4"]["sheet_fuel"] == "LPG"
    assert lpg["factors"]["ch4"]["factor_row_id"] == "table4-lpg"
    assert lpg["factors"]["co2"]["factor_row_id"] == "table2-lpg"

    methanol = _mobile(
        vehicle_type="Medium- and Heavy-Duty Vehicles",
        fuel_type="Methanol",
        fuel_quantity="1",
        distance="10",
        model_year=None,
        sheets=sheets,
    )
    assert methanol["success"] is False
    assert methanol["total_t_co2e"] is None


def test_diesel_off_road_trucks_are_not_used_as_diesel_equipment():
    sheets = _mobile_sheets()
    sheets[3]["rows"].append(
        {
            "Vehicle Type": "Agricultural Equipment",
            "Fuel Type": "Diesel Off-Road Trucks",
            "_factor_row_id": "table5-off-road-trucks",
            "CH4 Factor (g CH4 / gallon)": "0.92",
            "N2O Factor (g N2O / gallon)": "0.56",
        }
    )
    equipment = _mobile(
        road_class="non_road",
        vehicle_type="Agricultural Equipment",
        fuel_type="Diesel Fuel",
        fuel_quantity="5",
        distance=None,
        model_year=None,
        sheets=sheets,
    )
    assert equipment["success"] is True
    assert equipment["factors"]["ch4"]["factor_row_id"] == "table5-diesel-equipment"
    assert equipment["factors"]["ch4"]["value"] == "1.26"
    assert equipment["total_t_co2e"] == "0.05264415"
    named = _mobile(
        road_class="non_road",
        vehicle_type="Agricultural Equipment",
        fuel_type="Diesel Off-Road Trucks",
        fuel_quantity="5",
        distance=None,
        model_year=None,
        sheets=sheets,
    )
    assert named["success"] is False
    assert named["total_t_co2e"] is None


def test_mobile_validation_fails_closed():
    missing_distance = _mobile(distance=None)
    assert missing_distance["success"] is False
    bad_year = _mobile(model_year=1999)
    assert bad_year["success"] is False
    assert "1999" in bad_year["error"]
    scf_off_road = _mobile(
        road_class="non_road",
        vehicle_type="Agricultural Equipment",
        fuel_type="Compressed Natural Gas (CNG)",
        fuel_quantity="100",
        fuel_unit="scf",
        distance=None,
        model_year=None,
    )
    assert scf_off_road["success"] is False
    blend = _mobile(fuel_type="B20")
    assert blend["success"] is False
    assert blend["review_required"] is True
    assert blend["total_t_co2e"] is None


def _refrigerant_sheet():
    def row(name, gwp, composition, row_id):
        return {
            "ASHRAE #": name,
            "100-year GWP": gwp,
            "Blend Composition": composition,
            "_factor_row_id": row_id,
            "_factor_dataset_id": DATASET_ID,
            "kg_co2e": "1",
        }

    return [
        {
            "dataset_code": "epa_refrigerant_gwp",
            "dataset_id": DATASET_ID,
            "publisher": "EPA",
            "title": "Hub Table 12",
            "version_label": "2025-01-15",
            "is_active": True,
            "rows": [
                row("R-404A", "3,943", "44% HFC-125, 4% HFC-134a, 52% HFC-143a", "row-404a"),
                row("R-407C", "1,624", "23% HFC-32, 25% HFC-125, 52% HFC-134a", "row-407c"),
            ],
        }
    ]


def _refrigerant(**overrides):
    payload = dict(
        method="leakage_record",
        gas="HFC-134a",
        leakage_kg="2",
        sheets=_refrigerant_sheet(),
        gwp="1",
        emissions_tco2e="999",
    )
    payload.update(overrides)
    return calculate_refrigerant_leakage(**payload)


def test_hfc_134a_measured_leak_uses_table_11_gwp():
    # 2 kg * 1300 / 1000 = 2.6 t CO2e
    result = _refrigerant(gas="R-134a")
    assert result["success"] is True
    assert result["refrigerant"] == "HFC-134a"
    assert result["gwp"] == "1300"
    assert result["leakage_kg"] == "2"
    assert result["emissions_tco2e"] == "2.6"
    assert result["emissions_tco2e"] != "999"
    assert result["dataset_code"] is None
    assert "Table 11" in result["factor_provenance"]


def test_r404a_measured_and_r407c_estimated():
    # 1 kg * 3943 / 1000 = 3.943 t
    measured = _refrigerant(gas="R-404A", leakage_kg="1")
    assert measured["success"] is True
    assert measured["gwp"] == "3943"
    assert measured["emissions_tco2e"] == "3.943"
    assert measured["dataset_code"] == "epa_refrigerant_gwp"
    assert measured["factor_row_id"] == "row-404a"
    # 10 kg * 5% = 0.5 kg * 1624 / 1000 = 0.812 t
    estimated = _refrigerant(
        method="estimated_leakage",
        gas="R-407C",
        leakage_kg=None,
        charge_kg="10",
        leakage_rate_percent="5",
        equipment_type="chiller",
    )
    assert estimated["success"] is True
    assert estimated["leakage_kg"] == "0.5"
    assert estimated["leakage_rate_source"] == "user_assumption"
    assert estimated["gwp"] == "1624"
    assert estimated["emissions_tco2e"] == "0.812"


def test_refrigerant_invalid_inputs_fail_closed():
    refused = _refrigerant(gas="R-22", leakage_kg="1")
    assert refused["success"] is False
    assert refused["emissions_tco2e"] is None
    missing_sheet = _refrigerant(gas="R-404A", leakage_kg="1", sheets=[])
    assert missing_sheet["success"] is False
    assert missing_sheet["emissions_tco2e"] is None
    blank_rate = _refrigerant(
        method="estimated_leakage",
        gas="R-407C",
        leakage_kg=None,
        charge_kg="10",
        leakage_rate_percent=None,
    )
    assert blank_rate["success"] is False
    assert blank_rate["emissions_tco2e"] is None
    zero_gwp_row = _refrigerant_sheet()
    zero_gwp_row[0]["rows"][0]["100-year GWP"] = "0"
    zero = _refrigerant(gas="R-404A", leakage_kg="1", sheets=zero_gwp_row)
    assert zero["success"] is False
    assert zero["emissions_tco2e"] is None
