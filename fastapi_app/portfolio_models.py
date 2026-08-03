"""
SQLAlchemy models for organizations + portfolio KEEP tables (public schema).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    parent_organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    is_active: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True, server_default="true")
    is_original: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True, server_default="false")


class Counterparty(Base):
    __tablename__ = "counterparties"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    sector: Mapped[str] = mapped_column(Text, nullable=False)
    geography: Mapped[str] = mapped_column(Text, nullable=False)
    counterparty_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="SME")
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
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


class Exposure(Base):
    __tablename__ = "exposures"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    counterparty_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("counterparties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    exposure_id: Mapped[str] = mapped_column(Text, nullable=False)
    amount_pkr: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=Decimal("0"))
    probability_of_default: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    loss_given_default: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    tenor_months: Mapped[int] = mapped_column(Integer, nullable=False)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
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


class CompanyEmission(Base):
    """
    company_emissions has no organization_id — org-scope via counterparty join
    (or user_id for bank-level rows where counterparty_id IS NULL).
    """

    __tablename__ = "company_emissions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    counterparty_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("counterparties.id", ondelete="CASCADE"),
        nullable=True,
    )
    is_bank_emissions: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True, server_default="false"
    )
    scope1_emissions: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 6), nullable=True, server_default="0"
    )
    scope2_emissions: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 6), nullable=True, server_default="0"
    )
    scope3_emissions: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 6), nullable=True, server_default="0"
    )
    total_emissions: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 6), nullable=True, server_default="0"
    )
    calculation_source: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, server_default="emission_calculator"
    )
    calculation_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[Optional[str]] = mapped_column(Text, nullable=True, server_default="active")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=True
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=True,
    )
