"""Organization endpoints under /api/v1/organizations."""

from __future__ import annotations

import uuid

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth_models import Profile, UserOrganization
from ..auth_org import OrgContext, get_current_org_context
from ..db import get_db
from ..portfolio_models import Organization
from ..schemas_v1 import OrganizationCreate, OrganizationOut, OrganizationUpdate
from .deps import get_membership, require_org_admin, require_org_member

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("", response_model=List[OrganizationOut])
def list_organizations(
    ctx: OrgContext = Depends(get_current_org_context),
    db: Session = Depends(get_db),
) -> List[OrganizationOut]:
    rows = (
        db.query(Organization, UserOrganization.role)
        .join(
            UserOrganization,
            UserOrganization.organization_id == Organization.id,
        )
        .filter(UserOrganization.user_id == ctx.user.id)
        .order_by(Organization.name.asc())
        .all()
    )
    return [
        OrganizationOut(
            id=org.id,
            name=org.name,
            description=org.description,
            parent_organization_id=org.parent_organization_id,
            is_original=org.is_original,
            is_active=org.is_active,
            created_by=org.created_by,
            created_at=org.created_at,
            updated_at=org.updated_at,
            role=role,
        )
        for org, role in rows
    ]


@router.post("", response_model=OrganizationOut, status_code=status.HTTP_201_CREATED)
def create_organization(
    body: OrganizationCreate,
    ctx: OrgContext = Depends(get_current_org_context),
    db: Session = Depends(get_db),
) -> OrganizationOut:
    if body.parent_organization_id is not None:
        parent_membership = get_membership(
            db, ctx.user.id, body.parent_organization_id
        )
        if parent_membership is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not a member of the parent organization",
            )

    org = Organization(
        name=body.name.strip(),
        description=body.description,
        parent_organization_id=body.parent_organization_id,
        created_by=ctx.user.id,
        is_original=bool(body.is_original),
        is_active=True,
    )
    db.add(org)
    db.flush()

    membership = UserOrganization(
        user_id=ctx.user.id,
        organization_id=org.id,
        role="admin",
        status="active",
    )
    db.add(membership)

    profile = db.query(Profile).filter(Profile.user_id == ctx.user.id).first()
    if profile is not None:
        profile.current_organization_id = org.id
        db.add(profile)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Could not create organization: {exc.orig}",
        ) from exc

    db.refresh(org)
    return OrganizationOut(
        id=org.id,
        name=org.name,
        description=org.description,
        parent_organization_id=org.parent_organization_id,
        is_original=org.is_original,
        is_active=org.is_active,
        created_by=org.created_by,
        created_at=org.created_at,
        updated_at=org.updated_at,
        role="admin",
    )


@router.get("/{organization_id}", response_model=OrganizationOut)
def get_organization(
    organization_id: uuid.UUID,
    membership: UserOrganization = Depends(require_org_member),
    db: Session = Depends(get_db),
) -> OrganizationOut:
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )
    return OrganizationOut(
        id=org.id,
        name=org.name,
        description=org.description,
        parent_organization_id=org.parent_organization_id,
        is_original=org.is_original,
        is_active=org.is_active,
        created_by=org.created_by,
        created_at=org.created_at,
        updated_at=org.updated_at,
        role=membership.role,
    )


@router.patch("/{organization_id}", response_model=OrganizationOut)
def patch_organization(
    organization_id: uuid.UUID,
    body: OrganizationUpdate,
    membership: UserOrganization = Depends(require_org_admin),
    db: Session = Depends(get_db),
) -> OrganizationOut:
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    data = body.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        data["name"] = data["name"].strip()
    for key, value in data.items():
        setattr(org, key, value)

    db.add(org)
    db.commit()
    db.refresh(org)

    return OrganizationOut(
        id=org.id,
        name=org.name,
        description=org.description,
        parent_organization_id=org.parent_organization_id,
        is_original=org.is_original,
        is_active=org.is_active,
        created_by=org.created_by,
        created_at=org.created_at,
        updated_at=org.updated_at,
        role=membership.role,
    )
