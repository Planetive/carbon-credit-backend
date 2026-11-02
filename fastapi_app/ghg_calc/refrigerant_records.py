"""
Persist EPA refrigerant leakage on app.emission_activities.

Calculation runs before any insert or update. A failed calculation, a failed
ownership check, or a failed commit leaves the database unchanged. One leak is
one row. Historical refrigerant entries, UK records, and combustion records
are not updated.
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
from .refrigerant_leakage import ACCOUNTING_VERSION, calculate_refrigerant_leakage

REFRIGERANT_METHOD = "epa_refrigerant_v1"
REFRIGERANT_CATEGORY = "refrigerant_leakage"
REFRIGERANT_LEGACY_SOURCE = "epa_refrigerant_v1"
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


def _activity_payload(
    calculation: Mapping[str, Any], ownership: Mapping[str, Any]
) -> Dict[str, Any]:
    meta: Dict[str, Any] = {
        "activity_group": "refrigerant_leakage",
        "method_version": calculation.get("accounting", {}).get("version") or ACCOUNTING_VERSION,
        "period": ownership["period"],
    }
    if ownership.get("equipment_type"):
        meta["equipment_type"] = ownership["equipment_type"]
    if ownership.get("equipment_id"):
        meta["equipment_id"] = ownership["equipment_id"]
    if ownership.get("site"):
        meta["site"] = ownership["site"]

    return {
        "calc": REFRIGERANT_METHOD,
        "activity_meta": meta,
        "inputs": {
            "method": calculation["method"],
            "refrigerant": calculation["refrigerant"],
            "leakage_kg": calculation["leakage_kg"],
            "charge_kg": calculation.get("charge_kg"),
            "leakage_rate_percent": calculation.get("leakage_rate_percent"),
            "leakage_rate_source": calculation.get("leakage_rate_source"),
        },
        "gwp": calculation.get("gwp"),
        "gwp_publication": calculation.get("gwp_publication"),
        "gwp_edition": calculation.get("gwp_edition"),
        "factor_provenance": calculation.get("factor_provenance"),
        "gwp_basis": calculation.get("gwp_basis"),
        "dataset_id": calculation.get("dataset_id"),
        "factor_row_id": calculation.get("factor_row_id"),
        "dataset_code": calculation.get("dataset_code"),
        "version_label": calculation.get("version_label"),
        "factor_attribute": calculation.get("factor_attribute"),
        "table11_reference": calculation.get("table11_reference"),
        "emissions_kg_co2e": calculation.get("emissions_kg_co2e"),
        "emissions_tco2e": calculation.get("emissions_tco2e"),
        "accounting": calculation.get("accounting") or {},
    }


def _org_assessment(
    db: Session, organization_id: uuid.UUID, assessment_id: uuid.UUID
) -> EmissionAssessment:
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


def _require_same_year(period: str, assessment: EmissionAssessment) -> None:
    activity_year = int(period[:4])
    assessment_year = _reporting_year(assessment.reporting_period)
    if assessment_year is None or assessment_year != activity_year:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"period {period} does not match the assessment reporting year"
            ),
        )


def _stage_record(
    db: Session,
    ctx: OrgContext,
    calculation: Mapping[str, Any],
    *,
    assessment_id: uuid.UUID,
    counterparty_id: Optional[uuid.UUID],
    equipment_type: Optional[str],
    equipment_id: Optional[str],
    site: Optional[str],
    period: str,
    activity_id: Optional[uuid.UUID],
) -> EmissionActivity:
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
        "equipment_type": _optional_text(equipment_type),
        "equipment_id": _optional_text(equipment_id),
        "site": _optional_text(site),
        "period": period_text,
    }
    raw = _activity_payload(calculation, ownership)
    tonnes = Decimal(str(calculation["emissions_tco2e"]))
    quantity = Decimal(str(calculation["leakage_kg"]))

    if activity_id is None:
        row = EmissionActivity(
            id=uuid.uuid4(),
            assessment_id=assessment_id,
            organization_id=organization_id,
            user_id=ctx.user.id,
            scope=1,
            category=REFRIGERANT_CATEGORY,
            method=REFRIGERANT_METHOD,
            legacy_source=REFRIGERANT_LEGACY_SOURCE,
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
        if row.method != REFRIGERANT_METHOD or row.legacy_source != REFRIGERANT_LEGACY_SOURCE:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This record was not created by the refrigerant leakage calculator",
            )
        row.assessment_id = assessment_id

    row.counterparty_id = counterparty_id
    row.quantity = quantity
    row.unit = "kg"
    row.factor_dataset_id = _uuid_or_none(calculation.get("dataset_id"))
    row.factor_row_id = _uuid_or_none(calculation.get("factor_row_id"))
    row.emissions_tco2e = tonnes
    row.raw = raw
    row.scope = 1
    row.category = REFRIGERANT_CATEGORY
    row.method = REFRIGERANT_METHOD
    row.legacy_source = REFRIGERANT_LEGACY_SOURCE
    return row


def save_epa_refrigerant_record(
    db: Session,
    ctx: OrgContext,
    *,
    sheets: Sequence[Mapping[str, Any]],
    method: str,
    gas: str,
    assessment_id: uuid.UUID,
    period: str,
    leakage_kg: Any = None,
    charge_kg: Any = None,
    leakage_rate_percent: Any = None,
    equipment_type: Optional[str] = None,
    equipment_id: Optional[str] = None,
    site: Optional[str] = None,
    counterparty_id: Optional[uuid.UUID] = None,
    activity_id: Optional[uuid.UUID] = None,
    gwp: Any = None,
    factor: Any = None,
    factor_dataset_id: Any = None,
    factor_row_id: Any = None,
    emissions: Any = None,
    emissions_kg: Any = None,
    emissions_kg_co2e: Any = None,
    emissions_tco2e: Any = None,
    organization_id: Any = None,
    **_ignored: Any,
) -> Dict[str, Any]:
    """Calculate, then commit one activity. Client totals, GWP, and organization are discarded."""
    del (
        gwp,
        factor,
        factor_dataset_id,
        factor_row_id,
        emissions,
        emissions_kg,
        emissions_kg_co2e,
        emissions_tco2e,
        organization_id,
        _ignored,
    )

    try:
        calculation = calculate_refrigerant_leakage(
            method=method,
            gas=gas,
            leakage_kg=leakage_kg,
            charge_kg=charge_kg,
            leakage_rate_percent=leakage_rate_percent,
            equipment_type=equipment_type,
            sheets=sheets,
        )
        if not calculation.get("success") or calculation.get("emissions_tco2e") is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=calculation.get("error") or "EPA refrigerant leakage calculation failed",
            )
        row = _stage_record(
            db,
            ctx,
            calculation,
            assessment_id=assessment_id,
            counterparty_id=counterparty_id,
            equipment_type=equipment_type,
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
            detail="Could not save refrigerant leakage record",
        ) from exc

    db.refresh(row)
    return {
        "activity_id": str(row.id),
        "assessment_id": str(row.assessment_id),
        "organization_id": str(row.organization_id),
        "counterparty_id": str(row.counterparty_id) if row.counterparty_id else None,
        "emissions_kg_co2e": calculation["emissions_kg_co2e"],
        "emissions_tco2e": calculation["emissions_tco2e"],
        "calculation": calculation,
        "raw": row.raw,
    }
