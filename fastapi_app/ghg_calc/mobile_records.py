"""
Persist EPA mobile combustion on app.emission_activities.

Calculation runs before any insert or update. A failed calculation or a failed
commit leaves the database unchanged. One vehicle or piece of equipment is one
row. Historical, UK, and stationary records are not updated.
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
from .mobile_combustion import ACCOUNTING_VERSION, calculate_mobile_combustion

MOBILE_METHOD = "epa_mobile_v1"
MOBILE_CATEGORY = "mobile_combustion"
MOBILE_LEGACY_SOURCE = "epa_mobile_v1"
_YEAR_MIN = 1990
_YEAR_MAX = 2200


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


def _require_period(period: Optional[str]) -> str:
    text = _optional_text(period)
    if (
        text is None
        or len(text) != 7
        or text[4] != "-"
        or not (text[:4].isdigit() and text[5:].isdigit())
        or not 1 <= int(text[5:]) <= 12
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="period must be YYYY-MM",
        )
    year = int(text[:4])
    if year < _YEAR_MIN or year > _YEAR_MAX:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="period must be YYYY-MM",
        )
    return text


def _reporting_year(value: Optional[str]) -> Optional[int]:
    text = _optional_text(value)
    if text is None:
        return None
    if len(text) == 4 and text.isdigit():
        year = int(text)
    elif (
        len(text) == 7
        and text[4] == "-"
        and text[:4].isdigit()
        and text[5:].isdigit()
        and 1 <= int(text[5:]) <= 12
    ):
        year = int(text[:4])
    else:
        return None
    if year < _YEAR_MIN or year > _YEAR_MAX:
        return None
    return year


def _require_same_year(period: str, assessment: EmissionAssessment) -> None:
    activity_year = int(period[:4])
    assessment_year = _reporting_year(assessment.reporting_period)
    if assessment_year is None or assessment_year != activity_year:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"period {period} does not match the assessment reporting year",
        )


def _activity_payload(calculation: Mapping[str, Any], ownership: Mapping[str, Any]) -> Dict[str, Any]:
    meta = {
        "activity_group": "mobile",
        "road_class": calculation["road_class"],
        "vehicle_type": calculation["vehicle_type"],
        "method_version": calculation.get("accounting", {}).get("version") or ACCOUNTING_VERSION,
        "period": ownership["period"],
    }
    if ownership.get("equipment_id"):
        meta["equipment_id"] = ownership["equipment_id"]
        meta["source_id"] = ownership["equipment_id"]
    if calculation.get("model_year"):
        meta["model_year"] = calculation["model_year"]
    if ownership.get("site"):
        meta["site"] = ownership["site"]

    return {
        "calc": MOBILE_METHOD,
        "activity_meta": meta,
        "inputs": {
            "road_class": calculation["road_class"],
            "vehicle_type": calculation["vehicle_type"],
            "fuel": calculation["fuel"],
            "fuel_quantity": calculation["fuel_quantity"],
            "fuel_unit": calculation["fuel_unit"],
            "distance": calculation["distance"],
            "distance_unit": calculation["distance_unit"],
            "model_year": calculation["model_year"],
            "gwp_version": "AR5",
        },
        "gases": calculation["gases"],
        "factors": calculation["factors"],
        "factor_source": calculation["factor_source"],
        "total_kg_co2e": calculation["total_kg_co2e"],
        "total_t_co2e": calculation["total_t_co2e"],
        "biogenic_co2_kg": calculation.get("biogenic_co2_kg"),
        "biogenic_co2_t": calculation.get("biogenic_co2_t"),
        "accounting": calculation.get("accounting") or {},
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
    if row is None or row.organization_id != organization_id:
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
    if row is None or row.organization_id != organization_id:
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
    equipment_id: Optional[str],
    site: Optional[str],
    period: str,
    activity_id: Optional[uuid.UUID],
) -> EmissionActivity:
    identifier = _optional_text(equipment_id)
    period_text = _require_period(period)

    organization_id = ctx.organization_id
    if organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No organization context; join or create an organization first",
        )

    assessment = _org_assessment(db, organization_id, assessment_id)
    _require_same_year(period_text, assessment)
    _org_counterparty(db, organization_id, counterparty_id)

    ownership = {
        "equipment_id": identifier,
        "site": _optional_text(site),
        "period": period_text,
    }
    raw = _activity_payload(calculation, ownership)
    co2_factor = calculation["factors"]["co2"]
    tonnes = Decimal(calculation["total_t_co2e"])
    quantity = Decimal(calculation["fuel_quantity"])

    if activity_id is None:
        row = EmissionActivity(
            id=uuid.uuid4(),
            assessment_id=assessment_id,
            organization_id=organization_id,
            user_id=ctx.user.id,
            scope=1,
            category=MOBILE_CATEGORY,
            method=MOBILE_METHOD,
            legacy_source=MOBILE_LEGACY_SOURCE,
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
        if row is None or row.organization_id != organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Emission activity not found",
            )
        if row.method != MOBILE_METHOD or row.legacy_source != MOBILE_LEGACY_SOURCE:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This record was not created by the mobile combustion calculator",
            )
        row.assessment_id = assessment_id

    row.counterparty_id = counterparty_id
    row.quantity = quantity
    row.unit = calculation["fuel_unit"]
    row.factor_dataset_id = _uuid_or_none(co2_factor.get("dataset_id"))
    row.factor_row_id = _uuid_or_none(co2_factor.get("factor_row_id"))
    row.emissions_tco2e = tonnes
    row.raw = raw
    row.scope = 1
    row.category = MOBILE_CATEGORY
    row.method = MOBILE_METHOD
    row.legacy_source = MOBILE_LEGACY_SOURCE
    return row


def save_epa_mobile_record(
    db: Session,
    ctx: OrgContext,
    *,
    sheets: Sequence[Mapping[str, Any]],
    road_class: str,
    vehicle_type: str,
    fuel_type: str,
    fuel_quantity: Any,
    fuel_unit: str,
    assessment_id: uuid.UUID,
    period: str,
    equipment_id: Optional[str] = None,
    distance: Any = None,
    distance_unit: Optional[str] = None,
    model_year: Any = None,
    gwp_version: str = "AR5",
    counterparty_id: Optional[uuid.UUID] = None,
    site: Optional[str] = None,
    activity_id: Optional[uuid.UUID] = None,
    factor: Any = None,
    emissions: Any = None,
    emissions_kg: Any = None,
    emissions_tco2e: Any = None,
    total_kg_co2e: Any = None,
    total_t_co2e: Any = None,
) -> Dict[str, Any]:
    """Calculate, then commit one activity. Client totals and factors are discarded."""
    del factor, emissions, emissions_kg, emissions_tco2e, total_kg_co2e, total_t_co2e

    calculation = calculate_mobile_combustion(
        road_class=road_class,
        vehicle_type=vehicle_type,
        fuel_type=fuel_type,
        fuel_quantity=fuel_quantity,
        fuel_unit=fuel_unit,
        distance=distance,
        distance_unit=distance_unit,
        model_year=model_year,
        gwp_version=gwp_version,
        sheets=sheets,
    )
    if (
        not calculation.get("success")
        or calculation.get("review_required")
        or calculation.get("total_t_co2e") is None
        or calculation.get("gases") is None
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=calculation.get("error") or "EPA mobile combustion calculation failed",
        )

    try:
        row = _stage_record(
            db,
            ctx,
            calculation,
            assessment_id=assessment_id,
            counterparty_id=counterparty_id,
            equipment_id=equipment_id,
            site=site,
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
            detail="Could not save mobile combustion record",
        ) from exc

    db.refresh(row)
    return {
        "activity_id": str(row.id),
        "assessment_id": str(row.assessment_id),
        "organization_id": str(row.organization_id),
        "counterparty_id": str(row.counterparty_id) if row.counterparty_id else None,
        "emissions_tco2e": calculation["total_t_co2e"],
        "biogenic_co2_t": calculation["biogenic_co2_t"],
        "calculation": calculation,
        "raw": row.raw,
    }
