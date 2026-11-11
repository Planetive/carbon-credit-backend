"""Request/response for POST /api/v1/ssp/calculate — preview only."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SspCalculateRequest(BaseModel):
    financing_instance_id: Optional[str] = Field(
        default=None,
        description="Load org-scoped draft holding by financing_instance_id.",
    )
    deal_id: Optional[uuid.UUID] = None
    holding_id: Optional[uuid.UUID] = None
    counterparty_id: Optional[uuid.UUID] = None
    persist_preview: bool = Field(
        default=False,
        description=(
            "If true, store preview provenance on ssp_calculations. "
            "Never sets is_reportable or include_in_portfolio."
        ),
    )
    expected_deal_updated_at: Optional[datetime] = None
    expected_holding_updated_at: Optional[datetime] = None
    draft: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional draft overlay / preview-only draft when no stored row is loaded.",
    )
    holding_client_id: Optional[str] = Field(
        default=None,
        description="Optional holdings[].holdingId to select when draft has multiple holdings.",
    )


class SspCalculateResponse(BaseModel):
    status: str
    code: Optional[str] = None
    message: Optional[str] = None
    methodology_version: str
    pcaf_ref: Optional[str] = None
    formula_id: Optional[str] = None
    formula_name: Optional[str] = None
    emissions_path: Optional[str] = None
    structure_type: Optional[str] = None
    emissions_unit: str = "tCO2e"
    is_reportable: bool = False
    include_in_portfolio: bool = False
    financed_emissions: Optional[float] = None
    scope_breakdown: Optional[Dict[str, Any]] = None
    data_quality_score: Optional[float] = None
    iaf: Optional[float] = None
    taf: Optional[float] = None
    deal_coa: Optional[float] = None
    pool_financed_emissions: Optional[float] = None
    collateral: List[Dict[str, Any]] = Field(default_factory=list)
    loans: List[Dict[str, Any]] = Field(default_factory=list)
    pools: List[Dict[str, Any]] = Field(default_factory=list)
    tranches: List[Dict[str, Any]] = Field(default_factory=list)
    holdings: List[Dict[str, Any]] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    provenance: Dict[str, Any] = Field(default_factory=dict)
    error_details: Optional[Dict[str, Any]] = None
    persisted_preview: bool = False
    financing_instance_id: Optional[str] = None
    deal_id: Optional[str] = None
    holding_db_id: Optional[str] = None
    deal_updated_at: Optional[str] = None
    holding_updated_at: Optional[str] = None
