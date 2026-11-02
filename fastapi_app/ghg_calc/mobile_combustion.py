"""
Backend-authoritative EPA Scope 1 mobile combustion.

One physical vehicle or equipment activity is calculated from the factor sheets.
The caller cannot supply a factor or a total.

Datasets, by exact code:
- mobile_combustion: fuel CO2. Value key ``kg CO2 per unit``.
  The row's Unit is the physical unit (gallon or scf). CNG uses scf.
- on_road_gasoline: CH4 and N2O by vehicle type and model year.
  Keys ``CH4 Factor (g CH4 / vehicle-mile)`` and
  ``N2O Factor (g N2O / vehicle-mile)``.
- on_road_diesel_alt_fuel: CH4 and N2O by vehicle type, fuel, and model year
  when the sheet has a year. Alternative-fuel rows may omit the year.
- non_road_vehicle: CH4 and N2O by equipment and fuel.
  Keys ``CH4 Factor (g CH4 / gallon)`` and ``N2O Factor (g N2O / gallon)``.

Some imported headers spell N2O as N20. That alias is used only when the
canonical N2O key is absent on the same row, or when both keys carry the same
number. Differing N2O and N20 values are rejected.

Model-year cells may be one year (``2020``) or an inclusive range
(``1990-1995``). ``1990-present`` and ``1990+`` run through 2100. A requested
year that falls in more than one row is ambiguous. The first sheet row is
never used as a fallback.

GWP AR5 (CH4 28, N2O 265) is applied to raw gas masses. These keys are not
CO2e factors. A CO2e column is not read.

Accounting, version epa_mobile_biogenic_v1:
- GHG Protocol Corporate Standard: CO2 from biodiesel and ethanol is reported
  outside Scope 1. CH4 and N2O from that combustion stay in Scope 1.
- Blends and other uncertain biofuel names are not split.
- EPA Emission Factors for Greenhouse Gas Inventories supplies the mobile
  factors. Publication year is whatever ``version_label`` is stored on the
  dataset. This module does not invent one.

This module does not write activities and does not change stationary combustion.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

GWP_SETS = {
    "AR5": {
        "CO2": Decimal("1"),
        "CH4": Decimal("28"),
        "N2O": Decimal("265"),
    }
}

ACCOUNTING_VERSION = "epa_mobile_biogenic_v1"
METHODOLOGY = (
    "GHG Protocol Corporate Standard: CO2 from biodiesel and ethanol is reported "
    "outside Scope 1, while CH4 and N2O from that combustion stay in Scope 1. "
    "CO2 uses the EPA mobile combustion fuel factor in that row's own unit "
    "(gallon or scf). On-road CH4 and N2O use grams per vehicle-mile for the "
    "matching vehicle class and model year. Non-road CH4 and N2O use grams per "
    "gallon for the matching equipment and fuel. AR5 GWP is applied to those raw "
    "gas masses. Blends without a documented biogenic fraction are not calculated. "
    "Factor publication year is the dataset version label and is not invented."
)

DATASET_CO2 = "mobile_combustion"
DATASET_GASOLINE = "on_road_gasoline"
DATASET_DIESEL = "on_road_diesel_alt_fuel"
DATASET_NON_ROAD = "non_road_vehicle"
DATASET_CODES = (DATASET_CO2, DATASET_GASOLINE, DATASET_DIESEL, DATASET_NON_ROAD)

_THOUSAND = Decimal("1000")
_LITERS_PER_GALLON = Decimal("3.78541")
_KM_TO_MILES = Decimal("0.621371")
_YEAR_MIN = 1900
_YEAR_MAX = 2100

_KEY_CO2 = "kg co2 per unit"
_KEY_CH4_MILE = "ch4 factor (g ch4 / vehicle-mile)"
_KEY_N2O_MILE = "n2o factor (g n2o / vehicle-mile)"
_KEY_CH4_GALLON = "ch4 factor (g ch4 / gallon)"
_KEY_N2O_GALLON = "n2o factor (g n2o / gallon)"
_KEY_VEHICLE = "vehicle type"
_KEY_FUEL = "fuel type"
_KEY_YEAR = "model year"
_KEY_UNIT = "unit"

_BIOGENIC_FUELS = frozenset(
    {
        "biodiesel",
        "biodiesel (100%)",
        "ethanol",
        "ethanol (100%)",
    }
)
_GASOLINE_FUELS = frozenset(
    {
        "motor gasoline",
        "gasoline",
        "petrol",
    }
)

# Each set is one physical fuel. Names match only inside a single set.
# "diesel" matches "diesel fuel", and "diesel equipment" matches "diesel fuel",
# but "diesel" does not match "diesel equipment" or "diesel off-road trucks".
# Those truck rows have their own CH4/N2O factors on the same equipment type.
# LNG is not CNG. B20 and E85 are not the pure biodiesel and ethanol rows.
_FUEL_EQUIVALENCE = (
    frozenset({"diesel fuel", "diesel"}),
    frozenset({"compressed natural gas (cng)", "compressed natural gas", "cng"}),
    frozenset({"diesel equipment", "diesel fuel"}),
    frozenset({"biodiesel (100%)", "biodiesel"}),
    frozenset({"ethanol (100%)", "ethanol"}),
    frozenset({"liquefied natural gas (lng)", "lng"}),
    frozenset({"liquefied petroleum gases (lpg)", "lpg"}),
)


def _norm_text(value: Any) -> str:
    return " ".join(str(value if value is not None else "").casefold().split())


def fuels_equivalent(left: Any, right: Any) -> bool:
    """True when both names are the same physical fuel in one explicit set."""
    first = _norm_text(left)
    second = _norm_text(right)
    if not first or not second:
        return False
    if first == second:
        return True
    return any(first in group and second in group for group in _FUEL_EQUIVALENCE)


def _norm_key(value: Any) -> str:
    return " ".join(str(value).casefold().replace("_", " ").split())


def _parse_decimal(value: Any) -> Optional[Decimal]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return None if value.is_nan() or not value.is_finite() else value
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (value != value or abs(value) == float("inf")):
            return None
        try:
            parsed = Decimal(str(value))
        except InvalidOperation:
            return None
        return None if not parsed.is_finite() else parsed
    text = str(value).replace(",", "").strip()
    if not text:
        return None
    try:
        parsed = Decimal(text)
    except InvalidOperation:
        return None
    return None if not parsed.is_finite() else parsed


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _fail(message: str, **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "success": False,
        "review_required": False,
        "error": message,
        "gases": None,
        "total_kg_co2e": None,
        "total_t_co2e": None,
        "biogenic_co2_kg": None,
        "biogenic_co2_t": None,
        "accounting": {
            "version": ACCOUNTING_VERSION,
            "methodology": METHODOLOGY,
        },
    }
    payload.update(extra)
    return payload


def classify_mobile_fuel(fuel: str) -> str:
    """fossil_scope1, biogenic_co2_outside_scope1, or needs_review."""
    name = _norm_text(fuel)
    if name in _BIOGENIC_FUELS:
        return "biogenic_co2_outside_scope1"
    review_tokens = ("blend", "gasohol", "renewable", "biomass", "biogas", "b20", "e85")
    if "%" in name or any(token in name for token in review_tokens):
        return "needs_review"
    if "bio" in name:
        return "needs_review"
    return "fossil_scope1"


def _attribute_index(row: Mapping[str, Any]) -> Dict[str, Tuple[str, Any]]:
    """Map a normalized key to (original key, value). N20 aliases fill a missing N2O key."""
    exact: Dict[str, Tuple[str, Any]] = {}
    aliases: List[Tuple[str, str, Any]] = []
    for raw_key, value in row.items():
        if str(raw_key).startswith("_"):
            continue
        norm = _norm_key(raw_key)
        if not norm or norm in exact:
            continue
        exact[norm] = (str(raw_key), value)
        if "n20" in norm and "n2o" not in norm:
            aliases.append((norm.replace("n20", "n2o"), str(raw_key), value))
    for alias, raw_key, value in aliases:
        if alias not in exact:
            exact[alias] = (raw_key, value)
    return exact


def _n2o_conflict(row: Mapping[str, Any], canonical: str) -> bool:
    """True when the row has both an N2O key and an N20 alias with different numbers."""
    found: List[Decimal] = []
    for raw_key, value in row.items():
        if str(raw_key).startswith("_"):
            continue
        norm = _norm_key(raw_key)
        alias = norm.replace("n20", "n2o") if "n20" in norm and "n2o" not in norm else norm
        if alias != canonical:
            continue
        parsed = _parse_decimal(value)
        if parsed is None:
            continue
        if all(parsed != existing for existing in found):
            found.append(parsed)
    return len(found) > 1


def parse_model_year_cell(value: Any) -> Optional[Tuple[int, int]]:
    """
    Return an inclusive year span, or None when the cell is blank.

    Raises ValueError when the cell has text that is not a year or a range.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("model year is not a year or a range")
    if isinstance(value, (int, Decimal)) and not isinstance(value, bool):
        year = int(value)
        if year < _YEAR_MIN or year > _YEAR_MAX:
            raise ValueError("model year is not a year or a range")
        return (year, year)
    if isinstance(value, float):
        if value != value or int(value) != value:
            raise ValueError("model year is not a year or a range")
        year = int(value)
        if year < _YEAR_MIN or year > _YEAR_MAX:
            raise ValueError("model year is not a year or a range")
        return (year, year)

    text = " ".join(str(value).strip().lower().replace("–", "-").replace("—", "-").split())
    if not text:
        return None
    if text.endswith("+") and text[:-1].isdigit():
        start = int(text[:-1])
        if _YEAR_MIN <= start <= _YEAR_MAX:
            return (start, _YEAR_MAX)
        raise ValueError("model year is not a year or a range")
    if "-" not in text and text.isdigit():
        year = int(text)
        if _YEAR_MIN <= year <= _YEAR_MAX:
            return (year, year)
        raise ValueError("model year is not a year or a range")
    start_text, end_text = [part.strip() for part in text.split("-", 1)]
    if not start_text.isdigit():
        raise ValueError("model year is not a year or a range")
    start = int(start_text)
    if end_text in {"present", "later", "onward", "current"}:
        end = _YEAR_MAX
    elif end_text.isdigit():
        end = int(end_text)
    else:
        raise ValueError("model year is not a year or a range")
    if start < _YEAR_MIN or end > _YEAR_MAX or end < start:
        raise ValueError("model year is not a year or a range")
    return (start, end)


