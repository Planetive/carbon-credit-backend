"""Emission calculator LCA/mode preferences under /api/v1/me/calculator-preferences."""

from __future__ import annotations

import json
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..auth_deps import get_current_user
from ..auth_models import User
from ..db import get_db

router = APIRouter(prefix="/me", tags=["calculator-preferences"])

CalculationMode = Literal["lca", "manual"]

# Activity-based Scope 1 screening keys the SPA persists.
_SCOPE1_SCREENING_KEYS = (
    "stationary",
    "vehicles_mobile",
    "leaks_releases",
    "industrial_other",
)
_SCOPE1_SCREENING_VALUES = {
    "not_assessed",
    "not_applicable",
    "applicable_pending",
    "calculated",
}


class CalculatorPreferencesOut(BaseModel):
    user_id: str
    has_lca_data: Optional[bool] = None
    calculation_mode: Optional[str] = None
    initial_questionnaire_completed: bool = False
    scope1_screening: Dict[str, str] = Field(default_factory=dict)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class CalculatorPreferencesUpsert(BaseModel):
    has_lca_data: Optional[bool] = None
    calculation_mode: CalculationMode
    initial_questionnaire_completed: bool = True
    # Omit to leave existing DB value unchanged on upsert.
    scope1_screening: Optional[Dict[str, str]] = None


def _normalize_screening(raw: Any) -> Dict[str, str]:
    """Accept jsonb / dict; keep only known keys with allowed values."""
    if raw is None:
        return {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, str] = {}
    for key in _SCOPE1_SCREENING_KEYS:
        val = raw.get(key)
        if isinstance(val, str) and val in _SCOPE1_SCREENING_VALUES:
            out[key] = val
    return out


def _row_to_out(row: Dict[str, Any]) -> CalculatorPreferencesOut:
    return CalculatorPreferencesOut(
        user_id=str(row["user_id"]),
        has_lca_data=row.get("has_lca_data"),
        calculation_mode=row.get("calculation_mode"),
        initial_questionnaire_completed=bool(
            row.get("initial_questionnaire_completed") or False
        ),
        scope1_screening=_normalize_screening(row.get("scope1_screening")),
        created_at=str(row["created_at"]) if row.get("created_at") else None,
        updated_at=str(row["updated_at"]) if row.get("updated_at") else None,
    )


@router.get(
    "/calculator-preferences",
    response_model=Optional[CalculatorPreferencesOut],
)
def get_my_calculator_preferences(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Optional[CalculatorPreferencesOut]:
    row = (
        db.execute(
            text(
                """
                SELECT user_id, has_lca_data, calculation_mode,
                       initial_questionnaire_completed, scope1_screening,
                       created_at, updated_at
                FROM public.emission_calculator_preferences
                WHERE user_id = :user_id
                LIMIT 1
                """
            ),
            {"user_id": str(user.id)},
        )
        .mappings()
        .first()
    )
    return _row_to_out(dict(row)) if row else None


@router.put("/calculator-preferences", response_model=CalculatorPreferencesOut)
def upsert_my_calculator_preferences(
    body: CalculatorPreferencesUpsert,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CalculatorPreferencesOut:
    update_screening = body.scope1_screening is not None
    screening_payload = (
        _normalize_screening(body.scope1_screening) if update_screening else {}
    )

    row = (
        db.execute(
            text(
                """
                INSERT INTO public.emission_calculator_preferences (
                  user_id, has_lca_data, calculation_mode,
                  initial_questionnaire_completed, scope1_screening
                ) VALUES (
                  :user_id, :has_lca_data, :calculation_mode,
                  :initial_questionnaire_completed,
                  CAST(:scope1_screening AS jsonb)
                )
                ON CONFLICT (user_id) DO UPDATE SET
                  has_lca_data = EXCLUDED.has_lca_data,
                  calculation_mode = EXCLUDED.calculation_mode,
                  initial_questionnaire_completed = EXCLUDED.initial_questionnaire_completed,
                  scope1_screening = CASE
                    WHEN :update_screening THEN CAST(:scope1_screening AS jsonb)
                    ELSE public.emission_calculator_preferences.scope1_screening
                  END,
                  updated_at = now()
                RETURNING user_id, has_lca_data, calculation_mode,
                          initial_questionnaire_completed, scope1_screening,
                          created_at, updated_at
                """
            ),
            {
                "user_id": str(user.id),
                "has_lca_data": body.has_lca_data,
                "calculation_mode": body.calculation_mode,
                "initial_questionnaire_completed": body.initial_questionnaire_completed,
                "scope1_screening": json.dumps(screening_payload),
                "update_screening": update_screening,
            },
        )
        .mappings()
        .first()
    )
    db.commit()
    return _row_to_out(dict(row))
