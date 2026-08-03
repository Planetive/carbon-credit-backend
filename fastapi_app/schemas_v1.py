"""Pydantic schemas for /api/v1 profile, orgs, and portfolio."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

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
