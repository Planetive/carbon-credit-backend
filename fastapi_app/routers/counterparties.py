"""Counterparty CRUD under /api/v1/counterparties (org-scoped)."""

from __future__ import annotations

import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth_org import OrgContext
from ..db import get_db
from ..portfolio_models import Counterparty, Exposure
from ..schemas_v1 import (
    COUNTERPARTY_TYPES,
    CounterpartyCreate,
    CounterpartyOut,
    CounterpartyUpdate,
    MessageOut,
)
from .deps import require_org_context

router = APIRouter(prefix="/counterparties", tags=["counterparties"])


def _validate_type(value: str) -> str:
    if value not in COUNTERPARTY_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"counterparty_type must be one of: {list(COUNTERPARTY_TYPES)}",
        )
    return value


def _get_org_counterparty(
    db: Session, organization_id: uuid.UUID, counterparty_id: uuid.UUID
) -> Counterparty:
    row = (
        db.query(Counterparty)
        .filter(
            Counterparty.id == counterparty_id,
            Counterparty.organization_id == organization_id,
        )
        .first()
    )
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Counterparty not found",
        )
    return row


@router.get("", response_model=List[CounterpartyOut])
def list_counterparties(
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> List[Counterparty]:
    return (
        db.query(Counterparty)
        .filter(Counterparty.organization_id == ctx.organization_id)
        .order_by(Counterparty.name.asc())
        .all()
    )


@router.post("", response_model=CounterpartyOut, status_code=status.HTTP_201_CREATED)
def create_counterparty(
    body: CounterpartyCreate,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Counterparty:
    cp_type = _validate_type(body.counterparty_type)
    cp = Counterparty(
        user_id=ctx.user.id,
        organization_id=ctx.organization_id,
        name=body.name.strip(),
        sector=body.sector.strip(),
        geography=body.geography.strip(),
        counterparty_type=cp_type,
    )
    db.add(cp)
    db.flush()

    if body.exposure is not None:
        exp = Exposure(
            user_id=ctx.user.id,
            organization_id=ctx.organization_id,
            counterparty_id=cp.id,
            exposure_id=body.exposure.exposure_id.strip(),
            amount_pkr=body.exposure.amount_pkr,
            probability_of_default=body.exposure.probability_of_default,
            loss_given_default=body.exposure.loss_given_default,
            tenor_months=body.exposure.tenor_months,
        )
        db.add(exp)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Could not create counterparty: {exc.orig}",
        ) from exc

    db.refresh(cp)
    return cp


@router.get("/{counterparty_id}", response_model=CounterpartyOut)
def get_counterparty(
    counterparty_id: uuid.UUID,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Counterparty:
    return _get_org_counterparty(db, ctx.organization_id, counterparty_id)


@router.patch("/{counterparty_id}", response_model=CounterpartyOut)
def patch_counterparty(
    counterparty_id: uuid.UUID,
    body: CounterpartyUpdate,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Counterparty:
    cp = _get_org_counterparty(db, ctx.organization_id, counterparty_id)
    data = body.model_dump(exclude_unset=True)
    if "counterparty_type" in data and data["counterparty_type"] is not None:
        data["counterparty_type"] = _validate_type(data["counterparty_type"])
    for key in ("name", "sector", "geography"):
        if key in data and data[key] is not None:
            data[key] = data[key].strip()
    for key, value in data.items():
        setattr(cp, key, value)
    db.add(cp)
    db.commit()
    db.refresh(cp)
    return cp


@router.delete("/{counterparty_id}", response_model=MessageOut)
def delete_counterparty(
    counterparty_id: uuid.UUID,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> MessageOut:
    cp = _get_org_counterparty(db, ctx.organization_id, counterparty_id)
    db.delete(cp)
    db.commit()
    return MessageOut(status="ok", message="Counterparty deleted")
