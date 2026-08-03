"""
EPA stationary fuel calc — ported from SPA FuelEmissions.tsx (factorMode=epa).

Stage A: build synthetic unit keys from Fuel EPA 1/2/3 sheet columns.
Stage B: emissions = quantity * factor; if unit starts with CH4|N2O → /1000 (g→kg gas).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .uk_fuel import parse_number


def build_epa_fuel_map(
    table_rows: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Dict[str, float]]]:
    """
    category → fuel → synthetic_unit → factor
    Exact port of loadFuelFactors() in FuelEmissions.tsx.
    """
    factors_map: Dict[str, Dict[str, Dict[str, float]]] = {}

    for row in table_rows:
        category = str(
            row.get("Category")
            or row.get("category")
            or row.get("Fuel Category")
            or row.get("fuel_category")
            or ""
        ).strip()
        fuel = str(
            row.get("Fuel Type")
            or row.get("Fuel")
            or row.get("fuel_type")
            or row.get("fuel")
            or ""
        ).strip()
        if not category or not fuel:
            continue

        hhv = parse_number(
            row.get("Heat Content (HHV)")
            or row.get("Heat Content")
            or row.get("HeatContent")
            or row.get("heat_content_hhv")
            or row.get("hhv")
        )
        hhv_unit_raw = (
            row.get("HHV Unit")
            or row.get("HIV Unit")
            or row.get("hhv_unit")
            or row.get("hiv_unit")
            or row.get("heat_content_unit")
        )
        hhv_unit = str(hhv_unit_raw).lower() if isinstance(hhv_unit_raw, str) else ""
        is_scf_based_hhv = hhv is not None and "scf" in hhv_unit

        co2_unit = str(row.get("CO2 Unit") or "").lower()
        ch4_unit = str(row.get("CH4 Unit") or "").lower()
        # N20 typo in Fuel EPA 1 is intentional
        n2o_unit_first = str(row.get("N20 Unit") or row.get("N2O Unit") or "").lower()
        use_first_set_mmbtu = "mmbtu" in co2_unit

        co2_per_mmbtu = (
            parse_number(row.get("CO2 Factor")) if use_first_set_mmbtu else None
        )
        ch4_per_mmbtu = (
            parse_number(row.get("CH4 Factor")) if "mmbtu" in ch4_unit else None
        )
        n2o_per_mmbtu = (
            parse_number(row.get("N2O Factor")) if "mmbtu" in n2o_unit_first else None
        )

        co2_unit1 = str(row.get("CO2 Unit_1") or "").lower()
        ch4_unit1 = str(row.get("CH4 Unit_1") or "").lower()
        n2o_unit1 = str(row.get("N2O Unit_1") or row.get("N2O Unit") or "").lower()
        co2_factor1 = parse_number(row.get("CO2 Factor_1"))
        ch4_factor1 = parse_number(row.get("CH4 Factor_1"))
        n2o_factor1 = parse_number(row.get("N2O Factor_1"))

        factors_map.setdefault(category, {}).setdefault(fuel, {})
        fuel_map = factors_map[category][fuel]

        if co2_per_mmbtu is not None:
            fuel_map["CO2 (kg CO2 / mmBtu)"] = co2_per_mmbtu
            if is_scf_based_hhv:
                fuel_map["CO2 (kg CO2 / MMSCF)"] = co2_per_mmbtu * hhv * 1_000_000
        if ch4_per_mmbtu is not None:
            fuel_map["CH4 (g CH4 / mmBtu)"] = ch4_per_mmbtu
            if is_scf_based_hhv:
                fuel_map["CH4 (g CH4 / MMSCF)"] = ch4_per_mmbtu * hhv * 1_000_000
        if n2o_per_mmbtu is not None:
            fuel_map["N2O (g N2O / mmBtu)"] = n2o_per_mmbtu
            if is_scf_based_hhv:
                fuel_map["N2O (g N2O / MMSCF)"] = n2o_per_mmbtu * hhv * 1_000_000

        if "short ton" in co2_unit1 and co2_factor1 is not None:
            fuel_map["CO2 (kg CO2 / short ton)"] = co2_factor1
        if "short ton" in ch4_unit1 and ch4_factor1 is not None:
            fuel_map["CH4 (g CH4 / short ton)"] = ch4_factor1
        if "short ton" in n2o_unit1 and n2o_factor1 is not None:
            fuel_map["N2O (g N2O / short ton)"] = n2o_factor1

        if (
            "scf" in co2_unit1
            and co2_factor1 is not None
            and fuel_map.get("CO2 (kg CO2 / MMSCF)") is None
        ):
            fuel_map["CO2 (kg CO2 / MMSCF)"] = co2_factor1 * 1_000_000
        if (
            "scf" in ch4_unit1
            and ch4_factor1 is not None
            and fuel_map.get("CH4 (g CH4 / MMSCF)") is None
        ):
            fuel_map["CH4 (g CH4 / MMSCF)"] = ch4_factor1 * 1_000_000
        if (
            "scf" in n2o_unit1
            and n2o_factor1 is not None
            and fuel_map.get("N2O (g N2O / MMSCF)") is None
        ):
            fuel_map["N2O (g N2O / MMSCF)"] = n2o_factor1 * 1_000_000

        if "gallon" in co2_unit1 and co2_factor1 is not None:
            fuel_map["CO2 (kg CO2 / gallon)"] = co2_factor1
        if "gallon" in ch4_unit1 and ch4_factor1 is not None:
            fuel_map["CH4 (g CH4 / gallon)"] = ch4_factor1
        if "gallon" in n2o_unit1 and n2o_factor1 is not None:
            fuel_map["N2O (g N2O / gallon)"] = n2o_factor1

    return factors_map


def calculate_epa_fuel_emissions(quantity: float, factor: float, unit: str) -> float:
    """
    SPA: raw = quantity * factor;
         if unit starts with CH4 or N2O: raw / 1000
         emissions = Number(raw.toFixed(6))
    """
    raw = quantity * factor
    is_g_per_unit = isinstance(unit, str) and (
        unit.startswith("CH4") or unit.startswith("N2O")
    )
    value = raw / 1000.0 if is_g_per_unit else raw
    return float(f"{value:.6f}")


def calculate_epa_fuel(
    *,
    quantity: float,
    unit: str,
    category: Optional[str] = None,
    fuel: Optional[str] = None,
    factor: Optional[float] = None,
    factors_map: Optional[Dict[str, Dict[str, Dict[str, float]]]] = None,
) -> Dict[str, Any]:
    resolved_factor = factor
    if resolved_factor is None and factors_map and category and fuel and unit:
        looked = factors_map.get(category, {}).get(fuel, {}).get(unit)
        resolved_factor = looked if isinstance(looked, (int, float)) else None

    if resolved_factor is None:
        return {
            "success": False,
            "error": "Could not resolve factor",
            "emissions": None,
            "emissions_kg": None,
            "emissions_tco2e": None,
            "factor": None,
        }

    emissions_kg = calculate_epa_fuel_emissions(quantity, float(resolved_factor), unit)
    return {
        "success": True,
        "emissions": emissions_kg,
        "emissions_kg": emissions_kg,
        "emissions_tco2e": float(f"{(emissions_kg / 1000.0):.9f}"),
        "factor": float(resolved_factor),
        "category": category,
        "fuel": fuel,
        "unit": unit,
        "quantity": quantity,
    }
