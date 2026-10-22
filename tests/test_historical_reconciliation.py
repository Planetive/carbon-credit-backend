"""Historical EPA stationary reconciliation. No database connection."""

from __future__ import annotations

import pytest

from fastapi_app.ghg_calc.historical_reconciliation import (
    APPROVAL_TOKEN,
    ELIGIBLE,
    INSUFFICIENT,
    INSERT_CORRECTION_SQL,
    NO_ISSUE,
    REVIEW,
    REVERT_CORRECTION_SQL,
    ApplyRejected,
    MemoryCorrectionStore,
    SqlCorrectionStore,
    apply_reviewed,
    findings_to_csv,
    reconcile,
    reviewed_ids_sha256,
    revert_batch,
)
from fastapi_app.ghg_calc.reconcile_historical_epa import main
from tests.test_stationary_combustion import NATURAL_GAS, SHEETS

USER = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
ASSESSMENT = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
CO2_ID = "10000000-0000-0000-0000-000000000001"
CH4_ID = "00000000-0000-0000-0000-000000000002"
N2O_ID = "20000000-0000-0000-0000-000000000003"
DUPLICATE_ID = "30000000-0000-0000-0000-000000000004"
COMPANY_ID = "40000000-0000-0000-0000-000000000005"
QUESTIONNAIRE_ID = "50000000-0000-0000-0000-000000000006"
COUNTERPARTY = "60000000-0000-0000-0000-000000000007"


def _legacy(**overrides):
    raw = {
        "fuel": "Natural Gas",
        "fuel_type_group": "Gaseous fuels",
        "emission_framework": "epa",
        "emissions": 5306,
        "_inferred_framework": "uk",
    }
    if "raw" in overrides:
        raw = overrides.pop("raw")
    row = {
        "id": CO2_ID,
        "user_id": USER,
        "assessment_id": ASSESSMENT,
        "legacy_source": "scope1_fuel_entries",
        "category": "fuel",
        "method": "activity_data",
        "quantity": 100,
        "unit": "CO2 (kg CO2 / mmBtu)",
        "emissions_tco2e": 5306,
        "raw": raw,
    }
    row.update(overrides)
    return row


def _manifest(ids):
    return {
        "verified": True,
        "backup_reference": "reviewed-backup-not-executed",
        "reviewed_ids_sha256": reviewed_ids_sha256(ids),
    }


def _apply(activities, ids, store, **kwargs):
    return apply_reviewed(
        activities=activities,
        sheets=SHEETS,
        store=store,
        approval_token=APPROVAL_TOKEN,
        backup_manifest=_manifest(ids),
        reviewed_ids=ids,
        **kwargs,
    )


def test_natural_gas_legacy_row_recalculates_all_gases():
    activity = _legacy()
    findings = reconcile(activities=[activity], sheets=SHEETS)
    finding = findings[0]
    assert finding.classification == ELIGIBLE
    assert finding.corrected_co2_kg == "5306"
    assert finding.corrected_ch4_kg == "0.1"
    assert finding.corrected_n2o_kg == "0.01"
    assert finding.corrected_total_tco2e == "5.31145"
    assert finding.factor_dataset_code == "fuel_epa_2"
    assert finding.factor_version_label == "imported_from_sheet"
    assert finding.factor_publisher == "EPA"
    assert finding.gwp_version == "AR5"
    assert finding.difference == ""
    assert finding.original_stored_unit == "kg of CO2 stored in emissions_tco2e"
    assert finding.counts_in_corrected_total == "true"
    csv_text = findings_to_csv(findings)
    assert CO2_ID in csv_text
    assert "eligible_for_automatic_recalculation" in csv_text
    assert activity["emissions_tco2e"] == 5306


