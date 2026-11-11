"""Pydantic contracts for /api/v1/ssp/drafts. Matches Phase 6A/6B frontend SspDraft."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SspDraftUpsert(BaseModel):
    financing_instance_id: str = Field(min_length=1)
    instance_key: Optional[str] = None
    counterparty_id: Optional[uuid.UUID] = None
    exposure_id: Optional[uuid.UUID] = None
    deal_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Attach this holding to an existing SSP deal in the same org.",
    )
    formula_id: Optional[str] = None
    formula_name: Optional[str] = None
    update_shared: bool = Field(
        default=False,
        description="If true, apply shared deal/hierarchy fields. Required when siblings exist and shared data would change.",
    )
    expected_deal_updated_at: Optional[datetime] = None
    expected_holding_updated_at: Optional[datetime] = None
    draft: Dict[str, Any] = Field(default_factory=dict)


class SspDraftPatch(BaseModel):
    instance_key: Optional[str] = None
    counterparty_id: Optional[uuid.UUID] = None
    exposure_id: Optional[uuid.UUID] = None
    formula_id: Optional[str] = None
    formula_name: Optional[str] = None
    update_shared: bool = False
    expected_deal_updated_at: Optional[datetime] = None
    expected_holding_updated_at: Optional[datetime] = None
    draft: Optional[Dict[str, Any]] = None


class SspDealOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    user_id: uuid.UUID
    counterparty_id: Optional[uuid.UUID] = None
    deal_key: Optional[str] = None
    deal_name: str
    deal_identifier: str
    issuer_name: str
    originator_name: str
    spv_name: str
    structure_type: str
    reporting_year: Optional[str] = None
    methodology_version: str
    currency: str
    documentation_source: str
    eligibility: Dict[str, Any] = Field(default_factory=dict)
    emissions_path: Optional[str] = None
    has_tranches: Optional[str] = None
    has_pool_of_pools: Optional[str] = None
    collateral_remains_with_originator: Optional[str] = None
    pools_linked_to_specific_tranches: Optional[str] = None
    shared_snapshot: Dict[str, Any] = Field(default_factory=dict)
    status: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class SspHoldingOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    user_id: uuid.UUID
    deal_id: uuid.UUID
    counterparty_id: Optional[uuid.UUID] = None
    exposure_id: Optional[uuid.UUID] = None
    financing_instance_id: str
    instance_key: Optional[str] = None
    holding_name: str
    tranche_client_id: Optional[str] = None
    bank_outstanding_investment: Optional[Decimal] = None
    currency: str
    formula_id: Optional[str] = None
    formula_name: Optional[str] = None
    status: str
    is_reportable: bool
    include_in_portfolio: bool
    draft_snapshot: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class SspCollateralOut(BaseModel):
    id: uuid.UUID
    deal_id: uuid.UUID
    collateral_id: str
    name: str
    collateral_type: str
    attribution_denominator: Optional[Decimal] = None
    class_inputs: Dict[str, Any] = Field(default_factory=dict)
    sort_order: int = 0

    model_config = {"from_attributes": True}


class SspLoanOut(BaseModel):
    id: uuid.UUID
    deal_id: uuid.UUID
    loan_id: str
    name: str
    current_outstanding_amount: Optional[Decimal] = None
    sort_order: int = 0

    model_config = {"from_attributes": True}


class SspPoolOut(BaseModel):
    id: uuid.UUID
    deal_id: uuid.UUID
    pool_id: str
    name: str
    pool_current_outstanding_amount: Optional[Decimal] = None
    sort_order: int = 0

    model_config = {"from_attributes": True}


class SspTrancheOut(BaseModel):
    id: uuid.UUID
    deal_id: uuid.UUID
    tranche_id: str
    name: str
    current_outstanding_amount: Optional[Decimal] = None
    sort_order: int = 0

    model_config = {"from_attributes": True}


class SspCalculationOut(BaseModel):
    id: uuid.UUID
    deal_id: uuid.UUID
    holding_id: Optional[uuid.UUID] = None
    reporting_year: Optional[str] = None
    methodology_version: str
    status: str
    is_reportable: bool
    include_in_portfolio: bool
    financed_emissions: Optional[Decimal] = None

    model_config = {"from_attributes": True}


class SspDraftRecord(BaseModel):
    holding: SspHoldingOut
    deal: SspDealOut
    collateral: List[SspCollateralOut] = Field(default_factory=list)
    loans: List[SspLoanOut] = Field(default_factory=list)
    pools: List[SspPoolOut] = Field(default_factory=list)
    tranches: List[SspTrancheOut] = Field(default_factory=list)
    calculations: List[SspCalculationOut] = Field(default_factory=list)
    draft: Dict[str, Any] = Field(default_factory=dict)
    created: bool = False
    sibling_count: int = 0
    shared_write_applied: bool = False
    holding_count: int = 1
