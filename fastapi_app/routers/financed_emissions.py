"""CRUD + calculate for app.financed_emissions (org-scoped)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth_org import OrgContext
from ..calculation_engine import CalculationEngine
from ..db import get_db
from ..finance_models import CompanyType
from ..ghg_models import FinancedEmission
from ..ppp_gdp import apply_ppp_resolution, is_sovereign_formula
from ..schemas_v1 import (
    CALC_KINDS,
    FinancedCalculateRequest,
    FinancedCalculateResponse,
    FinancedEmissionCreate,
    FinancedEmissionOut,
    FinancedEmissionUpdate,
    MessageOut,
)
from .deps import require_org_context

router = APIRouter(prefix="/financed-emissions", tags=["financed-emissions"])

_calc_engine: Optional[CalculationEngine] = None


def _engine() -> CalculationEngine:
    global _calc_engine
    if _calc_engine is None:
        _calc_engine = CalculationEngine()
    return _calc_engine


def _validate_calc_kind(value: str) -> str:
    if value not in CALC_KINDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"calc_kind must be one of: {list(CALC_KINDS)}",
        )
    return value


def _get_org_row(
    db: Session, organization_id: uuid.UUID, row_id: uuid.UUID
) -> FinancedEmission:
    row = (
        db.query(FinancedEmission)
        .filter(
            FinancedEmission.id == row_id,
            FinancedEmission.organization_id == organization_id,
        )
        .first()
    )
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Financed emission record not found",
        )
    return row


def _result_to_dict(calc_result: Any) -> Dict[str, Any]:
    steps = []
    for step in calc_result.calculation_steps or []:
        if hasattr(step, "step"):
            steps.append(
                {"step": step.step, "value": step.value, "formula": step.formula}
            )
        else:
            steps.append(step)
    return {
        "attribution_factor": calc_result.attribution_factor,
        "emission_factor": calc_result.emission_factor,
        "financed_emissions": calc_result.financed_emissions,
        "data_quality_score": calc_result.data_quality_score,
        "methodology": calc_result.methodology,
        "calculation_steps": steps,
        "metadata": calc_result.metadata,
    }


@router.get("", response_model=List[FinancedEmissionOut])
def list_financed_emissions(
    calc_kind: Optional[str] = None,
    counterparty_id: Optional[uuid.UUID] = None,
    status_filter: Optional[str] = Query(default=None, alias="status"),
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> List[FinancedEmission]:
    q = db.query(FinancedEmission).filter(
        FinancedEmission.organization_id == ctx.organization_id
    )
    if calc_kind:
        q = q.filter(FinancedEmission.calc_kind == _validate_calc_kind(calc_kind))
    if counterparty_id is not None:
        q = q.filter(FinancedEmission.counterparty_id == counterparty_id)
    if status_filter:
        q = q.filter(FinancedEmission.status == status_filter)
    return q.order_by(FinancedEmission.created_at.desc()).all()


@router.post("", response_model=FinancedEmissionOut, status_code=status.HTTP_201_CREATED)
def create_financed_emission(
    body: FinancedEmissionCreate,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> FinancedEmission:
    calc_kind = _validate_calc_kind(body.calc_kind)
    row = FinancedEmission(
        organization_id=ctx.organization_id,
        user_id=ctx.user.id,
        counterparty_id=body.counterparty_id,
        exposure_id=body.exposure_id,
        questionnaire_id=body.questionnaire_id,
        calc_kind=calc_kind,
        company_type=body.company_type,
        formula_id=body.formula_id,
        formula_name=body.formula_name,
        inputs=body.inputs or {},
        results=body.results or {},
        financed_emissions=body.financed_emissions,
        attribution_factor=body.attribution_factor,
        data_quality_score=body.data_quality_score,
        status=body.status,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Could not create financed emission: {exc.orig}",
        ) from exc
    db.refresh(row)
    return row


@router.post("/calculate", response_model=FinancedCalculateResponse)
def calculate_and_persist(
    body: FinancedCalculateRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> FinancedCalculateResponse:
    """
    Run the existing calculation engine and optionally save to app.financed_emissions.
    Does not change formula logic — thin persist wrapper around CalculationEngine.
    """
    calc_kind = _validate_calc_kind(body.calc_kind)
    company_type = (
        CompanyType.LISTED
        if body.company_type in ("listed", CompanyType.LISTED.value)
        else CompanyType.PRIVATE
    )
    inputs = dict(body.inputs or {})
    if inputs.get("resolve_ppp_gdp") or is_sovereign_formula(body.formula_id):
        try:
            inputs = apply_ppp_resolution(
                db,
                inputs,
                require_country=bool(inputs.get("resolve_ppp_gdp")),
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc
    try:
        calc_result = _engine().calculate(
            formula_id=body.formula_id,
            inputs=inputs,
            company_type=company_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal calculation error",
        ) from exc

    result_dict = _result_to_dict(calc_result)
    record: Optional[FinancedEmission] = None
    if body.persist:
        record = FinancedEmission(
            organization_id=ctx.organization_id,
            user_id=ctx.user.id,
            counterparty_id=body.counterparty_id,
            exposure_id=body.exposure_id,
            calc_kind=calc_kind,
            company_type=body.company_type,
            formula_id=body.formula_id,
            formula_name=result_dict.get("methodology"),
            inputs=inputs,
            results=result_dict,
            financed_emissions=Decimal(str(calc_result.financed_emissions)),
            attribution_factor=Decimal(str(calc_result.attribution_factor)),
            data_quality_score=Decimal(str(calc_result.data_quality_score)),
            status="completed",
        )
        db.add(record)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Could not persist calculation: {exc.orig}",
            ) from exc
        db.refresh(record)

    return FinancedCalculateResponse(
        success=True,
        result=result_dict,
        record=FinancedEmissionOut.model_validate(record) if record else None,
    )


@router.get("/{record_id}", response_model=FinancedEmissionOut)
def get_financed_emission(
    record_id: uuid.UUID,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> FinancedEmission:
    return _get_org_row(db, ctx.organization_id, record_id)


@router.patch("/{record_id}", response_model=FinancedEmissionOut)
def patch_financed_emission(
    record_id: uuid.UUID,
    body: FinancedEmissionUpdate,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> FinancedEmission:
    row = _get_org_row(db, ctx.organization_id, record_id)
    data = body.model_dump(exclude_unset=True)
    if "calc_kind" in data and data["calc_kind"] is not None:
        data["calc_kind"] = _validate_calc_kind(data["calc_kind"])
    for key, value in data.items():
        setattr(row, key, value)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/{record_id}", response_model=MessageOut)
def delete_financed_emission(
    record_id: uuid.UUID,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> MessageOut:
    row = _get_org_row(db, ctx.organization_id, record_id)
    db.delete(row)
    db.commit()
    return MessageOut(status="ok", message="Financed emission deleted")
