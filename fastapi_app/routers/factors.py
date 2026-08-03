"""Read-only factor dataset / row endpoints for UI factor pickers."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import String, cast, func, or_
from sqlalchemy.orm import Session

from ..auth_org import OrgContext, get_current_org_context
from ..db import get_db
from ..factor_models import FactorDataset, FactorRow
from .catalog_utils import table_exists

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/factors", tags=["factors"])


def _dataset_out(ds: FactorDataset) -> Dict[str, Any]:
    return {
        "id": str(ds.id),
        "code": ds.code,
        "publisher": ds.publisher,
        "title": ds.title,
        "version_label": ds.version_label,
        "effective_from": ds.effective_from.isoformat() if ds.effective_from else None,
        "effective_to": ds.effective_to.isoformat() if ds.effective_to else None,
        "is_active": ds.is_active,
        "source_notes": ds.source_notes,
        "created_at": ds.created_at.isoformat() if ds.created_at else None,
    }


def _row_out(row: FactorRow, dataset: Optional[FactorDataset] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "id": str(row.id),
        "dataset_id": str(row.dataset_id),
        "category": row.category,
        "label": row.label,
        "attributes": row.attributes or {},
        "unit": row.unit,
        "kg_co2e": float(row.kg_co2e) if row.kg_co2e is not None else None,
        "kg_co2": float(row.kg_co2) if row.kg_co2 is not None else None,
        "kg_ch4": float(row.kg_ch4) if row.kg_ch4 is not None else None,
        "kg_n2o": float(row.kg_n2o) if row.kg_n2o is not None else None,
        "meta": row.meta,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
    if dataset is not None:
        payload["dataset"] = {
            "id": str(dataset.id),
            "code": dataset.code,
            "publisher": dataset.publisher,
            "title": dataset.title,
            "version_label": dataset.version_label,
        }
    return payload


def _require_factor_tables(db: Session) -> None:
    if not table_exists(db, "ref", "factor_datasets") or not table_exists(
        db, "ref", "factor_rows"
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ref.factor_datasets / ref.factor_rows not available on this database",
        )


@router.get("/datasets", response_model=List[Dict[str, Any]])
def list_factor_datasets(
    methodology: Optional[str] = Query(
        default=None, description="Filter uk|epa|ipcc|... matched against code/title/publisher"
    ),
    name: Optional[str] = Query(default=None, description="Search title/code/source_notes"),
    source: Optional[str] = Query(default=None, description="Alias for publisher/source search"),
    active_only: bool = Query(default=True),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    ctx: OrgContext = Depends(get_current_org_context),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    _ = ctx
    _require_factor_tables(db)

    q = db.query(FactorDataset)
    if active_only:
        q = q.filter(FactorDataset.is_active.is_(True))
    if methodology:
        like = f"%{methodology.strip()}%"
        q = q.filter(
            or_(
                FactorDataset.code.ilike(like),
                FactorDataset.title.ilike(like),
                FactorDataset.publisher.ilike(like),
            )
        )
    search = name or source
    if search:
        like = f"%{search.strip()}%"
        q = q.filter(
            or_(
                FactorDataset.title.ilike(like),
                FactorDataset.code.ilike(like),
                FactorDataset.publisher.ilike(like),
                FactorDataset.source_notes.ilike(like),
            )
        )
    rows = q.order_by(FactorDataset.title.asc()).offset(offset).limit(limit).all()
    return [_dataset_out(r) for r in rows]


@router.get("/datasets/{dataset_id}", response_model=Dict[str, Any])
def get_factor_dataset(
    dataset_id: uuid.UUID,
    ctx: OrgContext = Depends(get_current_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _ = ctx
    _require_factor_tables(db)
    ds = db.query(FactorDataset).filter(FactorDataset.id == dataset_id).first()
    if not ds:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Factor dataset not found"
        )
    row_count = (
        db.query(func.count(FactorRow.id))
        .filter(FactorRow.dataset_id == dataset_id)
        .scalar()
    )
    out = _dataset_out(ds)
    out["row_count"] = int(row_count or 0)
    return out


@router.get("/rows", response_model=List[Dict[str, Any]])
def list_factor_rows(
    dataset_id: Optional[uuid.UUID] = Query(
        default=None, description="Strongly preferred; filters rows to one dataset"
    ),
    q: Optional[str] = Query(default=None, description="Search label/category/attributes"),
    category: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    ctx: OrgContext = Depends(get_current_org_context),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    _ = ctx
    _require_factor_tables(db)

    if dataset_id is None and not q and not category:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide dataset_id (preferred) and/or q/category to list factor rows",
        )

    query = db.query(FactorRow, FactorDataset).join(
        FactorDataset, FactorDataset.id == FactorRow.dataset_id
    )
    if dataset_id is not None:
        query = query.filter(FactorRow.dataset_id == dataset_id)
    if category:
        query = query.filter(FactorRow.category.ilike(f"%{category.strip()}%"))
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(
                FactorRow.label.ilike(like),
                FactorRow.category.ilike(like),
                cast(FactorRow.attributes, String).ilike(like),
            )
        )

    rows = (
        query.order_by(FactorRow.category.asc(), FactorRow.label.asc().nullslast())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [_row_out(row, ds) for row, ds in rows]


@router.get("/rows/{row_id}", response_model=Dict[str, Any])
def get_factor_row(
    row_id: uuid.UUID,
    ctx: OrgContext = Depends(get_current_org_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _ = ctx
    _require_factor_tables(db)
    pair = (
        db.query(FactorRow, FactorDataset)
        .join(FactorDataset, FactorDataset.id == FactorRow.dataset_id)
        .filter(FactorRow.id == row_id)
        .first()
    )
    if not pair:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Factor row not found"
        )
    row, ds = pair
    return _row_out(row, ds)
