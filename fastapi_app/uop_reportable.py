"""
Phase 5D — one reportable UoP parent in app.financed_emissions.

Underlying UoP draft/calculation tables stay non-reportable (0016 CHECK).
Dashboards, Category 15, and exports keep reading app.financed_emissions
through the existing selector. This module never invents PCAF formulas and
never silently subtracts overlapping general-purpose totals.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from .financing_instance import (
    extract_financing_instance_id,
    extract_reporting_year,
    find_row_by_financing_instance,
    is_aggregate_formula,
    normalize_financing_instance_id,
    normalize_reporting_year,
    year_aware_identity_available,
)
from .ghg_models import FinancedEmission
from .uop_drafts import is_uop_formula_id
from .uop_eligibility import uop_qualifies
from .uop_models import UOP_METHODOLOGY_VERSION

# Release flag. Stay false until UAT passes and an explicit ops enable.
UOP_REPORTABLE_SAVE_ENABLED = False

PCAF_OVERLAP_REF = "PCAF 2025 Part A §5.7 pp. 107–108"
PCAF_OVERLAP_GUIDANCE = (
    "PCAF 2025 Part A §5.7 (pages 107–108): where Use of Proceeds financing "
    "and general-purpose financing exist for the same counterparty in the same "
    "reporting year, look-through UoP emissions must not also be counted in the "
    "remaining general-purpose attribution unless an evidenced split of "
    "outstanding is available. This platform does not silently subtract or "
    "redistribute either total."
)

REPORTING_ROLE_PARENT = "uop_parent"
REPORTING_ROLE_UNDERLYING = "uop_underlying"
EXCLUDED_STATUSES = frozenset(
    {"failed", "draft", "review_required", "void", "superseded", "incomplete"}
)
IMPLEMENTED_FORMULAS = frozenset(
    {
        "uop-separate-lookthrough",
        "uop-integrated-lookthrough",
        "uop-issuer-reported",
    }
)


def reportable_save_enabled() -> bool:
    env = (os.getenv("UOP_REPORTABLE_SAVE_ENABLED") or "").strip().lower()
    if env in ("1", "true", "yes"):
        return True
    if env in ("0", "false", "no"):
        return False
    return bool(UOP_REPORTABLE_SAVE_ENABLED)


def _canon_num(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return str(value)
    return format(number.normalize(), "f")


def calculation_fingerprint(payload: Dict[str, Any]) -> str:
    """Stable hash of the authoritative calculation used to detect stale Save."""
    assets = []
    for asset in payload.get("assets") or []:
        if not isinstance(asset, dict):
            continue
        assets.append(
            {
                "id": asset.get("underlying_asset_id"),
                "fe": _canon_num(asset.get("investor_financed_emissions")),
                "dq": _canon_num(asset.get("data_quality_score")),
                "s1": _canon_num(asset.get("investor_scope1_tco2e")),
                "s2": _canon_num(asset.get("investor_scope2_tco2e")),
                "s3": _canon_num(asset.get("investor_scope3_tco2e")),
            }
        )
    assets.sort(key=lambda row: str(row.get("id") or ""))
    breakdown = payload.get("scope_breakdown") or {}
    attribution = payload.get("investor_attribution") or {}
    canonical = {
        "formula_id": payload.get("formula_id"),
        "financed_emissions": _canon_num(payload.get("financed_emissions")),
        "allocated": _canon_num(payload.get("allocated_financed_emissions")),
        "unallocated": _canon_num(payload.get("unallocated_financed_emissions")),
        "dq": _canon_num(payload.get("data_quality_score")),
        "af": _canon_num(attribution.get("attribution_factor")),
        "s1": _canon_num(breakdown.get("financed_scope1_tco2e")),
        "s2": _canon_num(breakdown.get("financed_scope2_tco2e")),
        "s3": _canon_num(breakdown.get("financed_scope3_tco2e")),
        "unallocated_scope": _canon_num(breakdown.get("financed_unallocated_tco2e")),
        "completeness": breakdown.get("scope_completeness"),
        "methodology_version": payload.get("methodology_version"),
        "reporting_year": payload.get("reporting_year"),
        "assets": assets,
    }
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def attach_fingerprint(
    result: Dict[str, Any],
    *,
    reporting_year: Optional[str] = None,
    structure_updated_at: Any = None,
    investment_updated_at: Any = None,
) -> Dict[str, Any]:
    if reporting_year:
        result["reporting_year"] = reporting_year
    if structure_updated_at is not None:
        result["structure_updated_at"] = (
            structure_updated_at.isoformat()
            if hasattr(structure_updated_at, "isoformat")
            else str(structure_updated_at)
        )
    if investment_updated_at is not None:
        result["investment_updated_at"] = (
            investment_updated_at.isoformat()
            if hasattr(investment_updated_at, "isoformat")
            else str(investment_updated_at)
        )
    result["calculation_fingerprint"] = calculation_fingerprint(result)
    return result


def _raise(code: str, message: str, http_status: int = 409, **extra: Any) -> None:
    raise HTTPException(
        status_code=http_status,
        detail={"code": code, "message": message, **extra},
    )


def assert_reportable_gates(
    result: Dict[str, Any],
    *,
    expected_fingerprint: Optional[str],
    financing_instance_id: Optional[str],
    reporting_year: Optional[str],
) -> None:
    if not reportable_save_enabled():
        _raise(
            "UOP_REPORTABLE_SAVE_DISABLED",
            "Reportable UoP Save is disabled until Phase 5D integration tests pass.",
            http_status=status.HTTP_403_FORBIDDEN,
        )
    if not uop_qualifies(result.get("eligibility")):
        _raise(
            "UOP_NOT_ELIGIBLE",
            "Figure 5.7-2 does not classify this financing as Use of Proceeds.",
            http_status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    if result.get("status") != "complete":
        _raise(
            "UOP_CALCULATION_INCOMPLETE",
            result.get("message")
            or "Incomplete or unsupported UoP calculations cannot become reportable.",
            http_status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            calculation_status=result.get("status"),
            calculation_code=result.get("code"),
        )
    formula_id = (result.get("formula_id") or "").strip()
    if formula_id not in IMPLEMENTED_FORMULAS:
        _raise(
            "UOP_METHOD_UNSUPPORTED",
            "The selected UoP method is not an implemented reportable formula.",
            http_status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            formula_id=formula_id or None,
        )
    if result.get("financed_emissions") is None:
        _raise(
            "UOP_TOTAL_MISSING",
            "A complete financed-emissions total is required before reportable Save.",
            http_status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    attribution = result.get("investor_attribution") or {}
    if attribution.get("attribution_factor") is None:
        _raise(
            "UOP_ATTRIBUTION_MISSING",
            "Investor attribution is required before reportable Save.",
            http_status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    if not normalize_financing_instance_id(financing_instance_id):
        _raise(
            "UOP_INSTANCE_REQUIRED",
            "financing_instance_id is required to save a reportable UoP parent.",
            http_status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    if not normalize_reporting_year(reporting_year):
        _raise(
            "UOP_REPORTING_YEAR_REQUIRED",
            "Reporting year is required so a later year cannot overwrite this instance.",
            http_status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    expected = (expected_fingerprint or "").strip()
    if not expected:
        _raise(
            "UOP_FINGERPRINT_REQUIRED",
            "Save requires the calculation_fingerprint from the last backend Calculate.",
            http_status=status.HTTP_409_CONFLICT,
        )
    actual = result.get("calculation_fingerprint") or calculation_fingerprint(result)
    if expected != actual:
        _raise(
            "UOP_STALE_CALCULATION",
            "The draft changed or the calculation is stale. Recalculate before Save.",
            http_status=status.HTTP_409_CONFLICT,
            expected_fingerprint=expected,
            actual_fingerprint=actual,
        )
    _assert_evidence(result)


def _assert_evidence(result: Dict[str, Any]) -> None:
    path = result.get("emissions_path")
    if path == "issuer_reported":
        report = result.get("issuer_report") or {}
        if report.get("financed_emissions_tco2e") is None or not report.get("source"):
            _raise(
                "UOP_EVIDENCE_MISSING",
                "Issuer-reported UoP Save needs the allocation/impact report total and source.",
                http_status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        return
    assets = [row for row in (result.get("assets") or []) if isinstance(row, dict)]
    complete_assets = [
        row
        for row in assets
        if row.get("status") in (None, "complete")
        and row.get("investor_financed_emissions") is not None
    ]
    if path in ("underlying_assets", "estimation") and not complete_assets:
        if result.get("financed_emissions") == 0:
            return
        _raise(
            "UOP_EVIDENCE_MISSING",
            "Look-through Save needs at least one complete underlying calculation.",
            http_status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )


def _row_year(row: FinancedEmission) -> Optional[str]:
    return extract_reporting_year(row)


def _row_issuer_name(row: FinancedEmission) -> str:
    inputs = row.inputs or {}
    for key in ("issuer_name", "issuerName", "companyName", "company_name", "name"):
        value = str(inputs.get(key) or "").strip().lower()
        if value:
            return value
    return ""


def scan_uop_general_purpose_overlap(
    db: Session,
    *,
    organization_id: uuid.UUID,
    counterparty_id: Optional[uuid.UUID],
    reporting_year: Optional[str],
    financing_instance_id: str,
    issuer_name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Detect UoP vs general-purpose financing to the same issuer/year.

    Does not adjust either total. Sibling UoP holdings in the same fund are
    independent investor attributions and are not overlap.
    """
    year = normalize_reporting_year(reporting_year)
    instance_id = normalize_financing_instance_id(financing_instance_id)
    issuer = str(issuer_name or "").strip().lower()
    overlapping: List[Dict[str, Any]] = []
    rows = (
        db.query(FinancedEmission)
        .filter(
            FinancedEmission.organization_id == organization_id,
            FinancedEmission.calc_kind == "finance",
        )
        .all()
    )
    for row in rows:
        if is_aggregate_formula(row.formula_id) or is_uop_formula_id(row.formula_id):
            continue
        if str(row.status or "completed").strip().lower() in EXCLUDED_STATUSES:
            continue
        other_instance = extract_financing_instance_id(row.inputs)
        if instance_id and other_instance == instance_id:
            continue
        other_year = _row_year(row)
        if year and other_year and other_year != year:
            continue
        same_counterparty = (
            counterparty_id is not None
            and row.counterparty_id is not None
            and row.counterparty_id == counterparty_id
        )
        same_issuer = bool(issuer) and _row_issuer_name(row) == issuer
        if not same_counterparty and not same_issuer:
            continue
        overlapping.append(
            {
                "kind": "uop_and_general_purpose",
                "formula_id": row.formula_id,
                "financing_instance_id": other_instance,
                "counterparty_id": str(row.counterparty_id) if row.counterparty_id else None,
                "reporting_year": other_year,
                "financed_emissions": (
                    None
                    if row.financed_emissions is None
                    else float(row.financed_emissions)
                ),
                "status": row.status,
                "pcaf_ref": PCAF_OVERLAP_REF,
                "guidance": PCAF_OVERLAP_GUIDANCE,
            }
        )
    return overlapping


