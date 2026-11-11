"""
SSP underlying absolute emissions from classInputs / reported scopes.

Returns ABSOLUTE asset/company emissions only — never applies CAF/outstanding
attribution. SSP CAF is applied separately in ssp_calc.py.

Absolute math is delegated to absolute_emissions helpers shared with standalone FE.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .absolute_emissions import (
    AbsoluteEmissionsError,
    absolute_building_emissions_tco2e,
    absolute_company_emissions_tco2e,
    absolute_motor_fleet_emissions_tco2e,
    company_option_from_class_inputs,
    motor_option_from_class_inputs,
    property_option_from_class_inputs,
)
from .property_pcaf import normalize_property_field_aliases
from .shared_formula_utils import normalize_finance_input_aliases


def _num(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pick(data: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return default


def _text(value: Any) -> str:
    return str(value or "").strip()


def _to_tco2e(amount: float, unit: str):
    """Convert common GHG mass units to tCO2e. Energy×EF handled by absolute helpers."""
    u = (unit or "tCO2e").strip().lower().replace(" ", "")
    if u in ("tco2e", "t", "tonne", "tonnes", "mtco2e", "metric ton"):
        return amount, None
    if u in ("kgco2e", "kg"):
        return amount / 1000.0, None
    if u in ("gco2e", "g"):
        return amount / 1_000_000.0, None
    return None, f"unsupported_emissions_unit:{unit}"


SUPPORTED_LOOKTHROUGH_TYPES = frozenset(
    {
        "mortgage",
        "commercial-real-estate",
        "motor-vehicle-loan",
        "business-loan",
        "unlisted-equity",
        "corporate-bond",
        "listed-equity",
    }
)


def absolute_emissions_for_collateral(collateral: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compute absolute Scope 1/2/3 for one collateral row.

    Status: complete | incomplete | unsupported | error
    """
    cid = _text(_pick(collateral, "collateralId", "collateral_id"))
    ctype = _text(_pick(collateral, "collateralType", "collateral_type"))
    name = _text(_pick(collateral, "name")) or cid or "collateral"
    base: Dict[str, Any] = {
        "collateral_id": cid,
        "name": name,
        "collateral_type": ctype,
        "status": "incomplete",
        "absolute_scope1_tco2e": None,
        "absolute_scope2_tco2e": None,
        "absolute_scope3_tco2e": None,
        "absolute_total_tco2e": None,
        "data_quality_score": None,
        "method": None,
        "provenance": {},
        "code": None,
        "message": None,
    }

    if ctype == "other-hard-asset":
        s1 = _num(_pick(collateral, "scope1Emissions", "scope1_emissions"))
        s2 = _num(_pick(collateral, "scope2Emissions", "scope2_emissions"))
        s3 = _num(_pick(collateral, "scope3Emissions", "scope3_emissions"))
        if s1 is None and s2 is None:
            base["status"] = "unsupported"
            base["code"] = "unsupported_other_hard_asset"
            base["message"] = (
                f"{name}: other hard asset requires asset-level Scope 1/2 emissions; "
                "no generic factor method is enabled."
            )
            return base
        return _pack_scopes(base, s1 or 0.0, s2 or 0.0, s3, method="reported-asset-level", dq=2)

    if ctype not in SUPPORTED_LOOKTHROUGH_TYPES:
        base["status"] = "unsupported"
        base["code"] = "unsupported_collateral_type"
        base["message"] = f"{name}: collateral type '{ctype}' is not mapped for SSP look-through."
        return base

    # Explicit reported scopes on the collateral row (mass units → tCO2e).
    path = _text(_pick(collateral, "emissionsPath", "emissions_path"))
    s1 = _num(_pick(collateral, "scope1Emissions", "scope1_emissions"))
    s2 = _num(_pick(collateral, "scope2Emissions", "scope2_emissions"))
    s3 = _num(_pick(collateral, "scope3Emissions", "scope3_emissions"))
    unit = _text(_pick(collateral, "emissionsUnit", "emissions_unit")) or "tCO2e"
    if path == "reported" or (s1 is not None or s2 is not None):
        if s1 is None and s2 is None:
            base["code"] = "missing_reported_scopes"
            base["message"] = f"{name}: reported path needs Scope 1 and/or Scope 2."
            return base
        converted = []
        for val in (s1, s2, s3):
            if val is None:
                converted.append(None)
                continue
            t, err = _to_tco2e(val, unit)
            if err:
                base["status"] = "error"
                base["code"] = "unsupported_emissions_unit"
                base["message"] = f"{name}: {err}"
                return base
            converted.append(t)
        dq = _num(_pick(collateral, "dataQualityScore", "data_quality_score")) or 2
        return _pack_scopes(
            base,
            converted[0] or 0.0,
            converted[1] or 0.0,
            converted[2],
            method="reported",
            dq=dq,
            extra_provenance={"emissions_unit": unit, "reporting_year": _pick(collateral, "reportingYear", "reporting_year")},
        )

    class_inputs = _pick(collateral, "classInputs", "class_inputs", default={}) or {}
    if not isinstance(class_inputs, dict):
        class_inputs = {}

    if ctype in ("business-loan", "unlisted-equity", "corporate-bond", "listed-equity"):
        return _company_via_shared(base, class_inputs, name)

    if ctype in ("mortgage", "commercial-real-estate"):
        return _property_via_shared(base, class_inputs, name, ctype)

    if ctype == "motor-vehicle-loan":
        return _motor_via_shared(base, class_inputs, name)

    base["code"] = "incomplete_underlying"
    base["message"] = f"{name}: could not resolve absolute emissions."
    return base


