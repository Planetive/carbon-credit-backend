"""
Waste generated — ported from SPA wasteTypes.ts + Scope3Section.tsx.

Formula: emissions = volume * disposal_method_factor  (no toFixed on store)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ._common import fail_payload, norm_cell, parse_number, success_payload

DISPOSAL_METHODS = [
    "Recycled",
    "Landfilled",
    "Combusted",
    "Composted",
    "Anaerobically Digested (Dry Digestate with Curing)",
    "Anaerobically Digested (Wet Digestate with Curing)",
]


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
            # Prefer exact column; also try stripped variants in attributes
            val = row.get(method)
            if val is None:
                for k, v in row.items():
                    if norm_cell(k) == method:
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
) -> Dict[str, Any]:
    resolved = factor
    mat_row = None
    if resolved is None and materials and material:
        mat_row = next(
            (m for m in materials if m.get("material") == material),
            None,
        )
        if mat_row is None:
            # case-insensitive fallback
            lower = material.lower()
            mat_row = next(
                (m for m in materials if str(m.get("material", "")).lower() == lower),
                None,
            )
        resolved = get_emission_factor(mat_row, disposal_method)

    if resolved is None:
        return fail_payload("Could not resolve waste emission factor")

    emissions_kg = float(volume) * float(resolved)
    return success_payload(
        emissions_kg,
        factor=float(resolved),
        extra={
            "material": material,
            "disposal_method": disposal_method,
            "volume": volume,
        },
    )
