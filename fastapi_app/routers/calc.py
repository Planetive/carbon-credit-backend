"""
GHG calc endpoints — SPA FuelEmissions math, optional persist to emission_activities.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth_org import OrgContext
from ..db import get_db
from ..factor_service import (
    factor_row_to_legacy_record,
    get_row_by_id,
    load_legacy_sheet,
    load_legacy_sheets,
)
from ..ghg_calc.epa_fuel import build_epa_fuel_map, calculate_epa_fuel
from ..ghg_calc.uk_fuel import build_uk_factors_map, calculate_uk_fuel
from ..ghg_models import EmissionActivity, EmissionAssessment
from .deps import require_org_context

router = APIRouter(prefix="/calc", tags=["calc"])


class UkFuelCalcRequest(BaseModel):
    quantity: float
    activity: Optional[str] = None
    fuel: Optional[str] = None
    unit: Optional[str] = None
    uk_factor_basis: str = Field(default="total")
    factor: Optional[float] = None
    factor_row_id: Optional[uuid.UUID] = None
    assessment_id: Optional[uuid.UUID] = None
    category: Optional[str] = Field(default="stationary_combustion")
    persist: bool = False


class EpaFuelCalcRequest(BaseModel):
    quantity: float
    unit: str
    category: Optional[str] = None
    fuel: Optional[str] = None
    factor: Optional[float] = None
    factor_row_id: Optional[uuid.UUID] = None
    assessment_id: Optional[uuid.UUID] = None
    persist: bool = False


class SimpleMultiplyRequest(BaseModel):
    """UK passenger / delivery / refrigerant: emissions = quantity_or_distance * factor."""

    quantity: float
    factor: float
    assessment_id: Optional[uuid.UUID] = None
    category: Optional[str] = None
    persist: bool = False
    meta: Optional[Dict[str, Any]] = None


def _persist_activity(
    db: Session,
    ctx: OrgContext,
    assessment_id: uuid.UUID,
    *,
    scope: int,
    category: str,
    method: str,
    emissions_kg: float,
    raw: Dict[str, Any],
    quantity: Optional[float] = None,
    unit: Optional[str] = None,
) -> EmissionActivity:
    assessment = (
        db.query(EmissionAssessment)
        .filter(
            EmissionAssessment.id == assessment_id,
            EmissionAssessment.organization_id == ctx.organization_id,
        )
        .first()
    )
    if not assessment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Emission assessment not found in current organization",
        )

    emissions_tco2e = Decimal(str(emissions_kg)) / Decimal("1000")
    row = EmissionActivity(
        assessment_id=assessment_id,
        organization_id=ctx.organization_id,
        user_id=ctx.user.id,
        scope=scope,
        category=category,
        method=method,
        quantity=Decimal(str(quantity)) if quantity is not None else None,
        unit=unit,
        emissions_tco2e=emissions_tco2e,
        raw=raw,
        legacy_source="api",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _factor_from_row_id(db: Session, row_id: uuid.UUID) -> Dict[str, Any]:
    row = get_row_by_id(db, row_id)
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Factor row not found"
        )
    return factor_row_to_legacy_record(row)


@router.post("/uk/fuel")
def calc_uk_fuel(
    body: UkFuelCalcRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    factor = body.factor
    factors_map = None

    if factor is None and body.factor_row_id is not None:
        legacy = _factor_from_row_id(db, body.factor_row_id)
        factors_map = build_uk_factors_map([legacy])
    elif factor is None:
        sheet = load_legacy_sheet(
            db,
            codes=["uk_fuel_factors"],
            name_hints=["UK_Fuel", "uk fuel"],
        )
        if sheet:
            factors_map = build_uk_factors_map(sheet)

    if body.uk_factor_basis not in ("total", "co2", "ch4", "n2o"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="uk_factor_basis must be one of: total, co2, ch4, n2o",
        )

    result = calculate_uk_fuel(
        quantity=body.quantity,
        activity=body.activity,
        fuel=body.fuel,
        unit=body.unit,
        uk_factor_basis=body.uk_factor_basis,  # type: ignore[arg-type]
        factor=factor,
        factors_map=factors_map,
    )
    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=result.get("error") or "UK fuel calculation failed",
        )

    activity_id = None
    if body.persist and body.assessment_id:
        act = _persist_activity(
            db,
            ctx,
            body.assessment_id,
            scope=1,
            category=body.category or "stationary_combustion",
            method="uk_fuel",
            emissions_kg=float(result["emissions_kg"]),
            quantity=body.quantity,
            unit=body.unit,
            raw={"calc": "uk_fuel", "request": body.model_dump(mode="json"), "result": result},
        )
        activity_id = str(act.id)
        result["activity_id"] = activity_id

    return result


@router.post("/epa/fuel")
def calc_epa_fuel(
    body: EpaFuelCalcRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    factor = body.factor
    factors_map = None

    if factor is None and body.factor_row_id is not None:
        legacy = _factor_from_row_id(db, body.factor_row_id)
        factors_map = build_epa_fuel_map([legacy])
    elif factor is None:
        sheet = load_legacy_sheets(
            db,
            [
                {"dataset_codes": ["fuel_epa_1"], "name_hints": ["Fuel EPA 1"]},
                {"dataset_codes": ["fuel_epa_2"], "name_hints": ["Fuel EPA 2"]},
                {"dataset_codes": ["fuel_epa_3"], "name_hints": ["Fuel EPA 3"]},
            ],
        )
        if sheet:
            factors_map = build_epa_fuel_map(sheet)

    result = calculate_epa_fuel(
        quantity=body.quantity,
        unit=body.unit,
        category=body.category,
        fuel=body.fuel,
        factor=factor,
        factors_map=factors_map,
    )
    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=result.get("error") or "EPA fuel calculation failed",
        )

    if body.persist and body.assessment_id:
        act = _persist_activity(
            db,
            ctx,
            body.assessment_id,
            scope=1,
            category="stationary_combustion",
            method="epa_fuel",
            emissions_kg=float(result["emissions_kg"]),
            quantity=body.quantity,
            unit=body.unit,
            raw={"calc": "epa_fuel", "request": body.model_dump(mode="json"), "result": result},
        )
        result["activity_id"] = str(act.id)

    return result


def _simple_multiply(quantity: float, factor: float) -> Dict[str, Any]:
    emissions_kg = float(f"{(quantity * factor):.6f}")
    return {
        "success": True,
        "emissions": emissions_kg,
        "emissions_kg": emissions_kg,
        "emissions_tco2e": float(f"{(emissions_kg / 1000.0):.9f}"),
        "factor": factor,
        "quantity": quantity,
    }


@router.post("/uk/passenger")
def calc_uk_passenger(
    body: SimpleMultiplyRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """SPA: emissions = distance * factor (round6)."""
    result = _simple_multiply(body.quantity, body.factor)
    if body.persist and body.assessment_id:
        act = _persist_activity(
            db,
            ctx,
            body.assessment_id,
            scope=1,
            category=body.category or "passenger_vehicle",
            method="uk_passenger",
            emissions_kg=float(result["emissions_kg"]),
            quantity=body.quantity,
            raw={"calc": "uk_passenger", "meta": body.meta or {}, "result": result},
        )
        result["activity_id"] = str(act.id)
    return result


@router.post("/uk/delivery")
def calc_uk_delivery(
    body: SimpleMultiplyRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """SPA: emissions = distance * factor (round6)."""
    result = _simple_multiply(body.quantity, body.factor)
    if body.persist and body.assessment_id:
        act = _persist_activity(
            db,
            ctx,
            body.assessment_id,
            scope=1,
            category=body.category or "delivery_vehicle",
            method="uk_delivery",
            emissions_kg=float(result["emissions_kg"]),
            quantity=body.quantity,
            raw={"calc": "uk_delivery", "meta": body.meta or {}, "result": result},
        )
        result["activity_id"] = str(act.id)
    return result


@router.post("/uk/refrigerant")
def calc_uk_refrigerant(
    body: SimpleMultiplyRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """SPA: emissions = quantity * factor (round6)."""
    result = _simple_multiply(body.quantity, body.factor)
    if body.persist and body.assessment_id:
        act = _persist_activity(
            db,
            ctx,
            body.assessment_id,
            scope=1,
            category=body.category or "refrigerant",
            method="uk_refrigerant",
            emissions_kg=float(result["emissions_kg"]),
            quantity=body.quantity,
            raw={"calc": "uk_refrigerant", "meta": body.meta or {}, "result": result},
        )
        result["activity_id"] = str(act.id)
    return result
