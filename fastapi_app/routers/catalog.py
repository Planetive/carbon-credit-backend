"""Read-only catalog endpoints (Explore encyclopedias)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..auth_org import OrgContext, get_current_org_context
from ..db import get_db
from ..ppp_gdp import row_has_resolvable_ppp
from .catalog_utils import fetch_table_rows, table_exists

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/catalog", tags=["catalog"])

# (route path segment, schema, table name)
CATALOG_TABLES = (
    ("country-emissions", "catalog", "country_emissions"),
    ("global-projects", "catalog", "global_projects"),
    ("global-projects-2025", "catalog", "global_projects_2025"),
    ("ccus-projects", "catalog", "ccus_projects"),
    ("ccus-policies", "catalog", "ccus_policies"),
    ("ccus-management-strategies", "catalog", "ccus_management_strategies"),
    ("bess", "catalog", "bess"),
    ("carbon-credit-markets", "catalog", "carbon_credit_markets"),
    ("compliance-mechanisms", "catalog", "compliance_mechanisms"),
    ("suppliers", "public", "suppliers"),
    ("ppp-adjusted-gdp", "ref", "ppp_adjusted_gdp"),
    ("country-sector-intensity", "ref", "country_sector_intensity"),
)


def _list_catalog(
    db: Session,
    schema: str,
    table: str,
    limit: int,
    offset: int,
    search_column: Optional[str] = None,
    search_value: Optional[str] = None,
) -> List[Dict[str, Any]]:
    where_sql = ""
    params: Dict[str, Any] = {}
    if search_column and search_value:
        # search_column is a fixed identifier from our code, never user input as SQL ident
        where_sql = f'WHERE "{search_column}"::text ILIKE :q'
        params["q"] = f"%{search_value}%"
    return fetch_table_rows(
        db,
        schema=schema,
        table=table,
        limit=limit,
        offset=offset,
        where_sql=where_sql,
        params=params,
    )


@router.get("/tables", response_model=List[Dict[str, Any]])
def list_available_catalog_tables(
    ctx: OrgContext = Depends(get_current_org_context),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Diagnostic: which catalog tables exist on this database."""
    _ = ctx
    out: List[Dict[str, Any]] = []
    for route, schema, table in CATALOG_TABLES:
        exists = table_exists(db, schema, table)
        out.append(
            {
                "route": f"/api/v1/catalog/{route}",
                "schema": schema,
                "table": table,
                "exists": exists,
            }
        )
        if not exists:
            logger.warning("Catalog table missing: %s.%s", schema, table)
    return out


