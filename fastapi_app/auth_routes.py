"""
Auth routes: signup, login, me, logout, password-reset stub.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth_models import Profile, User
from .auth_org import OrgContext, get_current_org_context
from .auth_schemas import (
    LoginRequest,
    LogoutResponse,
    PasswordResetRequest,
    ProfileOut,
    SignupRequest,
    TokenResponse,
    UserMeResponse,
)
from .auth_security import create_access_token, hash_password, verify_password
from .db import get_db

router = APIRouter()


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def signup(body: SignupRequest, db: Session = Depends(get_db)) -> TokenResponse:
    email = body.email.strip().lower()
    display_name = body.display_name.strip()

    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    user = User(
        email=email,
        password_hash=hash_password(body.password),
    )
    profile = Profile(user=user, display_name=display_name)
    db.add(user)
    db.add(profile)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    db.refresh(user)
    token = create_access_token(user.id, extra_claims={"email": user.email})
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    email = body.email.strip().lower()
    user = db.query(User).filter(User.email == email).first()

    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(user.id, extra_claims={"email": user.email})
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserMeResponse)
def me(
    ctx: OrgContext = Depends(get_current_org_context),
    db: Session = Depends(get_db),
) -> UserMeResponse:
    profile = db.query(Profile).filter(Profile.user_id == ctx.user.id).first()
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found for this user",
        )

    return UserMeResponse(
        id=ctx.user.id,
        email=ctx.user.email,
        profile=ProfileOut.model_validate(profile),
        current_organization_id=ctx.organization_id,
        role=ctx.role,
    )


@router.post("/logout", response_model=LogoutResponse)
def logout() -> LogoutResponse:
    """Stateless JWT: server has nothing to invalidate; client must discard the token."""
    return LogoutResponse()


@router.post(
    "/password-reset/request",
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
)
def password_reset_request(body: PasswordResetRequest) -> None:
    # TODO: email a one-time reset token once mail delivery is wired.
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Password reset is not implemented yet",
    )
