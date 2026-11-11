"""
Absolute (pre-attribution) emissions helpers shared by standalone FE and SSP.

These functions return company/asset ABSOLUTE tCO2e only.
Never apply outstanding/AVO/EVIC attribution here — FE applies AF; SSP applies CAF.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .financed_scope_breakdown import option_1_company_emissions, optional_number, reported_company_scope_total
from .shared_formula_utils import _as_float, normalize_finance_input_aliases, sector_intensity_tco2e

# PCAF option → data-quality score (matches mortgage/CRE/motor/corp configs).
PROPERTY_DQ = {"1a": 1, "1b": 2, "2a": 3, "2b": 4, "3": 5}
MOTOR_DQ = {"1a": 1, "1b": 1, "2a": 2, "2b": 3, "3a": 4, "3b": 5}
COMPANY_DQ = {"1a": 1, "1b": 2, "2a": 2, "2b": 3, "3a": 4}
# 3c is outstanding × ATR × intensity — already embeds attribution; SSP must not use as absolute.
BLOCKED_COMPANY_OPTIONS = frozenset({"3c", "3"})


class AbsoluteEmissionsError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _num(v: Any) -> float:
    try:
        n = float(v)
        return n if n == n else 0.0
    except (TypeError, ValueError):
        return 0.0


def absolute_building_emissions_tco2e(
    option_code: str,
    inputs: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Mortgage / CRE absolute building emissions (PCAF options 1a/1b/2a/2b/3).

    Emission factors are treated as tCO2e per kWh (SPA / property_pcaf parity).
    """
    # Local import avoids circular import with property_pcaf → absolute_emissions.
    from .property_pcaf import normalize_property_field_aliases

    option = (option_code or "").strip().lower()
    data = normalize_property_field_aliases(dict(inputs or {}))

    if option in ("1a", "1b"):
        energy = _num(data.get("energy_consumption"))
        ef = _num(data.get("emission_factor") or data.get("average_emission_factor"))
        if energy <= 0 or ef <= 0:
            raise AbsoluteEmissionsError(
                "missing_property_energy_factor",
                "Actual energy consumption and emission factor must be greater than 0",
            )
        total = energy * ef
        method = f"property-absolute:{option}:energy_x_ef"
    elif option == "2a":
        intensity = _num(data.get("estimated_energy_consumption_from_labels"))
        floor_area = _num(data.get("floor_area"))
        ef = _num(data.get("average_emission_factor") or data.get("emission_factor"))
        if intensity <= 0 or floor_area <= 0 or ef <= 0:
            raise AbsoluteEmissionsError(
                "missing_property_label_inputs",
                "Energy from labels, floor area, and average emission factor must be greater than 0",
            )
        total = intensity * floor_area * ef
        method = f"property-absolute:{option}:labels_x_area_x_ef"
    elif option == "2b":
        intensity = _num(data.get("estimated_energy_consumption_from_statistics"))
        floor_area = _num(data.get("floor_area"))
        ef = _num(data.get("average_emission_factor") or data.get("emission_factor"))
        if intensity <= 0 or floor_area <= 0 or ef <= 0:
            raise AbsoluteEmissionsError(
                "missing_property_stats_inputs",
                "Energy from statistics, floor area, and average emission factor must be greater than 0",
            )
        total = intensity * floor_area * ef
        method = f"property-absolute:{option}:stats_x_area_x_ef"
    elif option == "3":
        per_building = _num(data.get("estimated_energy_consumption_from_statistics"))
        buildings = _num(data.get("number_of_buildings"))
        ef = _num(data.get("average_emission_factor") or data.get("emission_factor"))
        if per_building <= 0 or buildings <= 0 or ef <= 0:
            raise AbsoluteEmissionsError(
                "missing_property_option3_inputs",
                "Statistics energy, number of buildings, and average emission factor must be greater than 0",
            )
        total = per_building * buildings * ef
        method = f"property-absolute:{option}:stats_x_buildings_x_ef"
    else:
        raise AbsoluteEmissionsError(
            "unsupported_property_option",
            f"Unsupported property loan option: {option_code}",
        )

    return {
        "absolute_total_tco2e": float(total),
        # Building operational absolute without fuel/electricity split → Scope 2 bucket.
        "absolute_scope1_tco2e": 0.0,
        "absolute_scope2_tco2e": float(total),
        "absolute_scope3_tco2e": None,
        "data_quality_score": PROPERTY_DQ.get(option),
        "method": method,
        "option_code": option,
        "factor_unit": "tCO2e/kWh",
        "provenance": {
            "kind": "absolute_building_emissions",
            "option_code": option,
            "source": "absolute_emissions.absolute_building_emissions_tco2e",
        },
    }


