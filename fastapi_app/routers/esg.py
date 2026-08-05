"""ESG readiness assessments + scores (public.esg_* tables, org-scoped)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..auth_org import OrgContext
from ..db import get_db
from .deps import require_org_context, require_platform_admin

router = APIRouter(prefix="/esg", tags=["esg"])


class EsgAssessmentOut(BaseModel):
    id: str
    user_id: str
    assessment_type: str
    status: str
    readiness_answers: Any = None
    total_completion: Optional[float] = None
    readiness_version: Optional[int] = None
    submitted_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    organization_id: Optional[str] = None


class EsgAssessmentUpsert(BaseModel):
    assessment_type: str = "esg_readiness"
    status: str = Field(default="draft")
    readiness_answers: Dict[str, Any] = Field(default_factory=dict)
    total_completion: Optional[float] = None
    readiness_version: Optional[int] = 1
    submitted_at: Optional[str] = None


class EsgScoreOut(BaseModel):
    id: str
    user_id: str
    assessment_id: str
    readiness_overall_score: Optional[float] = None
    readiness_maturity_band: Optional[str] = None
    readiness_completion_pct: Optional[float] = None
    readiness_results: Any = None
    scored_by: Optional[str] = None
    scored_at: Optional[str] = None


class EsgScoreUpsert(BaseModel):
    assessment_id: str
    readiness_overall_score: Optional[float] = None
    readiness_maturity_band: Optional[str] = None
    readiness_completion_pct: Optional[float] = None
    readiness_results: Any = None
    scored_by: Optional[str] = "Automated System"


def _row_to_assessment(row: Dict[str, Any]) -> EsgAssessmentOut:
    return EsgAssessmentOut(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        assessment_type=str(row.get("assessment_type") or ""),
        status=str(row.get("status") or "draft"),
        readiness_answers=row.get("readiness_answers"),
        total_completion=row.get("total_completion"),
        readiness_version=row.get("readiness_version"),
        submitted_at=str(row["submitted_at"]) if row.get("submitted_at") else None,
        created_at=str(row["created_at"]) if row.get("created_at") else None,
        updated_at=str(row["updated_at"]) if row.get("updated_at") else None,
        organization_id=str(row["organization_id"]) if row.get("organization_id") else None,
    )


def _row_to_score(row: Dict[str, Any]) -> EsgScoreOut:
    return EsgScoreOut(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        assessment_id=str(row["assessment_id"]),
        readiness_overall_score=row.get("readiness_overall_score"),
        readiness_maturity_band=row.get("readiness_maturity_band"),
        readiness_completion_pct=row.get("readiness_completion_pct"),
        readiness_results=row.get("readiness_results"),
        scored_by=row.get("scored_by"),
        scored_at=str(row["scored_at"]) if row.get("scored_at") else None,
    )


@router.get("/assessments", response_model=List[EsgAssessmentOut])
def list_assessments(
    assessment_type: Optional[str] = None,
    limit: int = Query(default=20, ge=1, le=100),
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> List[EsgAssessmentOut]:
    sql = """
        SELECT * FROM public.esg_assessments
        WHERE organization_id = :org_id
          AND user_id = :user_id
    """
    params: Dict[str, Any] = {
        "org_id": str(ctx.organization_id),
        "user_id": str(ctx.user.id),
        "limit": limit,
    }
    if assessment_type:
        sql += " AND assessment_type = :assessment_type"
        params["assessment_type"] = assessment_type
    sql += " ORDER BY updated_at DESC NULLS LAST LIMIT :limit"
    rows = db.execute(text(sql), params).mappings().all()
    return [_row_to_assessment(dict(r)) for r in rows]


@router.get("/assessments/latest", response_model=Optional[EsgAssessmentOut])
def get_latest_assessment(
    assessment_type: str = Query(...),
    status_filter: Optional[str] = Query(
        default=None,
        alias="status",
        description="Optional status filter, e.g. submitted or draft",
    ),
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Optional[EsgAssessmentOut]:
    sql = """
        SELECT * FROM public.esg_assessments
        WHERE organization_id = :org_id
          AND user_id = :user_id
          AND assessment_type = :assessment_type
    """
    params: Dict[str, Any] = {
        "org_id": str(ctx.organization_id),
        "user_id": str(ctx.user.id),
        "assessment_type": assessment_type,
    }
    if status_filter:
        if status_filter not in ("draft", "submitted"):
            raise HTTPException(
                status_code=422, detail="status must be draft or submitted"
            )
        sql += " AND status = :status"
        params["status"] = status_filter
    sql += " ORDER BY updated_at DESC NULLS LAST LIMIT 1"
    row = db.execute(text(sql), params).mappings().first()
    return _row_to_assessment(dict(row)) if row else None


@router.post("/assessments", response_model=EsgAssessmentOut, status_code=status.HTTP_201_CREATED)
def create_assessment(
    body: EsgAssessmentUpsert,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> EsgAssessmentOut:
    if body.status not in ("draft", "submitted"):
        raise HTTPException(status_code=422, detail="status must be draft or submitted")
    new_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    db.execute(
        text(
            """
            INSERT INTO public.esg_assessments (
              id, user_id, organization_id, assessment_type, status,
              readiness_answers, total_completion, readiness_version,
              submitted_at, created_at, updated_at
            ) VALUES (
              :id, :user_id, :org_id, :assessment_type, :status,
              CAST(:readiness_answers AS jsonb), :total_completion, :readiness_version,
              :submitted_at, :now, :now
            )
            """
        ),
        {
            "id": new_id,
            "user_id": str(ctx.user.id),
            "org_id": str(ctx.organization_id),
            "assessment_type": body.assessment_type,
            "status": body.status,
            "readiness_answers": json.dumps(body.readiness_answers or {}),
            "total_completion": body.total_completion,
            "readiness_version": body.readiness_version,
            "submitted_at": body.submitted_at,
            "now": now,
        },
    )
    db.commit()
    row = (
        db.execute(
            text("SELECT * FROM public.esg_assessments WHERE id = :id"),
            {"id": new_id},
        )
        .mappings()
        .first()
    )
    return _row_to_assessment(dict(row))


@router.patch("/assessments/{assessment_id}", response_model=EsgAssessmentOut)
def update_assessment(
    assessment_id: str,
    body: EsgAssessmentUpsert,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> EsgAssessmentOut:
    existing = (
        db.execute(
            text(
                """
                SELECT id FROM public.esg_assessments
                WHERE id = :id AND organization_id = :org_id AND user_id = :user_id
                """
            ),
            {
                "id": assessment_id,
                "org_id": str(ctx.organization_id),
                "user_id": str(ctx.user.id),
            },
        )
        .mappings()
        .first()
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Assessment not found")

    now = datetime.now(timezone.utc)
    db.execute(
        text(
            """
            UPDATE public.esg_assessments SET
              assessment_type = :assessment_type,
              status = :status,
              readiness_answers = CAST(:readiness_answers AS jsonb),
              total_completion = :total_completion,
              readiness_version = :readiness_version,
              submitted_at = :submitted_at,
              updated_at = :now
            WHERE id = :id
            """
        ),
        {
            "id": assessment_id,
            "assessment_type": body.assessment_type,
            "status": body.status,
            "readiness_answers": json.dumps(body.readiness_answers or {}),
            "total_completion": body.total_completion,
            "readiness_version": body.readiness_version,
            "submitted_at": body.submitted_at,
            "now": now,
        },
    )
    db.commit()
    row = (
        db.execute(
            text("SELECT * FROM public.esg_assessments WHERE id = :id"),
            {"id": assessment_id},
        )
        .mappings()
        .first()
    )
    return _row_to_assessment(dict(row))


@router.get("/scores/by-assessment/{assessment_id}", response_model=Optional[EsgScoreOut])
def get_score_by_assessment(
    assessment_id: str,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Optional[EsgScoreOut]:
    row = (
        db.execute(
            text(
                """
                SELECT s.* FROM public.esg_scores s
                JOIN public.esg_assessments a ON a.id = s.assessment_id
                WHERE s.assessment_id = :assessment_id
                  AND a.organization_id = :org_id
                  AND a.user_id = :user_id
                LIMIT 1
                """
            ),
            {
                "assessment_id": assessment_id,
                "org_id": str(ctx.organization_id),
                "user_id": str(ctx.user.id),
            },
        )
        .mappings()
        .first()
    )
    return _row_to_score(dict(row)) if row else None


@router.put("/scores", response_model=EsgScoreOut)
def upsert_score(
    body: EsgScoreUpsert,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> EsgScoreOut:
    owned = (
        db.execute(
            text(
                """
                SELECT id FROM public.esg_assessments
                WHERE id = :id AND organization_id = :org_id AND user_id = :user_id
                """
            ),
            {
                "id": body.assessment_id,
                "org_id": str(ctx.organization_id),
                "user_id": str(ctx.user.id),
            },
        )
        .mappings()
        .first()
    )
    if not owned:
        raise HTTPException(status_code=404, detail="Assessment not found")

    now = datetime.now(timezone.utc)
    existing = (
        db.execute(
            text(
                "SELECT id FROM public.esg_scores WHERE assessment_id = :assessment_id"
            ),
            {"assessment_id": body.assessment_id},
        )
        .mappings()
        .first()
    )

    payload = {
        "assessment_id": body.assessment_id,
        "user_id": str(ctx.user.id),
        "readiness_overall_score": body.readiness_overall_score,
        "readiness_maturity_band": body.readiness_maturity_band,
        "readiness_completion_pct": body.readiness_completion_pct,
        "readiness_results": json.dumps(body.readiness_results)
        if body.readiness_results is not None
        else None,
        "scored_by": body.scored_by,
        "now": now,
    }

    if existing:
        db.execute(
            text(
                """
                UPDATE public.esg_scores SET
                  readiness_overall_score = :readiness_overall_score,
                  readiness_maturity_band = :readiness_maturity_band,
                  readiness_completion_pct = :readiness_completion_pct,
                  readiness_results = CAST(:readiness_results AS jsonb),
                  scored_by = :scored_by,
                  scored_at = :now,
                  updated_at = :now
                WHERE assessment_id = :assessment_id
                """
            ),
            payload,
        )
        score_id = str(existing["id"])
    else:
        score_id = str(uuid.uuid4())
        payload["id"] = score_id
        db.execute(
            text(
                """
                INSERT INTO public.esg_scores (
                  id, user_id, assessment_id,
                  readiness_overall_score, readiness_maturity_band,
                  readiness_completion_pct, readiness_results,
                  scored_by, scored_at, created_at, updated_at
                ) VALUES (
                  :id, :user_id, :assessment_id,
                  :readiness_overall_score, :readiness_maturity_band,
                  :readiness_completion_pct, CAST(:readiness_results AS jsonb),
                  :scored_by, :now, :now, :now
                )
                """
            ),
            payload,
        )
    db.commit()
    row = (
        db.execute(
            text("SELECT * FROM public.esg_scores WHERE assessment_id = :assessment_id"),
            {"assessment_id": body.assessment_id},
        )
        .mappings()
        .first()
    )
    return _row_to_score(dict(row))


# ---------------------------------------------------------------------------
# Platform admin (cross-user) — protected by X-Admin-Key
# ---------------------------------------------------------------------------


class AdminAssessmentListItem(BaseModel):
    id: str
    user_id: str
    status: str
    total_completion: Optional[float] = None
    assessment_type: str
    created_at: Optional[str] = None
    submitted_at: Optional[str] = None
    updated_at: Optional[str] = None
    user_display_name: Optional[str] = None
    organization_name: Optional[str] = None
    scored_at: Optional[str] = None
    has_score: bool = False


class AdminAssessmentDetail(BaseModel):
    id: str
    user_id: str
    status: str
    assessment_type: str
    readiness_answers: Any = None
    total_completion: Optional[float] = None
    readiness_version: Optional[int] = None
    submitted_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    organization_id: Optional[str] = None
    user_display_name: Optional[str] = None
    organization_name: Optional[str] = None
    score: Optional[EsgScoreOut] = None


@router.get("/admin/assessments", response_model=List[AdminAssessmentListItem])
def admin_list_assessments(
    assessment_type: str = Query(default="issb_readiness_v1"),
    limit: int = Query(default=200, ge=1, le=1000),
    _: None = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> List[AdminAssessmentListItem]:
    rows = db.execute(
        text(
            """
            SELECT
              a.id,
              a.user_id,
              a.status,
              a.total_completion,
              a.assessment_type,
              a.created_at,
              a.submitted_at,
              a.updated_at,
              p.display_name AS user_display_name,
              p.organization_name AS organization_name,
              s.scored_at AS scored_at,
              (s.id IS NOT NULL) AS has_score
            FROM public.esg_assessments a
            LEFT JOIN public.profiles p ON p.user_id = a.user_id
            LEFT JOIN public.esg_scores s ON s.assessment_id = a.id
            WHERE a.assessment_type = :assessment_type
            ORDER BY a.created_at DESC NULLS LAST
            LIMIT :limit
            """
        ),
        {"assessment_type": assessment_type, "limit": limit},
    ).mappings().all()

    out: List[AdminAssessmentListItem] = []
    for r in rows:
        out.append(
            AdminAssessmentListItem(
                id=str(r["id"]),
                user_id=str(r["user_id"]),
                status=str(r.get("status") or "draft"),
                total_completion=r.get("total_completion"),
                assessment_type=str(r.get("assessment_type") or ""),
                created_at=str(r["created_at"]) if r.get("created_at") else None,
                submitted_at=str(r["submitted_at"]) if r.get("submitted_at") else None,
                updated_at=str(r["updated_at"]) if r.get("updated_at") else None,
                user_display_name=r.get("user_display_name"),
                organization_name=r.get("organization_name"),
                scored_at=str(r["scored_at"]) if r.get("scored_at") else None,
                has_score=bool(r.get("has_score")),
            )
        )
    return out


@router.get("/admin/assessments/{assessment_id}", response_model=AdminAssessmentDetail)
def admin_get_assessment(
    assessment_id: str,
    _: None = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> AdminAssessmentDetail:
    row = (
        db.execute(
            text(
                """
                SELECT
                  a.*,
                  p.display_name AS user_display_name,
                  p.organization_name AS organization_name
                FROM public.esg_assessments a
                LEFT JOIN public.profiles p ON p.user_id = a.user_id
                WHERE a.id = :id
                LIMIT 1
                """
            ),
            {"id": assessment_id},
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Assessment not found")

    score_row = (
        db.execute(
            text("SELECT * FROM public.esg_scores WHERE assessment_id = :id LIMIT 1"),
            {"id": assessment_id},
        )
        .mappings()
        .first()
    )

    return AdminAssessmentDetail(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        status=str(row.get("status") or "draft"),
        assessment_type=str(row.get("assessment_type") or ""),
        readiness_answers=row.get("readiness_answers"),
        total_completion=row.get("total_completion"),
        readiness_version=row.get("readiness_version"),
        submitted_at=str(row["submitted_at"]) if row.get("submitted_at") else None,
        created_at=str(row["created_at"]) if row.get("created_at") else None,
        updated_at=str(row["updated_at"]) if row.get("updated_at") else None,
        organization_id=str(row["organization_id"]) if row.get("organization_id") else None,
        user_display_name=row.get("user_display_name"),
        organization_name=row.get("organization_name"),
        score=_row_to_score(dict(score_row)) if score_row else None,
    )
