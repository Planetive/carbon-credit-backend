"""Persist location-based purchased electricity on app.emission_activities."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Dict, Optional

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from ..auth_org import OrgContext
from ..ghg_models import EmissionActivity, EmissionAssessment
from ..portfolio_models import Counterparty
from .scope2_electricity import ACCOUNTING_VERSION, CATEGORY, LOCATION_METHOD, calculate_location_electricity

_YEAR_MIN = 1990
_YEAR_MAX = 2200


def _optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


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


def _org_counterparty(db: Session, organization_id: uuid.UUID, counterparty_id: Optional[uuid.UUID]) -> None:
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


def _payload(calculation: Dict[str, Any]) -> Dict[str, Any]:
    factor = calculation["factor"]
    return {
        "calc": ACCOUNTING_VERSION,
        "activity_meta": {
            "activity_group": "purchased_electricity",
            "period": calculation["period"],
            "method_version": ACCOUNTING_VERSION,
            "country": calculation["country"],
            "grid_region": calculation["grid_region"],
        },
        "inputs": {
            "quantity": calculation["quantity"],
            "unit": calculation["unit"],
            "electricity_kwh": calculation["electricity_kwh"],
            "renewable_kwh": calculation["renewable_kwh"],
            "country": calculation["country"],
            "grid_region": calculation["grid_region"],
        },
        "contractual_renewable": {
            "kwh": calculation["renewable_kwh"],
            "applied_to_location_total": False,
        },
        "on_site_generation": {
            "included": False,
            "note": "On-site generation is not part of this purchased-electricity record.",
        },
        "factor": factor,
        "factor_source": factor,
        "gases": calculation["gases"],
        "total_kg_co2e": calculation["total_kg_co2e"],
        "total_t_co2e": calculation["total_t_co2e"],
        "methodology": calculation["methodology"],
        "accounting": calculation["accounting"],
    }


def save_scope2_electricity_record(
    db: Session,
    ctx: OrgContext,
    *,
    country: str,
    quantity: Any,
    unit: str,
    period: str,
    assessment_id: uuid.UUID,
    grid_region: str = "national",
    counterparty_id: Optional[uuid.UUID] = None,
    renewable_kwh: Any = None,
    activity_id: Optional[uuid.UUID] = None,
    grid_factor: Any = None,
    emissions_tco2e: Any = None,
) -> Dict[str, Any]:
    calculation = calculate_location_electricity(
        db,
        country=country,
        quantity=quantity,
        unit=unit,
        period=period,
        grid_region=grid_region,
        renewable_kwh=renewable_kwh,
        grid_factor=grid_factor,
        emissions_tco2e=emissions_tco2e,
    )
    if not calculation.get("ok") or not calculation.get("save_allowed"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=calculation.get("error") or "Purchased electricity could not be verified.",
        )

    organization_id = ctx.organization_id
    if organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No organization context; join or create an organization first",
        )

    try:
        assessment = _org_assessment(db, organization_id, assessment_id)
        activity_year = int(calculation["period"][:4])
        if _reporting_year(assessment.reporting_period) != activity_year:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"period {calculation['period']} does not match the assessment reporting year",
            )
        _org_counterparty(db, organization_id, counterparty_id)
        factor = calculation["factor"]
        raw = _payload(calculation)
        tonnes = Decimal(calculation["total_t_co2e"])

        if activity_id is None:
            row = EmissionActivity(
                id=uuid.uuid4(),
                assessment_id=assessment_id,
                organization_id=organization_id,
                user_id=ctx.user.id,
                scope=2,
                category=CATEGORY,
                method=LOCATION_METHOD,
                legacy_source=ACCOUNTING_VERSION,
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
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Emission activity not found")
            if row.method != LOCATION_METHOD or row.legacy_source != ACCOUNTING_VERSION:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="This record was not created by the location-based electricity calculator",
                )

        row.counterparty_id = counterparty_id
        row.quantity = Decimal(calculation["quantity"])
        row.unit = calculation["unit"]
        row.factor_dataset_id = uuid.UUID(factor["dataset_id"])
        row.factor_row_id = uuid.UUID(factor["factor_row_id"])
        row.emissions_tco2e = tonnes
        row.raw = raw
        row.scope = 2
        row.category = CATEGORY
        row.method = LOCATION_METHOD
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
            detail="Could not save purchased electricity record",
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
