"""UoP vs general-purpose overlap review API (PCAF §5.7 pp.107–108)."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth_org import OrgContext
from ..db import get_db
from .deps import require_org_context
from ..uop_overlap_review import (
    create_overlap_review,
    decide_overlap_review,
    list_overlap_candidates,
    list_overlap_reviews,
)

router = APIRouter(prefix="/uop/overlap-reviews", tags=["uop-overlap-reviews"])


class OverlapReviewCreate(BaseModel):
    uop_financing_instance_id: str
    reporting_year: str
    general_purpose_financing_instance_id: Optional[str] = None
    counterparty_id: Optional[uuid.UUID] = None
    issuer_name: Optional[str] = None
    documented_allocation_notes: Optional[str] = None
    evidence_reference: Optional[str] = None
    uop_outstanding_adjustment: Optional[float] = None
    general_purpose_outstanding_adjustment: Optional[float] = None
    adjustment_basis: Optional[str] = None


class OverlapReviewDecision(BaseModel):
    decision: str = Field(..., description="approved | rejected | cancelled")
    review_notes: Optional[str] = None


@router.get("/candidates")
def get_overlap_candidates(
    uop_financing_instance_id: str,
    reporting_year: str,
    counterparty_id: Optional[uuid.UUID] = None,
    issuer_name: Optional[str] = None,
    db: Session = Depends(get_db),
    ctx: OrgContext = Depends(require_org_context),
) -> Dict[str, Any]:
    items = list_overlap_candidates(
        db,
        organization_id=ctx.organization_id,
        counterparty_id=counterparty_id,
        reporting_year=reporting_year,
        financing_instance_id=uop_financing_instance_id,
        issuer_name=issuer_name,
    )
    reviews = list_overlap_reviews(
        db,
        organization_id=ctx.organization_id,
        financing_instance_id=uop_financing_instance_id,
        reporting_year=reporting_year,
    )
    return {"items": items, "reviews": reviews}


@router.get("")
def get_overlap_reviews(
    uop_financing_instance_id: Optional[str] = None,
    reporting_year: Optional[str] = None,
    db: Session = Depends(get_db),
    ctx: OrgContext = Depends(require_org_context),
) -> Dict[str, Any]:
    rows = list_overlap_reviews(
        db,
        organization_id=ctx.organization_id,
        financing_instance_id=uop_financing_instance_id,
        reporting_year=reporting_year,
    )
    return {"reviews": rows}


@router.post("")
def post_overlap_review(
    body: OverlapReviewCreate,
    db: Session = Depends(get_db),
    ctx: OrgContext = Depends(require_org_context),
) -> Dict[str, Any]:
    return create_overlap_review(
        db,
        organization_id=ctx.organization_id,
        payload=body.model_dump(),
        created_by=ctx.user.id if ctx.user else None,
    )


@router.post("/{review_id}/decision")
def post_overlap_decision(
    review_id: uuid.UUID,
    body: OverlapReviewDecision,
    db: Session = Depends(get_db),
    ctx: OrgContext = Depends(require_org_context),
) -> Dict[str, Any]:
    return decide_overlap_review(
        db,
        organization_id=ctx.organization_id,
        review_id=review_id,
        decision=body.decision,
        reviewer_user_id=ctx.user.id if ctx.user else None,
        review_notes=body.review_notes,
    )
