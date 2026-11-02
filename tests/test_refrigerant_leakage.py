"""EPA refrigerant leakage engine. Sheet rows are fixtures, not a live database."""

from decimal import Decimal
from uuid import UUID

from fastapi_app.ghg_calc.refrigerant_leakage import (
    calculate_refrigerant_leakage,
    load_refrigerant_factor_sheets,
)

DATASET_ID = "11111111-1111-1111-1111-111111111111"

_BLENDS = {
    "R-404A": ("3,943", "44% HFC-125, 4% HFC-134a, 52% HFC-143a", "row-r404a"),
    "R-407A": ("1923", "20% HFC-32, 40% HFC-125, 40% HFC-134a", "row-r407a"),
    "R-407B": ("2547", "10% HFC-32, 70% HFC-125, 20% HFC-134a", "row-r407b"),
    "R-407C": ("1,624", "23% HFC-32, 25% HFC-125, 52% HFC-134a", "row-r407c"),
    "R-407D": ("1487", "15% HFC-32, 15% HFC-125, 70% HFC-134a", "row-r407d"),
    "R-410A": (" 1,924 ", "50% HFC-32, 50% HFC-125", "row-r410a"),
    "R-410B": ("2048", "45% HFC-32, 55% HFC-125", "row-r410b"),
    "R-417A": ("2127", "46.6% HFC-125, 50% HFC-134a, 3.4% butane", "row-r417a"),
    "R-422A": ("2847", "85.1% HFC-125, 11.5% HFC-134a, 3.4% isobutane", "row-r422a"),
    "R-422D": ("2473", "65.1% HFC-125, 31.5% HFC-134a, 3.4% isobutane", "row-r422d"),
    "R-424A": ("3104", "50.5% HFC-125, 47% HFC-134a, 1% butane, 0.9% isobutane, 0.6% isopentane", "row-r424a"),
    "R-426A": ("1371", "5.1% HFC-125, 93% HFC-134a, 1.3% butane, 0.6% isobutane", "row-r426a"),
    "R-428A": ("3417", "77.5% HFC-125, 20% HFC-143a, 1.9% isobutane, 0.6% propane", "row-r428a"),
    "R-434A": ("3075", "63.2% HFC-125, 16% HFC-134a, 18% HFC-143a, 2.8% isobutane", "row-r434a"),
    "R-507A": ("3985", "50% HFC-125, 50% HFC-143a", "row-r507a"),
    "R-508A": ("11607", "39% HFC-23, 61% PFC-116", "row-r508a"),
    "R-508B": ("11698", "46% HFC-23, 54% PFC-116", "row-r508b"),
}

_REJECTED_ROWS = [
    {
        "ASHRAE #": "R-401A",
        "100-year GWP": "18",
        "Blend Composition": "53% HCFC-22, 34% HCFC-124, 13% HFC-152a",
        "_factor_row_id": "row-r401a",
        "_factor_dataset_id": DATASET_ID,
        "kg_co2e": 1182,
    },
    {
        "ASHRAE #": "R-406A",
        "100-year GWP": "0",
        "Blend Composition": "55% HCFC-22, 41% HCFC-142b, 4% isobutane",
        "_factor_row_id": "row-r406a",
        "_factor_dataset_id": DATASET_ID,
    },
    {
        "ASHRAE #": "R-22",
        "100-year GWP": "1760",
        "_factor_row_id": "row-r22",
        "_factor_dataset_id": DATASET_ID,
    },
]


def _blend_row(name, gwp, composition, row_id):
    return {
        "ASHRAE #": name,
        "100-year GWP": gwp,
        "Blend Composition": composition,
        "_factor_row_id": row_id,
        "_factor_dataset_id": DATASET_ID,
        "kg_co2e": 1,
    }


def _sheet(rows=None, **overrides):
    payload = {
        "dataset_code": "epa_refrigerant_gwp",
        "dataset_id": DATASET_ID,
        "publisher": "EPA",
        "title": "EPA Refrigerant GWP",
        "version_label": "imported_from_sheet",
        "is_active": True,
        "rows": rows
        if rows is not None
        else [_blend_row(*item) for item in ((name, *values) for name, values in _BLENDS.items())]
        + _REJECTED_ROWS,
    }
    payload.update(overrides)
    return payload


