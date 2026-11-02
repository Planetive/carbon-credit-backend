"""
GHG calc endpoints — SPA math parity, optional persist to emission_activities.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from ..auth_org import OrgContext
from ..db import get_db
from ..factor_service import (
    factor_row_to_legacy_record,
    fetch_all_rows_for_dataset,
    get_row_by_id,
    load_legacy_sheet,
    load_legacy_sheets,
    resolve_dataset,
)
from ..ghg_calc.epa_fuel import build_epa_fuel_map, calculate_epa_fuel
from ..ghg_calc.stationary_combustion import calculate_stationary_combustion
from ..ghg_calc.stationary_records import save_epa_stationary_record
from ..ghg_calc.heat_steam import build_heat_steam_rows, calculate_heat_steam
from ..ghg_calc.mobile_combustion import calculate_mobile_combustion, load_mobile_factor_sheets
from ..ghg_calc.refrigerant_leakage import (
    calculate_refrigerant_leakage,
    load_refrigerant_factor_sheets,
)
from ..ghg_calc.refrigerant_records import save_epa_refrigerant_record
from ..ghg_calc.mobile_records import save_epa_mobile_record
from ..ghg_calc.scope2_electricity import calculate_location_electricity
from ..ghg_calc.scope2_electricity_records import save_scope2_electricity_record
from ..ghg_calc.scope2_heat_steam import calculate_purchased_heat_steam
from ..ghg_calc.scope2_heat_steam_records import save_scope2_heat_steam_record
from ..ghg_calc.scope2_uk_electricity import calculate_uk_location_electricity
from ..ghg_calc.scope2_uk_heat_steam import calculate_uk_purchased_heat_steam
from ..ghg_calc.scope2_uk_records import save_uk_electricity_record, save_uk_heat_steam_record
from ..ghg_calc.mobile_fuel import build_mobile_options, calculate_mobile_fuel
from ..ghg_calc.non_road import build_non_road_rows, calculate_non_road
from ..ghg_calc.on_road import (
    build_on_road_diesel_rows,
    build_on_road_gasoline_rows,
    calculate_on_road_diesel,
    calculate_on_road_gasoline,
)
from ..ghg_calc.uk_fuel import build_uk_factors_map, calculate_uk_fuel
from ..ghg_calc.uk_transport import (
    build_uk_delivery_map,
    build_uk_passenger_map,
    calculate_uk_delivery,
    calculate_uk_passenger,
)
from ..ghg_calc.waste import build_waste_materials, calculate_waste
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


class EpaStationaryCalcRequest(BaseModel):
    """Authoritative stationary request. Extra fields such as factor are ignored."""

    model_config = ConfigDict(extra="ignore")

    fuel: str
    quantity: Decimal
    unit: str
    category: Optional[str] = None
    gwp_version: str = "AR5"


class EpaMobileCalcRequest(BaseModel):
    """Authoritative mobile request. Client factors and totals are ignored."""

    model_config = ConfigDict(extra="ignore")

    road_class: str
    vehicle_type: str
    fuel_type: str
    fuel_quantity: Decimal
    fuel_unit: str
    distance: Optional[Decimal] = None
    distance_unit: Optional[str] = None
    model_year: Optional[int] = None
    gwp_version: str = "AR5"


class EpaRefrigerantLeakageCalcRequest(BaseModel):
    """Authoritative refrigerant leakage request. Client GWP and totals are ignored."""

    model_config = ConfigDict(extra="ignore")

    method: Literal["leakage_record", "estimated_leakage"]
    gas: str = Field(min_length=1)
    leakage_kg: Optional[Decimal] = None
    charge_kg: Optional[Decimal] = None
    leakage_rate_percent: Optional[Decimal] = None
    equipment_type: Optional[str] = None

    @model_validator(mode="after")
    def fields_match_method(self) -> "EpaRefrigerantLeakageCalcRequest":
        if self.method == "leakage_record":
            if self.leakage_kg is None:
                raise ValueError("leakage_kg is required for leakage_record")
            if self.charge_kg is not None or self.leakage_rate_percent is not None:
                raise ValueError(
                    "charge_kg and leakage_rate_percent are only accepted for estimated_leakage"
                )
        else:
            if self.charge_kg is None or self.leakage_rate_percent is None:
                raise ValueError(
                    "charge_kg and leakage_rate_percent are required for estimated_leakage"
                )
            if self.leakage_kg is not None:
                raise ValueError("leakage_kg is only accepted for leakage_record")
        return self


class EpaRefrigerantLeakageSaveRequest(EpaRefrigerantLeakageCalcRequest):
    """Save request. Client GWP, factor ids, and emission totals are ignored."""

    model_config = ConfigDict(extra="ignore")

    assessment_id: uuid.UUID
    period: str
    equipment_id: Optional[str] = None
    site: Optional[str] = None
    counterparty_id: Optional[uuid.UUID] = None


class EpaMobileSaveRequest(BaseModel):
    """Save request. Client factor and emissions fields are ignored."""

    model_config = ConfigDict(extra="ignore")

    road_class: str
    vehicle_type: str
    fuel_type: str
    fuel_quantity: Decimal
    fuel_unit: str
    assessment_id: uuid.UUID
    period: str
    equipment_id: Optional[str] = None
    distance: Optional[Decimal] = None
    distance_unit: Optional[str] = None
    model_year: Optional[int] = None
    gwp_version: str = "AR5"
    counterparty_id: Optional[uuid.UUID] = None
    site: Optional[str] = None


class Scope2ElectricityRequest(BaseModel):
    """Location-based purchased electricity. grid_factor and emissions are ignored."""

    model_config = ConfigDict(extra="ignore")

    country: str
    quantity: Decimal
    unit: str
    period: str
    grid_region: str = "national"
    renewable_kwh: Optional[Decimal] = None
    grid_factor: Optional[Decimal] = None
    emissions_tco2e: Optional[Decimal] = None


class Scope2ElectricitySaveRequest(Scope2ElectricityRequest):
    assessment_id: uuid.UUID
    counterparty_id: Optional[uuid.UUID] = None


class Scope2HeatSteamRequest(BaseModel):
    """EPA purchased heat or steam. Client factors and emission totals are ignored."""

    model_config = ConfigDict(extra="ignore")

    energy_form: str
    quantity: Decimal
    unit: str
    period: str
    supplier_name: Optional[str] = None
    co2_factor: Optional[Decimal] = None
    ch4_factor: Optional[Decimal] = None
    n2o_factor: Optional[Decimal] = None
    emission_factor: Optional[Decimal] = None
    emissions_tco2e: Optional[Decimal] = None


class Scope2HeatSteamSaveRequest(Scope2HeatSteamRequest):
    assessment_id: uuid.UUID
    counterparty_id: Optional[uuid.UUID] = None


class UkScope2ElectricityRequest(BaseModel):
    """UK-calculator purchased electricity. Client factors and fuel masses are ignored."""

    model_config = ConfigDict(extra="ignore")

    country: str
    quantity: Decimal
    unit: str
    period: str
    grid_region: str = "national"
    renewable_kwh: Optional[Decimal] = None
    grid_factor: Optional[Decimal] = None
    emissions_tco2e: Optional[Decimal] = None
    other_pct: Optional[Decimal] = None
    other_row_emissions_sum: Optional[Decimal] = None


class UkScope2ElectricitySaveRequest(UkScope2ElectricityRequest):
    assessment_id: uuid.UUID
    counterparty_id: Optional[uuid.UUID] = None


class UkScope2HeatSteamRequest(BaseModel):
    """UK-calculator purchased heat or steam. Client factors are ignored."""

    model_config = ConfigDict(extra="ignore")

    country: str
    energy_form: str
    quantity: Decimal
    unit: str
    period: str
    supplier_name: Optional[str] = None
    co2_factor: Optional[Decimal] = None
    ch4_factor: Optional[Decimal] = None
    n2o_factor: Optional[Decimal] = None
    emission_factor: Optional[Decimal] = None
    emissions_tco2e: Optional[Decimal] = None


class UkScope2HeatSteamSaveRequest(UkScope2HeatSteamRequest):
    assessment_id: uuid.UUID
    counterparty_id: Optional[uuid.UUID] = None


class EpaStationarySaveRequest(BaseModel):
    """Save request. Client factor and emissions fields are ignored."""

    model_config = ConfigDict(extra="ignore")

    fuel: str
    quantity: Decimal
    unit: str
    assessment_id: uuid.UUID
    equipment_type: str
    category: Optional[str] = None
    gwp_version: str = "AR5"
    counterparty_id: Optional[uuid.UUID] = None
    site: Optional[str] = None
    equipment_id: Optional[str] = None
    period: str


class SimpleMultiplyRequest(BaseModel):
    quantity: float
    factor: float
    assessment_id: Optional[uuid.UUID] = None
    category: Optional[str] = None
    persist: bool = False
    meta: Optional[Dict[str, Any]] = None


class UkPassengerCalcRequest(BaseModel):
    distance: float
    activity: Optional[str] = None
    vehicle_type: Optional[str] = None
    unit: Optional[str] = None
    fuel_type: Optional[str] = None
    uk_factor_basis: str = "total"
    factor: Optional[float] = None
    assessment_id: Optional[uuid.UUID] = None
    category: Optional[str] = "passenger_vehicle"
    persist: bool = False


class UkDeliveryCalcRequest(BaseModel):
    distance: float
    activity: Optional[str] = None
    vehicle_type: Optional[str] = None
    unit: Optional[str] = None
    fuel_type: Optional[str] = None
    laden_level: Optional[str] = None
    uk_factor_basis: str = "total"
    factor: Optional[float] = None
    assessment_id: Optional[uuid.UUID] = None
    category: Optional[str] = "delivery_vehicle"
    persist: bool = False


class MobileFuelCalcRequest(BaseModel):
    quantity: float
    fuel_type: Optional[str] = None
    unit: Optional[str] = None
    input_unit: Optional[str] = None
    factor: Optional[float] = None
    assessment_id: Optional[uuid.UUID] = None
    persist: bool = False


class OnRoadGasolineCalcRequest(BaseModel):
    distance: float
    distance_unit: str = "mile"
    vehicle_type: Optional[str] = None
    model_year: Optional[str] = None
    emission_selection: str = "ch4_only"
    ch4_g_per_mile: Optional[float] = None
    n2o_g_per_mile: Optional[float] = None
    assessment_id: Optional[uuid.UUID] = None
    persist: bool = False


class OnRoadDieselCalcRequest(BaseModel):
    distance: float
    distance_unit: str = "mile"
    vehicle_type: Optional[str] = None
    fuel_type: Optional[str] = None
    model_year: Optional[str] = None
    emission_selection: str = "ch4"
    ch4_g_per_mile: Optional[float] = None
    n2o_g_per_mile: Optional[float] = None
    assessment_id: Optional[uuid.UUID] = None
    persist: bool = False


class NonRoadCalcRequest(BaseModel):
    quantity: float
    unit: str = "gallon"
    vehicle_type: Optional[str] = None
    fuel_type: Optional[str] = None
    emission_selection: str = "ch4"
    ch4_g_per_gallon: Optional[float] = None
    n2o_g_per_gallon: Optional[float] = None
    assessment_id: Optional[uuid.UUID] = None
    persist: bool = False


class HeatSteamCalcRequest(BaseModel):
    quantity: float
    gas: str = "co2"
    quantity_unit: str = "base"
    entry_type: Optional[str] = None
    unit: Optional[str] = None
    co2_factor: Optional[float] = None
    ch4_factor: Optional[float] = None
    n2o_factor: Optional[float] = None
    standard: str = "uk"  # uk | ebt
    assessment_id: Optional[uuid.UUID] = None
    persist: bool = False


class WasteCalcRequest(BaseModel):
    volume: float
    disposal_method: str
    material: Optional[str] = None
    factor: Optional[float] = None
    factor_unit: Optional[str] = None
    mass_unit: Optional[str] = None
    assessment_id: Optional[uuid.UUID] = None
    persist: bool = False


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


def _raise_if_failed(result: Dict[str, Any], label: str) -> Dict[str, Any]:
    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=result.get("error") or f"{label} calculation failed",
        )
    return result


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

    result = _raise_if_failed(
        calculate_uk_fuel(
            quantity=body.quantity,
            activity=body.activity,
            fuel=body.fuel,
            unit=body.unit,
            uk_factor_basis=body.uk_factor_basis,  # type: ignore[arg-type]
            factor=factor,
            factors_map=factors_map,
        ),
        "UK fuel",
    )

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
        result["activity_id"] = str(act.id)
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

    result = _raise_if_failed(
        calculate_epa_fuel(
            quantity=body.quantity,
            unit=body.unit,
            category=body.category,
            fuel=body.fuel,
            factor=factor,
            factors_map=factors_map,
        ),
        "EPA fuel",
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


_STATIONARY_DATASETS = (
    {
        "codes": ["fuel_epa_1", "fuel_epa1"],
        "hints": ["Fuel EPA 1"],
    },
    {
        "codes": ["fuel_epa_2", "fuel_epa2"],
        "hints": ["Fuel EPA 2"],
    },
    {
        "codes": ["fuel_epa_3", "fuel_epa3"],
        "hints": ["Fuel EPA 3"],
    },
)


def _stationary_factor_sheets(db: Session) -> list:
    sheets = []
    for spec in _STATIONARY_DATASETS:
        dataset = resolve_dataset(db, spec["codes"], spec["hints"])
        if dataset is None:
            continue
        rows = fetch_all_rows_for_dataset(db, dataset.id)
        sheets.append(
            {
                "publisher": dataset.publisher,
                "dataset_code": dataset.code,
                "dataset_title": dataset.title,
                "version_label": dataset.version_label,
                "effective_from": (
                    dataset.effective_from.isoformat() if dataset.effective_from else None
                ),
                "effective_to": (
                    dataset.effective_to.isoformat() if dataset.effective_to else None
                ),
                "dataset_id": str(dataset.id),
                "source_notes": dataset.source_notes,
                "rows": [
                    {
                        **factor_row_to_legacy_record(row),
                        "_factor_row_id": str(row.id),
                        "_factor_dataset_id": str(dataset.id),
                    }
                    for row in rows
                ],
            }
        )
    return sheets


@router.post("/epa/stationary")
def calc_epa_stationary(
    body: EpaStationaryCalcRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    All-gas stationary combustion. Does not read a client factor and does not
    write emission records.
    """
    del ctx
    return _raise_if_failed(
        calculate_stationary_combustion(
            fuel=body.fuel,
            quantity=body.quantity,
            unit=body.unit,
            category=body.category,
            gwp_version=body.gwp_version,
            sheets=_stationary_factor_sheets(db),
        ),
        "EPA stationary combustion",
    )