def _sheet_rows(sheets: Sequence[Mapping[str, Any]], code: str) -> Tuple[List[Mapping[str, Any]], Dict[str, Any]]:
    matches = [sheet for sheet in sheets if _norm_text(sheet.get("dataset_code")) == code]
    if not matches:
        return [], {}
    if len(matches) > 1:
        raise ValueError(f"More than one dataset is loaded for {code}")
    sheet = matches[0]
    source = {
        "dataset_code": code,
        "dataset_id": sheet.get("dataset_id"),
        "publisher": sheet.get("publisher") or "EPA",
        "title": sheet.get("title") or code,
        "version_label": sheet.get("version_label") or "imported",
        "source_notes": sheet.get("source_notes"),
    }
    rows = list(sheet.get("rows") or [])
    return rows, source


def _row_source(sheet_source: Mapping[str, Any], row: Mapping[str, Any], key_used: str) -> Dict[str, Any]:
    source = {
        "dataset_code": sheet_source.get("dataset_code"),
        "dataset_id": row.get("_factor_dataset_id") or sheet_source.get("dataset_id"),
        "factor_row_id": row.get("_factor_row_id"),
        "publisher": sheet_source.get("publisher"),
        "title": sheet_source.get("title"),
        "version_label": sheet_source.get("version_label"),
        "attribute_key": key_used,
    }
    label = _fuel_label(row)
    if label:
        source["sheet_fuel"] = label
    return source


