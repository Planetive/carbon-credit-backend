"""
SQLAlchemy models for ref.factor_datasets + ref.factor_rows.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class FactorDataset(Base):
    __tablename__ = "factor_datasets"
    __table_args__ = {"schema": "ref"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    publisher: Mapped[str] = mapped_column(Text, nullable=False, server_default="legacy")
    title: Mapped[str] = mapped_column(Text, nullable=False)
    version_label: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="imported"
    )
    effective_from: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    effective_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    source_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FactorRow(Base):
    __tablename__ = "factor_rows"
    __table_args__ = {"schema": "ref"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ref.factor_datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attributes: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    unit: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    kg_co2e: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)
    kg_co2: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)
    kg_ch4: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)
    kg_n2o: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)
    meta: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
