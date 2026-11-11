"""
Phase 6B.3 safety gate: prove a disposable Postgres URL is isolated.

Usage (from carbon-credit-backend):
  python scripts/ssp_isolated_stack_check.py

Refuses production EC2 hosts. Does not apply migrations to staging/production.
Starts a disposable Postgres, applies prepared 0020 via bootstrap_ssp_schema,
runs a smoke SELECT, then tears down.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import text

from tests.pg_isolated import (
    bootstrap_ssp_schema,
    is_isolated_url,
    is_production_url,
    make_engine,
    start_isolated_postgres,
)


def main() -> int:
    url, stop = start_isolated_postgres()
    try:
        if is_production_url(url):
            print("REFUSE: URL looks like production")
            return 2
        if not is_isolated_url(url):
            print(f"REFUSE: URL is not loopback-isolated: {url}")
            return 2
        engine = make_engine(url)
        bootstrap_ssp_schema(engine)
        with engine.connect() as conn:
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
            assert "ssp_deals" in tables
            assert "ssp_loan_collateral" in tables
            print("OK isolated stack")
            print(f"DATABASE_URL={url}")
            print("Migration 0020 applied only to disposable DB; stop() will destroy it.")
            print("Do NOT copy this URL into production .env files.")
        engine.dispose()
        return 0
    finally:
        stop()


if __name__ == "__main__":
    raise SystemExit(main())
