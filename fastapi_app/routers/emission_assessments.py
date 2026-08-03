"""CRUD for app.emission_assessments (org-scoped)."""

from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth_org import OrgContext
from ..db import get_db
from ..ghg_models import EmissionAssessment
from ..schemas_v1 import (
    FRAMEWORKS,
    EmissionAssessmentCreate,
    EmissionAssessmentOut,
    EmissionAssessmentUpdate,
    MessageOut,
)
from .deps import require_org_context

router = APIRouter(prefix="/emission-assessments", tags=["emission-assessments"])


def _validate_framework(value: str) -> str:
    if value not in FRAMEWORKS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"framework must be one of: {list(FRAMEWORKS)}",
        )
    return value


def _get_org_assessment(
    db: Session, organization_id: uuid.UUID, assessment_id: uuid.UUID
) -> EmissionAssessment:
    row = (
        db.query(EmissionAssessment)
        .filter(
            EmissionAssessment.id == assessment_id,
            EmissionAssessment.organization_id == organization_id,
        )
        .first()
    )
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Emission assessment not found",
        )
    return row


@router.get("", response_model=List[EmissionAssessmentOut])
def list_assessments(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    framework: Optional[str] = None,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> List[EmissionAssessment]:
    q = db.query(EmissionAssessment).filter(
        EmissionAssessment.organization_id == ctx.organization_id
    )
    if status_filter:
        q = q.filter(EmissionAssessment.status == status_filter)
    if framework:
        q = q.filter(EmissionAssessment.framework == framework)
    return q.order_by(EmissionAssessment.created_at.desc()).all()


@router.post("", response_model=EmissionAssessmentOut, status_code=status.HTTP_201_CREATED)
def create_assessment(
    body: EmissionAssessmentCreate,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> EmissionAssessment:
    framework = _validate_framework(body.framework)
    row = EmissionAssessment(
        organization_id=ctx.organization_id,
        user_id=ctx.user.id,
        framework=framework,
        reporting_period=body.reporting_period,
        status=body.status,
        totals=body.totals or {},
        legacy_note=body.legacy_note,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Could not create assessment: {exc.orig}",
        ) from exc
    db.refresh(row)
    return row


@router.get("/{assessment_id}", response_model=EmissionAssessmentOut)
def get_assessment(
    assessment_id: uuid.UUID,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> EmissionAssessment:
    return _get_org_assessment(db, ctx.organization_id, assessment_id)


@router.patch("/{assessment_id}", response_model=EmissionAssessmentOut)
def patch_assessment(
    assessment_id: uuid.UUID,
    body: EmissionAssessmentUpdate,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> EmissionAssessment:
    row = _get_org_assessment(db, ctx.organization_id, assessment_id)
    data = body.model_dump(exclude_unset=True)
    if "framework" in data and data["framework"] is not None:
        data["framework"] = _validate_framework(data["framework"])
    for key, value in data.items():
        setattr(row, key, value)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/{assessment_id}", response_model=MessageOut)
def delete_assessment(
    assessment_id: uuid.UUID,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> MessageOut:
    row = _get_org_assessment(db, ctx.organization_id, assessment_id)
    db.delete(row)
    db.commit()
    return MessageOut(status="ok", message="Emission assessment deleted")
