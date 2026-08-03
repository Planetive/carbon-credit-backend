"""Shared /api/v1 dependencies."""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..auth_models import UserOrganization
from ..auth_org import OrgContext, get_current_org_context
from ..db import get_db

ADMIN_ROLES = frozenset({"admin", "owner"})


def require_org_context(
    ctx: OrgContext = Depends(get_current_org_context),
) -> OrgContext:
    if ctx.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No organization context; join or create an organization first",
        )
    return ctx


def get_membership(
    db: Session,
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
) -> Optional[UserOrganization]:
    return (
        db.query(UserOrganization)
        .filter(
            UserOrganization.user_id == user_id,
            UserOrganization.organization_id == organization_id,
        )
        .first()
    )


def require_org_member(
    organization_id: uuid.UUID,
    ctx: OrgContext = Depends(get_current_org_context),
    db: Session = Depends(get_db),
) -> UserOrganization:
    membership = get_membership(db, ctx.user.id, organization_id)
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this organization",
        )
    return membership


def require_org_admin(
    organization_id: uuid.UUID,
    ctx: OrgContext = Depends(get_current_org_context),
    db: Session = Depends(get_db),
) -> UserOrganization:
    membership = require_org_member(organization_id, ctx, db)
    if (membership.role or "").lower() not in ADMIN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin or owner role required",
        )
    return membership
