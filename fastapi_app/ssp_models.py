"""SQLAlchemy models for PCAF 2025 §5.8 SSP draft tables. Never app.financed_emissions."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

SSP_METHODOLOGY_VERSION = "PCAF-2025-PartA-5.8"
SSP_NULL_COUNTERPARTY = uuid.UUID("00000000-0000-0000-0000-000000000000")


class SspDeal(Base):
    __tablename__ = "ssp_deals"
    __table_args__ = {"schema": "app"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    counterparty_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    deal_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    deal_name: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    deal_identifier: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    issuer_name: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    originator_name: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    spv_name: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    structure_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    reporting_year: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    methodology_version: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=SSP_METHODOLOGY_VERSION
    )
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default="PKR")
    documentation_source: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    eligibility: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    emissions_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    has_tranches: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    has_pool_of_pools: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    collateral_remains_with_originator: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pools_linked_to_specific_tranches: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    shared_snapshot: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SspHolding(Base):
    __tablename__ = "ssp_holdings"
    __table_args__ = {"schema": "app"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    deal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app.ssp_deals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    counterparty_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    exposure_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    financing_instance_id: Mapped[str] = mapped_column(Text, nullable=False)
    instance_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    holding_name: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    tranche_client_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    bank_outstanding_investment: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default="PKR")
    formula_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    formula_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    is_reportable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    include_in_portfolio: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    draft_snapshot: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SspCollateral(Base):
    __tablename__ = "ssp_collateral"
    __table_args__ = {"schema": "app"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    deal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app.ssp_deals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    collateral_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    collateral_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    attribution_denominator: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)
    denominator_label: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    current_outstanding_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)
    original_outstanding_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)
    asset_value_at_origination: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)
    updated_asset_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)
    pcaf_method_option: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    emissions_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scope1_emissions: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)
    scope2_emissions: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)
    scope3_emissions: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)
    data_quality_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4), nullable=True)
    factor_library_entry_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    class_inputs: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    evidence: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SspLoan(Base):
    __tablename__ = "ssp_loans"
    __table_args__ = {"schema": "app"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    deal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app.ssp_deals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    loan_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    current_outstanding_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)
    original_outstanding_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    evidence: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SspLoanCollateral(Base):
    __tablename__ = "ssp_loan_collateral"
    __table_args__ = {"schema": "app"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    deal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app.ssp_deals.id", ondelete="CASCADE"), nullable=False
    )
    loan_row_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app.ssp_loans.id", ondelete="CASCADE"), nullable=False
    )
    collateral_row_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app.ssp_collateral.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SspPool(Base):
    __tablename__ = "ssp_pools"
    __table_args__ = {"schema": "app"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    deal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app.ssp_deals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pool_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    pool_current_outstanding_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)
    reported_emissions_total: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)
    reported_emissions_period: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    reported_scope_coverage: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    reported_verification: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reported_source: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    evidence: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SspPoolLoan(Base):
    __tablename__ = "ssp_pool_loans"
    __table_args__ = {"schema": "app"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    deal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app.ssp_deals.id", ondelete="CASCADE"), nullable=False
    )
    pool_row_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app.ssp_pools.id", ondelete="CASCADE"), nullable=False
    )
    loan_row_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app.ssp_loans.id", ondelete="CASCADE"), nullable=False
    )
    # Phase 6C.1 — LAF numerator (loan COA allocated into this pool). Nullable for legacy drafts.
    amount_in_pool: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SspPoolOfPools(Base):
    __tablename__ = "ssp_pool_of_pools"
    __table_args__ = {"schema": "app"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    deal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app.ssp_deals.id", ondelete="CASCADE"), nullable=False
    )
    pool_of_pools_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    current_outstanding_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)
    evidence: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SspPoolOfPoolsMember(Base):
    __tablename__ = "ssp_pool_of_pools_members"
    __table_args__ = {"schema": "app"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    deal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app.ssp_deals.id", ondelete="CASCADE"), nullable=False
    )
    pool_of_pools_row_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app.ssp_pool_of_pools.id", ondelete="CASCADE"), nullable=False
    )
    pool_row_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app.ssp_pools.id", ondelete="CASCADE"), nullable=False
    )
    # Reserved for deferred multi-pool PoP weighting (6C.0B). Not used in 6C.1 calc.
    amount_in_pop: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SspTranche(Base):
    __tablename__ = "ssp_tranches"
    __table_args__ = {"schema": "app"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    deal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app.ssp_deals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tranche_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    seniority_label: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    current_outstanding_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)
    is_green_tranche: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_virtual_overcollateralization: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    evidence: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SspTranchePool(Base):
    __tablename__ = "ssp_tranche_pools"
    __table_args__ = {"schema": "app"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    deal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app.ssp_deals.id", ondelete="CASCADE"), nullable=False
    )
    tranche_row_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app.ssp_tranches.id", ondelete="CASCADE"), nullable=False
    )
    pool_row_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app.ssp_pools.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SspCalculation(Base):
    __tablename__ = "ssp_calculations"
    __table_args__ = {"schema": "app"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    deal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app.ssp_deals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    holding_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app.ssp_holdings.id", ondelete="CASCADE"), nullable=True
    )
    collateral_row_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app.ssp_collateral.id", ondelete="CASCADE"), nullable=True
    )
    reporting_year: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    methodology_version: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=SSP_METHODOLOGY_VERSION
    )
    formula_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    inputs: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    results: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    financed_emissions: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6), nullable=True)
    attribution_factor: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)
    data_quality_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4), nullable=True)
    financed_scope1_tco2e: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6), nullable=True)
    financed_scope2_tco2e: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6), nullable=True)
    financed_scope3_tco2e: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6), nullable=True)
    include_in_portfolio: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_reportable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    provenance: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