def _calc(**overrides):
    payload = dict(
        method="leakage_record",
        gas="R-404A",
        leakage_kg=2,
        sheets=[_sheet()],
        gwp=1,
        factor=3922,
        emissions_kg_co2e=1,
        emissions_tco2e=0,
    )
    payload.update(overrides)
    return calculate_refrigerant_leakage(**payload)


def test_r404a_measured_two_kilograms_converts_to_tonnes():
    result = _calc()
    assert result["success"] is True
    assert result["method"] == "leakage_record"
    assert result["refrigerant"] == "R-404A"
    assert result["gwp"] == "3943"
    assert result["leakage_kg"] == "2"
    assert result["emissions_kg_co2e"] == "7886"
    assert result["emissions_tco2e"] == "7.886"
    assert result["leakage_rate_source"] is None
    assert result["accounting"]["version"] == "epa_refrigerant_v1"


def test_r407c_uses_table12_gwp_not_the_older_code_map():
    result = _calc(gas="R-407C", leakage_kg=1, gwp=1774)
    assert result["success"] is True
    assert result["gwp"] == "1624"
    assert result["emissions_tco2e"] == "1.624"


def test_r410a_parses_commas_and_whitespace():
    result = _calc(gas="R-410A", leakage_kg=Decimal("1"))
    assert result["success"] is True
    assert result["gwp"] == "1924"
    assert result["emissions_kg_co2e"] == "1924"
    assert result["emissions_tco2e"] == "1.924"
    assert result["factor_row_id"] == "row-r410a"


def test_hfc134a_uses_table11_allowlist_and_alias():
    by_name = _calc(gas="HFC-134a", leakage_kg=2)
    by_alias = _calc(gas="R-134a", leakage_kg=2)
    assert by_name["success"] is True
    assert by_name["refrigerant"] == "HFC-134a"
    assert by_name["gwp"] == "1300"
    assert by_name["emissions_kg_co2e"] == "2600"
    assert by_name["emissions_tco2e"] == "2.6"
    assert by_name["dataset_id"] is None
    assert by_name["factor_row_id"] is None
    assert by_name["dataset_code"] is None
    assert by_name["table11_reference"]
    assert "not a ref.factor_rows" in by_name["table11_reference"]
    assert "uk_refrigerant_factors" in by_name["factor_provenance"]
    assert by_alias["refrigerant"] == "HFC-134a"
    assert by_alias["gwp"] == "1300"
    assert by_alias["emissions_tco2e"] == "2.6"


def test_fractional_kilograms_stay_exact():
    result = _calc(gas="R-407C", leakage_kg=Decimal("0.1"))
    assert result["success"] is True
    assert result["emissions_kg_co2e"] == "162.4"
    assert result["emissions_tco2e"] == "0.1624"


def test_estimated_leakage_uses_only_the_entered_rate():
    result = _calc(
        method="estimated_leakage",
        gas="R-410A",
        leakage_kg=None,
        charge_kg=10,
        leakage_rate_percent=10,
        equipment_type="small split AC",
    )
    other_type = _calc(
        method="estimated_leakage",
        gas="R-410A",
        leakage_kg=999,
        charge_kg=10,
        leakage_rate_percent=10,
        equipment_type="large chiller",
    )
    assert result["success"] is True
    assert result["method"] == "estimated_leakage"
    assert result["leakage_kg"] == "1"
    assert result["charge_kg"] == "10"
    assert result["leakage_rate_percent"] == "10"
    assert result["leakage_rate_source"] == "user_assumption"
    assert result["equipment_type"] == "small split AC"
    assert result["gwp"] == "1924"
    assert result["emissions_tco2e"] == "1.924"
    assert other_type["emissions_tco2e"] == result["emissions_tco2e"]
    assert "EPA default" not in (result["factor_provenance"] or "")


