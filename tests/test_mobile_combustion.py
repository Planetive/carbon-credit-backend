"""EPA mobile combustion engine. Sheet rows are fixtures, not production factors."""

from decimal import Decimal

from fastapi_app.ghg_calc.mobile_combustion import calculate_mobile_combustion

CO2_ROWS = [
    {"Fuel Type": "Motor Gasoline", "Unit": "gallon", "kg CO2 per unit": "8.78"},
    {"Fuel Type": "Diesel Fuel", "Unit": "gallon", "kg CO2 per unit": "10.21"},
    {"Fuel Type": "Biodiesel (100%)", "Unit": "gallon", "kg CO2 per unit": "9.45"},
    {"Fuel Type": "Ethanol (100%)", "Unit": "gallon", "kg CO2 per unit": "5.75"},
    {"Fuel Type": "Compressed Natural Gas", "Unit": "scf", "kg CO2 per unit": "0.05444"},
    {"Fuel Type": "B20", "Unit": "gallon", "kg CO2 per unit": "10.01"},
    {"Fuel Type": "E85", "Unit": "gallon", "kg CO2 per unit": "6.10"},
]

GASOLINE_ROWS = [
    {
        "Vehicle Type": "Passenger Cars",
        "Model Year": "2020",
        "CH4 Factor (g CH4 / vehicle-mile)": "0.01",
        "N2O Factor (g N2O / vehicle-mile)": "0.02",
        "_factor_row_id": "gas-2020",
    },
    {
        "Vehicle Type": "Passenger Cars",
        "Model Year": "2010-2014",
        "CH4 Factor (g CH4 / vehicle-mile)": "0.03",
        "N2O Factor (g N2O / vehicle-mile)": "0.04",
    },
    {
        "Vehicle Type": "Light-Duty Trucks",
        "Model Year": "1990",
        "CH4 Factor (g CH4 / vehicle-mile)": "0.5",
        "N2O Factor (g N2O / vehicle-mile)": "0.5",
    },
]

DIESEL_ROWS = [
    {
        "Vehicle Type": "Heavy-Duty Trucks",
        "Fuel Type": "Diesel Fuel",
        "Model Year": "2007-2020",
        "CH4 Factor (g CH4 / vehicle-mile)": "0.01",
        "N2O Factor (g N2O / vehicle-mile)": "0.02",
    },
    {
        "Vehicle Type": "Light-Duty Cars",
        "Fuel Type": "Compressed Natural Gas",
        "CH4 Factor (g CH4 / vehicle-mile)": "0.1",
        "N2O Factor (g N2O / vehicle-mile)": "0.1",
    },
    {
        "Vehicle Type": "Light-Duty Cars",
        "Fuel Type": "Biodiesel (100%)",
        "CH4 Factor (g CH4 / vehicle-mile)": "0.01",
        "N2O Factor (g N2O / vehicle-mile)": "0.02",
    },
    {
        "Vehicle Type": "Light-Duty Cars",
        "Fuel Type": "Ethanol (100%)",
        "CH4 Factor (g CH4 / vehicle-mile)": "0.01",
        "N20 Factor (g N20 / vehicle-mile)": "0.02",
    },
]

NON_ROAD_ROWS = [
    {
        "Vehicle Type": "Agricultural Equipment",
        "Fuel Type": "Diesel Fuel",
        "CH4 Factor (g CH4 / gallon)": "1",
        "N2O Factor (g N2O / gallon)": "0.4",
    }
]


def _sheets(**overrides):
    base = [
        {
            "dataset_code": "mobile_combustion",
            "publisher": "EPA",
            "title": "Mobile Combustion",
            "version_label": "imported",
            "rows": CO2_ROWS,
        },
        {
            "dataset_code": "on_road_gasoline",
            "publisher": "EPA",
            "title": "On-Road Gasoline",
            "version_label": "imported",
            "rows": GASOLINE_ROWS,
        },
        {
            "dataset_code": "on_road_diesel_alt_fuel",
            "publisher": "EPA",
            "title": "On-Road Diesel & Alt Fuel",
            "version_label": "imported",
            "rows": DIESEL_ROWS,
        },
        {
            "dataset_code": "non_road_vehicle",
            "publisher": "EPA",
            "title": "Non-Road Vehicle",
            "version_label": "imported",
            "rows": NON_ROAD_ROWS,
        },
    ]
    if not overrides:
        return base
    by_code = {sheet["dataset_code"]: sheet for sheet in base}
    for code, rows in overrides.items():
        by_code[code]["rows"] = rows
    return list(by_code.values())


