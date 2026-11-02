"""Isolated tests for financing_instance_id persistence / upsert semantics.

Uses an in-memory fake store — does not touch production Postgres.
"""

from __future__ import annotations

import threading
import uuid
from decimal import Decimal
from typing import Any, Dict, List, Optional

import pytest

from fastapi_app.financing_instance import (
    AGGREGATE_FORMULA_ID,
    FINANCING_INSTANCE_FIELD,
    can_upsert_by_instance,
    ensure_identity_in_results,
    extract_financing_instance_id,
    is_aggregate_formula,
    normalize_financing_instance_id,
    preserve_financing_instance_in_inputs,
    uniqueness_key,
)


# ---------------------------------------------------------------------------
# Pure helper coverage
# ---------------------------------------------------------------------------


def test_accepts_and_preserves_instance_id_in_inputs():
    raw = {
        "outstanding_amount": 1_000_000,
        FINANCING_INSTANCE_FIELD: "  loan-a-uuid  ",
        "extra_unknown": {"nested": True},
    }
    preserved = preserve_financing_instance_in_inputs(raw)
    assert preserved[FINANCING_INSTANCE_FIELD] == "loan-a-uuid"
    assert preserved["extra_unknown"] == {"nested": True}
    assert preserved["outstanding_amount"] == 1_000_000


def test_unknown_input_fields_are_not_stripped():
    inputs = preserve_financing_instance_in_inputs(
        {
            FINANCING_INSTANCE_FIELD: "id-1",
            "custom_spa_field": 42,
            "verified_emissions": 10,
        }
    )
    assert set(inputs) >= {
        FINANCING_INSTANCE_FIELD,
        "custom_spa_field",
        "verified_emissions",
    }


def test_missing_financing_instance_id_does_not_invent():
    out = preserve_financing_instance_in_inputs({"outstanding_amount": 5})
    assert FINANCING_INSTANCE_FIELD not in out
    assert extract_financing_instance_id(out) is None
    assert normalize_financing_instance_id("") is None
    assert normalize_financing_instance_id(None) is None


def test_extract_from_identity_step():
    payload = {
        "calculation_steps": [
            {
                "step": "__financing_identity__",
                FINANCING_INSTANCE_FIELD: "from-step",
            }
        ]
    }
    assert extract_financing_instance_id(payload) == "from-step"


def test_results_mirror_identity_step():
    results = ensure_identity_in_results(
        {"calculation_steps": [{"step": "math", "value": 1}]}, "inst-9"
    )
    assert results["metadata"][FINANCING_INSTANCE_FIELD] == "inst-9"
    assert results["calculation_steps"][0]["step"] == "__financing_identity__"
    assert results["calculation_steps"][0][FINANCING_INSTANCE_FIELD] == "inst-9"
    assert results["calculation_steps"][1]["step"] == "math"


def test_aggregate_excluded_from_upsert_rule():
    assert is_aggregate_formula(AGGREGATE_FORMULA_ID) is True
    assert is_aggregate_formula("Aggregate") is True
    assert is_aggregate_formula(" AGGREGATE ") is True
    assert can_upsert_by_instance(
        formula_id="aggregate", financing_instance_id="x"
    ) is False
    assert can_upsert_by_instance(
        formula_id="Aggregate", financing_instance_id="x"
    ) is False
    assert can_upsert_by_instance(
        formula_id="1a-business-loans", financing_instance_id=None
    ) is False
    assert can_upsert_by_instance(
        formula_id="1a-business-loans", financing_instance_id="x"
    ) is True


def test_instance_id_btrim_matches_index_normalization():
    assert normalize_financing_instance_id("  loan-1  ") == "loan-1"
    assert uniqueness_key(
        organization_id=uuid.uuid4(),
        counterparty_id=None,
        calc_kind="finance",
        financing_instance_id="  loan-1  ",
    )[3] == "loan-1"
    preserved = preserve_financing_instance_in_inputs(
        {FINANCING_INSTANCE_FIELD: "  loan-1  "}
    )
    assert preserved[FINANCING_INSTANCE_FIELD] == "loan-1"


# ---------------------------------------------------------------------------
# In-memory persistence simulator (mirrors router upsert rules)
# ---------------------------------------------------------------------------


class _Row:
    def __init__(self, **kwargs: Any):
        self.id = kwargs.pop("id", uuid.uuid4())
        for k, v in kwargs.items():
            setattr(self, k, v)


