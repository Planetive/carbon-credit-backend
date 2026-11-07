"""Approved emission-factor library. Org users match; admins approve. No silent substitution."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth_org import OrgContext
from ..db import get_db
from ..factor_library import (
    NO_FACTOR,
    SOURCE_REGISTRY,
    MatchQuery,
    entry_to_factor,
    match_factors,
    split_unit,
)
from ..factor_library_models import FactorLibraryAudit, FactorLibraryEntry
from ..factor_models import FactorDataset, FactorRow
from .catalog_utils import table_exists
from .deps import ADMIN_ROLES, require_org_context

router = APIRouter(prefix="/factor-library", tags=["factor-library"])


class MatchRequest(BaseModel):
    library_class: str
    geography: str
    activity_key: str
    reporting_year: int
    unit: str = ""
    currency_code: str = ""
    price_year: Optional[int] = None


class ManualFactorSubmit(BaseModel):
    library_class: str
    geography: str
    country_code: str = ""
    sector_or_activity: str
    activity_key: str
    factor_value: Decimal
    unit: str
    applicable_year: int
    publication_year: int
    source_organization: str
    source_document: str = ""
    source_url: str = ""
    provenance: str = ""
    license_name: str = ""
    permitted_use: str = ""
    currency_code: str = ""
    price_year: Optional[int] = None
    rationale: str = Field(min_length=8)
    gas: str = "CO2e"
    category: str = "manual_submission"


class ReviewRequest(BaseModel):
    notes: str = ""
    publish_global: bool = False


def _library_ready(db: Session) -> bool:
    return table_exists(db, "ref", "factor_library_entries")


def _require_library(db: Session) -> None:
    if not _library_ready(db):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Emission-factor library tables are not available on this database.",
        )


def _is_admin(ctx: OrgContext) -> bool:
    return (ctx.role or "").lower() in ADMIN_ROLES


def _entry_out(row: FactorLibraryEntry) -> Dict[str, Any]:
    factor = entry_to_factor(row)
    payload = factor.snapshot()
    payload["status"] = row.status
    payload["organization_id"] = str(row.organization_id) if row.organization_id else None
    payload["submitted_rationale"] = row.submitted_rationale
    payload["review_notes"] = row.review_notes
    payload["scope_boundary"] = row.scope_boundary
    payload["emissions_boundary"] = row.emissions_boundary
    return payload


def _visible_entries(db: Session, ctx: OrgContext) -> List[FactorLibraryEntry]:
    rows = (
        db.query(FactorLibraryEntry)
        .filter(FactorLibraryEntry.status == "approved")
        .all()
    )
    visible: List[FactorLibraryEntry] = []
    for row in rows:
        if row.organization_id is None:
            visible.append(row)
        elif ctx.organization_id and row.organization_id == ctx.organization_id:
            visible.append(row)
    return visible


def _audit(
    db: Session,
    entry: FactorLibraryEntry,
    action: str,
    ctx: OrgContext,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    db.add(
        FactorLibraryAudit(
            id=uuid4(),
            entry_id=entry.id,
            action=action,
            actor_user_id=ctx.user.id,
            organization_id=ctx.organization_id,
            payload=payload or {},
        )
    )


@router.get("/sources")
def list_sources(_: OrgContext = Depends(require_org_context)) -> Dict[str, Any]:
    return {"sources": list(SOURCE_REGISTRY)}


@router.get("/match")
def match_get(
    library_class: str = Query(...),
    geography: str = Query(...),
    activity_key: str = Query(...),
    reporting_year: int = Query(...),
    unit: str = Query(""),
    currency_code: str = Query(""),
    price_year: Optional[int] = Query(None),
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return _match(
        MatchRequest(
            library_class=library_class,
            geography=geography,
            activity_key=activity_key,
            reporting_year=reporting_year,
            unit=unit,
            currency_code=currency_code,
            price_year=price_year,
        ),
        ctx,
        db,
    )


@router.post("/match")
def match_post(
    body: MatchRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return _match(body, ctx, db)


def _match(body: MatchRequest, ctx: OrgContext, db: Session) -> Dict[str, Any]:
    query = MatchQuery(
        library_class=body.library_class,
        geography=body.geography,
        activity_key=body.activity_key,
        reporting_year=body.reporting_year,
        unit=body.unit,
        currency_code=body.currency_code,
        price_year=body.price_year,
    )
    if not _library_ready(db):
        return {
            "status": NO_FACTOR,
            "message": "No verified factor available for this country, activity, and year.",
            "factors": [],
            "silent_substitution": False,
        }
    catalog = [entry_to_factor(row) for row in _visible_entries(db, ctx)]
    result = match_factors(query, catalog)
    return {
        "status": result.status,
        "message": result.message,
        "factors": [item.snapshot() for item in result.factors],
        "silent_substitution": False,
    }


@router.post("/manual-submissions")
def submit_manual(
    body: ManualFactorSubmit,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _require_library(db)
    if ctx.organization_id is None:
        raise HTTPException(status_code=403, detail="Organization membership is required")
    numerator, denominator = split_unit(body.unit)
    entry = FactorLibraryEntry(
        id=uuid4(),
        publication_id=uuid4(),
        category=body.category,
        library_class=body.library_class,
        country_code=body.country_code or None,
        geography=body.geography,
        sector_or_activity=body.sector_or_activity,
        activity_key=body.activity_key,
        factor_value=body.factor_value,
        numerator_unit=numerator,
        denominator_unit=denominator,
        unit=body.unit,
        applicable_year=body.applicable_year,
        publication_year=body.publication_year,
        gas=body.gas,
        source_organization=body.source_organization,
        source_document=body.source_document or None,
        source_url=body.source_url or None,
        provenance=body.provenance or None,
        license_name=body.license_name or None,
        permitted_use=body.permitted_use or "pending_review",
        currency_code=body.currency_code or None,
        price_year=body.price_year,
        status="pending_review",
        submitted_by=ctx.user.id,
        submitted_rationale=body.rationale,
        organization_id=ctx.organization_id,
    )
    db.add(entry)
    db.flush()
    _audit(db, entry, "submit", ctx, {"rationale": body.rationale})
    db.commit()
    db.refresh(entry)
    return {"status": "pending_review", "entry": _entry_out(entry)}


@router.get("/pending")
def list_pending(
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _require_library(db)
    if not _is_admin(ctx):
        raise HTTPException(status_code=403, detail="Admin or owner role required")
    rows = (
        db.query(FactorLibraryEntry)
        .filter(
            FactorLibraryEntry.status == "pending_review",
            FactorLibraryEntry.organization_id == ctx.organization_id,
        )
        .all()
    )
    return {"entries": [_entry_out(row) for row in rows]}


@router.post("/{entry_id}/approve")
def approve_entry(
    entry_id: UUID,
    body: ReviewRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return _review(entry_id, "approved", body, ctx, db)


@router.post("/{entry_id}/reject")
def reject_entry(
    entry_id: UUID,
    body: ReviewRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return _review(entry_id, "rejected", body, ctx, db)


def _review(
    entry_id: UUID,
    next_status: str,
    body: ReviewRequest,
    ctx: OrgContext,
    db: Session,
) -> Dict[str, Any]:
    _require_library(db)
    if not _is_admin(ctx):
        raise HTTPException(status_code=403, detail="Admin or owner role required")
    entry = db.query(FactorLibraryEntry).filter(FactorLibraryEntry.id == entry_id).first()
    if entry is None:
        raise HTTPException(status_code=404, detail="Factor submission not found")
    if entry.organization_id != ctx.organization_id:
        raise HTTPException(status_code=403, detail="Organization isolation: this submission belongs to another organization")
    if entry.status != "pending_review":
        raise HTTPException(status_code=409, detail="Only pending submissions can be reviewed")
    entry.status = next_status
    entry.reviewed_by = ctx.user.id
    entry.reviewed_at = datetime.now(timezone.utc)
    entry.review_notes = body.notes or None
    if next_status == "approved" and body.publish_global:
        raise HTTPException(
            status_code=403,
            detail="Global publication is not enabled in this phase. Organization-scoped approval only.",
        )
    db.flush()
    _audit(db, entry, next_status, ctx, {"notes": body.notes})
    db.commit()
    db.refresh(entry)
    return {"status": next_status, "entry": _entry_out(entry)}


@router.get("/preview-catalog")
def preview_catalog(
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Read-only preview of verified catalog rows. Does not insert or approve."""
    if not _is_admin(ctx):
        raise HTTPException(status_code=403, detail="Admin or owner role required")
    if not table_exists(db, "ref", "factor_rows"):
        return {"candidates": [], "message": "Factor catalog tables are not available."}
    rows = db.query(FactorRow).all()
    datasets = {item.id: item for item in db.query(FactorDataset).all()}
    candidates = []
    for row in rows:
        attrs = row.attributes or {}
        if str(attrs.get("verification") or "").lower() != "verified":
            continue
        if row.kg_co2e is None:
            continue
        dataset = datasets.get(row.dataset_id)
        country = str(attrs.get("country") or "")
        year = attrs.get("reporting_year") or attrs.get("publication_year")
        candidates.append(
            {
                "factor_row_id": str(row.id),
                "dataset_code": dataset.code if dataset else None,
                "dataset_version": dataset.version_label if dataset else None,
                "label": row.label,
                "geography": country,
                "applicable_year": year,
                "unit": row.unit,
                "factor_value": float(row.kg_co2e),
                "source_organization": dataset.publisher if dataset else None,
                "status": "preview_only",
                "auto_approved": False,
            }
        )
    return {"candidates": candidates, "auto_approved": False}
