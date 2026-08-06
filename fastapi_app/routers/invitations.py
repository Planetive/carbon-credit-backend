"""Invitation accept + public peek under /api/v1/invitations."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..auth_deps import get_current_user
from ..auth_models import User
from ..db import get_db

router = APIRouter(prefix="/invitations", tags=["invitations"])


class AcceptInvitationBody(BaseModel):
    token: str = Field(min_length=1)


class AcceptInvitationOut(BaseModel):
    success: bool
    message: str
    organization_id: Optional[str] = None


class InvitationPeekOut(BaseModel):
    id: str
    email: str
    organization_id: str
    organization_name: Optional[str] = None
    role: str
    expires_at: Optional[str] = None
    status: str
    invited_by: Optional[str] = None
    inviter_name: Optional[str] = None


def _as_str(value: Any) -> Optional[str]:
    return str(value) if value is not None else None


def _load_invitation_by_token(db: Session, token: str) -> Optional[Dict[str, Any]]:
    row = (
        db.execute(
            text(
                """
                SELECT
                  i.*,
                  o.name AS organization_name,
                  p.display_name AS inviter_name
                FROM public.organization_invitations i
                LEFT JOIN public.organizations o ON o.id = i.organization_id
                LEFT JOIN public.profiles p ON p.user_id = i.invited_by
                WHERE i.token = :token
                LIMIT 1
                """
            ),
            {"token": token},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


@router.get("/by-token/{token}", response_model=InvitationPeekOut)
def peek_invitation_by_token(
    token: str,
    db: Session = Depends(get_db),
) -> InvitationPeekOut:
    """Public peek for AcceptInvitationScreen (no JWT required)."""
    row = _load_invitation_by_token(db, token)
    if not row:
        raise HTTPException(status_code=404, detail="Invitation not found")
    return InvitationPeekOut(
        id=str(row["id"]),
        email=str(row["email"]),
        organization_id=str(row["organization_id"]),
        organization_name=row.get("organization_name"),
        role=str(row.get("role") or "viewer"),
        expires_at=_as_str(row.get("expires_at")),
        status=str(row.get("status") or "pending"),
        invited_by=_as_str(row.get("invited_by")),
        inviter_name=row.get("inviter_name") or "Team",
    )


@router.post("/accept", response_model=AcceptInvitationOut)
def accept_invitation(
    body: AcceptInvitationBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AcceptInvitationOut:
    """
    Accept a pending invitation for the authenticated user.
    Invite email must match JWT user email (case-insensitive).
    """
    token = body.token.strip()
    row = _load_invitation_by_token(db, token)
    if not row:
        return AcceptInvitationOut(
            success=False, message="Invalid or expired invitation", organization_id=None
        )

    if str(row.get("status") or "") != "pending":
        return AcceptInvitationOut(
            success=False,
            message="This invitation is no longer valid",
            organization_id=None,
        )

    expires_at = row.get("expires_at")
    if expires_at is not None:
        if getattr(expires_at, "tzinfo", None) is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < datetime.now(timezone.utc):
            return AcceptInvitationOut(
                success=False, message="This invitation has expired", organization_id=None
            )

    invite_email = str(row.get("email") or "").strip().lower()
    user_email = str(user.email or "").strip().lower()
    if not invite_email or invite_email != user_email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invitation email does not match the authenticated user",
        )

    org_id = str(row["organization_id"])
    perms = row.get("permissions")
    if isinstance(perms, dict):
        perms_json = json.dumps(perms)
    elif perms is None:
        perms_json = "{}"
    else:
        perms_json = json.dumps(perms) if not isinstance(perms, str) else perms

    membership_id = str(uuid.uuid4())
    db.execute(
        text(
            """
            INSERT INTO public.user_organizations (
              id, user_id, organization_id, role, permissions,
              invited_by, invited_at, joined_at, status, created_at
            ) VALUES (
              :id, :user_id, :organization_id, :role, CAST(:permissions AS jsonb),
              :invited_by, :invited_at, now(), 'active', now()
            )
            ON CONFLICT (user_id, organization_id) DO UPDATE SET
              role = EXCLUDED.role,
              permissions = EXCLUDED.permissions,
              status = 'active',
              joined_at = now()
            """
        ),
        {
            "id": membership_id,
            "user_id": str(user.id),
            "organization_id": org_id,
            "role": row.get("role") or "viewer",
            "permissions": perms_json,
            "invited_by": str(row["invited_by"]) if row.get("invited_by") else None,
            "invited_at": row.get("created_at"),
        },
    )

    db.execute(
        text(
            """
            UPDATE public.organization_invitations
            SET status = 'accepted',
                accepted_at = now(),
                accepted_by = :user_id
            WHERE id = :id
            """
        ),
        {"id": str(row["id"]), "user_id": str(user.id)},
    )

    db.execute(
        text(
            """
            UPDATE public.profiles
            SET current_organization_id = :organization_id,
                updated_at = now()
            WHERE user_id = :user_id
              AND current_organization_id IS NULL
            """
        ),
        {"organization_id": org_id, "user_id": str(user.id)},
    )

    db.commit()
    return AcceptInvitationOut(
        success=True,
        message="Invitation accepted successfully",
        organization_id=org_id,
    )