class FakeFinancedStore:
    """Thread-safe stand-in for app.financed_emissions upsert behavior."""

    def __init__(self) -> None:
        self.rows: List[_Row] = []
        self._lock = threading.Lock()

    def _match(
        self,
        *,
        organization_id: uuid.UUID,
        counterparty_id: Optional[uuid.UUID],
        calc_kind: str,
        instance_id: str,
    ) -> Optional[_Row]:
        for row in self.rows:
            if row.organization_id != organization_id:
                continue
            if row.calc_kind != calc_kind:
                continue
            if row.counterparty_id != counterparty_id:
                continue
            if is_aggregate_formula(row.formula_id):
                continue
            rid = extract_financing_instance_id(row.inputs)
            if rid == instance_id:
                return row
        return None

    def persist(
        self,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        calc_kind: str,
        formula_id: str,
        counterparty_id: Optional[uuid.UUID],
        inputs: Dict[str, Any],
        results: Optional[Dict[str, Any]] = None,
        financed_emissions: Optional[Decimal] = None,
        exposure_id: Optional[uuid.UUID] = None,
        status: str = "completed",
    ) -> _Row:
        inputs = preserve_financing_instance_in_inputs(inputs)
        instance_id = extract_financing_instance_id(inputs)
        results = ensure_identity_in_results(results or {}, instance_id)
        with self._lock:
            if can_upsert_by_instance(
                formula_id=formula_id, financing_instance_id=instance_id
            ):
                assert instance_id is not None
                existing = self._match(
                    organization_id=organization_id,
                    counterparty_id=counterparty_id,
                    calc_kind=calc_kind,
                    instance_id=instance_id,
                )
                if existing is not None:
                    existing.user_id = user_id
                    existing.formula_id = formula_id
                    existing.inputs = inputs
                    existing.results = results
                    existing.financed_emissions = financed_emissions
                    existing.exposure_id = exposure_id
                    existing.status = status
                    return existing
            row = _Row(
                organization_id=organization_id,
                user_id=user_id,
                counterparty_id=counterparty_id,
                exposure_id=exposure_id,
                calc_kind=calc_kind,
                formula_id=formula_id,
                inputs=inputs,
                results=results,
                financed_emissions=financed_emissions,
                status=status,
            )
            self.rows.append(row)
            return row

    def patch(self, row_id: uuid.UUID, **fields: Any) -> _Row:
        with self._lock:
            row = next(r for r in self.rows if r.id == row_id)
            if "inputs" in fields:
                fields["inputs"] = preserve_financing_instance_in_inputs(
                    fields["inputs"]
                )
                inst = extract_financing_instance_id(fields["inputs"])
                if "results" in fields:
                    fields["results"] = ensure_identity_in_results(
                        fields["results"], inst
                    )
            for k, v in fields.items():
                setattr(row, k, v)
            return row


@pytest.fixture
def store() -> FakeFinancedStore:
    return FakeFinancedStore()


@pytest.fixture
def org_ids():
    return {
        "org": uuid.uuid4(),
        "user": uuid.uuid4(),
        "cp": uuid.uuid4(),
    }


def test_two_business_loans_same_formula_distinct_instances(store, org_ids):
    a = store.persist(
        organization_id=org_ids["org"],
        user_id=org_ids["user"],
        calc_kind="finance",
        formula_id="1a-business-loans",
        counterparty_id=org_ids["cp"],
        inputs={
            FINANCING_INSTANCE_FIELD: "loan-1",
            "outstanding_amount": 100,
        },
        financed_emissions=Decimal("1.0"),
    )
    b = store.persist(
        organization_id=org_ids["org"],
        user_id=org_ids["user"],
        calc_kind="finance",
        formula_id="1a-business-loans",
        counterparty_id=org_ids["cp"],
        inputs={
            FINANCING_INSTANCE_FIELD: "loan-2",
            "outstanding_amount": 200,
        },
        financed_emissions=Decimal("2.0"),
    )
    assert a.id != b.id
    assert len(store.rows) == 2
    assert a.inputs[FINANCING_INSTANCE_FIELD] == "loan-1"
    assert b.inputs[FINANCING_INSTANCE_FIELD] == "loan-2"


