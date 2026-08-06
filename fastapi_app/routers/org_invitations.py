"""Organization invitations + members under /api/v1/organizations/{org_id}/..."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..auth_org import OrgContext, get_current_org_context
from ..db import get_db
from ..org_permissions import generate_invitation_token, get_default_permissions
from .deps import require_can_invite, require_org_member

router = APIRouter(prefix="/organizations", tags=["organization-invitations"])

OrgRole = Literal["admin", "user", "editor", "viewer"]


class InvitationCreate(BaseModel):
    email: str = Field(min_length=1)
    role: OrgRole = "viewer"
    permissions: Optional[Dict[str, Any]] = None


class InvitationOut(BaseModel):
    id: str
    email: str
    role: str
    token: str
    expires_at: Optional[str] = None
    status: str
    organization_id: str
    invited_by: Optional[str] = None
    created_at: Optional[str] = None
    permissions: Optional[Dict[str, Any]] = None


class MemberOut(BaseModel):
    id: str
    user_id: str
    organization_id: str
    role: str
    permissions: Dict[str, Any] = Field(default_factory=dict)
    status: Optional[str] = None
    joined_at: Optional[str] = None
    invited_by: Optional[str] = None
    invited_at: Optional[str] = None
    email: Optional[str] = None
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None


def _as_str(value: Any) -> Optional[str]:
    return str(value) if value is not None else None


def _perms(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return dict(value)


def _invitation_out(row: Dict[str, Any]) -> InvitationOut:
    return InvitationOut(
        id=str(row["id"]),
        email=str(row["email"]),
        role=str(row["role"]),
        token=str(row["token"]),
        expires_at=_as_str(row.get("expires_at")),
        status=str(row.get("status") or "pending"),
        organization_id=str(row["organization_id"]),
        invited_by=_as_str(row.get("invited_by")),
        created_at=_as_str(row.get("created_at")),
        permissions=_perms(row.get("permissions")),
    )


@router.post(
    "/{organization_id}/invitations",
    response_model=InvitationOut,
    status_code=status.HTTP_201_CREATED,
)
def create_invitation(
    organization_id: uuid.UUID,
    body: InvitationCreate,
    membership=Depends(require_can_invite),
    ctx: OrgContext = Depends(get_current_org_context),
    db: Session = Depends(get_db),
) -> InvitationOut:
    _ = membership
    email = body.email.strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=422, detail="Invalid email")

    permissions = body.permissions if body.permissions is not None else get_default_permissions(
        body.role
    )
    token = generate_invitation_token()
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    new_id = str(uuid.uuid4())

    db.execute(
        text(
            """
            INSERT INTO public.organization_invitations (
              id, email, organization_id, role, permissions, token,
              invited_by, expires_at, status, created_at
            ) VALUES (
              :id, :email, :organization_id, :role, CAST(:permissions AS jsonb), :token,
              :invited_by, :expires_at, 'pending', now()
            )
            """
        ),
        {
            "id": new_id,
            "email": email,
            "organization_id": str(organization_id),
            "role": body.role,
            "permissions": json.dumps(permissions),
            "token": token,
            "invited_by": str(ctx.user.id),
            "expires_at": expires_at,
        },
    )
    db.commit()
    row = (
        db.execute(
            text("SELECT * FROM public.organization_invitations WHERE id = :id"),
            {"id": new_id},
        )
        .mappings()
        .first()
    )
    return _invitation_out(dict(row))


@router.get("/{organization_id}/invitations", response_model=List[InvitationOut])
def list_invitations(
    organization_id: uuid.UUID,
    status_filter: Optional[str] = Query(default="pending", alias="status"),
    membership=Depends(require_can_invite),
    db: Session = Depends(get_db),
) -> List[InvitationOut]:
    _ = membership
    sql = """
        SELECT * FROM public.organization_invitations
        WHERE organization_id = :organization_id
    """
    params: Dict[str, Any] = {"organization_id": str(organization_id)}
    if status_filter:
        sql += " AND status = :status"
        params["status"] = status_filter
    sql += " ORDER BY created_at DESC NULLS LAST"
    rows = db.execute(text(sql), params).mappings().all()
    return [_invitation_out(dict(r)) for r in rows]


@router.get("/{organization_id}/members", response_model=List[MemberOut])
def list_members(
    organization_id: uuid.UUID,
    membership=Depends(require_org_member),
    db: Session = Depends(get_db),
) -> List[MemberOut]:
    _ = membership
    rows = (
        db.execute(
            text(
                """
                SELECT
                  uo.id,
                  uo.user_id,
                  uo.organization_id,
                  uo.role,
                  uo.permissions,
                  uo.status,
                  uo.joined_at,
                  uo.invited_by,
                  uo.invited_at,
                  u.email AS user_email,
                  p.display_name
                FROM public.user_organizations uo
                LEFT JOIN public.users u ON u.id = uo.user_id
                LEFT JOIN public.profiles p ON p.user_id = uo.user_id
                WHERE uo.organization_id = :organization_id
                  AND COALESCE(uo.status, 'active') = 'active'
                ORDER BY uo.joined_at DESC NULLS LAST, uo.created_at DESC NULLS LAST
                """
            ),
            {"organization_id": str(organization_id)},
        )
        .mappings()
        .all()
    )
    out: List[MemberOut] = []
    for r in rows:
        out.append(
            MemberOut(
                id=str(r["id"]),
                user_id=str(r["user_id"]),
                organization_id=str(r["organization_id"]),
                role=str(r.get("role") or "viewer"),
                permissions=_perms(r.get("permissions")),
                status=r.get("status"),
                joined_at=_as_str(r.get("joined_at")),
                invited_by=_as_str(r.get("invited_by")),
                invited_at=_as_str(r.get("invited_at")),
                email=r.get("user_email"),
                display_name=r.get("display_name"),
                avatar_url=None,
            )
        )
    return out
