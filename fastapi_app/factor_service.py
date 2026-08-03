"""
Factor Service — resolve ref.factor_datasets by code and return legacy sheet-shaped dicts.

Mirrors SPA src/api/factorDualRead.ts (factorRowToLegacyRecord + paging).
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy.orm import Session

from .factor_models import FactorDataset, FactorRow

PAGE = 500


def factor_row_to_legacy_record(row: FactorRow) -> Dict[str, Any]:
    """Flatten API factor row → legacy sheet-shaped dict (ETL stores full row in attributes)."""
    attrs: Dict[str, Any]
    if row.attributes and isinstance(row.attributes, dict):
        attrs = dict(row.attributes)
    else:
        attrs = {}

    if row.unit is not None and attrs.get("unit") is None and attrs.get("Unit") is None:
        attrs["unit"] = row.unit
    if (
        row.category is not None
        and attrs.get("category") is None
        and attrs.get("Category") is None
    ):
        attrs["category"] = row.category
    if row.label is not None and attrs.get("label") is None:
        attrs["label"] = row.label
    if (
        row.kg_co2e is not None
        and attrs.get("kg_co2e") is None
        and attrs.get("kg CO2e") is None
    ):
        attrs["kg_co2e"] = float(row.kg_co2e)
    if row.kg_co2 is not None and attrs.get("kg_co2") is None:
        attrs["kg_co2"] = float(row.kg_co2)
    if row.kg_ch4 is not None and attrs.get("kg_ch4") is None:
        attrs["kg_ch4"] = float(row.kg_ch4)
    if row.kg_n2o is not None and attrs.get("kg_n2o") is None:
        attrs["kg_n2o"] = float(row.kg_n2o)
    return attrs


def resolve_dataset(
    db: Session,
    codes: Sequence[str],
    name_hints: Optional[Sequence[str]] = None,
) -> Optional[FactorDataset]:
    datasets = (
        db.query(FactorDataset)
        .filter(FactorDataset.is_active.is_(True))
        .limit(500)
        .all()
    )
    by_code = {str(d.code or "").lower(): d for d in datasets}

    for code in codes:
        hit = by_code.get(str(code).lower())
        if hit:
            return hit

    for hint in name_hints or []:
        h = hint.lower()
        for d in datasets:
            if h in str(d.code or "").lower() or h in str(d.title or "").lower():
                return d
    return None


def fetch_all_rows_for_dataset(db: Session, dataset_id: uuid.UUID) -> List[FactorRow]:
    all_rows: List[FactorRow] = []
    offset = 0
    while True:
        chunk = (
            db.query(FactorRow)
            .filter(FactorRow.dataset_id == dataset_id)
            .order_by(FactorRow.created_at.asc())
            .offset(offset)
            .limit(PAGE)
            .all()
        )
        if not chunk:
            break
        all_rows.extend(chunk)
        if len(chunk) < PAGE:
            break
        offset += PAGE
    return all_rows


def load_legacy_sheet(
    db: Session,
    codes: Sequence[str],
    name_hints: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    """Resolve dataset by code/hints and return all rows as legacy dicts."""
    ds = resolve_dataset(db, codes, name_hints)
    if ds is None:
        return []
    rows = fetch_all_rows_for_dataset(db, ds.id)
    return [factor_row_to_legacy_record(r) for r in rows]


def load_legacy_sheets(
    db: Session,
    sheets: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Concatenate several datasets (e.g. Fuel EPA 1/2/3)."""
    all_legacy: List[Dict[str, Any]] = []
    any_hit = False
    for sheet in sheets:
        codes = sheet.get("datasetCodes") or sheet.get("dataset_codes") or []
        hints = sheet.get("nameHints") or sheet.get("name_hints") or []
        ds = resolve_dataset(db, codes, hints)
        if ds is None:
            continue
        any_hit = True
        rows = fetch_all_rows_for_dataset(db, ds.id)
        all_legacy.extend(factor_row_to_legacy_record(r) for r in rows)
    return all_legacy if any_hit else []


def get_row_by_id(db: Session, row_id: uuid.UUID) -> Optional[FactorRow]:
    return db.query(FactorRow).filter(FactorRow.id == row_id).first()