def _calc(**overrides):
    payload = dict(
        road_class="on_road",
        vehicle_type="Passenger Cars",
        fuel_type="Motor Gasoline",
        fuel_quantity=10,
        fuel_unit="gallon",
        distance=100,
        distance_unit="mile",
        model_year=2020,
        sheets=_sheets(),
        factor=1,
        total_t_co2e=999,
    )
    payload.update(overrides)
    return calculate_mobile_combustion(**payload)


def test_gasoline_scope1_includes_co2_ch4_and_n2o_and_ignores_caller_factors():
    result = _calc()
    assert result["success"] is True
    assert result["gases"]["co2"]["mass_kg"] == "87.8"
    assert result["gases"]["ch4"]["co2e_kg"] == "0.028"
    assert result["gases"]["n2o"]["co2e_kg"] == "0.53"
    assert result["total_kg_co2e"] == "88.358"
    assert result["total_t_co2e"] == "0.088358"
    assert result["biogenic_co2_t"] == "0"
    assert result["accounting"]["treatment"] == "fossil_scope1"
    assert result["accounting"]["version"] == "epa_mobile_biogenic_v1"
    assert result["accounting"]["gwp_version"] == "AR5"
    assert result["accounting"]["publication_year"] is None
    assert result["factors"]["co2"]["unit"] == "kg CO2 / gallon"
    assert result["factors"]["ch4"]["unit"] == "g / vehicle-mile"
    assert result["factors"]["ch4"]["factor_row_id"] == "gas-2020"
    assert result["factors"]["co2"]["value"] == "8.78"


def test_liters_convert_to_gallons_and_kilometers_convert_to_miles():
    result = _calc(fuel_quantity=Decimal("3.78541"), fuel_unit="liter", distance=100, distance_unit="km")
    assert result["success"] is True
    assert result["gases"]["co2"]["mass_kg"] == "8.78"
    assert result["fuel_unit"] == "gallon"
    assert result["distance_unit"] == "mile"
    assert Decimal(result["distance"]) == Decimal("62.1371")


def test_model_year_range_matches_inside_and_rejects_outside():
    inside = _calc(model_year=2012)
    assert inside["success"] is True
    assert inside["factors"]["ch4"]["value"] == "0.03"
    assert inside["gases"]["ch4"]["co2e_kg"] == "0.084"
    outside = _calc(model_year=2015)
    assert outside["success"] is False
    assert "2015" in outside["error"]


def test_overlapping_year_ranges_are_rejected():
    rows = GASOLINE_ROWS + [
        {
            "Vehicle Type": "Passenger Cars",
            "Model Year": "2014-2016",
            "CH4 Factor (g CH4 / vehicle-mile)": "0.09",
            "N2O Factor (g N2O / vehicle-mile)": "0.09",
        }
    ]
    result = _calc(model_year=2014, sheets=_sheets(on_road_gasoline=rows))
    assert result["success"] is False
    assert "more than one" in result["error"]


def test_diesel_uses_vehicle_fuel_and_year_not_the_first_row():
    result = _calc(
        vehicle_type="Heavy-Duty Trucks",
        fuel_type="Diesel Fuel",
        model_year=2010,
        fuel_quantity=1,
        distance=10,
    )
    assert result["success"] is True
    assert result["gases"]["co2"]["mass_kg"] == "10.21"
    assert result["factors"]["ch4"]["dataset_code"] == "on_road_diesel_alt_fuel"
    assert result["factors"]["ch4"]["value"] == "0.01"
    assert result["biogenic_co2_t"] == "0"


def test_cng_uses_scf_and_an_undated_alternative_fuel_row():
    result = _calc(
        vehicle_type="Light-Duty Cars",
        fuel_type="Compressed Natural Gas",
        fuel_quantity=100,
        fuel_unit="scf",
        distance=10,
        model_year=None,
    )
    assert result["success"] is True
    assert result["gases"]["co2"]["mass_kg"] == "5.444"
    assert result["fuel_unit"] == "scf"
    assert result["total_kg_co2e"] == "5.737"
    assert result["factors"]["co2"]["unit"] == "kg CO2 / scf"
    rejected = _calc(
        vehicle_type="Light-Duty Cars",
        fuel_type="Compressed Natural Gas",
        fuel_quantity=10,
        fuel_unit="gallon",
        distance=10,
        model_year=None,
    )
    assert rejected["success"] is False
    assert "scf" in rejected["error"]