def assert_no_unresolved_overlap(overlap: List[Dict[str, Any]]) -> None:
    if not overlap:
        return
    _raise(
        "UOP_OVERLAP_REVIEW_REQUIRED",
        PCAF_OVERLAP_GUIDANCE,
        http_status=status.HTTP_409_CONFLICT,
        overlap=overlap,
        redistribution="none",
    )


def assert_reporting_year_not_overwrite(
    db: Session,
    *,
    organization_id: uuid.UUID,
    counterparty_id: Optional[uuid.UUID],
    financing_instance_id: str,
    reporting_year: str,
) -> Optional[FinancedEmission]:
    requested = normalize_reporting_year(reporting_year)
    existing = find_row_by_financing_instance(
        db,
        organization_id=organization_id,
        calc_kind="finance",
        financing_instance_id=financing_instance_id,
        counterparty_id=counterparty_id,
        reporting_year=requested,
        for_update=True,
    )
    if existing is not None:
        return existing
    if year_aware_identity_available(db):
        return None
    other = find_row_by_financing_instance(
        db,
        organization_id=organization_id,
        calc_kind="finance",
        financing_instance_id=financing_instance_id,
        counterparty_id=counterparty_id,
        for_update=False,
    )
    if other is None:
        return None
    existing_year = _row_year(other)
    if existing_year != requested:
        _raise(
            "REPORTING_YEAR_CONFLICT",
            (
                "app.financed_emissions unique identity (migration 0014) is "
                "(organization, counterparty, calc_kind, financing_instance_id) "
                "and does not include reporting year. Saving a different year "
                "would overwrite the existing instance. Apply prepared migration "
                "0017 before storing a second reporting year for the same holding."
            ),
            existing_reporting_year=existing_year,
            requested_reporting_year=requested,
            financing_instance_id=financing_instance_id,
        )
    return other


