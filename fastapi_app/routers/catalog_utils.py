"""Shared helpers for read-only catalog / ref queries."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def table_exists(db: Session, schema: str, table: str) -> bool:
    return bool(
        db.execute(
            text(
                "SELECT EXISTS ("
                "  SELECT 1 FROM information_schema.tables "
                "  WHERE table_schema = :schema AND table_name = :table"
                ")"
            ),
            {"schema": schema, "table": table},
        ).scalar()
    )


def fetch_table_rows(
    db: Session,
    schema: str,
    table: str,
    limit: int,
    offset: int,
    where_sql: str = "",
    params: Optional[Dict[str, Any]] = None,
    order_by: str = "1",
) -> List[Dict[str, Any]]:
    """
    SELECT * from schema.table with optional WHERE.
    Returns [] and logs if the table is missing or the query fails.
    """
    if not table_exists(db, schema, table):
        logger.warning("Catalog/ref table missing: %s.%s — returning empty list", schema, table)
        return []

    bind: Dict[str, Any] = {"limit": limit, "offset": offset}
    if params:
        bind.update(params)

    # Identifiers cannot be bound; schema/table are controlled by our code only.
    sql = (
        f'SELECT * FROM "{schema}"."{table}" '
        f"{where_sql} "
        f"ORDER BY {order_by} "
        f"LIMIT :limit OFFSET :offset"
    )
    try:
        rows = db.execute(text(sql), bind).mappings().all()
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.warning(
            "Failed reading %s.%s (%s) — returning empty list", schema, table, exc
        )
        return []