def _fuel_label(row: Mapping[str, Any]) -> str:
    index = _attribute_index(row)
    value = _cell(index, _KEY_FUEL) or row.get("label")
    return str(value).strip() if value else ""


def _cell(index: Mapping[str, Tuple[str, Any]], key: str) -> Any:
    found = index.get(key)
    return None if found is None else found[1]


def _original_key(index: Mapping[str, Tuple[str, Any]], key: str) -> str:
    found = index.get(key)
    return key if found is None else found[0]


def _select_co2_row(
    rows: Sequence[Mapping[str, Any]], fuel: str
) -> Tuple[Optional[Mapping[str, Any]], Optional[str]]:
    want = _norm_text(fuel)
    hits = []
    for row in rows:
        index = _attribute_index(row)
        name = _norm_text(_cell(index, _KEY_FUEL) or row.get("label"))
        if fuels_equivalent(name, want):
            hits.append(row)
    if not hits:
        return None, f"No mobile combustion CO2 factor matches fuel {fuel}"
    if len(hits) > 1:
        return None, f"More than one mobile combustion CO2 row matches fuel {fuel}"
    return hits[0], None


def _vehicle_name(row: Mapping[str, Any]) -> str:
    index = _attribute_index(row)
    return _norm_text(_cell(index, _KEY_VEHICLE) or row.get("category"))


