"""User project wizard drafts under /api/v1/me/project-inputs."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..auth_org import OrgContext, get_current_org_context
from ..db import get_db
from .catalog_utils import table_exists
from .deps import require_org_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/me", tags=["project-inputs"])

_PROJECT_INPUT_FIELDS = (
    "current_industry",
    "industry_size",
    "has_emissions_knowledge",
    "ghg_types",
    "ghg_sources",
    "ghg_annual",
    "waste_volume",
    "waste_pollutants",
    "waste_treatment",
    "waste_destination",
    "other_type",
    "other_volume",
    "other_disposal",
    "project_name",
    "country",
    "area_of_interest",
    "goal",
    "register_for_credits",
    "development_strategy",
    "additional_info",
)


class ProjectInputCreate(BaseModel):
    current_industry: Optional[str] = None
    industry_size: Optional[str] = None
    has_emissions_knowledge: Optional[str] = None
    ghg_types: Optional[str] = None
    ghg_sources: Optional[str] = None
    ghg_annual: Optional[Any] = None
    waste_volume: Optional[Any] = None
    waste_pollutants: Optional[str] = None
    waste_treatment: Optional[str] = None
    waste_destination: Optional[str] = None
    other_type: Optional[str] = None
    other_volume: Optional[Any] = None
    other_disposal: Optional[str] = None
    project_name: Optional[str] = None
    country: Optional[str] = None
    area_of_interest: Optional[str] = None
    type: Optional[str] = None
    subcategory: Optional[str] = None
    goal: Optional[str] = None
    register_for_credits: Optional[bool] = None
    development_strategy: Optional[str] = None
    additional_info: Optional[str] = None


class ProjectInputOut(BaseModel):
    id: str
    user_id: str
    organization_id: Optional[str] = None
    created_at: Optional[str] = None
    current_industry: Optional[str] = None
    industry_size: Optional[str] = None
    has_emissions_knowledge: Optional[str] = None
    ghg_types: Optional[str] = None
    ghg_sources: Optional[str] = None
    ghg_annual: Optional[Any] = None
    waste_volume: Optional[Any] = None
    waste_pollutants: Optional[str] = None
    waste_treatment: Optional[str] = None
    waste_destination: Optional[str] = None
    other_type: Optional[str] = None
    other_volume: Optional[Any] = None
    other_disposal: Optional[str] = None
    project_name: Optional[str] = None
    country: Optional[str] = None
    area_of_interest: Optional[str] = None
    type: Optional[str] = None
    subcategory: Optional[str] = None
    goal: Optional[str] = None
    register_for_credits: Optional[bool] = None
    development_strategy: Optional[str] = None
    additional_info: Optional[str] = None


def _has_column(db: Session, table: str, column: str) -> bool:
    return bool(
        db.execute(
            text(
                """
                SELECT EXISTS (
                  SELECT 1 FROM information_schema.columns
                  WHERE table_schema = 'public'
                    AND table_name = :table
                    AND column_name = :column
                )
                """
            ),
            {"table": table, "column": column},
        ).scalar()
    )


def _type_column(db: Session) -> str:
    """Prefer subcategory when present; live EC2 historically used type."""
    if _has_column(db, "project_inputs", "subcategory"):
        return "subcategory"
    return "type"


def _row_to_out(row: Dict[str, Any]) -> ProjectInputOut:
    type_val = row.get("type")
    sub_val = row.get("subcategory")
    mirrored = sub_val if sub_val is not None else type_val
    return ProjectInputOut(
        id=str(row["id"]),
        user_id=str(row["user_id"]) if row.get("user_id") else "",
        organization_id=str(row["organization_id"]) if row.get("organization_id") else None,
        created_at=str(row["created_at"]) if row.get("created_at") else None,
        current_industry=row.get("current_industry"),
        industry_size=row.get("industry_size"),
        has_emissions_knowledge=row.get("has_emissions_knowledge"),
        ghg_types=row.get("ghg_types"),
        ghg_sources=row.get("ghg_sources"),
        ghg_annual=row.get("ghg_annual"),
        waste_volume=row.get("waste_volume"),
        waste_pollutants=row.get("waste_pollutants"),
        waste_treatment=row.get("waste_treatment"),
        waste_destination=row.get("waste_destination"),
        other_type=row.get("other_type"),
        other_volume=row.get("other_volume"),
        other_disposal=row.get("other_disposal"),
        project_name=row.get("project_name"),
        country=row.get("country"),
        area_of_interest=row.get("area_of_interest"),
        type=mirrored,
        subcategory=mirrored,
        goal=row.get("goal"),
        register_for_credits=row.get("register_for_credits"),
        development_strategy=row.get("development_strategy"),
        additional_info=row.get("additional_info"),
    )


@router.get("/project-inputs", response_model=List[ProjectInputOut])
def list_my_project_inputs(
    ctx: OrgContext = Depends(get_current_org_context),
    db: Session = Depends(get_db),
) -> List[ProjectInputOut]:
    rows = (
        db.execute(
            text(
                """
                SELECT * FROM public.project_inputs
                WHERE user_id = :user_id
                ORDER BY created_at DESC NULLS LAST
                """
            ),
            {"user_id": str(ctx.user.id)},
        )
        .mappings()
        .all()
    )
    return [_row_to_out(dict(r)) for r in rows]


@router.post(
    "/project-inputs",
    response_model=ProjectInputOut,
    status_code=status.HTTP_201_CREATED,
)
def create_my_project_input(
    body: ProjectInputCreate,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> ProjectInputOut:
    type_col = _type_column(db)
    type_val = body.subcategory if body.subcategory is not None else body.type
    new_id = str(uuid.uuid4())

    cols = ["id", "user_id", "organization_id", type_col]
    params: Dict[str, Any] = {
        "id": new_id,
        "user_id": str(ctx.user.id),
        "organization_id": str(ctx.organization_id),
        type_col: type_val,
    }
    for field in _PROJECT_INPUT_FIELDS:
        cols.append(field)
        params[field] = getattr(body, field)

    col_sql = ", ".join(cols)
    val_sql = ", ".join(f":{c}" for c in cols)
    db.execute(
        text(
            f"""
            INSERT INTO public.project_inputs ({col_sql})
            VALUES ({val_sql})
            """
        ),
        params,
    )
    db.commit()
    row = (
        db.execute(
            text("SELECT * FROM public.project_inputs WHERE id = :id"),
            {"id": new_id},
        )
        .mappings()
        .first()
    )
    return _row_to_out(dict(row))


@router.get("/project-inputs/{project_id}", response_model=ProjectInputOut)
def get_my_project_input(
    project_id: str,
    ctx: OrgContext = Depends(get_current_org_context),
    db: Session = Depends(get_db),
) -> ProjectInputOut:
    row = (
        db.execute(
            text(
                """
                SELECT * FROM public.project_inputs
                WHERE id = :id AND user_id = :user_id
                LIMIT 1
                """
            ),
            {"id": project_id, "user_id": str(ctx.user.id)},
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Project input not found")
    return _row_to_out(dict(row))


@router.delete("/project-inputs/{project_id}")
def delete_my_project_input(
    project_id: str,
    ctx: OrgContext = Depends(get_current_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, str]:
    result = db.execute(
        text(
            """
            DELETE FROM public.project_inputs
            WHERE id = :id AND user_id = :user_id
            RETURNING id
            """
        ),
        {"id": project_id, "user_id": str(ctx.user.id)},
    )
    deleted = result.first()
    if not deleted:
        raise HTTPException(status_code=404, detail="Project input not found")
    db.commit()
    return {"status": "deleted"}


@router.get("/project-reports")
def list_my_project_reports(
    ctx: OrgContext = Depends(get_current_org_context),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    if not table_exists(db, "public", "project_reports"):
        logger.warning("project_reports table missing — returning []")
        return []
    try:
        rows = (
            db.execute(
                text(
                    """
                    SELECT * FROM public.project_reports
                    WHERE user_id = :user_id
                    ORDER BY created_at DESC NULLS LAST
                    """
                ),
                {"user_id": str(ctx.user.id)},
            )
            .mappings()
            .all()
        )
        out: List[Dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            for key in ("id", "user_id", "project_id"):
                if d.get(key) is not None:
                    d[key] = str(d[key])
            for key in ("created_at", "updated_at"):
                if d.get(key) is not None:
                    d[key] = str(d[key])
            out.append(d)
        return out
    except Exception as exc:
        logger.warning("Failed reading project_reports (%s) — returning []", exc)
        return []
