"""POST /api/v1/ssp/calculate — PCAF §5.8 preview engine. Never reportable."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..auth_org import OrgContext
from ..db import get_db
from ..ssp_calc import calculate_ssp_draft
from ..ssp_calc_schemas import SspCalculateRequest, SspCalculateResponse
from ..ssp_drafts import (
    _check_deal_lock,
    _check_holding_lock,
    _compose_draft,
    _commit,
    _load_graph,
    _now,
    find_holding_by_instance,
    get_org_deal,
    get_org_holding,
)
from ..ssp_models import SSP_METHODOLOGY_VERSION, SspCalculation
from .deps import require_org_context

router = APIRouter(prefix="/ssp", tags=["ssp-calculate"])


def _merge_draft(stored: Dict[str, Any], overlay: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not overlay:
        return dict(stored or {})
    merged = dict(stored or {})
    for key, value in overlay.items():
        if key in (
            "eligibility",
            "deal",
            "collateral",
            "loans",
            "pools",
            "poolOfPools",
            "tranches",
            "holdings",
        ) and isinstance(value, (dict, list)):
            merged[key] = value
        else:
            merged[key] = value
    return merged


def _dec(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _persist_preview(
    db: Session,
    *,
    organization_id: uuid.UUID,
    deal_id: uuid.UUID,
    holding_id: uuid.UUID,
    reporting_year: Optional[str],
    result: Dict[str, Any],
) -> None:
    """Store non-reportable preview provenance only."""
    calc = SspCalculation(
        id=uuid.uuid4(),
        organization_id=organization_id,
        deal_id=deal_id,
        holding_id=holding_id,
        collateral_row_id=None,
        reporting_year=reporting_year,
        methodology_version=result.get("methodology_version") or SSP_METHODOLOGY_VERSION,
        formula_id=result.get("formula_id"),
        status="draft",
        inputs={
            "emissions_path": result.get("emissions_path"),
            "structure_type": result.get("structure_type"),
            "preview": True,
        },
        results=result,
        financed_emissions=_dec(result.get("financed_emissions")),
        attribution_factor=_dec(result.get("iaf")),
        data_quality_score=_dec(result.get("data_quality_score")),
        financed_scope1_tco2e=_dec((result.get("scope_breakdown") or {}).get("scope1")),
        financed_scope2_tco2e=_dec((result.get("scope_breakdown") or {}).get("scope2")),
        financed_scope3_tco2e=_dec((result.get("scope_breakdown") or {}).get("scope3")),
        include_in_portfolio=False,
        is_reportable=False,
        provenance={
            "kind": "ssp_preview_calculation",
            "phase": "6C.1",
            "reportable": False,
            "include_in_portfolio": False,
            "calculated_at": _now().isoformat(),
        },
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(calc)


@router.post("/calculate", response_model=SspCalculateResponse)
def calculate_ssp(
    body: SspCalculateRequest,
    ctx: OrgContext = Depends(require_org_context),
    db: Session = Depends(get_db),
) -> SspCalculateResponse:
    deal = None
    holding = None
    stored_draft: Dict[str, Any] = {}

    if body.financing_instance_id:
        holding = find_holding_by_instance(
            db,
            organization_id=ctx.organization_id,
            financing_instance_id=body.financing_instance_id,
            counterparty_id=body.counterparty_id,
        )
        if holding is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SSP holding not found")
        deal = get_org_deal(db, ctx.organization_id, holding.deal_id)
        graph = _load_graph(db, ctx.organization_id, deal.id)
        stored_draft = _compose_draft(deal, holding, graph)
        if body.expected_holding_updated_at is not None:
            _check_holding_lock(holding, body.expected_holding_updated_at)
        if body.expected_deal_updated_at is not None:
            _check_deal_lock(deal, body.expected_deal_updated_at)
    elif body.holding_id:
        holding = get_org_holding(db, ctx.organization_id, body.holding_id)
        if holding is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SSP holding not found")
        deal = get_org_deal(db, ctx.organization_id, holding.deal_id)
        graph = _load_graph(db, ctx.organization_id, deal.id)
        stored_draft = _compose_draft(deal, holding, graph)
        if body.expected_holding_updated_at is not None:
            _check_holding_lock(holding, body.expected_holding_updated_at)
        if body.expected_deal_updated_at is not None:
            _check_deal_lock(deal, body.expected_deal_updated_at)
    elif body.deal_id:
        deal = get_org_deal(db, ctx.organization_id, body.deal_id)
        if deal is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SSP deal not found")
        if body.expected_deal_updated_at is not None:
            _check_deal_lock(deal, body.expected_deal_updated_at)

    draft = _merge_draft(stored_draft, body.draft)
    if not draft:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="draft is required when no stored SSP holding/deal is loaded",
        )

    calc = calculate_ssp_draft(draft, holding_id=body.holding_client_id)
    persisted = False
    if body.persist_preview and calc.get("status") == "complete" and holding is not None and deal is not None:
        _persist_preview(
            db,
            organization_id=ctx.organization_id,
            deal_id=deal.id,
            holding_id=holding.id,
            reporting_year=getattr(deal, "reporting_year", None),
            result=calc,
        )
        # Keep holding non-reportable; stash last preview on snapshot only.
        snap = dict(holding.draft_snapshot or {})
        snap["lastPreviewCalculation"] = {
            "status": calc.get("status"),
            "financed_emissions": calc.get("financed_emissions"),
            "calculated_at": datetime.now(timezone.utc).isoformat(),
            "is_reportable": False,
            "include_in_portfolio": False,
        }
        holding.draft_snapshot = snap
        holding.is_reportable = False
        holding.include_in_portfolio = False
        holding.updated_at = _now()
        db.add(holding)
        _commit(db)
        persisted = True
    elif body.persist_preview and holding is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="persist_preview requires a stored financing_instance_id or holding_id",
        )

    return SspCalculateResponse(
        status=calc.get("status") or "error",
        code=calc.get("code"),
        message=calc.get("message"),
        methodology_version=calc.get("methodology_version") or SSP_METHODOLOGY_VERSION,
        pcaf_ref=calc.get("pcaf_ref"),
        formula_id=calc.get("formula_id"),
        formula_name=calc.get("formula_name"),
        emissions_path=calc.get("emissions_path"),
        structure_type=calc.get("structure_type"),
        emissions_unit=calc.get("emissions_unit") or "tCO2e",
        is_reportable=False,
        include_in_portfolio=False,
        financed_emissions=calc.get("financed_emissions"),
        scope_breakdown=calc.get("scope_breakdown"),
        data_quality_score=calc.get("data_quality_score"),
        iaf=calc.get("iaf"),
        taf=calc.get("taf"),
        deal_coa=calc.get("deal_coa"),
        pool_financed_emissions=calc.get("pool_financed_emissions"),
        collateral=calc.get("collateral") or [],
        loans=calc.get("loans") or [],
        pools=calc.get("pools") or [],
        tranches=calc.get("tranches") or [],
        holdings=calc.get("holdings") or [],
        notes=calc.get("notes") or [],
        warnings=calc.get("warnings") or [],
        provenance=calc.get("provenance") or {},
        error_details=calc.get("error_details"),
        persisted_preview=persisted,
        financing_instance_id=getattr(holding, "financing_instance_id", None) if holding else None,
        deal_id=str(deal.id) if deal else None,
        holding_db_id=str(holding.id) if holding else None,
        deal_updated_at=deal.updated_at.isoformat() if deal and deal.updated_at else None,
        holding_updated_at=holding.updated_at.isoformat() if holding and holding.updated_at else None,
    )