def _fuel_name(row: Mapping[str, Any]) -> str:
    index = _attribute_index(row)
    return _norm_text(_cell(index, _KEY_FUEL) or row.get("label"))


def _select_year_row(
    rows: Sequence[Mapping[str, Any]],
    model_year: Optional[int],
    label: str,
) -> Tuple[Optional[Mapping[str, Any]], Optional[str]]:
    parsed: List[Tuple[Mapping[str, Any], Optional[Tuple[int, int]]]] = []
    invalid = 0
    for row in rows:
        index = _attribute_index(row)
        try:
            span = parse_model_year_cell(_cell(index, _KEY_YEAR))
        except ValueError:
            invalid += 1
            continue
        parsed.append((row, span))
    if not parsed:
        return None, f"{label} has a model year that is not a single year or a range"

    undated = [row for row, span in parsed if span is None]
    dated = [(row, span) for row, span in parsed if span is not None]

    if model_year is None:
        if dated:
            return None, f"A model year is required for {label}"
        if len(undated) == 1:
            return undated[0], None
        if not undated:
            return None, f"No CH4/N2O factor row matches {label}"
        return None, f"More than one undated CH4/N2O row matches {label}"

    hits = [row for row, span in dated if span is not None and span[0] <= model_year <= span[1]]
    if len(hits) > 1:
        return None, f"Model year {model_year} matches more than one row for {label}"
    if len(hits) == 1:
        if undated:
            return None, f"Model year {model_year} is ambiguous for {label} because an undated row is also present"
        return hits[0], None
    if not dated and len(undated) == 1:
        return undated[0], None
    if undated and dated:
        return None, f"Model year {model_year} does not match a single row for {label}"
    return None, f"No CH4/N2O factor row matches {label} for model year {model_year}"


def _fuel_activity(quantity: Decimal, unit: str, factor_unit: str) -> Tuple[Optional[Decimal], Optional[str], Optional[str]]:
    physical = _norm_text(factor_unit)
    given = _norm_text(unit)
    if "scf" in physical or "cubic foot" in physical or "cubic feet" in physical:
        if given in {"scf", "ft3", "ft^3", "cubic foot", "cubic feet", "standard cubic foot", "standard cubic feet"}:
            return quantity, "scf", None
        return None, None, f"This CO2 factor is per scf and cannot be used with unit {unit}"
    if "gallon" in physical:
        if given in {"gallon", "gallons", "gal", "us gallon"}:
            return quantity, "gallon", None
        if given in {"liter", "liters", "litre", "litres", "l"}:
            return quantity / _LITERS_PER_GALLON, "gallon", None
        return None, None, f"This CO2 factor is per gallon and cannot be used with unit {unit}"
    return None, None, f"CO2 factor unit {factor_unit} is not gallon or scf"


