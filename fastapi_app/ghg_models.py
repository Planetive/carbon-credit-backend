"""
SQLAlchemy models for app.emission_* and app.financed_emissions (KEEP unified tables).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional

from sqlalchemy import DateTime, ForeignKey, Numeric, SmallInteger, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class EmissionAssessment(Base):
    __tablename__ = "emission_assessments"
    __table_args__ = {"schema": "app"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    framework: Mapped[str] = mapped_column(Text, nullable=False, server_default="mixed")
    reporting_period: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="imported")
    totals: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    legacy_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class EmissionActivity(Base):
    __tablename__ = "emission_activities"
    __table_args__ = {"schema": "app"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.emission_assessments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    scope: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False, server_default="activity_data")
    counterparty_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    factor_dataset_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    factor_row_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    emissions_tco2e: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)
    raw: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    legacy_source: Mapped[str] = mapped_column(Text, nullable=False, server_default="api")
    legacy_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class FinancedEmission(Base):
    __tablename__ = "financed_emissions"
    __table_args__ = {"schema": "app"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    counterparty_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    exposure_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    questionnaire_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    calc_kind: Mapped[str] = mapped_column(Text, nullable=False, server_default="finance")
    company_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    formula_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    formula_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    inputs: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    results: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    financed_emissions: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6), nullable=True)
    attribution_factor: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)
    data_quality_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="completed")
    legacy_source: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    legacy_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