def test_ambiguous_fuel_is_review_not_eligible():
    shared = dict(NATURAL_GAS)
    shared["Fuel Type"] = "Shared Fuel"
    other = dict(shared)
    other["Category"] = "Other Gas"
    sheets = [
        {
            "publisher": "EPA",
            "dataset_code": "fuel_epa_2",
            "version_label": "imported_from_sheet",
            "rows": [shared],
        },
        {
            "publisher": "EPA",
            "dataset_code": "fuel_epa_2b",
            "version_label": "imported_from_sheet",
            "rows": [other],
        },
    ]
    activity = _legacy(
        raw={
            "fuel": "Shared Fuel",
            "emission_framework": "epa",
            "emissions": 5306,
        }
    )
    finding = reconcile(activities=[activity], sheets=sheets)[0]
    assert finding.classification == REVIEW
    assert "not unique" in finding.reason
    assert finding.corrected_total_tco2e == ""


def test_duplicate_gas_rows_require_review_and_are_not_applied():
    first = _legacy()
    second = _legacy(id=DUPLICATE_ID)
    findings = reconcile(activities=[first, second], sheets=SHEETS)
    assert {item.classification for item in findings} == {REVIEW}
    assert all(item.counts_in_corrected_total == "false" for item in findings)
    store = MemoryCorrectionStore()
    with pytest.raises(ApplyRejected):
        _apply([first, second], [CO2_ID, DUPLICATE_ID], store)
    assert store.rows == []
    assert first["emissions_tco2e"] == 5306


def test_distinct_gas_lines_count_the_corrected_total_once():
    rows = [
        _legacy(),
        _legacy(
            id=CH4_ID,
            unit="CH4 (g CH4 / mmBtu)",
            emissions_tco2e=0.1,
            raw={
                "fuel": "Natural Gas",
                "emission_framework": "epa",
                "emissions": 0.1,
            },
        ),
        _legacy(
            id=N2O_ID,
            unit="N2O (g N2O / mmBtu)",
            emissions_tco2e=0.01,
            raw={
                "fuel": "Natural Gas",
                "emission_framework": "epa",
                "emissions": 0.01,
            },
        ),
    ]
    findings = reconcile(activities=rows, sheets=SHEETS)
    counted = [item for item in findings if item.counts_in_corrected_total == "true"]
    assert len(counted) == 1
    assert counted[0].record_id == CO2_ID
    assert counted[0].corrected_total_tco2e == "5.31145"
    assert {item.classification for item in findings} == {ELIGIBLE}
    store = MemoryCorrectionStore()
    with pytest.raises(ApplyRejected, match="incomplete"):
        _apply(rows, [CO2_ID], store)
    assert store.rows == []
    result = _apply(rows, [CO2_ID, CH4_ID, N2O_ID], store)
    assert result.inserted == 1
    assert store.rows[0]["member_activity_ids"] == sorted([CO2_ID, CH4_ID, N2O_ID])
    assert rows[0]["emissions_tco2e"] == 5306


def test_missing_quantity_is_not_rewritten_and_portfolio_rows_stay_unchanged():
    missing = _legacy(quantity=None, raw={"fuel": "Natural Gas", "emission_framework": "epa"})
    unknown = {
        "id": "70000000-0000-0000-0000-000000000008",
        "legacy_source": "scope1_fuel_entries",
        "method": "activity_data",
        "raw": {"emission_framework": "epa", "fuel": "Natural Gas"},
    }
    company = {
        "id": COMPANY_ID,
        "counterparty_id": COUNTERPARTY,
        "notes": "Calculated using EPA emission calculator version",
        "scope1_emissions": 5311.45,
        "scope2_emissions": 0,
        "scope3_emissions": 0,
    }
    questionnaire = {
        "id": QUESTIONNAIRE_ID,
        "counterparty_id": COUNTERPARTY,
        "scope1_emissions": 12,
        "scope2_emissions": 0,
        "scope3_emissions": 0,
    }
    findings = reconcile(
        activities=[missing, unknown],
        company_rows=[company],
        questionnaires=[questionnaire],
        sheets=SHEETS,
    )
    by_id = {item.record_id: item for item in findings}
    assert by_id[CO2_ID].classification == REVIEW
    assert by_id["70000000-0000-0000-0000-000000000008"].classification == INSUFFICIENT
    assert by_id[COMPANY_ID].classification == REVIEW
    assert by_id[COMPANY_ID].corrected_total_tco2e == ""
    assert by_id[QUESTIONNAIRE_ID].classification == INSUFFICIENT
    store = MemoryCorrectionStore()
    with pytest.raises(ApplyRejected):
        _apply(
            [missing],
            [QUESTIONNAIRE_ID],
            store,
            company_rows=[company],
            questionnaires=[questionnaire],
        )
    assert store.rows == []


