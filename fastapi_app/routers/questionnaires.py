"""Counterparty questionnaires under /api/v1/counterparties/... and /api/v1/questionnaires."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..auth_org import OrgContext
from ..db import get_db
from ..portfolio_models import Counterparty
from .catalog_utils import table_exists
from .deps import require_org_context

logger = logging.getLogger(__name__)

counterparties_q_router = APIRouter(prefix="/counterparties", tags=["questionnaires"])
questionnaires_router = APIRouter(prefix="/questionnaires", tags=["questionnaires"])

TABLE = "counterparty_questionnaires"

WRITABLE_FIELDS = (
    "corporate_structure",
    "has_emissions",
    "scope1_emissions",
    "scope2_emissions",
    "scope3_emissions",
    "verification_status",
    "verifier_name",
    "evic",
    "total_equity_plus_debt",
    "share_price",
    "outstanding_shares",
    "total_debt",
    "minority_interest",
    "preferred_stock",
    "total_equity",
)


class QuestionnaireUpsert(BaseModel):
    model_config = ConfigDict(extra="ignore")

    corporate_structure: Optional[str] = None
    has_emissions: Optional[Any] = None
    scope1_emissions: Optional[float] = None
    scope2_emissions: Optional[float] = None
    scope3_emissions: Optional[float] = None
    verification_status: Optional[str] = None
    verifier_name: Optional[str] = None
    evic: Optional[float] = None
    total_equity_plus_debt: Optional[float] = None
    share_price: Optional[float] = None
    outstanding_shares: Optional[float] = None
    total_debt: Optional[float] = None
    minority_interest: Optional[float] = None
    preferred_stock: Optional[float] = None
    total_equity: Optional[float] = None
    # SPA sometimes includes these; ignore for write identity
    counterparty_id: Optional[str] = None


class QuestionnairePatch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    corporate_structure: Optional[str] = None
    has_emissions: Optional[Any] = None
    scope1_emissions: Optional[float] = None
    scope2_emissions: Optional[float] = None
    scope3_emissions: Optional[float] = None
    verification_status: Optional[str] = None
    verifier_name: Optional[str] = None
    evic: Optional[float] = None
    total_equity_plus_debt: Optional[float] = None
    share_price: Optional[float] = None
    outstanding_shares: Optional[float] = None
    total_debt: Optional[float] = None
    minority_interest: Optional[float] = None
    preferred_stock: Optional[float] = None
    total_equity: Optional[float] = None


def _ensure_table(db: Session) -> None:
    if not table_exists(db, "public", TABLE):
        logger.error("KEEP table public.%s missing", TABLE)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Table public.{TABLE} is not available",
        )


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    s = str(value).strip().lower()
    if s in ("yes", "true", "1", "y"):
        return True
    if s in ("no", "false", "0", "n", ""):
        return False
    return default


def _normalize_structure(value: Optional[str], default: str = "unlisted") -> str:
    if not value:
        return default
    v = str(value).strip().lower()
    if v not in ("listed", "unlisted"):
        raise HTTPException(
            status_code=422,
            detail="corporate_structure must be listed or unlisted",
        )
    return v


def _normalize_verification(value: Optional[str]) -> Optional[str]:
    if value is None or value == "":
        return None
    v = str(value).strip().lower()
    if v not in ("verified", "unverified"):
        raise HTTPException(
            status_code=422,
            detail="verification_status must be verified or unverified",
        )
    return v


def _row_out(row: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, val in row.items():
        if key in ("id", "user_id", "counterparty_id") and val is not None:
            out[key] = str(val)
        elif key in ("created_at", "updated_at") and val is not None:
            out[key] = str(val)
        elif hasattr(val, "as_tuple"):  # Decimal
            out[key] = float(val)
        else:
            out[key] = val
    return out


def _get_org_counterparty(
    db: Session, organization_id: uuid.UUID, counterparty_id: uuid.UUID
) -> Counterparty:
    row = (
        db.query(Counterparty)
        .filter(
            Counterparty.id == counterparty_id,
            Counterparty.organization_id == organization_id,
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Counterparty not found")
    return row


def _fetch_for_counterparty(
    db: Session, organization_id: uuid.UUID, counterparty_id: uuid.UUID
) -> Optional[Dict[str, Any]]:
    row = (
        db.execute(
            text(
                """
                SELECT cq.*
                FROM public.counterparty_questionnaires cq
                JOIN public.counterparties c ON c.id = cq.counterparty_id
                WHERE cq.counterparty_id = :counterparty_id
                  AND c.organization_id = :organization_id
                LIMIT 1
                """
            ),
            {
                "counterparty_id": str(counterparty_id),
                "organization_id": str(organization_id),
            },
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def _payload_from_upsert(body: QuestionnaireUpsert, *, for_insert: bool) -> Dict[str, Any]:
    data = body.model_dump(exclude_unset=True, exclude={"counterparty_id"})
    if "has_emissions" in data:
        data["has_emissions"] = _coerce_bool(data["has_emissions"], default=False)
    if "corporate_structure" in data:
        data["corporate_structure"] = _normalize_structure(data["corporate_structure"])
    elif for_insert:
        data["corporate_structure"] = "unlisted"
    if "verification_status" in data:
        data["verification_status"] = _normalize_verification(data["verification_status"])
    if for_insert and "has_emissions" not in data:
        data["has_emissions"] = False
    return data


@counterparties_q_router.get("/{counterparty_id}/questionnaire")
def get_counterparty_questionnaire(
    counterparty_id: uuid.UUID,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Optional[Dict[str, Any]]:
    _ensure_table(db)
    _get_org_counterparty(db, ctx.organization_id, counterparty_id)
    row = _fetch_for_counterparty(db, ctx.organization_id, counterparty_id)
    return _row_out(row) if row else None


@counterparties_q_router.put("/{counterparty_id}/questionnaire")
def upsert_counterparty_questionnaire(
    counterparty_id: uuid.UUID,
    body: QuestionnaireUpsert,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _ensure_table(db)
    _get_org_counterparty(db, ctx.organization_id, counterparty_id)

    existing = _fetch_for_counterparty(db, ctx.organization_id, counterparty_id)
    now = datetime.now(timezone.utc)

    if existing:
        updates = _payload_from_upsert(body, for_insert=False)
        if not updates:
            return _row_out(existing)
        sets = [f"{col} = :{col}" for col in updates.keys()]
        sets.append("updated_at = :updated_at")
        params = dict(updates)
        params["updated_at"] = now
        params["id"] = str(existing["id"])
        db.execute(
            text(
                f"""
                UPDATE public.counterparty_questionnaires
                SET {", ".join(sets)}
                WHERE id = :id
                """
            ),
            params,
        )
        db.commit()
        row = (
            db.execute(
                text("SELECT * FROM public.counterparty_questionnaires WHERE id = :id"),
                {"id": str(existing["id"])},
            )
            .mappings()
            .first()
        )
        return _row_out(dict(row))

    insert_data = _payload_from_upsert(body, for_insert=True)
    new_id = str(uuid.uuid4())
    cols = ["id", "user_id", "counterparty_id", "created_at", "updated_at"]
    params: Dict[str, Any] = {
        "id": new_id,
        "user_id": str(ctx.user.id),
        "counterparty_id": str(counterparty_id),
        "created_at": now,
        "updated_at": now,
    }
    for field in WRITABLE_FIELDS:
        if field in insert_data:
            cols.append(field)
            params[field] = insert_data[field]
    # ensure NOT NULL columns present
    if "corporate_structure" not in params:
        cols.append("corporate_structure")
        params["corporate_structure"] = "unlisted"
    if "has_emissions" not in params:
        cols.append("has_emissions")
        params["has_emissions"] = False

    db.execute(
        text(
            f"""
            INSERT INTO public.counterparty_questionnaires ({", ".join(cols)})
            VALUES ({", ".join(f":{c}" for c in cols)})
            """
        ),
        params,
    )
    db.commit()
    row = (
        db.execute(
            text("SELECT * FROM public.counterparty_questionnaires WHERE id = :id"),
            {"id": new_id},
        )
        .mappings()
        .first()
    )
    return _row_out(dict(row))


@questionnaires_router.get("")
def list_questionnaires(
    counterparty_id: Optional[uuid.UUID] = Query(default=None),
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    _ensure_table(db)
    sql = """
        SELECT cq.*
        FROM public.counterparty_questionnaires cq
        JOIN public.counterparties c ON c.id = cq.counterparty_id
        WHERE c.organization_id = :organization_id
    """
    params: Dict[str, Any] = {"organization_id": str(ctx.organization_id)}
    if counterparty_id is not None:
        sql += " AND cq.counterparty_id = :counterparty_id"
        params["counterparty_id"] = str(counterparty_id)
    sql += " ORDER BY cq.updated_at DESC NULLS LAST"
    rows = db.execute(text(sql), params).mappings().all()
    return [_row_out(dict(r)) for r in rows]


@questionnaires_router.patch("/{questionnaire_id}")
def patch_questionnaire(
    questionnaire_id: uuid.UUID,
    body: QuestionnairePatch,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _ensure_table(db)
    existing = (
        db.execute(
            text(
                """
                SELECT cq.*
                FROM public.counterparty_questionnaires cq
                JOIN public.counterparties c ON c.id = cq.counterparty_id
                WHERE cq.id = :id AND c.organization_id = :organization_id
                LIMIT 1
                """
            ),
            {
                "id": str(questionnaire_id),
                "organization_id": str(ctx.organization_id),
            },
        )
        .mappings()
        .first()
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Questionnaire not found")

    updates = body.model_dump(exclude_unset=True)
    if "has_emissions" in updates:
        updates["has_emissions"] = _coerce_bool(updates["has_emissions"], default=False)
    if "corporate_structure" in updates:
        updates["corporate_structure"] = _normalize_structure(updates["corporate_structure"])
    if "verification_status" in updates:
        updates["verification_status"] = _normalize_verification(
            updates["verification_status"]
        )
    if not updates:
        return _row_out(dict(existing))

    sets = [f"{col} = :{col}" for col in updates.keys()]
    sets.append("updated_at = :updated_at")
    params = dict(updates)
    params["updated_at"] = datetime.now(timezone.utc)
    params["id"] = str(questionnaire_id)
    db.execute(
        text(
            f"""
            UPDATE public.counterparty_questionnaires
            SET {", ".join(sets)}
            WHERE id = :id
            """
        ),
        params,
    )
    db.commit()
    row = (
        db.execute(
            text("SELECT * FROM public.counterparty_questionnaires WHERE id = :id"),
            {"id": str(questionnaire_id)},
        )
        .mappings()
        .first()
    )
    return _row_out(dict(row))
