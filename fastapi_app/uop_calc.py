"""
PCAF 2025 Part A §5.7 Use of Proceeds calculation engine.

Formulas are taken from the official Third Edition (pages 98–109). Paths that
cannot be evidenced from that text are returned as unsupported/incomplete.
Does not write app.financed_emissions. Does not invent emission factors.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .uop_eligibility import resolve_uop_accounting, uop_qualifies
from .uop_underlying import (
    ISSUER_LEVEL_REASONS,
    UnderlyingInputError,
    calculate_issuer_level,
    calculate_underlying_asset,
    score5_sector_intensity,
)
from .uop_nested import calculate_nested_uop_asset
from .uop_sovereign import calculate_uop_sovereign_asset
from .uop_sub_sovereign import calculate_uop_sub_sovereign_asset

PCAF_UOP_EQUATIONS = "PCAF Part A 2025, §5.7 Equations to calculate financed emissions"
PCAF_UOP_ATTRIBUTION = "PCAF Part A 2025, §5.7 Attribution of emissions"
PCAF_UOP_DATA = "PCAF Part A 2025, §5.7 Data required"
EMISSIONS_UNIT = "tCO2e"
METHODOLOGY_VERSION = "PCAF-2025-PartA-5.7"
SCOPE_ABS_TOL = 1e-6
SCOPE_REL_TOL = 1e-6

# Asset-class attribution denominators from the matching Part A chapters,
# applied to the questionnaire field totalAssetValue.
ASSET_CLASS_DENOMINATOR = {
    "listed-equity": ("evic", "EVIC", "PCAF §5.1 Outstanding / EVIC"),
    "corporate-bond": ("evic", "EVIC", "PCAF §5.1 Outstanding / EVIC"),
    "business-loan": (
        "total_equity_plus_debt",
        "Total equity + debt",
        "PCAF §5.2 Outstanding / (equity + debt)",
    ),
    "unlisted-equity": (
        "total_equity_plus_debt",
        "Total equity + debt",
        "PCAF §5.2 Outstanding / (equity + debt)",
    ),
    "project-finance": (
        "total_project_equity_plus_debt",
        "Project equity + debt",
        "PCAF §5.3 Outstanding / (project equity + debt)",
    ),
    "commercial-real-estate": (
        "property_value_at_origination",
        "Property value at origination",
        "PCAF §5.4 Outstanding / property value at origination",
    ),
    "mortgage": (
        "property_value_at_origination",
        "Property value at origination",
        "PCAF §5.5 Outstanding / property value at origination",
    ),
    "motor-vehicle-loan": (
        "total_value_at_origination",
        "Vehicle value at origination",
        "PCAF §5.6 Outstanding / value at origination",
    ),
    "sovereign-debt": (
        "ppp_adjusted_gdp",
        "PPP-adjusted GDP",
        "PCAF §5.9 Outstanding / PPP-adjusted GDP",
    ),
    "sub-sovereign-debt": (
        "regional_ppp_adjusted_gdp",
        "Regional PPP-adjusted GDP",
        "PCAF §5.10 Outstanding / regional PPP-adjusted GDP (AF capped at 1)",
    ),
    "use-of-proceeds": (
        "child_total_capital",
        "Child structure total capital",
        "PCAF §5.7 nested look-through (parent allocation / child capital)",
    ),
}

# Territory-based sub-sovereign is supported with employee-provided regional inputs.
# Corporate-like sub-sovereign issuers are redirected inside uop_sub_sovereign.
UNSUPPORTED_ASSET_CLASSES: Dict[str, str] = {}

INCOMPLETE = "incomplete"
UNSUPPORTED = "unsupported"
COMPLETE = "complete"
ZERO_UNALLOCATED = "zero_unallocated"


class UopCalcError(Exception):
    def __init__(self, status_code: int, detail: Any):
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail


def _num(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise UopCalcError(422, f"Expected a number, got {value!r}") from None
    if number != number or number in (float("inf"), float("-inf")):
        raise UopCalcError(422, "Non-finite number is not allowed")
    return number


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _pick(payload: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return default


def _add(left: Optional[float], right: Optional[float]) -> Optional[float]:
    if left is None:
        return right
    if right is None:
        return left
    return left + right


def _close(actual: float, expected: float) -> bool:
    scale = max(abs(actual), abs(expected), 1.0)
    return abs(actual - expected) <= max(SCOPE_ABS_TOL, SCOPE_REL_TOL * scale)


def _status_for(value: Optional[float], *, estimated: bool = False, unallocated: bool = False) -> str:
    if unallocated:
        return "unallocated"
    if value is None:
        return "missing"
    if estimated:
        return "estimated"
    if value == 0:
        return "zero"
    return "reported"


def investor_attribution(
    *,
    outstanding: float,
    investment_type: str,
    total_debt: Optional[float],
    total_equity: Optional[float],
    total_assets_fallback: Optional[float] = None,
) -> Dict[str, Any]:
    """
    PCAF §5.7 Attribution of emissions + footnotes 163–166.

    Denominator is total equity + debt of the UoP structure.
    Negative equity is set to 0 (all residual emissions to debt; equity AF = 0).
    If equity or debt cannot be obtained, total assets may be used.
    """
    notes: List[str] = []
    debt = 0.0 if total_debt is None else total_debt
    equity_raw = total_equity
    equity = 0.0 if equity_raw is None else equity_raw
    if equity < 0:
        notes.append(
            "PCAF footnote 164: negative total equity is set to 0, so equity "
            "investments receive no emissions and remaining emissions go to debt."
        )
        equity = 0.0

    denom = equity + debt
    denom_kind = "total_equity_plus_debt"
    if denom <= 0:
        if total_assets_fallback is not None and total_assets_fallback > 0:
            denom = total_assets_fallback
            denom_kind = "total_assets_fallback"
            notes.append(
                "PCAF footnote 166: total equity + debt was not usable; "
                "fell back to total balance-sheet / total assets."
            )
        else:
            raise UopCalcError(
                422,
                {
                    "code": "invalid_denominator",
                    "message": (
                        "UoP investor attribution requires total equity + debt "
                        "greater than zero after applying footnote 164, or a "
                        "total-assets fallback (footnote 166)."
                    ),
                },
            )

    if outstanding < 0:
        raise UopCalcError(422, "Outstanding investment cannot be negative.")

    factor = 0.0
    if investment_type == "equity" and equity_raw is not None and equity_raw < 0:
        factor = 0.0
        notes.append("Equity attribution factor is 0 because structure equity is negative.")
    else:
        factor = outstanding / denom

    return {
        "outstanding_amount": outstanding,
        "investment_type": investment_type,
        "total_structure_debt": debt,
        "total_structure_equity_raw": equity_raw,
        "total_structure_equity_used": equity,
        "denominator": denom,
        "denominator_kind": denom_kind,
        "attribution_factor": factor,
        "equation": "Outstanding_investor / (Total equity + debt of UoP structure)",
        "pcaf_ref": PCAF_UOP_ATTRIBUTION,
        "notes": notes,
    }


def allocation_percentage(
    *,
    classification: str,
    allocation_status: str,
    allocated_proceeds: Optional[float],
    unallocated_proceeds: Optional[float],
    asset_allocated_sum: float,
    structure_denom: float,
) -> Dict[str, Any]:
    """PCAF §5.7 Outstanding amount / allocation percentage, including footnote 170."""
    if classification == "integrated":
        return {
            "allocation_percent": 1.0,
            "assumed_fully_allocated": False,
            "equation": "Integrated UoP: allocation percentage shall be 100%",
            "pcaf_ref": PCAF_UOP_EQUATIONS,
        }
    if allocation_status == "none_yet":
        return {
            "allocation_percent": 0.0,
            "assumed_fully_allocated": False,
            "equation": "Separate UoP at issuance / none allocated: 0%",
            "pcaf_ref": PCAF_UOP_EQUATIONS,
        }
    if allocation_status == "unknown":
        return {
            "allocation_percent": 1.0,
            "assumed_fully_allocated": True,
            "equation": (
                "Separate UoP unknown allocation may be assumed 100%, but "
                "unallocated amounts shall then also be estimated (PCAF §5.7)."
            ),
            "pcaf_ref": PCAF_UOP_EQUATIONS,
        }
    if structure_denom > 0 and asset_allocated_sum:
        pct = asset_allocated_sum / structure_denom
        return {
            "allocation_percent": pct,
            "assumed_fully_allocated": False,
            "equation": "sum(outstanding in underlying assets) / (total equity + debt)",
            "pcaf_ref": "PCAF Part A 2025, §5.7 footnote 170",
        }
    if allocated_proceeds is not None and structure_denom > 0:
        return {
            "allocation_percent": allocated_proceeds / structure_denom,
            "assumed_fully_allocated": False,
            "equation": "allocated proceeds / (total equity + debt)",
            "pcaf_ref": PCAF_UOP_EQUATIONS,
        }
    if allocated_proceeds is not None and unallocated_proceeds is not None:
        total = allocated_proceeds + unallocated_proceeds
        if total > 0:
            return {
                "allocation_percent": allocated_proceeds / total,
                "assumed_fully_allocated": False,
                "equation": "allocated proceeds / (allocated + unallocated proceeds)",
                "pcaf_ref": PCAF_UOP_EQUATIONS,
            }
    return {
        "allocation_percent": 1.0,
        "assumed_fully_allocated": False,
        "equation": "No allocation split available; not assumed.",
        "pcaf_ref": PCAF_UOP_EQUATIONS,
    }


def _asset_class_key(asset: Dict[str, Any]) -> str:
    return _text(_pick(asset, "assetClass", "asset_class"))


def _calculate_one_asset(
    asset: Dict[str, Any],
    *,
    db: Any = None,
    organization_id: Any = None,
    reporting_year: Optional[str] = None,
    parent_structure_id: Optional[str] = None,
    visited_nested: Optional[set] = None,
) -> Dict[str, Any]:
    asset_id = _text(_pick(asset, "underlyingAssetId", "underlying_asset_id"))
    name = _text(_pick(asset, "name")) or asset_id or "Underlying asset"
    asset_class = _asset_class_key(asset)
    allocated = _num(_pick(asset, "allocatedOutstanding", "allocated_outstanding"))
    result: Dict[str, Any] = {
        "underlying_asset_id": asset_id,
        "name": name,
        "asset_class": asset_class,
        "allocated_outstanding": allocated,
        "status": COMPLETE,
    }
    if not asset_id:
        raise UopCalcError(422, "Each underlying asset requires underlyingAssetId.")
    if allocated is None or allocated < 0:
        raise UopCalcError(422, f"{name}: allocated outstanding is required and cannot be negative.")
    estimation = _pick(asset, "estimation", default={}) or {}
    if not isinstance(estimation, dict):
        estimation = {}
    if asset_class in UNSUPPORTED_ASSET_CLASSES:
        result.update(
            {
                "status": UNSUPPORTED,
                "message": UNSUPPORTED_ASSET_CLASSES[asset_class],
                "structure_financed_emissions": None,
            }
        )
        return result
    if asset_class not in ASSET_CLASS_DENOMINATOR:
        result.update(
            {
                "status": UNSUPPORTED,
                "message": (
                    f"No verified PCAF attribution formula is configured for "
                    f"asset class '{asset_class or 'blank'}'."
                ),
                "structure_financed_emissions": None,
            }
        )
        return result

    denom_kind, denom_label, denom_ref = ASSET_CLASS_DENOMINATOR[asset_class]
    try:
        if asset_class == "sovereign-debt":
            return calculate_uop_sovereign_asset(
                result,
                asset=asset,
                estimation=estimation,
                allocated=float(allocated or 0.0),
                name=name,
                db=db,
            )
        if asset_class == "sub-sovereign-debt":
            return calculate_uop_sub_sovereign_asset(
                result,
                asset=asset,
                estimation=estimation,
                allocated=float(allocated or 0.0),
                name=name,
            )
        if asset_class == "use-of-proceeds":
            parent_identity = (
                _text(_pick(asset, "parentStructureId", "parent_structure_id"))
                or _text(parent_structure_id)
                or name
            )

            def _child_calc(child_asset, **kwargs):
                return _calculate_one_asset(
                    child_asset,
                    parent_structure_id=parent_identity,
                    visited_nested=kwargs.pop("visited_nested", visited_nested),
                    **kwargs,
                )

            return calculate_nested_uop_asset(
                result,
                asset=asset,
                estimation=estimation,
                allocated=float(allocated or 0.0),
                name=name,
                parent_identity=parent_identity,
                visited=visited_nested,
                calculate_child_asset=_child_calc,
                db=db,
                organization_id=organization_id,
                reporting_year=reporting_year,
            )
        return calculate_underlying_asset(
            asset,
            denom_kind=denom_kind,
            denom_label=denom_label,
            denom_ref=denom_ref,
            db=db,
            organization_id=organization_id,
            reporting_year=reporting_year,
        )
    except UnderlyingInputError as exc:
        raise UopCalcError(exc.status_code, exc.detail) from exc


def _scale_asset(asset: Dict[str, Any], investor_af: float) -> Dict[str, Any]:
    out = dict(asset)
    if asset.get("status") != COMPLETE or asset.get("structure_financed_emissions") is None:
        out["investor_financed_emissions"] = None
        return out
    out["investor_attribution_factor"] = investor_af
    out["combined_attribution_factor"] = (
        investor_af * asset["asset_attribution_factor"]
        if asset.get("asset_attribution_factor") is not None
        else investor_af
    )
    out["investor_scope1_tco2e"] = (
        None if asset.get("structure_scope1_tco2e") is None else investor_af * asset["structure_scope1_tco2e"]
    )
    out["investor_scope2_tco2e"] = (
        None if asset.get("structure_scope2_tco2e") is None else investor_af * asset["structure_scope2_tco2e"]
    )
    out["investor_scope3_tco2e"] = (
        None if asset.get("structure_scope3_tco2e") is None else investor_af * asset["structure_scope3_tco2e"]
    )
    out["investor_unallocated_tco2e"] = (
        None
        if asset.get("structure_unallocated_tco2e") is None
        else investor_af * asset["structure_unallocated_tco2e"]
    )
    out["investor_financed_emissions"] = investor_af * asset["structure_financed_emissions"]
    return out


def _weighted_dq(assets: List[Dict[str, Any]]) -> Optional[float]:
    weights = []
    scores = []
    for asset in assets:
        if asset.get("status") != COMPLETE or asset.get("data_quality_score") is None:
            continue
        outstanding = asset.get("allocated_outstanding")
        if outstanding is None or outstanding < 0:
            continue
        weights.append(float(outstanding))
        scores.append(float(asset["data_quality_score"]))
    if not weights or sum(weights) == 0:
        return None
    return sum(w * s for w, s in zip(weights, scores)) / sum(weights)


def _breakdown_from_parts(
    *,
    s1: Optional[float],
    s2: Optional[float],
    s3: Optional[float],
    unallocated: Optional[float],
    total: float,
    estimated: bool,
    method: str,
    notes: List[str],
) -> Dict[str, Any]:
    present = [value for value in (s1, s2, s3, unallocated) if value is not None]
    reconstructed = sum(present) if present else 0.0
    if present and not _close(reconstructed, total):
        raise UopCalcError(
            422,
            "Financed scope breakdown does not reconcile with the UoP total.",
        )
    if not present and abs(total) > SCOPE_ABS_TOL:
        unallocated = total
        reconstructed = total
    scope_status = {
        "scope1": _status_for(s1, estimated=estimated and s1 is not None, unallocated=s1 is None and unallocated is not None and s2 is None and s3 is None),
        "scope2": _status_for(s2, estimated=estimated and s2 is not None, unallocated=s2 is None and unallocated is not None and s1 is None and s3 is None),
        "scope3": _status_for(s3, estimated=estimated and s3 is not None, unallocated=s3 is None and unallocated is not None and s1 is None and s2 is None),
    }
    if s1 is None and s2 is None and s3 is None and unallocated is not None:
        scope_status = {"scope1": "unallocated", "scope2": "unallocated", "scope3": "unallocated"}
        completeness = "total_only"
        included: Tuple[str, ...] = ()
    else:
        included = tuple(
            name
            for name, value in (("scope1", s1), ("scope2", s2), ("scope3", s3))
            if value is not None
        )
        missing = [name for name, value in (("scope1", s1), ("scope2", s2), ("scope3", s3)) if value is None]
        completeness = "complete" if not missing else "partial"
    missing = [name for name, status in scope_status.items() if status == "missing"]
    return {
        "financed_scope1_tco2e": s1,
        "financed_scope2_tco2e": s2,
        "financed_scope3_tco2e": s3,
        "financed_unallocated_tco2e": unallocated,
        "financed_emissions_tco2e": total,
        "included_scopes": list(included),
        "missing_scopes": missing,
        "excluded_scopes": [],
        "not_applicable_scopes": [],
        "scope_status": scope_status,
        "scope_completeness": completeness,
        "calculation_method": method,
        "methodology_version": METHODOLOGY_VERSION,
        "emissions_unit": EMISSIONS_UNIT,
        "estimated": estimated,
        "notes": notes,
    }


def _issuer_reported(draft: Dict[str, Any], investor: Dict[str, Any]) -> Dict[str, Any]:
    reported = _num(
        _pick(
            draft,
            "issuerReportedFinancedEmissions",
            "issuer_reported_financed_emissions",
        )
    )
    if reported is None:
        return {
            "status": INCOMPLETE,
            "code": "missing_issuer_reported_emissions",
            "message": (
                "Issuer-reported UoP financed emissions (allocation and impact "
                "report) are required. Do not use the issuer’s corporate inventory."
            ),
        }
    year = _text(_pick(draft, "issuerReportYear", "issuer_report_year"))
    source = _text(_pick(draft, "issuerReportSource", "issuer_report_source"))
    reporting_year = _text(_pick(draft, "reportingYear", "reporting_year"))
    if not year or not source:
        return {
            "status": INCOMPLETE,
            "code": "missing_issuer_report_provenance",
            "message": (
                "Issuer-reported UoP emissions need the report year and source. "
                "Corporate GHG inventories are not a valid substitute."
            ),
        }
    notes = [
        "PCAF §5.7 Reported emissions by issuer: FE = Outstanding / (equity + debt) × issuer-reported UoP financed emissions.",
        "This is the structure’s financed emissions from an allocation and impact report, not issuer corporate Scope 1/2/3.",
    ]
    if reporting_year and year != reporting_year:
        notes.append(
            f"Issuer report year ({year}) differs from the structure reporting year ({reporting_year})."
        )
    verification = _text(_pick(draft, "issuerReportVerification", "issuer_report_verification"))
    fe = investor["attribution_factor"] * reported
    dq = 1.0 if verification == "verified" else 2.0
    breakdown = _breakdown_from_parts(
        s1=None,
        s2=None,
        s3=None,
        unallocated=fe,
        total=fe,
        estimated=False,
        method="uop-issuer-reported",
        notes=notes,
    )
    return {
        "status": COMPLETE,
        "formula_id": "uop-issuer-reported",
        "formula_name": "PCAF §5.7 issuer-reported UoP structure emissions",
        "financed_emissions": fe,
        "data_quality_score": dq,
        "assets": [],
        "allocated_financed_emissions": fe,
        "unallocated_financed_emissions": 0.0,
        "scope_breakdown": breakdown,
        "notes": notes,
        "issuer_report": {
            "financed_emissions_tco2e": reported,
            "report_year": year,
            "source": source,
            "verification": verification,
            "attribution_basis": "Outstanding / (total equity + debt of the UoP structure)",
        },
    }


def _score5_unallocated(
    *,
    outstanding_relevant: float,
    assets: List[Dict[str, Any]],
    evidence: str,
) -> Dict[str, Any]:
    if not evidence:
        return {
            "status": INCOMPLETE,
            "code": "missing_unallocated_evidence",
            "message": (
                "PCAF allows asset-level / score-5 estimates for unallocated "
                "amounts only with evidence of expected allocation."
            ),
        }
    if outstanding_relevant < 0:
        raise UopCalcError(422, "Unallocated outstanding cannot be negative.")
    try:
        weighted, used = score5_sector_intensity(assets)
    except UnderlyingInputError as exc:
        raise UopCalcError(exc.status_code, exc.detail) from exc
    if used == 0 or weighted is None:
        return {
            "status": INCOMPLETE,
            "code": "missing_unallocated_factor",
            "message": (
                "Unallocated score-5 estimation needs published sector intensities "
                "on expected listed-equity, bond, business-loan, unlisted-equity, "
                "or project-finance assets (PCAF §5.7 score 5). Factors are not "
                "invented, and building/vehicle assets cannot supply this factor."
            ),
        }
    fe = outstanding_relevant * weighted
    return {
        "status": COMPLETE,
        "financed_emissions": fe,
        "data_quality_score": 5.0,
        "equation": "Outstanding_relevant × Σ (sector allocation % × sector EF)",
        "pcaf_ref": PCAF_UOP_DATA,
        "estimated": True,
    }


def _merge_issuer_level(
    draft: Dict[str, Any], explicit: Optional[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    merged: Dict[str, Any] = {}
    mapping = {
        "companyType": ("issuerCompanyType", "issuer_company_type", "companyType"),
        "evic": ("issuerEvic", "issuer_evic", "evic"),
        "totalEquityPlusDebt": (
            "issuerEquityPlusDebt",
            "issuer_equity_plus_debt",
            "totalEquityPlusDebt",
        ),
        "issuerEmissions": ("issuerEmissions", "issuer_emissions"),
        "scope1Emissions": ("issuerScope1Emissions", "issuer_scope1_emissions", "scope1Emissions"),
        "scope2Emissions": ("issuerScope2Emissions", "issuer_scope2_emissions", "scope2Emissions"),
        "scope3Emissions": ("issuerScope3Emissions", "issuer_scope3_emissions", "scope3Emissions"),
        "verificationStatus": (
            "issuerVerificationStatus",
            "issuer_verification_status",
            "verificationStatus",
        ),
    }
    for dest, aliases in mapping.items():
        value = _pick(draft, *aliases)
        if value is not None and value != "":
            merged[dest] = value
    if explicit:
        for key, value in explicit.items():
            if value is not None and value != "":
                merged[key] = value
    return merged or None


def _issuer_level_unallocated(issuer_level: Optional[Dict[str, Any]], outstanding_relevant: float) -> Dict[str, Any]:
    try:
        return calculate_issuer_level(issuer_level or {}, outstanding_relevant)
    except UnderlyingInputError as exc:
        raise UopCalcError(exc.status_code, exc.detail) from exc


def calculate_uop_draft(
    draft: Dict[str, Any],
    *,
    issuer_level: Optional[Dict[str, Any]] = None,
    db: Any = None,
    organization_id: Any = None,
) -> Dict[str, Any]:
    outcome = resolve_uop_accounting(_pick(draft, "eligibility", default={}) or {})
    if not uop_qualifies(outcome):
        raise UopCalcError(
            422,
            {
                "code": "not_uop_eligible",
                "message": (
                    "Figure 5.7-2 does not classify this financing as Use of Proceeds. "
                    "Do not calculate it with the §5.7 engine."
                ),
                "outcome": outcome,
            },
        )
    classification = outcome["classification"]
    investment_type = _text(_pick(draft, "investmentType", "investment_type"))
    if investment_type not in ("debt", "equity"):
        raise UopCalcError(422, "investmentType must be debt or equity.")
    if classification == "integrated" and investment_type == "equity":
        raise UopCalcError(
            422,
            "PCAF footnote 174: investors can only provide debt to integrated UoP structures.",
        )
    outstanding = _num(_pick(draft, "outstandingInvestment", "outstanding_amount"))
    if outstanding is None:
        raise UopCalcError(422, "outstandingInvestment is required.")
    total_debt = _num(_pick(draft, "totalStructureDebt", "total_structure_debt"))
    total_equity = _num(_pick(draft, "totalStructureEquity", "total_structure_equity"))
    total_assets = _num(_pick(draft, "totalStructureAssets", "total_structure_assets", "totalAssets"))
    investor = investor_attribution(
        outstanding=outstanding,
        investment_type=investment_type,
        total_debt=total_debt,
        total_equity=total_equity,
        total_assets_fallback=total_assets,
    )
    path = _text(_pick(draft, "emissionsPath", "emissions_path"))
    notes = list(investor["notes"])
    warnings: List[str] = []
    issuer_level = _merge_issuer_level(draft, issuer_level)

    if path == "issuer_reported":
        computed = _issuer_reported(draft, investor)
        if computed.get("status") != COMPLETE:
            return _wrap(classification, path, investor, computed, outcome)
        return _wrap(classification, path, investor, computed, outcome)

    allocation_status = _text(_pick(draft, "allocationStatus", "allocation_status"))
    allocated_proceeds = _num(_pick(draft, "allocatedProceeds", "allocated_proceeds"))
    unallocated_proceeds = _num(_pick(draft, "unallocatedProceeds", "unallocated_proceeds"))
    assets_in = _pick(draft, "assets", default=[]) or []
    if not isinstance(assets_in, list):
        raise UopCalcError(422, "draft.assets must be an array")

    issuer_reason = _text(_pick(draft, "issuerLevelReason", "issuer_level_reason"))
    if (
        classification == "integrated"
        and path == "estimation"
        and issuer_reason in ISSUER_LEVEL_REASONS
        and not assets_in
    ):
        notes.append(
            "PCAF §5.7 footnote 168: look-through is theoretically impossible, "
            "not feasible, or not material, so issuer-level data is applied to "
            "allocated and unallocated amounts together. This is Figure 5-1 "
            "Step 3a, not a UoP look-through."
        )
        try:
            issuer_calc = calculate_issuer_level(issuer_level or {}, outstanding)
        except UnderlyingInputError as exc:
            raise UopCalcError(exc.status_code, exc.detail) from exc
        if issuer_calc.get("status") != COMPLETE:
            return _wrap(classification, path, investor, issuer_calc, outcome)
        total = float(issuer_calc["financed_emissions"])
        s1 = issuer_calc.get("scope1_tco2e")
        s2 = issuer_calc.get("scope2_tco2e")
        s3 = issuer_calc.get("scope3_tco2e")
        unallocated = issuer_calc.get("unallocated_tco2e")
        if s1 is None and s2 is None and s3 is None and unallocated is None:
            unallocated = total
        breakdown = _breakdown_from_parts(
            s1=s1,
            s2=s2,
            s3=s3,
            unallocated=unallocated,
            total=total,
            estimated=False,
            method="uop-integrated-issuer-level",
            notes=notes + [issuer_calc.get("pcaf_ref") or ""],
        )
        computed = {
            "status": COMPLETE,
            "formula_id": "uop-integrated-issuer-level",
            "formula_name": "PCAF §5.7 integrated issuer-level (footnote 168)",
            "financed_emissions": total,
            "data_quality_score": issuer_calc.get("data_quality_score"),
            "assets": [],
            "allocated_financed_emissions": total,
            "unallocated_financed_emissions": 0.0,
            "scope_breakdown": breakdown,
            "notes": notes + [issuer_calc.get("pcaf_ref") or ""],
        }
        return _wrap(classification, path, investor, computed, outcome, warnings)

    if classification == "separate" and allocation_status == "none_yet":
        notes.append(
            "PCAF §5.7 Separate UoP: financed emissions are only calculated once "
            "funds are allocated. Unallocated cash does not generate emissions."
        )
        breakdown = _breakdown_from_parts(
            s1=0.0,
            s2=0.0,
            s3=0.0,
            unallocated=0.0,
            total=0.0,
            estimated=False,
            method="uop-separate-zero-unallocated",
            notes=notes,
        )
        computed = {
            "status": COMPLETE,
            "formula_id": "uop-separate-zero-unallocated",
            "formula_name": "PCAF §5.7 separate UoP — no allocation yet (valid zero)",
            "financed_emissions": 0.0,
            "data_quality_score": None,
            "assets": [],
            "allocated_financed_emissions": 0.0,
            "unallocated_financed_emissions": 0.0,
            "scope_breakdown": breakdown,
            "notes": notes + ["Data quality score cannot be defined with no allocated assets (PCAF §5.7 Data required)."],
        }
        return _wrap(classification, path, investor, computed, outcome)

    reporting_year = _text(_pick(draft, "reportingYear", "reporting_year")) or None
    parent_structure_id = _text(
        _pick(draft, "financingInstanceId", "financing_instance_id", "structureId", "structure_id")
    ) or None
    asset_rows = [
        _calculate_one_asset(
            item,
            db=db,
            organization_id=organization_id,
            reporting_year=reporting_year,
            parent_structure_id=parent_structure_id,
            visited_nested={parent_structure_id} if parent_structure_id else set(),
        )
        for item in assets_in
    ]
    blocked = [row for row in asset_rows if row.get("status") == UNSUPPORTED]
    incomplete = [row for row in asset_rows if row.get("status") == INCOMPLETE]
    if blocked:
        return _wrap(
            classification,
            path,
            investor,
            {
                "status": UNSUPPORTED,
                "code": "unsupported_underlying_asset",
                "message": blocked[0]["message"],
                "assets": asset_rows,
            },
            outcome,
        )
    if incomplete:
        return _wrap(
            classification,
            path,
            investor,
            {
                "status": INCOMPLETE,
                "code": incomplete[0].get("code", "incomplete_underlying_asset"),
                "message": incomplete[0].get("message"),
                "assets": asset_rows,
            },
            outcome,
        )

    scaled = [_scale_asset(row, investor["attribution_factor"]) for row in asset_rows]
    s1 = s2 = s3 = unallocated = None
    allocated_fe = 0.0
    estimated_any = False
    for row in scaled:
        allocated_fe += row.get("investor_financed_emissions") or 0.0
        s1 = _add(s1, row.get("investor_scope1_tco2e"))
        s2 = _add(s2, row.get("investor_scope2_tco2e"))
        s3 = _add(s3, row.get("investor_scope3_tco2e"))
        unallocated = _add(unallocated, row.get("investor_unallocated_tco2e"))
        estimated_any = estimated_any or bool(row.get("estimated"))

    asset_sum = sum(float(row.get("allocated_outstanding") or 0) for row in scaled)
    alloc = allocation_percentage(
        classification=classification,
        allocation_status=allocation_status,
        allocated_proceeds=allocated_proceeds,
        unallocated_proceeds=unallocated_proceeds,
        asset_allocated_sum=asset_sum,
        structure_denom=investor["denominator"],
    )

    unallocated_fe = 0.0
    extra_notes = []
    if classification == "separate":
        extra_notes.append(
            "PCAF §5.7 Separate: FE = (Outstanding / (equity + debt)) × Σ (AF_asset × asset emissions). "
            "Unallocated cash is not treated as emissions unless unknown allocation is assumed 100%."
        )
        if alloc.get("assumed_fully_allocated"):
            remaining_ratio = 0.0
            if investor["denominator"] > 0:
                remaining_ratio = max(0.0, 1.0 - (asset_sum / investor["denominator"]))
            relevant = outstanding * remaining_ratio
            extra_notes.append(
                "Unknown allocation is assumed 100% (PCAF §5.7). Unallocated "
                "amounts are estimated so financed emissions stay consistent "
                "with outstanding amount."
            )
            if remaining_ratio > 0:
                evidence = _text(
                    _pick(draft, "expectedAllocationEvidence", "expected_allocation_evidence")
                ) or "PCAF §5.7 unknown allocation assumed 100%"
                estimate = _score5_unallocated(
                    outstanding_relevant=relevant,
                    assets=assets_in,
                    evidence=evidence,
                )
                if estimate.get("status") != COMPLETE:
                    return _wrap(classification, path, investor, {**estimate, "assets": scaled}, outcome)
                unallocated_fe = float(estimate["financed_emissions"])
                unallocated = _add(unallocated, unallocated_fe)
                extra_notes.append(estimate["equation"])
                estimated_any = True
            else:
                extra_notes.append(
                    "Listed assets already cover the structure denominator; "
                    "no residual unallocated estimate is added."
                )
    else:
        extra_notes.append(
            "PCAF §5.7 Integrated: FE = FE_allocated + FE_unallocated. "
            "Unallocated amounts are in scope and are not treated as separate-structure cash."
        )
        unallocated_amt = unallocated_proceeds or 0.0
        if unallocated_amt > 0:
            uses_asset = _text(
                _pick(
                    draft,
                    "unallocatedUsesAssetLevelEstimate",
                    "unallocated_uses_asset_level_estimate",
                )
            )
            structure_size = (allocated_proceeds or 0) + unallocated_amt
            if structure_size <= 0:
                structure_size = investor["denominator"]
            investor_unallocated = outstanding * (unallocated_amt / structure_size)
            if uses_asset == "yes":
                evidence = _text(
                    _pick(draft, "expectedAllocationEvidence", "expected_allocation_evidence")
                )
                estimate = _score5_unallocated(
                    outstanding_relevant=investor_unallocated,
                    assets=assets_in,
                    evidence=evidence,
                )
                if estimate.get("status") != COMPLETE:
                    return _wrap(classification, path, investor, {**estimate, "assets": scaled}, outcome)
                unallocated_fe = float(estimate["financed_emissions"])
                unallocated = _add(unallocated, unallocated_fe)
                estimated_any = True
                extra_notes.append(
                    "Unallocated amounts estimated from expected asset-level sector factors (PCAF §5.7)."
                )
            else:
                issuer_calc = _issuer_level_unallocated(issuer_level, investor_unallocated)
                if issuer_calc.get("status") != COMPLETE:
                    return _wrap(
                        classification, path, investor, {**issuer_calc, "assets": scaled}, outcome
                    )
                unallocated_fe = float(issuer_calc["financed_emissions"])
                if issuer_calc.get("scope1_tco2e") is None and issuer_calc.get("scope2_tco2e") is None:
                    unallocated = _add(unallocated, unallocated_fe)
                else:
                    s1 = _add(s1, issuer_calc.get("scope1_tco2e"))
                    s2 = _add(s2, issuer_calc.get("scope2_tco2e"))
                    s3 = _add(s3, issuer_calc.get("scope3_tco2e"))
                extra_notes.append(issuer_calc.get("pcaf_ref"))

    total = allocated_fe + unallocated_fe
    if s1 is None and s2 is None and s3 is None and unallocated is None:
        unallocated = total
    breakdown = _breakdown_from_parts(
        s1=s1,
        s2=s2,
        s3=s3,
        unallocated=unallocated,
        total=total,
        estimated=estimated_any,
        method="uop-integrated-lookthrough" if classification == "integrated" else "uop-separate-lookthrough",
        notes=notes + extra_notes,
    )
    dq = _weighted_dq(scaled)
    if dq is None:
        extra_notes.append("Data quality score cannot be defined with no allocated assets (PCAF §5.7 Data required).")
    formula_id = (
        "uop-integrated-lookthrough" if classification == "integrated" else "uop-separate-lookthrough"
    )
    computed = {
        "status": COMPLETE,
        "formula_id": formula_id,
        "formula_name": (
            "PCAF §5.7 integrated look-through"
            if classification == "integrated"
            else "PCAF §5.7 separate look-through"
        ),
        "financed_emissions": total,
        "data_quality_score": dq,
        "assets": scaled,
        "allocated_financed_emissions": allocated_fe,
        "unallocated_financed_emissions": unallocated_fe,
        "allocation": alloc,
        "scope_breakdown": breakdown,
        "notes": notes + extra_notes,
    }
    return _wrap(classification, path, investor, computed, outcome, warnings)


def _wrap(
    classification: str,
    path: str,
    investor: Dict[str, Any],
    computed: Dict[str, Any],
    outcome: Dict[str, Any],
    warnings: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return {
        "status": computed.get("status", COMPLETE),
        "code": computed.get("code"),
        "message": computed.get("message"),
        "classification": classification,
        "emissions_path": path,
        "formula_id": computed.get("formula_id"),
        "formula_name": computed.get("formula_name"),
        "methodology_version": METHODOLOGY_VERSION,
        "emissions_unit": EMISSIONS_UNIT,
        "pcaf_ref": outcome.get("pcafRef") or PCAF_UOP_EQUATIONS,
        "eligibility": outcome,
        "investor_attribution": investor,
        "financed_emissions": computed.get("financed_emissions"),
        "allocated_financed_emissions": computed.get("allocated_financed_emissions"),
        "unallocated_financed_emissions": computed.get("unallocated_financed_emissions"),
        "data_quality_score": computed.get("data_quality_score"),
        "assets": computed.get("assets") or [],
        "allocation": computed.get("allocation"),
        "scope_breakdown": computed.get("scope_breakdown"),
        "issuer_report": computed.get("issuer_report"),
        "notes": computed.get("notes") or [],
        "warnings": warnings or [],
        "is_reportable": False,
        "include_in_portfolio": False,
        "double_count_guard": (
            "Underlying asset rows stay non-reportable. This result is not added "
            "to app.financed_emissions or portfolio totals."
        ),
    }
