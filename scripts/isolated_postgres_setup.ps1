# Disposable PostgreSQL for Phase 5D.1 UoP integration tests.
# Does not connect to production (18.211.235.71 / rethinkcarbon).
# Does not apply 0017 to production.
#
# Option A — TEST_DATABASE_URL pointing at a local empty database:
#   $env:TEST_DATABASE_URL = "postgresql://USER:PASS@127.0.0.1:5432/uop5d1"
#   python -m pytest tests/test_uop_reportable_postgres.py -q
#
# Option B — let tests/pg_isolated.py download portable PostgreSQL 18 binaries
# into %LOCALAPPDATA%\rethink-uop-isolated-pg and init a temp cluster.
#
# Option C — Docker:
#   docker run --rm -d --name rethink-uop-5d-pg -e POSTGRES_USER=uop -e POSTGRES_PASSWORD=uop -e POSTGRES_DB=uop5d1 -p 55432:5432 postgres:16
#   $env:TEST_DATABASE_URL = "postgresql://uop:uop@127.0.0.1:55432/uop5d1"

$ErrorActionPreference = "Stop"
if ($env:TEST_DATABASE_URL -and $env:TEST_DATABASE_URL -match "18\.211\.235\.71") {
  throw "Refusing production DATABASE_URL"
}
Write-Host "Run: python -m pytest tests/test_uop_reportable_postgres.py -q --tb=short"