def _pack_scopes(
    base: Dict[str, Any],
    s1: float,
    s2: float,
    s3: Optional[float],
    *,
    method: str,
    dq: Any,
    extra_provenance: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    total = s1 + s2 + (s3 or 0.0)
    base["status"] = "complete"
    base["absolute_scope1_tco2e"] = s1
    base["absolute_scope2_tco2e"] = s2
    base["absolute_scope3_tco2e"] = s3
    base["absolute_total_tco2e"] = total
    base["method"] = method
    base["data_quality_score"] = float(dq) if dq is not None else None
    base["provenance"] = {"kind": "ssp_absolute_emissions", "method": method}
    if extra_provenance:
        base["provenance"].update(extra_provenance)
    return base


def _apply_shared(base: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    out = _pack_scopes(
        base,
        float(result.get("absolute_scope1_tco2e") or 0.0),
        float(result.get("absolute_scope2_tco2e") or 0.0),
        result.get("absolute_scope3_tco2e"),
        method=str(result.get("method") or "shared-absolute"),
        dq=result.get("data_quality_score"),
        extra_provenance=result.get("provenance") or {},
    )
    out["absolute_total_tco2e"] = float(result["absolute_total_tco2e"])
    return out


def _fail_abs(base: Dict[str, Any], exc: AbsoluteEmissionsError) -> Dict[str, Any]:
    base["status"] = "incomplete" if exc.code.startswith("missing_") else "unsupported"
    if exc.code.startswith("unsupported_"):
        base["status"] = "unsupported"
    base["code"] = exc.code
    base["message"] = f"{base['name']}: {exc.message}"
    return base


def _flatten_property_inputs(class_inputs: Dict[str, Any]) -> Dict[str, Any]:
    form = class_inputs.get("formData") or class_inputs.get("form_data") or {}
    if not isinstance(form, dict):
        form = {}
    merged = dict(form)
    # Prefer first property / CRE row activity fields when present.
    for key in ("properties", "commercialProperties", "commercial_properties"):
        rows = class_inputs.get(key) or []
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            prop = rows[0]
            for src, dst in (
                ("actualEnergyConsumption", "energy_consumption"),
                ("actual_energy_consumption", "energy_consumption"),
                ("energy_consumption", "energy_consumption"),
                ("supplierSpecificEmissionFactor", "emission_factor"),
                ("supplier_specific_emission_factor", "emission_factor"),
                ("averageEmissionFactor", "average_emission_factor"),
                ("average_emission_factor", "average_emission_factor"),
                ("estimatedEnergyConsumptionFromLabels", "estimated_energy_consumption_from_labels"),
                ("estimated_energy_consumption_from_labels", "estimated_energy_consumption_from_labels"),
                ("estimatedEnergyConsumptionFromStatistics", "estimated_energy_consumption_from_statistics"),
                ("estimated_energy_consumption_from_statistics", "estimated_energy_consumption_from_statistics"),
                ("floorArea", "floor_area"),
                ("floor_area", "floor_area"),
                ("numberOfBuildings", "number_of_buildings"),
                ("number_of_buildings", "number_of_buildings"),
            ):
                if prop.get(src) is not None and merged.get(dst) is None:
                    merged[dst] = prop.get(src)
            break
    # CamelCase form aliases
    aliases = {
        "energyConsumption": "energy_consumption",
        "actualEnergyConsumption": "energy_consumption",
        "emissionFactor": "emission_factor",
        "averageEmissionFactor": "average_emission_factor",
        "floorArea": "floor_area",
        "estimatedEnergyConsumptionFromLabels": "estimated_energy_consumption_from_labels",
        "estimatedEnergyConsumptionFromStatistics": "estimated_energy_consumption_from_statistics",
        "numberOfBuildings": "number_of_buildings",
    }
    for camel, snake in aliases.items():
        if merged.get(camel) is not None and merged.get(snake) is None:
            merged[snake] = merged[camel]
    return normalize_property_field_aliases(merged)


def _property_via_shared(
    base: Dict[str, Any],
    class_inputs: Dict[str, Any],
    name: str,
    ctype: str,
) -> Dict[str, Any]:
    option = property_option_from_class_inputs(class_inputs)
    inputs = _flatten_property_inputs(class_inputs)
    # Multi-property sum for 1a/1b when several property rows carry energy×EF
    props = []
    for key in ("properties", "commercialProperties", "commercial_properties"):
        raw = class_inputs.get(key) or []
        if isinstance(raw, list):
            props.extend([p for p in raw if isinstance(p, dict)])
    if option in ("1a", "1b") and len(props) > 1:
        total = 0.0
        used = 0
        for prop in props:
            row = normalize_property_field_aliases(
                {
                    "energy_consumption": prop.get("actualEnergyConsumption")
                    or prop.get("actual_energy_consumption")
                    or prop.get("energy_consumption"),
                    "emission_factor": prop.get("supplierSpecificEmissionFactor")
                    or prop.get("supplier_specific_emission_factor")
                    or prop.get("emission_factor"),
                    "average_emission_factor": prop.get("averageEmissionFactor")
                    or prop.get("average_emission_factor"),
                }
            )
            try:
                part = absolute_building_emissions_tco2e(option, row)
                total += float(part["absolute_total_tco2e"])
                used += 1
            except AbsoluteEmissionsError:
                continue
        if used == 0:
            base["code"] = "missing_property_energy_factor"
            base["message"] = (
                f"{name}: mortgage/CRE look-through needs energy consumption and an emission factor "
                "(absolute building emissions). Outstanding/AVO attribution is applied later via CAF."
            )
            return base
        return _pack_scopes(
            base,
            0.0,
            total,
            None,
            method=f"property-absolute:{ctype}:{option}:multi",
            dq={"1a": 1, "1b": 2}.get(option, 3),
            extra_provenance={"properties_used": used, "option_code": option},
        )

    try:
        result = absolute_building_emissions_tco2e(option, inputs)
        result["method"] = f"{result['method']}:{ctype}"
        return _apply_shared(base, result)
    except AbsoluteEmissionsError as exc:
        return _fail_abs(base, exc)


def _motor_via_shared(base: Dict[str, Any], class_inputs: Dict[str, Any], name: str) -> Dict[str, Any]:
    option, fuel_path = motor_option_from_class_inputs(class_inputs)
    form = class_inputs.get("formData") or class_inputs.get("form_data") or {}
    if not isinstance(form, dict):
        form = {}
    inputs = dict(form)
    if class_inputs.get("vehicle_entries") and not inputs.get("vehicle_entries"):
        inputs["vehicle_entries"] = class_inputs["vehicle_entries"]
    # CamelCase aliases used by SSP questionnaire
    if inputs.get("distance") and not inputs.get("distance_traveled"):
        inputs["distance_traveled"] = inputs["distance"]
    if inputs.get("annualDistance") and not inputs.get("distance_traveled"):
        inputs["distance_traveled"] = inputs["annualDistance"]
    if inputs.get("emissionFactor") and not inputs.get("emission_factor"):
        inputs["emission_factor"] = inputs["emissionFactor"]
    if inputs.get("fuelConsumption") and not inputs.get("fuel_consumption"):
        inputs["fuel_consumption"] = inputs["fuelConsumption"]
    if inputs.get("totalValueAtOrigination") and not inputs.get("total_value_at_origination"):
        inputs["total_value_at_origination"] = inputs["totalValueAtOrigination"]
    if inputs.get("totalVehicleEmissions") and not inputs.get("total_vehicle_emissions"):
        inputs["total_vehicle_emissions"] = inputs["totalVehicleEmissions"]
    # Distance-only without efficiency is not a PCAF motor option — require efficiency unless precomputed emissions exist.
    try:
        result = absolute_motor_fleet_emissions_tco2e(inputs, option_code=option, fuel_path=fuel_path)
        return _apply_shared(base, result)
    except AbsoluteEmissionsError as exc:
        return _fail_abs(base, AbsoluteEmissionsError(exc.code, f"{exc.message}"))


def _company_via_shared(base: Dict[str, Any], class_inputs: Dict[str, Any], name: str) -> Dict[str, Any]:
    option = company_option_from_class_inputs(class_inputs)
    form = class_inputs.get("formData") or class_inputs.get("form_data") or {}
    if not isinstance(form, dict):
        form = {}
    inputs = normalize_finance_input_aliases(dict(form))
    try:
        result = absolute_company_emissions_tco2e(option, inputs)
        return _apply_shared(base, result)
    except AbsoluteEmissionsError as exc:
        return _fail_abs(base, AbsoluteEmissionsError(exc.code, exc.message))