def parent_inputs(
    result: Dict[str, Any],
    *,
    financing_instance_id: str,
    reporting_year: str,
    structure_id: Optional[str],
    investment_id: Optional[str],
    issuer_name: Optional[str],
    counterparty_id: Optional[uuid.UUID],
) -> Dict[str, Any]:
    attribution = result.get("investor_attribution") or {}
    return {
        "financing_instance_id": financing_instance_id,
        "reporting_year": reporting_year,
        "uop_structure_id": structure_id,
        "uop_investment_id": investment_id,
        "issuer_name": issuer_name,
        "counterparty_id": str(counterparty_id) if counterparty_id else None,
        "methodology_version": result.get("methodology_version") or UOP_METHODOLOGY_VERSION,
        "formula_id": result.get("formula_id"),
        "emissions_path": result.get("emissions_path"),
        "classification": result.get("classification"),
        "attribution_factor": attribution.get("attribution_factor"),
        "outstanding_amount": attribution.get("outstanding_amount"),
        "denominator": attribution.get("denominator"),
        "calculation_fingerprint": result.get("calculation_fingerprint"),
        "reporting_role": REPORTING_ROLE_PARENT,
    }


def parent_results(result: Dict[str, Any], overlap: List[Dict[str, Any]]) -> Dict[str, Any]:
    breakdown = dict(result.get("scope_breakdown") or {})
    payload = {
        "reporting_role": REPORTING_ROLE_PARENT,
        "uop_parent": True,
        "include_underlying_independently": False,
        "methodology_version": result.get("methodology_version") or UOP_METHODOLOGY_VERSION,
        "pcaf_ref": result.get("pcaf_ref"),
        "formula_id": result.get("formula_id"),
        "formula_name": result.get("formula_name"),
        "emissions_path": result.get("emissions_path"),
        "classification": result.get("classification"),
        "eligibility": result.get("eligibility"),
        "investor_attribution": result.get("investor_attribution"),
        "financed_emissions": result.get("financed_emissions"),
        "allocated_financed_emissions": result.get("allocated_financed_emissions"),
        "unallocated_financed_emissions": result.get("unallocated_financed_emissions"),
        "data_quality_score": result.get("data_quality_score"),
        "scope_breakdown": breakdown,
        "scope_completeness": breakdown.get("scope_completeness"),
        "financed_scope1_tco2e": breakdown.get("financed_scope1_tco2e"),
        "financed_scope2_tco2e": breakdown.get("financed_scope2_tco2e"),
        "financed_scope3_tco2e": breakdown.get("financed_scope3_tco2e"),
        "financed_unallocated_tco2e": breakdown.get("financed_unallocated_tco2e"),
        "included_scopes": breakdown.get("included_scopes"),
        "missing_scopes": breakdown.get("missing_scopes"),
        "calculation_method": breakdown.get("calculation_method") or result.get("formula_id"),
        "issuer_report": result.get("issuer_report"),
        "allocation": result.get("allocation"),
        "notes": result.get("notes") or [],
        "warnings": result.get("warnings") or [],
        "calculation_fingerprint": result.get("calculation_fingerprint"),
        "reporting_year": result.get("reporting_year"),
        "overlap": {
            "detected": bool(overlap),
            "status": "none" if not overlap else "review_required",
            "items": overlap,
            "redistribution": "none",
            "pcaf_ref": PCAF_OVERLAP_REF,
        },
        "double_count_guard": (
            "This parent is the only reportable UoP total for the financing "
            "instance. Underlying asset calculations stay in app.uop_asset_calculations "
            "with is_reportable=false and must not be unioned into dashboards."
        ),
        "metadata": {
            "emissions_unit": result.get("emissions_unit") or "tCO2e",
            "reporting_role": REPORTING_ROLE_PARENT,
            "methodology_version": result.get("methodology_version") or UOP_METHODOLOGY_VERSION,
        },
    }
    return payload


