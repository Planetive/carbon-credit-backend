# Carbon Credit Backend (FastAPI)

Canonical FastAPI API for RethinkCarbon. Deployed on **Railway** (uvicorn). Postgres lives on **EC2** (`DATABASE_URL`) — Railway does not host the database.

Auth is self-hosted JWT against `public.users` (not Supabase Auth). Product schema SQL migrations remain in the sibling app repo: `carbon-credit-app-main/db/migrations`. Auth bootstrap SQL is in `fastapi_app/sql/001_auth_users_and_profiles.sql`.

## Quickstart (local)

```bash
python -m venv .venv
# Windows PowerShell:
. .venv/Scripts/Activate.ps1
pip install -r requirements.txt
cp .env.example .env
# Fill DATABASE_URL and JWT_SECRET in .env

uvicorn fastapi_app.main:app --reload --host 0.0.0.0 --port 8000
```

- Swagger: http://localhost:8000/docs
- Health: http://localhost:8000/health
- DB probe: http://localhost:8000/test-db
- Auth: `POST /auth/signup`, `POST /auth/login`, `GET /auth/me`

See [SETUP.md](SETUP.md) for env vars and Railway notes.

## Endpoints (current)

- `GET /health`, `GET /test-db`
- Auth: `POST /auth/signup`, `POST /auth/login`, `GET /auth/me`, `POST /auth/logout`
- Portfolio / orgs: `/api/v1/me/profile`, `/api/v1/me/calculator-preferences`, `/api/v1/me/project-inputs`, `/api/v1/me/project-reports`, `/api/v1/organizations`, `/api/v1/organizations/{id}/invitations`, `/api/v1/organizations/{id}/members`, `/api/v1/invitations/accept`, `/api/v1/invitations/by-token/{token}`, `/api/v1/counterparties`, `/api/v1/counterparties/{id}/questionnaire`, `/api/v1/questionnaires`, `/api/v1/exposures`, `/api/v1/company-emissions`
- Contact: `POST /api/v1/contact-submissions` (public); admin `GET|PATCH|DELETE /api/v1/admin/contact-submissions` (`X-Admin-Key`)
- GHG: `/api/v1/emission-assessments`, `/api/v1/emission-activities`
- Financed: `/api/v1/financed-emissions`, `POST /api/v1/financed-emissions/calculate`
- Factors (read-only, JWT): `/api/v1/factors/datasets`, `/api/v1/factors/rows`, `/api/v1/factors/sheets/{code}` — reads `ref.factor_datasets` / `ref.factor_rows` (legacy-shaped sheet via Factor Service)
- ESG (JWT + org): `/api/v1/esg/assessments`, `/assessments/latest`, `/scores` — user-scoped CRUD on `public.esg_assessments` / `esg_scores`
- ESG admin (`X-Admin-Key`, no JWT): `/api/v1/esg/admin/assessments`, `/admin/assessments/{id}` — cross-user list/detail for admin dashboard
- Calc (JWT, SPA math parity): `/api/v1/calc/uk/fuel`, `/epa/fuel`, `/uk/passenger|delivery|refrigerant`, `/epa/mobile-fuel`, `/epa/on-road-gasoline|diesel`, `/epa/non-road`, `/heat-steam`, `/waste` — optional persist to `app.emission_activities` when `assessment_id` + `persist`
- Catalog (read-only, JWT): `/api/v1/catalog/country-emissions`, `global-projects`, `ccus-projects`, `bess`, `carbon-credit-markets`, … — missing tables return `[]`
- Calc (stateless): `POST /finance-emission`, `POST /facilitated-emission`, `POST /scenario/calculate`

## Deploy (Railway)

Start command (already in `railway.json` / `Procfile` / `nixpacks.toml`):

```text
uvicorn fastapi_app.main:app --host 0.0.0.0 --port $PORT
```

Required Railway env vars: `DATABASE_URL`, `JWT_SECRET`. Optional: `JWT_ALGORITHM`, `JWT_EXPIRE_MINUTES`, `ALLOWED_ORIGINS`, `SUPABASE_SERVICE_ROLE_KEY` (legacy fallback).

### ESG admin

Set `ADMIN_API_KEY` on Railway to the same secret as the SPA `VITE_ADMIN_PASSWORD`. Admin routes (`/api/v1/esg/admin/...`) accept header `X-Admin-Key` only (no JWT). User-scoped ESG CRUD uses JWT + org context (`/api/v1/esg/assessments`, `/scores`).
