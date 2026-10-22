"""
Read-only by default.

    python -m fastapi_app.ghg_calc.reconcile_historical_epa --output epa-stationary-reconciliation.csv

Apply is refused unless --apply, the approval token, a verified backup manifest,
and a reviewed id file are all present. This module does not run apply when imported.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .historical_reconciliation import (
    APPROVAL_TOKEN,
    ApplyRejected,
    Finding,
    SqlCorrectionStore,
    apply_reviewed,
    findings_to_csv,
    reconcile,
    revert_batch,
)

ACTIVITY_SQL = """
SELECT
    id::text AS id,
    assessment_id::text AS assessment_id,
    user_id::text AS user_id,
    scope,
    category,
    method,
    counterparty_id::text AS counterparty_id,
    quantity,
    unit,
    emissions_tco2e,
    raw,
    legacy_source,
    legacy_id::text AS legacy_id
FROM app.emission_activities
WHERE legacy_source IN (
    'scope1_fuel_entries',
    'epa_stationary',
    'ipcc_scope1_kitchen_entries',
    'ipcc_scope1_power_entries',
    'ipcc_scope1_heating_entries',
    'scope1_heatsteam_entries_epa'
)
OR method IN ('epa_stationary', 'epa_fuel', 'uk_fuel')
OR category IN ('stationary_combustion', 'fuel', 'kitchen', 'power', 'heating', 'heat_steam')
"""

COMPANY_SQL = """
SELECT
    id::text AS id,
    counterparty_id::text AS counterparty_id,
    notes,
    calculation_source,
    scope1_emissions,
    scope2_emissions,
    scope3_emissions,
    total_emissions,
    status
FROM public.company_emissions
"""

QUESTIONNAIRE_SQL = """
SELECT
    id::text AS id,
    counterparty_id::text AS counterparty_id,
    scope1_emissions,
    scope2_emissions,
    scope3_emissions,
    has_emissions,
    verification_status
FROM public.counterparty_questionnaires
"""

EMISSION_CALCULATION_SQL = """
SELECT
    id::text AS id,
    counterparty_id::text AS counterparty_id,
    calculation_type,
    financed_emissions,
    inputs,
    'public.emission_calculations' AS _source_table
FROM public.emission_calculations
"""

FINANCED_SQL = """
SELECT
    id::text AS id,
    counterparty_id::text AS counterparty_id,
    calc_kind,
    financed_emissions,
    inputs,
    legacy_source,
    'app.financed_emissions' AS _source_table
FROM app.financed_emissions
"""

ACTIVE_CORRECTION_SQL = """
SELECT
    id::text AS id,
    batch_id::text AS batch_id,
    activity_id::text AS activity_id,
    correction_hash,
    status,
    member_activity_ids::text[] AS member_activity_ids
FROM app.emission_activity_corrections
WHERE status = 'applied'
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Classify historical EPA stationary records. Dry-run is the default and does not write."
    )
    parser.add_argument(
        "--output",
        default="epa-stationary-reconciliation.csv",
        help="CSV path written by dry-run.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Insert versioned corrections. Requires approval, a backup manifest, and reviewed ids.",
    )
    parser.add_argument("--revert-batch", default="", help="Mark one applied correction batch as reverted.")
    parser.add_argument("--approval-token", default="")
    parser.add_argument("--backup-manifest", default="")
    parser.add_argument("--ids-file", default="", help="Reviewed activity ids, one UUID per line.")
    return parser


def read_reviewed_ids(path: str) -> List[str]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]


def read_manifest(path: str) -> Dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ApplyRejected("backup manifest must be a JSON object")
    return payload


def validate_gates(args: argparse.Namespace) -> None:
    if args.apply and args.revert_batch:
        raise ApplyRejected("apply and revert cannot be combined")
    if not args.apply and not args.revert_batch:
        return
    if args.approval_token != APPROVAL_TOKEN:
        raise ApplyRejected("apply and revert require the explicit approval token")
    if args.revert_batch:
        return
    if not args.backup_manifest or not args.ids_file:
        raise ApplyRejected("apply requires --backup-manifest and --ids-file")