@router.get("/country-emissions", response_model=List[Dict[str, Any]])
def list_country_emissions(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    country: Optional[str] = None,
    ctx: OrgContext = Depends(get_current_org_context),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    _ = ctx
    rows = _list_catalog(
        db, "catalog", "country_emissions", limit, offset, "country", country
    )
    if rows or table_exists(db, "catalog", "country_emissions"):
        return rows
    # Compatibility view fallback
    return _list_catalog(
        db, "public", "country_emissions", limit, offset, "country", country
    )


@router.get("/global-projects", response_model=List[Dict[str, Any]])
def list_global_projects(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    q: Optional[str] = None,
    ctx: OrgContext = Depends(get_current_org_context),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    _ = ctx
    # Prefer 2025 sheet if present; else legacy global_projects
    if table_exists(db, "catalog", "global_projects_2025"):
        return _list_catalog(db, "catalog", "global_projects_2025", limit, offset)
    return _list_catalog(db, "catalog", "global_projects", limit, offset)


@router.get("/ccus-projects", response_model=List[Dict[str, Any]])
def list_ccus_projects(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    ctx: OrgContext = Depends(get_current_org_context),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    _ = ctx
    return _list_catalog(db, "catalog", "ccus_projects", limit, offset)


@router.get("/bess", response_model=List[Dict[str, Any]])
def list_bess(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    ctx: OrgContext = Depends(get_current_org_context),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    _ = ctx
    return _list_catalog(db, "catalog", "bess", limit, offset)


@router.get("/carbon-credit-markets", response_model=List[Dict[str, Any]])
def list_carbon_credit_markets(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    ctx: OrgContext = Depends(get_current_org_context),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    _ = ctx
    return _list_catalog(db, "catalog", "carbon_credit_markets", limit, offset)


@router.get("/compliance-mechanisms", response_model=List[Dict[str, Any]])
def list_compliance_mechanisms(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    ctx: OrgContext = Depends(get_current_org_context),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    _ = ctx
    return _list_catalog(db, "catalog", "compliance_mechanisms", limit, offset)


def _list_with_public_fallback(
    db: Session,
    catalog_table: str,
    public_table: str,
    limit: int,
    offset: int,
) -> List[Dict[str, Any]]:
    if table_exists(db, "catalog", catalog_table):
        return _list_catalog(db, "catalog", catalog_table, limit, offset)
    if table_exists(db, "public", public_table):
        return _list_catalog(db, "public", public_table, limit, offset)
    return []


@router.get("/ccus-policies", response_model=List[Dict[str, Any]])
def list_ccus_policies(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    ctx: OrgContext = Depends(get_current_org_context),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    _ = ctx
    return _list_with_public_fallback(db, "ccus_policies", "ccus_policies", limit, offset)


@router.get("/ccus-management-strategies", response_model=List[Dict[str, Any]])
def list_ccus_management_strategies(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    ctx: OrgContext = Depends(get_current_org_context),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    _ = ctx
    return _list_with_public_fallback(
        db, "ccus_management_strategies", "ccus_management_strategies", limit, offset
    )


@router.get("/suppliers", response_model=List[Dict[str, Any]])
def list_suppliers(
    q: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    ctx: OrgContext = Depends(get_current_org_context),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """KEEP public.suppliers — Scope 3 supplier search (missing table → [])."""
    _ = ctx
    if not table_exists(db, "public", "suppliers"):
        logger.warning("Catalog table missing: public.suppliers — returning empty list")
        return []

    where_sql = ""
    params: Dict[str, Any] = {}
    q_trim = (q or "").strip()
    if q_trim:
        where_sql = (
            "WHERE supplier_name ILIKE :q "
            "OR COALESCE(code, '') ILIKE :q"
        )
        params["q"] = f"%{q_trim}%"

    return fetch_table_rows(
        db,
        schema="public",
        table="suppliers",
        limit=limit,
        offset=offset,
        where_sql=where_sql,
        params=params,
        order_by="supplier_name ASC",
    )


@router.get("/ppp-adjusted-gdp", response_model=List[Dict[str, Any]])
def list_ppp_adjusted_gdp(
    limit: int = Query(default=5000, ge=1, le=10000),
    offset: int = Query(default=0, ge=0),
    ctx: OrgContext = Depends(get_current_org_context),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """KEEP ref.ppp_adjusted_gdp — countries with at least one usable GDP year."""
    _ = ctx
    if not table_exists(db, "ref", "ppp_adjusted_gdp"):
        logger.warning("Catalog table missing: ref.ppp_adjusted_gdp — returning empty list")
        return []

    rows = (
        db.execute(
            text(
                """
                SELECT country_name, gdp_2024, gdp_2025
                FROM ref.ppp_adjusted_gdp
                WHERE (gdp_2025 IS NOT NULL AND gdp_2025 > 0)
                   OR (gdp_2024 IS NOT NULL AND gdp_2024 > 0)
                ORDER BY country_name
                LIMIT :limit OFFSET :offset
                """
            ),
            {"limit": limit, "offset": offset},
        )
        .mappings()
        .all()
    )
    out: List[Dict[str, Any]] = []
    for r in rows:
        row = dict(r)
        if not row_has_resolvable_ppp(row):
            continue
        for key in ("gdp_2024", "gdp_2025"):
            if row.get(key) is not None and hasattr(row[key], "as_tuple"):
                row[key] = float(row[key])
        out.append(row)
    return out


@router.get("/country-sector-intensity", response_model=List[Dict[str, Any]])
def list_country_sector_intensity(
    country_name: Optional[str] = Query(default=None),
    limit: int = Query(default=5000, ge=1, le=10000),
    ctx: OrgContext = Depends(get_current_org_context),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    _ = ctx
    if not table_exists(db, "ref", "country_sector_intensity"):
        logger.warning("Catalog table missing: ref.country_sector_intensity — returning empty list")
        return []

    query = "SELECT * FROM ref.country_sector_intensity"
    params: Dict[str, Any] = {"limit": limit}
    country = (country_name or "").strip()
    if country:
        query += " WHERE lower(country_name) = lower(:country_name)"
        params["country_name"] = country
    query += " ORDER BY sector_name LIMIT :limit"
    rows = db.execute(text(query), params).mappings().all()
    return [dict(r) for r in rows]
