"""
One-time reconciliation for historical EPA stationary combustion records.

Dry-run classification is the default. Apply inserts versioned correction rows
and does not update emission activities, company snapshots, questionnaires, or
finance results. Original activity values stay where they were stored.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from sqlalchemy import text

from .stationary_combustion import (
    calculate_stationary_combustion,
    canonical_consumption_unit,
)

ELIGIBLE = "eligible_for_automatic_recalculation"
REVIEW = "confirmed_incorrect_requiring_review"
INSUFFICIENT = "insufficient_information"
NO_ISSUE = "no_identified_issue"

APPROVAL_TOKEN = "APPROVE-EPA-STATIONARY-RECONCILIATION"
EPA_COMPANY_NOTES = "Calculated using EPA emission calculator version"
UK_COMPANY_NOTES = "Calculated using emission calculator"
ACTIVITY_TABLE = "app.emission_activities"
TONNE_TOLERANCE = Decimal("0.0000001")
SCOPE_QUANTUM = Decimal("0.000001")
GROUP_NAMESPACE = uuid.UUID("a3c1e7b0-6e4d-4a1f-9c2b-0d5e8f1a2b3c")

OUT_OF_SCOPE_CATEGORIES = {"kitchen", "power", "heating", "heat_steam"}
SHEET_CATEGORY_BLOCKLIST = OUT_OF_SCOPE_CATEGORIES | {"stationary_combustion", "fuel"}

_GAS_UNIT = re.compile(
    r"^(CO2|CH4|N2O)\s*\(\s*(?:kg|g)\s+(CO2|CH4|N2O)\s*/\s*(.+?)\s*\)\s*$",
    re.IGNORECASE,
)

CSV_COLUMNS = [
    "record_id",
    "source_table",
    "group_id",
    "group_role",
    "sibling_record_ids",
    "classification",
    "reason",
    "fuel",
    "category",
    "quantity",
    "activity_unit",
    "original_stored_value",
    "original_stored_unit",
    "original_co2_kg",
    "original_ch4_kg",
    "original_n2o_kg",
    "corrected_co2_kg",
    "corrected_ch4_kg",
    "corrected_n2o_kg",
    "corrected_total_tco2e",
    "difference",
    "difference_basis",
    "factor_publisher",
    "factor_dataset_code",
    "factor_version_label",
    "factor_dataset_id",
    "factor_row_id",
    "gwp_version",
    "counts_in_corrected_total",
]

INSERT_CORRECTION_SQL = """
INSERT INTO app.emission_activity_corrections (
    id, batch_id, activity_id, group_id, member_activity_ids,
    correction_hash, original_emissions_tco2e, corrected_total_tco2e,
    corrected_gases, factor_source, status
) VALUES (
    CAST(:id AS uuid),
    CAST(:batch_id AS uuid),
    CAST(:activity_id AS uuid),
    :group_id,
    CAST(string_to_array(:member_activity_ids, ',') AS uuid[]),
    :correction_hash,
    CAST(NULLIF(:original_emissions_tco2e, '') AS numeric),
    CAST(:corrected_total_tco2e AS numeric),
    CAST(:corrected_gases AS jsonb),
    CAST(:factor_source AS jsonb),
    'applied'
)
"""

REVERT_CORRECTION_SQL = """
UPDATE app.emission_activity_corrections
SET status = 'reverted', reverted_at = now()
WHERE batch_id = :batch_id AND status = 'applied'
"""


class ApplyRejected(Exception):
    """Apply or revert refused before any correction is committed."""


def _parse_decimal(value: Any) -> Optional[Decimal]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return None if not value.is_finite() else value
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (value != value or abs(value) == float("inf")):
            return None
        try:
            parsed = Decimal(str(value))
        except InvalidOperation:
            return None
        return None if not parsed.is_finite() else parsed
    text = str(value).replace(",", "").strip()
    if not text:
        return None
    try:
        parsed = Decimal(text)
    except InvalidOperation:
        return None
    return None if not parsed.is_finite() else parsed


def _text(value: Any) -> str:
    if value is None:
        return ""
    rendered = format(value, "f") if isinstance(value, Decimal) else str(value).strip()
    if isinstance(value, Decimal) and "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0" if isinstance(value, Decimal) else rendered


def _raw_dict(record: Mapping[str, Any]) -> Dict[str, Any]:
    raw = record.get("raw")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return dict(raw) if isinstance(raw, Mapping) else {}


def _inputs(raw: Mapping[str, Any]) -> Dict[str, Any]:
    inputs = raw.get("inputs")
    return dict(inputs) if isinstance(inputs, Mapping) else {}


def parse_activity_unit(unit: Any) -> tuple[Optional[str], Optional[str]]:
    """Return the physical consumption unit and, for a single-gas factor unit, the gas."""
    text = " ".join(str(unit or "").strip().split())
    if not text:
        return None, None
    physical = canonical_consumption_unit(text)
    if physical is not None:
        return physical, None
    match = _GAS_UNIT.match(text)
    if match is None or match.group(1).lower() != match.group(2).lower():
        return None, None
    physical = canonical_consumption_unit(match.group(3))
    if physical is None:
        return None, None
    return physical, match.group(1).lower()


def reviewed_ids_sha256(record_ids: Iterable[str]) -> str:
    lines = sorted({str(value).strip().lower() for value in record_ids if str(value).strip()})
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def correction_hash(payload: Mapping[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _scope_tuple(*values: Any) -> Optional[tuple]:
    parsed = []
    for value in values:
        number = _parse_decimal(value)
        if number is None:
            return None
        parsed.append(number.quantize(SCOPE_QUANTUM))
    return tuple(parsed)


def _same_tonnes(left: Optional[Decimal], right: Optional[Decimal]) -> bool:
    if left is None or right is None:
        return False
    return abs(left - right) <= TONNE_TOLERANCE


@dataclass
class Finding:
    record_id: str
    source_table: str
    classification: str
    reason: str
    group_id: str = ""
    group_role: str = ""
    sibling_record_ids: str = ""
    fuel: str = ""
    category: str = ""
    quantity: str = ""
    activity_unit: str = ""
    original_stored_value: str = ""
    original_stored_unit: str = ""
    original_co2_kg: str = ""
    original_ch4_kg: str = ""
    original_n2o_kg: str = ""
    corrected_co2_kg: str = ""
    corrected_ch4_kg: str = ""
    corrected_n2o_kg: str = ""
    corrected_total_tco2e: str = ""
    difference: str = ""
    difference_basis: str = ""
    factor_publisher: str = ""
    factor_dataset_code: str = ""
    factor_version_label: str = ""
    factor_dataset_id: str = ""
    factor_row_id: str = ""
    gwp_version: str = ""
    counts_in_corrected_total: str = "false"
    correction_payload: Dict[str, Any] = field(default_factory=dict, repr=False)

    def csv_row(self) -> Dict[str, str]:
        row = {column: getattr(self, column) for column in CSV_COLUMNS}
        return {key: "" if value is None else str(value) for key, value in row.items()}


@dataclass
class ApplyResult:
    batch_id: Optional[str]
    inserted: int
    skipped: int
    correction_ids: List[str]


class MemoryCorrectionStore:
    """In-memory correction ledger used by tests and by a caller without a database."""

    def __init__(self, fail_on_insert: Optional[int] = None):
        self.rows: List[Dict[str, Any]] = []
        self.fail_on_insert = fail_on_insert
        self.fail_on_revert = False
        self._pending: List[Dict[str, Any]] = []
        self._snapshot: List[Dict[str, Any]] = []
        self.in_transaction = False

    def begin(self) -> None:
        self.in_transaction = True
        self._snapshot = [dict(row) for row in self.rows]
        self._pending = []

    def insert(self, row: Mapping[str, Any]) -> None:
        if not self.in_transaction:
            raise ApplyRejected("insert requires an open transaction")
        attempt = len(self._pending) + 1
        if self.fail_on_insert is not None and attempt == self.fail_on_insert:
            raise RuntimeError("forced correction insert failure")
        self._pending.append(dict(row))

    def commit(self) -> None:
        self.rows.extend(self._pending)
        self._pending = []
        self.in_transaction = False

    def rollback(self) -> None:
        self.rows = [dict(row) for row in self._snapshot]
        self._pending = []
        self.in_transaction = False

    def active_for(self, activity_id: str) -> List[Dict[str, Any]]:
        target = str(activity_id).lower()
        return [
            row
            for row in self.rows
            if row.get("status") == "applied"
            and target in {str(member).lower() for member in row.get("member_activity_ids") or []}
        ]

    def revert(self, batch_id: str) -> int:
        if not self.in_transaction:
            raise ApplyRejected("revert requires an open transaction")
        if self.fail_on_revert:
            raise RuntimeError("forced correction revert failure")
        count = 0
        target = str(batch_id)
        updated: List[Dict[str, Any]] = []
        for row in self.rows:
            if row.get("batch_id") == target and row.get("status") == "applied":
                changed = dict(row)
                changed["status"] = "reverted"
                updated.append(changed)
                count += 1
            else:
                updated.append(row)
        self.rows = updated
        return count


class SqlCorrectionStore:
    """
    Writes only app.emission_activity_corrections.

    The caller opens the transaction. A failed insert must roll back that
    transaction. This store does not update source tables.
    """

    def __init__(self, connection: Any):
        self.connection = connection
        self._transaction = None

    def begin(self) -> None:
        self._transaction = self.connection.begin()

    def insert(self, row: Mapping[str, Any]) -> None:
        params = dict(row)
        params["member_activity_ids"] = ",".join(str(member) for member in params["member_activity_ids"])
        params["original_emissions_tco2e"] = params.get("original_emissions_tco2e") or ""
        params["corrected_gases"] = json.dumps(params["corrected_gases"])
        params["factor_source"] = json.dumps(params["factor_source"])
        self.connection.execute(text(INSERT_CORRECTION_SQL), params)

    def commit(self) -> None:
        if self._transaction is not None:
            self._transaction.commit()
            self._transaction = None

    def rollback(self) -> None:
        if self._transaction is not None:
            self._transaction.rollback()
            self._transaction = None

    def active_for(self, activity_id: str) -> List[Dict[str, Any]]:
        result = self.connection.execute(
            text(
                """
                SELECT id::text, batch_id::text, activity_id::text, correction_hash, status,
                       member_activity_ids::text[] AS member_activity_ids
                FROM app.emission_activity_corrections
                WHERE status = 'applied'
                  AND (
                    activity_id = CAST(:activity_id AS uuid)
                    OR CAST(:activity_id AS uuid) = ANY(member_activity_ids)
                  )
                """
            ),
            {"activity_id": activity_id},
        )
        return [dict(row) for row in result.mappings()]

    def revert(self, batch_id: str) -> int:
        result = self.connection.execute(text(REVERT_CORRECTION_SQL), {"batch_id": batch_id})
        return int(result.rowcount or 0)


def findings_to_csv(findings: Sequence[Finding]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for finding in findings:
        writer.writerow(finding.csv_row())
    return buffer.getvalue()


def _sheet_category(raw: Mapping[str, Any]) -> Optional[str]:
    inputs = _inputs(raw)
    for candidate in (
        inputs.get("fuel_category"),
        raw.get("fuel_category"),
        raw.get("Fuel Category"),
    ):
        text = str(candidate or "").strip()
        if text and text.casefold() not in SHEET_CATEGORY_BLOCKLIST:
            return text
    return None


def _framework(raw: Mapping[str, Any]) -> str:
    explicit = raw.get("emission_framework")
    if explicit is not None and str(explicit).strip():
        return str(explicit).strip().lower()
    return ""


def _activity_kind(record: Mapping[str, Any], raw: Mapping[str, Any]) -> str:
    method = str(record.get("method") or "").strip().lower()
    legacy = str(record.get("legacy_source") or "").strip().lower()
    category = str(record.get("category") or "").strip().lower()
    if method == "uk_fuel" or _framework(raw) == "uk":
        return "uk_fuel"
    if category in OUT_OF_SCOPE_CATEGORIES or legacy in {
        "ipcc_scope1_kitchen_entries",
        "ipcc_scope1_power_entries",
        "ipcc_scope1_heating_entries",
        "scope1_heatsteam_entries_epa",
    }:
        return "out_of_scope"
    if method in {"epa_stationary", "epa_fuel"} or legacy in {"epa_stationary", "scope1_fuel_entries"}:
        return "epa_stationary"
    if category in {"stationary_combustion", "fuel"}:
        return "epa_stationary"
    return "out_of_scope"


def _stored_unit(kind_method: str, gas: Optional[str], raw: Mapping[str, Any]) -> str:
    if kind_method == "epa_stationary" and not gas and raw.get("calc") == "epa_stationary":
        return "tCO2e"
    if kind_method == "epa_fuel":
        return "tonnes of the selected gas, not three-gas tCO2e"
    if gas:
        return f"kg of {gas.upper()} stored in emissions_tco2e"
    if raw.get("calc") == "epa_stationary" or raw.get("total_t_co2e") is not None:
        return "tCO2e"
    return "unknown"


def _original_gas_masses(
    stored: Optional[Decimal],
    stored_unit: str,
    gas: Optional[str],
    raw: Mapping[str, Any],
) -> Dict[str, str]:
    masses = {"co2": "", "ch4": "", "n2o": ""}
    gases = raw.get("gases") if isinstance(raw.get("gases"), Mapping) else {}
    for name in masses:
        mass = (gases.get(name) or {}).get("mass_kg") if isinstance(gases.get(name), Mapping) else None
        if mass is not None:
            masses[name] = _text(mass)
    if stored is None or not gas or masses[gas]:
        return masses
    if stored_unit.startswith("kg of"):
        masses[gas] = _text(stored)
    elif stored_unit.startswith("tonnes of the selected gas"):
        masses[gas] = _text(stored * Decimal("1000"))
    return masses


@dataclass
class _Prepared:
    record_id: str
    user_id: str
    assessment_id: str
    fuel: str
    category: Optional[str]
    quantity: Optional[Decimal]
    physical_unit: Optional[str]
    activity_unit: str
    gas: Optional[str]
    stored: Optional[Decimal]
    stored_unit: str
    method: str
    kind: str
    raw: Dict[str, Any]
    original_gases: Dict[str, str]


def _prepare_activity(record: Mapping[str, Any]) -> _Prepared:
    raw = _raw_dict(record)
    inputs = _inputs(raw)
    fuel = str(
        inputs.get("fuel") or raw.get("fuel") or raw.get("Fuel") or record.get("fuel") or ""
    ).strip()
    unit_text = str(inputs.get("unit") or record.get("unit") or raw.get("unit") or "").strip()
    physical, gas = parse_activity_unit(unit_text)
    quantity = _parse_decimal(
        record.get("quantity")
        if record.get("quantity") is not None
        else inputs.get("quantity") or raw.get("quantity")
    )
    stored = _parse_decimal(record.get("emissions_tco2e"))
    if stored is None:
        stored = _parse_decimal(raw.get("emissions"))
    method = str(record.get("method") or "").strip().lower()
    kind = _activity_kind(record, raw)
    stored_unit = _stored_unit(method, gas, raw)
    if method == "epa_stationary":
        stored_unit = "tCO2e"
    return _Prepared(
        record_id=str(record.get("id") or ""),
        user_id=str(record.get("user_id") or ""),
        assessment_id=str(record.get("assessment_id") or ""),
        fuel=fuel,
        category=_sheet_category(raw),
        quantity=quantity,
        physical_unit=physical,
        activity_unit=unit_text,
        gas=gas,
        stored=stored,
        stored_unit=stored_unit,
        method=method,
        kind=kind,
        raw=raw,
        original_gases=_original_gas_masses(stored, stored_unit, gas, raw),
    )


def _group_key(prepared: _Prepared) -> str:
    identity = prepared.assessment_id or prepared.user_id or prepared.record_id
    quantity = _text(prepared.quantity) if prepared.quantity is not None else ""
    return "|".join(
        [
            identity,
            prepared.fuel.casefold(),
            quantity,
            prepared.physical_unit or "",
            (prepared.category or "").casefold(),
        ]
    )


def _legacy_unit_is_proven_wrong(prepared: _Prepared) -> bool:
    return prepared.stored_unit.startswith("kg of") or prepared.stored_unit.startswith("tonnes of the selected gas")


def _calculation_payload(prepared: _Prepared, result: Mapping[str, Any]) -> Dict[str, Any]:
    source = result.get("factor_source") or {}
    gases = result.get("gases") or {}
    return {
        "fuel": result.get("fuel"),
        "category": result.get("category"),
        "quantity": result.get("quantity"),
        "unit": result.get("unit"),
        "co2_kg": (gases.get("co2") or {}).get("mass_kg"),
        "ch4_kg": (gases.get("ch4") or {}).get("mass_kg"),
        "n2o_kg": (gases.get("n2o") or {}).get("mass_kg"),
        "total_tco2e": result.get("total_t_co2e"),
        "dataset_code": source.get("dataset_code"),
        "version_label": source.get("version_label"),
        "gwp_version": source.get("gwp_version"),
    }


def _apply_calculation(finding: Finding, prepared: _Prepared, result: Mapping[str, Any]) -> None:
    gases = result.get("gases") or {}
    source = result.get("factor_source") or {}
    finding.fuel = str(result.get("fuel") or prepared.fuel)
    finding.category = str(result.get("category") or prepared.category or "")
    finding.quantity = str(result.get("quantity") or "")
    finding.activity_unit = prepared.activity_unit or str(result.get("unit") or "")
    finding.corrected_co2_kg = str((gases.get("co2") or {}).get("mass_kg") or "")
    finding.corrected_ch4_kg = str((gases.get("ch4") or {}).get("mass_kg") or "")
    finding.corrected_n2o_kg = str((gases.get("n2o") or {}).get("mass_kg") or "")
    finding.corrected_total_tco2e = str(result.get("total_t_co2e") or "")
    finding.factor_publisher = str(source.get("publisher") or "")
    finding.factor_dataset_code = str(source.get("dataset_code") or "")
    finding.factor_version_label = str(source.get("version_label") or "")
    finding.factor_dataset_id = str(source.get("dataset_id") or "")
    finding.factor_row_id = str(source.get("factor_row_id") or "")
    finding.gwp_version = str(source.get("gwp_version") or "")
    finding.correction_payload = _calculation_payload(prepared, result)
    corrected = _parse_decimal(result.get("total_t_co2e"))
    if prepared.stored_unit == "tCO2e" and corrected is not None and prepared.stored is not None:
        finding.difference = _text(corrected - prepared.stored)
        finding.difference_basis = "corrected tCO2e minus the stored tCO2e column"
    else:
        finding.difference = ""
        finding.difference_basis = (
            "stored value is not three-gas tCO2e, so it is not subtracted from the corrected tonnes"
        )


def _base_activity_finding(prepared: _Prepared) -> Finding:
    finding = Finding(
        record_id=prepared.record_id or "missing",
        source_table=ACTIVITY_TABLE,
        classification=INSUFFICIENT,
        reason="",
        fuel=prepared.fuel,
        category=prepared.category or "",
        quantity=_text(prepared.quantity) if prepared.quantity is not None else "",
        activity_unit=prepared.activity_unit,
        original_stored_value=_text(prepared.stored) if prepared.stored is not None else "",
        original_stored_unit=prepared.stored_unit,
        original_co2_kg=prepared.original_gases["co2"],
        original_ch4_kg=prepared.original_gases["ch4"],
        original_n2o_kg=prepared.original_gases["n2o"],
    )
    return finding


def _classify_epa_group(
    members: Sequence[_Prepared],
    sheets: Sequence[Mapping[str, Any]],
) -> List[Finding]:
    primary_seed = sorted(members, key=lambda item: ({"co2": 0, "ch4": 1, "n2o": 2}.get(item.gas or "", 3), item.record_id))[0]
    result = None
    if (
        primary_seed.fuel
        and primary_seed.quantity is not None
        and primary_seed.physical_unit
    ):
        result = calculate_stationary_combustion(
            fuel=primary_seed.fuel,
            quantity=primary_seed.quantity,
            unit=primary_seed.physical_unit,
            category=primary_seed.category,
            sheets=sheets,
        )
    success = bool(result and result.get("success"))
    gases = [item.gas for item in members]
    duplicate_gas = len(gases) != len(set(gases))
    mixed_whole_and_gas_lines = any(item.gas is None for item in members) and any(
        item.gas is not None for item in members
    )
    group_identity = _group_key(primary_seed)
    group_id = str(uuid.uuid5(GROUP_NAMESPACE, group_identity))
    sibling_ids = ",".join(sorted(item.record_id for item in members))
    proven_wrong = any(_legacy_unit_is_proven_wrong(item) for item in members)
    corrected = _parse_decimal(result.get("total_t_co2e")) if success else None

    findings: List[Finding] = []
    for prepared in sorted(members, key=lambda item: item.record_id):
        finding = _base_activity_finding(prepared)
        finding.group_id = group_id
        finding.sibling_record_ids = sibling_ids
        if not prepared.record_id:
            finding.classification = INSUFFICIENT
            finding.reason = "Activity id is missing."
        elif not prepared.fuel or prepared.quantity is None or not prepared.physical_unit:
            finding.classification = REVIEW if proven_wrong else INSUFFICIENT
            finding.reason = (
                "Original fuel, quantity, or approved consumption unit is missing. "
                "The stored number is not recalculated."
            )
        elif not success:
            error = str((result or {}).get("error") or "calculation failed")
            finding.classification = REVIEW if proven_wrong else INSUFFICIENT
            finding.reason = f"Authoritative recalculation is not unique: {error}"
        elif duplicate_gas or mixed_whole_and_gas_lines:
            _apply_calculation(finding, prepared, result)
            finding.classification = REVIEW
            finding.counts_in_corrected_total = "false"
            finding.reason = (
                "Rows share a fuel quantity but are not one unambiguous activity. "
                "Duplicates and mixed whole-activity plus single-gas lines stay in review."
            )
        else:
            _apply_calculation(finding, prepared, result)
            already = prepared.stored_unit == "tCO2e" and _same_tonnes(prepared.stored, corrected)
            if already and len(members) == 1:
                finding.classification = NO_ISSUE
                finding.counts_in_corrected_total = "false"
                finding.reason = "Stored tCO2e matches the authoritative stationary calculation."
            else:
                finding.classification = ELIGIBLE
                is_primary = prepared.record_id == primary_seed.record_id
                finding.group_role = "primary" if is_primary else "sibling"
                finding.counts_in_corrected_total = "true" if is_primary else "false"
                if len(members) == 1:
                    finding.reason = (
                        "Fuel, quantity, and consumption unit are sufficient. "
                        "The stored value is not the authoritative three-gas tCO2e."
                    )
                else:
                    finding.reason = (
                        "Distinct gas lines share one fuel quantity. "
                        "The corrected total is counted once, on the primary row."
                    )
        findings.append(finding)
    return findings


def build_activity_findings(
    activities: Sequence[Mapping[str, Any]],
    sheets: Sequence[Mapping[str, Any]],
) -> List[Finding]:
    prepared = [_prepare_activity(record) for record in activities]
    grouped: Dict[str, List[_Prepared]] = {}
    passthrough: List[_Prepared] = []
    for item in prepared:
        if item.kind != "epa_stationary":
            passthrough.append(item)
            continue
        if not item.fuel or item.quantity is None or not item.physical_unit:
            passthrough.append(item)
            continue
        grouped.setdefault(_group_key(item), []).append(item)

    findings: List[Finding] = []
    for item in passthrough:
        finding = _base_activity_finding(item)
        if item.kind == "uk_fuel":
            finding.classification = NO_ISSUE
            finding.reason = "UK fuel row. This reconciliation does not recalculate it."
        elif item.kind == "out_of_scope":
            finding.classification = NO_ISSUE
            finding.reason = "Outside the EPA stationary combustion engine."
        elif not item.fuel or item.quantity is None or not item.physical_unit:
            proven = _legacy_unit_is_proven_wrong(item)
            finding.classification = REVIEW if proven else INSUFFICIENT
            finding.reason = "Fuel, quantity, or an approved consumption unit is missing."
        findings.append(finding)

    for members in grouped.values():
        findings.extend(_classify_epa_group(members, sheets))
    return findings


def _company_finding(record: Mapping[str, Any]) -> Finding:
    scopes = _scope_tuple(
        record.get("scope1_emissions"),
        record.get("scope2_emissions"),
        record.get("scope3_emissions"),
    )
    nonzero = bool(scopes and any(value != 0 for value in scopes))
    notes = str(record.get("notes") or "")
    finding = Finding(
        record_id=str(record.get("id") or "missing"),
        source_table="public.company_emissions",
        classification=INSUFFICIENT,
        reason="Company snapshot has no marker that identifies the EPA kilogram handoff.",
        original_stored_value="" if scopes is None else "|".join(_text(value) for value in scopes),
        original_stored_unit="column comment says tCO2e; no unit column is stored",
    )
    if notes == EPA_COMPANY_NOTES and nonzero:
        finding.classification = REVIEW
        finding.reason = (
            "notes identify the pre-fix EPA calculator, which wrote session kilograms "
            "into tCO2e columns. The session was not a complete inventory, so the "
            "snapshot is not divided or overwritten."
        )
        finding.original_stored_unit = "kilograms written into a tCO2e column"
    elif notes == EPA_COMPANY_NOTES:
        finding.classification = NO_ISSUE
        finding.reason = "EPA calculator note is present and every scope is zero."
    elif notes == UK_COMPANY_NOTES:
        finding.classification = INSUFFICIENT
        finding.reason = "UK calculator note. Its unit was not established by this reconciliation."
    return finding


def _dependent_scope_finding(
    record: Mapping[str, Any],
    source_table: str,
    confirmed: Mapping[str, tuple],
) -> Finding:
    inputs = record.get("inputs") if isinstance(record.get("inputs"), Mapping) else {}
    scopes = _scope_tuple(
        record.get("scope1_emissions") if "scope1_emissions" in record else inputs.get("scope1Emissions"),
        record.get("scope2_emissions") if "scope2_emissions" in record else inputs.get("scope2Emissions"),
        record.get("scope3_emissions") if "scope3_emissions" in record else inputs.get("scope3Emissions"),
    )
    counterparty = str(record.get("counterparty_id") or "")
    finding = Finding(
        record_id=str(record.get("id") or "missing"),
        source_table=source_table,
        classification=INSUFFICIENT,
        reason=(
            "No unit or calculator source is stored. A numeric value alone is not "
            "treated as a kilogram mismatch."
        ),
        original_stored_value="" if scopes is None else "|".join(_text(value) for value in scopes),
        original_stored_unit="undetermined",
    )
    if counterparty and scopes is not None and confirmed.get(counterparty) == scopes:
        finding.classification = REVIEW
        finding.reason = (
            "Scope values equal a company snapshot written by the pre-fix EPA calculator. "
            "The row has no unit of its own, so finance results are not rescaled."
        )
    return finding


def build_portfolio_findings(
    company_rows: Sequence[Mapping[str, Any]],
    questionnaires: Sequence[Mapping[str, Any]],
    finance_rows: Sequence[Mapping[str, Any]],
) -> List[Finding]:
    company_findings = [_company_finding(row) for row in company_rows]
    confirmed: Dict[str, tuple] = {}
    for row, finding in zip(company_rows, company_findings):
        if finding.classification != REVIEW:
            continue
        scopes = _scope_tuple(
            row.get("scope1_emissions"),
            row.get("scope2_emissions"),
            row.get("scope3_emissions"),
        )
        counterparty = str(row.get("counterparty_id") or "")
        if counterparty and scopes is not None:
            confirmed[counterparty] = scopes
    dependent = [
        _dependent_scope_finding(row, "public.counterparty_questionnaires", confirmed)
        for row in questionnaires
    ]
    dependent.extend(
        _dependent_scope_finding(row, str(row.get("_source_table") or "public.emission_calculations"), confirmed)
        for row in finance_rows
    )
    return [*company_findings, *dependent]


def build_findings(
    *,
    activities: Sequence[Mapping[str, Any]] = (),
    company_rows: Sequence[Mapping[str, Any]] = (),
    questionnaires: Sequence[Mapping[str, Any]] = (),
    finance_rows: Sequence[Mapping[str, Any]] = (),
    sheets: Sequence[Mapping[str, Any]] = (),
) -> List[Finding]:
    return [
        *build_activity_findings(activities, sheets),
        *build_portfolio_findings(company_rows, questionnaires, finance_rows),
    ]


def overlay_existing_corrections(
    findings: Sequence[Finding],
    active_corrections: Sequence[Mapping[str, Any]],
) -> List[Finding]:
    """Report rows whose active correction already matches as no identified issue."""
    by_member: Dict[str, List[Mapping[str, Any]]] = {}
    for correction in active_corrections:
        if correction.get("status") not in (None, "applied"):
            continue
        members = correction.get("member_activity_ids") or [correction.get("activity_id")]
        for member in members:
            by_member.setdefault(str(member).lower(), []).append(correction)

    overlaid: List[Finding] = []
    for finding in findings:
        current = finding
        existing = by_member.get(finding.record_id.lower(), [])
        if existing and finding.correction_payload:
            expected = correction_hash(finding.correction_payload)
            hashes = {str(item.get("correction_hash") or "") for item in existing}
            copied = Finding(**{**finding.__dict__})
            if hashes == {expected}:
                copied.classification = NO_ISSUE
                copied.counts_in_corrected_total = "false"
                copied.reason = "An active correction already records this recalculation."
            else:
                copied.classification = REVIEW
                copied.counts_in_corrected_total = "false"
                copied.reason = (
                    "An active correction does not match this recalculation. "
                    "Revert that batch before proposing another."
                )
            current = copied
        overlaid.append(current)
    return overlaid


def reconcile(
    *,
    activities: Sequence[Mapping[str, Any]] = (),
    company_rows: Sequence[Mapping[str, Any]] = (),
    questionnaires: Sequence[Mapping[str, Any]] = (),
    finance_rows: Sequence[Mapping[str, Any]] = (),
    sheets: Sequence[Mapping[str, Any]] = (),
    active_corrections: Sequence[Mapping[str, Any]] = (),
) -> List[Finding]:
    base = build_findings(
        activities=activities,
        company_rows=company_rows,
        questionnaires=questionnaires,
        finance_rows=finance_rows,
        sheets=sheets,
    )
    return overlay_existing_corrections(base, active_corrections)


def _validate_manifest(manifest: Mapping[str, Any], reviewed_ids: Sequence[str]) -> None:
    if manifest.get("verified") is not True:
        raise ApplyRejected("backup manifest must set verified to true")
    reference = str(manifest.get("backup_reference") or "").strip()
    if not reference:
        raise ApplyRejected("backup manifest requires backup_reference")
    expected = reviewed_ids_sha256(reviewed_ids)
    if str(manifest.get("reviewed_ids_sha256") or "") != expected:
        raise ApplyRejected("backup manifest hash does not match the reviewed record ids")


def apply_reviewed(
    *,
    activities: Sequence[Mapping[str, Any]],
    sheets: Sequence[Mapping[str, Any]],
    store: Any,
    approval_token: str,
    backup_manifest: Mapping[str, Any],
    reviewed_ids: Sequence[str],
    company_rows: Sequence[Mapping[str, Any]] = (),
    questionnaires: Sequence[Mapping[str, Any]] = (),
    finance_rows: Sequence[Mapping[str, Any]] = (),
) -> ApplyResult:
    """
    Insert one correction per eligible group.

    Source rows are not modified. A group is written only when every member id
    is in the reviewed list. The same correction hash is skipped on a later run.
    """
    if approval_token != APPROVAL_TOKEN:
        raise ApplyRejected("approval token was not accepted")
    if not reviewed_ids:
        raise ApplyRejected("reviewed record id list is empty")
    _validate_manifest(backup_manifest, reviewed_ids)

    findings = build_findings(
        activities=activities,
        company_rows=company_rows,
        questionnaires=questionnaires,
        finance_rows=finance_rows,
        sheets=sheets,
    )
    by_id = {finding.record_id.lower(): finding for finding in findings}
    selected: List[Finding] = []
    for record_id in reviewed_ids:
        finding = by_id.get(str(record_id).strip().lower())
        if finding is None or finding.source_table != ACTIVITY_TABLE:
            raise ApplyRejected(
                f"{record_id} is not an EPA stationary activity eligible for a versioned correction"
            )
        if finding.classification != ELIGIBLE:
            raise ApplyRejected(f"{record_id} is classified as {finding.classification}")
        selected.append(finding)

    selected_ids = {finding.record_id.lower() for finding in selected}
    groups: Dict[str, List[Finding]] = {}
    for finding in selected:
        groups.setdefault(finding.group_id, []).append(finding)
    for group_id, _chosen in groups.items():
        members = {
            finding.record_id.lower()
            for finding in findings
            if finding.group_id == group_id and finding.classification == ELIGIBLE
        }
        if members - selected_ids:
            raise ApplyRejected(
                f"group {group_id} is incomplete; review every member before applying"
            )

    batch_id = str(uuid.uuid4())
    planned: List[Dict[str, Any]] = []
    skipped = 0
    store.begin()
    try:
        for group_id, chosen in groups.items():
            primary = next(item for item in chosen if item.group_role == "primary")
            payload_hash = correction_hash(primary.correction_payload)
            member_ids = sorted({item.record_id for item in chosen})
            existing_hashes = set()
            for member_id in member_ids:
                for existing in store.active_for(member_id):
                    existing_hashes.add(str(existing.get("correction_hash") or ""))
            if existing_hashes:
                if existing_hashes != {payload_hash}:
                    raise ApplyRejected(
                        f"group {group_id} already has a different active correction; revert it first"
                    )
                skipped += 1
                continue
            planned.append(
                {
                    "id": str(uuid.uuid4()),
                    "batch_id": batch_id,
                    "activity_id": primary.record_id,
                    "group_id": group_id,
                    "member_activity_ids": member_ids,
                    "correction_hash": payload_hash,
                    "original_emissions_tco2e": primary.original_stored_value or None,
                    "corrected_total_tco2e": primary.corrected_total_tco2e,
                    "corrected_gases": {
                        "co2_kg": primary.corrected_co2_kg,
                        "ch4_kg": primary.corrected_ch4_kg,
                        "n2o_kg": primary.corrected_n2o_kg,
                    },
                    "factor_source": {
                        "publisher": primary.factor_publisher,
                        "dataset_code": primary.factor_dataset_code,
                        "version_label": primary.factor_version_label,
                        "dataset_id": primary.factor_dataset_id,
                        "factor_row_id": primary.factor_row_id,
                        "gwp_version": primary.gwp_version,
                    },
                    "status": "applied",
                }
            )
        for row in planned:
            store.insert(row)
        if planned:
            store.commit()
        else:
            store.rollback()
    except Exception:
        store.rollback()
        raise
    if not planned:
        return ApplyResult(batch_id=None, inserted=0, skipped=skipped, correction_ids=[])
    return ApplyResult(
        batch_id=batch_id,
        inserted=len(planned),
        skipped=skipped,
        correction_ids=[row["id"] for row in planned],
    )


def revert_batch(store: Any, batch_id: str, approval_token: str) -> int:
    """Mark one applied batch as reverted. Source tables are not changed."""
    if approval_token != APPROVAL_TOKEN:
        raise ApplyRejected("approval token was not accepted")
    if not str(batch_id).strip():
        raise ApplyRejected("batch id is required")
    store.begin()
    try:
        count = int(store.revert(batch_id))
        if count == 0:
            store.rollback()
            raise ApplyRejected("no applied corrections were found for that batch")
        store.commit()
    except ApplyRejected:
        raise
    except Exception:
        store.rollback()
        raise
    return count