def test_two_mortgages_distinct_instances(store, org_ids):
    m1 = store.persist(
        organization_id=org_ids["org"],
        user_id=org_ids["user"],
        calc_kind="finance",
        formula_id="1a-mortgage",
        counterparty_id=org_ids["cp"],
        inputs={FINANCING_INSTANCE_FIELD: "mort-1"},
        financed_emissions=Decimal("3"),
    )
    m2 = store.persist(
        organization_id=org_ids["org"],
        user_id=org_ids["user"],
        calc_kind="finance",
        formula_id="1a-mortgage",
        counterparty_id=org_ids["cp"],
        inputs={FINANCING_INSTANCE_FIELD: "mort-2"},
        financed_emissions=Decimal("4"),
    )
    assert {m1.id, m2.id} == {r.id for r in store.rows}
    assert len(store.rows) == 2


def test_recalculation_updates_only_that_loan(store, org_ids):
    first = store.persist(
        organization_id=org_ids["org"],
        user_id=org_ids["user"],
        calc_kind="finance",
        formula_id="1a-business-loans",
        counterparty_id=org_ids["cp"],
        inputs={FINANCING_INSTANCE_FIELD: "loan-1", "outstanding_amount": 100},
        financed_emissions=Decimal("1"),
    )
    sibling = store.persist(
        organization_id=org_ids["org"],
        user_id=org_ids["user"],
        calc_kind="finance",
        formula_id="1a-business-loans",
        counterparty_id=org_ids["cp"],
        inputs={FINANCING_INSTANCE_FIELD: "loan-2", "outstanding_amount": 200},
        financed_emissions=Decimal("2"),
    )
    updated = store.persist(
        organization_id=org_ids["org"],
        user_id=org_ids["user"],
        calc_kind="finance",
        formula_id="1a-business-loans",
        counterparty_id=org_ids["cp"],
        inputs={FINANCING_INSTANCE_FIELD: "loan-1", "outstanding_amount": 150},
        financed_emissions=Decimal("1.5"),
    )
    assert updated.id == first.id
    assert len(store.rows) == 2
    assert sibling.financed_emissions == Decimal("2")
    assert updated.financed_emissions == Decimal("1.5")
    assert updated.inputs["outstanding_amount"] == 150


def test_patch_one_loan_does_not_modify_sibling(store, org_ids):
    a = store.persist(
        organization_id=org_ids["org"],
        user_id=org_ids["user"],
        calc_kind="finance",
        formula_id="1a-mortgage",
        counterparty_id=org_ids["cp"],
        inputs={FINANCING_INSTANCE_FIELD: "m-a"},
        financed_emissions=Decimal("10"),
    )
    b = store.persist(
        organization_id=org_ids["org"],
        user_id=org_ids["user"],
        calc_kind="finance",
        formula_id="1a-mortgage",
        counterparty_id=org_ids["cp"],
        inputs={FINANCING_INSTANCE_FIELD: "m-b"},
        financed_emissions=Decimal("20"),
    )
    store.patch(
        a.id,
        inputs={FINANCING_INSTANCE_FIELD: "m-a", "note": "recalc"},
        financed_emissions=Decimal("11"),
    )
    assert a.financed_emissions == Decimal("11")
    assert b.financed_emissions == Decimal("20")
    assert b.inputs[FINANCING_INSTANCE_FIELD] == "m-b"


def test_missing_instance_id_always_inserts(store, org_ids):
    r1 = store.persist(
        organization_id=org_ids["org"],
        user_id=org_ids["user"],
        calc_kind="finance",
        formula_id="1a-business-loans",
        counterparty_id=org_ids["cp"],
        inputs={"outstanding_amount": 1},
        financed_emissions=Decimal("1"),
    )
    r2 = store.persist(
        organization_id=org_ids["org"],
        user_id=org_ids["user"],
        calc_kind="finance",
        formula_id="1a-business-loans",
        counterparty_id=org_ids["cp"],
        inputs={"outstanding_amount": 2},
        financed_emissions=Decimal("2"),
    )
    assert r1.id != r2.id
    assert len(store.rows) == 2


