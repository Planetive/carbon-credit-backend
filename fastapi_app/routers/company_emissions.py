"""Company emissions GET/PATCH under /api/v1/company-emissions (org-scoped)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..auth_org import OrgContext
from ..db import get_db
from ..portfolio_models import CompanyEmission, Counterparty
from ..schemas_v1 import CompanyEmissionOut, CompanyEmissionUpdate
from .deps import require_org_context

router = APIRouter(prefix="/company-emissions", tags=["company-emissions"])


def _org_scoped_query(db: Session, organization_id: uuid.UUID, user_id: uuid.UUID):
    """
    company_emissions has no organization_id.
    Scope company rows via counterparty.organization_id;
    scope bank rows (counterparty_id IS NULL) to the current user within the org context.
    """
    return (
        db.query(CompanyEmission)
        .outerjoin(Counterparty, Counterparty.id == CompanyEmission.counterparty_id)
        .filter(
            (
                (CompanyEmission.counterparty_id.isnot(None))
                & (Counterparty.organization_id == organization_id)
            )
            | (
                (CompanyEmission.counterparty_id.is_(None))
                & (CompanyEmission.user_id == user_id)
                & (CompanyEmission.is_bank_emissions.is_(True))
            )
        )
    )


@router.get("", response_model=List[CompanyEmissionOut])
def list_company_emissions(
    counterparty_id: Optional[uuid.UUID] = None,
    status_filter: Optional[str] = Query(default="active", alias="status"),
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> List[CompanyEmission]:
    q = _org_scoped_query(db, ctx.organization_id, ctx.user.id)
    if counterparty_id is not None:
        q = q.filter(CompanyEmission.counterparty_id == counterparty_id)
    if status_filter:
        q = q.filter(CompanyEmission.status == status_filter)
    return q.order_by(CompanyEmission.updated_at.desc().nullslast()).all()


@router.get("/{emission_id}", response_model=CompanyEmissionOut)
def get_company_emission(
    emission_id: uuid.UUID,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> CompanyEmission:
    row = (
        _org_scoped_query(db, ctx.organization_id, ctx.user.id)
        .filter(CompanyEmission.id == emission_id)
        .first()
    )
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company emission not found",
        )
    return row


@router.patch("/{emission_id}", response_model=CompanyEmissionOut)
def patch_company_emission(
    emission_id: uuid.UUID,
    body: CompanyEmissionUpdate,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> CompanyEmission:
    row = (
        _org_scoped_query(db, ctx.organization_id, ctx.user.id)
        .filter(CompanyEmission.id == emission_id)
        .first()
    )
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company emission not found",
        )

    data = body.model_dump(exclude_unset=True)
    if "status" in data and data["status"] is not None:
        if data["status"] not in ("active", "archived"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="status must be 'active' or 'archived'",
            )
    if "calculation_source" in data and data["calculation_source"] is not None:
        allowed = {"emission_calculator", "questionnaire", "manual"}
        if data["calculation_source"] not in allowed:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"calculation_source must be one of: {sorted(allowed)}",
            )

    for key, value in data.items():
        setattr(row, key, value)

    # Keep total in sync when any scope changes
    s1 = row.scope1_emissions if row.scope1_emissions is not None else Decimal("0")
    s2 = row.scope2_emissions if row.scope2_emissions is not None else Decimal("0")
    s3 = row.scope3_emissions if row.scope3_emissions is not None else Decimal("0")
    row.total_emissions = s1 + s2 + s3

    db.add(row)
    db.commit()
    db.refresh(row)
    return row
