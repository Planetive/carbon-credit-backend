"""
Phase 6B.4 — disposable full-stack for SSP browser E2E.

Starts isolated Postgres (0020 + auth), seeds JWT-capable users, launches FastAPI
with DATABASE_URL/JWT_SECRET overridden (never production .env values), and
optionally prints frontend env for Vite.

Fail-closed: refuses production hosts. Tears down Postgres on exit.

Usage:
  python scripts/run_ssp_e2e_stack.py                  # start API + keep alive
  python scripts/run_ssp_e2e_stack.py --write-env       # also write frontend .env.ssp-e2e
  python scripts/run_ssp_e2e_stack.py --smoke           # seed + login smoke then exit
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SPA_ROOT = BACKEND_ROOT.parent / "carbon-credit-app-main"
sys.path.insert(0, str(BACKEND_ROOT))

# Override BEFORE any fastapi_app import that might load dotenv into process.
os.environ["PGGSSENCMODE"] = "disable"
os.environ["PGSSLMODE"] = "disable"

from sqlalchemy import text

from tests.pg_isolated import (
    bootstrap_ssp_fullstack_schema,
    is_isolated_url,
    is_production_url,
    make_engine,
    start_isolated_postgres,
)

ORG_A = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
ORG_B = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
USER_A = uuid.UUID("11111111-1111-4111-8111-111111111111")
USER_B = uuid.UUID("22222222-2222-4222-8222-222222222222")
CP_A = uuid.UUID("33333333-3333-4333-8333-333333333333")
TEST_PASSWORD = "SspE2ePass!234"
# Must include @planetive for CompanyProtectedRoute allowlist.
EMAIL_A = "ssp.e2e@planetive.com"
EMAIL_B = "ssp.other@planetive.com"
JWT_SECRET = "ssp-e2e-isolated-jwt-secret-do-not-reuse"


def _refuse_inherited_production() -> None:
    inherited = os.environ.get("DATABASE_URL", "")
    # When launching, we always override; still warn/fail if caller forgot and
    # tried to point the script at production explicitly via CLI later.
    if inherited and is_production_url(inherited):
        # Allow only if we are about to replace it — still print refuse for clarity.
        print("NOTE: inherited DATABASE_URL looks like production; it will be overridden.")


def _hash_password_compat(plain: str) -> str:
    """Prefer app helper; fall back to bcrypt directly if passlib/bcrypt mismatch."""
    try:
        from fastapi_app.auth_security import hash_password

        return hash_password(plain)
    except Exception:
        import bcrypt

        return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def seed_identity(engine) -> dict:
    # Import after JWT_SECRET is set so hash/token helpers work.
    os.environ["JWT_SECRET"] = JWT_SECRET
    from fastapi_app.auth_security import create_access_token

    pw = _hash_password_compat(TEST_PASSWORD)
    with engine.begin() as conn:
        for org_id, name in ((ORG_A, "SSP E2E Org A"), (ORG_B, "SSP E2E Org B")):
            conn.execute(
                text(
                    """
                    INSERT INTO public.organizations (id, name, is_active)
                    VALUES (CAST(:id AS uuid), :name, true)
                    ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
                    """
                ),
                {"id": str(org_id), "name": name},
            )
        for user_id, email in ((USER_A, EMAIL_A), (USER_B, EMAIL_B)):
            conn.execute(
                text(
                    """
                    INSERT INTO public.users (id, email, password_hash, email_confirmed)
                    VALUES (CAST(:id AS uuid), :email, :pw, true)
                    ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash
                    """
                ),
                {"id": str(user_id), "email": email, "pw": pw},
            )
        conn.execute(
            text(
                """
                INSERT INTO public.profiles (
                  id, user_id, display_name, user_type, current_organization_id, organization_name
                ) VALUES
                  (gen_random_uuid(), CAST(:ua AS uuid), 'SSP E2E User A', 'financial_institution',
                   CAST(:oa AS uuid), 'SSP E2E Org A'),
                  (gen_random_uuid(), CAST(:ub AS uuid), 'SSP E2E User B', 'financial_institution',
                   CAST(:ob AS uuid), 'SSP E2E Org B')
                ON CONFLICT (user_id) DO UPDATE
                  SET current_organization_id = EXCLUDED.current_organization_id,
                      display_name = EXCLUDED.display_name
                """
            ),
            {"ua": str(USER_A), "ub": str(USER_B), "oa": str(ORG_A), "ob": str(ORG_B)},
        )
        conn.execute(
            text(
                "DELETE FROM public.user_organizations WHERE user_id IN "
                "(CAST(:ua AS uuid), CAST(:ub AS uuid))"
            ),
            {"ua": str(USER_A), "ub": str(USER_B)},
        )
        conn.execute(
            text(
                """
                INSERT INTO public.user_organizations (id, user_id, organization_id, role, status)
                VALUES
                  (gen_random_uuid(), CAST(:ua AS uuid), CAST(:oa AS uuid), 'admin', 'active'),
                  (gen_random_uuid(), CAST(:ub AS uuid), CAST(:ob AS uuid), 'admin', 'active')
                """
            ),
            {"ua": str(USER_A), "ub": str(USER_B), "oa": str(ORG_A), "ob": str(ORG_B)},
        )
        conn.execute(
            text(
                """
                INSERT INTO public.counterparties (
                  id, user_id, organization_id, name, sector, geography, counterparty_type
                ) VALUES (
                  CAST(:id AS uuid), CAST(:uid AS uuid), CAST(:oid AS uuid),
                  'SSP Demo Counterparty', 'Financials', 'PK', 'corporate'
                )
                ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
                """
            ),
            {"id": str(CP_A), "uid": str(USER_A), "oid": str(ORG_A)},
        )

    token_a = create_access_token(USER_A, extra_claims={"email": EMAIL_A})
    token_b = create_access_token(USER_B, extra_claims={"email": EMAIL_B})
    return {
        "org_a": str(ORG_A),
        "org_b": str(ORG_B),
        "email_a": EMAIL_A,
        "email_b": EMAIL_B,
        "password": TEST_PASSWORD,
        "counterparty_id": str(CP_A),
        "jwt_a": token_a,
        "jwt_b": token_b,
        "jwt_secret": JWT_SECRET,
    }


def write_frontend_env(api_port: int, seed: dict) -> Path:
    path = SPA_ROOT / ".env.ssp-e2e"
    contents = "\n".join(
        [
            f"VITE_BACKEND_URL=http://127.0.0.1:{api_port}",
            "VITE_USE_JWT_AUTH=true",
            f"SSP_E2E_EMAIL={seed['email_a']}",
            f"SSP_E2E_PASSWORD={seed['password']}",
            f"SSP_E2E_EMAIL_B={seed['email_b']}",
            f"SSP_E2E_COUNTERPARTY_ID={seed['counterparty_id']}",
            f"SSP_E2E_BASE_URL=http://127.0.0.1:8080",
            "",
        ]
    )
    path.write_text(contents, encoding="utf-8")
    # Credentials file for Playwright (gitignored pattern via name)
    creds = SPA_ROOT / "e2e" / ".ssp-e2e-credentials.json"
    creds.parent.mkdir(parents=True, exist_ok=True)
    creds.write_text(json.dumps(seed, indent=2), encoding="utf-8")
    return path


def wait_http(url: str, attempts: int = 40) -> None:
    last = None
    for _ in range(attempts):
        try:
            with urlopen(url, timeout=2) as resp:
                if resp.status < 500:
                    return
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(0.5)
    raise RuntimeError(f"Service not ready at {url}: {last}")


def smoke_login(api_port: int, seed: dict) -> None:
    body = json.dumps({"email": seed["email_a"], "password": seed["password"]}).encode()
    req = Request(
        f"http://127.0.0.1:{api_port}/auth/login",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=10) as resp:
        payload = json.loads(resp.read().decode())
    token = payload["access_token"]
    drafts = Request(
        f"http://127.0.0.1:{api_port}/api/v1/ssp/drafts",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urlopen(drafts, timeout=10) as resp:
        assert resp.status == 200
        assert json.loads(resp.read().decode()) == []
    # Cross-org: user B token must not see org A drafts (empty list ok)
    drafts_b = Request(
        f"http://127.0.0.1:{api_port}/api/v1/ssp/drafts",
        headers={"Authorization": f"Bearer {seed['jwt_b']}"},
    )
    with urlopen(drafts_b, timeout=10) as resp:
        assert resp.status == 200


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-port", type=int, default=8010)
    parser.add_argument("--write-env", action="store_true")
    parser.add_argument("--smoke", action="store_true", help="Seed + API smoke then exit (still tears down DB)")
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Keep API alive for Playwright (Ctrl+C to tear down)",
    )
    args = parser.parse_args()

    _refuse_inherited_production()
    url, stop = start_isolated_postgres()
    api_proc = None
    api_log = None
    try:
        if is_production_url(url) or not is_isolated_url(url):
            print("REFUSE: disposable URL failed isolation checks")
            return 2
        print(f"Isolated DATABASE_URL={url}")
        engine = make_engine(url)
        bootstrap_ssp_fullstack_schema(engine)
        seed = seed_identity(engine)
        engine.dispose()

        env = os.environ.copy()
        # Explicit overrides — never inherit production DATABASE_URL into the API.
        env["DATABASE_URL"] = url
        env["JWT_SECRET"] = JWT_SECRET
        env["JWT_ALGORITHM"] = "HS256"
        env["ALLOWED_ORIGINS"] = (
            "http://localhost:8080,http://127.0.0.1:8080,"
            "http://localhost:4173,http://127.0.0.1:4173"
        )
        env["PGGSSENCMODE"] = "disable"
        env["PGSSLMODE"] = "disable"

        # Log to a file — never PIPE without a reader (Windows pipe buffer fills and
        # deadlocks uvicorn after a few dozen requests / log lines).
        api_log_path = SPA_ROOT / "e2e" / "uvicorn-ssp-e2e.log"
        api_log_path.parent.mkdir(parents=True, exist_ok=True)
        api_log = open(api_log_path, "w", encoding="utf-8", errors="replace")
        api_proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "fastapi_app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(args.api_port),
            ],
            cwd=str(BACKEND_ROOT),
            env=env,
            stdout=api_log,
            stderr=subprocess.STDOUT,
        )
        # Fail closed if the child dies before becoming ready (e.g. port in use).
        for _ in range(40):
            if api_proc.poll() is not None:
                api_log.flush()
                tail = ""
                try:
                    tail = api_log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
                except Exception:
                    pass
                raise RuntimeError(
                    f"uvicorn exited early ({api_proc.returncode}): {tail}"
                )
            try:
                wait_http(f"http://127.0.0.1:{args.api_port}/docs", attempts=1)
                break
            except Exception:
                time.sleep(0.5)
        else:
            raise RuntimeError("uvicorn did not become ready in time")
        smoke_login(args.api_port, seed)
        print("API smoke: login + ssp drafts list OK", flush=True)

        if args.write_env:
            path = write_frontend_env(args.api_port, seed)
            print(f"Wrote {path}", flush=True)
            print(f"Wrote {SPA_ROOT / 'e2e' / '.ssp-e2e-credentials.json'}", flush=True)

        manifest = {
            "database_url": url,
            "api_base": f"http://127.0.0.1:{args.api_port}",
            "frontend_hint": "http://127.0.0.1:8080",
            "email": seed["email_a"],
            "password": seed["password"],
            "email_b": seed["email_b"],
            "counterparty_id": seed["counterparty_id"],
        }
        out = SPA_ROOT / "e2e" / ".ssp-e2e-stack.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(json.dumps(manifest, indent=2), flush=True)

        if not args.serve:
            print("Smoke complete. Re-run with --serve --write-env to keep API up for Playwright.")
            return 0

        print("Stack running. Ctrl+C to tear down.", flush=True)
        while True:
            if api_proc.poll() is not None:
                api_log.flush()
                try:
                    print(api_log_path.read_text(encoding="utf-8", errors="replace")[-4000:])
                except Exception:
                    pass
                return api_proc.returncode or 1
            time.sleep(1)
    except KeyboardInterrupt:
        return 0
    finally:
        if api_proc and api_proc.poll() is None:
            api_proc.send_signal(signal.SIGTERM)
            try:
                api_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                api_proc.kill()
        if api_log is not None:
            try:
                api_log.close()
            except Exception:
                pass
        stop()
        print("Torn down isolated Postgres.", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
