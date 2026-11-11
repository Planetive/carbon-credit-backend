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
from ..financed_scope_breakdown import breakdown_api_fields
from ..financing_instance import (
    FINANCING_INSTANCE_FIELD,
    can_upsert_by_instance,
    ensure_identity_in_results,
    extract_financing_instance_id,
    extract_reporting_year,
    find_row_by_financing_instance,
    financing_instance_json_expr,
    normalize_financing_instance_id,
    normalize_reporting_year,
    preserve_financing_instance_in_inputs,
    year_aware_identity_available,
)
from ..uop_drafts import is_uop_formula_id, uop_reportable_blocked_detail
from ..ssp_drafts import is_ssp_formula_id, ssp_reportable_blocked_detail
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
    metadata = dict(calc_result.metadata or {})
    metadata.setdefault("emissions_unit", "tCO2e")
    payload = {
        "attribution_factor": calc_result.attribution_factor,
        "emission_factor": calc_result.emission_factor,
        "financed_emissions": calc_result.financed_emissions,
        "data_quality_score": calc_result.data_quality_score,
        "methodology": calc_result.methodology,
        "calculation_steps": steps,
        "emissions_unit": "tCO2e",
        "metadata": metadata,
    }
    payload.update(breakdown_api_fields(metadata))
    return payload


def _persist_financed_row(
    db: Session,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    calc_kind: str,
    formula_id: Optional[str],
    fields: Dict[str, Any],
) -> FinancedEmission:
    """
    Insert a new row, or update the existing non-aggregate row that shares the
    same (organization_id, counterparty_id, calc_kind, inputs.financing_instance_id).

    Missing instance IDs always insert — never overwrite by formula_id alone.
    Aggregate rows always insert (identity uniqueness does not apply).
    """
    inputs = preserve_financing_instance_in_inputs(fields.get("inputs"))
    instance_id = extract_financing_instance_id(inputs)
    requested_year = normalize_reporting_year(
        inputs.get("reporting_year") or inputs.get("reportingYear")
    )
    if requested_year:
        inputs["reporting_year"] = requested_year
    results = ensure_identity_in_results(fields.get("results"), instance_id)
    fields = {**fields, "inputs": inputs, "results": results}

    existing: Optional[FinancedEmission] = None
    if can_upsert_by_instance(
        formula_id=formula_id, financing_instance_id=instance_id
    ):
        assert instance_id is not None
        existing = find_row_by_financing_instance(
            db,
            organization_id=organization_id,
            calc_kind=calc_kind,
            financing_instance_id=instance_id,
            counterparty_id=fields.get("counterparty_id"),
            reporting_year=requested_year,
            for_update=True,
        )
        if existing is None and requested_year:
            other = find_row_by_financing_instance(
                db,
                organization_id=organization_id,
                calc_kind=calc_kind,
                financing_instance_id=instance_id,
                counterparty_id=fields.get("counterparty_id"),
                for_update=False,
            )
            other_year = extract_reporting_year(other) if other is not None else None
            if other is not None and other_year and other_year != requested_year:
                if not year_aware_identity_available(db):
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={
                            "code": "REPORTING_YEAR_CONFLICT",
                            "message": (
                                "app.financed_emissions unique identity (migration 0014) "
                                "does not include reporting year. Saving a different year "
                                "would overwrite the existing instance. Apply prepared "
                                "migration 0017 before storing a second reporting year."
                            ),
                            "existing_reporting_year": other_year,
                            "requested_reporting_year": requested_year,
                            "financing_instance_id": instance_id,
                        },
                    )

    if existing is not None:
        for key, value in fields.items():
            setattr(existing, key, value)
        existing.formula_id = formula_id
        # Recalculation of one loan must not change ownership metadata.
        existing.organization_id = organization_id
        existing.user_id = user_id
        db.add(existing)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Concurrent save conflict for financing_instance_id; "
                    f"retry the request. ({exc.orig})"
                ),
            ) from exc
        db.refresh(existing)
        return existing

    row = FinancedEmission(
        organization_id=organization_id,
        user_id=user_id,
        formula_id=formula_id,
        **fields,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # Concurrent insert of the same instance id (after unique index exists).
        if can_upsert_by_instance(
            formula_id=formula_id, financing_instance_id=instance_id
        ):
            assert instance_id is not None
            raced = find_row_by_financing_instance(
                db,
                organization_id=organization_id,
                calc_kind=calc_kind,
                financing_instance_id=instance_id,
                counterparty_id=fields.get("counterparty_id"),
                reporting_year=requested_year,
                for_update=True,
            )
            if raced is not None:
                for key, value in fields.items():
                    setattr(raced, key, value)
                raced.organization_id = organization_id
                raced.user_id = user_id
                db.add(raced)
                try:
                    db.commit()
                except IntegrityError as exc2:
                    db.rollback()
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            "Concurrent save conflict for financing_instance_id; "
                            f"retry the request. ({exc2.orig})"
                        ),
                    ) from exc2
                db.refresh(raced)
                return raced
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Could not persist financed emission: {exc.orig}",
        ) from exc
    db.refresh(row)
    return row