def test_explicit_zero_rate_is_zero_and_a_missing_rate_is_not():
    zero = _calc(
        method="estimated_leakage",
        gas="R-404A",
        charge_kg=4,
        leakage_rate_percent=0,
    )
    missing = _calc(
        method="estimated_leakage",
        gas="R-404A",
        charge_kg=4,
        leakage_rate_percent=None,
    )
    blank = _calc(
        method="estimated_leakage",
        gas="R-404A",
        charge_kg=4,
        leakage_rate_percent="  ",
    )
    assert zero["success"] is True
    assert zero["method"] == "estimated_leakage"
    assert zero["leakage_kg"] == "0"
    assert zero["leakage_rate_percent"] == "0"
    assert zero["leakage_rate_source"] == "user_assumption"
    assert zero["emissions_kg_co2e"] == "0"
    assert zero["emissions_tco2e"] == "0"
    assert missing["success"] is False
    assert missing["emissions_tco2e"] is None
    assert missing["emissions_kg_co2e"] is None
    assert "not treated as zero" in missing["error"]
    assert blank["success"] is False
    assert blank["emissions_tco2e"] is None


def test_rate_outside_0_to_100_is_rejected():
    high = _calc(method="estimated_leakage", charge_kg=1, leakage_rate_percent=Decimal("100.1"))
    negative = _calc(method="estimated_leakage", charge_kg=1, leakage_rate_percent=-1)
    full = _calc(method="estimated_leakage", charge_kg=1, leakage_rate_percent=100)
    assert high["success"] is False
    assert high["emissions_tco2e"] is None
    assert negative["success"] is False
    assert full["success"] is True
    assert full["emissions_tco2e"] == "3.943"


def test_hcfc_blend_is_rejected_even_when_the_sheet_has_a_gwp():
    result = _calc(gas="R-401A", leakage_kg=2)
    assert result["success"] is False
    assert result["refrigerant"] == "R-401A"
    assert "HCFC" in result["error"]
    assert result["gwp"] is None
    assert result["emissions_tco2e"] is None
    assert result["emissions_kg_co2e"] is None


def test_zero_gwp_blend_is_rejected_and_a_supported_zero_row_is_not_used():
    named = _calc(gas="R-406A", leakage_kg=2)
    zeroed = _calc(
        gas="R-410A",
        sheets=[
            _sheet(
                rows=[
                    _blend_row("R-410A", "0", "50% HFC-32, 50% HFC-125", "row-r410a"),
                ]
            )
        ],
    )
    assert named["success"] is False
    assert "zero-GWP" in named["error"]
    assert named["emissions_tco2e"] is None
    assert zeroed["success"] is False
    assert "zero" in zeroed["error"]
    assert zeroed["emissions_kg_co2e"] is None
    assert zeroed["emissions_tco2e"] is None


def test_unknown_and_excluded_gases_are_refused():
    unknown = _calc(gas="R-999")
    sf6 = _calc(gas="SF6", gwp=23500)
    co2 = _calc(gas="CO2")
    r22 = _calc(gas="R-22")
    pfc = _calc(gas="PFC-116")
    for result in (unknown, sf6, co2, r22, pfc):
        assert result["success"] is False
        assert result["emissions_tco2e"] is None
        assert result["gwp"] is None
    assert "not a supported refrigerant" in unknown["error"]
    assert "not calculated" in sf6["error"]
    assert "not calculated" in co2["error"]
    assert "not calculated" in r22["error"]
    assert r22["emissions_tco2e"] is None


