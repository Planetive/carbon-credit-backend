"""
Heat & steam — ported from SPA HeatSteamEmissions.tsx.

Formula:
  qty_base = quantity * 1037 if quantity_unit==mmscf and supports_mmscf else quantity
  CO2: Number((qty_base * factor).toFixed(6))
  CH4/N2O: Number(((qty_base * factor) / 1000).toFixed(6))  # g→kg gas
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from ._common import (
    fail_payload,
    norm_cell,
    parse_number,
    pick_first_value,
    round6,
    success_payload,
)

HEAT_DEFAULT_FACTOR = 0.17355
MMBTU_PER_MMSCF = 1037
Gas = Literal["co2", "ch4", "n2o"]


def build_heat_steam_rows(table_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in table_rows:
        typ = norm_cell(
            row.get("Type") or row.get("type") or row.get("Activity") or row.get("activity")
        )
        unit = norm_cell(row.get("Unit") or row.get("unit"))
        if not typ:
            continue

        co2_raw = (
            pick_first_value(row, [r"^kg\s*CO2\s*/\s*mmBtu$", r"CO2.*mmBtu"])
            or row.get("kg CO₂e")
            or row.get("kg CO2e")
            or row.get("kg_co2e")
        )
        ch4_raw = (
            pick_first_value(row, [r"CH4.*mmBtu", r"g\s*CH4.*mmBtu"])
            or row.get("CH4")
            or row.get("CH₄")
            or row.get("ch4")
            or row.get("CH4 Factor")
            or row.get("ch4_factor")
        )
        n2o_raw = (
            pick_first_value(row, [r"N2O.*mmBtu", r"g\s*N2O.*mmBtu"])
            or row.get("N2O")
            or row.get("N20")
            or row.get("n2o")
            or row.get("N2O Factor")
            or row.get("n2o_factor")
        )

        co2 = parse_number(co2_raw)
        ch4 = parse_number(ch4_raw)
        n2o = parse_number(n2o_raw)
        supports_mmscf = "mmbtu" in unit.lower() if unit else False

        out.append(
            {
                "type": typ,
                "unit": unit,
                "co2_factor": co2 if co2 is not None else HEAT_DEFAULT_FACTOR,
                "ch4_factor": ch4,
                "n2o_factor": n2o,
                "supports_mmscf": supports_mmscf,
            }
        )
    return out


def compute_emissions_kg(gas: Gas, factor_per_unit: float, quantity_in_base: float) -> float:
    if gas == "co2":
        return round6(quantity_in_base * factor_per_unit)
    return round6((quantity_in_base * factor_per_unit) / 1000.0)


def calculate_heat_steam(
    *,
    quantity: float,
    gas: Gas = "co2",
    quantity_unit: str = "base",
    entry_type: Optional[str] = None,
    unit: Optional[str] = None,
    co2_factor: Optional[float] = None,
    ch4_factor: Optional[float] = None,
    n2o_factor: Optional[float] = None,
    factor_rows: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    row = None
    if factor_rows and entry_type:
        row = next((r for r in factor_rows if r["type"] == entry_type), None)
        if row is None:
            # SPA maps district ↔ "District steam and heat"
            lower = entry_type.lower()
            if "district" in lower:
                row = next(
                    (r for r in factor_rows if "district" in r["type"].lower()), None
                )
            else:
                row = next(
                    (
                        r
                        for r in factor_rows
                        if "steam" in r["type"].lower() or "heat" in r["type"].lower()
                    ),
                    None,
                )

    if row:
        co2_factor = co2_factor if co2_factor is not None else row.get("co2_factor")
        ch4_factor = ch4_factor if ch4_factor is not None else row.get("ch4_factor")
        n2o_factor = n2o_factor if n2o_factor is not None else row.get("n2o_factor")
        unit = unit or row.get("unit")
        supports = bool(row.get("supports_mmscf"))
    else:
        supports = bool(unit and "mmbtu" in str(unit).lower())

    if gas == "co2":
        factor = (
            float(co2_factor)
            if co2_factor is not None
            else HEAT_DEFAULT_FACTOR
        )
    elif gas == "ch4":
        if ch4_factor is None and co2_factor is None and row is None:
            return fail_payload("Could not resolve CH4 heat/steam factor")
        factor = float(ch4_factor) if ch4_factor is not None else HEAT_DEFAULT_FACTOR
    else:
        if n2o_factor is None and co2_factor is None and row is None:
            return fail_payload("Could not resolve N2O heat/steam factor")
        factor = float(n2o_factor) if n2o_factor is not None else HEAT_DEFAULT_FACTOR

    # SPA resolveHeatSteamEmissionsKg: once quantity_unit is "mmscf" on the wire,
    # always convert ×1037 (no supports_mmscf gate).
    if str(quantity_unit or "").lower() == "mmscf":
        qty_base = float(quantity) * MMBTU_PER_MMSCF
    else:
        qty_base = float(quantity)
    emissions_kg = compute_emissions_kg(gas, factor, qty_base)
    return success_payload(
        emissions_kg,
        factor=factor,
        extra={
            "entry_type": entry_type,
            "unit": unit,
            "gas": gas,
            "quantity": quantity,
            "quantity_unit": quantity_unit,
            "quantity_in_base": qty_base,
            "supports_mmscf": supports,
        },
    )
