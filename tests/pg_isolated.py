"""Start a disposable PostgreSQL and apply 0014/0017 without touching production."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Callable, Optional, Tuple
from urllib.parse import urlparse

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from fastapi_app.db import Base
from fastapi_app.ghg_models import FinancedEmission
from fastapi_app.uop_models import (
    UopAssetCalculation,
    UopInvestment,
    UopStructure,
    UopUnderlyingAsset,
)

PRODUCTION_HOST_MARKERS = ("18.211.235.71",)
ISOLATED_HOSTS = {"127.0.0.1", "localhost", "::1"}
PORTABLE_PG_VERSION = "18.6.1"
PORTABLE_PG_URL = (
    "https://github.com/theseus-rs/postgresql-binaries/releases/download/"
    f"{PORTABLE_PG_VERSION}/postgresql-{PORTABLE_PG_VERSION}-x86_64-pc-windows-msvc.tar.gz"
)
BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_0017 = BACKEND_ROOT / "db" / "migrations" / "0017_financed_emissions_reporting_year.sql"

# Must be set before libpq connects; Windows otherwise hangs in GSS/SSPI.
os.environ.setdefault("PGGSSENCMODE", "disable")
os.environ.setdefault("PGSSLMODE", "disable")


def is_production_url(url: str) -> bool:
    lowered = url.lower()
    return any(marker in lowered for marker in PRODUCTION_HOST_MARKERS)


def is_isolated_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in ISOLATED_HOSTS


def _port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex((host, port)) == 0


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _cache_dir() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir())
    path = root / "rethink-uop-isolated-pg"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _find_initdb(root: Path) -> Optional[Path]:
    # Do not rglob: the portable archive bundles a Python stdlib under bin/Lib.
    candidates = [
        *root.glob("*/bin/initdb.exe"),
        *root.glob("*/bin/initdb"),
        root / "bin" / "initdb.exe",
        root / "bin" / "initdb",
    ]
    for candidate in candidates:
        if candidate.is_file():
            share = candidate.parent.parent / "share" / "postgres.bki"
            if share.exists():
                return candidate
    return None


def _download_portable_postgres() -> Path:
    dest_dir = _cache_dir() / "pg-18.6.1"
    found = _find_initdb(dest_dir)
    if found:
        return found
    archive = _cache_dir() / "postgresql-18.6.1-windows.tar.gz"
    if not archive.exists():
        request = urllib.request.Request(
            PORTABLE_PG_URL,
            headers={"User-Agent": "rethink-carbon-isolated-pg/5d.1"},
        )
        with urllib.request.urlopen(request, timeout=300) as response, archive.open("wb") as out:
            shutil.copyfileobj(response, out)
    dest_dir.mkdir(parents=True, exist_ok=True)
    header = archive.read_bytes()[:2]
    if header != b"\x1f\x8b":
        archive.unlink(missing_ok=True)
        raise RuntimeError("Portable PostgreSQL download is not a gzip archive")
    with tarfile.open(archive, "r:gz") as tar:
        extract_kwargs = {}
        if getattr(tarfile, "data_filter", None) is not None:
            extract_kwargs["filter"] = "data"
        tar.extractall(dest_dir, **extract_kwargs)
    found = _find_initdb(dest_dir)
    if not found:
        raise RuntimeError("Portable PostgreSQL archive did not contain initdb/share")
    return found


def start_isolated_postgres() -> Tuple[str, Callable[[], None]]:
    env_url = (os.environ.get("TEST_DATABASE_URL") or "").strip()
    if env_url:
        if is_production_url(env_url) or not is_isolated_url(env_url):
            raise RuntimeError(
                "Refusing non-isolated TEST_DATABASE_URL (localhost/127.0.0.1 only; never production)"
            )
        return env_url, lambda: None

    initdb = _download_portable_postgres()
    bindir = initdb.parent
    data_dir = Path(tempfile.mkdtemp(prefix="uop5d1-pg-"))
    log_file = data_dir / "pg.log"
    port = _free_port()
    subprocess.run(
        [
            str(initdb),
            "-D",
            str(data_dir / "data"),
            "-U",
            "uop",
            "--auth=trust",
            "--encoding=UTF8",
            "--locale=C",
            "--no-sync",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=60,
    )
    # Windows libpq otherwise tries GSS/SSPI and can hang past connect_timeout.
    os.environ["PGGSSENCMODE"] = "disable"
    os.environ["PGSSLMODE"] = "disable"
    pg_ctl = bindir / ("pg_ctl.exe" if initdb.suffix == ".exe" else "pg_ctl")
    pg_env = os.environ.copy()
    pg_env["PATH"] = str(bindir) + os.pathsep + pg_env.get("PATH", "")
    pg_env["PGUSER"] = "uop"
    pg_env["PGHOST"] = "127.0.0.1"
    pg_env["PGCONNECT_TIMEOUT"] = "5"
    pg_env["PGSSLMODE"] = "disable"
    pg_env["PGGSSENCMODE"] = "disable"
    subprocess.run(
        [
            str(pg_ctl),
            "-D",
            str(data_dir / "data"),
            "-l",
            str(log_file),
            "-o",
            f"-p {port} -h 127.0.0.1",
            "start",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=30,
        env=pg_env,
    )
    import psycopg2

    dsn = (
        f"host=127.0.0.1 port={port} user=uop password=uop dbname=postgres "
        "sslmode=disable gssencmode=disable connect_timeout=5"
    )
    last_error: Optional[Exception] = None
    for _ in range(10):
        try:
            admin = psycopg2.connect(dsn)
            admin.autocommit = True
            with admin.cursor() as cur:
                cur.execute("CREATE DATABASE uop5d1")
            admin.close()
            last_error = None
            break
        except Exception as exc:
            last_error = exc
            time.sleep(0.5)
    if last_error is not None:
        subprocess.run(
            [str(pg_ctl), "-D", str(data_dir / "data"), "-m", "immediate", "stop"],
            capture_output=True,
            check=False,
            timeout=15,
            env=pg_env,
        )
        raise RuntimeError(f"CREATE DATABASE failed: {last_error}")
    url = (
        f"postgresql://uop:uop@127.0.0.1:{port}/uop5d1"
        "?sslmode=disable&gssencmode=disable"
    )

    def stop() -> None:
        subprocess.run(
            [str(pg_ctl), "-D", str(data_dir / "data"), "-m", "immediate", "stop"],
            capture_output=True,
            check=False,
            timeout=15,
        )
        shutil.rmtree(data_dir, ignore_errors=True)

    return url, stop


def _sql_statements(script: str) -> list[str]:
    statements: list[str] = []
    buf: list[str] = []
    i = 0
    dollar: Optional[str] = None
    while i < len(script):
        if dollar:
            end = script.find(dollar, i)
            if end < 0:
                buf.append(script[i:])
                break
            buf.append(script[i : end + len(dollar)])
            i = end + len(dollar)
            dollar = None
            continue
        if script.startswith("--", i):
            newline = script.find("\n", i)
            i = len(script) if newline < 0 else newline + 1
            continue
        if script.startswith("$$", i):
            dollar = "$$"
            buf.append("$$")
            i += 2
            continue
        char = script[i]
        if char == ";":
            stmt = "".join(buf).strip()
            if stmt and stmt.upper() not in {"BEGIN", "COMMIT"}:
                statements.append(stmt)
            buf = []
            i += 1
            continue
        buf.append(char)
        i += 1
    tail = "".join(buf).strip()
    if tail and tail.upper() not in {"BEGIN", "COMMIT"}:
        statements.append(tail)
    return statements


def apply_sql_file(engine: Engine, path: Path) -> None:
    script = path.read_text(encoding="utf-8")
    with engine.begin() as conn:
        dbapi = conn.connection.dbapi_connection
        for statement in _sql_statements(script):
            cursor = dbapi.cursor()
            try:
                cursor.execute(statement)
            finally:
                cursor.close()


def bootstrap_uop_schema(engine: Engine, *, apply_0017: bool) -> None:
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS app"))
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS public"))
    tables = [
        FinancedEmission.__table__,
        UopStructure.__table__,
        UopInvestment.__table__,
        UopUnderlyingAsset.__table__,
        UopAssetCalculation.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_financed_emissions_financing_instance
                ON app.financed_emissions (
                  organization_id,
                  COALESCE(counterparty_id, CAST('00000000-0000-0000-0000-000000000000' AS uuid)),
                  calc_kind,
                  (btrim(inputs->>'financing_instance_id'))
                )
                WHERE
                  NULLIF(btrim(inputs->>'financing_instance_id'), '') IS NOT NULL
                  AND lower(COALESCE(formula_id, '')) <> 'aggregate'
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE app.uop_asset_calculations
                  DROP CONSTRAINT IF EXISTS uop_asset_calculations_not_reportable_chk
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE app.uop_asset_calculations
                  ADD CONSTRAINT uop_asset_calculations_not_reportable_chk
                  CHECK (is_reportable IS FALSE AND include_in_portfolio IS FALSE)
                """
            )
        )
    if apply_0017:
        apply_sql_file(engine, MIGRATION_0017)


def connect_args() -> dict:
    return {
        "connect_timeout": 5,
        "sslmode": "disable",
        "gssencmode": "disable",
    }


def make_engine(url: str, **kwargs) -> Engine:
    os.environ.setdefault("PGGSSENCMODE", "disable")
    os.environ.setdefault("PGSSLMODE", "disable")
    return create_engine(url, pool_pre_ping=True, connect_args=connect_args(), **kwargs)


def make_session(engine: Engine) -> Session:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)()