def _distance_miles(distance: Decimal, unit: str) -> Tuple[Optional[Decimal], Optional[str]]:
    given = _norm_text(unit)
    if given in {"mile", "miles", "mi"}:
        return distance, None
    if given in {"km", "kilometer", "kilometre", "kilometers", "kilometres"}:
        return distance * _KM_TO_MILES, None
    return None, f"distance unit {unit} is not miles or km"


def _gas_factor(
    row: Mapping[str, Any], key: str
) -> Tuple[Optional[Decimal], Optional[str], Optional[str]]:
    if _n2o_conflict(row, key):
        return None, None, "N2O and N20 factor keys on the same row disagree"
    index = _attribute_index(row)
    if key not in index:
        return None, None, f"Factor key {key} is missing"
    number = _parse_decimal(_cell(index, key))
    if number is None:
        return None, None, f"Factor key {key} is not a number"
    return number, _original_key(index, key), None


def load_mobile_factor_sheets(db: Any) -> List[Dict[str, Any]]:
    """Read the four mobile datasets by exact code. Name hints are not used."""
    from ..factor_service import fetch_all_rows_for_dataset, factor_row_to_legacy_record, resolve_dataset

    sheets: List[Dict[str, Any]] = []
    for code in DATASET_CODES:
        dataset = resolve_dataset(db, [code], [])
        if dataset is None:
            continue
        rows = []
        for factor_row in fetch_all_rows_for_dataset(db, dataset.id):
            legacy = factor_row_to_legacy_record(factor_row)
            legacy["_factor_row_id"] = str(factor_row.id)
            legacy["_factor_dataset_id"] = str(dataset.id)
            rows.append(legacy)
        sheets.append(
            {
                "dataset_code": str(dataset.code),
                "dataset_id": str(dataset.id),
                "publisher": dataset.publisher,
                "title": dataset.title,
                "version_label": dataset.version_label,
                "source_notes": dataset.source_notes,
                "rows": rows,
            }
        )
    return sheets


