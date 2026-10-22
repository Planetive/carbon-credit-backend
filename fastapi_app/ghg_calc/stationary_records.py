"""
Persist EPA stationary combustion on app.emission_activities.

Calculation runs before any insert or update. A failed calculation or a failed
commit leaves the database unchanged. Records created by other calculators are
not updated.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Dict, Mapping, Optional, Sequence

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from ..auth_org import OrgContext
from ..ghg_models import EmissionActivity, EmissionAssessment
from ..portfolio_models import Counterparty
from .stationary_combustion import calculate_stationary_combustion

STATIONARY_METHOD = "epa_stationary"
STATIONARY_CATEGORY = "stationary_combustion"
STATIONARY_LEGACY_SOURCE = "epa_stationary"


def _optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _uuid_or_none(value: Any) -> Optional[uuid.UUID]:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _activity_payload(calculation: Mapping[str, Any], ownership: Mapping[str, Any]) -> Dict[str, Any]:
    meta = {
        "activity_group": "stationary",
        "equipment_type": ownership["equipment_type"],
        "method_version": "epa_stationary_v1",
    }
    if ownership.get("site"):
        meta["site"] = ownership["site"]
    if ownership.get("equipment_id"):
        meta["source_id"] = ownership["equipment_id"]
        meta["equipment_id"] = ownership["equipment_id"]
    if ownership.get("period"):
        meta["period"] = ownership["period"]

    return {
        "calc": STATIONARY_METHOD,
        "activity_meta": meta,
        "inputs": {
            "fuel": calculation["fuel"],
            "fuel_category": calculation["category"],
            "quantity": calculation["quantity"],
            "unit": calculation["unit"],
            "gwp_version": calculation["factor_source"]["gwp_version"],
        },
        "gases": calculation["gases"],
        "factors": calculation["factors"],
        "factor_source": calculation["factor_source"],
        "total_kg_co2e": calculation["total_kg_co2e"],
        "total_t_co2e": calculation["total_t_co2e"],
    }


def _org_assessment(db: Session, organization_id: uuid.UUID, assessment_id: uuid.UUID) -> EmissionAssessment:
    row = (
        db.query(EmissionAssessment)
        .filter(
            EmissionAssessment.id == assessment_id,
            EmissionAssessment.organization_id == organization_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Emission assessment not found in current organization",
        )
    return row


def _org_counterparty(
    db: Session, organization_id: uuid.UUID, counterparty_id: Optional[uuid.UUID]
) -> None:
    if counterparty_id is None:
        return
    row = (
        db.query(Counterparty)
        .filter(
            Counterparty.id == counterparty_id,
            Counterparty.organization_id == organization_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="counterparty_id does not belong to the current organization",
        )


def _stage_record(
    db: Session,
    ctx: OrgContext,
    calculation: Mapping[str, Any],
    *,
    assessment_id: uuid.UUID,
    counterparty_id: Optional[uuid.UUID],
    equipment_type: str,
    site: Optional[str],
    equipment_id: Optional[str],
    period: Optional[str],
    activity_id: Optional[uuid.UUID],
) -> EmissionActivity:
    equipment = _optional_text(equipment_type)
    if not equipment:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="equipment_type is required",
        )
    period_text = _optional_text(period)
    if period_text is not None and (
        len(period_text) != 7 or period_text[4] != "-" or not (
            period_text[:4].isdigit() and period_text[5:].isdigit()
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="period must be YYYY-MM",
        )

    organization_id = ctx.organization_id
    if organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No organization context; join or create an organization first",
        )

    _org_assessment(db, organization_id, assessment_id)
    _org_counterparty(db, organization_id, counterparty_id)

    ownership = {
        "equipment_type": equipment,
        "site": _optional_text(site),
        "equipment_id": _optional_text(equipment_id),
        "period": period_text,
    }
    raw = _activity_payload(calculation, ownership)
    source = calculation["factor_source"]
    tonnes = Decimal(calculation["total_t_co2e"])
    quantity = Decimal(calculation["quantity"])

    if activity_id is None:
        row = EmissionActivity(
            id=uuid.uuid4(),
            assessment_id=assessment_id,
            organization_id=organization_id,
            user_id=ctx.user.id,
            scope=1,
            category=STATIONARY_CATEGORY,
            method=STATIONARY_METHOD,
            legacy_source=STATIONARY_LEGACY_SOURCE,
        )
        db.add(row)
    else:
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
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Emission activity not found",
            )
        if row.method != STATIONARY_METHOD or row.legacy_source != STATIONARY_LEGACY_SOURCE:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This record was not created by the stationary combustion calculator",
            )

    row.counterparty_id = counterparty_id
    row.quantity = quantity
    row.unit = calculation["unit"]
    row.factor_dataset_id = _uuid_or_none(source.get("dataset_id"))
    row.factor_row_id = _uuid_or_none(source.get("factor_row_id"))
    row.emissions_tco2e = tonnes
    row.raw = raw
    row.scope = 1
    row.category = STATIONARY_CATEGORY
    row.method = STATIONARY_METHOD
    row.legacy_source = STATIONARY_LEGACY_SOURCE
    return row


def save_epa_stationary_record(
    db: Session,
    ctx: OrgContext,
    *,
    sheets: Sequence[Mapping[str, Any]],
    fuel: str,
    quantity: Any,
    unit: str,
    assessment_id: uuid.UUID,
    equipment_type: str,
    category: Optional[str] = None,
    gwp_version: str = "AR5",
    counterparty_id: Optional[uuid.UUID] = None,
    site: Optional[str] = None,
    equipment_id: Optional[str] = None,
    period: Optional[str] = None,
    activity_id: Optional[uuid.UUID] = None,
    factor: Any = None,
    emissions: Any = None,
    emissions_kg: Any = None,
    emissions_tco2e: Any = None,
    total_kg_co2e: Any = None,
    total_t_co2e: Any = None,
) -> Dict[str, Any]:
    """Calculate, then commit. Client totals and factors are discarded."""
    del factor, emissions, emissions_kg, emissions_tco2e, total_kg_co2e, total_t_co2e

    calculation = calculate_stationary_combustion(
        fuel=fuel,
        quantity=quantity,
        unit=unit,
        category=category,
        gwp_version=gwp_version,
        sheets=sheets,
    )
    if not calculation.get("success"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=calculation.get("error") or "EPA stationary combustion calculation failed",
        )

    try:
        row = _stage_record(
            db,
            ctx,
            calculation,
            assessment_id=assessment_id,
            counterparty_id=counterparty_id,
            equipment_type=equipment_type,
            site=site,
            equipment_id=equipment_id,
            period=period,
            activity_id=activity_id,
        )
        db.flush()
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except (IntegrityError, SQLAlchemyError) as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not save stationary combustion record",
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
    }
