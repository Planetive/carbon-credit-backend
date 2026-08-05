"""Shared /api/v1 dependencies."""

from __future__ import annotations

import os
import secrets
import uuid
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
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


def require_platform_admin(
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
) -> None:
    """
    Platform admin gate for cross-user ESG admin screens.
    Set ADMIN_API_KEY (preferred) or ADMIN_PASSWORD on the backend.
    """
    expected = (
        os.environ.get("ADMIN_API_KEY") or os.environ.get("ADMIN_PASSWORD") or ""
    ).strip()
    provided = (x_admin_key or "").strip()
    if not expected or not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing admin key",
        )


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