def absolute_motor_fleet_emissions_tco2e(
    inputs: Dict[str, Any],
    *,
    option_code: str = "1b",
    fuel_path: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Absolute sum of vehicle emissions_tco2e (pre CAF / outstanding attribution).

    Uses the same resolve_vehicle_rows prep as standalone motor PCAF.
    Factors are tCO2e per litre (fuel) or tCO2e per (km × L/km) as in FE.
    """
    from .motor_vehicle_pcaf import parse_motor_vehicle_entries, resolve_vehicle_rows

    option = (option_code or "").strip().lower()
    if fuel_path is None:
        fuel_path = option == "1a" or bool((inputs or {}).get("fuel_path"))

    data = dict(inputs or {})
    # Enrich vehicle rows that carry activity inputs but not absolute emissions yet.
    entries = parse_motor_vehicle_entries(data.get("vehicle_entries"))
    if entries:
        enriched: List[Dict[str, Any]] = []
        for row in entries:
            em = _num(row.get("emissions_tco2e"))
            if em <= 0:
                if fuel_path:
                    em = _num(row.get("fuel_consumption")) * _num(row.get("emission_factor"))
                else:
                    em = (
                        _num(row.get("distance_traveled"))
                        * _num(row.get("efficiency"))
                        * _num(row.get("emission_factor"))
                    )
            if em <= 0:
                continue
            out = dict(row)
            out["emissions_tco2e"] = em
            # Placeholder value so resolve/validate paths that need >0 value still work when summing.
            if _num(out.get("value_at_origination")) <= 0:
                out["value_at_origination"] = 1.0
            enriched.append(out)
        if enriched:
            data = {**data, "vehicle_entries": enriched}

    vehicles = resolve_vehicle_rows(data, fuel_path=bool(fuel_path))
    if not vehicles:
        raise AbsoluteEmissionsError(
            "missing_motor_factor_inputs",
            (
                "Motor look-through needs fuel consumption and emission factor (option 1a) "
                "or distance, efficiency, and emission factor (other options)."
            ),
        )
    total = 0.0
    for v in vehicles:
        em = _num(v.get("emissions_tco2e"))
        if em <= 0:
            raise AbsoluteEmissionsError(
                "missing_motor_factor_inputs",
                "Each vehicle must have absolute emissions greater than 0.",
            )
        total += em

    return {
        "absolute_total_tco2e": float(total),
        "absolute_scope1_tco2e": 0.0,
        "absolute_scope2_tco2e": float(total),
        "absolute_scope3_tco2e": None,
        "data_quality_score": MOTOR_DQ.get(option),
        "method": f"motor-absolute:{option}:{'fuel' if fuel_path else 'distance_efficiency'}",
        "option_code": option,
        "vehicle_count": len(vehicles),
        "provenance": {
            "kind": "absolute_motor_fleet_emissions",
            "option_code": option,
            "fuel_path": bool(fuel_path),
            "source": "absolute_emissions.absolute_motor_fleet_emissions_tco2e",
        },
    }


def absolute_company_emissions_tco2e(
    option_code: str,
    inputs: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Company / bond absolute emissions for options 1a/1b/2a/2b/3a.

    Option 3c is blocked — it embeds outstanding and is not an absolute company total.
    """
    option = (option_code or "").strip().lower()
    if option in BLOCKED_COMPANY_OPTIONS or option == "3c":
        raise AbsoluteEmissionsError(
            "unsupported_company_option",
            f"Option '{option_code}' embeds outstanding attribution and cannot be used as SSP absolute emissions.",
        )

    data = normalize_finance_input_aliases(dict(inputs or {}))
    s1 = optional_number(data, "scope1_emissions", "scope1Emissions")
    s2 = optional_number(data, "scope2_emissions", "scope2Emissions")
    s3 = optional_number(data, "scope3_emissions", "scope3Emissions")

    if option == "1a":
        total = option_1_company_emissions(data, verified=True)
        if total is None:
            raise AbsoluteEmissionsError(
                "missing_company_emissions",
                "Verified emissions or reported Scope 1/2/3 values are required",
            )
        method = "company-absolute:1a:verified"
    elif option == "1b":
        total = option_1_company_emissions(data, verified=False)
        if total is None:
            raise AbsoluteEmissionsError(
                "missing_company_emissions",
                "Unverified emissions or reported Scope 1/2/3 values are required",
            )
        method = "company-absolute:1b:unverified"
    elif option == "2a":
        energy = _as_float(data.get("energy_consumption"))
        ef = _as_float(data.get("emission_factor"))
        if energy <= 0 or ef <= 0:
            raise AbsoluteEmissionsError(
                "missing_company_energy_factor",
                "Energy consumption and emission factor must be greater than 0",
            )
        process = _as_float(data.get("process_emissions"))
        total = energy * ef + process
        s1 = s1 if s1 is not None else float(total)
        s2 = s2 if s2 is not None else 0.0
        method = "company-absolute:2a:energy_x_ef"
    elif option == "2b":
        production = _as_float(data.get("production"))
        ef = _as_float(data.get("production_emission_factor")) or _as_float(data.get("emission_factor"))
        if production <= 0 or ef <= 0:
            raise AbsoluteEmissionsError(
                "missing_company_production_factor",
                "Production and emission factor must be greater than 0",
            )
        total = production * ef
        s1 = s1 if s1 is not None else float(total)
        s2 = s2 if s2 is not None else 0.0
        method = "company-absolute:2b:production_x_ef"
    elif option == "3a":
        revenue = _as_float(data.get("company_revenue"))
        intensity = sector_intensity_tco2e(data)
        if revenue <= 0 or intensity <= 0:
            raise AbsoluteEmissionsError(
                "missing_company_revenue_intensity",
                "Company/project revenue and sector intensity must be greater than 0",
            )
        total = revenue * intensity
        s1 = s1 if s1 is not None else float(total)
        s2 = s2 if s2 is not None else 0.0
        method = "company-absolute:3a:revenue_x_intensity"
    else:
        raise AbsoluteEmissionsError(
            "unsupported_company_option",
            f"Unsupported company option '{option_code}' for absolute emissions",
        )

    # Preserve explicit scopes when present; otherwise leave unallocated total with S1 bucket convention for activity methods.
    if option in ("1a", "1b") and (s1 is not None or s2 is not None or s3 is not None):
        scope_total = reported_company_scope_total(data)
        if scope_total is not None:
            # Prefer scope split when provided.
            pass
        else:
            s1, s2, s3 = float(total), 0.0, None
    elif option in ("1a", "1b"):
        s1, s2, s3 = float(total), 0.0, None

    return {
        "absolute_total_tco2e": float(total),
        "absolute_scope1_tco2e": float(s1) if s1 is not None else 0.0,
        "absolute_scope2_tco2e": float(s2) if s2 is not None else 0.0,
        "absolute_scope3_tco2e": float(s3) if s3 is not None else None,
        "data_quality_score": COMPANY_DQ.get(option),
        "method": method,
        "option_code": option,
        "provenance": {
            "kind": "absolute_company_emissions",
            "option_code": option,
            "source": "absolute_emissions.absolute_company_emissions_tco2e",
        },
    }


def property_option_from_class_inputs(class_inputs: Dict[str, Any]) -> str:
    method_sel = class_inputs.get("methodSelection") or class_inputs.get("method_selection") or {}
    raw = str(method_sel.get("calculationMethod") or method_sel.get("calculation_method") or "").strip().lower()
    if raw in PROPERTY_DQ:
        return raw
    # Strip asset-class suffixes e.g. 1a-mortgage
    for opt in ("1a", "1b", "2a", "2b", "3"):
        if raw.startswith(opt):
            return opt
    return "1a"


def motor_option_from_class_inputs(class_inputs: Dict[str, Any]) -> Tuple[str, bool]:
    method_sel = class_inputs.get("methodSelection") or class_inputs.get("method_selection") or {}
    raw = str(method_sel.get("calculationMethod") or method_sel.get("calculation_method") or "").strip().lower()
    option = "1b"
    for opt in ("1a", "1b", "2a", "2b", "3a", "3b"):
        if raw.startswith(opt):
            option = opt
            break
    fuel_path = option == "1a"
    meta = method_sel.get("metadata") if isinstance(method_sel.get("metadata"), dict) else {}
    if "fuel_path" in meta:
        fuel_path = bool(meta["fuel_path"])
    return option, fuel_path


def company_option_from_class_inputs(class_inputs: Dict[str, Any]) -> str:
    method_sel = class_inputs.get("methodSelection") or class_inputs.get("method_selection") or {}
    raw = str(method_sel.get("calculationMethod") or method_sel.get("calculation_method") or "").strip().lower()
    for opt in ("1a", "1b", "2a", "2b", "3a", "3c"):
        if raw.startswith(opt):
            return opt
    # Default reported path
    return "1b"
