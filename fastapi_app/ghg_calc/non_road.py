"""
EPA non-road vehicle — ported from SPA NonRoadVehicleEmissions.tsx.

Formula:
  gallons = quantity if unit==gallon else quantity / 3.78541
  emissions = (ch4|n2o_g_per_gallon * gallons) / 1000
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ._common import (
    fail_payload,
    norm_cell,
    pick_first_key,
    pick_number,
    success_payload,
)

LITERS_PER_GALLON = 3.78541


def build_non_road_rows(table_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in table_rows:
        vehicle_type = norm_cell(
            pick_first_key(r, [r"^Vehicle\s*Type$", r"vehicle[_\s]*type"])
            or r.get("vehicle_type")
            or r.get("vehicleType")
        )
        fuel_type = norm_cell(
            pick_first_key(r, [r"^Fuel\s*Type$", r"fuel[_\s]*type"])
            or r.get("fuel_type")
            or r.get("fuelType")
        )
        if not vehicle_type or not fuel_type:
            continue
        out.append(
            {
                "vehicle_type": vehicle_type,
                "fuel_type": fuel_type,
                "co2e_g_per_gallon": pick_number(
                    r, [r"co2e\s*factor", r"co2[_\s]*equivalent", r"ghg\s*factor"]
                ),
                "co2_g_per_gallon": pick_number(
                    r, [r"^CO2\s*Factor", r"co2[_\s]*factor", r"g\s*co2"]
                ),
                "ch4_g_per_gallon": pick_number(
                    r, [r"^CH4\s*Factor", r"ch4[_\s]*factor", r"g\s*ch4"]
                ),
                "n2o_g_per_gallon": pick_number(
                    r, [r"^N2O\s*Factor", r"n2o[_\s]*factor", r"g\s*n2o"]
                ),
            }
        )
    return out


def calculate_non_road(
    *,
    quantity: float,
    unit: str = "gallon",
    vehicle_type: Optional[str] = None,
    fuel_type: Optional[str] = None,
    emission_selection: str = "ch4",
    ch4_g_per_gallon: Optional[float] = None,
    n2o_g_per_gallon: Optional[float] = None,
    factor_rows: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    ch4 = ch4_g_per_gallon
    n2o = n2o_g_per_gallon

    if ch4 is None and n2o is None:
        if factor_rows and vehicle_type and fuel_type:
            hit = next(
                (
                    f
                    for f in factor_rows
                    if f["vehicle_type"] == vehicle_type and f["fuel_type"] == fuel_type
                ),
                None,
            )
            if not hit:
                return fail_payload("Could not resolve non-road factor row")
            ch4 = hit.get("ch4_g_per_gallon")
            n2o = hit.get("n2o_g_per_gallon")
        else:
            return fail_payload(
                "Provide ch4/n2o factors or vehicle_type+fuel_type with factor_rows"
            )

    u = (unit or "gallon").lower()
    gallons = float(quantity) if u == "gallon" else float(quantity) / LITERS_PER_GALLON
    sel = "ch4" if (emission_selection or "ch4").lower() in ("ch4", "ch4_only") else "n2o"
    factor = float(ch4 or 0) if sel == "ch4" else float(n2o or 0)
    emissions_kg = (factor * gallons) / 1000.0
    return success_payload(
        emissions_kg,
        factor=factor,
        extra={
            "vehicle_type": vehicle_type,
            "fuel_type": fuel_type,
            "quantity": quantity,
            "unit": unit,
            "gallons": gallons,
            "emission_selection": sel,
            "gas": "CH4" if sel == "ch4" else "N2O",
        },
    )
