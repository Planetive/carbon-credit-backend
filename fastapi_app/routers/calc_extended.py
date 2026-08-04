"""
Extended GHG calc routes — electricity, EPA refrigerant, Scope 3, IPCC.
Same auth/persist conventions as routers/calc.py.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth_org import OrgContext
from ..db import get_db
from ..ghg_calc.electricity import calculate_electricity
from ..ghg_calc.epa_refrigerant import calculate_epa_refrigerant
from ..ghg_calc.ipcc_flaring import calculate_ipcc_flaring
from ..ghg_calc.ipcc_operational import (
    calculate_ipcc_heating,
    calculate_ipcc_kitchen,
    calculate_ipcc_power,
    calculate_ipcc_vehicular,
)
from ..ghg_calc.ipcc_road import (
    calculate_ipcc_alt_fuel,
    calculate_ipcc_industry,
    calculate_ipcc_road,
    calculate_ipcc_road_vehicle,
    calculate_ipcc_usa_vehicles,
)
from ..ghg_calc.ipcc_stationary import calculate_ipcc_stationary
from ..ghg_calc.ipcc_venting import calculate_ipcc_venting
from ..ghg_calc.leased_assets import (
    calculate_leased_category_total,
    calculate_leased_electricity,
    calculate_leased_refrigerant,
    calculate_leased_transport_row,
)
from ..ghg_calc.scope3_simple import (
    calculate_business_travel,
    calculate_employee_commuting,
    calculate_freight,
    calculate_spend_based,
)
from ..ghg_calc.sold_products import (
    calculate_sold_products_electricity,
    calculate_sold_products_hybrid,
    calculate_sold_products_qty_factor,
)
from ..ghg_models import EmissionActivity, EmissionAssessment
from .deps import require_org_context

router = APIRouter(prefix="/calc", tags=["calc"])


def _persist(
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
    row = EmissionActivity(
        assessment_id=assessment_id,
        organization_id=ctx.organization_id,
        user_id=ctx.user.id,
        scope=scope,
        category=category,
        method=method,
        quantity=Decimal(str(quantity)) if quantity is not None else None,
        unit=unit,
        emissions_tco2e=Decimal(str(emissions_kg)) / Decimal("1000"),
        raw=raw,
        legacy_source="api",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _ok(result: Dict[str, Any], label: str) -> Dict[str, Any]:
    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=result.get("error") or f"{label} calculation failed",
        )
    return result


class ElectricityRequest(BaseModel):
    total_kwh: float
    grid_pct: Optional[float] = None
    grid_factor: Optional[float] = None
    other_pct: Optional[float] = None
    other_row_emissions_sum: Optional[float] = None
    renewable_pct: Optional[float] = None
    assessment_id: Optional[uuid.UUID] = None
    persist: bool = False


class EpaRefrigerantRequest(BaseModel):
    method: str
    gwp: float
    leakage_kg: Optional[float] = None
    charge_kg: Optional[float] = None
    leakage_rate_percent: Optional[float] = None
    assessment_id: Optional[uuid.UUID] = None
    persist: bool = False


class FreightRequest(BaseModel):
    distance: float
    weight: float
    co2_factor: float
    assessment_id: Optional[uuid.UUID] = None
    persist: bool = False


class BusinessTravelRequest(BaseModel):
    distance: float
    co2_factor: float
    unit: Optional[str] = None
    assessment_id: Optional[uuid.UUID] = None
    persist: bool = False


class CommutingRequest(BaseModel):
    employees: float
    distance: float
    co2_factor: float
    unit: Optional[str] = None
    assessment_id: Optional[uuid.UUID] = None
    persist: bool = False


class SpendBasedRequest(BaseModel):
    amount: float
    emission_factor: float
    category: str = "purchased_goods"
    assessment_id: Optional[uuid.UUID] = None
    persist: bool = False


class QtyFactorRequest(BaseModel):
    quantity: float
    factor: float
    assessment_id: Optional[uuid.UUID] = None
    persist: bool = False


class SoldElecRequest(BaseModel):
    total_kwh: float
    grid_pct: Optional[float] = None
    grid_factor: Optional[float] = None
    other_pct: Optional[float] = None
    other_row_emissions_sum: Optional[float] = None
    assessment_id: Optional[uuid.UUID] = None
    persist: bool = False


class LeasedTotalRequest(BaseModel):
    category: str
    electricity_kg: Optional[float] = None
    transport_rows_kg: Optional[List[float]] = None
    refrigerant_kg: Optional[float] = None
    assessment_id: Optional[uuid.UUID] = None
    persist: bool = False


class IpccStationaryRequest(BaseModel):
    quantity: float
    factor: float
    assessment_id: Optional[uuid.UUID] = None
    persist: bool = False


class IpccFlaringRequest(BaseModel):
    volume: float
    unit: str = "m3"
    composition: List[Dict[str, Any]]
    assessment_id: Optional[uuid.UUID] = None
    persist: bool = False


class IpccVentingRequest(BaseModel):
    volume: float
    unit: str = "m3"
    composition: List[Dict[str, Any]]
    assessment_id: Optional[uuid.UUID] = None
    persist: bool = False


class IpccVehicularRequest(BaseModel):
    diesel_liters: float = 0
    petrol_liters: float = 0
    diesel_factor: Optional[float] = None
    petrol_factor: Optional[float] = None
    assessment_id: Optional[uuid.UUID] = None
    persist: bool = False


class IpccKitchenRequest(BaseModel):
    lpg_kg: float = 0
    ng_mmscf: float = 0
    ghv: float = 0
    lpg_factor: Optional[float] = None
    natural_gas_co2: Optional[float] = None
    assessment_id: Optional[uuid.UUID] = None
    persist: bool = False


class IpccPowerRequest(BaseModel):
    diesel_liters: float = 0
    ng_mmscf: float = 0
    ghv: float = 0
    diesel_factor: Optional[float] = None
    natural_gas_co2: Optional[float] = None
    assessment_id: Optional[uuid.UUID] = None
    persist: bool = False


class IpccHeatingRequest(BaseModel):
    ng_mmscf: float = 0
    ghv: float = 0
    natural_gas_co2: Optional[float] = None
    assessment_id: Optional[uuid.UUID] = None
    persist: bool = False


class IpccRoadVehicleRequest(BaseModel):
    quantity: float
    ch4_factor: Optional[float] = None
    n2o_factor: Optional[float] = None
    selected_factor: str = "CH4"
    assessment_id: Optional[uuid.UUID] = None
    persist: bool = False


class IpccIndustryRequest(BaseModel):
    quantity: float
    ef_co2: Optional[float] = None
    ef_ch4: Optional[float] = None
    ef_n2o: Optional[float] = None
    selected_factor: str = "CO2"
    assessment_id: Optional[uuid.UUID] = None
    persist: bool = False


@router.post("/electricity")
def calc_electricity(
    body: ElectricityRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    result = _ok(
        calculate_electricity(
            total_kwh=body.total_kwh,
            grid_pct=body.grid_pct,
            grid_factor=body.grid_factor,
            other_pct=body.other_pct,
            other_row_emissions_sum=body.other_row_emissions_sum,
            renewable_pct=body.renewable_pct,
        ),
        "Electricity",
    )
    if body.persist and body.assessment_id:
        act = _persist(
            db,
            ctx,
            body.assessment_id,
            scope=2,
            category="electricity",
            method="electricity",
            emissions_kg=float(result["emissions_kg"]),
            quantity=body.total_kwh,
            unit="kWh",
            raw={"calc": "electricity", "request": body.model_dump(mode="json"), "result": result},
        )
        result["activity_id"] = str(act.id)
    return result


@router.post("/epa/refrigerant")
def calc_epa_refrigerant(
    body: EpaRefrigerantRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    if body.method not in ("leakage_record", "estimated_leakage"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="method must be leakage_record or estimated_leakage",
        )
    result = _ok(
        calculate_epa_refrigerant(
            method=body.method,  # type: ignore[arg-type]
            gwp=body.gwp,
            leakage_kg=body.leakage_kg,
            charge_kg=body.charge_kg,
            leakage_rate_percent=body.leakage_rate_percent,
        ),
        "EPA refrigerant",
    )
    if body.persist and body.assessment_id:
        act = _persist(
            db,
            ctx,
            body.assessment_id,
            scope=1,
            category="refrigerant",
            method="epa_refrigerant",
            emissions_kg=float(result["emissions_kg"]),
            quantity=result.get("leakage_kg"),
            unit="kg",
            raw={"calc": "epa_refrigerant", "request": body.model_dump(mode="json"), "result": result},
        )
        result["activity_id"] = str(act.id)
    return result


@router.post("/freight")
def calc_freight(
    body: FreightRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    result = _ok(
        calculate_freight(
            distance=body.distance, weight=body.weight, co2_factor=body.co2_factor
        ),
        "Freight",
    )
    if body.persist and body.assessment_id:
        act = _persist(
            db,
            ctx,
            body.assessment_id,
            scope=3,
            category="freight",
            method="freight",
            emissions_kg=float(result["emissions_kg"]),
            quantity=body.distance,
            raw={"calc": "freight", "request": body.model_dump(mode="json"), "result": result},
        )
        result["activity_id"] = str(act.id)
    return result


@router.post("/business-travel")
def calc_business_travel(
    body: BusinessTravelRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    result = _ok(
        calculate_business_travel(
            distance=body.distance, co2_factor=body.co2_factor, unit=body.unit
        ),
        "Business travel",
    )
    if body.persist and body.assessment_id:
        act = _persist(
            db,
            ctx,
            body.assessment_id,
            scope=3,
            category="business_travel",
            method="business_travel",
            emissions_kg=float(result["emissions_kg"]),
            quantity=body.distance,
            unit=body.unit,
            raw={
                "calc": "business_travel",
                "request": body.model_dump(mode="json"),
                "result": result,
            },
        )
        result["activity_id"] = str(act.id)
    return result


@router.post("/employee-commuting")
def calc_employee_commuting(
    body: CommutingRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    result = _ok(
        calculate_employee_commuting(
            employees=body.employees,
            distance=body.distance,
            co2_factor=body.co2_factor,
            unit=body.unit,
        ),
        "Employee commuting",
    )
    if body.persist and body.assessment_id:
        act = _persist(
            db,
            ctx,
            body.assessment_id,
            scope=3,
            category="employee_commuting",
            method="employee_commuting",
            emissions_kg=float(result["emissions_kg"]),
            quantity=body.distance,
            unit=body.unit,
            raw={
                "calc": "employee_commuting",
                "request": body.model_dump(mode="json"),
                "result": result,
            },
        )
        result["activity_id"] = str(act.id)
    return result


@router.post("/spend-based")
def calc_spend_based(
    body: SpendBasedRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    result = _ok(
        calculate_spend_based(amount=body.amount, emission_factor=body.emission_factor),
        "Spend-based",
    )
    if body.persist and body.assessment_id:
        act = _persist(
            db,
            ctx,
            body.assessment_id,
            scope=3,
            category=body.category or "purchased_goods",
            method="spend_based",
            emissions_kg=float(result["emissions_kg"]),
            quantity=body.amount,
            raw={
                "calc": "spend_based",
                "request": body.model_dump(mode="json"),
                "result": result,
            },
        )
        result["activity_id"] = str(act.id)
    return result


@router.post("/sold-products/qty-factor")
def calc_sold_qty_factor(
    body: QtyFactorRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    result = _ok(
        calculate_sold_products_qty_factor(quantity=body.quantity, factor=body.factor),
        "Sold products",
    )
    if body.persist and body.assessment_id:
        act = _persist(
            db,
            ctx,
            body.assessment_id,
            scope=3,
            category="sold_products",
            method="sold_products_qty_factor",
            emissions_kg=float(result["emissions_kg"]),
            quantity=body.quantity,
            raw={
                "calc": "sold_products_qty_factor",
                "request": body.model_dump(mode="json"),
                "result": result,
            },
        )
        result["activity_id"] = str(act.id)
    return result


@router.post("/sold-products/electricity")
def calc_sold_electricity(
    body: SoldElecRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    result = _ok(
        calculate_sold_products_electricity(
            total_kwh=body.total_kwh,
            grid_pct=body.grid_pct,
            grid_factor=body.grid_factor,
            other_pct=body.other_pct,
            other_row_emissions_sum=body.other_row_emissions_sum,
        ),
        "Sold products electricity",
    )
    if body.persist and body.assessment_id:
        act = _persist(
            db,
            ctx,
            body.assessment_id,
            scope=3,
            category="sold_products",
            method="sold_products_electricity",
            emissions_kg=float(result["emissions_kg"]),
            quantity=body.total_kwh,
            unit="kWh",
            raw={
                "calc": "sold_products_electricity",
                "request": body.model_dump(mode="json"),
                "result": result,
            },
        )
        result["activity_id"] = str(act.id)
    return result


@router.post("/leased/electricity")
def calc_leased_electricity(
    body: SoldElecRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    result = _ok(
        calculate_leased_electricity(
            total_kwh=body.total_kwh,
            grid_pct=body.grid_pct,
            grid_factor=body.grid_factor,
            other_pct=body.other_pct,
            other_row_emissions_sum=body.other_row_emissions_sum,
        ),
        "Leased electricity",
    )
    if body.persist and body.assessment_id:
        act = _persist(
            db,
            ctx,
            body.assessment_id,
            scope=3,
            category="leased_assets",
            method="leased_electricity",
            emissions_kg=float(result["emissions_kg"]),
            quantity=body.total_kwh,
            unit="kWh",
            raw={
                "calc": "leased_electricity",
                "request": body.model_dump(mode="json"),
                "result": result,
            },
        )
        result["activity_id"] = str(act.id)
    return result


@router.post("/leased/transport")
def calc_leased_transport(
    body: QtyFactorRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    # quantity field = distance
    result = _ok(
        calculate_leased_transport_row(distance=body.quantity, factor=body.factor),
        "Leased transport",
    )
    if body.persist and body.assessment_id:
        act = _persist(
            db,
            ctx,
            body.assessment_id,
            scope=3,
            category="leased_assets",
            method="leased_transport",
            emissions_kg=float(result["emissions_kg"]),
            quantity=body.quantity,
            raw={
                "calc": "leased_transport",
                "request": body.model_dump(mode="json"),
                "result": result,
            },
        )
        result["activity_id"] = str(act.id)
    return result


@router.post("/leased/refrigerant")
def calc_leased_refrigerant(
    body: QtyFactorRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    result = _ok(
        calculate_leased_refrigerant(quantity=body.quantity, factor=body.factor),
        "Leased refrigerant",
    )
    if body.persist and body.assessment_id:
        act = _persist(
            db,
            ctx,
            body.assessment_id,
            scope=3,
            category="leased_assets",
            method="leased_refrigerant",
            emissions_kg=float(result["emissions_kg"]),
            quantity=body.quantity,
            raw={
                "calc": "leased_refrigerant",
                "request": body.model_dump(mode="json"),
                "result": result,
            },
        )
        result["activity_id"] = str(act.id)
    return result


@router.post("/leased/total")
def calc_leased_total(
    body: LeasedTotalRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    result = calculate_leased_category_total(
        category=body.category,
        electricity_kg=body.electricity_kg,
        transport_rows_kg=body.transport_rows_kg,
        refrigerant_kg=body.refrigerant_kg,
    )
    if body.persist and body.assessment_id:
        act = _persist(
            db,
            ctx,
            body.assessment_id,
            scope=3,
            category="leased_assets",
            method="leased_total",
            emissions_kg=float(result["emissions_kg"]),
            raw={
                "calc": "leased_total",
                "request": body.model_dump(mode="json"),
                "result": result,
            },
        )
        result["activity_id"] = str(act.id)
    return result


# --- IPCC ---


@router.post("/ipcc/stationary")
def calc_ipcc_stationary(
    body: IpccStationaryRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    result = _ok(
        calculate_ipcc_stationary(quantity=body.quantity, factor=body.factor),
        "IPCC stationary",
    )
    if body.persist and body.assessment_id:
        act = _persist(
            db,
            ctx,
            body.assessment_id,
            scope=1,
            category="ipcc_stationary",
            method="ipcc_stationary",
            emissions_kg=float(result["emissions_kg"]),
            quantity=body.quantity,
            raw={
                "calc": "ipcc_stationary",
                "request": body.model_dump(mode="json"),
                "result": result,
            },
        )
        result["activity_id"] = str(act.id)
    return result


@router.post("/ipcc/flaring")
def calc_ipcc_flaring(
    body: IpccFlaringRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    result = _ok(
        calculate_ipcc_flaring(
            volume=body.volume, unit=body.unit, composition=body.composition
        ),
        "IPCC flaring",
    )
    if body.persist and body.assessment_id:
        act = _persist(
            db,
            ctx,
            body.assessment_id,
            scope=1,
            category="ipcc_flaring",
            method="ipcc_flaring",
            emissions_kg=float(result["emissions_kg"]),
            quantity=body.volume,
            unit=body.unit,
            raw={
                "calc": "ipcc_flaring",
                "request": body.model_dump(mode="json"),
                "result": result,
            },
        )
        result["activity_id"] = str(act.id)
    return result


@router.post("/ipcc/venting")
def calc_ipcc_venting(
    body: IpccVentingRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    result = _ok(
        calculate_ipcc_venting(
            volume=body.volume, unit=body.unit, composition=body.composition
        ),
        "IPCC venting",
    )
    if body.persist and body.assessment_id:
        act = _persist(
            db,
            ctx,
            body.assessment_id,
            scope=1,
            category="ipcc_venting",
            method="ipcc_venting",
            emissions_kg=float(result["emissions_kg"]),
            quantity=body.volume,
            unit=body.unit,
            raw={
                "calc": "ipcc_venting",
                "request": body.model_dump(mode="json"),
                "result": result,
            },
        )
        result["activity_id"] = str(act.id)
    return result


@router.post("/ipcc/vehicular")
def calc_ipcc_vehicular(
    body: IpccVehicularRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    result = calculate_ipcc_vehicular(
        diesel_liters=body.diesel_liters,
        petrol_liters=body.petrol_liters,
        diesel_factor=body.diesel_factor,
        petrol_factor=body.petrol_factor,
    )
    if body.persist and body.assessment_id:
        act = _persist(
            db,
            ctx,
            body.assessment_id,
            scope=1,
            category="ipcc_vehicular",
            method="ipcc_vehicular",
            emissions_kg=float(result["emissions_kg"]),
            raw={
                "calc": "ipcc_vehicular",
                "request": body.model_dump(mode="json"),
                "result": result,
            },
        )
        result["activity_id"] = str(act.id)
    return result


@router.post("/ipcc/kitchen")
def calc_ipcc_kitchen(
    body: IpccKitchenRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    result = calculate_ipcc_kitchen(
        lpg_kg=body.lpg_kg,
        ng_mmscf=body.ng_mmscf,
        ghv=body.ghv,
        lpg_factor=body.lpg_factor,
        natural_gas_co2=body.natural_gas_co2,
    )
    if body.persist and body.assessment_id:
        act = _persist(
            db,
            ctx,
            body.assessment_id,
            scope=1,
            category="ipcc_kitchen",
            method="ipcc_kitchen",
            emissions_kg=float(result["emissions_kg"]),
            raw={
                "calc": "ipcc_kitchen",
                "request": body.model_dump(mode="json"),
                "result": result,
            },
        )
        result["activity_id"] = str(act.id)
    return result


@router.post("/ipcc/power")
def calc_ipcc_power(
    body: IpccPowerRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    result = calculate_ipcc_power(
        diesel_liters=body.diesel_liters,
        ng_mmscf=body.ng_mmscf,
        ghv=body.ghv,
        diesel_factor=body.diesel_factor,
        natural_gas_co2=body.natural_gas_co2,
    )
    if body.persist and body.assessment_id:
        act = _persist(
            db,
            ctx,
            body.assessment_id,
            scope=1,
            category="ipcc_power",
            method="ipcc_power",
            emissions_kg=float(result["emissions_kg"]),
            raw={
                "calc": "ipcc_power",
                "request": body.model_dump(mode="json"),
                "result": result,
            },
        )
        result["activity_id"] = str(act.id)
    return result


@router.post("/ipcc/heating")
def calc_ipcc_heating(
    body: IpccHeatingRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    result = calculate_ipcc_heating(
        ng_mmscf=body.ng_mmscf,
        ghv=body.ghv,
        natural_gas_co2=body.natural_gas_co2,
    )
    if body.persist and body.assessment_id:
        act = _persist(
            db,
            ctx,
            body.assessment_id,
            scope=1,
            category="ipcc_heating",
            method="ipcc_heating",
            emissions_kg=float(result["emissions_kg"]),
            raw={
                "calc": "ipcc_heating",
                "request": body.model_dump(mode="json"),
                "result": result,
            },
        )
        result["activity_id"] = str(act.id)
    return result


@router.post("/ipcc/road")
def calc_ipcc_road(
    body: IpccStationaryRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    result = _ok(
        calculate_ipcc_road(quantity=body.quantity, factor=body.factor), "IPCC road"
    )
    if body.persist and body.assessment_id:
        act = _persist(
            db,
            ctx,
            body.assessment_id,
            scope=1,
            category="ipcc_road",
            method="ipcc_road",
            emissions_kg=float(result["emissions_kg"]),
            quantity=body.quantity,
            raw={
                "calc": "ipcc_road",
                "request": body.model_dump(mode="json"),
                "result": result,
            },
        )
        result["activity_id"] = str(act.id)
    return result


@router.post("/ipcc/road-vehicle")
def calc_ipcc_road_vehicle(
    body: IpccRoadVehicleRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    result = _ok(
        calculate_ipcc_road_vehicle(
            quantity=body.quantity,
            ch4_factor=body.ch4_factor,
            n2o_factor=body.n2o_factor,
            selected_factor=body.selected_factor,
        ),
        "IPCC road vehicle",
    )
    if body.persist and body.assessment_id:
        act = _persist(
            db,
            ctx,
            body.assessment_id,
            scope=1,
            category="ipcc_road_vehicle",
            method="ipcc_road_vehicle",
            emissions_kg=float(result["emissions_kg"]),
            quantity=body.quantity,
            raw={
                "calc": "ipcc_road_vehicle",
                "request": body.model_dump(mode="json"),
                "result": result,
            },
        )
        result["activity_id"] = str(act.id)
    return result


@router.post("/ipcc/usa-vehicles")
def calc_ipcc_usa(
    body: IpccStationaryRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    result = _ok(
        calculate_ipcc_usa_vehicles(quantity=body.quantity, factor=body.factor),
        "IPCC USA vehicles",
    )
    if body.persist and body.assessment_id:
        act = _persist(
            db,
            ctx,
            body.assessment_id,
            scope=1,
            category="ipcc_usa_vehicles",
            method="ipcc_usa_vehicles",
            emissions_kg=float(result["emissions_kg"]),
            quantity=body.quantity,
            raw={
                "calc": "ipcc_usa_vehicles",
                "request": body.model_dump(mode="json"),
                "result": result,
            },
        )
        result["activity_id"] = str(act.id)
    return result


@router.post("/ipcc/alt-fuel")
def calc_ipcc_alt(
    body: IpccRoadVehicleRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    result = _ok(
        calculate_ipcc_alt_fuel(
            quantity=body.quantity,
            ch4_factor=body.ch4_factor,
            n2o_factor=body.n2o_factor,
            selected_factor=body.selected_factor,
        ),
        "IPCC alt fuel",
    )
    if body.persist and body.assessment_id:
        act = _persist(
            db,
            ctx,
            body.assessment_id,
            scope=1,
            category="ipcc_alt_fuel",
            method="ipcc_alt_fuel",
            emissions_kg=float(result["emissions_kg"]),
            quantity=body.quantity,
            raw={
                "calc": "ipcc_alt_fuel",
                "request": body.model_dump(mode="json"),
                "result": result,
            },
        )
        result["activity_id"] = str(act.id)
    return result


@router.post("/ipcc/industry")
def calc_ipcc_industry(
    body: IpccIndustryRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    result = _ok(
        calculate_ipcc_industry(
            quantity=body.quantity,
            ef_co2=body.ef_co2,
            ef_ch4=body.ef_ch4,
            ef_n2o=body.ef_n2o,
            selected_factor=body.selected_factor,
        ),
        "IPCC industry",
    )
    if body.persist and body.assessment_id:
        act = _persist(
            db,
            ctx,
            body.assessment_id,
            scope=1,
            category="ipcc_industry",
            method="ipcc_industry",
            emissions_kg=float(result["emissions_kg"]),
            quantity=body.quantity,
            raw={
                "calc": "ipcc_industry",
                "request": body.model_dump(mode="json"),
                "result": result,
            },
        )
        result["activity_id"] = str(act.id)
    return result
