"""
PCAF financed-emissions scope breakdown (Phase 3C).

Does not change the existing financed_emissions total except to reject
internally inconsistent outputs. Missing scopes stay None — never coerced to 0.

PCAF Part A 2nd edition (December 2022):
- Listed equity / bonds / business loans / unlisted equity: shall report
  borrower/investee Scope 1 and 2; Scope 3 is phase-in and disclosed separately.
- Option 2a cannot estimate Scope 3.
- Project finance: shall report project Scope 1 and 2; Scope 3 if relevant.
- CRE / mortgages: shall cover building-energy Scope 1 and 2; construction/
  embodied Scope 3 is optional and not collected here.
- Motor vehicles: shall report vehicle operation Scope 1 and 2; production
  Scope 3 is optional and not collected here.
- Sovereign: shall report production (PCAF sovereign Scope 1); Scope 2 and 3
  should be reported under PCAF's sovereign definitions when available.
- Facilitated company emissions follow the listed-equity/bond scope rules,
  then the facilitated weighting factor is applied to each included scope.

Estimated intensity/production methods that cannot be split are stored as an
explicit unallocated total covering the method's applicable scopes.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from .finance_models import CalculationResult, FormulaCategory, FormulaConfig

PCAF_METHODOLOGY_VERSION = "PCAF-PartA-2022-2nd"
PCAF_EMISSIONS_UNIT = "tCO2e"
SCOPE_TOTAL_ABS_TOLERANCE = 1e-6
SCOPE_TOTAL_REL_TOLERANCE = 1e-6

COMPANY_GHG_CATEGORIES = {
    FormulaCategory.LISTED_EQUITY,
    FormulaCategory.BUSINESS_LOANS,
    FormulaCategory.PROJECT_FINANCE,
    FormulaCategory.FACILITATED_EMISSION,
}
BUILDING_ENERGY_CATEGORIES = {
    FormulaCategory.MORTGAGE,
    FormulaCategory.COMMERCIAL_REAL_ESTATE,
}

Status = str  # reported | zero | missing | excluded | not_applicable | estimated | unallocated


def optional_number(inputs: Dict[str, Any], *keys: str) -> Optional[float]:
    """Return a finite float, or None when the field is absent/blank. 0 stays 0."""
    for key in keys:
        if key not in inputs:
            continue
        value = inputs[key]
        if value is None or value == "":
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be a finite number") from None
        if number != number or number in (float("inf"), float("-inf")):
            raise ValueError(f"{key} must be a finite number")
        return number
    return None


def weighting_factor(inputs: Dict[str, Any]) -> float:
    value = optional_number(inputs, "weighting_factor", "weightingFactor")
    if value is None:
        return 1.0
    if value < 0:
        raise ValueError("Weighting factor must be non-negative")
    return value


def _attribute(value: Optional[float], factor: float) -> Optional[float]:
    if value is None:
        return None
    return factor * value


def _status(value: Optional[float], *, excluded: bool = False, estimated: bool = False) -> Status:
    if excluded:
        return "excluded"
    if value is None:
        return "missing"
    if estimated:
        return "estimated"
    if value == 0:
        return "zero"
    return "reported"


def _close(actual: float, expected: float) -> bool:
    scale = max(abs(actual), abs(expected), 1.0)
    return abs(actual - expected) <= max(SCOPE_TOTAL_ABS_TOLERANCE, SCOPE_TOTAL_REL_TOLERANCE * scale)


def _lists(
    scope_status: Dict[str, Status],
    included: Iterable[str],
) -> Dict[str, List[str]]:
    included_set = [name for name in ("scope1", "scope2", "scope3") if name in set(included)]
    missing = [name for name, status in scope_status.items() if status == "missing"]
    excluded = [name for name, status in scope_status.items() if status == "excluded"]
    not_applicable = [name for name, status in scope_status.items() if status == "not_applicable"]
    return {
        "included_scopes": included_set,
        "missing_scopes": missing,
        "excluded_scopes": excluded,
        "not_applicable_scopes": not_applicable,
    }


def _payload(
    *,
    s1: Optional[float],
    s2: Optional[float],
    s3: Optional[float],
    unallocated: Optional[float],
    financed_emissions: float,
    scope_status: Dict[str, Status],
    included: Iterable[str],
    completeness: str,
    calculation_method: str,
    notes: List[str],
    estimated: bool,
) -> Dict[str, Any]:
    included_values = [
        value
        for value in (s1, s2, s3, unallocated)
        if value is not None
    ]
    reconstructed = sum(included_values) if included_values else None
    if reconstructed is not None and not _close(reconstructed, financed_emissions):
        raise ValueError(
            "Financed scope breakdown is inconsistent with the financed-emissions total"
        )
    lists = _lists(scope_status, included)
    return {
        "financed_scope1_tco2e": s1,
        "financed_scope2_tco2e": s2,
        "financed_scope3_tco2e": s3,
        "financed_unallocated_tco2e": unallocated,
        "financed_emissions_tco2e": financed_emissions,
        "included_scopes": lists["included_scopes"],
        "missing_scopes": lists["missing_scopes"],
        "excluded_scopes": lists["excluded_scopes"],
        "not_applicable_scopes": lists["not_applicable_scopes"],
        "scope_status": scope_status,
        "scope_completeness": completeness,
        "calculation_method": calculation_method,
        "methodology_version": PCAF_METHODOLOGY_VERSION,
        "emissions_unit": PCAF_EMISSIONS_UNIT,
        "estimated": estimated,
        "notes": notes,
    }


def reported_company_scope_total(inputs: Dict[str, Any]) -> Optional[float]:
    scopes = [
        optional_number(inputs, "scope1_emissions", "scope1Emissions"),
        optional_number(inputs, "scope2_emissions", "scope2Emissions"),
        optional_number(inputs, "scope3_emissions", "scope3Emissions"),
    ]
    present = [value for value in scopes if value is not None]
    if not present:
        return None
    return float(sum(present))


def option_1_company_emissions(inputs: Dict[str, Any], verified: bool) -> Optional[float]:
    """Preserve the existing 1a/1b total: explicit verified/unverified, else reported scopes."""
    key = "verified_emissions" if verified else "unverified_emissions"
    alt = "verifiedEmissions" if verified else "unverifiedEmissions"
    total = optional_number(inputs, key, alt)
    scopes = reported_company_scope_total(inputs)
    if total is not None and scopes is not None and not _close(total, scopes):
        raise ValueError(
            "Reported scope emissions do not match the company emissions total"
        )
    if total is not None:
        return total
    return scopes


def _attribution_multiplier(inputs: Dict[str, Any], category: FormulaCategory, attribution_factor: float) -> float:
    weight = weighting_factor(inputs) if category == FormulaCategory.FACILITATED_EMISSION else 1.0
    return attribution_factor * weight


def _company_option_1(
    inputs: Dict[str, Any],
    attribution_factor: float,
    financed_emissions: float,
    option_code: str,
    notes: List[str],
    category: FormulaCategory,
) -> Dict[str, Any]:
    factor = _attribution_multiplier(inputs, category, attribution_factor)
    s1_in = optional_number(inputs, "scope1_emissions", "scope1Emissions")
    s2_in = optional_number(inputs, "scope2_emissions", "scope2Emissions")
    s3_in = optional_number(inputs, "scope3_emissions", "scope3Emissions")
    if s1_in is None and s2_in is None and s3_in is None:
        return _payload(
            s1=None,
            s2=None,
            s3=None,
            unallocated=financed_emissions,
            financed_emissions=financed_emissions,
            scope_status={
                "scope1": "unallocated",
                "scope2": "unallocated",
                "scope3": "unallocated",
            },
            included=("scope1", "scope2", "scope3"),
            completeness="total_only",
            calculation_method=option_code,
            notes=notes
            + [
                "No per-scope company GHG was provided; the attributed total is stored unallocated."
            ],
            estimated=False,
        )
    notes = notes + [
        "PCAF requires separate disclosure of borrower/investee Scope 3 where applicable; missing Scope 3 is not treated as zero."
    ]
    return _payload(
        s1=_attribute(s1_in, factor),
        s2=_attribute(s2_in, factor),
        s3=_attribute(s3_in, factor),
        unallocated=None,
        financed_emissions=financed_emissions,
        scope_status={
            "scope1": _status(s1_in),
            "scope2": _status(s2_in),
            "scope3": _status(s3_in),
        },
        included=[
            name
            for name, value in (("scope1", s1_in), ("scope2", s2_in), ("scope3", s3_in))
            if value is not None
        ],
        completeness="complete" if None not in (s1_in, s2_in, s3_in) else "partial",
        calculation_method=option_code,
        notes=notes,
        estimated=False,
    )


def _company_option_2a(
    inputs: Dict[str, Any],
    attribution_factor: float,
    financed_emissions: float,
    option_code: str,
    notes: List[str],
    category: FormulaCategory,
) -> Dict[str, Any]:
    """Electricity activity is Scope 2; optional process emissions are Scope 1. Scope 3 excluded."""
    factor = _attribution_multiplier(inputs, category, attribution_factor)
    energy = optional_number(inputs, "energy_consumption", "energyConsumption") or 0.0
    emission_factor = optional_number(inputs, "emission_factor", "emissionFactor") or 0.0
    process = optional_number(inputs, "process_emissions", "processEmissions")
    s2_in = energy * emission_factor
    notes = notes + [
        "PCAF Option 2a cannot estimate Scope 3. Electricity activity is attributed as Scope 2; process emissions, when provided, as Scope 1."
    ]
    return _payload(
        s1=_attribute(process, factor),
        s2=_attribute(s2_in, factor),
        s3=None,
        unallocated=None,
        financed_emissions=financed_emissions,
        scope_status={
            "scope1": _status(process),
            "scope2": _status(s2_in),
            "scope3": "excluded",
        },
        included=["scope2"] + (["scope1"] if process is not None else []),
        completeness="partial",
        calculation_method=option_code,
        notes=notes,
        estimated=False,
    )


def _total_only(
    financed_emissions: float,
    option_code: str,
    included: Iterable[str],
    excluded: Iterable[str],
    missing: Iterable[str],
    notes: List[str],
    estimated: bool,
    completeness: str = "total_only",
) -> Dict[str, Any]:
    included_list = list(included)
    status = {
        "scope1": "unallocated" if "scope1" in included_list else "missing",
        "scope2": "unallocated" if "scope2" in included_list else "missing",
        "scope3": "unallocated" if "scope3" in included_list else "missing",
    }
    for name in excluded:
        status[name] = "excluded"
    for name in missing:
        status[name] = "missing"
    if estimated:
        for name in included_list:
            if status[name] == "unallocated":
                status[name] = "estimated"
    return _payload(
        s1=None,
        s2=None,
        s3=None,
        unallocated=financed_emissions,
        financed_emissions=financed_emissions,
        scope_status=status,
        included=included_list,
        completeness=completeness,
        calculation_method=option_code,
        notes=notes,
        estimated=estimated,
    )


def build_scope_breakdown(
    formula: FormulaConfig,
    inputs: Dict[str, Any],
    attribution_factor: float,
    financed_emissions: float,
) -> Dict[str, Any]:
    if not _close(float(financed_emissions), float(financed_emissions)):
        raise ValueError("financed_emissions must be finite")
    option = formula.option_code
    category = formula.category
    notes: List[str] = []

    if category in COMPANY_GHG_CATEGORIES:
        if option in ("1a", "1b"):
            return _company_option_1(
                inputs, attribution_factor, financed_emissions, option, notes, category
            )
        if option == "2a":
            return _company_option_2a(
                inputs, attribution_factor, financed_emissions, option, notes, category
            )
        return _total_only(
            financed_emissions,
            option,
            included=("scope1", "scope2", "scope3"),
            excluded=(),
            missing=(),
            notes=notes
            + [
                "This PCAF option uses an estimated or production factor that cannot be split into GHG Protocol scopes."
            ],
            estimated=True,
        )

    if category in BUILDING_ENERGY_CATEGORIES:
        return _total_only(
            financed_emissions,
            option,
            included=("scope1", "scope2"),
            excluded=("scope3",),
            missing=(),
            notes=notes
            + [
                "PCAF requires building-energy Scope 1 and 2. This method does not separate fuels (Scope 1) from electricity (Scope 2)."
            ],
            estimated=option not in ("1a", "1b"),
        )

    if category == FormulaCategory.MOTOR_VEHICLE_LOAN:
        return _total_only(
            financed_emissions,
            option,
            included=("scope1", "scope2"),
            excluded=("scope3",),
            missing=(),
            notes=notes
            + [
                "PCAF requires vehicle-operation Scope 1 and 2. Production/embodied Scope 3 is optional and not collected. This method does not separate tailpipe (Scope 1) from vehicle electricity (Scope 2)."
            ],
            estimated=option not in ("1a", "1b"),
        )

    if category == FormulaCategory.SOVEREIGN_DEBT:
        if option in ("1a", "1b"):
            # UNFCCC territorial / production inventory maps to PCAF sovereign Scope 1.
            return _payload(
                s1=financed_emissions,
                s2=None,
                s3=None,
                unallocated=None,
                financed_emissions=financed_emissions,
                scope_status={
                    "scope1": "reported" if financed_emissions != 0 else "zero",
                    "scope2": "missing",
                    "scope3": "missing",
                },
                included=("scope1",),
                completeness="partial",
                calculation_method=option,
                notes=notes
                + [
                    "PCAF sovereign Scope 1 is production/territorial emissions. Scope 2 and 3 should be reported under PCAF sovereign definitions when available; they are not inferred here."
                ],
                estimated=False,
            )
        return _total_only(
            financed_emissions,
            option,
            included=("scope1",),
            excluded=(),
            missing=("scope2", "scope3"),
            notes=notes
            + [
                "Estimated sovereign method stored as an unallocated production-related total. Scope 2 and 3 are not inferred."
            ],
            estimated=True,
        )

    return _total_only(
        financed_emissions,
        option,
        included=("scope1", "scope2", "scope3"),
        excluded=(),
        missing=(),
        notes=notes + ["Scope breakdown is unavailable for this asset class."],
        estimated=True,
    )


def attach_scope_breakdown(
    formula: FormulaConfig,
    inputs: Dict[str, Any],
    result: CalculationResult,
) -> CalculationResult:
    breakdown = build_scope_breakdown(
        formula,
        inputs or {},
        float(result.attribution_factor),
        float(result.financed_emissions),
    )
    metadata = dict(result.metadata or {})
    metadata["scope_breakdown"] = breakdown
    metadata.setdefault("methodology_version", PCAF_METHODOLOGY_VERSION)
    metadata.setdefault("emissions_unit", PCAF_EMISSIONS_UNIT)
    result.metadata = metadata
    return result


def breakdown_api_fields(metadata: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    breakdown = dict((metadata or {}).get("scope_breakdown") or {})
    if not breakdown:
        return {}
    return {
        "financed_scope1_tco2e": breakdown.get("financed_scope1_tco2e"),
        "financed_scope2_tco2e": breakdown.get("financed_scope2_tco2e"),
        "financed_scope3_tco2e": breakdown.get("financed_scope3_tco2e"),
        "financed_unallocated_tco2e": breakdown.get("financed_unallocated_tco2e"),
        "included_scopes": breakdown.get("included_scopes") or [],
        "missing_scopes": breakdown.get("missing_scopes") or [],
        "excluded_scopes": breakdown.get("excluded_scopes") or [],
        "not_applicable_scopes": breakdown.get("not_applicable_scopes") or [],
        "scope_status": breakdown.get("scope_status") or {},
        "scope_completeness": breakdown.get("scope_completeness"),
        "calculation_method": breakdown.get("calculation_method"),
        "methodology_version": breakdown.get("methodology_version") or PCAF_METHODOLOGY_VERSION,
        "estimated": breakdown.get("estimated"),
        "notes": breakdown.get("notes") or [],
    }