def persist_fields(result: Dict[str, Any], inputs: Dict[str, Any], overlap: List[Dict[str, Any]]) -> Dict[str, Any]:
    attribution = result.get("investor_attribution") or {}
    fe = result.get("financed_emissions")
    af = attribution.get("attribution_factor")
    dq = result.get("data_quality_score")
    return {
        "counterparty_id": (
            uuid.UUID(str(inputs["counterparty_id"]))
            if inputs.get("counterparty_id")
            else None
        ),
        "calc_kind": "finance",
        "company_type": "use-of-proceeds",
        "formula_name": result.get("formula_name"),
        "inputs": inputs,
        "results": parent_results(result, overlap),
        "financed_emissions": None if fe is None else Decimal(str(fe)),
        "attribution_factor": None if af is None else Decimal(str(af)),
        "data_quality_score": None if dq is None else Decimal(str(dq)),
        "status": "completed",
        "legacy_source": "uop_reportable_parent",
    }


def dashboard_eligible(row: FinancedEmission) -> bool:
    """Same exclusion rules the SPA selector uses for reportable totals."""
    if str(row.status or "completed").strip().lower() in EXCLUDED_STATUSES:
        return False
    results = row.results or {}
    if results.get("reporting_role") == REPORTING_ROLE_UNDERLYING:
        return False
    if results.get("include_underlying_independently") is True:
        return False
    overlap = results.get("overlap") or {}
    if overlap.get("status") == "review_required":
        return False
    if row.financed_emissions is None:
        return False
    return True


