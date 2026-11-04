"""
Financing-instance identity helpers for app.financed_emissions.

formula_id is an asset-class / PCAF methodology key, not a unique loan.
Each distinct loan/investment may carry a stable financing_instance_id in
inputs (and optionally results.calculation_steps). Portfolio exposures.id
(exposure_id column) is a separate credit-facility FK and must not be used
as a substitute for financing_instance_id.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import String, cast, func, text
from sqlalchemy.orm import Session

from .ghg_models import FinancedEmission

YEAR_AWARE_INDEX = "uq_financed_emissions_financing_instance_year"

FINANCING_INSTANCE_FIELD = "financing_instance_id"
FINANCING_IDENTITY_STEP = "__financing_identity__"
AGGREGATE_FORMULA_ID = "aggregate"


def is_aggregate_formula(formula_id: Optional[str]) -> bool:
    """Match DB predicate: lower(COALESCE(formula_id, '')) <> 'aggregate'."""
    return (formula_id or "").strip().lower() == AGGREGATE_FORMULA_ID


def normalize_financing_instance_id(value: Any) -> Optional[str]:
    """
    Return a non-empty trimmed instance id string, or None if missing/invalid.

    Python str.strip() mirrors Postgres btrim() for the ASCII whitespace the
    SPA emits; persisted values are always written in this normalized form so
    they match the unique index expression btrim(inputs->>'financing_instance_id').
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    # Accept UUID strings and other stable client-generated ids (e.g. fin-...).
    if len(text) > 128:
        return None
    return text


def financing_instance_json_expr():
    """SQL expression matching unique index: btrim(inputs->>'financing_instance_id')."""
    return func.btrim(cast(FinancedEmission.inputs[FINANCING_INSTANCE_FIELD], String))


def non_aggregate_formula_sql():
    """SQL predicate matching unique index aggregate exclusion (case-insensitive)."""
    return func.lower(func.coalesce(FinancedEmission.formula_id, "")) != AGGREGATE_FORMULA_ID


def normalize_reporting_year(value: Any) -> Optional[str]:
    text_value = str(value or "").strip()
    return text_value or None


def extract_reporting_year(source: Any) -> Optional[str]:
    if source is None:
        return None
    column_year = normalize_reporting_year(getattr(source, "reporting_year", None))
    if column_year:
        return column_year
    if isinstance(source, dict):
        direct = normalize_reporting_year(
            source.get("reporting_year") or source.get("reportingYear")
        )
        if direct:
            return direct
        for key in ("inputs", "results"):
            nested = source.get(key)
            if isinstance(nested, dict):
                found = normalize_reporting_year(
                    nested.get("reporting_year") or nested.get("reportingYear")
                )
                if found:
                    return found
        return None
    inputs = getattr(source, "inputs", None)
    if isinstance(inputs, dict):
        found = normalize_reporting_year(
            inputs.get("reporting_year") or inputs.get("reportingYear")
        )
        if found:
            return found
    results = getattr(source, "results", None)
    if isinstance(results, dict):
        return normalize_reporting_year(
            results.get("reporting_year") or results.get("reportingYear")
        )
    return None


def year_aware_identity_available(db: Session) -> bool:
    """True when migration 0017's unique index is present (or a test session opts in)."""
    if getattr(db, "year_aware_identity", False):
        return True
    bind = getattr(db, "get_bind", lambda: None)()
    dialect = getattr(getattr(bind, "dialect", None), "name", "")
    if dialect != "postgresql":
        return False
    try:
        row = db.execute(
            text(
                """
                SELECT 1
                FROM pg_indexes
                WHERE schemaname = 'app'
                  AND indexname = :name
                """
            ),
            {"name": YEAR_AWARE_INDEX},
        ).first()
        return row is not None
    except Exception:
        return False


def extract_financing_instance_id(source: Any) -> Optional[str]:
    """Pull financing_instance_id from inputs dict, nested payloads, or identity step."""
    if source is None:
        return None
    if isinstance(source, dict):
        direct = normalize_financing_instance_id(source.get(FINANCING_INSTANCE_FIELD))
        if direct:
            return direct
        for key in ("inputs", "pcafInputs", "pcaf_inputs", "results"):
            nested = source.get(key)
            if isinstance(nested, dict):
                found = normalize_financing_instance_id(
                    nested.get(FINANCING_INSTANCE_FIELD)
                )
                if found:
                    return found
        steps = source.get("calculation_steps") or source.get("calculationSteps")
        if isinstance(steps, list):
            for step in steps:
                if not isinstance(step, dict):
                    continue
                found = normalize_financing_instance_id(
                    step.get(FINANCING_INSTANCE_FIELD)
                )
                if found:
                    return found
        elif isinstance(steps, dict):
            found = normalize_financing_instance_id(steps.get(FINANCING_INSTANCE_FIELD))
            if found:
                return found
    return None


