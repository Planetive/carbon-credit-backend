"""
Backend-authoritative EPA Scope 1 stationary combustion.

Looks up CO2, CH4, and N2O on Fuel EPA 1/2/3. The caller cannot supply the
factor or the total. CH4 and N2O sheet values are grams of that gas; CO2 sheet
values are kilograms of CO2. GWP is applied after the gram-to-kilogram conversion.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Mapping, Optional, Sequence

GWP_SETS = {
    "AR5": {
        "CO2": Decimal("1"),
        "CH4": Decimal("28"),
        "N2O": Decimal("265"),
    }
}

_UNIT_ALIASES = {
    "mmbtu": "mmBtu",
    "mm btu": "mmBtu",
    "short ton": "short ton",
    "short tons": "short ton",
    "shortton": "short ton",
    "us short ton": "short ton",
    "gallon": "gallon",
    "gallons": "gallon",
    "us gallon": "gallon",
    "gal": "gallon",
    "mmscf": "MMSCF",
    "mm scf": "MMSCF",
}

_FACTOR_UNITS = {
    "mmBtu": {
        "co2": "kg CO2 / mmBtu",
        "ch4": "g CH4 / mmBtu",
        "n2o": "g N2O / mmBtu",
    },
    "short ton": {
        "co2": "kg CO2 / short ton",
        "ch4": "g CH4 / short ton",
        "n2o": "g N2O / short ton",
    },
    "gallon": {
        "co2": "kg CO2 / gallon",
        "ch4": "g CH4 / gallon",
        "n2o": "g N2O / gallon",
    },
    "MMSCF": {
        "co2": "kg CO2 / MMSCF",
        "ch4": "g CH4 / MMSCF",
        "n2o": "g N2O / MMSCF",
    },
}

_GRAM_GASES = ("ch4", "n2o")
_GASES = ("co2", "ch4", "n2o")
_MILLION = Decimal("1000000")
_THOUSAND = Decimal("1000")


def canonical_consumption_unit(unit: str) -> Optional[str]:
    key = " ".join(str(unit).strip().lower().split())
    return _UNIT_ALIASES.get(key)


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


def _unit_text(value: Any) -> str:
    return str(value).lower() if isinstance(value, str) else ""


def _contains(unit_text: str, token: str) -> bool:
    return token in unit_text


def factors_for_row(row: Mapping[str, Any]) -> Dict[str, Dict[str, Decimal]]:
    """Physical unit -> gas -> sheet factor. CH4 and N2O stay in grams."""
    hhv = _parse_decimal(
        row.get("Heat Content (HHV)")
        or row.get("Heat Content")
        or row.get("HeatContent")
        or row.get("heat_content_hhv")
        or row.get("hhv")
    )
    hhv_unit = _unit_text(
        row.get("HHV Unit")
        or row.get("HIV Unit")
        or row.get("hhv_unit")
        or row.get("hiv_unit")
        or row.get("heat_content_unit")
    )

    co2_per_mmbtu = (
        _parse_decimal(row.get("CO2 Factor"))
        if _contains(_unit_text(row.get("CO2 Unit")), "mmbtu")
        else None
    )
    ch4_per_mmbtu = (
        _parse_decimal(row.get("CH4 Factor"))
        if _contains(_unit_text(row.get("CH4 Unit")), "mmbtu")
        else None
    )
    n2o_unit_first = _unit_text(row.get("N20 Unit") or row.get("N2O Unit"))
    n2o_per_mmbtu = (
        _parse_decimal(row.get("N2O Factor"))
        if _contains(n2o_unit_first, "mmbtu")
        else None
    )

    co2_unit_1 = _unit_text(row.get("CO2 Unit_1"))
    ch4_unit_1 = _unit_text(row.get("CH4 Unit_1"))
    n2o_unit_1_raw = row.get("N2O Unit_1")
    if n2o_unit_1_raw is None or (isinstance(n2o_unit_1_raw, str) and not n2o_unit_1_raw.strip()):
        n2o_unit_1_raw = row.get("N2O Unit")
    n2o_unit_1 = _unit_text(n2o_unit_1_raw)
    co2_factor_1 = _parse_decimal(row.get("CO2 Factor_1"))
    ch4_factor_1 = _parse_decimal(row.get("CH4 Factor_1"))
    n2o_factor_1 = _parse_decimal(row.get("N2O Factor_1"))

    by_unit: Dict[str, Dict[str, Decimal]] = {}

    mmbtu = {
        "co2": co2_per_mmbtu,
        "ch4": ch4_per_mmbtu,
        "n2o": n2o_per_mmbtu,
    }
    if all(mmbtu[gas] is not None for gas in _GASES):
        by_unit["mmBtu"] = mmbtu  # type: ignore[assignment]

    def _second(token: str, unit_name: str) -> None:
        picked = {
            "co2": co2_factor_1 if _contains(co2_unit_1, token) else None,
            "ch4": ch4_factor_1 if _contains(ch4_unit_1, token) else None,
            "n2o": n2o_factor_1 if _contains(n2o_unit_1, token) else None,
        }
        if all(picked[gas] is not None for gas in _GASES):
            by_unit[unit_name] = picked  # type: ignore[assignment]

    _second("short ton", "short ton")
    _second("gallon", "gallon")

    if hhv is not None and _contains(hhv_unit, "scf") and "mmBtu" in by_unit:
        by_unit["MMSCF"] = {
            gas: by_unit["mmBtu"][gas] * hhv * _MILLION for gas in _GASES
        }
    elif (
        _contains(co2_unit_1, "scf")
        and _contains(ch4_unit_1, "scf")
        and _contains(n2o_unit_1, "scf")
        and all(value is not None for value in (co2_factor_1, ch4_factor_1, n2o_factor_1))
        and "MMSCF" not in by_unit
    ):
        by_unit["MMSCF"] = {
            "co2": co2_factor_1 * _MILLION,  # type: ignore[operator]
            "ch4": ch4_factor_1 * _MILLION,  # type: ignore[operator]
            "n2o": n2o_factor_1 * _MILLION,  # type: ignore[operator]
        }

    return by_unit


def _sheet_source(sheet: Mapping[str, Any]) -> Dict[str, Optional[str]]:
    return {
        "publisher": sheet.get("publisher") or "EPA",
        "dataset_code": sheet.get("dataset_code"),
        "dataset_title": sheet.get("dataset_title"),
        "version_label": sheet.get("version_label"),
        "dataset_id": sheet.get("dataset_id"),
        "effective_from": sheet.get("effective_from"),
        "effective_to": sheet.get("effective_to"),
        "source_notes": sheet.get("source_notes"),
    }


def index_stationary_sheets(
    sheets: Sequence[Mapping[str, Any]],
) -> Dict[tuple, Dict[str, Any]]:
    """category/fuel -> factors and the dataset that supplied the row."""
    index: Dict[tuple, Dict[str, Any]] = {}
    for sheet in sheets:
        source = _sheet_source(sheet)
        for row in sheet.get("rows") or []:
            if not isinstance(row, Mapping):
                continue
            category = str(
                row.get("Category") or row.get("category") or ""
            ).strip()
            fuel = str(
                row.get("Fuel Type") or row.get("Fuel") or row.get("fuel") or ""
            ).strip()
            if not category or not fuel:
                continue
            parsed = factors_for_row(row)
            if not parsed:
                continue
            key = (category.casefold(), fuel.casefold())
            entry = index.setdefault(
                key,
                {
                    "category": category,
                    "fuel": fuel,
                    "by_unit": {},
                    "source": source,
                },
            )
            entry["by_unit"].update(parsed)
            entry["source"] = source
            if row.get("_factor_dataset_id"):
                entry["factor_dataset_id"] = str(row.get("_factor_dataset_id"))
            if row.get("_factor_row_id"):
                entry["factor_row_id"] = str(row.get("_factor_row_id"))
    return index


def _fail(message: str) -> Dict[str, Any]:
    return {
        "success": False,
        "error": message,
        "gases": None,
        "total_kg_co2e": None,
        "total_t_co2e": None,
    }


def _gwp_set(version: str) -> Optional[Dict[str, Decimal]]:
    return GWP_SETS.get(str(version).strip().upper())


def calculate_stationary_combustion(
    *,
    fuel: str,
    quantity: Any,
    unit: str,
    sheets: Sequence[Mapping[str, Any]],
    category: Optional[str] = None,
    gwp_version: str = "AR5",
    factor: Any = None,
    emissions: Any = None,
    emissions_kg: Any = None,
    total_kg_co2e: Any = None,
    total_t_co2e: Any = None,
    **_ignored: Any,
) -> Dict[str, Any]:
    """
    Calculate all three gases from the factor sheets.

    `factor`, `emissions`, `emissions_kg`, and the total arguments are accepted
    and discarded so a frontend value cannot replace the dataset.
    """
    del factor, emissions, emissions_kg, total_kg_co2e, total_t_co2e, _ignored

    gwp = _gwp_set(gwp_version)
    if gwp is None:
        known = ", ".join(sorted(GWP_SETS))
        return _fail(f"gwp_version must be one of: {known}")

    amount = _parse_decimal(quantity)
    if amount is None or amount < 0:
        return _fail("quantity must be a finite number greater than or equal to 0")

    physical = canonical_consumption_unit(unit)
    if physical is None:
        allowed = "mmBtu, short ton, gallon, MMSCF"
        return _fail(f"unit is not a supported consumption unit ({allowed})")

    fuel_name = str(fuel or "").strip()
    if not fuel_name:
        return _fail("fuel is required")

    index = index_stationary_sheets(sheets)
    fuel_key = fuel_name.casefold()
    category_key = str(category).strip().casefold() if category and str(category).strip() else None
    hits = [
        entry
        for (cat_key, name_key), entry in index.items()
        if name_key == fuel_key and (category_key is None or cat_key == category_key)
    ]
    if not hits:
        return _fail("No EPA stationary factor matches this fuel")
    if len(hits) > 1:
        return _fail("fuel matches more than one category; category is required")

    entry = hits[0]
    bundle = entry["by_unit"].get(physical)
    if not bundle or any(bundle.get(gas) is None for gas in _GASES):
        return _fail(f"{entry['fuel']} has no complete CO2, CH4, and N2O factors for {physical}")

    gases: Dict[str, Dict[str, str]] = {}
    factors: Dict[str, Dict[str, str]] = {}
    total = Decimal("0")
    for gas in _GASES:
        sheet_factor = bundle[gas]
        mass = amount * sheet_factor
        if gas in _GRAM_GASES:
            mass = mass / _THOUSAND
        gwp_value = gwp["CO2"] if gas == "co2" else gwp[gas.upper()]
        co2e = mass * gwp_value
        total += co2e
        gases[gas] = {
            "mass_kg": _decimal_text(mass),
            "gwp": _decimal_text(gwp_value),
            "co2e_kg": _decimal_text(co2e),
        }
        factors[gas] = {
            "value": _decimal_text(sheet_factor),
            "unit": _FACTOR_UNITS[physical][gas],
        }

    source = dict(entry["source"])
    source["gwp_version"] = str(gwp_version).strip().upper()
    source["gwp"] = {name: _decimal_text(value) for name, value in gwp.items()}
    if entry.get("factor_dataset_id"):
        source["dataset_id"] = entry["factor_dataset_id"]
    if entry.get("factor_row_id"):
        source["factor_row_id"] = entry["factor_row_id"]

    return {
        "success": True,
        "fuel": entry["fuel"],
        "category": entry["category"],
        "quantity": _decimal_text(amount),
        "unit": physical,
        "gases": gases,
        "total_kg_co2e": _decimal_text(total),
        "total_t_co2e": _decimal_text(total / _THOUSAND),
        "factors": factors,
        "factor_source": source,
    }