def test_matching_stationary_record_has_no_identified_issue():
    activity = {
        "id": CO2_ID,
        "method": "epa_stationary",
        "legacy_source": "epa_stationary",
        "category": "stationary_combustion",
        "quantity": "100",
        "unit": "mmBtu",
        "emissions_tco2e": "5.31145",
        "raw": {
            "calc": "epa_stationary",
            "inputs": {
                "fuel": "Natural Gas",
                "fuel_category": "Natural Gas",
                "quantity": "100",
                "unit": "mmBtu",
            },
        },
    }
    finding = reconcile(activities=[activity], sheets=SHEETS)[0]
    assert finding.classification == NO_ISSUE
    assert finding.difference == "0"


def test_insert_failure_rolls_back_and_rerun_is_idempotent_until_revert():
    activity = _legacy()
    store = MemoryCorrectionStore(fail_on_insert=1)
    with pytest.raises(RuntimeError, match="forced correction insert failure"):
        _apply([activity], [CO2_ID], store)
    assert store.rows == []
    assert store.in_transaction is False
    assert activity["emissions_tco2e"] == 5306

    store.fail_on_insert = None
    first = _apply([activity], [CO2_ID], store)
    assert first.inserted == 1
    second = _apply([activity], [CO2_ID], store)
    assert second.inserted == 0
    assert second.skipped == 1
    assert len(store.rows) == 1

    active = [row for row in store.rows if row["status"] == "applied"]
    report = reconcile(activities=[activity], sheets=SHEETS, active_corrections=active)
    assert report[0].classification == NO_ISSUE

    store.fail_on_revert = True
    with pytest.raises(RuntimeError, match="forced correction revert failure"):
        revert_batch(store, first.batch_id, APPROVAL_TOKEN)
    assert store.rows[0]["status"] == "applied"

    store.fail_on_revert = False
    reverted = revert_batch(store, first.batch_id, APPROVAL_TOKEN)
    assert reverted == 1
    assert store.rows[0]["status"] == "reverted"
    third = _apply([activity], [CO2_ID], store)
    assert third.inserted == 1
    assert len(store.rows) == 2
    assert activity["emissions_tco2e"] == 5306
    with pytest.raises(ApplyRejected):
        revert_batch(store, first.batch_id, APPROVAL_TOKEN)


def test_sql_apply_rolls_back_without_touching_source_tables():
    class FakeTx:
        def __init__(self, conn):
            self.conn = conn

        def commit(self):
            self.conn.committed = True

        def rollback(self):
            self.conn.rolled_back = True

    class FakeConn:
        def __init__(self):
            self.committed = False
            self.rolled_back = False
            self.statements = []

        def begin(self):
            return FakeTx(self)

        def execute(self, statement, params=None):
            sql = str(statement)
            self.statements.append(sql)
            if "INSERT" in sql:
                raise RuntimeError("db down")

            class Result:
                rowcount = 0

                def mappings(self):
                    return []

            return Result()

    connection = FakeConn()
    with pytest.raises(RuntimeError, match="db down"):
        _apply([_legacy()], [CO2_ID], SqlCorrectionStore(connection))
    assert connection.rolled_back is True
    assert connection.committed is False
    written = "\n".join(connection.statements)
    assert "app.emission_activity_corrections" in written
    assert "company_emissions" not in written
    assert "counterparty_questionnaires" not in written
    assert "UPDATE app.emission_activities" not in INSERT_CORRECTION_SQL
    assert "company_emissions" not in REVERT_CORRECTION_SQL


def test_apply_command_does_not_open_a_database_without_approval():
    with pytest.raises(SystemExit) as caught:
        main(["--apply"])
    assert caught.value.code == 2