def test_missing_and_duplicate_rows_and_datasets_fail_closed():
    missing_row = _calc(
        gas="R-404A",
        sheets=[_sheet(rows=[_blend_row("R-410A", "1924", "50% HFC-32, 50% HFC-125", "row-r410a")])],
    )
    duplicate_row = _calc(
        sheets=[
            _sheet(
                rows=[
                    _blend_row("R-404A", "3943", "44% HFC-125, 4% HFC-134a, 52% HFC-143a", "row-a"),
                    _blend_row("R-404A", "3943", "44% HFC-125, 4% HFC-134a, 52% HFC-143a", "row-b"),
                ]
            )
        ]
    )
    missing_dataset = _calc(sheets=[])
    uk_only = _calc(
        sheets=[
            {
                "dataset_code": "uk_refrigerant_factors",
                "dataset_id": "22222222-2222-2222-2222-222222222222",
                "version_label": "imported_from_sheet",
                "rows": [{"Emission": "HFC-134a", "kg CO2e": 1, "ASHRAE #": "R-404A", "100-year GWP": "3922"}],
            }
        ]
    )
    duplicate_dataset = _calc(sheets=[_sheet(), _sheet(dataset_id="33333333-3333-3333-3333-333333333333")])
    inactive = _calc(sheets=[_sheet(is_active=False)])
    for result in (missing_row, duplicate_row, missing_dataset, uk_only, duplicate_dataset, inactive):
        assert result["success"] is False
        assert result["emissions_tco2e"] is None
        assert result["emissions_kg_co2e"] is None
        assert result["gwp"] is None
    assert "missing factor is not treated as zero" in missing_row["error"]
    assert "More than one" in duplicate_row["error"]
    assert "missing or inactive" in missing_dataset["error"]
    assert "missing or inactive" in uk_only["error"]
    assert "More than one active" in duplicate_dataset["error"]


def test_malformed_gwp_text_is_rejected_and_kg_co2e_is_not_a_substitute():
    malformed = _calc(
        gas="R-410A",
        sheets=[_sheet(rows=[_blend_row("R-410A", "not a number", "50% HFC-32, 50% HFC-125", "row-r410a")])],
    )
    empty = _calc(
        gas="R-410A",
        sheets=[_sheet(rows=[_blend_row("R-410A", "   ", "50% HFC-32, 50% HFC-125", "row-r410a")])],
    )
    column_only = _calc(
        gas="R-410A",
        sheets=[
            _sheet(
                rows=[
                    {
                        "ASHRAE #": "R-410A",
                        "kg_co2e": 1924,
                        "_factor_row_id": "row-r410a",
                        "_factor_dataset_id": DATASET_ID,
                    }
                ]
            )
        ],
    )
    for result in (malformed, empty, column_only):
        assert result["success"] is False
        assert result["emissions_tco2e"] is None
        assert result["gwp"] is None
    assert "malformed" in malformed["error"]
    assert "empty" in empty["error"]
    assert "not used as a substitute" in column_only["error"]


def test_browser_supplied_gwp_and_totals_are_ignored():
    result = _calc(gwp=1, factor=3922, emissions_tco2e=0, emissions_kg_co2e=1, total_t_co2e=0)
    assert result["success"] is True
    assert result["gwp"] == "3943"
    assert result["emissions_kg_co2e"] == "7886"
    assert result["emissions_tco2e"] == "7.886"


def test_blend_provenance_keeps_dataset_row_and_table12_basis():
    plain = _calc()
    hydrocarbon = _calc(gas="R-422A", leakage_kg=1)
    assert plain["dataset_code"] == "epa_refrigerant_gwp"
    assert plain["dataset_id"] == DATASET_ID
    assert plain["factor_row_id"] == "row-r404a"
    assert plain["factor_attribute"] == "100-year GWP"
    assert plain["version_label"] == "imported_from_sheet"
    assert plain["gwp_publication"] == (
        "EPA GHG Emission Factors Hub, Table 12, document last modified 05 June 2024"
    )
    assert "AR5" in plain["gwp_edition"]
    assert "Table 8.A.1" in plain["gwp_edition"]
    assert "Not a frontend GWP map and not a UK refrigerant factor" in plain["factor_provenance"]
    assert plain["table11_reference"] is None
    assert "accounting factor" in plain["gwp_basis"]
    assert hydrocarbon["success"] is True
    assert "hydrocarbon constituents" in hydrocarbon["gwp_basis"]
    assert "separate physical warming contribution" in hydrocarbon["factor_provenance"]
    assert hydrocarbon["factor_row_id"] == "row-r422a"


