"""POST /api/v1/uop/calculate — PCAF §5.7 engine. JWT org-scoped.

Underlying UoP draft rows stay non-reportable. Reportable Save, when the
release flag is on, upserts one parent in app.financed_emissions.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..auth_org import OrgContext
from ..db import get_db
from .financed_emissions import _persist_financed_row
from ..uop_calc import UopCalcError, calculate_uop_draft
from ..uop_calc_schemas import UopCalculateRequest, UopCalculateResponse
from ..uop_reportable import (
    PCAF_OVERLAP_REF,
    assert_no_unresolved_overlap,
    assert_reportable_gates,
    assert_reporting_year_not_overwrite,
    attach_fingerprint,
    parent_inputs,
    persist_fields,
    scan_uop_general_purpose_overlap,
)
from ..uop_drafts import (
    _assets_for_structure,
    _calcs_for_structure,
    _check_investment_lock,
    _check_structure_lock,
    _commit,
    _compose_draft,
    _find_calc,
    _investments_for_structure,
    _now,
    find_investment_by_instance,
    get_org_investment,
    get_org_structure,
)
from ..uop_models import UopAssetCalculation, UopInvestment
from .deps import require_org_context

router = APIRouter(prefix="/uop", tags=["uop-calculate"])


def _merge_draft(stored: Dict[str, Any], overlay: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    merged = dict(stored or {})
    if overlay:
        merged.update(overlay)
        if "eligibility" in overlay:
            merged["eligibility"] = overlay["eligibility"]
        if "assets" in overlay:
            merged["assets"] = overlay["assets"]
    return merged


def _persist_result(
    db: Session,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    investment: UopInvestment,
    result: Dict[str, Any],
) -> None:
    structure = get_org_structure(db, organization_id, investment.structure_id)
    assets = _assets_for_structure(db, organization_id, structure.id)
    existing_calcs = _calcs_for_structure(db, organization_id, structure.id)
    by_frontend_id = {row.underlying_asset_id: row for row in assets}
    for asset_result in result.get("assets") or []:
        frontend_id = asset_result.get("underlying_asset_id")
        asset_row = by_frontend_id.get(frontend_id) if frontend_id else None
        if asset_row is None:
            continue
        calc = _find_calc(
            existing_calcs,
            asset_id=asset_row.id,
            investment_id=investment.id,
            reporting_year=structure.reporting_year,
            methodology_version=structure.methodology_version,
        )
        payload = {
            "kind": "uop_underlying_calculation",
            "phase": "5C",
            "formula_implemented": True,
            "updated_by": str(user_id),
            "result": asset_result,
        }
        financed = asset_result.get("investor_financed_emissions")
        if calc is None:
            calc = UopAssetCalculation(
                id=uuid.uuid4(),
                organization_id=organization_id,
                structure_id=structure.id,
                asset_id=asset_row.id,
                investment_id=investment.id,
                reporting_year=structure.reporting_year,
                methodology_version=structure.methodology_version,
                formula_id=result.get("formula_id"),
                status="draft",
                inputs={},
                results={},
                include_in_portfolio=False,
                is_reportable=False,
                provenance={},
                created_at=_now(),
                updated_at=_now(),
            )
            db.add(calc)
        calc.formula_id = result.get("formula_id")
        calc.status = "draft"
        calc.inputs = {
            "underlying_asset_id": asset_row.underlying_asset_id,
            "asset_class": asset_row.asset_class,
            "financing_instance_id": investment.financing_instance_id,
        }
        calc.results = payload
        calc.financed_emissions = None if financed is None else Decimal(str(financed))
        calc.attribution_factor = (
            None
            if asset_result.get("combined_attribution_factor") is None
            else Decimal(str(asset_result["combined_attribution_factor"]))
        )
        calc.data_quality_score = (
            None
            if asset_result.get("data_quality_score") is None
            else Decimal(str(asset_result["data_quality_score"]))
        )
        calc.financed_scope1_tco2e = _dec(asset_result.get("investor_scope1_tco2e"))
        calc.financed_scope2_tco2e = _dec(asset_result.get("investor_scope2_tco2e"))
        calc.financed_scope3_tco2e = _dec(asset_result.get("investor_scope3_tco2e"))
        calc.include_in_portfolio = False
        calc.is_reportable = False
        calc.provenance = {
            "kind": "uop_underlying_calculation",
            "phase": "5C",
            "formula_implemented": True,
            "reportable": False,
            "updated_by": str(user_id),
        }
        calc.updated_at = _now()

    snapshot = dict(investment.draft_snapshot or {})
    stored = dict(result)
    stored["calculated_at"] = _now().isoformat()
    stored["is_reportable"] = False
    stored["include_in_portfolio"] = False
    stored["persisted"] = True
    snapshot["lastCalculation"] = stored
    investment.draft_snapshot = snapshot
    investment.formula_id = result.get("formula_id")
    investment.formula_name = result.get("formula_name")
    investment.status = "draft"
    investment.is_reportable = False
    investment.include_in_portfolio = False
    investment.updated_at = _now()
    db.add(investment)
    _commit(db)


def _dec(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    return Decimal(str(value))


@router.post("/calculate", response_model=UopCalculateResponse)
def calculate_uop(
    body: UopCalculateRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> UopCalculateResponse:
    investment: Optional[UopInvestment] = None
    stored_draft: Dict[str, Any] = {}
    if body.investment_id is not None:
        investment = get_org_investment(db, ctx.organization_id, body.investment_id)
    elif body.financing_instance_id:
        investment = find_investment_by_instance(
            db,
            organization_id=ctx.organization_id,
            financing_instance_id=body.financing_instance_id,
            counterparty_id=body.counterparty_id,
        )

    if investment is not None:
        if (
            body.structure_id is not None
            and body.structure_id != investment.structure_id
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="structure_id does not match this financing_instance_id.",
            )
        structure = get_org_structure(db, ctx.organization_id, investment.structure_id)
        _check_investment_lock(investment, body.expected_investment_updated_at)
        siblings = [
            row
            for row in _investments_for_structure(db, ctx.organization_id, structure.id)
            if row.id != investment.id
        ]
        if body.persist or body.persist_reportable:
            _check_structure_lock(
                structure,
                body.expected_structure_updated_at,
                siblings=siblings,
            )
        assets = _assets_for_structure(db, ctx.organization_id, structure.id)
        stored_draft = _compose_draft(structure, investment, assets)

    draft = _merge_draft(stored_draft, body.draft)
    if not draft:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A UoP draft snapshot or an existing financing_instance_id is required.",
        )
    if investment is not None:
        draft.setdefault("financingInstanceId", investment.financing_instance_id)

    try:
        result = calculate_uop_draft(draft, issuer_level=body.issuer_level)
    except UopCalcError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    reporting_year = None
    issuer_name = draft.get("issuerName") or draft.get("issuer_name")
    structure = None
    if investment is not None:
        structure = get_org_structure(db, ctx.organization_id, investment.structure_id)
        reporting_year = structure.reporting_year
        issuer_name = structure.issuer_name or issuer_name
        attach_fingerprint(
            result,
            reporting_year=reporting_year,
            structure_updated_at=structure.updated_at,
            investment_updated_at=investment.updated_at,
        )
        result["financing_instance_id"] = investment.financing_instance_id
        result["structure_id"] = str(investment.structure_id)
        result["investment_id"] = str(investment.id)
    else:
        reporting_year = draft.get("reportingYear") or draft.get("reporting_year")
        attach_fingerprint(result, reporting_year=reporting_year)
        result["financing_instance_id"] = draft.get("financingInstanceId")

    instance_id = result.get("financing_instance_id")
    counterparty_id = (
        investment.counterparty_id
        if investment is not None
        else body.counterparty_id
    )
    overlap_items = []
    if instance_id:
        overlap_items = scan_uop_general_purpose_overlap(
            db,
            organization_id=ctx.organization_id,
            counterparty_id=counterparty_id,
            reporting_year=reporting_year,
            financing_instance_id=instance_id,
            issuer_name=issuer_name,
        )
    result["overlap"] = {
        "detected": bool(overlap_items),
        "status": "review_required" if overlap_items else "none",
        "items": overlap_items,
        "redistribution": "none",
        "pcaf_ref": PCAF_OVERLAP_REF,
    }

    persist_underlying = body.persist or body.persist_reportable
    persisted = False
    if persist_underlying:
        if investment is None:
            result.setdefault("warnings", []).append(
                "Persist requires an existing UoP draft (financing_instance_id or investment_id)."
            )
        elif result.get("status") != "complete":
            result.setdefault("warnings", []).append(
                "Incomplete or unsupported calculations are not persisted."
            )
        else:
            _persist_result(
                db,
                organization_id=ctx.organization_id,
                user_id=ctx.user.id,
                investment=investment,
                result=result,
            )
            persisted = True

    persisted_reportable = False
    reportable_record_id = None
    if body.persist_reportable:
        if investment is None or structure is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "UOP_DRAFT_REQUIRED",
                    "message": "Reportable Save requires an existing UoP draft holding.",
                },
            )
        assert_reportable_gates(
            result,
            expected_fingerprint=body.expected_fingerprint,
            financing_instance_id=investment.financing_instance_id,
            reporting_year=reporting_year,
        )
        assert_no_unresolved_overlap(overlap_items)
        assert_reporting_year_not_overwrite(
            db,
            organization_id=ctx.organization_id,
            counterparty_id=investment.counterparty_id,
            financing_instance_id=investment.financing_instance_id,
            reporting_year=str(reporting_year),
        )
        inputs = parent_inputs(
            result,
            financing_instance_id=investment.financing_instance_id,
            reporting_year=str(reporting_year),
            structure_id=str(investment.structure_id),
            investment_id=str(investment.id),
            issuer_name=issuer_name,
            counterparty_id=investment.counterparty_id,
        )
        fields = persist_fields(result, inputs, overlap_items)
        record = _persist_financed_row(
            db,
            organization_id=ctx.organization_id,
            user_id=ctx.user.id,
            calc_kind="finance",
            formula_id=result.get("formula_id"),
            fields=fields,
        )
        persisted_reportable = True
        reportable_record_id = str(record.id)
        result["is_reportable"] = True
        result["include_in_portfolio"] = True
        result["double_count_guard"] = (
            "This parent is the only reportable UoP total for the financing "
            "instance. Underlying asset calculations stay non-reportable."
        )
    else:
        result["is_reportable"] = False
        result["include_in_portfolio"] = False

    result["persisted"] = persisted
    result["persisted_reportable"] = persisted_reportable
    result["reportable_record_id"] = reportable_record_id
    return UopCalculateResponse.model_validate(result)
