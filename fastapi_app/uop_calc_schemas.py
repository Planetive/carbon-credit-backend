"""Request/response for POST /api/v1/uop/calculate. Preview by default; persist is non-reportable."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class UopCalculateRequest(BaseModel):
    financing_instance_id: Optional[str] = Field(
        default=None,
        description="Holding identity. Used to load and optionally persist a draft.",
    )
    structure_id: Optional[uuid.UUID] = None
    investment_id: Optional[uuid.UUID] = None
    counterparty_id: Optional[uuid.UUID] = None
    persist: bool = Field(
        default=False,
        description=(
            "If true, store validated results on UoP calculation rows. "
            "Never sets is_reportable or include_in_portfolio on draft tables."
        ),
    )
    persist_reportable: bool = Field(
        default=False,
        description=(
            "If true, upsert exactly one parent row in app.financed_emissions "
            "when reportable Save gates pass. Disabled unless the release flag "
            "is enabled. Underlying asset rows stay non-reportable."
        ),
    )
    expected_fingerprint: Optional[str] = Field(
        default=None,
        description="calculation_fingerprint from the last backend Calculate.",
    )
    expected_structure_updated_at: Optional[datetime] = None
    expected_investment_updated_at: Optional[datetime] = None
    draft: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Phase 5A UopDraft snapshot. Required for preview when no stored draft is loaded.",
    )
    issuer_level: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Optional issuer-level inputs for integrated unallocated amounts "
            "(Figure 5-1 Step 3a). Not the issuer corporate inventory standing "
            "in for issuer-reported UoP structure emissions."
        ),
    )


class UopCalculateResponse(BaseModel):
    status: str
    code: Optional[str] = None
    message: Optional[str] = None
    classification: Optional[str] = None
    emissions_path: Optional[str] = None
    formula_id: Optional[str] = None
    formula_name: Optional[str] = None
    methodology_version: str
    emissions_unit: str = "tCO2e"
    pcaf_ref: Optional[str] = None
    eligibility: Dict[str, Any] = Field(default_factory=dict)
    investor_attribution: Dict[str, Any] = Field(default_factory=dict)
    financed_emissions: Optional[float] = None
    allocated_financed_emissions: Optional[float] = None
    unallocated_financed_emissions: Optional[float] = None
    data_quality_score: Optional[float] = None
    assets: List[Dict[str, Any]] = Field(default_factory=list)
    allocation: Optional[Dict[str, Any]] = None
    scope_breakdown: Optional[Dict[str, Any]] = None
    issuer_report: Optional[Dict[str, Any]] = None
    notes: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    is_reportable: bool = False
    include_in_portfolio: bool = False
    double_count_guard: Optional[str] = None
    persisted: bool = False
    persisted_reportable: bool = False
    reportable_record_id: Optional[str] = None
    calculation_fingerprint: Optional[str] = None
    reporting_year: Optional[str] = None
    overlap: Optional[Dict[str, Any]] = None
    financing_instance_id: Optional[str] = None
    structure_id: Optional[str] = None
    investment_id: Optional[str] = None
    structure_updated_at: Optional[str] = None
    investment_updated_at: Optional[str] = None