def test_documented_aliases_resolve_and_negative_mass_does_not():
    alias = _calc(gas="HFC-43-I0mee", leakage_kg=1)
    r32 = _calc(gas="R-32", leakage_kg=1)
    negative = _calc(leakage_kg=-2)
    missing = _calc(leakage_kg=None)
    assert alias["success"] is True
    assert alias["refrigerant"] == "HFC-43-10mee"
    assert alias["gwp"] == "1650"
    assert alias["dataset_id"] is None
    assert r32["success"] is True
    assert r32["refrigerant"] == "HFC-32"
    assert r32["gwp"] == "677"
    assert negative["success"] is False
    assert negative["emissions_tco2e"] is None
    assert missing["success"] is False
    assert missing["emissions_tco2e"] is None


def test_loader_wires_row_identity_and_fails_closed_without_one_active_dataset():
    dataset_id = UUID("44444444-4444-4444-4444-444444444444")
    row_id = UUID("55555555-5555-5555-5555-555555555555")

    class FakeDataset:
        id = dataset_id
        code = "epa_refrigerant_gwp"
        publisher = "EPA"
        title = "EPA Refrigerant GWP"
        version_label = "imported_from_sheet"
        source_notes = None

    class FakeRow:
        id = row_id
        attributes = {
            "ASHRAE #": "R-404A",
            "100-year GWP": " 3,943 ",
            "Blend Composition": "44% HFC-125, 4% HFC-134a, 52% HFC-143a",
        }
        unit = None
        category = "refrigerant"
        label = None
        kg_co2e = Decimal("3922")
        kg_co2 = None
        kg_ch4 = None
        kg_n2o = None

    class Query:
        def __init__(self, items):
            self.items = items

        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def offset(self, *args, **kwargs):
            return self

        def limit(self, *args, **kwargs):
            return self

        def all(self):
            return list(self.items)

    class FakeDb:
        def __init__(self, datasets, rows):
            self.datasets = datasets
            self.rows = rows

        def query(self, model):
            if model.__tablename__ == "factor_datasets":
                return Query(self.datasets)
            if model.__tablename__ == "factor_rows":
                return Query(self.rows)
            raise AssertionError(model)

    loaded = load_refrigerant_factor_sheets(FakeDb([FakeDataset()], [FakeRow()]))
    result = calculate_refrigerant_leakage(
        method="leakage_record",
        gas="R-404A",
        leakage_kg=2,
        sheets=loaded,
        gwp=3922,
    )
    assert result["success"] is True
    assert result["gwp"] == "3943"
    assert result["emissions_tco2e"] == "7.886"
    assert result["dataset_id"] == str(dataset_id)
    assert result["factor_row_id"] == str(row_id)

    missing = load_refrigerant_factor_sheets(FakeDb([], []))
    missing_result = calculate_refrigerant_leakage(
        method="leakage_record",
        gas="HFC-134a",
        leakage_kg=1,
        sheets=missing,
    )
    assert missing_result["success"] is True
    assert missing_result["gwp"] == "1300"
    assert missing_result["emissions_tco2e"] == "1.3"
    assert missing_result["dataset_id"] is None
    assert missing_result["factor_row_id"] is None
    assert missing_result["table11_reference"]

    blend_without_dataset = calculate_refrigerant_leakage(
        method="leakage_record",
        gas="R-404A",
        leakage_kg=2,
        sheets=missing,
    )
    assert blend_without_dataset["success"] is False
    assert blend_without_dataset["emissions_tco2e"] is None
    assert "missing or inactive" in blend_without_dataset["error"]

    duplicate = load_refrigerant_factor_sheets(FakeDb([FakeDataset(), FakeDataset()], []))
    duplicate_result = calculate_refrigerant_leakage(
        method="leakage_record",
        gas="R-404A",
        leakage_kg=2,
        sheets=duplicate,
    )
    assert duplicate_result["success"] is False
    assert duplicate_result["emissions_tco2e"] is None
    assert "More than one active" in duplicate_result["error"]