def test_biodiesel_and_ethanol_keep_biogenic_co2_out_of_scope_1():
    biodiesel = _calc(
        vehicle_type="Light-Duty Cars",
        fuel_type="Biodiesel (100%)",
        fuel_quantity=1,
        distance=10,
        model_year=None,
    )
    assert biodiesel["success"] is True
    assert biodiesel["gases"]["co2"]["mass_kg"] == "9.45"
    assert biodiesel["gases"]["co2"]["reporting"] == "biogenic_outside_scope1"
    assert biodiesel["biogenic_co2_t"] == "0.00945"
    assert biodiesel["total_kg_co2e"] == "0.0558"
    assert Decimal(biodiesel["total_kg_co2e"]) + Decimal(biodiesel["biogenic_co2_kg"]) != Decimal(
        biodiesel["total_kg_co2e"]
    )

    ethanol = _calc(
        vehicle_type="Light-Duty Cars",
        fuel_type="Ethanol (100%)",
        fuel_quantity=1,
        distance=10,
        model_year=None,
    )
    assert ethanol["success"] is True
    assert ethanol["factors"]["n2o"]["attribute_key"] == "N20 Factor (g N20 / vehicle-mile)"
    assert ethanol["gases"]["n2o"]["co2e_kg"] == "0.053"
    assert ethanol["biogenic_co2_kg"] == "5.75"
    assert ethanol["accounting"]["treatment"] == "biogenic_co2_outside_scope1"


def test_blends_are_blocked():
    for fuel in ("B20", "E85"):
        result = _calc(fuel_type=fuel, vehicle_type="Light-Duty Cars", model_year=None)
        assert result["success"] is False
        assert result["review_required"] is True
        assert result["total_t_co2e"] is None
        assert result["biogenic_co2_t"] is None


def test_non_road_diesel_uses_grams_per_gallon():
    result = _calc(
        road_class="non_road",
        vehicle_type="Agricultural Equipment",
        fuel_type="Diesel Fuel",
        fuel_quantity=5,
        distance=None,
        model_year=None,
    )
    assert result["success"] is True
    assert result["gases"]["co2"]["mass_kg"] == "51.05"
    assert result["gases"]["ch4"]["co2e_kg"] == "0.14"
    assert result["gases"]["n2o"]["co2e_kg"] == "0.53"
    assert result["total_kg_co2e"] == "51.72"
    assert result["distance"] is None
    assert result["factors"]["ch4"]["unit"] == "g / gallon"
    assert result["factors"]["ch4"]["dataset_code"] == "non_road_vehicle"


def test_missing_and_duplicate_matches_do_not_fall_back_to_the_first_row():
    missing = _calc(vehicle_type="Motorcycles", model_year=2020)
    assert missing["success"] is False
    assert missing["total_t_co2e"] is None

    duplicated = _calc(
        sheets=_sheets(
            on_road_gasoline=GASOLINE_ROWS
            + [
                {
                    "Vehicle Type": "Passenger Cars",
                    "Model Year": "2020",
                    "CH4 Factor (g CH4 / vehicle-mile)": "9",
                    "N2O Factor (g N2O / vehicle-mile)": "9",
                }
            ]
        )
    )
    assert duplicated["success"] is False
    assert "more than one" in duplicated["error"]

    duplicated_fuel = _calc(
        sheets=_sheets(mobile_combustion=CO2_ROWS + [dict(CO2_ROWS[0])])
    )
    assert duplicated_fuel["success"] is False
    assert "More than one" in duplicated_fuel["error"]


def test_on_road_without_distance_is_not_a_complete_total():
    result = _calc(distance=None)
    assert result["success"] is False
    assert result["total_t_co2e"] is None


def test_disagreeing_n20_alias_is_rejected():
    rows = [
        {
            "Vehicle Type": "Passenger Cars",
            "Model Year": "2020",
            "CH4 Factor (g CH4 / vehicle-mile)": "0.01",
            "N2O Factor (g N2O / vehicle-mile)": "0.02",
            "N20 Factor (g N20 / vehicle-mile)": "0.09",
        }
    ]
    result = _calc(sheets=_sheets(on_road_gasoline=rows))
    assert result["success"] is False
    assert "disagree" in result["error"]


def test_dated_diesel_rows_require_a_model_year():
    result = _calc(vehicle_type="Heavy-Duty Trucks", fuel_type="Diesel Fuel", model_year=None, distance=10)
    assert result["success"] is False
    assert "model year is required" in result["error"].lower()


def test_only_ar5_is_accepted():
    result = _calc(gwp_version="AR6")
    assert result["success"] is False
