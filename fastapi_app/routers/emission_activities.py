"""CRUD for app.emission_activities (org-scoped; belongs to assessment)."""

from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth_org import OrgContext
from ..db import get_db
from ..ghg_models import EmissionActivity, EmissionAssessment
from ..schemas_v1 import (
    EmissionActivityCreate,
    EmissionActivityOut,
    EmissionActivityUpdate,
    MessageOut,
)
from .deps import require_org_context

router = APIRouter(prefix="/emission-activities", tags=["emission-activities"])


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
            detail="Emission assessment not found in current organization",
        )
    return row


def _get_org_activity(
    db: Session, organization_id: uuid.UUID, activity_id: uuid.UUID
) -> EmissionActivity:
    row = (
        db.query(EmissionActivity)
        .filter(
            EmissionActivity.id == activity_id,
            EmissionActivity.organization_id == organization_id,
        )
        .first()
    )
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Emission activity not found",
        )
    return row


@router.get("", response_model=List[EmissionActivityOut])
def list_activities(
    assessment_id: Optional[uuid.UUID] = None,
    scope: Optional[int] = Query(default=None, ge=1, le=3),
    category: Optional[str] = None,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> List[EmissionActivity]:
    q = db.query(EmissionActivity).filter(
        EmissionActivity.organization_id == ctx.organization_id
    )
    if assessment_id is not None:
        q = q.filter(EmissionActivity.assessment_id == assessment_id)
    if scope is not None:
        q = q.filter(EmissionActivity.scope == scope)
    if category:
        q = q.filter(EmissionActivity.category == category)
    return q.order_by(EmissionActivity.created_at.asc()).all()


@router.post("", response_model=EmissionActivityOut, status_code=status.HTTP_201_CREATED)
def create_activity(
    body: EmissionActivityCreate,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> EmissionActivity:
    _get_org_assessment(db, ctx.organization_id, body.assessment_id)
    row = EmissionActivity(
        assessment_id=body.assessment_id,
        organization_id=ctx.organization_id,
        user_id=ctx.user.id,
        scope=body.scope,
        category=body.category.strip(),
        method=body.method,
        counterparty_id=body.counterparty_id,
        quantity=body.quantity,
        unit=body.unit,
        factor_dataset_id=body.factor_dataset_id,
        factor_row_id=body.factor_row_id,
        emissions_tco2e=body.emissions_tco2e,
        raw=body.raw or {},
        legacy_source="api",
        legacy_id=None,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Could not create activity: {exc.orig}",
        ) from exc
    db.refresh(row)
    return row


@router.get("/{activity_id}", response_model=EmissionActivityOut)
def get_activity(
    activity_id: uuid.UUID,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> EmissionActivity:
    return _get_org_activity(db, ctx.organization_id, activity_id)


@router.patch("/{activity_id}", response_model=EmissionActivityOut)
def patch_activity(
    activity_id: uuid.UUID,
    body: EmissionActivityUpdate,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> EmissionActivity:
    row = _get_org_activity(db, ctx.organization_id, activity_id)
    data = body.model_dump(exclude_unset=True)
    if "category" in data and data["category"] is not None:
        data["category"] = data["category"].strip()
    for key, value in data.items():
        setattr(row, key, value)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/{activity_id}", response_model=MessageOut)
def delete_activity(
    activity_id: uuid.UUID,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> MessageOut:
    row = _get_org_activity(db, ctx.organization_id, activity_id)
    db.delete(row)
    db.commit()
    return MessageOut(status="ok", message="Emission activity deleted")
