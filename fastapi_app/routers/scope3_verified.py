"""Verified Scope 3 calc + persist routes (server-authoritative)."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ..auth_org import OrgContext, require_org_context
from ..db import get_db
from ..ghg_calc.scope3_records import save_scope3_record
from ..ghg_calc.scope3_verified_calc import (
    calculate_verified_business_travel,
    calculate_verified_employee_commuting,
    calculate_verified_freight,
    calculate_verified_spend,
    calculate_verified_waste,
)

router = APIRouter(prefix="/calc/scope3", tags=["scope3-verified"])


def _raise(result: Dict[str, Any]) -> Dict[str, Any]:
    if not result.get("ok"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=result.get("error") or "Scope 3 calculation failed",
        )
    return result


class FreightRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    vehicle_type: str
    distance_km: float
    weight_kg: float = 0
    period: str
    # Ignored if sent by clients
    co2_factor: Optional[float] = None
    emissions: Optional[float] = None
    emissions_kg: Optional[float] = None


class FreightSaveRequest(FreightRequest):
    assessment_id: uuid.UUID
    counterparty_id: Optional[uuid.UUID] = None
    activity_id: Optional[uuid.UUID] = None
    client_entry_id: Optional[str] = None
    category: str = Field(
        default="upstream_transportation",
        description="upstream_transportation or downstream_transportation",
    )


class TravelRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    vehicle_type: str
    distance_km: float
    period: str
    co2_factor: Optional[float] = None
    emissions: Optional[float] = None


class TravelSaveRequest(TravelRequest):
    assessment_id: uuid.UUID
    counterparty_id: Optional[uuid.UUID] = None
    activity_id: Optional[uuid.UUID] = None
    client_entry_id: Optional[str] = None


class CommuteRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    vehicle_type: str
    distance_km: float
    employees: float
    period: str
    distance_basis: Optional[str] = "annual_total"
    working_days_per_year: Optional[float] = None
    co2_factor: Optional[float] = None
    emissions: Optional[float] = None


class CommuteSaveRequest(CommuteRequest):
    assessment_id: uuid.UUID
    counterparty_id: Optional[uuid.UUID] = None
    activity_id: Optional[uuid.UUID] = None
    client_entry_id: Optional[str] = None


class WasteRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    material: str
    disposal_method: str
    mass_kg: float
    period: str
    factor: Optional[float] = None
    emissions: Optional[float] = None


class WasteSaveRequest(WasteRequest):
    assessment_id: uuid.UUID
    counterparty_id: Optional[uuid.UUID] = None
    activity_id: Optional[uuid.UUID] = None
    client_entry_id: Optional[str] = None
    category: str = Field(
        default="waste_generated",
        description="waste_generated or end_of_life",
    )


class SpendRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    amount: float
    period: str
    supplier_id: Optional[str] = None
    supplier_code: Optional[str] = None
    activity_currency: str = "USD"
    activity_price_year: int = 2022
    category: str = "purchased_goods"
    emission_factor: Optional[float] = None
    emissions: Optional[float] = None


class SpendSaveRequest(SpendRequest):
    assessment_id: uuid.UUID
    counterparty_id: Optional[uuid.UUID] = None
    activity_id: Optional[uuid.UUID] = None
    client_entry_id: Optional[str] = None


@router.post("/freight")
def calc_freight(
    body: FreightRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _ = ctx
    return _raise(
        calculate_verified_freight(
            db,
            vehicle_type=body.vehicle_type,
            distance_km=body.distance_km,
            weight_kg=body.weight_kg,
            period=body.period,
            client_co2_factor=body.co2_factor,
            client_emissions=body.emissions or body.emissions_kg,
        )
    )


@router.post("/freight/records", status_code=status.HTTP_201_CREATED)
def save_freight(
    body: FreightSaveRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    calc = calculate_verified_freight(
        db,
        vehicle_type=body.vehicle_type,
        distance_km=body.distance_km,
        weight_kg=body.weight_kg,
        period=body.period,
        client_co2_factor=body.co2_factor,
        client_emissions=body.emissions or body.emissions_kg,
    )
    if body.category not in ("upstream_transportation", "downstream_transportation"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="category must be upstream_transportation or downstream_transportation",
        )
    return save_scope3_record(
        db,
        ctx,
        calculation=calc,
        assessment_id=body.assessment_id,
        counterparty_id=body.counterparty_id,
        activity_id=body.activity_id,
        client_entry_id=body.client_entry_id,
        category_override=body.category,
    )


@router.post("/business-travel")
def calc_travel(
    body: TravelRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _ = ctx
    return _raise(
        calculate_verified_business_travel(
            db,
            vehicle_type=body.vehicle_type,
            distance_km=body.distance_km,
            period=body.period,
            client_co2_factor=body.co2_factor,
            client_emissions=body.emissions,
        )
    )


@router.post("/business-travel/records", status_code=status.HTTP_201_CREATED)
def save_travel(
    body: TravelSaveRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    calc = calculate_verified_business_travel(
        db,
        vehicle_type=body.vehicle_type,
        distance_km=body.distance_km,
        period=body.period,
        client_co2_factor=body.co2_factor,
        client_emissions=body.emissions,
    )
    return save_scope3_record(
        db,
        ctx,
        calculation=calc,
        assessment_id=body.assessment_id,
        counterparty_id=body.counterparty_id,
        activity_id=body.activity_id,
        client_entry_id=body.client_entry_id,
    )


@router.post("/employee-commuting")
def calc_commute(
    body: CommuteRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _ = ctx
    return _raise(
        calculate_verified_employee_commuting(
            db,
            vehicle_type=body.vehicle_type,
            distance_km=body.distance_km,
            employees=body.employees,
            period=body.period,
            distance_basis=body.distance_basis,
            working_days_per_year=body.working_days_per_year,
            client_co2_factor=body.co2_factor,
            client_emissions=body.emissions,
        )
    )


@router.post("/employee-commuting/records", status_code=status.HTTP_201_CREATED)
def save_commute(
    body: CommuteSaveRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    calc = calculate_verified_employee_commuting(
        db,
        vehicle_type=body.vehicle_type,
        distance_km=body.distance_km,
        employees=body.employees,
        period=body.period,
        distance_basis=body.distance_basis,
        working_days_per_year=body.working_days_per_year,
        client_co2_factor=body.co2_factor,
        client_emissions=body.emissions,
    )
    return save_scope3_record(
        db,
        ctx,
        calculation=calc,
        assessment_id=body.assessment_id,
        counterparty_id=body.counterparty_id,
        activity_id=body.activity_id,
        client_entry_id=body.client_entry_id,
    )


@router.post("/waste")
def calc_waste(
    body: WasteRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _ = ctx
    return _raise(
        calculate_verified_waste(
            db,
            material=body.material,
            disposal_method=body.disposal_method,
            mass_kg=body.mass_kg,
            period=body.period,
            client_factor=body.factor,
            client_emissions=body.emissions,
        )
    )


@router.post("/waste/records", status_code=status.HTTP_201_CREATED)
def save_waste(
    body: WasteSaveRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    calc = calculate_verified_waste(
        db,
        material=body.material,
        disposal_method=body.disposal_method,
        mass_kg=body.mass_kg,
        period=body.period,
        client_factor=body.factor,
        client_emissions=body.emissions,
    )
    if body.category not in ("waste_generated", "end_of_life"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="category must be waste_generated or end_of_life",
        )
    return save_scope3_record(
        db,
        ctx,
        calculation=calc,
        assessment_id=body.assessment_id,
        counterparty_id=body.counterparty_id,
        activity_id=body.activity_id,
        client_entry_id=body.client_entry_id,
        category_override=body.category,
    )


@router.post("/spend")
def calc_spend(
    body: SpendRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _ = ctx
    return _raise(
        calculate_verified_spend(
            db,
            amount=body.amount,
            period=body.period,
            category=body.category,
            supplier_id=body.supplier_id,
            supplier_code=body.supplier_code,
            activity_currency=body.activity_currency,
            activity_price_year=body.activity_price_year,
            client_emission_factor=body.emission_factor,
            client_emissions=body.emissions,
        )
    )


@router.post("/spend/records", status_code=status.HTTP_201_CREATED)
def save_spend(
    body: SpendSaveRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    calc = calculate_verified_spend(
        db,
        amount=body.amount,
        period=body.period,
        category=body.category,
        supplier_id=body.supplier_id,
        supplier_code=body.supplier_code,
        activity_currency=body.activity_currency,
        activity_price_year=body.activity_price_year,
        client_emission_factor=body.emission_factor,
        client_emissions=body.emissions,
    )
    return save_scope3_record(
        db,
        ctx,
        calculation=calc,
        assessment_id=body.assessment_id,
        counterparty_id=body.counterparty_id,
        activity_id=body.activity_id,
        client_entry_id=body.client_entry_id,
        category_override=body.category,
    )