@router.get("", response_model=List[FinancedEmissionOut])
def list_financed_emissions(
    calc_kind: Optional[str] = None,
    counterparty_id: Optional[uuid.UUID] = None,
    status_filter: Optional[str] = Query(default=None, alias="status"),
    financing_instance_id: Optional[str] = Query(default=None),
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
    instance = normalize_financing_instance_id(financing_instance_id)
    if instance:
        # Match unique/lookup index expression: btrim(inputs->>'financing_instance_id')
        q = q.filter(financing_instance_json_expr() == instance)
    return q.order_by(FinancedEmission.created_at.desc()).all()


@router.post("", response_model=FinancedEmissionOut, status_code=status.HTTP_201_CREATED)
def create_financed_emission(
    body: FinancedEmissionCreate,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> FinancedEmission:
    calc_kind = _validate_calc_kind(body.calc_kind)
    if is_uop_formula_id(body.formula_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=uop_reportable_blocked_detail(),
        )
    if is_ssp_formula_id(body.formula_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ssp_reportable_blocked_detail(),
        )
    return _persist_financed_row(
        db,
        organization_id=ctx.organization_id,
        user_id=ctx.user.id,
        calc_kind=calc_kind,
        formula_id=body.formula_id,
        fields={
            "counterparty_id": body.counterparty_id,
            "exposure_id": body.exposure_id,
            "questionnaire_id": body.questionnaire_id,
            "calc_kind": calc_kind,
            "company_type": body.company_type,
            "formula_name": body.formula_name,
            "inputs": body.inputs or {},
            "results": body.results or {},
            "financed_emissions": body.financed_emissions,
            "attribution_factor": body.attribution_factor,
            "data_quality_score": body.data_quality_score,
            "status": body.status,
        },
    )


@router.post("/calculate", response_model=FinancedCalculateResponse)
def calculate_and_persist(
    body: FinancedCalculateRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> FinancedCalculateResponse:
    """
    Run the existing calculation engine and optionally save to app.financed_emissions.
    Does not change formula logic — thin persist wrapper around CalculationEngine.

    When inputs.financing_instance_id is present on a non-aggregate formula,
    persist updates that instance in place instead of inserting a duplicate.
    """
    calc_kind = _validate_calc_kind(body.calc_kind)
    if is_uop_formula_id(body.formula_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=uop_reportable_blocked_detail(),
        )
    if is_ssp_formula_id(body.formula_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ssp_reportable_blocked_detail(),
        )
    company_type = (
        CompanyType.LISTED
        if body.company_type in ("listed", CompanyType.LISTED.value)
        else CompanyType.PRIVATE
    )
    inputs = preserve_financing_instance_in_inputs(body.inputs)
    instance_id = extract_financing_instance_id(inputs)
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
        # PPP enrichment must not drop the financing instance identity.
        if instance_id:
            inputs[FINANCING_INSTANCE_FIELD] = instance_id
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

    result_dict = ensure_identity_in_results(_result_to_dict(calc_result), instance_id)
    record: Optional[FinancedEmission] = None
    if body.persist:
        record = _persist_financed_row(
            db,
            organization_id=ctx.organization_id,
            user_id=ctx.user.id,
            calc_kind=calc_kind,
            formula_id=body.formula_id,
            fields={
                "counterparty_id": body.counterparty_id,
                "exposure_id": body.exposure_id,
                "calc_kind": calc_kind,
                "company_type": body.company_type,
                "formula_name": result_dict.get("methodology"),
                "inputs": inputs,
                "results": result_dict,
                "financed_emissions": Decimal(str(calc_result.financed_emissions)),
                "attribution_factor": Decimal(str(calc_result.attribution_factor)),
                "data_quality_score": Decimal(str(calc_result.data_quality_score)),
                "status": "completed",
            },
        )

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
    if "inputs" in data:
        data["inputs"] = preserve_financing_instance_in_inputs(data.get("inputs"))
        instance_id = extract_financing_instance_id(data["inputs"])
        if "results" in data:
            data["results"] = ensure_identity_in_results(
                data.get("results"), instance_id
            )
        elif instance_id:
            data["results"] = ensure_identity_in_results(
                dict(row.results or {}), instance_id
            )
    for key, value in data.items():
        setattr(row, key, value)
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Update conflicts with another financing_instance_id under this "
                f"organization/counterparty/calc_kind. ({exc.orig})"
            ),
        ) from exc
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
