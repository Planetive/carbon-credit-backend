"""Pydantic schemas for /api/v1 profile, orgs, and portfolio."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


# ----- Profile -----

class ProfileUpdate(BaseModel):
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    phone: Optional[str] = Field(default=None, max_length=50)
    organization_name: Optional[str] = Field(default=None, max_length=200)
    user_type: Optional[str] = Field(default=None, max_length=64)
    current_organization_id: Optional[uuid.UUID] = None


class ProfileResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    display_name: str
    phone: Optional[str] = None
    organization_name: Optional[str] = None
    user_type: Optional[str] = None
    current_organization_id: Optional[uuid.UUID] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    role: Optional[str] = None

    model_config = {"from_attributes": True}


# ----- Organizations -----

class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    parent_organization_id: Optional[uuid.UUID] = None
    is_original: Optional[bool] = False


class OrganizationUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    is_active: Optional[bool] = None


class OrganizationOut(BaseModel):
    id: uuid.UUID
    name: str
    description: Optional[str] = None
    parent_organization_id: Optional[uuid.UUID] = None
    is_original: Optional[bool] = None
    is_active: Optional[bool] = None
    created_by: Optional[uuid.UUID] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    role: Optional[str] = None

    model_config = {"from_attributes": True}


# ----- Counterparties -----

COUNTERPARTY_TYPES = (
    "SME",
    "Retail",
    "Corporate",
    "Sovereign",
    "Bank",
    "Insurance",
    "Asset_Management",
    "Other",
)


class ExposureCreateNested(BaseModel):
    exposure_id: str = Field(min_length=1, max_length=64)
    amount_pkr: Decimal = Field(default=Decimal("0"))
    probability_of_default: Decimal
    loss_given_default: Decimal
    tenor_months: int = Field(ge=0)


class CounterpartyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    sector: str = Field(min_length=1, max_length=200)
    geography: str = Field(min_length=1, max_length=200)
    counterparty_type: str = Field(default="SME")
    exposure: Optional[ExposureCreateNested] = None


class CounterpartyUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    sector: Optional[str] = Field(default=None, min_length=1, max_length=200)
    geography: Optional[str] = Field(default=None, min_length=1, max_length=200)
    counterparty_type: Optional[str] = None


class CounterpartyOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    sector: str
    geography: str
    counterparty_type: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ----- Exposures -----

class ExposureCreate(BaseModel):
    counterparty_id: uuid.UUID
    exposure_id: str = Field(min_length=1, max_length=64)
    amount_pkr: Decimal = Field(default=Decimal("0"))
    probability_of_default: Decimal
    loss_given_default: Decimal
    tenor_months: int = Field(ge=0)


class ExposureUpdate(BaseModel):
    exposure_id: Optional[str] = Field(default=None, min_length=1, max_length=64)
    amount_pkr: Optional[Decimal] = None
    probability_of_default: Optional[Decimal] = None
    loss_given_default: Optional[Decimal] = None
    tenor_months: Optional[int] = Field(default=None, ge=0)


class ExposureOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    organization_id: uuid.UUID
    counterparty_id: uuid.UUID
    exposure_id: str
    amount_pkr: Decimal
    probability_of_default: Decimal
    loss_given_default: Decimal
    tenor_months: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ----- Company emissions -----

class CompanyEmissionUpdate(BaseModel):
    scope1_emissions: Optional[Decimal] = None
    scope2_emissions: Optional[Decimal] = None
    scope3_emissions: Optional[Decimal] = None
    calculation_source: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class CompanyEmissionOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    counterparty_id: Optional[uuid.UUID] = None
    is_bank_emissions: Optional[bool] = None
    scope1_emissions: Optional[Decimal] = None
    scope2_emissions: Optional[Decimal] = None
    scope3_emissions: Optional[Decimal] = None
    total_emissions: Optional[Decimal] = None
    calculation_source: Optional[str] = None
    calculation_date: Optional[datetime] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class MessageOut(BaseModel):
    status: str = "ok"
    message: str = ""


# ----- GHG assessments / activities -----

FRAMEWORKS = ("uk", "epa", "ipcc", "mixed")
CALC_KINDS = ("finance", "facilitated")


class EmissionAssessmentCreate(BaseModel):
    framework: str = Field(default="mixed")
    reporting_period: Optional[str] = None
    status: str = Field(default="draft")
    totals: Optional[Dict[str, Any]] = None
    legacy_note: Optional[str] = None


class EmissionAssessmentUpdate(BaseModel):
    framework: Optional[str] = None
    reporting_period: Optional[str] = None
    status: Optional[str] = None
    totals: Optional[Dict[str, Any]] = None
    legacy_note: Optional[str] = None


class EmissionAssessmentOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    user_id: uuid.UUID
    framework: str
    reporting_period: Optional[str] = None
    status: str
    totals: Dict[str, Any] = Field(default_factory=dict)
    legacy_note: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class EmissionActivityCreate(BaseModel):
    assessment_id: uuid.UUID
    scope: int = Field(ge=1, le=3)
    category: str = Field(min_length=1, max_length=200)
    method: str = Field(default="activity_data")
    counterparty_id: Optional[uuid.UUID] = None
    quantity: Optional[Decimal] = None
    unit: Optional[str] = None
    factor_dataset_id: Optional[uuid.UUID] = None
    factor_row_id: Optional[uuid.UUID] = None
    emissions_tco2e: Optional[Decimal] = None
    raw: Optional[Dict[str, Any]] = None


class EmissionActivityUpdate(BaseModel):
    scope: Optional[int] = Field(default=None, ge=1, le=3)
    category: Optional[str] = Field(default=None, min_length=1, max_length=200)
    method: Optional[str] = None
    counterparty_id: Optional[uuid.UUID] = None
    quantity: Optional[Decimal] = None
    unit: Optional[str] = None
    factor_dataset_id: Optional[uuid.UUID] = None
    factor_row_id: Optional[uuid.UUID] = None
    emissions_tco2e: Optional[Decimal] = None
    raw: Optional[Dict[str, Any]] = None


class EmissionActivityOut(BaseModel):
    id: uuid.UUID
    assessment_id: uuid.UUID
    organization_id: uuid.UUID
    user_id: uuid.UUID
    scope: int
    category: str
    method: str
    counterparty_id: Optional[uuid.UUID] = None
    quantity: Optional[Decimal] = None
    unit: Optional[str] = None
    factor_dataset_id: Optional[uuid.UUID] = None
    factor_row_id: Optional[uuid.UUID] = None
    emissions_tco2e: Optional[Decimal] = None
    raw: Dict[str, Any] = Field(default_factory=dict)
    legacy_source: str
    legacy_id: Optional[uuid.UUID] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ----- Financed emissions -----

class FinancedEmissionCreate(BaseModel):
    calc_kind: str = Field(default="finance")
    company_type: Optional[str] = None
    formula_id: Optional[str] = None
    formula_name: Optional[str] = None
    inputs: Optional[Dict[str, Any]] = None
    results: Optional[Dict[str, Any]] = None
    financed_emissions: Optional[Decimal] = None
    attribution_factor: Optional[Decimal] = None
    data_quality_score: Optional[Decimal] = None
    counterparty_id: Optional[uuid.UUID] = None
    exposure_id: Optional[uuid.UUID] = None
    questionnaire_id: Optional[uuid.UUID] = None
    status: str = Field(default="completed")


class FinancedEmissionUpdate(BaseModel):
    calc_kind: Optional[str] = None
    company_type: Optional[str] = None
    formula_id: Optional[str] = None
    formula_name: Optional[str] = None
    inputs: Optional[Dict[str, Any]] = None
    results: Optional[Dict[str, Any]] = None
    financed_emissions: Optional[Decimal] = None
    attribution_factor: Optional[Decimal] = None
    data_quality_score: Optional[Decimal] = None
    counterparty_id: Optional[uuid.UUID] = None
    exposure_id: Optional[uuid.UUID] = None
    questionnaire_id: Optional[uuid.UUID] = None
    status: Optional[str] = None


class FinancedEmissionOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    user_id: uuid.UUID
    counterparty_id: Optional[uuid.UUID] = None
    exposure_id: Optional[uuid.UUID] = None
    questionnaire_id: Optional[uuid.UUID] = None
    calc_kind: str
    company_type: Optional[str] = None
    formula_id: Optional[str] = None
    formula_name: Optional[str] = None
    inputs: Dict[str, Any] = Field(default_factory=dict)
    results: Dict[str, Any] = Field(default_factory=dict)
    financed_emissions: Optional[Decimal] = None
    attribution_factor: Optional[Decimal] = None
    data_quality_score: Optional[Decimal] = None
    status: str
    legacy_source: Optional[str] = None
    legacy_id: Optional[uuid.UUID] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class FinancedCalculateRequest(BaseModel):
    """Compute via existing calculation engine and optionally persist."""

    calc_kind: str = Field(default="finance")
    formula_id: str
    company_type: str = Field(description="listed | unlisted / private")
    inputs: Dict[str, Any]
    counterparty_id: Optional[uuid.UUID] = None
    exposure_id: Optional[uuid.UUID] = None
    persist: bool = True


class FinancedCalculateResponse(BaseModel):
    success: bool = True
    result: Dict[str, Any]
    record: Optional[FinancedEmissionOut] = None
