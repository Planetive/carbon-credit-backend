"""Persist UK purchased electricity and heat on app.emission_activities."""

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
from .scope2_uk_electricity import (
    ACCOUNTING_VERSION as ELECTRICITY_VERSION,
    CATEGORY as ELECTRICITY_CATEGORY,
    LOCATION_METHOD,
    calculate_uk_location_electricity,
)
from .scope2_uk_heat_steam import (
    ACCOUNTING_VERSION as HEAT_VERSION,
    CATEGORY as HEAT_CATEGORY,
    METHOD as HEAT_METHOD,
    calculate_uk_purchased_heat_steam,
)

_YEAR_MIN = 1990
_YEAR_MAX = 2200


def _reporting_year(value: Optional[str]) -> Optional[int]:
    text = (value or "").strip()
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
    if row.framework != "uk":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This purchased-energy record belongs on a UK assessment",
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


def _store(
    db: Session,
    ctx: OrgContext,
    *,
    calculation: Dict[str, Any],
    assessment_id: uuid.UUID,
    counterparty_id: Optional[uuid.UUID],
    activity_id: Optional[uuid.UUID],
    category: str,
    method: str,
    version: str,
    raw: Dict[str, Any],
    failure: str,
) -> Dict[str, Any]:
    if not calculation.get("ok") or not calculation.get("save_allowed"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=calculation.get("error") or failure,
        )
    organization_id = ctx.organization_id
    if organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No organization context; join or create an organization first",
        )
    try:
        assessment = _assessment(db, organization_id, assessment_id)
        activity_year = int(calculation["period"][:4])
        if _reporting_year(assessment.reporting_period) != activity_year:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"period {calculation['period']} does not match the assessment reporting year",
            )
        _counterparty(db, organization_id, counterparty_id)
        factor = calculation["factor"]
        tonnes = Decimal(calculation["total_t_co2e"])
        if activity_id is None:
            row = EmissionActivity(
                id=uuid.uuid4(),
                assessment_id=assessment_id,
                organization_id=organization_id,
                user_id=ctx.user.id,
                scope=2,
                category=category,
                method=method,
                legacy_source=version,
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
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Emission activity not found")
            if row.method != method or row.legacy_source != version:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="This record was not created by the UK purchased-energy calculator",
                )
        row.counterparty_id = counterparty_id
        row.quantity = Decimal(calculation["quantity"])
        row.unit = calculation["unit"]
        row.factor_dataset_id = uuid.UUID(factor["dataset_id"])
        row.factor_row_id = uuid.UUID(factor["factor_row_id"])
        row.emissions_tco2e = tonnes
        row.raw = raw
        row.scope = 2
        row.category = category
        row.method = method
        row.legacy_source = version
        db.flush()
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except (IntegrityError, SQLAlchemyError) as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=failure) from exc

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


def _electricity_raw(calculation: Dict[str, Any]) -> Dict[str, Any]:
    factor = calculation["factor"]
    return {
        "calc": ELECTRICITY_VERSION,
        "activity_meta": {
            "activity_group": ELECTRICITY_CATEGORY,
            "period": calculation["period"],
            "method_version": ELECTRICITY_VERSION,
            "country": calculation["country"],
            "grid_region": calculation["grid_region"],
        },
        "inputs": {
            "quantity": calculation["quantity"],
            "unit": calculation["unit"],
            "electricity_kwh": calculation["electricity_kwh"],
            "country": calculation["country"],
            "grid_region": calculation["grid_region"],
        },
        "contractual_renewable": {
            "kwh": calculation["renewable_kwh"],
            "applied_to_location_total": False,
        },
        "on_site_generation": {
            "included": False,
            "note": "Fuel burned by the organisation is Scope 1 and is not part of this purchased-electricity record.",
        },
        "factor": factor,
        "factor_source": factor,
        "gases": calculation["gases"],
        "total_kg_co2e": calculation["total_kg_co2e"],
        "total_t_co2e": calculation["total_t_co2e"],
        "methodology": calculation["methodology"],
        "accounting": calculation["accounting"],
    }


def _heat_raw(calculation: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "calc": HEAT_VERSION,
        "activity_meta": {
            "activity_group": HEAT_CATEGORY,
            "period": calculation["period"],
            "method_version": HEAT_VERSION,
            "energy_form": calculation["energy_form"],
            "country": calculation["country"],
        },
        "inputs": {
            "energy_form": calculation["energy_form"],
            "quantity": calculation["quantity"],
            "unit": calculation["unit"],
            "supplier_name": calculation["supplier_name"],
            "country": calculation["country"],
        },
        "on_site_combustion": {"included": False},
        "factor": calculation["factor"],
        "factor_source": calculation["factor"],
        "gases": calculation["gases"],
        "total_kg_co2e": calculation["total_kg_co2e"],
        "total_t_co2e": calculation["total_t_co2e"],
        "methodology": calculation["methodology"],
        "accounting": calculation["accounting"],
    }


def save_uk_electricity_record(db: Session, ctx: OrgContext, *, activity_id: Optional[uuid.UUID] = None, **kwargs: Any) -> Dict[str, Any]:
    assessment_id = kwargs.pop("assessment_id")
    counterparty_id = kwargs.pop("counterparty_id", None)
    calculation = calculate_uk_location_electricity(db, **kwargs)
    return _store(
        db,
        ctx,
        calculation=calculation,
        assessment_id=assessment_id,
        counterparty_id=counterparty_id,
        activity_id=activity_id,
        category=ELECTRICITY_CATEGORY,
        method=LOCATION_METHOD,
        version=ELECTRICITY_VERSION,
        raw=_electricity_raw(calculation) if calculation.get("ok") else {},
        failure="Could not save purchased electricity record",
    )


def save_uk_heat_steam_record(db: Session, ctx: OrgContext, *, activity_id: Optional[uuid.UUID] = None, **kwargs: Any) -> Dict[str, Any]:
    assessment_id = kwargs.pop("assessment_id")
    counterparty_id = kwargs.pop("counterparty_id", None)
    calculation = calculate_uk_purchased_heat_steam(db, **kwargs)
    return _store(
        db,
        ctx,
        calculation=calculation,
        assessment_id=assessment_id,
        counterparty_id=counterparty_id,
        activity_id=activity_id,
        category=HEAT_CATEGORY,
        method=HEAT_METHOD,
        version=HEAT_VERSION,
        raw=_heat_raw(calculation) if calculation.get("ok") else {},
        failure="Could not save purchased heat or steam record",
    )
