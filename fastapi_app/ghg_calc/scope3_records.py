"""Persist verified Scope 3 activities on app.emission_activities."""

from __future__ import annotations

import hashlib
import json
import uuid
from decimal import Decimal
from typing import Any, Dict, Optional

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from ..auth_org import OrgContext
from ..ghg_models import EmissionActivity, EmissionAssessment
from ..portfolio_models import Counterparty
from .scope3_period import period_error
from .scope3_verified_calc import ACCOUNTING_VERSION


def _assessment(db: Session, organization_id: uuid.UUID, assessment_id: uuid.UUID) -> EmissionAssessment:
    row = (
        db.query(EmissionAssessment)
        .filter(
            EmissionAssessment.id == assessment_id,
            EmissionAssessment.organization_id == organization_id,
        )
        .first()
    )
    if row is None or row.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Emission assessment not found in current organization",
        )
    return row


def _counterparty(db: Session, organization_id: uuid.UUID, counterparty_id: Optional[uuid.UUID]) -> None:
    if counterparty_id is None:
        return
    row = (
        db.query(Counterparty)
        .filter(Counterparty.id == counterparty_id, Counterparty.organization_id == organization_id)
        .first()
    )
    if row is None or row.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="counterparty_id does not belong to the current organization",
        )


def _canonicalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _canonicalize(value[k]) for k in sorted(value.keys(), key=lambda x: str(x))}
    if isinstance(value, (list, tuple)):
        return [_canonicalize(v) for v in value]
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, float):
        return format(Decimal(str(value)), "f")
    return value


def activity_input_fingerprint(
    *,
    category: str,
    method: str,
    period: str,
    counterparty_id: Optional[uuid.UUID],
    inputs: Dict[str, Any],
    client_entry_id: Optional[str] = None,
) -> str:
    """
    Identity for idempotent retries of the same logical activity.

    Matches assessment+category+period+counterparty+method+canonical inputs
    plus optional client_entry_id (UI row identity).
    Does NOT use emission totals or factor values (those are server-derived).
    Distinct client_entry_id values keep separate rows even when inputs match.
    """
    payload = {
        "category": category,
        "method": method,
        "period": period,
        "counterparty_id": str(counterparty_id) if counterparty_id else None,
        "client_entry_id": (client_entry_id or "").strip() or None,
        "inputs": _canonicalize(inputs or {}),
    }
    blob = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _raw(calculation: Dict[str, Any], *, fingerprint: str) -> Dict[str, Any]:
    factor = calculation.get("factor") or {}
    return {
        "calc": ACCOUNTING_VERSION,
        "activity_meta": {
            "activity_group": calculation.get("category"),
            "period": calculation.get("period"),
            "method_version": calculation.get("method") or ACCOUNTING_VERSION,
            "reporting_year": calculation.get("reporting_year"),
            "input_fingerprint": fingerprint,
        },
        "inputs": calculation.get("inputs") or {},
        "factor": factor,
        "factor_source": factor,
        "total_kg_co2e": calculation.get("total_kg_co2e"),
        "total_t_co2e": calculation.get("total_t_co2e"),
        "methodology": calculation.get("methodology"),
        "accounting": calculation.get("accounting"),
    }


def _find_by_fingerprint(
    db: Session,
    *,
    organization_id: uuid.UUID,
    assessment_id: uuid.UUID,
    category: str,
    fingerprint: str,
) -> Optional[EmissionActivity]:
    rows = (
        db.query(EmissionActivity)
        .filter(
            EmissionActivity.organization_id == organization_id,
            EmissionActivity.assessment_id == assessment_id,
            EmissionActivity.scope == 3,
            EmissionActivity.category == category,
            EmissionActivity.legacy_source == ACCOUNTING_VERSION,
        )
        .with_for_update()
        .all()
    )
    for row in rows:
        meta = (row.raw or {}).get("activity_meta") or {}
        if meta.get("input_fingerprint") == fingerprint:
            return row
    return None


def save_scope3_record(
    db: Session,
    ctx: OrgContext,
    *,
    calculation: Dict[str, Any],
    assessment_id: uuid.UUID,
    counterparty_id: Optional[uuid.UUID] = None,
    activity_id: Optional[uuid.UUID] = None,
    client_entry_id: Optional[str] = None,
    category_override: Optional[str] = None,
) -> Dict[str, Any]:
    if not calculation.get("ok") or not calculation.get("save_allowed"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=calculation.get("error") or "Scope 3 calculation is not saveable",
        )
    organization_id = ctx.organization_id
    if organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No organization context; join or create an organization first",
        )

    category = category_override or calculation["category"]
    method = calculation["method"]
    period = calculation.get("period")
    fingerprint = activity_input_fingerprint(
        category=category,
        method=method,
        period=str(period or ""),
        counterparty_id=counterparty_id,
        inputs=calculation.get("inputs") or {},
        client_entry_id=client_entry_id,
    )

    reused_existing = False
    try:
        assessment = _assessment(db, organization_id, assessment_id)
        pe = period_error(period, assessment.reporting_period)
        if pe:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=pe)
        _counterparty(db, organization_id, counterparty_id)

        factor = calculation["factor"]
        tonnes = Decimal(str(calculation["total_t_co2e"]))
        dataset_id = factor.get("dataset_id")
        row_id = factor.get("factor_row_id")

        if activity_id is not None:
            row = (
                db.query(EmissionActivity)
                .filter(
                    EmissionActivity.id == activity_id,
                    EmissionActivity.organization_id == organization_id,
                )
                .with_for_update()
                .first()
            )
            if row is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Emission activity not found")
            if row.scope != 3 or row.legacy_source != ACCOUNTING_VERSION:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="This record was not created by the verified Scope 3 calculator",
                )
            reused_existing = True
        else:
            # Idempotent retry: same fingerprint updates the existing row.
            # Unrelated activities with matching amounts are not collapsed.
            row = _find_by_fingerprint(
                db,
                organization_id=organization_id,
                assessment_id=assessment_id,
                category=category,
                fingerprint=fingerprint,
            )
            if row is None:
                row = EmissionActivity(
                    id=uuid.uuid4(),
                    assessment_id=assessment_id,
                    organization_id=organization_id,
                    user_id=ctx.user.id,
                    scope=3,
                    category=category,
                    method=method,
                    legacy_source=ACCOUNTING_VERSION,
                )
                db.add(row)
            else:
                reused_existing = True

        row.counterparty_id = counterparty_id
        row.quantity = Decimal(str(calculation["quantity"]))
        row.unit = calculation["unit"]
        row.factor_dataset_id = uuid.UUID(dataset_id) if dataset_id else None
        try:
            row.factor_row_id = uuid.UUID(str(row_id)) if row_id else None
        except (ValueError, TypeError):
            row.factor_row_id = None
        row.emissions_tco2e = tonnes
        row.raw = _raw(calculation, fingerprint=fingerprint)
        row.scope = 3
        row.category = category
        row.method = method
        row.legacy_source = ACCOUNTING_VERSION
        db.flush()
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except (IntegrityError, SQLAlchemyError) as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Verified Scope 3 activity could not be saved",
        ) from exc

    db.refresh(row)
    return {
        "activity_id": str(row.id),
        "assessment_id": str(row.assessment_id),
        "organization_id": str(row.organization_id),
        "counterparty_id": str(row.counterparty_id) if row.counterparty_id else None,
        "emissions_tco2e": calculation["total_t_co2e"],
        "calculation": calculation,
        "raw": row.raw,
        "idempotent_replay": reused_existing,
    }