def calculate_mobile_combustion(
    *,
    road_class: str,
    vehicle_type: str,
    fuel_type: str,
    fuel_quantity: Any,
    fuel_unit: str,
    sheets: Sequence[Mapping[str, Any]],
    distance: Any = None,
    distance_unit: Optional[str] = None,
    model_year: Any = None,
    gwp_version: str = "AR5",
    factor: Any = None,
    emissions: Any = None,
    emissions_kg: Any = None,
    total_kg_co2e: Any = None,
    total_t_co2e: Any = None,
    **_ignored: Any,
) -> Dict[str, Any]:
    """
    Calculate CO2, CH4, and N2O for one vehicle or piece of equipment.

    Caller ``factor`` and total arguments are discarded.
    """
    del factor, emissions, emissions_kg, total_kg_co2e, total_t_co2e, _ignored

    gwp = GWP_SETS.get(str(gwp_version).strip().upper())
    if gwp is None:
        return _fail("gwp_version must be AR5")

    road = _norm_text(road_class).replace("-", "_").replace(" ", "_")
    if road not in {"on_road", "non_road"}:
        return _fail("road_class must be on_road or non_road")

    vehicle = str(vehicle_type or "").strip()
    fuel = str(fuel_type or "").strip()
    if not vehicle or not fuel:
        return _fail("vehicle_type and fuel_type are required")

    amount = _parse_decimal(fuel_quantity)
    if amount is None or amount < 0:
        return _fail("fuel_quantity must be a finite number greater than or equal to 0")

    year: Optional[int] = None
    if model_year is not None and str(model_year).strip() != "":
        parsed_year = _parse_decimal(model_year)
        if parsed_year is None or parsed_year != parsed_year.to_integral_value():
            return _fail("model_year must be a whole year")
        year = int(parsed_year)
        if year < _YEAR_MIN or year > _YEAR_MAX:
            return _fail("model_year must be a whole year")

    treatment = classify_mobile_fuel(fuel)
    if treatment == "needs_review":
        return _fail(
            f"{fuel} has no documented biogenic fraction. "
            "Its CO2 is not added to Scope 1 and is not reported as biogenic CO2.",
            review_required=True,
            fuel=fuel,
            vehicle_type=vehicle,
            accounting={
                "version": ACCOUNTING_VERSION,
                "treatment": "needs_review",
                "methodology": METHODOLOGY,
                "gwp_version": "AR5",
            },
        )

    try:
        co2_rows, co2_source = _sheet_rows(sheets, DATASET_CO2)
    except ValueError as exc:
        return _fail(str(exc))
    if not co2_rows:
        return _fail("mobile_combustion dataset is not loaded")

    co2_row, co2_error = _select_co2_row(co2_rows, fuel)
    if co2_error or co2_row is None:
        return _fail(co2_error or "No mobile combustion CO2 factor matches this fuel")
    co2_index = _attribute_index(co2_row)
    co2_factor = _parse_decimal(_cell(co2_index, _KEY_CO2))
    factor_unit = _cell(co2_index, _KEY_UNIT) or co2_row.get("unit")
    if co2_factor is None or not factor_unit:
        return _fail(f"{fuel} has no kg CO2 per unit factor with a unit")
    activity, activity_unit, unit_error = _fuel_activity(amount, fuel_unit, str(factor_unit))
    if unit_error or activity is None or activity_unit is None:
        return _fail(unit_error or "fuel unit does not match the CO2 factor")

    if road == "on_road":
        if distance is None or str(distance).strip() == "":
            return _fail("On-road CH4 and N2O require distance")
        miles_input = _parse_decimal(distance)
        if miles_input is None or miles_input < 0:
            return _fail("distance must be a finite number greater than or equal to 0")
        miles, distance_error = _distance_miles(miles_input, distance_unit or "")
        if distance_error or miles is None:
            return _fail(distance_error or "distance unit is not miles or km")
        if _norm_text(fuel) in _GASOLINE_FUELS:
            dataset_code = DATASET_GASOLINE
            family = f"{vehicle} gasoline"
        else:
            dataset_code = DATASET_DIESEL
            family = f"{vehicle} / {fuel}"
        ch4_key, n2o_key = _KEY_CH4_MILE, _KEY_N2O_MILE
        gas_unit = "g / vehicle-mile"
        try:
            gas_rows, gas_source = _sheet_rows(sheets, dataset_code)
        except ValueError as exc:
            return _fail(str(exc))
        if not gas_rows:
            return _fail(f"{dataset_code} dataset is not loaded")
        candidates = [row for row in gas_rows if _vehicle_name(row) == _norm_text(vehicle)]
        if dataset_code == DATASET_DIESEL:
            candidates = [row for row in candidates if fuels_equivalent(_fuel_name(row), fuel)]
        if not candidates:
            return _fail(f"No CH4/N2O factor row matches {family}")
        gas_row, year_error = _select_year_row(candidates, year, family)
        if year_error or gas_row is None:
            return _fail(year_error or f"No CH4/N2O factor row matches {family}")
        activity_for_gas = miles
    else:
        miles = None
        dataset_code = DATASET_NON_ROAD
        ch4_key, n2o_key = _KEY_CH4_GALLON, _KEY_N2O_GALLON
        gas_unit = "g / gallon"
        if activity_unit != "gallon":
            return _fail("Non-road CH4 and N2O factors are per gallon and cannot be applied to scf")
        try:
            gas_rows, gas_source = _sheet_rows(sheets, dataset_code)
        except ValueError as exc:
            return _fail(str(exc))
        if not gas_rows:
            return _fail("non_road_vehicle dataset is not loaded")
        candidates = [
            row
            for row in gas_rows
            if _vehicle_name(row) == _norm_text(vehicle) and fuels_equivalent(_fuel_name(row), fuel)
        ]
        if not candidates:
            return _fail(f"No non-road CH4/N2O row matches {vehicle} / {fuel}")
        if len(candidates) > 1:
            return _fail(f"More than one non-road row matches {vehicle} / {fuel}")
        gas_row = candidates[0]
        activity_for_gas = activity

    ch4_factor, ch4_key_used, ch4_error = _gas_factor(gas_row, ch4_key)
    n2o_factor, n2o_key_used, n2o_error = _gas_factor(gas_row, n2o_key)
    if ch4_error or n2o_error or ch4_factor is None or n2o_factor is None or ch4_key_used is None or n2o_key_used is None:
        return _fail(ch4_error or n2o_error or "CH4 and N2O factors are required")

    co2_mass = activity * co2_factor
    ch4_mass = activity_for_gas * ch4_factor / _THOUSAND
    n2o_mass = activity_for_gas * n2o_factor / _THOUSAND
    co2_co2e = co2_mass * gwp["CO2"]
    ch4_co2e = ch4_mass * gwp["CH4"]
    n2o_co2e = n2o_mass * gwp["N2O"]

    if treatment == "biogenic_co2_outside_scope1":
        scope_total = ch4_co2e + n2o_co2e
        biogenic = co2_mass
        co2_reporting = "biogenic_outside_scope1"
    else:
        scope_total = co2_co2e + ch4_co2e + n2o_co2e
        biogenic = Decimal("0")
        co2_reporting = "scope1"

    gases = {
        "co2": {
            "mass_kg": _decimal_text(co2_mass),
            "gwp": _decimal_text(gwp["CO2"]),
            "co2e_kg": _decimal_text(co2_co2e),
            "reporting": co2_reporting,
        },
        "ch4": {
            "mass_kg": _decimal_text(ch4_mass),
            "gwp": _decimal_text(gwp["CH4"]),
            "co2e_kg": _decimal_text(ch4_co2e),
            "reporting": "scope1",
        },
        "n2o": {
            "mass_kg": _decimal_text(n2o_mass),
            "gwp": _decimal_text(gwp["N2O"]),
            "co2e_kg": _decimal_text(n2o_co2e),
            "reporting": "scope1",
        },
    }
    factors = {
        "co2": {
            "value": _decimal_text(co2_factor),
            "unit": f"kg CO2 / {activity_unit}",
            **_row_source(co2_source, co2_row, _original_key(co2_index, _KEY_CO2)),
        },
        "ch4": {
            "value": _decimal_text(ch4_factor),
            "unit": gas_unit,
            **_row_source(gas_source, gas_row, ch4_key_used),
        },
        "n2o": {
            "value": _decimal_text(n2o_factor),
            "unit": gas_unit,
            **_row_source(gas_source, gas_row, n2o_key_used),
        },
    }
    accounting = {
        "version": ACCOUNTING_VERSION,
        "treatment": treatment,
        "methodology": METHODOLOGY,
        "gwp_version": "AR5",
        "gwp": {name: _decimal_text(value) for name, value in gwp.items()},
        "biogenic_co2_kg": _decimal_text(biogenic),
        "biogenic_co2_t": _decimal_text(biogenic / _THOUSAND),
        "scope1_kg_co2e": _decimal_text(scope_total),
        "scope1_t_co2e": _decimal_text(scope_total / _THOUSAND),
        "publication_year": None,
    }
    return {
        "success": True,
        "review_required": False,
        "road_class": road,
        "vehicle_type": vehicle,
        "fuel": fuel,
        "model_year": None if year is None else str(year),
        "fuel_quantity": _decimal_text(amount),
        "fuel_unit": activity_unit,
        "distance": None if miles is None else _decimal_text(miles),
        "distance_unit": None if miles is None else "mile",
        "gases": gases,
        "total_kg_co2e": accounting["scope1_kg_co2e"],
        "total_t_co2e": accounting["scope1_t_co2e"],
        "biogenic_co2_kg": accounting["biogenic_co2_kg"],
        "biogenic_co2_t": accounting["biogenic_co2_t"],
        "factors": factors,
        "factor_source": {
            "gwp_version": "AR5",
            "gwp": accounting["gwp"],
            "datasets": [co2_source, gas_source],
            "publication_year": None,
        },
        "accounting": accounting,
    }
