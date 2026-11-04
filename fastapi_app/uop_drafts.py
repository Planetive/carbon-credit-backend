"""
Use of Proceeds draft persistence. No emissions formulas. Never writes
app.financed_emissions. Identity is financing_instance_id, not formula_id.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .financing_instance import normalize_financing_instance_id
from .uop_models import (
    UOP_METHODOLOGY_VERSION,
    UOP_NULL_COUNTERPARTY,
    UopAssetCalculation,
    UopInvestment,
    UopStructure,
    UopUnderlyingAsset,
)
from .uop_schemas import (
    UopAssetCalculationOut,
    UopDraftPatch,
    UopDraftRecord,
    UopDraftUpsert,
    UopInvestmentOut,
    UopStructureOut,
    UopUnderlyingAssetOut,
)

ALLOWED_CLASSIFICATIONS = frozenset({"separate", "integrated"})
ALLOWED_INVESTMENT_TYPES = frozenset({"debt", "equity"})
ALLOWED_STATUSES = frozenset({"draft", "in_progress"})
ALLOWED_EMISSIONS_PATHS = frozenset(
    {"issuer_reported", "underlying_assets", "estimation"}
)
ALLOWED_ALLOCATION = frozenset({"known", "unknown", "none_yet"})
ALLOWED_STRUCTURE_KINDS = frozenset(
    {
        "",
        "equity-fund",
        "debt-fund",
        "holding-spv-without-control",
        "labeled-bond",
        "labeled-loan",
        "multi-asset-loan",
        "other",
    }
)
ALLOWED_YES_NO = frozenset({"yes", "no"})
ALLOWED_VERIFICATION = frozenset({"verified", "unverified"})
ALLOWED_ISSUER_REASONS = frozenset(
    {"theoretically_impossible", "practically_not_feasible", "not_material"}
)


def is_uop_formula_id(formula_id: Optional[str]) -> bool:
    """True when a financed-emissions formula_id would be a UoP methodology key."""
    key = (formula_id or "").strip().lower()
    if not key:
        return False
    return key.startswith("uop") or "use-of-proceeds" in key


def uop_reportable_blocked_detail() -> str:
    return (
        "Use of Proceeds cannot be calculated or saved as reportable financed "
        "emissions. Persist drafts via /api/v1/uop/drafts."
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _pick(payload: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return default


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _optional_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _choice(value: Any, allowed: Iterable[str], field: str) -> Optional[str]:
    if value is None or value == "":
        return None
    text = str(value).strip()
    if text not in allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field} must be one of: {sorted(allowed)}",
        )
    return text


def _dec(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid numeric value: {value!r}",
        ) from exc


def _require_instance_id(value: Any) -> str:
    instance = normalize_financing_instance_id(value)
    if not instance:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="financing_instance_id is required and cannot be blank",
        )
    return instance


def _same_counterparty(
    left: Optional[uuid.UUID], right: Optional[uuid.UUID]
) -> bool:
    return (left or UOP_NULL_COUNTERPARTY) == (right or UOP_NULL_COUNTERPARTY)


def _org_rows(db: Session, model, organization_id: uuid.UUID) -> List[Any]:
    return (
        db.query(model)
        .filter(model.organization_id == organization_id)
        .all()
    )


def find_investment_by_instance(
    db: Session,
    *,
    organization_id: uuid.UUID,
    financing_instance_id: str,
    counterparty_id: Optional[uuid.UUID] = None,
    match_counterparty: bool = False,
) -> Optional[UopInvestment]:
    """
    Locate a holding by financing_instance_id.

    Upsert uses match_counterparty=True so the unique key is
    (org, counterparty, instance), matching 0014. Resume/GET without a
    counterparty matches the org-scoped instance; multiple hits are 409.
    """
    instance = normalize_financing_instance_id(financing_instance_id)
    if not instance:
        return None
    matches = [
        row
        for row in _org_rows(db, UopInvestment, organization_id)
        if normalize_financing_instance_id(row.financing_instance_id) == instance
    ]
    if match_counterparty:
        matches = [
            row
            for row in matches
            if _same_counterparty(row.counterparty_id, counterparty_id)
        ]
    elif counterparty_id is not None:
        matches = [
            row
            for row in matches
            if _same_counterparty(row.counterparty_id, counterparty_id)
        ]
    if len(matches) > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "financing_instance_id is ambiguous across counterparties; "
                "pass counterparty_id"
            ),
        )
    return matches[0] if matches else None


def get_org_investment(
    db: Session, organization_id: uuid.UUID, investment_id: uuid.UUID
) -> UopInvestment:
    for row in _org_rows(db, UopInvestment, organization_id):
        if row.id == investment_id:
            return row
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="UoP draft not found",
    )


def get_org_structure(
    db: Session, organization_id: uuid.UUID, structure_id: uuid.UUID
) -> UopStructure:
    for row in _org_rows(db, UopStructure, organization_id):
        if row.id == structure_id:
            return row
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="UoP structure not found",
    )


def _investments_for_structure(
    db: Session, organization_id: uuid.UUID, structure_id: uuid.UUID
) -> List[UopInvestment]:
    return [
        row
        for row in _org_rows(db, UopInvestment, organization_id)
        if row.structure_id == structure_id
    ]


def _assets_for_structure(
    db: Session, organization_id: uuid.UUID, structure_id: uuid.UUID
) -> List[UopUnderlyingAsset]:
    rows = [
        row
        for row in _org_rows(db, UopUnderlyingAsset, organization_id)
        if row.structure_id == structure_id
    ]
    return sorted(rows, key=lambda row: (row.sort_order, str(row.underlying_asset_id)))


def _calcs_for_structure(
    db: Session, organization_id: uuid.UUID, structure_id: uuid.UUID
) -> List[UopAssetCalculation]:
    return [
        row
        for row in _org_rows(db, UopAssetCalculation, organization_id)
        if row.structure_id == structure_id
    ]


def _apply_structure_fields(structure: UopStructure, draft: Dict[str, Any]) -> None:
    structure.name = _text(_pick(draft, "structureName", "structure_name", default=""))
    structure.issuer_name = _text(_pick(draft, "issuerName", "issuer_name", default=""))
    structure.structure_kind = _choice(
        _pick(draft, "structureKind", "structure_kind", default=""),
        ALLOWED_STRUCTURE_KINDS,
        "structureKind",
    ) or ""
    structure.classification = _choice(
        _pick(draft, "classification"),
        ALLOWED_CLASSIFICATIONS,
        "classification",
    )
    eligibility = _pick(draft, "eligibility", default={})
    structure.eligibility = dict(eligibility) if isinstance(eligibility, dict) else {}
    structure.total_structure_debt = _dec(
        _pick(draft, "totalStructureDebt", "total_structure_debt")
    )
    structure.total_structure_equity = _dec(
        _pick(draft, "totalStructureEquity", "total_structure_equity")
    )
    structure.reporting_year = _optional_text(
        _pick(draft, "reportingYear", "reporting_year")
    )
    structure.methodology_version = (
        _optional_text(_pick(draft, "methodologyVersion", "methodology_version"))
        or UOP_METHODOLOGY_VERSION
    )
    structure.currency = _optional_text(_pick(draft, "currency")) or "PKR"
    structure.evidence_source = _text(
        _pick(draft, "evidenceSource", "evidence_source", default="")
    )
    structure.evidence_notes = _text(
        _pick(draft, "evidenceNotes", "evidence_notes", default="")
    )
    structure.allocation_status = _choice(
        _pick(draft, "allocationStatus", "allocation_status"),
        ALLOWED_ALLOCATION,
        "allocationStatus",
    )
    structure.allocated_proceeds = _dec(
        _pick(draft, "allocatedProceeds", "allocated_proceeds")
    )
    structure.unallocated_proceeds = _dec(
        _pick(draft, "unallocatedProceeds", "unallocated_proceeds")
    )
    structure.expected_allocation_evidence = _text(
        _pick(
            draft,
            "expectedAllocationEvidence",
            "expected_allocation_evidence",
            default="",
        )
    )
    estimate = _pick(
        draft,
        "unallocatedUsesAssetLevelEstimate",
        "unallocated_uses_asset_level_estimate",
    )
    structure.unallocated_uses_asset_level_estimate = _choice(
        estimate, ALLOWED_YES_NO, "unallocatedUsesAssetLevelEstimate"
    )
    structure.emissions_path = _choice(
        _pick(draft, "emissionsPath", "emissions_path"),
        ALLOWED_EMISSIONS_PATHS,
        "emissionsPath",
    )
    structure.issuer_level_reason = _choice(
        _pick(draft, "issuerLevelReason", "issuer_level_reason"),
        ALLOWED_ISSUER_REASONS,
        "issuerLevelReason",
    )
    structure.issuer_reported_financed_emissions = _dec(
        _pick(
            draft,
            "issuerReportedFinancedEmissions",
            "issuer_reported_financed_emissions",
        )
    )
    structure.issuer_report_year = _optional_text(
        _pick(draft, "issuerReportYear", "issuer_report_year")
    )
    structure.issuer_report_verification = _choice(
        _pick(draft, "issuerReportVerification", "issuer_report_verification"),
        ALLOWED_VERIFICATION,
        "issuerReportVerification",
    )
    structure.issuer_report_source = _text(
        _pick(draft, "issuerReportSource", "issuer_report_source", default="")
    )
    structure.updated_at = _now()


def _apply_investment_fields(
    investment: UopInvestment,
    *,
    draft: Dict[str, Any],
    instance_id: str,
    instance_key: Optional[str],
    formula_id: Optional[str],
    formula_name: Optional[str],
    exposure_id: Optional[uuid.UUID],
    counterparty_id: Optional[uuid.UUID],
) -> None:
    investment_type = _choice(
        _pick(draft, "investmentType", "investment_type"),
        ALLOWED_INVESTMENT_TYPES,
        "investmentType",
    )
    investment.financing_instance_id = instance_id
    investment.instance_key = instance_key or _optional_text(
        _pick(draft, "instanceKey", "instance_key")
    )
    investment.investment_type = investment_type
    investment.outstanding_amount = _dec(
        _pick(draft, "outstandingInvestment", "outstanding_amount")
    )
    investment.formula_id = _optional_text(formula_id) or _optional_text(
        _pick(draft, "formulaId", "formula_id")
    )
    investment.formula_name = _optional_text(formula_name)
    investment.exposure_id = exposure_id
    investment.counterparty_id = counterparty_id
    investment.status = "draft"
    investment.is_reportable = False
    investment.include_in_portfolio = False
    snapshot = dict(draft)
    snapshot["financingInstanceId"] = instance_id
    if investment.instance_key:
        snapshot["instanceKey"] = investment.instance_key
    previous = dict(investment.draft_snapshot or {})
    if "lastCalculation" in previous and "lastCalculation" not in snapshot:
        snapshot["lastCalculation"] = previous["lastCalculation"]
    investment.draft_snapshot = snapshot
    investment.updated_at = _now()


def _validate_integrated_debt_only(
    classification: Optional[str], investment_type: Optional[str]
) -> None:
    if classification == "integrated" and investment_type == "equity":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "PCAF 2025 Part A footnote 174: integrated Use of Proceeds "
                "investors are debt-only."
            ),
        )


def _reject_reportable_payload(draft: Dict[str, Any]) -> None:
    for key in (
        "is_reportable",
        "include_in_portfolio",
        "isReportable",
        "includeInPortfolio",
    ):
        if draft.get(key) is True:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "UoP drafts cannot be marked reportable or included in the "
                    "portfolio. Totals are not saved as financed emissions."
                ),
            )


def _json_num(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(Decimal(str(value)))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _same_dt(left: Optional[datetime], right: Optional[datetime]) -> bool:
    if left is None or right is None:
        return left is right
    return abs((_aware(left) - _aware(right)).total_seconds()) < 0.002


def _same_num(left: Any, right: Any) -> bool:
    if left in (None, "") and right in (None, ""):
        return True
    if left in (None, "") or right in (None, ""):
        return False
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except (InvalidOperation, ValueError):
        return False


def _same_text(left: Any, right: Any) -> bool:
    return _text(left).strip() == _text(right).strip()


def _same_json(left: Any, right: Any) -> bool:
    return json.dumps(left or {}, sort_keys=True, default=str) == json.dumps(
        right or {}, sort_keys=True, default=str
    )


def _proposed_shared(draft: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": _text(_pick(draft, "structureName", "structure_name", default="")),
        "issuer_name": _text(_pick(draft, "issuerName", "issuer_name", default="")),
        "structure_kind": _text(
            _pick(draft, "structureKind", "structure_kind", default="")
        ),
        "classification": _optional_text(_pick(draft, "classification")),
        "eligibility": _pick(draft, "eligibility", default={}) or {},
        "total_structure_debt": _pick(draft, "totalStructureDebt", "total_structure_debt"),
        "total_structure_equity": _pick(
            draft, "totalStructureEquity", "total_structure_equity"
        ),
        "reporting_year": _optional_text(
            _pick(draft, "reportingYear", "reporting_year")
        ),
        "currency": _optional_text(_pick(draft, "currency")) or "PKR",
        "evidence_source": _text(
            _pick(draft, "evidenceSource", "evidence_source", default="")
        ),
        "evidence_notes": _text(
            _pick(draft, "evidenceNotes", "evidence_notes", default="")
        ),
        "allocation_status": _optional_text(
            _pick(draft, "allocationStatus", "allocation_status")
        ),
        "allocated_proceeds": _pick(draft, "allocatedProceeds", "allocated_proceeds"),
        "unallocated_proceeds": _pick(
            draft, "unallocatedProceeds", "unallocated_proceeds"
        ),
        "expected_allocation_evidence": _text(
            _pick(
                draft,
                "expectedAllocationEvidence",
                "expected_allocation_evidence",
                default="",
            )
        ),
        "unallocated_uses_asset_level_estimate": _optional_text(
            _pick(
                draft,
                "unallocatedUsesAssetLevelEstimate",
                "unallocated_uses_asset_level_estimate",
            )
        ),
        "emissions_path": _optional_text(
            _pick(draft, "emissionsPath", "emissions_path")
        ),
        "issuer_level_reason": _optional_text(
            _pick(draft, "issuerLevelReason", "issuer_level_reason")
        ),
        "issuer_reported_financed_emissions": _pick(
            draft,
            "issuerReportedFinancedEmissions",
            "issuer_reported_financed_emissions",
        ),
        "issuer_report_year": _optional_text(
            _pick(draft, "issuerReportYear", "issuer_report_year")
        ),
        "issuer_report_verification": _optional_text(
            _pick(draft, "issuerReportVerification", "issuer_report_verification")
        ),
        "issuer_report_source": _text(
            _pick(draft, "issuerReportSource", "issuer_report_source", default="")
        ),
    }


def _shared_field_changes(structure: UopStructure, draft: Dict[str, Any]) -> List[str]:
    proposed = _proposed_shared(draft)
    current = {
        "name": structure.name or "",
        "issuer_name": structure.issuer_name or "",
        "structure_kind": structure.structure_kind or "",
        "classification": structure.classification,
        "eligibility": structure.eligibility or {},
        "total_structure_debt": structure.total_structure_debt,
        "total_structure_equity": structure.total_structure_equity,
        "reporting_year": structure.reporting_year,
        "currency": structure.currency or "PKR",
        "evidence_source": structure.evidence_source or "",
        "evidence_notes": structure.evidence_notes or "",
        "allocation_status": structure.allocation_status,
        "allocated_proceeds": structure.allocated_proceeds,
        "unallocated_proceeds": structure.unallocated_proceeds,
        "expected_allocation_evidence": structure.expected_allocation_evidence or "",
        "unallocated_uses_asset_level_estimate": structure.unallocated_uses_asset_level_estimate,
        "emissions_path": structure.emissions_path,
        "issuer_level_reason": structure.issuer_level_reason,
        "issuer_reported_financed_emissions": structure.issuer_reported_financed_emissions,
        "issuer_report_year": structure.issuer_report_year,
        "issuer_report_verification": structure.issuer_report_verification,
        "issuer_report_source": structure.issuer_report_source or "",
    }
    numeric = {
        "total_structure_debt",
        "total_structure_equity",
        "allocated_proceeds",
        "unallocated_proceeds",
        "issuer_reported_financed_emissions",
    }
    json_fields = {"eligibility"}
    changed: List[str] = []
    for key, old in current.items():
        new = proposed.get(key)
        if key in numeric:
            if not _same_num(old, new):
                changed.append(key)
        elif key in json_fields:
            if not _same_json(_compact_json(old), _compact_json(new)):
                changed.append(key)
        else:
            if not _same_text(old, new):
                changed.append(key)
    return changed


def _compact_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: compact
            for key, item in value.items()
            if (compact := _compact_json(item)) not in (None, "", [], {})
        }
    if isinstance(value, list):
        return [item for item in (_compact_json(item) for item in value) if item not in (None, "", [], {})]
    return value


def _asset_changes(
    assets: Sequence[UopUnderlyingAsset], draft: Dict[str, Any]
) -> List[str]:
    if _pick(draft, "assets", default=None) is None:
        return []
    payloads = _asset_payloads(draft)
    existing = {
        normalize_financing_instance_id(row.underlying_asset_id): row for row in assets
    }
    incoming = {item["_id"] for item in payloads}
    if existing.keys() != incoming:
        return ["assets"]
    for item in payloads:
        row = existing.get(item["_id"])
        if row is None:
            return ["assets"]
        if not _same_text(row.name, _pick(item, "name", default="")):
            return ["assets"]
        if not _same_text(row.asset_class, _pick(item, "assetClass", "asset_class", default="")):
            return ["assets"]
        if not _same_num(
            row.allocated_outstanding,
            _pick(item, "allocatedOutstanding", "allocated_outstanding"),
        ):
            return ["assets"]
        if not _same_num(
            row.total_asset_value, _pick(item, "totalAssetValue", "total_asset_value")
        ):
            return ["assets"]
        if not _same_text(
            row.has_reported_emissions,
            _pick(item, "hasReportedEmissions", "has_reported_emissions"),
        ):
            return ["assets"]
        if not _same_text(
            row.verification_status,
            _pick(item, "verificationStatus", "verification_status"),
        ):
            return ["assets"]
        if not _same_num(row.scope1_emissions, _pick(item, "scope1Emissions", "scope1_emissions")):
            return ["assets"]
        if not _same_num(row.scope2_emissions, _pick(item, "scope2Emissions", "scope2_emissions")):
            return ["assets"]
        if not _same_num(row.scope3_emissions, _pick(item, "scope3Emissions", "scope3_emissions")):
            return ["assets"]
        if not _same_json(
            _compact_json(row.estimation),
            _compact_json(_pick(item, "estimation", default={})),
        ):
            return ["assets"]
    return []


def _conflict_detail(
    *,
    code: str,
    message: str,
    structure: UopStructure,
    changed_fields: Sequence[str],
    sibling_count: int,
    sibling_ids: Sequence[str],
) -> Dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "changed_fields": list(changed_fields),
        "structure_id": str(structure.id),
        "structure_updated_at": _iso(structure.updated_at),
        "sibling_count": sibling_count,
        "sibling_financing_instance_ids": list(sibling_ids),
    }


def _check_structure_lock(
    structure: UopStructure,
    expected: Optional[datetime],
    *,
    siblings: Sequence[UopInvestment],
) -> None:
    if not siblings:
        return
    if expected is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_conflict_detail(
                code="stale_structure",
                message=(
                    "Confirm this shared-fund change with expected_structure_updated_at "
                    "so other holdings are not overwritten."
                ),
                structure=structure,
                changed_fields=[],
                sibling_count=len(siblings),
                sibling_ids=[row.financing_instance_id for row in siblings],
            ),
        )
    if not _same_dt(structure.updated_at, expected):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_conflict_detail(
                code="stale_structure",
                message=(
                    "The shared fund was updated elsewhere. Refresh and review "
                    "before saving fund-level changes."
                ),
                structure=structure,
                changed_fields=[],
                sibling_count=len(siblings),
                sibling_ids=[row.financing_instance_id for row in siblings],
            ),
        )


def _check_investment_lock(
    investment: UopInvestment, expected: Optional[datetime]
) -> None:
    if expected is None:
        return
    if not _same_dt(investment.updated_at, expected):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "stale_investment",
                "message": (
                    "This holding was saved more recently. Refresh before overwriting "
                    "your outstanding amount or investment type."
                ),
                "investment_id": str(investment.id),
                "investment_updated_at": _iso(investment.updated_at),
            },
        )


def _asset_to_draft(asset: UopUnderlyingAsset) -> Dict[str, Any]:
    return {
        "underlyingAssetId": asset.underlying_asset_id,
        "name": asset.name or "",
        "assetClass": asset.asset_class or "",
        "allocatedOutstanding": _json_num(asset.allocated_outstanding),
        "totalAssetValue": _json_num(asset.total_asset_value),
        "hasReportedEmissions": asset.has_reported_emissions or "",
        "verificationStatus": asset.verification_status or "",
        "verifierName": asset.verifier_name or "",
        "scope1Emissions": _json_num(asset.scope1_emissions),
        "scope2Emissions": _json_num(asset.scope2_emissions),
        "scope3Emissions": _json_num(asset.scope3_emissions),
        "dataSource": asset.data_source or "",
        "evidenceNotes": asset.evidence_notes or "",
        "estimation": dict(asset.estimation or {}),
    }


def _compose_draft(
    structure: UopStructure,
    investment: UopInvestment,
    assets: Sequence[UopUnderlyingAsset],
) -> Dict[str, Any]:
    snapshot = dict(investment.draft_snapshot or {})
    snapshot.update(
        {
            "financingInstanceId": investment.financing_instance_id,
            "instanceKey": investment.instance_key or snapshot.get("instanceKey") or "",
            "investmentType": investment.investment_type or "",
            "outstandingInvestment": _json_num(investment.outstanding_amount),
            "structureId": str(structure.id),
            "investmentId": str(investment.id),
            "structureUpdatedAt": _iso(structure.updated_at),
            "investmentUpdatedAt": _iso(investment.updated_at),
            "structureName": structure.name or "",
            "issuerName": structure.issuer_name or "",
            "structureKind": structure.structure_kind or "",
            "classification": structure.classification or "",
            "eligibility": structure.eligibility or snapshot.get("eligibility") or {},
            "totalStructureDebt": _json_num(structure.total_structure_debt),
            "totalStructureEquity": _json_num(structure.total_structure_equity),
            "reportingYear": structure.reporting_year or snapshot.get("reportingYear") or "",
            "currency": structure.currency or "PKR",
            "evidenceSource": structure.evidence_source or "",
            "evidenceNotes": structure.evidence_notes or "",
            "emissionsPath": structure.emissions_path or "",
            "issuerLevelReason": structure.issuer_level_reason or "",
            "issuerReportedFinancedEmissions": _json_num(
                structure.issuer_reported_financed_emissions
            ),
            "issuerReportYear": structure.issuer_report_year or "",
            "issuerReportVerification": structure.issuer_report_verification or "",
            "issuerReportSource": structure.issuer_report_source or "",
            "allocationStatus": structure.allocation_status or "",
            "allocatedProceeds": _json_num(structure.allocated_proceeds),
            "unallocatedProceeds": _json_num(structure.unallocated_proceeds),
            "expectedAllocationEvidence": structure.expected_allocation_evidence or "",
            "unallocatedUsesAssetLevelEstimate": structure.unallocated_uses_asset_level_estimate
            or "",
            "assets": [_asset_to_draft(row) for row in assets],
        }
    )
    return snapshot


def _decide_shared_write(
    *,
    structure: UopStructure,
    assets: Sequence[UopUnderlyingAsset],
    draft: Dict[str, Any],
    siblings: Sequence[UopInvestment],
    created_new_structure: bool,
    attaching: bool,
    update_shared: bool,
    expected_structure_updated_at: Optional[datetime],
) -> bool:
    if created_new_structure:
        return True
    changed = _shared_field_changes(structure, draft) + _asset_changes(assets, draft)
    if attaching and not update_shared:
        return False
    if update_shared:
        _check_structure_lock(
            structure, expected_structure_updated_at, siblings=siblings
        )
        return True
    if not changed:
        return False
    if not siblings:
        return True
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=_conflict_detail(
            code="shared_structure_conflict",
            message=(
                "This save would change shared fund or asset data used by other "
                "holdings. Confirm update_shared=true after reviewing, or save "
                "only this holding's outstanding amount."
            ),
            structure=structure,
            changed_fields=changed,
            sibling_count=len(siblings),
            sibling_ids=[row.financing_instance_id for row in siblings],
        ),
    )


def _asset_payloads(draft: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = _pick(draft, "assets", default=[])
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="draft.assets must be an array",
        )
    payloads: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="each underlying asset must be an object",
            )
        asset_id = normalize_financing_instance_id(
            _pick(item, "underlyingAssetId", "underlying_asset_id")
        )
        if not asset_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="each underlying asset requires underlyingAssetId",
            )
        if asset_id in seen:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"duplicate underlyingAssetId: {asset_id}",
            )
        seen.add(asset_id)
        payloads.append({**item, "_id": asset_id, "_order": index})
    return payloads


def _apply_asset_fields(asset: UopUnderlyingAsset, payload: Dict[str, Any]) -> None:
    asset.underlying_asset_id = payload["_id"]
    asset.name = _text(_pick(payload, "name", default=""))
    asset.asset_class = _text(_pick(payload, "assetClass", "asset_class", default=""))
    asset.sort_order = int(payload["_order"])
    asset.allocated_outstanding = _dec(
        _pick(payload, "allocatedOutstanding", "allocated_outstanding")
    )
    asset.total_asset_value = _dec(
        _pick(payload, "totalAssetValue", "total_asset_value")
    )
    asset.has_reported_emissions = _choice(
        _pick(payload, "hasReportedEmissions", "has_reported_emissions"),
        ALLOWED_YES_NO,
        "hasReportedEmissions",
    )
    asset.verification_status = _choice(
        _pick(payload, "verificationStatus", "verification_status"),
        ALLOWED_VERIFICATION,
        "verificationStatus",
    )
    asset.verifier_name = _text(_pick(payload, "verifierName", "verifier_name", default=""))
    asset.scope1_emissions = _dec(_pick(payload, "scope1Emissions", "scope1_emissions"))
    asset.scope2_emissions = _dec(_pick(payload, "scope2Emissions", "scope2_emissions"))
    asset.scope3_emissions = _dec(_pick(payload, "scope3Emissions", "scope3_emissions"))
    asset.data_source = _text(_pick(payload, "dataSource", "data_source", default=""))
    asset.evidence_notes = _text(
        _pick(payload, "evidenceNotes", "evidence_notes", default="")
    )
    estimation = _pick(payload, "estimation", default={})
    asset.estimation = dict(estimation) if isinstance(estimation, dict) else {}
    asset.inputs = {
        "underlyingAssetId": payload["_id"],
        "assetClass": asset.asset_class,
        "name": asset.name,
    }
    asset.updated_at = _now()


def _find_calc(
    calcs: Sequence[UopAssetCalculation],
    *,
    asset_id: uuid.UUID,
    investment_id: uuid.UUID,
    reporting_year: Optional[str],
    methodology_version: str,
) -> Optional[UopAssetCalculation]:
    year = (reporting_year or "").strip()
    for row in calcs:
        if row.asset_id != asset_id:
            continue
        if row.investment_id != investment_id:
            continue
        if (row.reporting_year or "").strip() != year:
            continue
        if (row.methodology_version or "") != methodology_version:
            continue
        return row
    return None


def _ensure_investment_calcs(
    db: Session,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    structure: UopStructure,
    investment: UopInvestment,
    assets: Sequence[UopUnderlyingAsset],
) -> None:
    existing_calcs = _calcs_for_structure(db, organization_id, structure.id)
    for asset in assets:
        calc = _find_calc(
            existing_calcs,
            asset_id=asset.id,
            investment_id=investment.id,
            reporting_year=structure.reporting_year,
            methodology_version=structure.methodology_version,
        )
        if calc is None:
            db.add(
                UopAssetCalculation(
                    id=uuid.uuid4(),
                    organization_id=organization_id,
                    structure_id=structure.id,
                    asset_id=asset.id,
                    investment_id=investment.id,
                    reporting_year=structure.reporting_year,
                    methodology_version=structure.methodology_version,
                    formula_id=None,
                    status="draft",
                    inputs={
                        "underlying_asset_id": asset.underlying_asset_id,
                        "asset_class": asset.asset_class,
                        "financing_instance_id": investment.financing_instance_id,
                    },
                    results={},
                    financed_emissions=None,
                    include_in_portfolio=False,
                    is_reportable=False,
                    provenance={
                        "kind": "uop_underlying_draft",
                        "phase": "5B",
                        "formula_implemented": False,
                        "updated_by": str(user_id),
                    },
                    created_at=_now(),
                    updated_at=_now(),
                )
            )
            continue
        calc.include_in_portfolio = False
        calc.is_reportable = False
        calc.status = "draft"
        calc.inputs = {
            "underlying_asset_id": asset.underlying_asset_id,
            "asset_class": asset.asset_class,
            "financing_instance_id": investment.financing_instance_id,
        }
        calc.provenance = {
            **dict(calc.provenance or {}),
            "kind": "uop_underlying_draft",
            "phase": "5B",
            "formula_implemented": False,
            "updated_by": str(user_id),
        }
        calc.updated_at = _now()


def _sync_assets_and_calcs(
    db: Session,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    structure: UopStructure,
    investment: UopInvestment,
    draft: Dict[str, Any],
    apply_shared: bool,
) -> Tuple[List[UopUnderlyingAsset], List[UopAssetCalculation]]:
    existing_assets = _assets_for_structure(db, organization_id, structure.id)
    existing_calcs = _calcs_for_structure(db, organization_id, structure.id)
    if not apply_shared:
        _ensure_investment_calcs(
            db,
            organization_id=organization_id,
            user_id=user_id,
            structure=structure,
            investment=investment,
            assets=existing_assets,
        )
        return existing_assets, _calcs_for_structure(db, organization_id, structure.id)

    payloads = _asset_payloads(draft)
    by_frontend_id = {
        normalize_financing_instance_id(row.underlying_asset_id): row
        for row in existing_assets
    }
    keep_ids: set[str] = set()
    synced_assets: List[UopUnderlyingAsset] = []
    for payload in payloads:
        asset_id = payload["_id"]
        keep_ids.add(asset_id)
        asset = by_frontend_id.get(asset_id)
        if asset is None:
            asset = UopUnderlyingAsset(
                id=uuid.uuid4(),
                organization_id=organization_id,
                structure_id=structure.id,
                underlying_asset_id=asset_id,
                created_at=_now(),
                updated_at=_now(),
            )
            db.add(asset)
        _apply_asset_fields(asset, payload)
        synced_assets.append(asset)

    _flush(db)
    _ensure_investment_calcs(
        db,
        organization_id=organization_id,
        user_id=user_id,
        structure=structure,
        investment=investment,
        assets=synced_assets,
    )

    for asset in existing_assets:
        frontend_id = normalize_financing_instance_id(asset.underlying_asset_id)
        if frontend_id in keep_ids:
            continue
        for calc in existing_calcs:
            if calc.asset_id == asset.id:
                db.delete(calc)
        db.delete(asset)
    return synced_assets, _calcs_for_structure(db, organization_id, structure.id)


def _bundle(
    db: Session,
    organization_id: uuid.UUID,
    investment: UopInvestment,
    *,
    created: bool = False,
    shared_write_applied: bool = False,
) -> UopDraftRecord:
    structure = get_org_structure(db, organization_id, investment.structure_id)
    assets = _assets_for_structure(db, organization_id, structure.id)
    calcs = [
        row
        for row in _calcs_for_structure(db, organization_id, structure.id)
        if row.investment_id == investment.id
    ]
    holdings = _investments_for_structure(db, organization_id, structure.id)
    holding_count = len(holdings)
    sibling_count = max(0, holding_count - 1)
    return UopDraftRecord(
        investment=UopInvestmentOut.model_validate(investment),
        structure=UopStructureOut.model_validate(structure),
        assets=[UopUnderlyingAssetOut.model_validate(row) for row in assets],
        calculations=[UopAssetCalculationOut.model_validate(row) for row in calcs],
        draft=_compose_draft(structure, investment, assets),
        created=created,
        sibling_count=sibling_count,
        holding_count=holding_count,
        shared_write_applied=shared_write_applied,
    )


def _flush(db: Session) -> None:
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "UoP draft conflicts with an existing financing_instance_id "
                f"under this organization/counterparty. ({exc.orig})"
            ),
        ) from exc


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "UoP draft conflicts with an existing financing_instance_id "
                f"under this organization/counterparty. ({exc.orig})"
            ),
        ) from exc


def upsert_uop_draft(
    db: Session,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    body: UopDraftUpsert,
) -> UopDraftRecord:
    draft = dict(body.draft or {})
    _reject_reportable_payload(draft)
    instance_id = _require_instance_id(
        body.financing_instance_id
        or _pick(draft, "financingInstanceId", "financing_instance_id")
    )
    _validate_integrated_debt_only(
        _choice(_pick(draft, "classification"), ALLOWED_CLASSIFICATIONS, "classification"),
        _choice(
            _pick(draft, "investmentType", "investment_type"),
            ALLOWED_INVESTMENT_TYPES,
            "investmentType",
        ),
    )
    existing = find_investment_by_instance(
        db,
        organization_id=organization_id,
        financing_instance_id=instance_id,
        counterparty_id=body.counterparty_id,
        match_counterparty=True,
    )
    created = existing is None
    created_new_structure = False
    attaching = False
    if existing is not None:
        if (
            body.structure_id is not None
            and body.structure_id != existing.structure_id
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "financing_instance_id already belongs to a different UoP "
                    "structure; updating this holding does not move or overwrite "
                    "unrelated investments."
                ),
            )
        structure = get_org_structure(db, organization_id, existing.structure_id)
        investment = existing
        _check_investment_lock(investment, body.expected_investment_updated_at)
    else:
        if body.structure_id is not None:
            structure = get_org_structure(db, organization_id, body.structure_id)
            attaching = True
        else:
            structure = UopStructure(
                id=uuid.uuid4(),
                organization_id=organization_id,
                user_id=user_id,
                counterparty_id=body.counterparty_id,
                status="draft",
                methodology_version=UOP_METHODOLOGY_VERSION,
                eligibility={},
                created_at=_now(),
                updated_at=_now(),
            )
            db.add(structure)
            created_new_structure = True
            _flush(db)
        investment = UopInvestment(
            id=uuid.uuid4(),
            organization_id=organization_id,
            user_id=user_id,
            structure_id=structure.id,
            financing_instance_id=instance_id,
            status="draft",
            is_reportable=False,
            include_in_portfolio=False,
            draft_snapshot={},
            created_at=_now(),
            updated_at=_now(),
        )
        db.add(investment)
        _flush(db)

    apply_shared = False
    try:
        siblings = [
            row
            for row in _investments_for_structure(db, organization_id, structure.id)
            if row.id != investment.id
        ]
        assets = _assets_for_structure(db, organization_id, structure.id)
        apply_shared = _decide_shared_write(
            structure=structure,
            assets=assets,
            draft=draft,
            siblings=siblings,
            created_new_structure=created_new_structure,
            attaching=attaching,
            update_shared=body.update_shared,
            expected_structure_updated_at=body.expected_structure_updated_at,
        )
        if apply_shared:
            _apply_structure_fields(structure, draft)
            structure.user_id = user_id
            if body.counterparty_id is not None and structure.counterparty_id is None:
                structure.counterparty_id = body.counterparty_id
        _apply_investment_fields(
            investment,
            draft=draft,
            instance_id=instance_id,
            instance_key=body.instance_key,
            formula_id=body.formula_id,
            formula_name=body.formula_name,
            exposure_id=body.exposure_id,
            counterparty_id=body.counterparty_id,
        )
        investment.user_id = user_id
        investment.structure_id = structure.id
        _validate_integrated_debt_only(
            structure.classification, investment.investment_type
        )
        _sync_assets_and_calcs(
            db,
            organization_id=organization_id,
            user_id=user_id,
            structure=structure,
            investment=investment,
            draft=draft,
            apply_shared=apply_shared,
        )
        db.add(structure)
        db.add(investment)
        _commit(db)
    except HTTPException:
        db.rollback()
        raise
    db.refresh(investment)
    db.refresh(structure)
    return _bundle(
        db,
        organization_id,
        investment,
        created=created,
        shared_write_applied=apply_shared,
    )


def patch_uop_draft(
    db: Session,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    investment_id: uuid.UUID,
    body: UopDraftPatch,
) -> UopDraftRecord:
    investment = get_org_investment(db, organization_id, investment_id)
    structure = get_org_structure(db, organization_id, investment.structure_id)
    _check_investment_lock(investment, body.expected_investment_updated_at)
    draft = dict(investment.draft_snapshot or {})
    if body.draft:
        _reject_reportable_payload(body.draft)
        draft.update(body.draft)
    instance_id = investment.financing_instance_id
    siblings = [
        row
        for row in _investments_for_structure(db, organization_id, structure.id)
        if row.id != investment.id
    ]
    assets = _assets_for_structure(db, organization_id, structure.id)
    apply_shared = False
    if body.draft is not None:
        apply_shared = _decide_shared_write(
            structure=structure,
            assets=assets,
            draft=draft,
            siblings=siblings,
            created_new_structure=False,
            attaching=False,
            update_shared=body.update_shared,
            expected_structure_updated_at=body.expected_structure_updated_at,
        )
    try:
        if apply_shared:
            _apply_structure_fields(structure, draft)
            structure.user_id = user_id
        _apply_investment_fields(
            investment,
            draft=draft,
            instance_id=instance_id,
            instance_key=body.instance_key if body.instance_key is not None else investment.instance_key,
            formula_id=body.formula_id if body.formula_id is not None else investment.formula_id,
            formula_name=body.formula_name if body.formula_name is not None else investment.formula_name,
            exposure_id=body.exposure_id if body.exposure_id is not None else investment.exposure_id,
            counterparty_id=body.counterparty_id if body.counterparty_id is not None else investment.counterparty_id,
        )
        investment.user_id = user_id
        _validate_integrated_debt_only(
            structure.classification, investment.investment_type
        )
        _sync_assets_and_calcs(
            db,
            organization_id=organization_id,
            user_id=user_id,
            structure=structure,
            investment=investment,
            draft=draft,
            apply_shared=apply_shared,
        )
        db.add(structure)
        db.add(investment)
        _commit(db)
    except HTTPException:
        db.rollback()
        raise
    db.refresh(investment)
    db.refresh(structure)
    return _bundle(
        db,
        organization_id,
        investment,
        shared_write_applied=apply_shared,
    )


def get_uop_draft(
    db: Session, organization_id: uuid.UUID, investment_id: uuid.UUID
) -> UopDraftRecord:
    investment = get_org_investment(db, organization_id, investment_id)
    return _bundle(db, organization_id, investment)


def get_uop_draft_by_instance(
    db: Session,
    *,
    organization_id: uuid.UUID,
    financing_instance_id: str,
    counterparty_id: Optional[uuid.UUID] = None,
) -> UopDraftRecord:
    instance_id = _require_instance_id(financing_instance_id)
    investment = find_investment_by_instance(
        db,
        organization_id=organization_id,
        financing_instance_id=instance_id,
        counterparty_id=counterparty_id,
    )
    if investment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="UoP draft not found",
        )
    return _bundle(db, organization_id, investment)


def list_uop_drafts(
    db: Session,
    *,
    organization_id: uuid.UUID,
    counterparty_id: Optional[uuid.UUID] = None,
    structure_id: Optional[uuid.UUID] = None,
    financing_instance_id: Optional[str] = None,
) -> List[UopDraftRecord]:
    instance = normalize_financing_instance_id(financing_instance_id)
    rows = _org_rows(db, UopInvestment, organization_id)
    if counterparty_id is not None:
        rows = [row for row in rows if row.counterparty_id == counterparty_id]
    if structure_id is not None:
        rows = [row for row in rows if row.structure_id == structure_id]
    if instance:
        rows = [
            row
            for row in rows
            if normalize_financing_instance_id(row.financing_instance_id) == instance
        ]
    rows.sort(key=lambda row: row.created_at or _now(), reverse=True)
    return [_bundle(db, organization_id, row) for row in rows]


def delete_uop_draft(
    db: Session, organization_id: uuid.UUID, investment_id: uuid.UUID
) -> None:
    investment = get_org_investment(db, organization_id, investment_id)
    structure_id = investment.structure_id
    for calc in _calcs_for_structure(db, organization_id, structure_id):
        if calc.investment_id == investment.id:
            db.delete(calc)
    db.delete(investment)
    remaining = [
        row
        for row in _investments_for_structure(db, organization_id, structure_id)
        if row.id != investment.id
    ]
    if not remaining:
        for calc in _calcs_for_structure(db, organization_id, structure_id):
            db.delete(calc)
        for asset in _assets_for_structure(db, organization_id, structure_id):
            db.delete(asset)
        structure = get_org_structure(db, organization_id, structure_id)
        db.delete(structure)
    _commit(db)
