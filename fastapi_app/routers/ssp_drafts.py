"""Org-scoped SSP (PCAF §5.8) draft persistence. No formulas. No financed_emissions writes."""

from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from ..auth_org import OrgContext
from ..db import get_db
from ..schemas_v1 import MessageOut
from ..ssp_drafts import (
    delete_ssp_draft,
    get_ssp_draft,
    get_ssp_draft_by_instance,
    list_ssp_drafts,
    patch_ssp_draft,
    upsert_ssp_draft,
)
from ..ssp_schemas import SspDraftPatch, SspDraftRecord, SspDraftUpsert
from .deps import require_org_context

router = APIRouter(prefix="/ssp/drafts", tags=["ssp-drafts"])


@router.get("", response_model=List[SspDraftRecord])
def list_drafts(
    counterparty_id: Optional[uuid.UUID] = None,
    deal_id: Optional[uuid.UUID] = None,
    financing_instance_id: Optional[str] = Query(default=None),
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> List[SspDraftRecord]:
    return list_ssp_drafts(
        db,
        organization_id=ctx.organization_id,
        counterparty_id=counterparty_id,
        deal_id=deal_id,
        financing_instance_id=financing_instance_id,
    )


@router.put("", response_model=SspDraftRecord)
def put_draft(
    body: SspDraftUpsert,
    response: Response,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> SspDraftRecord:
    record = upsert_ssp_draft(
        db,
        organization_id=ctx.organization_id,
        user_id=ctx.user.id,
        body=body,
    )
    response.status_code = (
        status.HTTP_201_CREATED if record.created else status.HTTP_200_OK
    )
    return record


@router.get("/by-instance/{financing_instance_id}", response_model=SspDraftRecord)
def get_draft_by_instance(
    financing_instance_id: str,
    counterparty_id: Optional[uuid.UUID] = None,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> SspDraftRecord:
    return get_ssp_draft_by_instance(
        db,
        organization_id=ctx.organization_id,
        financing_instance_id=financing_instance_id,
        counterparty_id=counterparty_id,
    )


@router.get("/{holding_id}", response_model=SspDraftRecord)
def get_draft(
    holding_id: uuid.UUID,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> SspDraftRecord:
    return get_ssp_draft(db, ctx.organization_id, holding_id)


@router.patch("/{holding_id}", response_model=SspDraftRecord)
def patch_draft(
    holding_id: uuid.UUID,
    body: SspDraftPatch,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> SspDraftRecord:
    return patch_ssp_draft(
        db,
        organization_id=ctx.organization_id,
        user_id=ctx.user.id,
        holding_id=holding_id,
        body=body,
    )


@router.delete("/{holding_id}", response_model=MessageOut)
def remove_draft(
    holding_id: uuid.UUID,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> MessageOut:
    delete_ssp_draft(db, ctx.organization_id, holding_id)
    return MessageOut(status="ok", message="SSP draft deleted")
