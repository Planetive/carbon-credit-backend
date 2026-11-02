"""Persist EPA purchased heat and steam on app.emission_activities."""

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
from .scope2_heat_steam import ACCOUNTING_VERSION, CATEGORY, METHOD, calculate_purchased_heat_steam

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
    return {
        "calc": ACCOUNTING_VERSION,
        "activity_meta": {
            "activity_group": CATEGORY,
            "period": calculation["period"],
            "method_version": ACCOUNTING_VERSION,
            "energy_form": calculation["energy_form"],
        },
        "inputs": {
            "energy_form": calculation["energy_form"],
            "quantity": calculation["quantity"],
            "unit": calculation["unit"],
            "supplier_name": calculation["supplier_name"],
        },
        "on_site_combustion": {
            "included": False,
            "note": "On-site fuel combustion is Scope 1 and is not part of this purchased-energy record.",
        },
        "factor": calculation["factor"],
        "factor_source": calculation["factor"],
        "gases": calculation["gases"],
        "total_kg_co2e": calculation["total_kg_co2e"],
        "total_t_co2e": calculation["total_t_co2e"],
        "methodology": calculation["methodology"],
        "accounting": calculation["accounting"],
    }


def save_scope2_heat_steam_record(
    db: Session,
    ctx: OrgContext,
    *,
    energy_form: str,
    quantity: Any,
    unit: str,
    period: str,
    assessment_id: uuid.UUID,
    counterparty_id: Optional[uuid.UUID] = None,
    supplier_name: Optional[str] = None,
    activity_id: Optional[uuid.UUID] = None,
    co2_factor: Any = None,
    ch4_factor: Any = None,
    n2o_factor: Any = None,
    emission_factor: Any = None,
    emissions_tco2e: Any = None,
) -> Dict[str, Any]:
    calculation = calculate_purchased_heat_steam(
        energy_form=energy_form,
        quantity=quantity,
        unit=unit,
        period=period,
        supplier_name=supplier_name,
        co2_factor=co2_factor,
        ch4_factor=ch4_factor,
        n2o_factor=n2o_factor,
        emission_factor=emission_factor,
        emissions_tco2e=emissions_tco2e,
    )
    if not calculation.get("ok") or not calculation.get("save_allowed"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=calculation.get("error") or "Purchased heat or steam could not be verified.",
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
                method=METHOD,
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
            if row.method != METHOD or row.legacy_source != ACCOUNTING_VERSION:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="This record was not created by the purchased heat and steam calculator",
                )

        row.counterparty_id = counterparty_id
        row.quantity = Decimal(calculation["quantity"])
        row.unit = calculation["unit"]
        row.factor_dataset_id = None
        row.factor_row_id = None
        row.emissions_tco2e = tonnes
        row.raw = raw
        row.scope = 2
        row.category = CATEGORY
        row.method = METHOD
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
            detail="Could not save purchased heat or steam record",
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
