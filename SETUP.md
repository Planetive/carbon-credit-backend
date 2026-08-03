# Backend Setup Guide

## Prerequisites

- Python 3.9+
- Access to EC2 Postgres database `rethinkcarbon`
- A strong `JWT_SECRET` for signing access tokens

## Installation

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Environment configuration

```bash
cp .env.example .env
```

Required:

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | EC2 Postgres URL, e.g. `postgresql://postgres:PASSWORD@HOST:5432/rethinkcarbon` |
| `JWT_SECRET` | Secret used to sign/verify JWTs |

Optional:

| Variable | Default / notes |
|----------|-----------------|
| `JWT_ALGORITHM` | `HS256` |
| `JWT_EXPIRE_MINUTES` | `10080` (7 days) |
| `ALLOWED_ORIGINS` | Comma-separated CORS origins |
| `SUPABASE_SERVICE_ROLE_KEY` | Legacy fallback only for `/health` and `/test-db` |

### 3. Auth SQL (once per database)

Run against `rethinkcarbon` before using `/auth/signup`:

```text
fastapi_app/sql/001_auth_users_and_profiles.sql
```

Product schema migrations stay in the sibling frontend repo:

```text
carbon-credit-app-main/db/migrations
```

### 4. Run locally

```bash
uvicorn fastapi_app.main:app --reload --host 0.0.0.0 --port 8000
```

Smoke checks:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/test-db
```

## Railway

- This repo is the deploy target. Start: `uvicorn fastapi_app.main:app --host 0.0.0.0 --port $PORT`
- Set `DATABASE_URL` (EC2) and `JWT_SECRET` on the Railway service
- Do **not** attach Railway Postgres; the app uses external EC2 Postgres

## Security notes

- Never commit `.env`
- `JWT_SECRET` must be long and random in production
- `SUPABASE_SERVICE_ROLE_KEY` is optional legacy only; prefer `DATABASE_URL`
