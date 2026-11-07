"""
PCAF §5.7 pp.107–108 overlap review workflow.

Detects UoP vs general-purpose financing to the same issuer/year, lets a
reviewer record evidenced outstanding/allocation adjustments, and approve or
reject. Never silently subtracts emissions. Unresolved reviews keep reportable
Save blocked. Migration 0019 is prepared and must not be auto-applied.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from .financing_instance import normalize_financing_instance_id, normalize_reporting_year
from .uop_reportable import (
    PCAF_OVERLAP_GUIDANCE,
    PCAF_OVERLAP_REF,
    scan_uop_general_purpose_overlap,
)

# Review workflow flag. Independent of reportable Save.
UOP_OVERLAP_REVIEW_ENABLED = True


def overlap_review_enabled() -> bool:
    env = (os.getenv("UOP_OVERLAP_REVIEW_ENABLED") or "").strip().lower()
    if env in ("1", "true", "yes"):
        return True
    if env in ("0", "false", "no"):
        return False
    return bool(UOP_OVERLAP_REVIEW_ENABLED)


def _table_exists(db: Session) -> bool:
    # Memory/test sessions and pre-migration DBs have no review table.
    if db is None or not hasattr(db, "execute"):
        return False
    try:
        row = db.execute(
            text(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'app' AND table_name = 'uop_overlap_reviews'
                LIMIT 1
                """
            )
        ).first()
        return bool(row)
    except Exception:
        return False


def list_overlap_candidates(
    db: Session,
    *,
    organization_id: uuid.UUID,
    counterparty_id: Optional[uuid.UUID],
    reporting_year: Optional[str],
    financing_instance_id: str,
    issuer_name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    return scan_uop_general_purpose_overlap(
        db,
        organization_id=organization_id,
        counterparty_id=counterparty_id,
        reporting_year=reporting_year,
        financing_instance_id=financing_instance_id,
        issuer_name=issuer_name,
    )


def list_overlap_reviews(
    db: Session,
    *,
    organization_id: uuid.UUID,
    financing_instance_id: Optional[str] = None,
    reporting_year: Optional[str] = None,
) -> List[Dict[str, Any]]:
    if not _table_exists(db):
        return []
    clauses = ["organization_id = :org"]
    params: Dict[str, Any] = {"org": str(organization_id)}
    if financing_instance_id:
        clauses.append("uop_financing_instance_id = :fid")
        params["fid"] = normalize_financing_instance_id(financing_instance_id)
    if reporting_year:
        clauses.append("reporting_year = :year")
        params["year"] = normalize_reporting_year(reporting_year)
    rows = db.execute(
        text(
            f"""
            SELECT id, organization_id, uop_financing_instance_id,
                   general_purpose_financing_instance_id, counterparty_id,
                   issuer_name, reporting_year, status,
                   documented_allocation_notes, evidence_reference,
                   evidence_is_verified, uop_outstanding_adjustment,
                   general_purpose_outstanding_adjustment, adjustment_basis,
                   reviewer_user_id, review_notes, decided_at,
                   created_by, created_at, updated_at
            FROM app.uop_overlap_reviews
            WHERE {' AND '.join(clauses)}
            ORDER BY created_at DESC
            """
        ),
        params,
    ).mappings().all()
    return [dict(row) for row in rows]


def create_overlap_review(
    db: Session,
    *,
    organization_id: uuid.UUID,
    payload: Dict[str, Any],
    created_by: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    if not overlap_review_enabled():
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Overlap review is disabled.")
    if not _table_exists(db):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "OVERLAP_REVIEW_SCHEMA_MISSING",
                "message": (
                    "app.uop_overlap_reviews is not installed. "
                    "Apply migration 0019_uop_overlap_reviews.sql after review."
                ),
            },
        )
    uop_id = normalize_financing_instance_id(payload.get("uop_financing_instance_id"))
    year = normalize_reporting_year(payload.get("reporting_year"))
    if not uop_id or not year:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="uop_financing_instance_id and reporting_year are required.",
        )
    evidence = str(payload.get("evidence_reference") or "").strip()
    notes = str(payload.get("documented_allocation_notes") or "").strip()
    if not evidence and not notes:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Record the documented proceeds allocation or an evidence "
                "reference. Entering a name does not verify a document."
            ),
        )
    row = db.execute(
        text(
            """
            INSERT INTO app.uop_overlap_reviews (
              organization_id, uop_financing_instance_id,
              general_purpose_financing_instance_id, counterparty_id,
              issuer_name, reporting_year, status,
              documented_allocation_notes, evidence_reference,
              evidence_is_verified, uop_outstanding_adjustment,
              general_purpose_outstanding_adjustment, adjustment_basis,
              created_by
            ) VALUES (
              :org, :uop_id, :gp_id, :cp_id, :issuer, :year, 'pending_review',
              :notes, :evidence, FALSE, :uop_adj, :gp_adj, :basis, :created_by
            )
            RETURNING *
            """
        ),
        {
            "org": str(organization_id),
            "uop_id": uop_id,
            "gp_id": payload.get("general_purpose_financing_instance_id"),
            "cp_id": payload.get("counterparty_id"),
            "issuer": payload.get("issuer_name"),
            "year": year,
            "notes": notes or None,
            "evidence": evidence or None,
            "uop_adj": payload.get("uop_outstanding_adjustment"),
            "gp_adj": payload.get("general_purpose_outstanding_adjustment"),
            "basis": payload.get("adjustment_basis"),
            "created_by": str(created_by) if created_by else None,
        },
    ).mappings().first()
    db.commit()
    return dict(row)


