"""Isolated PostgreSQL tests for the emission-factor library. Never uses production."""

from __future__ import annotations

import time
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from fastapi_app.factor_library_models import FactorLibraryAudit, FactorLibraryEntry
from tests.pg_isolated import (
    bootstrap_factor_library,
    is_isolated_url,
    is_production_url,
    make_engine,
    make_session,
    start_isolated_postgres,
)


def _wait_ready(url: str, attempts: int = 10) -> None:
    last_error = None
    for _ in range(attempts):
        try:
            engine = make_engine(url)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            engine.dispose()
            return
        except Exception as exc:
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"Isolated Postgres did not become ready: {last_error}")


@pytest.fixture(scope="session")
def library_engine():
    try:
        url, stop = start_isolated_postgres()
    except Exception as exc:
        pytest.skip(f"Isolated PostgreSQL is unavailable ({exc})")
        return
    if is_production_url(url) or not is_isolated_url(url):
        pytest.fail("Refusing production or non-isolated DATABASE_URL")
    try:
        _wait_ready(url)
        engine = make_engine(url)
        bootstrap_factor_library(engine)
        yield engine
        engine.dispose()
    finally:
        stop()


@pytest.fixture
def library_session(library_engine):
    session = make_session(library_engine)
    try:
        yield session
        session.rollback()
    finally:
        session.close()
        with library_engine.begin() as conn:
            conn.execute(
                text(
                    "TRUNCATE TABLE ref.factor_library_audit, ref.factor_library_entries "
                    "RESTART IDENTITY CASCADE"
                )
            )


def _approved(**overrides) -> FactorLibraryEntry:
    payload = dict(
        id=uuid.uuid4(),
        publication_id=uuid.uuid4(),
        category="purchased_electricity",
        library_class="physical",
        country_code="GB",
        geography="United Kingdom",
        sector_or_activity="electricity",
        activity_key="electricity",
        factor_value=Decimal("0.13096000"),
        numerator_unit="kg CO2e",
        denominator_unit="kWh",
        unit="kg CO2e/kWh",
        applicable_year=2026,
        publication_year=2026,
        gas="CO2e",
        source_organization="UK DESNZ",
        status="approved",
    )
    payload.update(overrides)
    return FactorLibraryEntry(**payload)


def test_0018_tables_and_trigger_exist(library_engine):
    with library_engine.connect() as conn:
        tables = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'ref' AND table_name IN "
                "('factor_library_entries', 'factor_library_audit')"
            )
        ).scalars().all()
        assert "factor_library_entries" in tables
        assert "factor_library_audit" in tables
        trigger = conn.execute(
            text(
                "SELECT tgname FROM pg_trigger "
                "WHERE tgrelid = 'ref.factor_library_entries'::regclass "
                "AND tgname = 'trg_factor_library_protect_approved'"
            )
        ).scalar()
        assert trigger == "trg_factor_library_protect_approved"


def test_approved_factor_value_cannot_be_overwritten(library_session):
    row = _approved(activity_key="electricity-overwrite")
    library_session.add(row)
    library_session.commit()
    row.factor_value = Decimal("0.99999000")
    with pytest.raises(Exception) as exc:
        library_session.commit()
    library_session.rollback()
    assert "immutable" in str(exc.value).lower()
    stored = library_session.get(FactorLibraryEntry, row.id)
    assert stored is not None
    assert stored.factor_value == Decimal("0.13096000")


def test_approved_factor_cannot_be_deleted(library_session):
    row = _approved(activity_key="electricity-delete")
    library_session.add(row)
    library_session.commit()
    library_session.delete(row)
    with pytest.raises(Exception) as exc:
        library_session.commit()
    library_session.rollback()
    assert "cannot be deleted" in str(exc.value).lower()


def test_duplicate_approved_identity_is_rejected(library_session):
    library_session.add(_approved(activity_key="electricity-dup"))
    library_session.commit()
    library_session.add(_approved(activity_key="electricity-dup"))
    with pytest.raises(IntegrityError):
        library_session.commit()
    library_session.rollback()


def test_revision_is_a_new_publication(library_session):
    original = _approved(activity_key="electricity-revision")
    library_session.add(original)
    library_session.commit()
    original.status = "retired"
    library_session.commit()
    revision = _approved(
        activity_key="electricity-revision",
        supersedes_id=original.id,
        factor_value=Decimal("0.13100000"),
        publication_id=uuid.uuid4(),
    )
    library_session.add(revision)
    library_session.commit()
    stored_old = library_session.get(FactorLibraryEntry, original.id)
    stored_new = library_session.get(FactorLibraryEntry, revision.id)
    assert stored_old.factor_value == Decimal("0.13096000")
    assert stored_new.factor_value == Decimal("0.13100000")
    assert stored_new.supersedes_id == original.id


def test_org_scoped_pending_row_and_audit(library_session):
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    pending = _approved(
        activity_key="electricity-pending",
        status="pending_review",
        organization_id=org_id,
        submitted_by=user_id,
    )
    library_session.add(pending)
    library_session.flush()
    library_session.add(
        FactorLibraryAudit(
            id=uuid.uuid4(),
            entry_id=pending.id,
            action="submit",
            actor_user_id=user_id,
            organization_id=org_id,
            payload={"rationale": "documented source"},
        )
    )
    library_session.commit()
    rows = library_session.query(FactorLibraryEntry).filter_by(organization_id=org_id).all()
    assert len(rows) == 1
    assert rows[0].status == "pending_review"
    audits = library_session.query(FactorLibraryAudit).filter_by(entry_id=pending.id).all()
    assert audits[0].action == "submit"
