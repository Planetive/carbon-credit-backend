"""
Organization context for authenticated users.

Preference order matches app-main Phase 1B backfill
(db/migrations/0003d_phase1b_backfill_fixed_user_id.sql):
  1) profiles.current_organization_id if that org is in user_organizations
  2) earliest admin/owner membership
  3) first membership (by created_at)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from .auth_deps import get_current_user
from .auth_models import Profile, User, UserOrganization
from .db import get_db


@dataclass(frozen=True)
class OrgContext:
    user: User
    organization_id: uuid.UUID | None
    role: str | None


def resolve_org_for_user(db: Session, user_id: uuid.UUID) -> tuple[uuid.UUID | None, str | None]:
    """
    Resolve (organization_id, role) for a user.
    Returns (None, None) when the user has no memberships.
    """
    profile = db.query(Profile).filter(Profile.user_id == user_id).first()
    preferred_org_id = profile.current_organization_id if profile else None

    if preferred_org_id is not None:
        membership = (
            db.query(UserOrganization)
            .filter(
                UserOrganization.user_id == user_id,
                UserOrganization.organization_id == preferred_org_id,
            )
            .first()
        )
        if membership is not None:
            return membership.organization_id, membership.role

    # Earliest admin/owner, else first membership (created_at ASC NULLS LAST)
    admin_rank = case(
        (func.lower(func.coalesce(UserOrganization.role, "")).in_(("admin", "owner")), 0),
        else_=1,
    )
    membership = (
        db.query(UserOrganization)
        .filter(UserOrganization.user_id == user_id)
        .order_by(admin_rank.asc(), UserOrganization.created_at.asc().nulls_last())
        .first()
    )
    if membership is None:
        return None, None
    return membership.organization_id, membership.role


def get_current_org_context(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrgContext:
    organization_id, role = resolve_org_for_user(db, current_user.id)
    return OrgContext(
        user=current_user,
        organization_id=organization_id,
        role=role,
    )
