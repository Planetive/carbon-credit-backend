"""
SQLAlchemy models for PCAF 2025 §5.7 Use of Proceeds draft tables.

These rows are not app.financed_emissions. Underlying calculation records are
CHECK-forced not reportable so dashboards and Category 15 cannot double-count
look-through components. financing_instance_id is the holding identity;
formula_id is methodology only.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

UOP_METHODOLOGY_VERSION = "PCAF-2025-PartA-5.7"
UOP_NULL_COUNTERPARTY = uuid.UUID("00000000-0000-0000-0000-000000000000")


class UopStructure(Base):
    __tablename__ = "uop_structures"
    __table_args__ = {"schema": "app"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    counterparty_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    issuer_name: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    structure_kind: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    classification: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    eligibility: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    total_structure_debt: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 8), nullable=True
    )
    total_structure_equity: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 8), nullable=True
    )
    reporting_year: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    methodology_version: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=UOP_METHODOLOGY_VERSION
    )
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default="PKR")
    evidence_source: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    evidence_notes: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    allocation_status: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    allocated_proceeds: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 8), nullable=True
    )
    unallocated_proceeds: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 8), nullable=True
    )
    expected_allocation_evidence: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=""
    )
    unallocated_uses_asset_level_estimate: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    emissions_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    issuer_level_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    issuer_reported_financed_emissions: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 8), nullable=True
    )
    issuer_report_year: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    issuer_report_verification: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    issuer_report_source: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=""
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class UopInvestment(Base):
    __tablename__ = "uop_investments"
    __table_args__ = {"schema": "app"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    structure_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.uop_structures.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    counterparty_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    exposure_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    financing_instance_id: Mapped[str] = mapped_column(Text, nullable=False)
    instance_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    investment_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    outstanding_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 8), nullable=True
    )
    formula_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    formula_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    is_reportable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    include_in_portfolio: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    draft_snapshot: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class UopUnderlyingAsset(Base):
    __tablename__ = "uop_underlying_assets"
    __table_args__ = {"schema": "app"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    structure_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.uop_structures.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    underlying_asset_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    asset_class: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    allocated_outstanding: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 8), nullable=True
    )
    total_asset_value: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 8), nullable=True
    )
    has_reported_emissions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    verification_status: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    verifier_name: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    scope1_emissions: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 8), nullable=True
    )
    scope2_emissions: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 8), nullable=True
    )
    scope3_emissions: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 8), nullable=True
    )
    data_source: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    evidence_notes: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    estimation: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    inputs: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class UopAssetCalculation(Base):
    __tablename__ = "uop_asset_calculations"
    __table_args__ = {"schema": "app"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    structure_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.uop_structures.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.uop_underlying_assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    investment_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.uop_investments.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    reporting_year: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    methodology_version: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=UOP_METHODOLOGY_VERSION
    )
    formula_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    inputs: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    results: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    financed_emissions: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 6), nullable=True
    )
    attribution_factor: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 8), nullable=True
    )
    data_quality_score: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 4), nullable=True
    )
    financed_scope1_tco2e: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 6), nullable=True
    )
    financed_scope2_tco2e: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 6), nullable=True
    )
    financed_scope3_tco2e: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 6), nullable=True
    )
    include_in_portfolio: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    is_reportable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    provenance: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