def test_aggregate_rows_remain_separate(store, org_ids):
    loan = store.persist(
        organization_id=org_ids["org"],
        user_id=org_ids["user"],
        calc_kind="finance",
        formula_id="1a-mortgage",
        counterparty_id=org_ids["cp"],
        inputs={FINANCING_INSTANCE_FIELD: "m-1"},
        financed_emissions=Decimal("5"),
    )
    agg1 = store.persist(
        organization_id=org_ids["org"],
        user_id=org_ids["user"],
        calc_kind="finance",
        formula_id="aggregate",
        counterparty_id=org_ids["cp"],
        inputs={FINANCING_INSTANCE_FIELD: "m-1"},  # even if present, no upsert
        financed_emissions=Decimal("50"),
    )
    agg2 = store.persist(
        organization_id=org_ids["org"],
        user_id=org_ids["user"],
        calc_kind="finance",
        formula_id="aggregate",
        counterparty_id=org_ids["cp"],
        inputs={},
        financed_emissions=Decimal("60"),
    )
    assert len(store.rows) == 3
    assert {loan.id, agg1.id, agg2.id} == {r.id for r in store.rows}


def test_save_then_get_reload_preserves_instance_id(store, org_ids):
    saved = store.persist(
        organization_id=org_ids["org"],
        user_id=org_ids["user"],
        calc_kind="finance",
        formula_id="1a-business-loans",
        counterparty_id=org_ids["cp"],
        inputs={
            FINANCING_INSTANCE_FIELD: "reload-me",
            "verified_emissions": 12,
        },
        financed_emissions=Decimal("9"),
    )
    reloaded = next(r for r in store.rows if r.id == saved.id)
    assert reloaded.inputs[FINANCING_INSTANCE_FIELD] == "reload-me"
    assert reloaded.results["metadata"][FINANCING_INSTANCE_FIELD] == "reload-me"
    assert extract_financing_instance_id(reloaded.results) == "reload-me"


def test_legacy_rows_without_instance_ids_untouched(store, org_ids):
    legacy = store.persist(
        organization_id=org_ids["org"],
        user_id=org_ids["user"],
        calc_kind="finance",
        formula_id="1a-business-loans",
        counterparty_id=org_ids["cp"],
        inputs={"outstanding_amount": 999},
        financed_emissions=Decimal("9"),
    )
    store.persist(
        organization_id=org_ids["org"],
        user_id=org_ids["user"],
        calc_kind="finance",
        formula_id="1a-business-loans",
        counterparty_id=org_ids["cp"],
        inputs={FINANCING_INSTANCE_FIELD: "new-loan"},
        financed_emissions=Decimal("1"),
    )
    assert FINANCING_INSTANCE_FIELD not in legacy.inputs
    assert len(store.rows) == 2


def test_concurrent_saves_same_instance_do_not_duplicate(store, org_ids):
    errors: List[BaseException] = []
    results: List[_Row] = []

    def worker():
        try:
            row = store.persist(
                organization_id=org_ids["org"],
                user_id=org_ids["user"],
                calc_kind="finance",
                formula_id="1a-business-loans",
                counterparty_id=org_ids["cp"],
                inputs={
                    FINANCING_INSTANCE_FIELD: "concurrent-1",
                    "outstanding_amount": 10,
                },
                financed_emissions=Decimal("1"),
            )
            results.append(row)
        except BaseException as exc:  # noqa: BLE001 — collect for assertion
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert len(store.rows) == 1
    assert len({r.id for r in results}) == 1
    assert store.rows[0].inputs[FINANCING_INSTANCE_FIELD] == "concurrent-1"


def test_uniqueness_key_matches_frontend_contract(org_ids):
    key = uniqueness_key(
        organization_id=org_ids["org"],
        counterparty_id=org_ids["cp"],
        calc_kind="finance",
        financing_instance_id="abc",
    )
    assert key == (org_ids["org"], org_ids["cp"], "finance", "abc")


def test_exposure_id_is_not_treated_as_instance_id(store, org_ids):
    exposure = uuid.uuid4()
    row = store.persist(
        organization_id=org_ids["org"],
        user_id=org_ids["user"],
        calc_kind="finance",
        formula_id="1a-business-loans",
        counterparty_id=org_ids["cp"],
        exposure_id=exposure,
        inputs={FINANCING_INSTANCE_FIELD: "inst-not-exposure"},
        financed_emissions=Decimal("1"),
    )
    assert row.exposure_id == exposure
    assert row.inputs[FINANCING_INSTANCE_FIELD] == "inst-not-exposure"
    assert str(row.exposure_id) != row.inputs[FINANCING_INSTANCE_FIELD]
