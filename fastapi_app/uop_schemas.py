"""Pydantic contracts for /api/v1/uop/drafts. Matches Phase 5A frontend UopDraft."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class UopDraftUpsert(BaseModel):
    financing_instance_id: str = Field(
        min_length=1,
        description=(
            "Stable holding identity. Same contract as financed_emissions "
            "inputs.financing_instance_id. Not formula_id."
        ),
    )
    instance_key: Optional[str] = Field(
        default=None, description="Wizard key, e.g. use-of-proceeds#1"
    )
    counterparty_id: Optional[uuid.UUID] = None
    exposure_id: Optional[uuid.UUID] = Field(
        default=None,
        description="FK to public.exposures.id only — not financing_instance_id.",
    )
    structure_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Attach this holding to an existing UoP structure in the same org.",
    )
    formula_id: Optional[str] = Field(
        default=None,
        description="Methodology annotation only. Never used as a unique exposure key.",
    )
    formula_name: Optional[str] = None
    update_shared: bool = Field(
        default=False,
        description=(
            "If true, apply shared fund/asset fields to the structure. "
            "Required when siblings exist and shared data would change."
        ),
    )
    expected_structure_updated_at: Optional[datetime] = Field(
        default=None,
        description="Optimistic lock for shared structure rows. Required with update_shared when siblings exist.",
    )
    expected_investment_updated_at: Optional[datetime] = Field(
        default=None,
        description="Optimistic lock for this holding. 409 if another save landed first.",
    )
    draft: Dict[str, Any] = Field(
        default_factory=dict,
        description="Phase 5A UopDraft snapshot (camelCase from the SPA).",
    )


class UopDraftPatch(BaseModel):
    instance_key: Optional[str] = None
    counterparty_id: Optional[uuid.UUID] = None
    exposure_id: Optional[uuid.UUID] = None
    formula_id: Optional[str] = None
    formula_name: Optional[str] = None
    update_shared: bool = False
    expected_structure_updated_at: Optional[datetime] = None
    expected_investment_updated_at: Optional[datetime] = None
    draft: Optional[Dict[str, Any]] = None


class UopStructureOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    user_id: uuid.UUID
    counterparty_id: Optional[uuid.UUID] = None
    name: str
    issuer_name: str
    structure_kind: str
    classification: Optional[str] = None
    eligibility: Dict[str, Any] = Field(default_factory=dict)
    total_structure_debt: Optional[Decimal] = None
    total_structure_equity: Optional[Decimal] = None
    reporting_year: Optional[str] = None
    methodology_version: str
    currency: str
    evidence_source: str
    evidence_notes: str
    allocation_status: Optional[str] = None
    allocated_proceeds: Optional[Decimal] = None
    unallocated_proceeds: Optional[Decimal] = None
    expected_allocation_evidence: str
    unallocated_uses_asset_level_estimate: Optional[str] = None
    emissions_path: Optional[str] = None
    issuer_level_reason: Optional[str] = None
    issuer_reported_financed_emissions: Optional[Decimal] = None
    issuer_report_year: Optional[str] = None
    issuer_report_verification: Optional[str] = None
    issuer_report_source: str
    status: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class UopInvestmentOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    user_id: uuid.UUID
    structure_id: uuid.UUID
    counterparty_id: Optional[uuid.UUID] = None
    exposure_id: Optional[uuid.UUID] = None
    financing_instance_id: str
    instance_key: Optional[str] = None
    investment_type: Optional[str] = None
    outstanding_amount: Optional[Decimal] = None
    formula_id: Optional[str] = None
    formula_name: Optional[str] = None
    status: str
    is_reportable: bool
    include_in_portfolio: bool
    draft_snapshot: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class UopUnderlyingAssetOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    structure_id: uuid.UUID
    underlying_asset_id: str
    name: str
    asset_class: str
    sort_order: int
    allocated_outstanding: Optional[Decimal] = None
    total_asset_value: Optional[Decimal] = None
    has_reported_emissions: Optional[str] = None
    verification_status: Optional[str] = None
    verifier_name: str
    scope1_emissions: Optional[Decimal] = None
    scope2_emissions: Optional[Decimal] = None
    scope3_emissions: Optional[Decimal] = None
    data_source: str
    evidence_notes: str
    estimation: Dict[str, Any] = Field(default_factory=dict)
    inputs: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class UopAssetCalculationOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    structure_id: uuid.UUID
    asset_id: uuid.UUID
    investment_id: Optional[uuid.UUID] = None
    reporting_year: Optional[str] = None
    methodology_version: str
    formula_id: Optional[str] = None
    status: str
    inputs: Dict[str, Any] = Field(default_factory=dict)
    results: Dict[str, Any] = Field(default_factory=dict)
    financed_emissions: Optional[Decimal] = None
    attribution_factor: Optional[Decimal] = None
    data_quality_score: Optional[Decimal] = None
    financed_scope1_tco2e: Optional[Decimal] = None
    financed_scope2_tco2e: Optional[Decimal] = None
    financed_scope3_tco2e: Optional[Decimal] = None
    include_in_portfolio: bool
    is_reportable: bool
    provenance: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class UopDraftRecord(BaseModel):
    investment: UopInvestmentOut
    structure: UopStructureOut
    assets: List[UopUnderlyingAssetOut] = Field(default_factory=list)
    calculations: List[UopAssetCalculationOut] = Field(default_factory=list)
    draft: Dict[str, Any] = Field(default_factory=dict)
    created: bool = False
    sibling_count: int = 0
    shared_write_applied: bool = False
    holding_count: int = 1