def _select(connection: Any, sql: str) -> List[Dict[str, Any]]:
    return [dict(row) for row in connection.execute(text(sql)).mappings()]


def load_inventory(connection: Any) -> Dict[str, Any]:
    """Run SELECT statements only. A missing optional table is reported, not written."""
    warnings: List[Finding] = []

    def optional(sql: str, label: str) -> List[Dict[str, Any]]:
        try:
            nested = connection.begin_nested()
            try:
                rows = _select(connection, sql)
                nested.commit()
                return rows
            except Exception:
                nested.rollback()
                raise
        except SQLAlchemyError as exc:
            warnings.append(
                Finding(
                    record_id=label,
                    source_table=label,
                    classification="insufficient_information",
                    reason=f"Read failed and no rows were classified: {exc.__class__.__name__}",
                )
            )
            return []

    activities = _select(connection, ACTIVITY_SQL)
    return {
        "activities": activities,
        "company_rows": optional(COMPANY_SQL, "public.company_emissions"),
        "questionnaires": optional(QUESTIONNAIRE_SQL, "public.counterparty_questionnaires"),
        "finance_rows": [
            *optional(EMISSION_CALCULATION_SQL, "public.emission_calculations"),
            *optional(FINANCED_SQL, "app.financed_emissions"),
        ],
        "active_corrections": optional(ACTIVE_CORRECTION_SQL, "app.emission_activity_corrections"),
        "warnings": warnings,
    }


def write_report(path: str, findings: Sequence[Finding]) -> None:
    Path(path).write_text(findings_to_csv(findings), encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        validate_gates(args)
    except ApplyRejected as exc:
        parser.error(str(exc))

    from sqlalchemy.orm import Session

    from ..db import engine
    from ..routers.calc import _stationary_factor_sheets

    if engine is None:
        print("DATABASE_URL is not set. No database was opened.", file=sys.stderr)
        return 2

    with Session(engine) as session:
        inventory = load_inventory(session)
        sheets = _stationary_factor_sheets(session)
        session.rollback()

    if args.revert_batch:
        with engine.connect() as connection:
            count = revert_batch(SqlCorrectionStore(connection), args.revert_batch, args.approval_token)
        print(f"Reverted {count} correction row(s) in batch {args.revert_batch}. Source tables were not updated.")
        return 0

    if args.apply:
        manifest = read_manifest(args.backup_manifest)
        reviewed = read_reviewed_ids(args.ids_file)
        with engine.connect() as connection:
            result = apply_reviewed(
                activities=inventory["activities"],
                company_rows=inventory["company_rows"],
                questionnaires=inventory["questionnaires"],
                finance_rows=inventory["finance_rows"],
                sheets=sheets,
                store=SqlCorrectionStore(connection),
                approval_token=args.approval_token,
                backup_manifest=manifest,
                reviewed_ids=reviewed,
            )
        print(
            f"Inserted {result.inserted} correction row(s); skipped {result.skipped}. "
            "Original activity, questionnaire, company, and finance rows were not updated."
        )
        return 0

    findings = [
        *inventory["warnings"],
        *reconcile(
            activities=inventory["activities"],
            company_rows=inventory["company_rows"],
            questionnaires=inventory["questionnaires"],
            finance_rows=inventory["finance_rows"],
            sheets=sheets,
            active_corrections=inventory["active_corrections"],
        ),
    ]
    write_report(args.output, findings)
    counts: Dict[str, int] = {}
    for finding in findings:
        counts[finding.classification] = counts.get(finding.classification, 0) + 1
    print(f"Dry-run wrote {len(findings)} row(s) to {args.output}.")
    for name, count in sorted(counts.items()):
        print(f"{name}: {count}")
    print("No database writes were committed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ApplyRejected as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