@router.post("/epa/mobile")
def calc_epa_mobile(
    body: EpaMobileCalcRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    All-gas mobile combustion. Does not read a client factor and does not
    write emission records.
    """
    del ctx
    return _raise_if_failed(
        calculate_mobile_combustion(
            road_class=body.road_class,
            vehicle_type=body.vehicle_type,
            fuel_type=body.fuel_type,
            fuel_quantity=body.fuel_quantity,
            fuel_unit=body.fuel_unit,
            distance=body.distance,
            distance_unit=body.distance_unit,
            model_year=body.model_year,
            gwp_version=body.gwp_version,
            sheets=load_mobile_factor_sheets(db),
        ),
        "EPA mobile combustion",
    )


@router.post("/epa/refrigerant-leakage")
def calc_epa_refrigerant_leakage(
    body: EpaRefrigerantLeakageCalcRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Refrigerant leakage. Does not read a client GWP and does not write
    emission records. The legacy /epa/refrigerant route is unchanged.
    """
    del ctx
    return _raise_if_failed(
        calculate_refrigerant_leakage(
            method=body.method,
            gas=body.gas,
            leakage_kg=body.leakage_kg,
            charge_kg=body.charge_kg,
            leakage_rate_percent=body.leakage_rate_percent,
            equipment_type=body.equipment_type,
            sheets=load_refrigerant_factor_sheets(db),
        ),
        "EPA refrigerant leakage",
    )


@router.post("/epa/refrigerant-leakage/records", status_code=status.HTTP_201_CREATED)
def create_epa_refrigerant_leakage_record(
    body: EpaRefrigerantLeakageSaveRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return save_epa_refrigerant_record(
        db,
        ctx,
        sheets=load_refrigerant_factor_sheets(db),
        method=body.method,
        gas=body.gas,
        leakage_kg=body.leakage_kg,
        charge_kg=body.charge_kg,
        leakage_rate_percent=body.leakage_rate_percent,
        equipment_type=body.equipment_type,
        equipment_id=body.equipment_id,
        site=body.site,
        period=body.period,
        assessment_id=body.assessment_id,
        counterparty_id=body.counterparty_id,
    )


@router.patch("/epa/refrigerant-leakage/records/{activity_id}")
def update_epa_refrigerant_leakage_record(
    activity_id: uuid.UUID,
    body: EpaRefrigerantLeakageSaveRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return save_epa_refrigerant_record(
        db,
        ctx,
        sheets=load_refrigerant_factor_sheets(db),
        method=body.method,
        gas=body.gas,
        leakage_kg=body.leakage_kg,
        charge_kg=body.charge_kg,
        leakage_rate_percent=body.leakage_rate_percent,
        equipment_type=body.equipment_type,
        equipment_id=body.equipment_id,
        site=body.site,
        period=body.period,
        assessment_id=body.assessment_id,
        counterparty_id=body.counterparty_id,
        activity_id=activity_id,
    )


@router.post("/epa/mobile/records", status_code=status.HTTP_201_CREATED)
def create_epa_mobile_record(
    body: EpaMobileSaveRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return save_epa_mobile_record(
        db,
        ctx,
        sheets=load_mobile_factor_sheets(db),
        road_class=body.road_class,
        vehicle_type=body.vehicle_type,
        fuel_type=body.fuel_type,
        fuel_quantity=body.fuel_quantity,
        fuel_unit=body.fuel_unit,
        distance=body.distance,
        distance_unit=body.distance_unit,
        model_year=body.model_year,
        gwp_version=body.gwp_version,
        assessment_id=body.assessment_id,
        counterparty_id=body.counterparty_id,
        equipment_id=body.equipment_id,
        site=body.site,
        period=body.period,
    )


@router.patch("/epa/mobile/records/{activity_id}")
def update_epa_mobile_record(
    activity_id: uuid.UUID,
    body: EpaMobileSaveRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return save_epa_mobile_record(
        db,
        ctx,
        sheets=load_mobile_factor_sheets(db),
        road_class=body.road_class,
        vehicle_type=body.vehicle_type,
        fuel_type=body.fuel_type,
        fuel_quantity=body.fuel_quantity,
        fuel_unit=body.fuel_unit,
        distance=body.distance,
        distance_unit=body.distance_unit,
        model_year=body.model_year,
        gwp_version=body.gwp_version,
        assessment_id=body.assessment_id,
        counterparty_id=body.counterparty_id,
        equipment_id=body.equipment_id,
        site=body.site,
        period=body.period,
        activity_id=activity_id,
    )


@router.post("/scope2/electricity")
def calc_scope2_electricity(
    body: Scope2ElectricityRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _ = ctx
    result = calculate_location_electricity(
        db,
        country=body.country,
        quantity=body.quantity,
        unit=body.unit,
        period=body.period,
        grid_region=body.grid_region,
        renewable_kwh=body.renewable_kwh,
        grid_factor=body.grid_factor,
        emissions_tco2e=body.emissions_tco2e,
    )
    if not result.get("ok"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=result.get("error") or "Purchased electricity could not be calculated.",
        )
    return result


@router.post("/scope2/electricity/records", status_code=status.HTTP_201_CREATED)
def create_scope2_electricity_record(
    body: Scope2ElectricitySaveRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return save_scope2_electricity_record(
        db,
        ctx,
        country=body.country,
        quantity=body.quantity,
        unit=body.unit,
        period=body.period,
        assessment_id=body.assessment_id,
        grid_region=body.grid_region,
        counterparty_id=body.counterparty_id,
        renewable_kwh=body.renewable_kwh,
        grid_factor=body.grid_factor,
        emissions_tco2e=body.emissions_tco2e,
    )


@router.patch("/scope2/electricity/records/{activity_id}")
def update_scope2_electricity_record(
    activity_id: uuid.UUID,
    body: Scope2ElectricitySaveRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return save_scope2_electricity_record(
        db,
        ctx,
        country=body.country,
        quantity=body.quantity,
        unit=body.unit,
        period=body.period,
        assessment_id=body.assessment_id,
        grid_region=body.grid_region,
        counterparty_id=body.counterparty_id,
        renewable_kwh=body.renewable_kwh,
        activity_id=activity_id,
        grid_factor=body.grid_factor,
        emissions_tco2e=body.emissions_tco2e,
    )


def _uk_electricity_kwargs(body: UkScope2ElectricityRequest) -> Dict[str, Any]:
    return {
        "country": body.country,
        "quantity": body.quantity,
        "unit": body.unit,
        "period": body.period,
        "grid_region": body.grid_region,
        "renewable_kwh": body.renewable_kwh,
        "grid_factor": body.grid_factor,
        "emissions_tco2e": body.emissions_tco2e,
        "other_pct": body.other_pct,
        "other_row_emissions_sum": body.other_row_emissions_sum,
    }


@router.post("/scope2/uk/electricity")
def calc_uk_scope2_electricity(
    body: UkScope2ElectricityRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _ = ctx
    result = calculate_uk_location_electricity(db, **_uk_electricity_kwargs(body))
    if not result.get("ok"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=result.get("error") or "Purchased electricity could not be calculated.",
        )
    return result


@router.post("/scope2/uk/electricity/records", status_code=status.HTTP_201_CREATED)
def create_uk_scope2_electricity_record(
    body: UkScope2ElectricitySaveRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return save_uk_electricity_record(
        db,
        ctx,
        assessment_id=body.assessment_id,
        counterparty_id=body.counterparty_id,
        **_uk_electricity_kwargs(body),
    )


@router.patch("/scope2/uk/electricity/records/{activity_id}")
def update_uk_scope2_electricity_record(
    activity_id: uuid.UUID,
    body: UkScope2ElectricitySaveRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return save_uk_electricity_record(
        db,
        ctx,
        activity_id=activity_id,
        assessment_id=body.assessment_id,
        counterparty_id=body.counterparty_id,
        **_uk_electricity_kwargs(body),
    )


def _uk_heat_kwargs(body: UkScope2HeatSteamRequest) -> Dict[str, Any]:
    return {
        "country": body.country,
        "energy_form": body.energy_form,
        "quantity": body.quantity,
        "unit": body.unit,
        "period": body.period,
        "supplier_name": body.supplier_name,
        "co2_factor": body.co2_factor,
        "ch4_factor": body.ch4_factor,
        "n2o_factor": body.n2o_factor,
        "emission_factor": body.emission_factor,
        "emissions_tco2e": body.emissions_tco2e,
    }


@router.post("/scope2/uk/heat-steam")
def calc_uk_scope2_heat_steam(
    body: UkScope2HeatSteamRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _ = ctx
    result = calculate_uk_purchased_heat_steam(db, **_uk_heat_kwargs(body))
    if not result.get("ok"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=result.get("error") or "Purchased heat or steam could not be calculated.",
        )
    return result


@router.post("/scope2/uk/heat-steam/records", status_code=status.HTTP_201_CREATED)
def create_uk_scope2_heat_steam_record(
    body: UkScope2HeatSteamSaveRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return save_uk_heat_steam_record(
        db,
        ctx,
        assessment_id=body.assessment_id,
        counterparty_id=body.counterparty_id,
        **_uk_heat_kwargs(body),
    )


@router.patch("/scope2/uk/heat-steam/records/{activity_id}")
def update_uk_scope2_heat_steam_record(
    activity_id: uuid.UUID,
    body: UkScope2HeatSteamSaveRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return save_uk_heat_steam_record(
        db,
        ctx,
        activity_id=activity_id,
        assessment_id=body.assessment_id,
        counterparty_id=body.counterparty_id,
        **_uk_heat_kwargs(body),
    )


@router.post("/scope2/heat-steam")
def calc_scope2_heat_steam(
    body: Scope2HeatSteamRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _ = ctx, db
    result = calculate_purchased_heat_steam(
        energy_form=body.energy_form,
        quantity=body.quantity,
        unit=body.unit,
        period=body.period,
        supplier_name=body.supplier_name,
        co2_factor=body.co2_factor,
        ch4_factor=body.ch4_factor,
        n2o_factor=body.n2o_factor,
        emission_factor=body.emission_factor,
        emissions_tco2e=body.emissions_tco2e,
    )
    if not result.get("ok"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=result.get("error") or "Purchased heat or steam could not be calculated.",
        )
    return result


@router.post("/scope2/heat-steam/records", status_code=status.HTTP_201_CREATED)
def create_scope2_heat_steam_record(
    body: Scope2HeatSteamSaveRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return save_scope2_heat_steam_record(
        db,
        ctx,
        energy_form=body.energy_form,
        quantity=body.quantity,
        unit=body.unit,
        period=body.period,
        assessment_id=body.assessment_id,
        counterparty_id=body.counterparty_id,
        supplier_name=body.supplier_name,
        co2_factor=body.co2_factor,
        ch4_factor=body.ch4_factor,
        n2o_factor=body.n2o_factor,
        emission_factor=body.emission_factor,
        emissions_tco2e=body.emissions_tco2e,
    )


@router.patch("/scope2/heat-steam/records/{activity_id}")
def update_scope2_heat_steam_record(
    activity_id: uuid.UUID,
    body: Scope2HeatSteamSaveRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return save_scope2_heat_steam_record(
        db,
        ctx,
        energy_form=body.energy_form,
        quantity=body.quantity,
        unit=body.unit,
        period=body.period,
        assessment_id=body.assessment_id,
        counterparty_id=body.counterparty_id,
        supplier_name=body.supplier_name,
        activity_id=activity_id,
        co2_factor=body.co2_factor,
        ch4_factor=body.ch4_factor,
        n2o_factor=body.n2o_factor,
        emission_factor=body.emission_factor,
        emissions_tco2e=body.emissions_tco2e,
    )


@router.post("/epa/stationary/records", status_code=status.HTTP_201_CREATED)
def create_epa_stationary_record(
    body: EpaStationarySaveRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return save_epa_stationary_record(
        db,
        ctx,
        sheets=_stationary_factor_sheets(db),
        fuel=body.fuel,
        quantity=body.quantity,
        unit=body.unit,
        category=body.category,
        gwp_version=body.gwp_version,
        assessment_id=body.assessment_id,
        counterparty_id=body.counterparty_id,
        equipment_type=body.equipment_type,
        site=body.site,
        equipment_id=body.equipment_id,
        period=body.period,
    )


@router.patch("/epa/stationary/records/{activity_id}")
def update_epa_stationary_record(
    activity_id: uuid.UUID,
    body: EpaStationarySaveRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return save_epa_stationary_record(
        db,
        ctx,
        sheets=_stationary_factor_sheets(db),
        fuel=body.fuel,
        quantity=body.quantity,
        unit=body.unit,
        category=body.category,
        gwp_version=body.gwp_version,
        assessment_id=body.assessment_id,
        counterparty_id=body.counterparty_id,
        equipment_type=body.equipment_type,
        site=body.site,
        equipment_id=body.equipment_id,
        period=body.period,
        activity_id=activity_id,
    )


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
def calc_uk_passenger_route(
    body: UkPassengerCalcRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    factors_map = None
    if body.factor is None:
        sheet = load_legacy_sheet(
            db,
            codes=["uk_passenger_factors", "uk_passenger_factor"],
            name_hints=["passenger", "UK_Passenger"],
        )
        if sheet:
            factors_map = build_uk_passenger_map(sheet)

    result = _raise_if_failed(
        calculate_uk_passenger(
            distance=body.distance,
            activity=body.activity,
            vehicle_type=body.vehicle_type,
            unit=body.unit,
            fuel_type=body.fuel_type,
            uk_factor_basis=body.uk_factor_basis,  # type: ignore[arg-type]
            factor=body.factor,
            factors_map=factors_map,
        ),
        "UK passenger",
    )
    if body.persist and body.assessment_id:
        act = _persist_activity(
            db,
            ctx,
            body.assessment_id,
            scope=1,
            category=body.category or "passenger_vehicle",
            method="uk_passenger",
            emissions_kg=float(result["emissions_kg"]),
            quantity=body.distance,
            unit=body.unit,
            raw={"calc": "uk_passenger", "request": body.model_dump(mode="json"), "result": result},
        )
        result["activity_id"] = str(act.id)
    return result


@router.post("/uk/delivery")
def calc_uk_delivery_route(
    body: UkDeliveryCalcRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    factors_map = None
    if body.factor is None:
        sheet = load_legacy_sheet(
            db,
            codes=["uk_delivery_factors", "uk_delivery_factor"],
            name_hints=["delivery", "UK_delivery"],
        )
        if sheet:
            factors_map = build_uk_delivery_map(sheet)

    result = _raise_if_failed(
        calculate_uk_delivery(
            distance=body.distance,
            activity=body.activity,
            vehicle_type=body.vehicle_type,
            unit=body.unit,
            fuel_type=body.fuel_type,
            laden_level=body.laden_level,
            uk_factor_basis=body.uk_factor_basis,  # type: ignore[arg-type]
            factor=body.factor,
            factors_map=factors_map,
        ),
        "UK delivery",
    )
    if body.persist and body.assessment_id:
        act = _persist_activity(
            db,
            ctx,
            body.assessment_id,
            scope=1,
            category=body.category or "delivery_vehicle",
            method="uk_delivery",
            emissions_kg=float(result["emissions_kg"]),
            quantity=body.distance,
            unit=body.unit,
            raw={"calc": "uk_delivery", "request": body.model_dump(mode="json"), "result": result},
        )
        result["activity_id"] = str(act.id)
    return result


@router.post("/uk/refrigerant")
def calc_uk_refrigerant(
    body: SimpleMultiplyRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
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


@router.post("/epa/mobile-fuel")
def calc_mobile_fuel(
    body: MobileFuelCalcRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    options = None
    if body.factor is None:
        sheet = load_legacy_sheet(
            db,
            codes=["mobile_combustion"],
            name_hints=["Mobile Combustion", "mobile combustion"],
        )
        if sheet:
            options = build_mobile_options(sheet)

    result = _raise_if_failed(
        calculate_mobile_fuel(
            quantity=body.quantity,
            fuel_type=body.fuel_type,
            unit=body.unit,
            input_unit=body.input_unit,
            factor=body.factor,
            options=options,
        ),
        "Mobile fuel",
    )
    if body.persist and body.assessment_id:
        act = _persist_activity(
            db,
            ctx,
            body.assessment_id,
            scope=1,
            category="mobile_combustion",
            method="epa_mobile_fuel",
            emissions_kg=float(result["emissions_kg"]),
            quantity=body.quantity,
            unit=body.unit,
            raw={"calc": "epa_mobile_fuel", "request": body.model_dump(mode="json"), "result": result},
        )
        result["activity_id"] = str(act.id)
    return result


@router.post("/epa/on-road-gasoline")
def calc_on_road_gasoline(
    body: OnRoadGasolineCalcRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    factor_rows = None
    if body.ch4_g_per_mile is None and body.n2o_g_per_mile is None:
        sheet = load_legacy_sheet(
            db,
            codes=["on_road_gasoline"],
            name_hints=["On-Road Gasoline", "on road gasoline"],
        )
        if sheet:
            factor_rows = build_on_road_gasoline_rows(sheet)

    result = _raise_if_failed(
        calculate_on_road_gasoline(
            distance=body.distance,
            distance_unit=body.distance_unit,
            vehicle_type=body.vehicle_type,
            model_year=body.model_year,
            emission_selection=body.emission_selection,
            ch4_g_per_mile=body.ch4_g_per_mile,
            n2o_g_per_mile=body.n2o_g_per_mile,
            factor_rows=factor_rows,
        ),
        "On-road gasoline",
    )
    if body.persist and body.assessment_id:
        act = _persist_activity(
            db,
            ctx,
            body.assessment_id,
            scope=1,
            category="on_road_gasoline",
            method="epa_on_road_gasoline",
            emissions_kg=float(result["emissions_kg"]),
            quantity=body.distance,
            unit=body.distance_unit,
            raw={
                "calc": "epa_on_road_gasoline",
                "request": body.model_dump(mode="json"),
                "result": result,
            },
        )
        result["activity_id"] = str(act.id)
    return result


@router.post("/epa/on-road-diesel")
def calc_on_road_diesel(
    body: OnRoadDieselCalcRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    factor_rows = None
    if body.ch4_g_per_mile is None and body.n2o_g_per_mile is None:
        sheet = load_legacy_sheet(
            db,
            codes=["on_road_diesel_alt_fuel", "on_road_diesel_alt"],
            name_hints=["On-Road Diesel", "diesel alt"],
        )
        if sheet:
            factor_rows = build_on_road_diesel_rows(sheet)

    result = _raise_if_failed(
        calculate_on_road_diesel(
            distance=body.distance,
            distance_unit=body.distance_unit,
            vehicle_type=body.vehicle_type,
            fuel_type=body.fuel_type,
            model_year=body.model_year,
            emission_selection=body.emission_selection,
            ch4_g_per_mile=body.ch4_g_per_mile,
            n2o_g_per_mile=body.n2o_g_per_mile,
            factor_rows=factor_rows,
        ),
        "On-road diesel",
    )
    if body.persist and body.assessment_id:
        act = _persist_activity(
            db,
            ctx,
            body.assessment_id,
            scope=1,
            category="on_road_diesel",
            method="epa_on_road_diesel",
            emissions_kg=float(result["emissions_kg"]),
            quantity=body.distance,
            unit=body.distance_unit,
            raw={
                "calc": "epa_on_road_diesel",
                "request": body.model_dump(mode="json"),
                "result": result,
            },
        )
        result["activity_id"] = str(act.id)
    return result


@router.post("/epa/non-road")
def calc_non_road(
    body: NonRoadCalcRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    factor_rows = None
    if body.ch4_g_per_gallon is None and body.n2o_g_per_gallon is None:
        sheet = load_legacy_sheet(
            db,
            codes=["non_road_vehicle"],
            name_hints=["Non-Road Vehicle", "non road"],
        )
        if sheet:
            factor_rows = build_non_road_rows(sheet)

    result = _raise_if_failed(
        calculate_non_road(
            quantity=body.quantity,
            unit=body.unit,
            vehicle_type=body.vehicle_type,
            fuel_type=body.fuel_type,
            emission_selection=body.emission_selection,
            ch4_g_per_gallon=body.ch4_g_per_gallon,
            n2o_g_per_gallon=body.n2o_g_per_gallon,
            factor_rows=factor_rows,
        ),
        "Non-road",
    )
    if body.persist and body.assessment_id:
        act = _persist_activity(
            db,
            ctx,
            body.assessment_id,
            scope=1,
            category="non_road_vehicle",
            method="epa_non_road",
            emissions_kg=float(result["emissions_kg"]),
            quantity=body.quantity,
            unit=body.unit,
            raw={"calc": "epa_non_road", "request": body.model_dump(mode="json"), "result": result},
        )
        result["activity_id"] = str(act.id)
    return result


@router.post("/heat-steam")
def calc_heat_steam(
    body: HeatSteamCalcRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    if body.gas not in ("co2", "ch4", "n2o"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="gas must be one of: co2, ch4, n2o",
        )

    factor_rows = None
    needs_lookup = (
        body.co2_factor is None and body.ch4_factor is None and body.n2o_factor is None
    )
    if needs_lookup:
        if (body.standard or "uk").lower() == "ebt":
            sheet = load_legacy_sheet(
                db,
                codes=["heat_and_steam_ebt", "heat_and_steam_ebt_"],
                name_hints=["heat and steam EBT", "heat steam ebt"],
            )
        else:
            sheet = load_legacy_sheet(
                db,
                codes=["heat_and_steam"],
                name_hints=["heat and steam"],
            )
        if sheet:
            factor_rows = build_heat_steam_rows(sheet)

    result = _raise_if_failed(
        calculate_heat_steam(
            quantity=body.quantity,
            gas=body.gas,  # type: ignore[arg-type]
            quantity_unit=body.quantity_unit,
            entry_type=body.entry_type,
            unit=body.unit,
            co2_factor=body.co2_factor,
            ch4_factor=body.ch4_factor,
            n2o_factor=body.n2o_factor,
            factor_rows=factor_rows,
        ),
        "Heat/steam",
    )
    if body.persist and body.assessment_id:
        act = _persist_activity(
            db,
            ctx,
            body.assessment_id,
            scope=2,
            category="heat_steam",
            method="heat_steam",
            emissions_kg=float(result["emissions_kg"]),
            quantity=body.quantity,
            unit=body.unit,
            raw={"calc": "heat_steam", "request": body.model_dump(mode="json"), "result": result},
        )
        result["activity_id"] = str(act.id)
    return result


@router.post("/waste")
def calc_waste(
    body: WasteCalcRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    materials = None
    if body.factor is None:
        sheet = load_legacy_sheet(
            db,
            codes=["waste"],
            name_hints=["waste"],
        )
        if sheet:
            materials = build_waste_materials(sheet)

    result = _raise_if_failed(
        calculate_waste(
            volume=body.volume,
            disposal_method=body.disposal_method,
            material=body.material,
            factor=body.factor,
            materials=materials,
            factor_unit=body.factor_unit,
            mass_unit=body.mass_unit,
        ),
        "Waste",
    )
    if body.persist and body.assessment_id:
        act = _persist_activity(
            db,
            ctx,
            body.assessment_id,
            scope=3,
            category="waste_generated",
            method="waste",
            emissions_kg=float(result["emissions_kg"]),
            quantity=body.volume,
            unit="kg",
            raw={"calc": "waste", "request": body.model_dump(mode="json"), "result": result},
        )
        result["activity_id"] = str(act.id)
    return result
