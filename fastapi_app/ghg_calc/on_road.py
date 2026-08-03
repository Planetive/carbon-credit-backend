"""
EPA on-road gasoline / diesel+alt — ported from SPA OnRoad*Emissions.tsx.

Formula (gas-only kg; no GWP / no toFixed on raw calc):
  miles = distance if unit==mile else distance * 0.621371
  emissions = (ch4|n2o_g_per_mile * miles) / 1000
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

KM_TO_MILES = 0.621371


def _normalize_selection(selection: str) -> str:
    s = (selection or "ch4_only").lower()
    if s in ("ch4", "ch4_only"):
        return "ch4"
    return "n2o"


def build_on_road_gasoline_rows(table_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in table_rows:
        vehicle_type = norm_cell(
            pick_first_key(r, [r"^Vehicle\s*Type$", r"vehicle[_\s]*type"])
            or r.get("VehicleType")
            or r.get("vehicle_type")
            or r.get("vehicleType")
        )
        model_year = norm_cell(
            pick_first_key(r, [r"^Model\s*Year$", r"model[_\s]*year", r"year"])
            or r.get("ModelYear")
            or r.get("model_year")
            or r.get("modelYear")
        )
        if not vehicle_type or not model_year:
            continue
        out.append(
            {
                "vehicle_type": vehicle_type,
                "model_year": model_year,
                "co2e_g_per_mile": pick_number(
                    r, [r"co2e\s*factor", r"co2[_\s]*equivalent", r"ghg\s*factor"]
                ),
                "co2_g_per_mile": pick_number(r, [r"^CO2\s*Factor", r"co2[_\s]*factor"]),
                "ch4_g_per_mile": pick_number(r, [r"^CH4\s*Factor", r"ch4[_\s]*factor"]),
                "n2o_g_per_mile": pick_number(r, [r"^N2O\s*Factor", r"n2o[_\s]*factor"]),
            }
        )
    return out


def build_on_road_diesel_rows(table_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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
        model_year_raw = (
            pick_first_key(r, [r"^Model\s*Year$", r"model[_\s]*year", r"year"])
            or r.get("model_year")
            or r.get("modelYear")
        )
        model_year = norm_cell(model_year_raw) or None
        if not vehicle_type or not fuel_type:
            continue
        out.append(
            {
                "vehicle_type": vehicle_type,
                "fuel_type": fuel_type,
                "model_year": model_year if model_year else None,
                "co2e_g_per_mile": pick_number(
                    r, [r"co2e\s*factor", r"co2[_\s]*equivalent", r"ghg\s*factor"]
                ),
                "co2_g_per_mile": pick_number(r, [r"^CO2\s*Factor", r"co2[_\s]*factor"]),
                "ch4_g_per_mile": pick_number(r, [r"^CH4\s*Factor", r"ch4[_\s]*factor"]),
                "n2o_g_per_mile": pick_number(r, [r"^N2O\s*Factor", r"n2o[_\s]*factor"]),
            }
        )
    return out


def _miles_from_distance(distance: float, distance_unit: str) -> float:
    unit = (distance_unit or "mile").lower()
    if unit in ("km", "kilometer", "kilometre"):
        return float(distance) * KM_TO_MILES
    return float(distance)


def calculate_on_road_gasoline(
    *,
    distance: float,
    distance_unit: str = "mile",
    vehicle_type: Optional[str] = None,
    model_year: Optional[str] = None,
    emission_selection: str = "ch4_only",
    ch4_g_per_mile: Optional[float] = None,
    n2o_g_per_mile: Optional[float] = None,
    factor_rows: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    ch4 = ch4_g_per_mile
    n2o = n2o_g_per_mile

    if ch4 is None and n2o is None:
        if factor_rows and vehicle_type and model_year:
            hit = next(
                (
                    f
                    for f in factor_rows
                    if f["vehicle_type"] == vehicle_type
                    and f["model_year"] == str(model_year)
                ),
                None,
            )
            if not hit:
                return fail_payload("Could not resolve on-road gasoline factor row")
            ch4 = hit.get("ch4_g_per_mile")
            n2o = hit.get("n2o_g_per_mile")
        else:
            return fail_payload(
                "Provide ch4/n2o factors or vehicle_type+model_year with factor_rows"
            )

    miles = _miles_from_distance(distance, distance_unit)
    sel = _normalize_selection(emission_selection)
    factor = float(ch4 or 0) if sel == "ch4" else float(n2o or 0)
    emissions_kg = (factor * miles) / 1000.0
    return success_payload(
        emissions_kg,
        factor=factor,
        extra={
            "vehicle_type": vehicle_type,
            "model_year": model_year,
            "distance": distance,
            "distance_unit": distance_unit,
            "miles": miles,
            "emission_selection": sel,
            "gas": "CH4" if sel == "ch4" else "N2O",
        },
    )


def calculate_on_road_diesel(
    *,
    distance: float,
    distance_unit: str = "mile",
    vehicle_type: Optional[str] = None,
    fuel_type: Optional[str] = None,
    model_year: Optional[str] = None,
    emission_selection: str = "ch4",
    ch4_g_per_mile: Optional[float] = None,
    n2o_g_per_mile: Optional[float] = None,
    factor_rows: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    ch4 = ch4_g_per_mile
    n2o = n2o_g_per_mile

    if ch4 is None and n2o is None:
        if factor_rows and vehicle_type and fuel_type:
            matches = [
                f
                for f in factor_rows
                if f["vehicle_type"] == vehicle_type and f["fuel_type"] == fuel_type
            ]
            needs_year = any(f.get("model_year") for f in matches)
            hit = None
            if needs_year:
                if model_year:
                    hit = next(
                        (m for m in matches if m.get("model_year") == str(model_year)),
                        None,
                    )
            else:
                hit = next((m for m in matches if not m.get("model_year")), None) or (
                    matches[0] if matches else None
                )
            if not hit:
                return fail_payload("Could not resolve on-road diesel factor row")
            ch4 = hit.get("ch4_g_per_mile")
            n2o = hit.get("n2o_g_per_mile")
        else:
            return fail_payload(
                "Provide ch4/n2o factors or vehicle_type+fuel_type with factor_rows"
            )

    miles = _miles_from_distance(distance, distance_unit)
    sel = _normalize_selection(emission_selection)
    factor = float(ch4 or 0) if sel == "ch4" else float(n2o or 0)
    emissions_kg = (factor * miles) / 1000.0
    return success_payload(
        emissions_kg,
        factor=factor,
        extra={
            "vehicle_type": vehicle_type,
            "fuel_type": fuel_type,
            "model_year": model_year,
            "distance": distance,
            "distance_unit": distance_unit,
            "miles": miles,
            "emission_selection": sel,
            "gas": "CH4" if sel == "ch4" else "N2O",
        },
    )