def select_component_rows(rows: List[FinancedEmission]) -> Tuple[List[FinancedEmission], float]:
    """
    Never add aggregate + components. UoP parents are components and are kept
    alongside a general-purpose aggregate for the same counterparty.
    """
    eligible = [row for row in rows if dashboard_eligible(row)]
    uop_parents = [row for row in eligible if is_uop_formula_id(row.formula_id)]
    general = [row for row in eligible if not is_uop_formula_id(row.formula_id)]
    aggregates = [row for row in general if is_aggregate_formula(row.formula_id)]
    components = [row for row in general if not is_aggregate_formula(row.formula_id)]
    selected: List[FinancedEmission]
    if aggregates:
        latest = sorted(
            aggregates,
            key=lambda row: (row.updated_at or row.created_at, str(row.id)),
            reverse=True,
        )[0]
        selected = [latest, *uop_parents]
    else:
        selected = [*components, *uop_parents]
    selected = _collapse_same_instance(selected)
    total = sum(float(row.financed_emissions or 0) for row in selected)
    return selected, total


def _collapse_same_instance(rows: List[FinancedEmission]) -> List[FinancedEmission]:
    """Keep one row per financing_instance_id (latest reporting year)."""
    by_instance: Dict[str, FinancedEmission] = {}
    leftover: List[FinancedEmission] = []
    for row in rows:
        instance_id = extract_financing_instance_id(row.inputs)
        if not instance_id:
            leftover.append(row)
            continue
        previous = by_instance.get(instance_id)
        if previous is None:
            by_instance[instance_id] = row
            continue
        prev_year = _row_year(previous) or ""
        this_year = _row_year(row) or ""
        if this_year > prev_year:
            by_instance[instance_id] = row
    return leftover + list(by_instance.values())
