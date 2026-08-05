"""Public contact form + admin CRUD on public.contact_submissions."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db import get_db
from .deps import require_platform_admin

router = APIRouter(tags=["contact-submissions"])

ContactStatus = Literal["new", "in_progress", "completed", "spam"]


class ContactSubmissionCreate(BaseModel):
    name: str = Field(min_length=1)
    email: str = Field(min_length=1)
    company: Optional[str] = None
    phone: Optional[str] = None
    subject: str = Field(default="")
    message: str = Field(min_length=1)
    status: ContactStatus = "new"


class ContactStatusPatch(BaseModel):
    status: ContactStatus


class ContactSubmissionOut(BaseModel):
    id: str
    name: str
    email: str
    company: Optional[str] = None
    phone: Optional[str] = None
    subject: str
    message: str
    status: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


def _row_to_out(row: Dict[str, Any]) -> ContactSubmissionOut:
    return ContactSubmissionOut(
        id=str(row["id"]),
        name=str(row.get("name") or ""),
        email=str(row.get("email") or ""),
        company=row.get("company"),
        phone=row.get("phone"),
        subject=str(row.get("subject") or ""),
        message=str(row.get("message") or ""),
        status=str(row.get("status") or "new"),
        created_at=str(row["created_at"]) if row.get("created_at") else None,
        updated_at=str(row["updated_at"]) if row.get("updated_at") else None,
    )


@router.post(
    "/contact-submissions",
    response_model=ContactSubmissionOut,
    status_code=status.HTTP_201_CREATED,
)
def create_contact_submission(
    body: ContactSubmissionCreate,
    db: Session = Depends(get_db),
) -> ContactSubmissionOut:
    name = (body.name or "").strip()
    email = (body.email or "").strip()
    message = (body.message or "").strip()
    if not name or not email or not message:
        raise HTTPException(
            status_code=422,
            detail="name, email, and message are required",
        )

    new_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    db.execute(
        text(
            """
            INSERT INTO public.contact_submissions (
              id, name, email, company, phone, subject, message, status,
              created_at, updated_at
            ) VALUES (
              :id, :name, :email, :company, :phone, :subject, :message, :status,
              :now, :now
            )
            """
        ),
        {
            "id": new_id,
            "name": name,
            "email": email,
            "company": body.company,
            "phone": body.phone,
            "subject": (body.subject or "").strip() or "Contact",
            "message": message,
            "status": body.status,
            "now": now,
        },
    )
    db.commit()
    row = (
        db.execute(
            text("SELECT * FROM public.contact_submissions WHERE id = :id"),
            {"id": new_id},
        )
        .mappings()
        .first()
    )
    return _row_to_out(dict(row))


@router.get(
    "/admin/contact-submissions",
    response_model=List[ContactSubmissionOut],
)
def admin_list_contact_submissions(
    _: None = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> List[ContactSubmissionOut]:
    rows = (
        db.execute(
            text(
                """
                SELECT * FROM public.contact_submissions
                ORDER BY created_at DESC NULLS LAST
                """
            )
        )
        .mappings()
        .all()
    )
    return [_row_to_out(dict(r)) for r in rows]


@router.patch(
    "/admin/contact-submissions/{submission_id}",
    response_model=ContactSubmissionOut,
)
def admin_patch_contact_submission(
    submission_id: str,
    body: ContactStatusPatch,
    _: None = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> ContactSubmissionOut:
    now = datetime.now(timezone.utc)
    result = db.execute(
        text(
            """
            UPDATE public.contact_submissions
            SET status = :status, updated_at = :now
            WHERE id = :id
            RETURNING *
            """
        ),
        {"id": submission_id, "status": body.status, "now": now},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Contact submission not found")
    db.commit()
    return _row_to_out(dict(row))


@router.delete("/admin/contact-submissions/{submission_id}")
def admin_delete_contact_submission(
    submission_id: str,
    _: None = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> Dict[str, str]:
    result = db.execute(
        text(
            """
            DELETE FROM public.contact_submissions
            WHERE id = :id
            RETURNING id
            """
        ),
        {"id": submission_id},
    )
    if not result.first():
        raise HTTPException(status_code=404, detail="Contact submission not found")
    db.commit()
    return {"status": "deleted"}