def decide_overlap_review(
    db: Session,
    *,
    organization_id: uuid.UUID,
    review_id: uuid.UUID,
    decision: str,
    reviewer_user_id: Optional[uuid.UUID] = None,
    review_notes: Optional[str] = None,
) -> Dict[str, Any]:
    if decision not in ("approved", "rejected", "cancelled"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="decision must be approved, rejected, or cancelled.")
    if not _table_exists(db):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Overlap review schema missing.")
    existing = db.execute(
        text(
            """
            SELECT * FROM app.uop_overlap_reviews
            WHERE id = :id AND organization_id = :org
            FOR UPDATE
            """
        ),
        {"id": str(review_id), "org": str(organization_id)},
    ).mappings().first()
    if not existing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Overlap review not found.")
    if existing["status"] != "pending_review":
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Review already {existing['status']}.")
    if decision == "approved":
        if not existing.get("evidence_reference") and not existing.get("documented_allocation_notes"):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="An approved overlap review requires documented allocation notes or an evidence reference.",
            )
        # PCAF allows an evidenced split. We still do not auto-subtract totals.
        if (
            existing.get("uop_outstanding_adjustment") is None
            and existing.get("general_purpose_outstanding_adjustment") is None
        ):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Record the evidenced outstanding or allocation adjustment "
                    "before approving. The platform will not invent the split."
                ),
            )
    row = db.execute(
        text(
            """
            UPDATE app.uop_overlap_reviews
            SET status = :status,
                reviewer_user_id = :reviewer,
                review_notes = :notes,
                decided_at = :decided_at,
                updated_at = NOW()
            WHERE id = :id AND organization_id = :org
            RETURNING *
            """
        ),
        {
            "status": decision,
            "reviewer": str(reviewer_user_id) if reviewer_user_id else None,
            "notes": review_notes,
            "decided_at": datetime.now(timezone.utc),
            "id": str(review_id),
            "org": str(organization_id),
        },
    ).mappings().first()
    db.commit()
    return dict(row)


def approved_overlap_for_instance(
    db: Session,
    *,
    organization_id: uuid.UUID,
    financing_instance_id: str,
    reporting_year: Optional[str],
) -> List[Dict[str, Any]]:
    reviews = list_overlap_reviews(
        db,
        organization_id=organization_id,
        financing_instance_id=financing_instance_id,
        reporting_year=reporting_year,
    )
    return [row for row in reviews if row.get("status") == "approved"]


def enrich_overlap_payload(
    overlap_items: List[Dict[str, Any]],
    reviews: List[Dict[str, Any]],
) -> Dict[str, Any]:
    pending = [row for row in reviews if row.get("status") == "pending_review"]
    approved = [row for row in reviews if row.get("status") == "approved"]
    rejected = [row for row in reviews if row.get("status") == "rejected"]
    unresolved = bool(overlap_items) and not approved
    return {
        "detected": bool(overlap_items),
        "status": (
            "approved"
            if approved and overlap_items
            else "review_required"
            if overlap_items
            else "none"
        ),
        "items": overlap_items,
        "reviews": reviews,
        "pending_reviews": pending,
        "approved_reviews": approved,
        "rejected_reviews": rejected,
        "unresolved": unresolved,
        "auto_redistribution": "none",
        "pcaf_ref": PCAF_OVERLAP_REF,
        "guidance": PCAF_OVERLAP_GUIDANCE,
        "impact_note": (
            "Approved reviews document an evidenced outstanding/allocation "
            "split for auditors. Reported emissions are not silently "
            "subtracted by this workflow."
        ),
    }


def assert_overlap_resolved_for_reportable(
    overlap_items: List[Dict[str, Any]],
    reviews: List[Dict[str, Any]],
) -> None:
    if not overlap_items:
        return
    if any(row.get("status") == "approved" for row in reviews):
        return
    raise HTTPException(
        status.HTTP_409_CONFLICT,
        detail={
            "code": "UOP_OVERLAP_REVIEW_REQUIRED",
            "message": PCAF_OVERLAP_GUIDANCE,
            "overlap": overlap_items,
            "redistribution": "none",
        },
    )
