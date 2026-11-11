"""
Phase 6B.1 isolated PostgreSQL verification for SSP drafts.

Never uses production DATABASE_URL / the EC2 rethinkcarbon host.
Applies prepared migration 0020 only to the disposable database.
Does not apply 0019 (not a dependency of 0020).
"""

from __future__ import annotations

import time
import uuid

import pytest
from sqlalchemy import text

from tests.pg_isolated import (
    MIGRATION_0019,
    MIGRATION_0020,
    bootstrap_ssp_schema,
    is_isolated_url,
    is_production_url,
    make_engine,
    make_session,
    start_isolated_postgres,
)
from tests.test_ssp_drafts import (
    COL_1,
    COL_2,
    COUNTERPARTY_ID,
    INSTANCE_A,
    INSTANCE_B,
    LOAN_1,
    LOAN_2,
    ORG_ID,
    OTHER_ORG_ID,
    POOL_1,
    TRANCHE_1,
    USER_ID,
    _client,
    _draft,
    _put,
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
def isolated_engine():
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
        bootstrap_ssp_schema(engine)
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO public.organizations (id, name) VALUES (:id, 'org-a') "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                {"id": str(ORG_ID)},
            )
            conn.execute(
                text(
                    "INSERT INTO public.organizations (id, name) VALUES (:id, 'org-b') "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                {"id": str(OTHER_ORG_ID)},
            )
            conn.execute(
                text(
                    "INSERT INTO public.counterparties (id, organization_id, name) "
                    "VALUES (:id, :org, 'cp') ON CONFLICT (id) DO NOTHING"
                ),
                {"id": str(COUNTERPARTY_ID), "org": str(ORG_ID)},
            )
        yield engine
        engine.dispose()
    finally:
        stop()


@pytest.fixture
def postgres_session(isolated_engine):
    session = make_session(isolated_engine)
    try:
        yield session
        session.rollback()
    finally:
        session.close()
        with isolated_engine.begin() as conn:
            for table in (
                "app.ssp_calculations",
                "app.ssp_tranche_pools",
                "app.ssp_pool_of_pools_members",
                "app.ssp_pool_loans",
                "app.ssp_loan_collateral",
                "app.ssp_tranches",
                "app.ssp_pool_of_pools",
                "app.ssp_pools",
                "app.ssp_loans",
                "app.ssp_collateral",
                "app.ssp_holdings",
                "app.ssp_deals",
                "app.financed_emissions",
            ):
                conn.execute(text(f"TRUNCATE TABLE {table} CASCADE"))


def test_0020_sql_is_additive_and_does_not_touch_financed_emissions_data():
    script = MIGRATION_0020.read_text(encoding="utf-8")
    upper = " ".join(script.upper().split())
    assert "DELETE FROM" not in upper
    assert "DROP TABLE" not in upper
    assert "ALTER TABLE APP.FINANCED_EMISSIONS" not in upper
    assert "INSERT INTO APP.FINANCED_EMISSIONS" not in upper
    assert "0020_ssp_structures" in script
    # 0019 is independent — SSP DDL must not CREATE/ALTER overlap-review tables.
    assert "create table" in script.lower()
    assert "create table if not exists app.uop_overlap_reviews" not in script.lower()
    assert "from app.uop_overlap_reviews" not in script.lower()
    assert MIGRATION_0019.exists()


def test_0020_schema_constraints_indexes_triggers(isolated_engine):
    with isolated_engine.connect() as conn:
        tables = {
            row[0]
            for row in conn.execute(
                text(
                    """
                    SELECT table_name FROM information_schema.tables
                    WHERE table_schema = 'app' AND table_name LIKE 'ssp_%'
                    """
                )
            )
        }
        expected = {
            "ssp_deals",
            "ssp_holdings",
            "ssp_collateral",
            "ssp_loans",
            "ssp_loan_collateral",
            "ssp_pools",
            "ssp_pool_loans",
            "ssp_pool_of_pools",
            "ssp_pool_of_pools_members",
            "ssp_tranches",
            "ssp_tranche_pools",
            "ssp_calculations",
        }
        assert expected.issubset(tables)

        indexes = {
            row[0]
            for row in conn.execute(
                text(
                    """
                    SELECT indexname FROM pg_indexes
                    WHERE schemaname = 'app' AND tablename LIKE 'ssp_%'
                    """
                )
            )
        }
        assert "uq_ssp_holdings_financing_instance" in indexes
        assert "uq_ssp_collateral_deal_asset" in indexes
        assert "uq_ssp_loans_deal_loan" in indexes

        checks = {
            row[0]
            for row in conn.execute(
                text(
                    """
                    SELECT conname FROM pg_constraint
                    WHERE conrelid = 'app.ssp_holdings'::regclass AND contype = 'c'
                    """
                )
            )
        }
        assert "ssp_holdings_not_reportable_chk" in checks
        assert "ssp_holdings_not_portfolio_chk" in checks

        calc_checks = {
            row[0]
            for row in conn.execute(
                text(
                    """
                    SELECT conname FROM pg_constraint
                    WHERE conrelid = 'app.ssp_calculations'::regclass AND contype = 'c'
                    """
                )
            )
        }
        assert "ssp_calculations_not_reportable_chk" in calc_checks

        triggers = {
            row[0]
            for row in conn.execute(
                text(
                    """
                    SELECT tgname FROM pg_trigger
                    WHERE tgrelid::regclass::text LIKE 'app.ssp_%'
                      AND NOT tgisinternal
                    """
                )
            )
        }
        assert "trg_ssp_holdings_org_match" in triggers
        assert "trg_ssp_collateral_org_match" in triggers
        assert "trg_ssp_pool_of_pools_org_match" in triggers
        # Phase 6B.2 — association tables enforce org match + deal-scoped FKs.
        assert "trg_ssp_loan_collateral_org_match" in triggers
        assert "trg_ssp_pool_loans_org_match" in triggers
        assert "trg_ssp_pop_members_org_match" in triggers
        assert "trg_ssp_tranche_pools_org_match" in triggers

        fk_names = {
            row[0]
            for row in conn.execute(
                text(
                    """
                    SELECT conname FROM pg_constraint
                    WHERE contype = 'f'
                      AND conrelid::regclass::text LIKE 'app.ssp_%'
                    """
                )
            )
        }
        assert "fk_ssp_loan_collateral_loan_deal" in fk_names
        assert "fk_ssp_loan_collateral_collateral_deal" in fk_names
        assert "fk_ssp_pool_loans_pool_deal" in fk_names
        assert "fk_ssp_pool_loans_loan_deal" in fk_names
        assert "fk_ssp_pop_members_pop_deal" in fk_names
        assert "fk_ssp_tranche_pools_tranche_deal" in fk_names

        versions = {
            row[0]
            for row in conn.execute(text("SELECT version FROM public.schema_migrations"))
        }
        assert "0020_ssp_structures" in versions
        assert "0019_uop_overlap_reviews" not in versions


def test_postgres_create_reload_update_delete(postgres_session, isolated_engine):
    client = _client(postgres_session)
    created = _put(client)
    assert created.status_code in (200, 201), created.text
    body = created.json()
    holding_id = body["holding"]["id"]
    assert body["holding"]["is_reportable"] is False
    assert body["deal"]["reporting_year"] == "2024"
    assert len(body["collateral"]) == 2
    assert body["collateral"][0]["collateral_id"] != body["collateral"][1]["collateral_id"]

    reloaded = client.get(f"/api/v1/ssp/drafts/by-instance/{INSTANCE_A}")
    assert reloaded.status_code == 200
    assert reloaded.json()["holding"]["id"] == holding_id
    assert reloaded.json()["draft"]["deal"]["dealName"] == "RMBS 2024-1"
    assert set(c["collateralId"] for c in reloaded.json()["draft"]["collateral"]) == {COL_1, COL_2}

    updated = _put(
        client,
        INSTANCE_A,
        update_shared=True,
        expected_deal_updated_at=body["deal"]["updated_at"],
        expected_holding_updated_at=body["holding"]["updated_at"],
        draft=_draft(
            financingInstanceId=INSTANCE_A,
            deal={**_draft()["deal"], "dealName": "RMBS 2024-1 Updated"},
        ),
    )
    assert updated.status_code in (200, 201), updated.text
    assert updated.json()["deal"]["deal_name"] == "RMBS 2024-1 Updated"

    deleted = client.delete(f"/api/v1/ssp/drafts/{holding_id}")
    assert deleted.status_code == 200
    assert client.get(f"/api/v1/ssp/drafts/by-instance/{INSTANCE_A}").status_code == 404

    with isolated_engine.connect() as conn:
        deals = conn.execute(text("SELECT count(*) FROM app.ssp_deals")).scalar()
        holdings = conn.execute(text("SELECT count(*) FROM app.ssp_holdings")).scalar()
        fe = conn.execute(text("SELECT count(*) FROM app.financed_emissions")).scalar()
    assert deals == 0
    assert holdings == 0
    assert fe == 0


def test_postgres_multiple_holdings_and_independent_deals(postgres_session):
    client = _client(postgres_session)
    first = _put(client, INSTANCE_A)
    assert first.status_code in (200, 201), first.text
    deal_id = first.json()["deal"]["id"]

    second = _put(
        client,
        INSTANCE_B,
        deal_id=deal_id,
        update_shared=False,
        instance_key="securitization-structured-products#2",
        draft=_draft(
            financingInstanceId=INSTANCE_B,
            holdings=[
                {
                    "holdingId": "hold-2",
                    "name": "Second note",
                    "trancheId": TRANCHE_1,
                    "bankOutstandingInvestment": 15,
                    "currency": "PKR",
                    "evidence": {"source": "", "notes": "", "documentReference": ""},
                }
            ],
        ),
    )
    assert second.status_code in (200, 201), second.text
    assert second.json()["deal"]["id"] == deal_id
    assert second.json()["sibling_count"] >= 1

    third_instance = "cccccccc-cccc-1111-1111-cccccccccccc"
    independent = _put(
        client,
        third_instance,
        update_shared=True,
        instance_key="securitization-structured-products#3",
        draft=_draft(
            financingInstanceId=third_instance,
            deal={**_draft()["deal"], "dealName": "Independent CLO"},
        ),
    )
    assert independent.status_code in (200, 201), independent.text
    assert independent.json()["deal"]["id"] != deal_id

    listed = client.get("/api/v1/ssp/drafts", params={"counterparty_id": str(COUNTERPARTY_ID)})
    assert listed.status_code == 200
    assert len(listed.json()) == 3


def test_postgres_shared_deal_and_stale_holding_conflicts(postgres_session):
    client = _client(postgres_session)
    first = _put(client, INSTANCE_A)
    deal_id = first.json()["deal"]["id"]
    second = _put(
        client,
        INSTANCE_B,
        deal_id=deal_id,
        update_shared=False,
        draft=_draft(financingInstanceId=INSTANCE_B),
    )
    assert second.status_code in (200, 201), second.text

    conflict = _put(
        client,
        INSTANCE_B,
        deal_id=deal_id,
        update_shared=False,
        expected_holding_updated_at=second.json()["holding"]["updated_at"],
        draft=_draft(
            financingInstanceId=INSTANCE_B,
            deal={**_draft()["deal"], "dealName": "Would overwrite siblings"},
        ),
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "shared_deal_conflict"

    stale = _put(
        client,
        INSTANCE_B,
        deal_id=deal_id,
        update_shared=False,
        expected_holding_updated_at="2000-01-01T00:00:00+00:00",
        draft=_draft(
            financingInstanceId=INSTANCE_B,
            holdings=[
                {
                    "holdingId": "hold-2",
                    "name": "Renamed holding only",
                    "trancheId": TRANCHE_1,
                    "bankOutstandingInvestment": 16,
                    "currency": "PKR",
                    "evidence": {"source": "", "notes": "", "documentReference": ""},
                }
            ],
        ),
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "stale_holding"


def test_postgres_org_isolation_and_no_financed_emissions_writes(postgres_session, isolated_engine):
    client_a = _client(postgres_session, ORG_ID)
    assert _put(client_a, INSTANCE_A).status_code in (200, 201)

    client_b = _client(postgres_session, OTHER_ORG_ID)
    listed = client_b.get("/api/v1/ssp/drafts")
    assert listed.status_code == 200
    assert listed.json() == []

    blocked = client_a.post(
        "/api/v1/financed-emissions",
        json={
            "calc_kind": "finance",
            "formula_id": "ssp-lookthrough",
            "formula_name": "SSP",
            "inputs": {"financing_instance_id": INSTANCE_A},
            "results": {},
            "financed_emissions": 12,
            "status": "draft",
        },
    )
    assert blocked.status_code == 400

    with isolated_engine.connect() as conn:
        fe = conn.execute(text("SELECT count(*) FROM app.financed_emissions")).scalar()
        holdings = conn.execute(
            text("SELECT is_reportable, include_in_portfolio FROM app.ssp_holdings")
        ).fetchall()
    assert fe == 0
    assert holdings
    assert all(row[0] is False and row[1] is False for row in holdings)


def test_postgres_cascade_deletes_children(postgres_session, isolated_engine):
    client = _client(postgres_session)
    created = _put(client, INSTANCE_A)
    holding_id = created.json()["holding"]["id"]
    deal_id = created.json()["deal"]["id"]

    with isolated_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM app.ssp_collateral")).scalar() == 2
        assert conn.execute(text("SELECT count(*) FROM app.ssp_loans")).scalar() == 2
        assert conn.execute(text("SELECT count(*) FROM app.ssp_pools")).scalar() == 1
        assert conn.execute(text("SELECT count(*) FROM app.ssp_loan_collateral")).scalar() >= 2

    assert client.delete(f"/api/v1/ssp/drafts/{holding_id}").status_code == 200

    with isolated_engine.connect() as conn:
        assert conn.execute(
            text("SELECT count(*) FROM app.ssp_deals WHERE id = CAST(:id AS uuid)"),
            {"id": deal_id},
        ).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM app.ssp_collateral")).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM app.ssp_loan_collateral")).scalar() == 0


def _seed_two_deals(conn):
    """Two deals in the same org, each with one loan and one collateral."""
    deal_a = str(uuid.uuid4())
    deal_b = str(uuid.uuid4())
    loan_a = str(uuid.uuid4())
    loan_b = str(uuid.uuid4())
    col_a = str(uuid.uuid4())
    col_b = str(uuid.uuid4())
    pool_a = str(uuid.uuid4())
    pool_b = str(uuid.uuid4())
    tranche_a = str(uuid.uuid4())
    pop_a = str(uuid.uuid4())
    org = str(ORG_ID)
    user = str(USER_ID)
    for deal_id, name in ((deal_a, "Deal A"), (deal_b, "Deal B")):
        conn.execute(
            text(
                """
                INSERT INTO app.ssp_deals (id, organization_id, user_id, deal_name, status)
                VALUES (CAST(:id AS uuid), CAST(:org AS uuid), CAST(:user AS uuid), :name, 'draft')
                """
            ),
            {"id": deal_id, "org": org, "user": user, "name": name},
        )
    conn.execute(
        text(
            """
            INSERT INTO app.ssp_loans (id, organization_id, deal_id, loan_id, name)
            VALUES
              (CAST(:la AS uuid), CAST(:org AS uuid), CAST(:da AS uuid), 'L-A', 'Loan A'),
              (CAST(:lb AS uuid), CAST(:org AS uuid), CAST(:db AS uuid), 'L-B', 'Loan B')
            """
        ),
        {"la": loan_a, "lb": loan_b, "org": org, "da": deal_a, "db": deal_b},
    )
    conn.execute(
        text(
            """
            INSERT INTO app.ssp_collateral (id, organization_id, deal_id, collateral_id, name)
            VALUES
              (CAST(:ca AS uuid), CAST(:org AS uuid), CAST(:da AS uuid), 'C-A', 'Col A'),
              (CAST(:cb AS uuid), CAST(:org AS uuid), CAST(:db AS uuid), 'C-B', 'Col B')
            """
        ),
        {"ca": col_a, "cb": col_b, "org": org, "da": deal_a, "db": deal_b},
    )
    conn.execute(
        text(
            """
            INSERT INTO app.ssp_pools (id, organization_id, deal_id, pool_id, name)
            VALUES
              (CAST(:pa AS uuid), CAST(:org AS uuid), CAST(:da AS uuid), 'P-A', 'Pool A'),
              (CAST(:pb AS uuid), CAST(:org AS uuid), CAST(:db AS uuid), 'P-B', 'Pool B')
            """
        ),
        {"pa": pool_a, "pb": pool_b, "org": org, "da": deal_a, "db": deal_b},
    )
    conn.execute(
        text(
            """
            INSERT INTO app.ssp_tranches (id, organization_id, deal_id, tranche_id, name)
            VALUES (CAST(:ta AS uuid), CAST(:org AS uuid), CAST(:da AS uuid), 'T-A', 'Tranche A')
            """
        ),
        {"ta": tranche_a, "org": org, "da": deal_a},
    )
    conn.execute(
        text(
            """
            INSERT INTO app.ssp_pool_of_pools (id, organization_id, deal_id, pool_of_pools_id, name)
            VALUES (CAST(:pop AS uuid), CAST(:org AS uuid), CAST(:da AS uuid), 'POP-A', 'PoP A')
            """
        ),
        {"pop": pop_a, "org": org, "da": deal_a},
    )
    return {
        "org": org,
        "other_org": str(OTHER_ORG_ID),
        "deal_a": deal_a,
        "deal_b": deal_b,
        "loan_a": loan_a,
        "loan_b": loan_b,
        "col_a": col_a,
        "col_b": col_b,
        "pool_a": pool_a,
        "pool_b": pool_b,
        "tranche_a": tranche_a,
        "pop_a": pop_a,
    }


def test_postgres_association_integrity_valid_and_cross_deal(isolated_engine):
    with isolated_engine.begin() as conn:
        ids = _seed_two_deals(conn)
        # Valid same-deal loan↔collateral
        conn.execute(
            text(
                """
                INSERT INTO app.ssp_loan_collateral
                  (organization_id, deal_id, loan_row_id, collateral_row_id)
                VALUES
                  (CAST(:org AS uuid), CAST(:deal AS uuid),
                   CAST(:loan AS uuid), CAST(:col AS uuid))
                """
            ),
            {
                "org": ids["org"],
                "deal": ids["deal_a"],
                "loan": ids["loan_a"],
                "col": ids["col_a"],
            },
        )
        # Valid pool↔loan, tranche↔pool, pop↔pool
        conn.execute(
            text(
                """
                INSERT INTO app.ssp_pool_loans
                  (organization_id, deal_id, pool_row_id, loan_row_id)
                VALUES
                  (CAST(:org AS uuid), CAST(:deal AS uuid),
                   CAST(:pool AS uuid), CAST(:loan AS uuid))
                """
            ),
            {
                "org": ids["org"],
                "deal": ids["deal_a"],
                "pool": ids["pool_a"],
                "loan": ids["loan_a"],
            },
        )
        conn.execute(
            text(
                """
                INSERT INTO app.ssp_tranche_pools
                  (organization_id, deal_id, tranche_row_id, pool_row_id)
                VALUES
                  (CAST(:org AS uuid), CAST(:deal AS uuid),
                   CAST(:tranche AS uuid), CAST(:pool AS uuid))
                """
            ),
            {
                "org": ids["org"],
                "deal": ids["deal_a"],
                "tranche": ids["tranche_a"],
                "pool": ids["pool_a"],
            },
        )
        conn.execute(
            text(
                """
                INSERT INTO app.ssp_pool_of_pools_members
                  (organization_id, deal_id, pool_of_pools_row_id, pool_row_id)
                VALUES
                  (CAST(:org AS uuid), CAST(:deal AS uuid),
                   CAST(:pop AS uuid), CAST(:pool AS uuid))
                """
            ),
            {
                "org": ids["org"],
                "deal": ids["deal_a"],
                "pop": ids["pop_a"],
                "pool": ids["pool_a"],
            },
        )

    with isolated_engine.connect() as conn:
        # Cross-deal loan↔collateral must fail composite FK
        try:
            with conn.begin():
                conn.execute(
                    text(
                        """
                        INSERT INTO app.ssp_loan_collateral
                          (organization_id, deal_id, loan_row_id, collateral_row_id)
                        VALUES
                          (CAST(:org AS uuid), CAST(:deal AS uuid),
                           CAST(:loan AS uuid), CAST(:col AS uuid))
                        """
                    ),
                    {
                        "org": ids["org"],
                        "deal": ids["deal_a"],
                        "loan": ids["loan_a"],
                        "col": ids["col_b"],
                    },
                )
            pytest.fail("cross-deal loan_collateral should have been rejected")
        except Exception as exc:
            assert "fk_ssp_loan_collateral" in str(exc).lower() or "foreign key" in str(exc).lower()

        try:
            with conn.begin():
                conn.execute(
                    text(
                        """
                        INSERT INTO app.ssp_pool_loans
                          (organization_id, deal_id, pool_row_id, loan_row_id)
                        VALUES
                          (CAST(:org AS uuid), CAST(:deal AS uuid),
                           CAST(:pool AS uuid), CAST(:loan AS uuid))
                        """
                    ),
                    {
                        "org": ids["org"],
                        "deal": ids["deal_a"],
                        "pool": ids["pool_a"],
                        "loan": ids["loan_b"],
                    },
                )
            pytest.fail("cross-deal pool_loans should have been rejected")
        except Exception as exc:
            assert "fk_ssp_pool_loans" in str(exc).lower() or "foreign key" in str(exc).lower()

        try:
            with conn.begin():
                conn.execute(
                    text(
                        """
                        INSERT INTO app.ssp_tranche_pools
                          (organization_id, deal_id, tranche_row_id, pool_row_id)
                        VALUES
                          (CAST(:org AS uuid), CAST(:deal AS uuid),
                           CAST(:tranche AS uuid), CAST(:pool AS uuid))
                        """
                    ),
                    {
                        "org": ids["org"],
                        "deal": ids["deal_a"],
                        "tranche": ids["tranche_a"],
                        "pool": ids["pool_b"],
                    },
                )
            pytest.fail("cross-deal tranche_pools should have been rejected")
        except Exception as exc:
            assert "fk_ssp_tranche_pools" in str(exc).lower() or "foreign key" in str(exc).lower()

        try:
            with conn.begin():
                conn.execute(
                    text(
                        """
                        INSERT INTO app.ssp_pool_of_pools_members
                          (organization_id, deal_id, pool_of_pools_row_id, pool_row_id)
                        VALUES
                          (CAST(:org AS uuid), CAST(:deal AS uuid),
                           CAST(:pop AS uuid), CAST(:pool AS uuid))
                        """
                    ),
                    {
                        "org": ids["org"],
                        "deal": ids["deal_a"],
                        "pop": ids["pop_a"],
                        "pool": ids["pool_b"],
                    },
                )
            pytest.fail("cross-deal pop members should have been rejected")
        except Exception as exc:
            assert "fk_ssp_pop_members" in str(exc).lower() or "foreign key" in str(exc).lower()


def test_postgres_association_org_mismatch_rejected(isolated_engine):
    with isolated_engine.begin() as conn:
        ids = _seed_two_deals(conn)
        try:
            conn.execute(
                text(
                    """
                    INSERT INTO app.ssp_loan_collateral
                      (organization_id, deal_id, loan_row_id, collateral_row_id)
                    VALUES
                      (CAST(:org AS uuid), CAST(:deal AS uuid),
                       CAST(:loan AS uuid), CAST(:col AS uuid))
                    """
                ),
                {
                    "org": ids["other_org"],
                    "deal": ids["deal_a"],
                    "loan": ids["loan_a"],
                    "col": ids["col_a"],
                },
            )
            pytest.fail("org-mismatched association should have been rejected")
        except Exception as exc:
            assert "ssp org match" in str(exc).lower() or "org match" in str(exc).lower()


def test_postgres_api_rejects_unknown_association_ids(postgres_session):
    client = _client(postgres_session)
    bad = _put(
        client,
        INSTANCE_A,
        draft=_draft(
            financingInstanceId=INSTANCE_A,
            loans=[
                {
                    "loanId": LOAN_1,
                    "name": "Loan",
                    "collateralIds": ["missing-collateral-xyz"],
                    "currentOutstandingAmount": 10,
                    "originalOutstandingAmount": None,
                    "notes": "",
                    "evidence": {"source": "", "notes": "", "documentReference": ""},
                }
            ],
        ),
    )
    assert bad.status_code == 422, bad.text


def test_postgres_multi_class_class_inputs_roundtrip(postgres_session):
    client = _client(postgres_session)
    draft = _draft(
        financingInstanceId=INSTANCE_A,
        emissionsPath="lookthrough",
        collateral=[
            {
                "collateralId": COL_1,
                "name": "House",
                "collateralType": "mortgage",
                "attributionDenominator": 100,
                "denominatorLabel": "Property value",
                "currentOutstandingAmount": None,
                "originalOutstandingAmount": None,
                "assetValueAtOrigination": 100,
                "updatedAssetValue": None,
                "pcafMethodOption": "1a",
                "emissionsPath": "asset-class-estimate",
                "scope1Emissions": None,
                "scope2Emissions": None,
                "scope3Emissions": None,
                "dataQualityScore": None,
                "factorLibraryEntryId": "",
                "classInputs": {
                    "schemaVersion": 1,
                    "formData": {
                        "energy_consumption": 1200,
                        "supplier_specific_emission_factor": 0.4,
                        "average_emission_factor": 0.3,
                    },
                    "properties": [
                        {
                            "id": "prop-1",
                            "name": "Residence A",
                            "propertyValueAtOrigination": 100,
                            "actualEnergyConsumption": 1200,
                            "actualEnergyConsumptionUnit": "kWh",
                            "supplierSpecificEmissionFactor": 0.4,
                            "supplierSpecificEmissionFactorUnit": "kgCO2e/kWh",
                            "averageEmissionFactor": 0,
                            "averageEmissionFactorUnit": "kgCO2e/kWh",
                            "estimatedEnergyConsumptionFromLabels": 0,
                            "estimatedEnergyConsumptionFromLabelsUnit": "kWh/m2",
                            "estimatedEnergyConsumptionFromStatistics": 0,
                            "estimatedEnergyConsumptionFromStatisticsUnit": "kWh/m2",
                            "floorArea": 90,
                        }
                    ],
                },
                "evidence": {"source": "trustee", "notes": "", "documentReference": ""},
            },
            {
                "collateralId": COL_2,
                "name": "Fleet",
                "collateralType": "motor-vehicle-loan",
                "attributionDenominator": 50,
                "denominatorLabel": "Vehicle value",
                "currentOutstandingAmount": None,
                "originalOutstandingAmount": None,
                "assetValueAtOrigination": 50,
                "updatedAssetValue": None,
                "pcafMethodOption": "1a",
                "emissionsPath": "asset-class-estimate",
                "scope1Emissions": None,
                "scope2Emissions": None,
                "scope3Emissions": None,
                "dataQualityScore": None,
                "factorLibraryEntryId": "epa-row-1",
                "classInputs": {
                    "schemaVersion": 1,
                    "formData": {
                        "vehicle_entries": [
                            {
                                "id": "veh-1",
                                "fuelType": "petrol",
                                "distance": 10000,
                                "distanceUnit": "km",
                            }
                        ],
                        "total_value_at_origination": 50,
                        "factor_library": "EPA",
                    },
                },
                "evidence": {"source": "servicer", "notes": "", "documentReference": ""},
            },
        ],
    )
    created = _put(client, INSTANCE_A, draft=draft)
    assert created.status_code in (200, 201), created.text
    reloaded = client.get(f"/api/v1/ssp/drafts/by-instance/{INSTANCE_A}")
    assert reloaded.status_code == 200
    body = reloaded.json()["draft"]
    by_id = {c["collateralId"]: c for c in body["collateral"]}
    assert by_id[COL_1]["classInputs"]["properties"][0]["floorArea"] == 90
    assert by_id[COL_1]["classInputs"]["formData"]["energy_consumption"] == 1200
    assert by_id[COL_2]["classInputs"]["formData"]["vehicle_entries"][0]["id"] == "veh-1"
    assert by_id[COL_2]["factorLibraryEntryId"] == "epa-row-1"
    assert by_id[COL_1]["collateralId"] == COL_1
    assert by_id[COL_2]["collateralId"] == COL_2

    # Edit → save preserves ids and nested rows
    props = list(by_id[COL_1]["classInputs"]["properties"])
    props.append({**props[0], "id": "prop-2", "name": "Residence B", "floorArea": 110})
    draft["collateral"][0]["classInputs"]["properties"] = props
    draft["collateral"][0]["classInputs"]["formData"]["energy_consumption"] = 1300
    updated = _put(
        client,
        INSTANCE_A,
        update_shared=True,
        expected_deal_updated_at=created.json()["deal"]["updated_at"],
        expected_holding_updated_at=created.json()["holding"]["updated_at"],
        draft=draft,
    )
    assert updated.status_code in (200, 201), updated.text
    again = client.get(f"/api/v1/ssp/drafts/by-instance/{INSTANCE_A}").json()["draft"]
    house = next(c for c in again["collateral"] if c["collateralId"] == COL_1)
    assert len(house["classInputs"]["properties"]) == 2
    assert house["classInputs"]["formData"]["energy_consumption"] == 1300
    assert house["collateralId"] == COL_1
