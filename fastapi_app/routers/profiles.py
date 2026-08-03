"""Profile endpoints under /api/v1/me/profile."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..auth_models import Profile, UserOrganization
from ..auth_org import OrgContext, get_current_org_context
from ..db import get_db
from ..schemas_v1 import ProfileResponse, ProfileUpdate

router = APIRouter(prefix="/me", tags=["profile"])


@router.get("/profile", response_model=ProfileResponse)
def get_my_profile(
    ctx: OrgContext = Depends(get_current_org_context),
    db: Session = Depends(get_db),
) -> ProfileResponse:
    profile = db.query(Profile).filter(Profile.user_id == ctx.user.id).first()
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found",
        )
    return ProfileResponse(
        id=profile.id,
        user_id=profile.user_id,
        display_name=profile.display_name,
        phone=profile.phone,
        organization_name=profile.organization_name,
        user_type=profile.user_type,
        current_organization_id=ctx.organization_id,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
        role=ctx.role,
    )


@router.patch("/profile", response_model=ProfileResponse)
def patch_my_profile(
    body: ProfileUpdate,
    ctx: OrgContext = Depends(get_current_org_context),
    db: Session = Depends(get_db),
) -> ProfileResponse:
    profile = db.query(Profile).filter(Profile.user_id == ctx.user.id).first()
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found",
        )

    data = body.model_dump(exclude_unset=True)

    if "current_organization_id" in data:
        new_org_id = data["current_organization_id"]
        if new_org_id is not None:
            membership = (
                db.query(UserOrganization)
                .filter(
                    UserOrganization.user_id == ctx.user.id,
                    UserOrganization.organization_id == new_org_id,
                )
                .first()
            )
            if membership is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Not a member of the requested organization",
                )

    if "user_type" in data and data["user_type"] is not None:
        allowed = {"corporate", "financial_institution"}
        if data["user_type"] not in allowed:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"user_type must be one of: {sorted(allowed)}",
            )

    for key, value in data.items():
        setattr(profile, key, value)

    db.add(profile)
    db.commit()
    db.refresh(profile)

    # Re-resolve role after possible org switch
    from ..auth_org import resolve_org_for_user

    org_id, role = resolve_org_for_user(db, ctx.user.id)

    return ProfileResponse(
        id=profile.id,
        user_id=profile.user_id,
        display_name=profile.display_name,
        phone=profile.phone,
        organization_name=profile.organization_name,
        user_type=profile.user_type,
        current_organization_id=org_id,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
        role=role,
    )
