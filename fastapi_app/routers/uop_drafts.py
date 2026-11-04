"""Org-scoped Use of Proceeds draft persistence. No formulas. No financed_emissions writes."""

from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from ..auth_org import OrgContext
from ..db import get_db
from ..schemas_v1 import MessageOut
from ..uop_drafts import (
    delete_uop_draft,
    get_uop_draft,
    get_uop_draft_by_instance,
    list_uop_drafts,
    patch_uop_draft,
    upsert_uop_draft,
)
from ..uop_schemas import UopDraftPatch, UopDraftRecord, UopDraftUpsert
from .deps import require_org_context

router = APIRouter(prefix="/uop/drafts", tags=["uop-drafts"])


@router.get("", response_model=List[UopDraftRecord])
def list_drafts(
    counterparty_id: Optional[uuid.UUID] = None,
    structure_id: Optional[uuid.UUID] = None,
    financing_instance_id: Optional[str] = Query(default=None),
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> List[UopDraftRecord]:
    return list_uop_drafts(
        db,
        organization_id=ctx.organization_id,
        counterparty_id=counterparty_id,
        structure_id=structure_id,
        financing_instance_id=financing_instance_id,
    )


@router.put("", response_model=UopDraftRecord)
def put_draft(
    body: UopDraftUpsert,
    response: Response,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> UopDraftRecord:
    record = upsert_uop_draft(
        db,
        organization_id=ctx.organization_id,
        user_id=ctx.user.id,
        body=body,
    )
    response.status_code = (
        status.HTTP_201_CREATED if record.created else status.HTTP_200_OK
    )
    return record


@router.get("/by-instance/{financing_instance_id}", response_model=UopDraftRecord)
def get_draft_by_instance(
    financing_instance_id: str,
    counterparty_id: Optional[uuid.UUID] = None,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> UopDraftRecord:
    return get_uop_draft_by_instance(
        db,
        organization_id=ctx.organization_id,
        financing_instance_id=financing_instance_id,
        counterparty_id=counterparty_id,
    )


@router.get("/{investment_id}", response_model=UopDraftRecord)
def get_draft(
    investment_id: uuid.UUID,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> UopDraftRecord:
    return get_uop_draft(db, ctx.organization_id, investment_id)


@router.patch("/{investment_id}", response_model=UopDraftRecord)
def patch_draft(
    investment_id: uuid.UUID,
    body: UopDraftPatch,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> UopDraftRecord:
    return patch_uop_draft(
        db,
        organization_id=ctx.organization_id,
        user_id=ctx.user.id,
        investment_id=investment_id,
        body=body,
    )


@router.delete("/{investment_id}", response_model=MessageOut)
def remove_draft(
    investment_id: uuid.UUID,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> MessageOut:
    delete_uop_draft(db, ctx.organization_id, investment_id)
    return MessageOut(status="ok", message="UoP draft deleted")
