"""SQLAlchemy models for the approved emission-factor library."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class FactorLibraryEntry(Base):
    __tablename__ = "factor_library_entries"
    __table_args__ = {"schema": "ref"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    publication_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.uuid4)
    supersedes_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    factor_row_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    dataset_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    dataset_code: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    dataset_version: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    library_class: Mapped[str] = mapped_column(Text, nullable=False)
    country_code: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    region: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    geography: Mapped[str] = mapped_column(Text, nullable=False)
    sector_or_activity: Mapped[str] = mapped_column(Text, nullable=False)
    activity_key: Mapped[str] = mapped_column(Text, nullable=False)
    factor_value: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    numerator_unit: Mapped[str] = mapped_column(Text, nullable=False)
    denominator_unit: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str] = mapped_column(Text, nullable=False)
    applicable_year: Mapped[int] = mapped_column(Integer, nullable=False)
    publication_year: Mapped[int] = mapped_column(Integer, nullable=False)
    gas: Mapped[str] = mapped_column(Text, nullable=False, server_default="CO2e")
    scope_boundary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    emissions_boundary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_organization: Mapped[str] = mapped_column(Text, nullable=False)
    source_document: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    provenance: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    license_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    permitted_use: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    currency_code: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    submitted_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    submitted_rationale: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    review_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    effective_from: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    effective_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class FactorLibraryAudit(Base):
    __tablename__ = "factor_library_audit"
    __table_args__ = {"schema": "ref"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ref.factor_library_entries.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    actor_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