def preserve_financing_instance_in_inputs(
    inputs: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Ensure financing_instance_id is kept in the persisted inputs JSONB blob.
    Does not invent IDs for legacy/missing rows.
    """
    out = dict(inputs or {})
    instance_id = extract_financing_instance_id(out)
    if instance_id:
        out[FINANCING_INSTANCE_FIELD] = instance_id
    return out


def ensure_identity_in_results(
    results: Optional[Dict[str, Any]], instance_id: Optional[str]
) -> Dict[str, Any]:
    """Mirror financing_instance_id into results metadata / identity step when known."""
    out = dict(results or {})
    if not instance_id:
        return out
    meta = dict(out.get("metadata") or {})
    meta[FINANCING_INSTANCE_FIELD] = instance_id
    out["metadata"] = meta

    steps = out.get("calculation_steps")
    step_list = list(steps) if isinstance(steps, list) else []
    step_list = [
        s
        for s in step_list
        if not (
            isinstance(s, dict) and s.get("step") == FINANCING_IDENTITY_STEP
        )
    ]
    step_list.insert(
        0,
        {
            "step": FINANCING_IDENTITY_STEP,
            FINANCING_INSTANCE_FIELD: instance_id,
            "value": 0,
            "formula": "",
        },
    )
    out["calculation_steps"] = step_list
    return out


def can_upsert_by_instance(
    *,
    formula_id: Optional[str],
    financing_instance_id: Optional[str],
) -> bool:
    """
    Upsert only for non-aggregate rows with a valid instance id.
    Missing IDs must never overwrite by formula_id.
    """
    if is_aggregate_formula(formula_id):
        return False
    return financing_instance_id is not None


def find_row_by_financing_instance(
    db: Session,
    *,
    organization_id: uuid.UUID,
    calc_kind: str,
    financing_instance_id: str,
    counterparty_id: Optional[uuid.UUID],
    reporting_year: Optional[str] = None,
    for_update: bool = False,
) -> Optional[FinancedEmission]:
    """
    Locate the active row for (organization_id, counterparty_id, calc_kind, instance).
    When reporting_year is provided, only that year matches (0017 identity).
    Aggregates are excluded. Does not invent matches for legacy rows without an id.
    """
    instance_id = normalize_financing_instance_id(financing_instance_id)
    if not instance_id:
        return None

    q = db.query(FinancedEmission).filter(
        FinancedEmission.organization_id == organization_id,
        FinancedEmission.calc_kind == calc_kind,
    )
    if counterparty_id is None:
        q = q.filter(FinancedEmission.counterparty_id.is_(None))
    else:
        q = q.filter(FinancedEmission.counterparty_id == counterparty_id)

    if for_update:
        q = q.with_for_update()

    # Unique index uses btrim(inputs->>'financing_instance_id'). Verify in Python
    # so in-memory test sessions and JSON-expression dialects agree.
    matched = [
        row
        for row in q.order_by(FinancedEmission.updated_at.desc()).all()
        if extract_financing_instance_id(getattr(row, "inputs", None)) == instance_id
        and not is_aggregate_formula(row.formula_id)
    ]
    wanted_year = normalize_reporting_year(reporting_year)
    if wanted_year is not None:
        matched = [
            row for row in matched if extract_reporting_year(row) == wanted_year
        ]
    return matched[0] if matched else None


def apply_row_fields(row: FinancedEmission, fields: Dict[str, Any]) -> FinancedEmission:
    for key, value in fields.items():
        setattr(row, key, value)
    return row


def uniqueness_key(
    *,
    organization_id: uuid.UUID,
    counterparty_id: Optional[uuid.UUID],
    calc_kind: str,
    financing_instance_id: str,
) -> Tuple[uuid.UUID, Optional[uuid.UUID], str, str]:
    normalized = normalize_financing_instance_id(financing_instance_id) or ""
    return (organization_id, counterparty_id, calc_kind, normalized)
