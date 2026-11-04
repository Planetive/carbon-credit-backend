"""
Map a UoP underlying asset onto the existing PCAF CalculationEngine.

§5.7 requires asset-class methods from the matching Part A chapters. This
module does not re-implement those formulas. Paths that cannot be mapped to a
verified option are returned incomplete or unsupported.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .calculation_engine import CalculationEngine
from .finance_models import CompanyType
from .motor_vehicle_pcaf import compute_motor_vehicle_pcaf_financed
from .shared_formula_utils import (
    calculate_attribution_factor_commercial_real_estate,
    calculate_financed_emissions,
)

INCOMPLETE = "incomplete"
UNSUPPORTED = "unsupported"
COMPLETE = "complete"

SCORE5_ASSET_CLASSES = {
    "listed-equity",
    "corporate-bond",
    "business-loan",
    "unlisted-equity",
    "project-finance",
}
LISTED_CLASSES = {"listed-equity", "corporate-bond"}
UNLISTED_CLASSES = {"business-loan", "unlisted-equity"}
PROJECT_CLASSES = {"project-finance"}
BUILDING_CLASSES = {"mortgage", "commercial-real-estate"}
MOTOR_CLASSES = {"motor-vehicle-loan"}

# UoP Table 5.7-1 score 5 is only listed equity/bonds, business loans /
# unlisted equity, and project finance. Buildings and vehicles have no
# outstanding × sector-EF option in their chapters.
UNSUPPORTED_SCORE5_MESSAGE = (
    "PCAF §5.7 score 5 (Outstanding × Σ sector allocation % × sector EF) "
    "applies only to listed equity and bonds, business loans and unlisted "
    "equity, and project finance. This asset class has no verified economic "
    "estimation option on the UoP form."
)

ALLOWED_OPTIONS = {
    "listed-equity": {"2a", "2b", "3a", "3c", "score5"},
    "corporate-bond": {"2a", "2b", "3a", "3c", "score5"},
    "business-loan": {"2a", "2b", "3a", "3c", "score5"},
    "unlisted-equity": {"2a", "2b", "3a", "3c", "score5"},
    "project-finance": {"2a", "2b", "3a", "3c", "score5"},
    "mortgage": {"1a", "1b", "2a", "2b", "3"},
    "commercial-real-estate": {"1a", "1b", "2a", "2b", "3"},
    "motor-vehicle-loan": {"1a", "1b", "2a", "2b", "3a", "3b"},
}

# Legacy unit inference only. New drafts select pcafOption explicitly.
UNSUPPORTED_PHYSICAL = {
    "building-floor-area": (
        "Commercial real estate and mortgages score 3–5 from energy labels "
        "or statistical building data (PCAF §5.4 / §5.5 options 2a, 2b, 3). "
        "Select that option and enter label/statistical intensity plus floor "
        "area or building count. Floor area alone is not scored as option 2."
    ),
    "motor-distance": (
        "Motor-vehicle options 1b/2a/2b/3a/3b need distance, efficiency, and "
        "a published fuel factor (PCAF §5.6). Select the option instead of "
        "inferring score 3 from a distance unit."
    ),
    "unmapped-unit": (
        "Physical activity is only used when the unit maps to a verified "
        "asset-class option, or when a PCAF option is selected. Score 3 is "
        "not assigned because activity data exists."
    ),
}

ISSUER_LEVEL_REASONS = {
    "theoretically_impossible",
    "practically_not_feasible",
    "not_material",
}

_ENGINE: Optional[CalculationEngine] = None


class UnderlyingInputError(Exception):
    def __init__(self, detail: Any, status_code: int = 422):
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail


def _engine() -> CalculationEngine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = CalculationEngine()
    return _ENGINE


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _pick(payload: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return default


def _num(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise UnderlyingInputError(f"Expected a number, got {value!r}") from None
    if number != number or number in (float("inf"), float("-inf")):
        raise UnderlyingInputError("Non-finite number is not allowed")
    return number


def _norm_unit(unit: str) -> str:
    return (
        _text(unit)
        .lower()
        .replace(" ", "")
        .replace("²", "2")
        .replace("³", "3")
        .replace(".", "")
    )


def classify_physical_unit(unit: str) -> str:
    token = _norm_unit(unit)
    if not token:
        return "unknown"
    if token in {
        "mwh",
        "kwh",
        "gwh",
        "wh",
        "gj",
        "mj",
        "kj",
        "therm",
        "therms",
        "mmbtu",
        "btu",
    }:
        return "energy"
    if token in {
        "t",
        "te",
        "ton",
        "tons",
        "tonne",
        "tonnes",
        "mt",
        "kg",
        "unit",
        "units",
        "piece",
        "pieces",
        "item",
        "items",
    }:
        return "production"
    if token in {
        "m2",
        "sqm",
        "sqmeter",
        "sqmetre",
        "sqft",
        "ft2",
        "sqfeet",
        "squaremeter",
        "squaremetre",
        "squarefoot",
        "squarefeet",
    }:
        return "floor_area"
    if token in {
        "l",
        "liter",
        "litre",
        "liters",
        "litres",
        "gal",
        "gallon",
        "gallons",
        "scf",
        "kgfuel",
    }:
        return "fuel"
    if token in {
        "km",
        "kilometre",
        "kilometer",
        "kilometres",
        "kilometers",
        "mi",
        "mile",
        "miles",
    }:
        return "distance"
    return "unknown"


def _intensity_tco2e_per_unit(estimation: Dict[str, Any], *, physical: bool) -> Optional[float]:
    raw = _num(
        _pick(
            estimation,
            "emissionFactor",
            "emission_factor",
            "sectorIntensity",
            "sector_intensity",
        )
    )
    if raw is None:
        return None
    unit = _text(
        _pick(
            estimation,
            "emissionFactorUnit",
            "emission_factor_unit",
            "factorUnit",
            "factor_unit",
            "sectorIntensityUnit",
            "sector_intensity_unit",
        )
    ).lower()
    if physical:
        if "kg" in unit and "tco2" not in unit.replace(" ", ""):
            return raw / 1000.0
        return raw
    if "kg" in unit:
        return raw / 1000.0
    return raw


def _incomplete(result: Dict[str, Any], code: str, message: str) -> Dict[str, Any]:
    result.update(
        {
            "status": INCOMPLETE,
            "code": code,
            "message": message,
            "structure_financed_emissions": None,
        }
    )
    return result


def _unsupported(result: Dict[str, Any], message: str, code: str = "unsupported_methodology") -> Dict[str, Any]:
    result.update(
        {
            "status": UNSUPPORTED,
            "code": code,
            "message": message,
            "structure_financed_emissions": None,
        }
    )
    return result


def _formula_for(asset_class: str, option: str) -> Tuple[Optional[str], CompanyType]:
    if asset_class in LISTED_CLASSES:
        return f"{option}-listed-equity", CompanyType.LISTED
    if asset_class in UNLISTED_CLASSES:
        return f"{option}-unlisted-equity", CompanyType.PRIVATE
    if asset_class in PROJECT_CLASSES:
        return f"{option}-project-finance", CompanyType.PRIVATE
    if asset_class == "mortgage":
        return f"{option}-mortgage", CompanyType.PRIVATE
    if asset_class == "commercial-real-estate":
        return f"{option}-commercial-real-estate", CompanyType.PRIVATE
    return None, CompanyType.PRIVATE


def _corporate_denom_inputs(asset_class: str, allocated: float, denom: float) -> Dict[str, Any]:
    inputs: Dict[str, Any] = {
        "outstanding_amount": allocated,
        "total_assets": denom,
    }
    if asset_class in LISTED_CLASSES:
        inputs["evic"] = denom
    elif asset_class in PROJECT_CLASSES:
        inputs["total_project_equity_plus_debt"] = denom
    else:
        inputs["total_equity_plus_debt"] = denom
    return inputs


def _scopes_from_engine(result) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    breakdown = (result.metadata or {}).get("scope_breakdown") or {}
    return (
        breakdown.get("financed_scope1_tco2e"),
        breakdown.get("financed_scope2_tco2e"),
        breakdown.get("financed_scope3_tco2e"),
        breakdown.get("financed_unallocated_tco2e"),
    )


def _apply_engine_result(
    result: Dict[str, Any],
    calc,
    *,
    allocated: float,
    denom: Optional[float],
    estimated: bool,
    reused_methodology: str,
) -> Dict[str, Any]:
    s1, s2, s3, unallocated = _scopes_from_engine(calc)
    option = _text((calc.metadata or {}).get("option_code")) or None
    result.update(
        {
            "status": COMPLETE,
            "asset_attribution_factor": calc.attribution_factor,
            "denominator": denom,
            "structure_scope1_tco2e": s1,
            "structure_scope2_tco2e": s2,
            "structure_scope3_tco2e": s3,
            "structure_unallocated_tco2e": unallocated,
            "structure_financed_emissions": calc.financed_emissions,
            "data_quality_score": float(calc.data_quality_score),
            "option_code": option,
            "reused_formula_id": (calc.metadata or {}).get("formula_id"),
            "estimated": estimated,
            "reused_methodology": reused_methodology,
            "allocated_outstanding": allocated,
        }
    )
    return result


def _run_engine(formula_id: str, inputs: Dict[str, Any], company_type: CompanyType):
    return _engine().calculate(formula_id, inputs, company_type)


def _reported_total(s1: Optional[float], s2: Optional[float], s3: Optional[float]) -> Optional[float]:
    present = [value for value in (s1, s2, s3) if value is not None]
    if not present:
        return None
    return sum(present)


def _reported_corporate_or_project(
    result: Dict[str, Any],
    *,
    asset_class: str,
    name: str,
    allocated: float,
    denom: Optional[float],
    denom_label: str,
    denom_ref: str,
    verification: str,
    s1: Optional[float],
    s2: Optional[float],
    s3: Optional[float],
) -> Dict[str, Any]:
    if denom is None or denom <= 0:
        return _incomplete(
            result,
            "missing_asset_denominator",
            (
                f"{name}: {denom_label} is required and must be greater "
                "than zero to compute the asset-class attribution factor."
            ),
        )
    total = _reported_total(s1, s2, s3)
    if total is None:
        return _incomplete(
            result,
            "missing_reported_emissions",
            (
                f"{name}: reported emissions were selected but no scope "
                "value was provided. Blank is missing, not zero."
            ),
        )
    option = "1a" if verification == "verified" else "1b"
    formula_id, company_type = _formula_for(asset_class, option)
    if not formula_id:
        return _unsupported(result, f"{name}: no 1a/1b formula for {asset_class}.")
    emissions_key = "verified_emissions" if option == "1a" else "unverified_emissions"
    inputs = _corporate_denom_inputs(asset_class, allocated, denom)
    inputs[emissions_key] = total
    if s1 is not None:
        inputs["scope1_emissions"] = s1
    if s2 is not None:
        inputs["scope2_emissions"] = s2
    if s3 is not None:
        inputs["scope3_emissions"] = s3
    try:
        calc = _run_engine(formula_id, inputs, company_type)
    except ValueError as exc:
        return _incomplete(result, "underlying_engine_invalid", f"{name}: {exc}")
    result["scope1_emissions"] = s1
    result["scope2_emissions"] = s2
    result["scope3_emissions"] = s3
    return _apply_engine_result(
        result,
        calc,
        allocated=allocated,
        denom=denom,
        estimated=False,
        reused_methodology=f"{denom_ref}; {formula_id}",
    )


def _reported_building(
    result: Dict[str, Any],
    *,
    name: str,
    allocated: float,
    denom: Optional[float],
    denom_label: str,
    denom_ref: str,
    verification: str,
    s1: Optional[float],
    s2: Optional[float],
    s3: Optional[float],
) -> Dict[str, Any]:
    """
    Issuer-reported building GHG × §5.4/§5.5 AF.

    Options 1a/1b on the building questionnaires are energy × EF, which the
    UoP reported-GHG path does not collect. Attribution still uses the
    validated property helper so AF is not a second formula.
    """
    if denom is None or denom <= 0:
        return _incomplete(
            result,
            "missing_asset_denominator",
            (
                f"{name}: {denom_label} is required and must be greater "
                "than zero to compute the asset-class attribution factor."
            ),
        )
    total = _reported_total(s1, s2, s3)
    if total is None:
        return _incomplete(
            result,
            "missing_reported_emissions",
            (
                f"{name}: reported emissions were selected but no scope "
                "value was provided. Blank is missing, not zero."
            ),
        )
    af = calculate_attribution_factor_commercial_real_estate(allocated, denom)
    fe = calculate_financed_emissions(allocated, denom, total)
    verified = verification == "verified"
    result.update(
        {
            "status": COMPLETE,
            "asset_attribution_factor": af,
            "denominator": denom,
            "scope1_emissions": s1,
            "scope2_emissions": s2,
            "scope3_emissions": s3,
            "structure_scope1_tco2e": None if s1 is None else af * s1,
            "structure_scope2_tco2e": None if s2 is None else af * s2,
            "structure_scope3_tco2e": None if s3 is None else af * s3,
            "structure_unallocated_tco2e": None,
            "structure_financed_emissions": fe,
            "data_quality_score": 1.0 if verified else 2.0,
            "option_code": "1a" if verified else "1b",
            "estimated": False,
            "reused_formula_id": None,
            "reused_methodology": (
                f"{denom_ref}; issuer-reported underlying GHG (UoP Table 5.7-1 "
                "score 1/2). Building energy×EF options were not used because "
                "energy consumption was not provided."
            ),
        }
    )
    return result


def _reported_motor(
    result: Dict[str, Any],
    *,
    asset_id: str,
    name: str,
    allocated: float,
    denom: Optional[float],
    denom_label: str,
    denom_ref: str,
    verification: str,
    s1: Optional[float],
    s2: Optional[float],
    s3: Optional[float],
) -> Dict[str, Any]:
    if denom is None or denom <= 0:
        return _incomplete(
            result,
            "missing_asset_denominator",
            (
                f"{name}: {denom_label} is required and must be greater "
                "than zero to compute the asset-class attribution factor."
            ),
        )
    total = _reported_total(s1, s2, s3)
    if total is None:
        return _incomplete(
            result,
            "missing_reported_emissions",
            (
                f"{name}: reported emissions were selected but no scope "
                "value was provided. Blank is missing, not zero."
            ),
        )
    raw = compute_motor_vehicle_pcaf_financed(
        allocated,
        [
            {
                "id": asset_id or "vehicle-1",
                "name": name,
                "value_at_origination": denom,
                "emissions_tco2e": total,
                "outstanding_amount": allocated,
            }
        ],
    )
    fe = float(raw["total_financed_emissions"])
    af = allocated / denom
    verified = verification == "verified"
    result.update(
        {
            "status": COMPLETE,
            "asset_attribution_factor": af,
            "denominator": denom,
            "scope1_emissions": s1,
            "scope2_emissions": s2,
            "scope3_emissions": s3,
            "structure_scope1_tco2e": None if s1 is None else af * s1,
            "structure_scope2_tco2e": None if s2 is None else af * s2,
            "structure_scope3_tco2e": None if s3 is None else af * s3,
            "structure_unallocated_tco2e": None,
            "structure_financed_emissions": fe,
            "data_quality_score": 1.0 if verified else 2.0,
            "option_code": "1a" if verified else "1b",
            "estimated": False,
            "reused_formula_id": "motor-vehicle-pcaf",
            "reused_methodology": (
                f"{denom_ref}; compute_motor_vehicle_pcaf_financed. "
                "Fuel-consumption option 1a was not used because vehicle fuel "
                "rows are not on the UoP form."
            ),
        }
    )
    return result


def _physical_corporate_or_project(
    result: Dict[str, Any],
    *,
    asset_class: str,
    name: str,
    allocated: float,
    denom: Optional[float],
    denom_label: str,
    denom_ref: str,
    kind: str,
    activity: float,
    factor: float,
) -> Dict[str, Any]:
    if denom is None or denom <= 0:
        return _incomplete(
            result,
            "missing_asset_denominator",
            (
                f"{name}: {denom_label} is required to attribute "
                "physical-activity emissions under the asset-class method."
            ),
        )
    option = "2a" if kind == "energy" else "2b"
    formula_id, company_type = _formula_for(asset_class, option)
    if not formula_id:
        return _unsupported(result, f"{name}: no {option} formula for {asset_class}.")
    inputs = _corporate_denom_inputs(asset_class, allocated, denom)
    if option == "2a":
        inputs["energy_consumption"] = activity
        inputs["emission_factor"] = factor
    else:
        inputs["production"] = activity
        inputs["production_emission_factor"] = factor
    try:
        calc = _run_engine(formula_id, inputs, company_type)
    except ValueError as exc:
        return _incomplete(result, "underlying_engine_invalid", f"{name}: {exc}")
    result["activity_amount"] = activity
    result["emission_factor"] = factor
    return _apply_engine_result(
        result,
        calc,
        allocated=allocated,
        denom=denom,
        estimated=True,
        reused_methodology=f"{denom_ref}; {formula_id}",
    )


def _physical_building_energy(
    result: Dict[str, Any],
    *,
    asset_class: str,
    name: str,
    allocated: float,
    denom: Optional[float],
    denom_label: str,
    denom_ref: str,
    verification: str,
    activity: float,
    factor: float,
) -> Dict[str, Any]:
    if denom is None or denom <= 0:
        return _incomplete(
            result,
            "missing_asset_denominator",
            (
                f"{name}: {denom_label} is required to attribute "
                "physical-activity emissions under the asset-class method."
            ),
        )
    option = "1a" if verification == "verified" else "1b"
    formula_id, company_type = _formula_for(asset_class, option)
    if not formula_id:
        return _unsupported(result, f"{name}: no {option} formula for {asset_class}.")
    if activity == 0:
        af = calculate_attribution_factor_commercial_real_estate(allocated, denom)
        result.update(
            {
                "status": COMPLETE,
                "asset_attribution_factor": af,
                "denominator": denom,
                "activity_amount": activity,
                "emission_factor": factor,
                "structure_scope1_tco2e": None,
                "structure_scope2_tco2e": None,
                "structure_scope3_tco2e": None,
                "structure_unallocated_tco2e": 0.0,
                "structure_financed_emissions": 0.0,
                "data_quality_score": 1.0 if option == "1a" else 2.0,
                "option_code": option,
                "reused_formula_id": formula_id,
                "estimated": False,
                "reused_methodology": f"{denom_ref}; {formula_id} valid zero energy",
            }
        )
        return result
    inputs = {
        "outstanding_amount": allocated,
        "property_value_at_origination": denom,
        "energy_consumption": activity,
        "emission_factor": factor,
    }
    try:
        calc = _run_engine(formula_id, inputs, company_type)
    except ValueError as exc:
        return _incomplete(result, "underlying_engine_invalid", f"{name}: {exc}")
    result["activity_amount"] = activity
    result["emission_factor"] = factor
    return _apply_engine_result(
        result,
        calc,
        allocated=allocated,
        denom=denom,
        estimated=False,
        reused_methodology=f"{denom_ref}; {formula_id}",
    )


def _physical_motor_fuel(
    result: Dict[str, Any],
    *,
    asset_id: str,
    name: str,
    allocated: float,
    denom: Optional[float],
    denom_label: str,
    denom_ref: str,
    activity: float,
    factor: float,
) -> Dict[str, Any]:
    if denom is None or denom <= 0:
        return _incomplete(
            result,
            "missing_asset_denominator",
            (
                f"{name}: {denom_label} is required to attribute "
                "physical-activity emissions under the asset-class method."
            ),
        )
    asset_emissions = activity * factor
    raw = compute_motor_vehicle_pcaf_financed(
        allocated,
        [
            {
                "id": asset_id or "vehicle-1",
                "name": name,
                "value_at_origination": denom,
                "emissions_tco2e": asset_emissions,
                "outstanding_amount": allocated,
            }
        ],
    )
    af = allocated / denom
    result.update(
        {
            "status": COMPLETE,
            "asset_attribution_factor": af,
            "denominator": denom,
            "activity_amount": activity,
            "emission_factor": factor,
            "asset_emissions_tco2e": asset_emissions,
            "structure_scope1_tco2e": None,
            "structure_scope2_tco2e": None,
            "structure_scope3_tco2e": None,
            "structure_unallocated_tco2e": float(raw["total_financed_emissions"]),
            "structure_financed_emissions": float(raw["total_financed_emissions"]),
            "data_quality_score": 1.0,
            "option_code": "1a",
            "estimated": True,
            "reused_formula_id": "motor-vehicle-pcaf",
            "reused_methodology": (
                f"{denom_ref}; compute_motor_vehicle_pcaf_financed on "
                "fuel × published factor (UoP form has no EPA fuel catalog)."
            ),
        }
    )
    return result


def _economic_score5(
    result: Dict[str, Any],
    *,
    asset_class: str,
    name: str,
    allocated: float,
    estimation: Dict[str, Any],
) -> Dict[str, Any]:
    if asset_class not in SCORE5_ASSET_CLASSES:
        return _unsupported(result, f"{name}: {UNSUPPORTED_SCORE5_MESSAGE}", "unsupported_score5")
    factor = _intensity_tco2e_per_unit(estimation, physical=False)
    weight_pct = _num(_pick(estimation, "sectorAllocationPercent", "sector_allocation_percent"))
    if factor is None or weight_pct is None:
        return _incomplete(
            result,
            "missing_economic_factor",
            (
                f"{name}: score-5 economic estimation needs a sector "
                "allocation % and a published intensity (tCO2e per "
                "currency of outstanding/asset). Factors are not invented "
                "and EPA/DESNZ energy factors are not used as EEIO intensities."
            ),
        )
    if weight_pct < 0:
        raise UnderlyingInputError(f"{name}: sector allocation % cannot be negative.")
    weight = weight_pct / 100.0
    structure_fe = allocated * weight * factor
    result.update(
        {
            "status": COMPLETE,
            "asset_attribution_factor": None,
            "sector_allocation_percent": weight_pct,
            "emission_factor": factor,
            "structure_scope1_tco2e": None,
            "structure_scope2_tco2e": None,
            "structure_scope3_tco2e": None,
            "structure_unallocated_tco2e": structure_fe,
            "structure_financed_emissions": structure_fe,
            "data_quality_score": 5.0,
            "option_code": "3 / score-5",
            "estimated": True,
            "reused_formula_id": "uop-score5",
            "reused_methodology": (
                "PCAF §5.7 Data required score 5: Outstanding × Σ "
                "(sector allocation % × sector emission factor)"
            ),
            "equation": "allocated_outstanding × sector_weight × intensity",
        }
    )
    return result


def _missing_option_input(result: Dict[str, Any], name: str, message: str) -> Dict[str, Any]:
    return _incomplete(result, "missing_option_inputs", f"{name}: {message}")


def _corporate_3a(
    result: Dict[str, Any],
    *,
    asset_class: str,
    name: str,
    allocated: float,
    denom: Optional[float],
    denom_label: str,
    denom_ref: str,
    estimation: Dict[str, Any],
) -> Dict[str, Any]:
    if denom is None or denom <= 0:
        return _incomplete(
            result,
            "missing_asset_denominator",
            f"{name}: {denom_label} is required for option 3a attribution.",
        )
    revenue = _num(_pick(estimation, "companyRevenue", "company_revenue"))
    intensity = _num(
        _pick(estimation, "sectorIntensity", "sector_intensity", "emissionFactor", "emission_factor")
    )
    unit = _text(
        _pick(
            estimation,
            "sectorIntensityUnit",
            "sector_intensity_unit",
            "factorUnit",
            "factor_unit",
        )
    )
    if revenue is None or intensity is None:
        return _missing_option_input(
            result,
            name,
            "option 3a needs company/project revenue and a published sector intensity. "
            "Factors are not invented.",
        )
    formula_id, company_type = _formula_for(asset_class, "3a")
    if not formula_id:
        return _unsupported(result, f"{name}: no 3a formula for {asset_class}.")
    inputs = _corporate_denom_inputs(asset_class, allocated, denom)
    inputs["company_revenue"] = revenue
    inputs["sector_intensity"] = intensity
    if unit:
        inputs["sector_intensity_unit"] = unit
    try:
        calc = _run_engine(formula_id, inputs, company_type)
    except ValueError as exc:
        return _incomplete(result, "underlying_engine_invalid", f"{name}: {exc}")
    return _apply_engine_result(
        result,
        calc,
        allocated=allocated,
        denom=denom,
        estimated=True,
        reused_methodology=f"{denom_ref}; {formula_id}",
    )


def _corporate_3c(
    result: Dict[str, Any],
    *,
    asset_class: str,
    name: str,
    allocated: float,
    denom_ref: str,
    estimation: Dict[str, Any],
) -> Dict[str, Any]:
    atr = _num(_pick(estimation, "assetTurnoverRatio", "asset_turnover_ratio"))
    intensity = _num(
        _pick(estimation, "sectorIntensity", "sector_intensity", "emissionFactor", "emission_factor")
    )
    unit = _text(
        _pick(
            estimation,
            "sectorIntensityUnit",
            "sector_intensity_unit",
            "factorUnit",
            "factor_unit",
        )
    )
    if atr is None or intensity is None:
        return _missing_option_input(
            result,
            name,
            "option 3c needs a published asset-turnover ratio and sector intensity. "
            "Factors are not invented.",
        )
    formula_id, company_type = _formula_for(asset_class, "3c")
    if not formula_id:
        return _unsupported(result, f"{name}: no 3c formula for {asset_class}.")
    inputs = {
        "outstanding_amount": allocated,
        "asset_turnover_ratio": atr,
        "sector_intensity": intensity,
    }
    if unit:
        inputs["sector_intensity_unit"] = unit
    try:
        calc = _run_engine(formula_id, inputs, company_type)
    except ValueError as exc:
        return _incomplete(result, "underlying_engine_invalid", f"{name}: {exc}")
    return _apply_engine_result(
        result,
        calc,
        allocated=allocated,
        denom=None,
        estimated=True,
        reused_methodology=f"{denom_ref}; {formula_id}",
    )


def _building_option(
    result: Dict[str, Any],
    *,
    asset_class: str,
    name: str,
    allocated: float,
    denom: Optional[float],
    denom_label: str,
    denom_ref: str,
    option: str,
    estimation: Dict[str, Any],
) -> Dict[str, Any]:
    if denom is None or denom <= 0:
        return _incomplete(
            result,
            "missing_asset_denominator",
            f"{name}: {denom_label} is required for the building method.",
        )
    formula_id, company_type = _formula_for(asset_class, option)
    if not formula_id:
        return _unsupported(result, f"{name}: no {option} formula for {asset_class}.")
    factor = _intensity_tco2e_per_unit(estimation, physical=True)
    inputs: Dict[str, Any] = {
        "outstanding_amount": allocated,
        "property_value_at_origination": denom,
    }
    if option in ("1a", "1b"):
        energy = _num(
            _pick(estimation, "energyConsumption", "energy_consumption", "physicalActivityAmount", "physical_activity_amount")
        )
        if energy is None or factor is None:
            return _missing_option_input(
                result,
                name,
                "building option 1a/1b needs actual energy consumption and a published factor.",
            )
        inputs["energy_consumption"] = energy
        inputs["emission_factor"] = factor
    elif option == "2a":
        intensity = _num(
            _pick(
                estimation,
                "labelEnergyIntensity",
                "label_energy_intensity",
                "estimated_energy_consumption_from_labels",
            )
        )
        floor_area = _num(_pick(estimation, "floorArea", "floor_area"))
        if intensity is None or floor_area is None or factor is None:
            return _missing_option_input(
                result,
                name,
                "building option 2a needs label energy intensity, floor area, and a published average grid factor.",
            )
        inputs["estimated_energy_consumption_from_labels"] = intensity
        inputs["floor_area"] = floor_area
        inputs["average_emission_factor"] = factor
    elif option == "2b":
        intensity = _num(
            _pick(
                estimation,
                "statsEnergyIntensity",
                "stats_energy_intensity",
                "estimated_energy_consumption_from_statistics",
            )
        )
        floor_area = _num(_pick(estimation, "floorArea", "floor_area"))
        if intensity is None or floor_area is None or factor is None:
            return _missing_option_input(
                result,
                name,
                "building option 2b needs statistical energy intensity, floor area, and a published average factor.",
            )
        inputs["estimated_energy_consumption_from_statistics"] = intensity
        inputs["floor_area"] = floor_area
        inputs["average_emission_factor"] = factor
    elif option == "3":
        intensity = _num(
            _pick(
                estimation,
                "statsEnergyIntensity",
                "stats_energy_intensity",
                "estimated_energy_consumption_from_statistics",
            )
        )
        buildings = _num(_pick(estimation, "numberOfBuildings", "number_of_buildings"))
        if intensity is None or buildings is None or factor is None:
            return _missing_option_input(
                result,
                name,
                "building option 3 needs statistical energy per building, number of buildings, and a published average factor.",
            )
        inputs["estimated_energy_consumption_from_statistics"] = intensity
        inputs["number_of_buildings"] = buildings
        inputs["average_emission_factor"] = factor
    else:
        return _unsupported(result, f"{name}: building option {option} is not configured.")
    try:
        calc = _run_engine(formula_id, inputs, company_type)
    except ValueError as exc:
        return _incomplete(result, "underlying_engine_invalid", f"{name}: {exc}")
    return _apply_engine_result(
        result,
        calc,
        allocated=allocated,
        denom=denom,
        estimated=option not in ("1a", "1b"),
        reused_methodology=f"{denom_ref}; {formula_id}",
    )


def _motor_option(
    result: Dict[str, Any],
    *,
    name: str,
    allocated: float,
    denom: Optional[float],
    denom_label: str,
    denom_ref: str,
    option: str,
    estimation: Dict[str, Any],
) -> Dict[str, Any]:
    if denom is None or denom <= 0:
        return _incomplete(
            result,
            "missing_asset_denominator",
            f"{name}: {denom_label} is required for the motor-vehicle method.",
        )
    formula_id = f"{option}-motor-vehicle"
    factor = _intensity_tco2e_per_unit(estimation, physical=True)
    inputs: Dict[str, Any] = {
        "outstanding_amount": allocated,
        "total_value_at_origination": denom,
        "emission_factor": factor,
    }
    if option == "1a":
        fuel = _num(
            _pick(estimation, "fuelConsumption", "fuel_consumption", "physicalActivityAmount", "physical_activity_amount")
        )
        if fuel is None or factor is None:
            return _missing_option_input(
                result,
                name,
                "motor-vehicle option 1a needs fuel consumption and a published fuel factor. "
                "EPA values are not substituted automatically.",
            )
        inputs["fuel_consumption"] = fuel
    else:
        distance = _num(
            _pick(estimation, "distanceTraveled", "distance_traveled", "physicalActivityAmount", "physical_activity_amount")
        )
        efficiency = _num(_pick(estimation, "efficiency"))
        if distance is None or efficiency is None or factor is None:
            return _missing_option_input(
                result,
                name,
                f"motor-vehicle option {option} needs distance, efficiency, and a published fuel factor. "
                "EPA values are not substituted automatically.",
            )
        inputs["distance_traveled"] = distance
        inputs["efficiency"] = efficiency
    try:
        calc = _run_engine(formula_id, inputs, CompanyType.PRIVATE)
    except ValueError as exc:
        return _incomplete(result, "underlying_engine_invalid", f"{name}: {exc}")
    return _apply_engine_result(
        result,
        calc,
        allocated=allocated,
        denom=denom,
        estimated=option not in ("1a", "1b"),
        reused_methodology=f"{denom_ref}; {formula_id}",
    )


def _calculate_selected_option(
    result: Dict[str, Any],
    *,
    asset_class: str,
    name: str,
    allocated: float,
    denom: Optional[float],
    denom_label: str,
    denom_ref: str,
    option: str,
    estimation: Dict[str, Any],
) -> Dict[str, Any]:
    allowed = ALLOWED_OPTIONS.get(asset_class) or set()
    if option not in allowed:
        return _unsupported(
            result,
            (
                f"{name}: PCAF option {option} is not a verified method for "
                f"asset class '{asset_class}'."
            ),
            "unsupported_physical_option",
        )
    if asset_class in LISTED_CLASSES | UNLISTED_CLASSES | PROJECT_CLASSES:
        if option == "2a":
            activity = _num(
                _pick(
                    estimation,
                    "energyConsumption",
                    "energy_consumption",
                    "physicalActivityAmount",
                    "physical_activity_amount",
                )
            )
            factor = _intensity_tco2e_per_unit(estimation, physical=True)
            if activity is None or factor is None:
                return _missing_option_input(
                    result,
                    name,
                    "option 2a needs energy consumption and a published energy factor.",
                )
            out = _physical_corporate_or_project(
                result,
                asset_class=asset_class,
                name=name,
                allocated=allocated,
                denom=denom,
                denom_label=denom_label,
                denom_ref=denom_ref,
                kind="energy",
                activity=activity,
                factor=factor,
            )
            process = _num(_pick(estimation, "processEmissions", "process_emissions"))
            if process is not None and out.get("status") == COMPLETE:
                # Re-run with optional process emissions so the engine, not UoP, adds them.
                formula_id, company_type = _formula_for(asset_class, "2a")
                if formula_id and denom:
                    inputs = _corporate_denom_inputs(asset_class, allocated, denom)
                    inputs["energy_consumption"] = activity
                    inputs["emission_factor"] = factor
                    inputs["process_emissions"] = process
                    try:
                        calc = _run_engine(formula_id, inputs, company_type)
                    except ValueError as exc:
                        return _incomplete(result, "underlying_engine_invalid", f"{name}: {exc}")
                    return _apply_engine_result(
                        result,
                        calc,
                        allocated=allocated,
                        denom=denom,
                        estimated=True,
                        reused_methodology=f"{denom_ref}; {formula_id}",
                    )
            return out
        if option == "2b":
            activity = _num(
                _pick(
                    estimation,
                    "productionAmount",
                    "production_amount",
                    "production",
                    "physicalActivityAmount",
                    "physical_activity_amount",
                )
            )
            factor = _intensity_tco2e_per_unit(estimation, physical=True)
            if activity is None or factor is None:
                return _missing_option_input(
                    result,
                    name,
                    "option 2b needs production and a published production factor.",
                )
            return _physical_corporate_or_project(
                result,
                asset_class=asset_class,
                name=name,
                allocated=allocated,
                denom=denom,
                denom_label=denom_label,
                denom_ref=denom_ref,
                kind="production",
                activity=activity,
                factor=factor,
            )
        if option == "3a":
            return _corporate_3a(
                result,
                asset_class=asset_class,
                name=name,
                allocated=allocated,
                denom=denom,
                denom_label=denom_label,
                denom_ref=denom_ref,
                estimation=estimation,
            )
        if option == "3c":
            return _corporate_3c(
                result,
                asset_class=asset_class,
                name=name,
                allocated=allocated,
                denom_ref=denom_ref,
                estimation=estimation,
            )
        if option == "score5":
            return _economic_score5(
                result,
                asset_class=asset_class,
                name=name,
                allocated=allocated,
                estimation=estimation,
            )
    if asset_class in BUILDING_CLASSES:
        return _building_option(
            result,
            asset_class=asset_class,
            name=name,
            allocated=allocated,
            denom=denom,
            denom_label=denom_label,
            denom_ref=denom_ref,
            option=option,
            estimation=estimation,
        )
    if asset_class in MOTOR_CLASSES:
        return _motor_option(
            result,
            name=name,
            allocated=allocated,
            denom=denom,
            denom_label=denom_label,
            denom_ref=denom_ref,
            option=option,
            estimation=estimation,
        )
    return _unsupported(result, f"{name}: no verified PCAF option mapper for {asset_class}.")


def calculate_underlying_asset(
    asset: Dict[str, Any],
    *,
    denom_kind: str,
    denom_label: str,
    denom_ref: str,
) -> Dict[str, Any]:
    asset_id = _text(_pick(asset, "underlyingAssetId", "underlying_asset_id"))
    name = _text(_pick(asset, "name")) or asset_id or "Underlying asset"
    asset_class = _text(_pick(asset, "assetClass", "asset_class"))
    allocated = _num(_pick(asset, "allocatedOutstanding", "allocated_outstanding"))
    denom = _num(_pick(asset, "totalAssetValue", "total_asset_value"))
    result: Dict[str, Any] = {
        "underlying_asset_id": asset_id,
        "name": name,
        "asset_class": asset_class,
        "allocated_outstanding": allocated,
        "status": COMPLETE,
        "denominator_kind": denom_kind,
        "denominator_label": denom_label,
        "pcaf_ref": denom_ref,
    }
    verification = _text(_pick(asset, "verificationStatus", "verification_status"))
    has_reported = _text(_pick(asset, "hasReportedEmissions", "has_reported_emissions"))
    if has_reported == "yes":
        s1 = _num(_pick(asset, "scope1Emissions", "scope1_emissions"))
        s2 = _num(_pick(asset, "scope2Emissions", "scope2_emissions"))
        s3 = _num(_pick(asset, "scope3Emissions", "scope3_emissions"))
        kwargs = dict(
            result=result,
            name=name,
            allocated=allocated or 0.0,
            denom=denom,
            denom_label=denom_label,
            denom_ref=denom_ref,
            verification=verification,
            s1=s1,
            s2=s2,
            s3=s3,
        )
        if asset_class in LISTED_CLASSES | UNLISTED_CLASSES | PROJECT_CLASSES:
            return _reported_corporate_or_project(asset_class=asset_class, **kwargs)
        if asset_class in BUILDING_CLASSES:
            return _reported_building(**kwargs)
        if asset_class in MOTOR_CLASSES:
            return _reported_motor(asset_id=asset_id, **kwargs)
        return _unsupported(result, f"{name}: no verified reported-emissions method for {asset_class}.")

    estimation = _pick(asset, "estimation", default={}) or {}
    if not isinstance(estimation, dict):
        estimation = {}
    method = _text(_pick(estimation, "method"))
    option = _text(_pick(estimation, "pcafOption", "pcaf_option", "optionCode", "option_code"))
    source = _text(_pick(estimation, "factorSource", "factor_source", "emissionFactorSource"))
    if not source and not _text(_pick(estimation, "factorDatasetCode", "factor_dataset_code")):
        return _incomplete(
            result,
            "missing_factor_source",
            (
                f"{name}: a published factor source is required. "
                "Emission factors are not invented."
            ),
        )

    if option:
        return _calculate_selected_option(
            result,
            asset_class=asset_class,
            name=name,
            allocated=allocated or 0.0,
            denom=denom,
            denom_label=denom_label,
            denom_ref=denom_ref,
            option=option,
            estimation=estimation,
        )

    if method == "physical":
        activity = _num(_pick(estimation, "physicalActivityAmount", "physical_activity_amount"))
        factor = _intensity_tco2e_per_unit(estimation, physical=True)
        if activity is None or factor is None:
            return _incomplete(
                result,
                "missing_physical_factor",
                (
                    f"{name}: physical-activity estimation needs an activity "
                    "amount and a published factor in tCO2e per activity unit. "
                    "EPA/DESNZ values are not substituted automatically."
                ),
            )
        kind = classify_physical_unit(
            _text(_pick(estimation, "physicalActivityUnit", "physical_activity_unit"))
        )
        if asset_class in LISTED_CLASSES | UNLISTED_CLASSES | PROJECT_CLASSES:
            if kind == "energy":
                return _physical_corporate_or_project(
                    result,
                    asset_class=asset_class,
                    name=name,
                    allocated=allocated or 0.0,
                    denom=denom,
                    denom_label=denom_label,
                    denom_ref=denom_ref,
                    kind="energy",
                    activity=activity,
                    factor=factor,
                )
            if kind == "production":
                return _physical_corporate_or_project(
                    result,
                    asset_class=asset_class,
                    name=name,
                    allocated=allocated or 0.0,
                    denom=denom,
                    denom_label=denom_label,
                    denom_ref=denom_ref,
                    kind="production",
                    activity=activity,
                    factor=factor,
                )
            return _unsupported(
                result,
                f"{name}: {UNSUPPORTED_PHYSICAL['unmapped-unit']}",
                "unsupported_physical_option",
            )
        if asset_class in BUILDING_CLASSES:
            if kind == "energy":
                return _physical_building_energy(
                    result,
                    asset_class=asset_class,
                    name=name,
                    allocated=allocated or 0.0,
                    denom=denom,
                    denom_label=denom_label,
                    denom_ref=denom_ref,
                    verification=verification,
                    activity=activity,
                    factor=factor,
                )
            if kind == "floor_area":
                return _unsupported(
                    result,
                    f"{name}: {UNSUPPORTED_PHYSICAL['building-floor-area']}",
                    "unsupported_physical_option",
                )
            return _unsupported(
                result,
                f"{name}: {UNSUPPORTED_PHYSICAL['unmapped-unit']}",
                "unsupported_physical_option",
            )
        if asset_class in MOTOR_CLASSES:
            if kind == "fuel":
                return _physical_motor_fuel(
                    result,
                    asset_id=asset_id,
                    name=name,
                    allocated=allocated or 0.0,
                    denom=denom,
                    denom_label=denom_label,
                    denom_ref=denom_ref,
                    activity=activity,
                    factor=factor,
                )
            if kind == "distance":
                return _unsupported(
                    result,
                    f"{name}: {UNSUPPORTED_PHYSICAL['motor-distance']}",
                    "unsupported_physical_option",
                )
            return _unsupported(
                result,
                f"{name}: {UNSUPPORTED_PHYSICAL['unmapped-unit']}",
                "unsupported_physical_option",
            )
        return _unsupported(result, f"{name}: {UNSUPPORTED_PHYSICAL['unmapped-unit']}", "unsupported_physical_option")

    if method == "economic":
        return _economic_score5(
            result,
            asset_class=asset_class,
            name=name,
            allocated=allocated or 0.0,
            estimation=estimation,
        )

    return _incomplete(
        result,
        "missing_estimation_method",
        f"{name}: choose reported emissions, physical activity, or economic estimation.",
    )


def calculate_issuer_level(payload: Dict[str, Any], outstanding: float) -> Dict[str, Any]:
    """
    Figure 5-1 Step 3a issuer-level method reused for integrated UoP
    unallocated amounts, and for footnote 168 combined allocated+unallocated
    when look-through is not possible.
    """
    emissions = _num(
        _pick(
            payload,
            "issuerEmissions",
            "issuer_emissions",
            "verified_emissions",
            "unverified_emissions",
        )
    )
    s1 = _num(_pick(payload, "scope1Emissions", "scope1_emissions"))
    s2 = _num(_pick(payload, "scope2Emissions", "scope2_emissions"))
    s3 = _num(_pick(payload, "scope3Emissions", "scope3_emissions"))
    if emissions is None:
        present = [value for value in (s1, s2, s3) if value is not None]
        emissions = sum(present) if present else None
    company_type = _text(_pick(payload, "companyType", "company_type", "issuerCompanyType"))
    verification = _text(_pick(payload, "verificationStatus", "verification_status"))
    option = "1a" if verification == "verified" else "1b"
    emissions_key = "verified_emissions" if option == "1a" else "unverified_emissions"
    if company_type == "listed":
        denom = _num(_pick(payload, "evic", "issuerEvic", "issuer_evic"))
        denom_label = "EVIC"
        formula_id = f"{option}-listed-equity"
        engine_type = CompanyType.LISTED
        inputs = {
            "outstanding_amount": outstanding,
            "evic": denom,
            "total_assets": denom,
            emissions_key: emissions,
        }
        ref = "PCAF §5.1 / Figure 5-1 Step 3a"
    elif company_type in ("unlisted", "private"):
        denom = _num(
            _pick(
                payload,
                "totalEquityPlusDebt",
                "total_equity_plus_debt",
                "issuerEquityPlusDebt",
            )
        )
        denom_label = "Total equity + debt"
        formula_id = f"{option}-unlisted-equity"
        engine_type = CompanyType.PRIVATE
        inputs = {
            "outstanding_amount": outstanding,
            "total_equity_plus_debt": denom,
            "total_assets": denom,
            emissions_key: emissions,
        }
        ref = "PCAF §5.2 / Figure 5-1 Step 3a"
    else:
        return {
            "status": INCOMPLETE,
            "code": "missing_issuer_level_data",
            "message": (
                "Integrated UoP unallocated amounts use issuer-level data "
                "(PCAF §5.7; Figure 5-1 Step 3a). Provide issuer company type "
                "and EVIC or equity+debt plus issuer emissions. Corporate "
                "inventories are not inferred from the UoP structure report."
            ),
        }
    if denom is None or denom <= 0 or emissions is None:
        return {
            "status": INCOMPLETE,
            "code": "missing_issuer_level_data",
            "message": (
                f"Issuer-level unallocated calculation needs {denom_label} > 0 "
                "and issuer emissions. Missing values are not treated as zero."
            ),
        }
    if s1 is not None:
        inputs["scope1_emissions"] = s1
    if s2 is not None:
        inputs["scope2_emissions"] = s2
    if s3 is not None:
        inputs["scope3_emissions"] = s3
    try:
        calc = _run_engine(formula_id, inputs, engine_type)
    except ValueError as exc:
        return {
            "status": INCOMPLETE,
            "code": "missing_issuer_level_data",
            "message": str(exc),
        }
    s1_fe, s2_fe, s3_fe, unallocated = _scopes_from_engine(calc)
    return {
        "status": COMPLETE,
        "financed_emissions": calc.financed_emissions,
        "attribution_factor": calc.attribution_factor,
        "denominator": denom,
        "denominator_label": denom_label,
        "pcaf_ref": f"PCAF §5.7 unallocated amounts; {ref}; {formula_id}",
        "data_quality_score": float(calc.data_quality_score),
        "reused_formula_id": formula_id,
        "scope1_tco2e": s1_fe,
        "scope2_tco2e": s2_fe,
        "scope3_tco2e": s3_fe,
        "unallocated_tco2e": unallocated,
        "estimated": False,
    }


def score5_sector_intensity(assets: List[Dict[str, Any]]) -> Tuple[Optional[float], int]:
    """Sum of (sector % × EF) using only score-5-eligible asset classes."""
    weighted = 0.0
    used = 0
    for asset in assets:
        asset_class = _text(_pick(asset, "assetClass", "asset_class"))
        if asset_class not in SCORE5_ASSET_CLASSES:
            continue
        estimation = asset.get("estimation") or {}
        if not isinstance(estimation, dict):
            continue
        if _text(_pick(estimation, "method")) not in ("", "economic"):
            continue
        factor = _intensity_tco2e_per_unit(estimation, physical=False)
        pct = _num(_pick(estimation, "sectorAllocationPercent", "sector_allocation_percent"))
        if factor is None or pct is None:
            continue
        weighted += (pct / 100.0) * factor
        used += 1
    if used == 0:
        return None, 0
    return weighted, used
