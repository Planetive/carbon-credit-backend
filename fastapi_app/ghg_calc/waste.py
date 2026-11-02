"""
Waste generated / end-of-life — EPA Hub / WARM style factors.

Formula (verified unit): emissions_kg =
  (mass_converted_to_short_tons) × factor[MTCO2e/short ton] × 1000

Refuse when factor_unit or mass_unit is missing/unsupported.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from ._common import fail_payload, norm_cell, parse_number, success_payload
from .scope3_factor_units import WASTE_DATASET_FACTOR_UNIT, waste_emissions_kg

DISPOSAL_METHODS = [
    "Recycled",
    "Landfilled",
    "Combusted",
    "Composted",
    "Anaerobically Digested (Dry Digestate with Curing)",
    "Anaerobically Digested (Wet Digestate with Curing)",
]


def _norm_key(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def _is_na(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip().lower() in ("n/a", "na", ""):
        return True
    return False


def _material_name(row: Dict[str, Any]) -> str:
    return norm_cell(
        row.get(" Material ")
        or row.get("Material")
        or row.get("material")
        or row.get("label")
    )


def build_waste_materials(table_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in table_rows:
        name = _material_name(row)
        if not name:
            continue
        material: Dict[str, Any] = {"material": name}
        for method in DISPOSAL_METHODS:
            val = row.get(method)
            if val is None:
                target = _norm_key(method)
                for k, v in row.items():
                    if _norm_key(str(k)) == target:
                        val = v
                        break
            material[method] = val
        out.append(material)
    return out


def get_emission_factor(
    material: Optional[Dict[str, Any]], disposal_method: str
) -> Optional[float]:
    if not material:
        return None
    value = material.get(disposal_method)
    if value is None:
        target = _norm_key(disposal_method)
        for k, v in material.items():
            if _norm_key(str(k)) == target:
                value = v
                break
    if _is_na(value):
        return None
    return parse_number(value)


def calculate_waste(
    *,
    volume: float,
    disposal_method: str,
    material: Optional[str] = None,
    factor: Optional[float] = None,
    materials: Optional[List[Dict[str, Any]]] = None,
    factor_unit: Optional[str] = None,
    mass_unit: Optional[str] = None,
) -> Dict[str, Any]:
    resolved = factor
    mat_row = None
    if resolved is None and materials and material:
        mat_row = next(
            (m for m in materials if m.get("material") == material),
            None,
        )
        if mat_row is None:
            lower = material.lower()
            mat_row = next(
                (m for m in materials if str(m.get("material", "")).lower() == lower),
                None,
            )
        resolved = get_emission_factor(mat_row, disposal_method)

    if resolved is None:
        return fail_payload("Could not resolve waste emission factor")

    # Refuse missing units — callers must pass the verified sheet unit
    # (WASTE_DATASET_FACTOR_UNIT for public.waste / EPA Hub Table 9).
    if not factor_unit:
        return fail_payload(
            "Waste factor unit missing; pass verified unit "
            f"(e.g. {WASTE_DATASET_FACTOR_UNIT})"
        )
    if not mass_unit:
        return fail_payload("Waste mass unit missing; refuse calculation")

    fu = factor_unit
    mu = mass_unit

    emissions_kg, err = waste_emissions_kg(
        mass=float(volume),
        mass_unit=mu,
        factor=float(resolved),
        factor_unit=fu,
    )
    if err or emissions_kg is None:
        return fail_payload(err or "Waste calculation failed")

    return success_payload(
        emissions_kg,
        factor=float(resolved),
        extra={
            "material": material,
            "disposal_method": disposal_method,
            "volume": volume,
            "mass_unit": mu,
            "factor_unit": fu,
        },
    )
