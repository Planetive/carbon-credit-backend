"""
Server-authoritative Scope 3 calculations for verified activity persistence.

Client factor values and emission totals are ignored. Factors are resolved from
authoritative datasets; missing/ambiguous units refuse the calculation.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..factor_service import load_legacy_sheet, resolve_dataset, fetch_all_rows_for_dataset, factor_row_to_legacy_record
from ..factor_models import FactorRow
from ._common import fail_payload, norm_cell, parse_number, success_payload
from .scope3_factor_units import (
    WASTE_DATASET_FACTOR_UNIT,
    freight_emissions_kg,
    spend_emissions_kg,
    travel_distance_emissions_kg,
    annualize_commuting_distance_km,
)
from .scope3_period import parse_period_month
from .waste import DISPOSAL_METHODS, get_emission_factor, build_waste_materials

ACCOUNTING_VERSION = "scope3_verified_activity_v1"


def _dec(value: float) -> str:
    return format(Decimal(str(value)), "f")


def _ok_calc(
    *,
    emissions_kg: float,
    period: str,
    category: str,
    method: str,
    quantity: float,
    unit: str,
    inputs: Dict[str, Any],
    factor: Dict[str, Any],
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    tonnes = float(emissions_kg) / 1000.0
    out: Dict[str, Any] = {
        "ok": True,
        "save_allowed": True,
        "period": period,
        "reporting_year": int(period[:4]),
        "scope": 3,
        "category": category,
        "method": method,
        "quantity": quantity,
        "unit": unit,
        "emissions_kg": emissions_kg,
        "total_kg_co2e": _dec(emissions_kg),
        "total_t_co2e": _dec(tonnes),
        "emissions_tco2e": _dec(tonnes),
        "factor": factor,
        "inputs": inputs,
        "accounting": {"version": ACCOUNTING_VERSION, "boundary": category},
        "methodology": ACCOUNTING_VERSION,
    }
    if extra:
        out.update(extra)
    return out


def _fail(error: str, **extra: Any) -> Dict[str, Any]:
    out = {
        "ok": False,
        "save_allowed": False,
        "error": error,
        "emissions_kg": None,
        "total_kg_co2e": None,
        "total_t_co2e": None,
        "emissions_tco2e": None,
    }
    out.update(extra)
    return out


def _require_period(period: Optional[str]) -> Optional[str]:
    if parse_period_month(period) is None:
        return "period must be YYYY-MM matching a valid calendar month"
    return None


def _sheet_rows(
    db: Session,
    *,
    codes: List[str],
    name_hints: List[str],
) -> Tuple[List[Dict[str, Any]], Optional[str], Optional[str]]:
    ds = resolve_dataset(db, codes, name_hints)
    if ds is None:
        return [], None, None
    rows = fetch_all_rows_for_dataset(db, ds.id)
    legacy = [factor_row_to_legacy_record(r) for r in rows]
    # Attach factor_row_id when present on ORM rows
    for legacy_row, orm in zip(legacy, rows):
        legacy_row["_factor_row_id"] = str(orm.id)
        legacy_row["_factor_dataset_id"] = str(ds.id)
    return legacy, str(ds.id), ds.code


def _pick(row: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] is not None and str(row[key]).strip() != "":
            return row[key]
    # case-insensitive
    lower = {str(k).strip().lower(): v for k, v in row.items()}
    for key in keys:
        v = lower.get(key.lower())
        if v is not None and str(v).strip() != "":
            return v
    return None


def resolve_freight_factor(db: Session, *, vehicle_type: str) -> Dict[str, Any]:
    rows, dataset_id, dataset_code = _sheet_rows(
        db,
        codes=["upstream_transportation_and_distribution", "upstream_transportation"],
        name_hints=["Upstream Transportation and Distribution", "upstream transportation"],
    )
    if not rows:
        return _fail(
            "Freight factor dataset is unavailable. Verified Categories 4/9 require "
            "Upstream Transportation and Distribution with Units."
        )
    target = norm_cell(vehicle_type).lower()
    matches = []
    for row in rows:
        name = norm_cell(
            _pick(row, "Vehicle Type", "vehicle_type", "vehicleType")
        )
        if name.lower() != target:
            continue
        unit = norm_cell(_pick(row, "Units", "Unit", "unit", "units"))
        factor = parse_number(
            _pick(
                row,
                "CO2 Factor (kg CO2 / unit)",
                " CO2 Factor (kg CO2 / unit) ",
                "CO2 Factor",
                "co2_factor",
            )
        )
        if factor is None or not unit:
            continue
        matches.append(
            {
                "vehicle_type": name,
                "factor_value": float(factor),
                "factor_unit": unit,
                "factor_row_id": row.get("_factor_row_id"),
                "dataset_id": dataset_id or row.get("_factor_dataset_id"),
                "dataset_code": dataset_code or "upstream_transportation_and_distribution",
                "gas_coverage": "CO2",
                "geography": "factor_sheet",
            }
        )
    if not matches:
        return _fail(f"No freight factor with a unit was found for vehicle type '{vehicle_type}'")
    if len(matches) > 1:
        return _fail(f"Ambiguous freight factors for vehicle type '{vehicle_type}'")
    return {"ok": True, "factor": matches[0]}


def calculate_verified_freight(
    db: Session,
    *,
    vehicle_type: str,
    distance_km: float,
    weight_kg: float,
    period: str,
    client_co2_factor: Optional[float] = None,
    client_emissions: Optional[float] = None,
) -> Dict[str, Any]:
    _ = client_co2_factor, client_emissions  # never trusted
    err = _require_period(period)
    if err:
        return _fail(err)
    resolved = resolve_freight_factor(db, vehicle_type=vehicle_type)
    if not resolved.get("ok"):
        return resolved
    factor = resolved["factor"]
    kg, calc_err = freight_emissions_kg(
        distance_km=float(distance_km),
        weight_kg=float(weight_kg) if weight_kg is not None else 0.0,
        co2_factor=float(factor["factor_value"]),
        factor_unit=factor["factor_unit"],
    )
    if calc_err or kg is None:
        return _fail(calc_err or "Freight calculation failed")
    return _ok_calc(
        emissions_kg=kg,
        period=period,
        category="upstream_transportation",
        method="scope3_freight_v1",
        quantity=float(distance_km),
        unit="km",
        inputs={
            "vehicle_type": vehicle_type,
            "distance_km": distance_km,
            "weight_kg": weight_kg,
        },
        factor=factor,
        extra={"category_alt": "downstream_transportation"},
    )


def resolve_travel_factor(db: Session, *, vehicle_type: str) -> Dict[str, Any]:
    rows, dataset_id, dataset_code = _sheet_rows(
        db,
        codes=["business_travel", "business travel"],
        name_hints=["business travel", "Business Travel"],
    )
    if not rows:
        return _fail(
            "Business travel factor dataset is unavailable. Verified Categories 6/7 require "
            "the business travel sheet with Units."
        )
    target = norm_cell(vehicle_type).lower()
    matches = []
    for row in rows:
        name = norm_cell(_pick(row, "Vehicle Type", "vehicle_type", "Mode", "mode"))
        if name.lower() != target:
            continue
        unit = norm_cell(_pick(row, "Units", "Unit", "unit", "units"))
        factor = parse_number(
            _pick(
                row,
                "CO2 Factor \n(kg CO2 / unit)",
                "CO2 Factor (kg CO2 / unit)",
                "CO2 Factor",
                "co2_factor",
            )
        )
        if factor is None or not unit:
            continue
        matches.append(
            {
                "vehicle_type": name,
                "factor_value": float(factor),
                "factor_unit": unit,
                "factor_row_id": row.get("_factor_row_id"),
                "dataset_id": dataset_id or row.get("_factor_dataset_id"),
                "dataset_code": dataset_code or "business_travel",
                "gas_coverage": "CO2",
                "geography": "factor_sheet",
            }
        )
    if not matches:
        return _fail(f"No travel factor with a unit was found for '{vehicle_type}'")
    if len(matches) > 1:
        return _fail(f"Ambiguous travel factors for '{vehicle_type}'")
    return {"ok": True, "factor": matches[0]}


def calculate_verified_business_travel(
    db: Session,
    *,
    vehicle_type: str,
    distance_km: float,
    period: str,
    client_co2_factor: Optional[float] = None,
    client_emissions: Optional[float] = None,
) -> Dict[str, Any]:
    _ = client_co2_factor, client_emissions
    err = _require_period(period)
    if err:
        return _fail(err)
    resolved = resolve_travel_factor(db, vehicle_type=vehicle_type)
    if not resolved.get("ok"):
        return resolved
    factor = resolved["factor"]
    kg, calc_err = travel_distance_emissions_kg(
        distance_km=float(distance_km),
        co2_factor=float(factor["factor_value"]),
        factor_unit=factor["factor_unit"],
    )
    if calc_err or kg is None:
        return _fail(calc_err or "Business travel calculation failed")
    return _ok_calc(
        emissions_kg=kg,
        period=period,
        category="business_travel",
        method="scope3_business_travel_v1",
        quantity=float(distance_km),
        unit="km",
        inputs={"vehicle_type": vehicle_type, "distance_km": distance_km},
        factor=factor,
    )


def calculate_verified_employee_commuting(
    db: Session,
    *,
    vehicle_type: str,
    distance_km: float,
    employees: float,
    period: str,
    distance_basis: Optional[str] = "annual_total",
    working_days_per_year: Optional[float] = None,
    client_co2_factor: Optional[float] = None,
    client_emissions: Optional[float] = None,
) -> Dict[str, Any]:
    _ = client_co2_factor, client_emissions
    err = _require_period(period)
    if err:
        return _fail(err)
    if not (employees > 0):
        return _fail("employees must be > 0")
    resolved = resolve_travel_factor(db, vehicle_type=vehicle_type)
    if not resolved.get("ok"):
        return resolved
    factor = resolved["factor"]
    annual_km, ann_err = annualize_commuting_distance_km(
        distance_km=float(distance_km),
        distance_basis=distance_basis,
        working_days_per_year=working_days_per_year,
    )
    if ann_err or annual_km is None:
        return _fail(ann_err or "Commuting distance annualization failed")
    trip_kg, calc_err = travel_distance_emissions_kg(
        distance_km=annual_km,
        co2_factor=float(factor["factor_value"]),
        factor_unit=factor["factor_unit"],
    )
    if calc_err or trip_kg is None:
        return _fail(calc_err or "Employee commuting calculation failed")
    kg = float(employees) * float(trip_kg)
    return _ok_calc(
        emissions_kg=kg,
        period=period,
        category="employee_commuting",
        method="scope3_employee_commuting_v1",
        quantity=float(distance_km),
        unit="km",
        inputs={
            "vehicle_type": vehicle_type,
            "distance_km": distance_km,
            "employees": employees,
            "distance_basis": distance_basis or "annual_total",
            "working_days_per_year": working_days_per_year,
            "annual_distance_km": annual_km,
        },
        factor=factor,
    )


def _waste_metadata_ok(db: Session) -> bool:
    """Structured metadata must exist — table comments are not proof."""
    try:
        from sqlalchemy import text

        row = db.execute(
            text(
                "SELECT factor_unit FROM public.waste_factor_unit_metadata "
                "WHERE dataset_code = 'waste' LIMIT 1"
            )
        ).first()
    except Exception:
        return False
    if row is None:
        return False
    unit = str(row[0] or "").strip()
    return unit == WASTE_DATASET_FACTOR_UNIT


def resolve_waste_factor(
    db: Session, *, material: str, disposal_method: str
) -> Dict[str, Any]:
    if disposal_method not in DISPOSAL_METHODS:
        return _fail(f"Unsupported waste disposal method: {disposal_method}")
    if not _waste_metadata_ok(db):
        return _fail(
            "Waste factor unit metadata is not installed. Apply the reviewed "
            "structured waste metadata migration before verified Cat 5/12 saves. "
            "Table comments alone are not authoritative."
        )
    rows, dataset_id, dataset_code = _sheet_rows(
        db,
        codes=["waste"],
        name_hints=["waste"],
    )
    if not rows:
        return _fail("Waste factor dataset is unavailable")
    materials = build_waste_materials(rows)
    target = norm_cell(material).lower()
    mat = next((m for m in materials if str(m.get("material", "")).lower() == target), None)
    if mat is None:
        return _fail(f"Waste material '{material}' not found")
    factor = get_emission_factor(mat, disposal_method)
    if factor is None:
        return _fail(
            f"No numeric factor for {material} / {disposal_method} (NA or missing)"
        )
    # Find matching ORM row id if possible
    factor_row_id = None
    for row in rows:
        name = norm_cell(_pick(row, " Material ", "Material", "material"))
        if name.lower() == target:
            factor_row_id = row.get("_factor_row_id")
            break
    return {
        "ok": True,
        "factor": {
            "material": material,
            "disposal_method": disposal_method,
            "factor_value": float(factor),
            "factor_unit": WASTE_DATASET_FACTOR_UNIT,
            "mass_unit": "kg",
            "factor_row_id": factor_row_id,
            "dataset_id": dataset_id,
            "dataset_code": dataset_code or "waste",
            "gas_coverage": "CO2e",
            "geography": "factor_sheet",
            "treatment_boundary": disposal_method,
        },
    }


def calculate_verified_waste(
    db: Session,
    *,
    material: str,
    disposal_method: str,
    mass_kg: float,
    period: str,
    client_factor: Optional[float] = None,
    client_emissions: Optional[float] = None,
) -> Dict[str, Any]:
    _ = client_factor, client_emissions
    err = _require_period(period)
    if err:
        return _fail(err)
    resolved = resolve_waste_factor(db, material=material, disposal_method=disposal_method)
    if not resolved.get("ok"):
        return resolved
    factor = resolved["factor"]
    from .scope3_factor_units import waste_emissions_kg

    kg, calc_err = waste_emissions_kg(
        mass=float(mass_kg),
        mass_unit="kg",
        factor=float(factor["factor_value"]),
        factor_unit=factor["factor_unit"],
    )
    if calc_err or kg is None:
        return _fail(calc_err or "Waste calculation failed")
    return _ok_calc(
        emissions_kg=kg,
        period=period,
        category="waste_generated",
        method="scope3_waste_v1",
        quantity=float(mass_kg),
        unit="kg",
        inputs={
            "material": material,
            "disposal_method": disposal_method,
            "mass_kg": mass_kg,
        },
        factor=factor,
        extra={"category_alt": "end_of_life"},
    )


def resolve_supplier_factor(db: Session, *, supplier_id: Optional[str] = None, supplier_code: Optional[str] = None) -> Dict[str, Any]:
    rows, dataset_id, dataset_code = _sheet_rows(
        db,
        codes=["suppliers"],
        name_hints=["suppliers", "Suppliers"],
    )
    # Also try direct SQL on public.suppliers if factor sheet empty
    if not rows:
        try:
            from sqlalchemy import text

            if supplier_id:
                row = db.execute(
                    text(
                        "SELECT id::text, code, supplier_name, unit, emission_factor "
                        "FROM public.suppliers WHERE id::text = :id LIMIT 1"
                    ),
                    {"id": supplier_id},
                ).mappings().first()
            elif supplier_code:
                row = db.execute(
                    text(
                        "SELECT id::text, code, supplier_name, unit, emission_factor "
                        "FROM public.suppliers WHERE code = :code LIMIT 1"
                    ),
                    {"code": supplier_code},
                ).mappings().first()
            else:
                row = None
            if row is None:
                return _fail("Supplier factor not found")
            return {
                "ok": True,
                "factor": {
                    "supplier_id": row["id"],
                    "supplier_code": row["code"],
                    "supplier_name": row["supplier_name"],
                    "factor_value": float(row["emission_factor"]),
                    "factor_unit": str(row["unit"]),
                    "factor_row_id": row["id"],
                    "dataset_id": None,
                    "dataset_code": "suppliers",
                    "gas_coverage": "CO2e",
                    "geography": "purchaser_price",
                    "price_year": 2022,
                    "currency": "USD",
                },
            }
        except Exception:
            return _fail(
                "Suppliers factor dataset is unavailable for verified Categories 1/2"
            )

    matches = []
    for row in rows:
        rid = str(row.get("id") or row.get("_factor_row_id") or "")
        code = norm_cell(_pick(row, "code", "Code"))
        if supplier_id and rid != str(supplier_id):
            continue
        if supplier_code and code != norm_cell(supplier_code):
            continue
        if not supplier_id and not supplier_code:
            continue
        unit = norm_cell(_pick(row, "unit", "Unit"))
        factor = parse_number(_pick(row, "emission_factor", "Emission Factor"))
        if factor is None or not unit:
            continue
        matches.append(
            {
                "supplier_id": rid or None,
                "supplier_code": code,
                "supplier_name": norm_cell(_pick(row, "supplier_name", "Supplier Name")),
                "factor_value": float(factor),
                "factor_unit": unit,
                "factor_row_id": row.get("_factor_row_id") or rid or None,
                "dataset_id": dataset_id,
                "dataset_code": dataset_code or "suppliers",
                "gas_coverage": "CO2e",
                "geography": "purchaser_price",
            }
        )
    if not matches:
        return _fail("Supplier factor not found or missing unit")
    if len(matches) > 1:
        return _fail("Ambiguous supplier factors")
    return {"ok": True, "factor": matches[0]}


def calculate_verified_spend(
    db: Session,
    *,
    amount: float,
    period: str,
    category: str = "purchased_goods",
    supplier_id: Optional[str] = None,
    supplier_code: Optional[str] = None,
    activity_currency: str = "USD",
    activity_price_year: int = 2022,
    client_emission_factor: Optional[float] = None,
    client_emissions: Optional[float] = None,
) -> Dict[str, Any]:
    _ = client_emission_factor, client_emissions
    err = _require_period(period)
    if err:
        return _fail(err)
    if category not in ("purchased_goods", "capital_goods"):
        return _fail("Spend category must be purchased_goods or capital_goods")
    resolved = resolve_supplier_factor(db, supplier_id=supplier_id, supplier_code=supplier_code)
    if not resolved.get("ok"):
        return resolved
    factor = resolved["factor"]
    kg, calc_err = spend_emissions_kg(
        amount=float(amount),
        emission_factor=float(factor["factor_value"]),
        factor_unit=factor["factor_unit"],
        activity_currency=activity_currency,
        activity_price_year=activity_price_year,
    )
    if calc_err or kg is None:
        return _fail(calc_err or "Spend-based calculation failed")
    return _ok_calc(
        emissions_kg=kg,
        period=period,
        category=category,
        method="scope3_spend_v1",
        quantity=float(amount),
        unit=activity_currency,
        inputs={
            "amount": amount,
            "activity_currency": activity_currency,
            "activity_price_year": activity_price_year,
            "supplier_id": supplier_id,
            "supplier_code": supplier_code,
        },
        factor=factor,
    )
