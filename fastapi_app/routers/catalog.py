"""Read-only catalog endpoints (pattern for Explore encyclopedias)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..auth_org import OrgContext, get_current_org_context
from ..db import get_db

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("/country-emissions", response_model=List[Dict[str, Any]])
def list_country_emissions(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    country: Optional[str] = None,
    ctx: OrgContext = Depends(get_current_org_context),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """
    Read-only sample catalog endpoint.
    Uses catalog.country_emissions (public.country_emissions view also exists).
    Auth required; not org-filtered (shared reference data).
    """
    _ = ctx  # auth gate
    try:
        if country:
            rows = db.execute(
                text(
                    "SELECT * FROM catalog.country_emissions "
                    "WHERE country ILIKE :country "
                    "ORDER BY country "
                    "LIMIT :limit OFFSET :offset"
                ),
                {"country": f"%{country}%", "limit": limit, "offset": offset},
            ).mappings().all()
        else:
            rows = db.execute(
                text(
                    "SELECT * FROM catalog.country_emissions "
                    "ORDER BY 1 "
                    "LIMIT :limit OFFSET :offset"
                ),
                {"limit": limit, "offset": offset},
            ).mappings().all()
    except Exception as exc:
        # Fall back to public compatibility view
        try:
            rows = db.execute(
                text(
                    "SELECT * FROM public.country_emissions "
                    "LIMIT :limit OFFSET :offset"
                ),
                {"limit": limit, "offset": offset},
            ).mappings().all()
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Catalog table unavailable: {exc}",
            ) from exc

    return [dict(r) for r in rows]
