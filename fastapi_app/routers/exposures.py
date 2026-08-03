"""Exposure CRUD under /api/v1/exposures (org-scoped)."""

from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth_org import OrgContext
from ..db import get_db
from ..portfolio_models import Counterparty, Exposure
from ..schemas_v1 import ExposureCreate, ExposureOut, ExposureUpdate, MessageOut
from .deps import require_org_context

router = APIRouter(prefix="/exposures", tags=["exposures"])


def _get_org_exposure(
    db: Session, organization_id: uuid.UUID, exposure_pk: uuid.UUID
) -> Exposure:
    row = (
        db.query(Exposure)
        .filter(
            Exposure.id == exposure_pk,
            Exposure.organization_id == organization_id,
        )
        .first()
    )
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Exposure not found",
        )
    return row


def _require_org_counterparty(
    db: Session, organization_id: uuid.UUID, counterparty_id: uuid.UUID
) -> Counterparty:
    cp = (
        db.query(Counterparty)
        .filter(
            Counterparty.id == counterparty_id,
            Counterparty.organization_id == organization_id,
        )
        .first()
    )
    if not cp:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="counterparty_id does not belong to the current organization",
        )
    return cp


@router.get("", response_model=List[ExposureOut])
def list_exposures(
    counterparty_id: Optional[uuid.UUID] = None,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> List[Exposure]:
    q = db.query(Exposure).filter(Exposure.organization_id == ctx.organization_id)
    if counterparty_id is not None:
        q = q.filter(Exposure.counterparty_id == counterparty_id)
    return q.order_by(Exposure.created_at.asc()).all()


@router.post("", response_model=ExposureOut, status_code=status.HTTP_201_CREATED)
def create_exposure(
    body: ExposureCreate,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Exposure:
    _require_org_counterparty(db, ctx.organization_id, body.counterparty_id)
    exp = Exposure(
        user_id=ctx.user.id,
        organization_id=ctx.organization_id,
        counterparty_id=body.counterparty_id,
        exposure_id=body.exposure_id.strip(),
        amount_pkr=body.amount_pkr,
        probability_of_default=body.probability_of_default,
        loss_given_default=body.loss_given_default,
        tenor_months=body.tenor_months,
    )
    db.add(exp)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Could not create exposure: {exc.orig}",
        ) from exc
    db.refresh(exp)
    return exp


@router.get("/{exposure_id}", response_model=ExposureOut)
def get_exposure(
    exposure_id: uuid.UUID,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Exposure:
    return _get_org_exposure(db, ctx.organization_id, exposure_id)


@router.patch("/{exposure_id}", response_model=ExposureOut)
def patch_exposure(
    exposure_id: uuid.UUID,
    body: ExposureUpdate,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Exposure:
    exp = _get_org_exposure(db, ctx.organization_id, exposure_id)
    data = body.model_dump(exclude_unset=True)
    if "exposure_id" in data and data["exposure_id"] is not None:
        data["exposure_id"] = data["exposure_id"].strip()
    for key, value in data.items():
        setattr(exp, key, value)
    db.add(exp)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Could not update exposure: {exc.orig}",
        ) from exc
    db.refresh(exp)
    return exp


@router.delete("/{exposure_id}", response_model=MessageOut)
def delete_exposure(
    exposure_id: uuid.UUID,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> MessageOut:
    exp = _get_org_exposure(db, ctx.organization_id, exposure_id)
    db.delete(exp)
    db.commit()
    return MessageOut(status="ok", message="Exposure deleted")
