-- CANONICAL Phase 3C migration. Apply from this backend file only.
-- DO NOT apply from the SPA copy. DO NOT run against production from this review.
--
-- Target: EC2 Postgres (app.financed_emissions). Hosted Supabase is not the ledger.
-- Prerequisite: 0014_financed_emissions_financing_instance (identity indexes) should
-- already be applied. This file does not rewrite those indexes.
--
-- Behaviour:
--   * nullable columns, no DEFAULT, no backfill
--   * existing rows stay NULL (historical total-only)
--   * JSON results remains the API source of truth until ORM maps these columns
--   * NULL means missing / excluded / unallocated / historical — never treat as 0
--   * 0 is a stored reported-zero value, not a default

BEGIN;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'app' AND table_name = 'financed_emissions'
  ) THEN
    RAISE EXCEPTION '0015 abort: app.financed_emissions does not exist';
  END IF;
END
$$;

ALTER TABLE app.financed_emissions
  ADD COLUMN IF NOT EXISTS financed_scope1_tco2e numeric(20, 6),
  ADD COLUMN IF NOT EXISTS financed_scope2_tco2e numeric(20, 6),
  ADD COLUMN IF NOT EXISTS financed_scope3_tco2e numeric(20, 6),
  ADD COLUMN IF NOT EXISTS financed_unallocated_tco2e numeric(20, 6),
  ADD COLUMN IF NOT EXISTS scope_completeness text;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'app'
      AND table_name = 'financed_emissions'
      AND column_name IN (
        'financed_scope1_tco2e',
        'financed_scope2_tco2e',
        'financed_scope3_tco2e',
        'financed_unallocated_tco2e'
      )
      AND (
        data_type <> 'numeric'
        OR numeric_precision IS DISTINCT FROM 20
        OR numeric_scale IS DISTINCT FROM 6
        OR is_nullable <> 'YES'
      )
  ) THEN
    RAISE EXCEPTION
      '0015 abort: a scope column exists with unexpected type, scale, or nullability';
  END IF;
END
$$;

ALTER TABLE app.financed_emissions
  DROP CONSTRAINT IF EXISTS financed_emissions_scope_completeness_check;

ALTER TABLE app.financed_emissions
  ADD CONSTRAINT financed_emissions_scope_completeness_check
  CHECK (
    scope_completeness IS NULL
    OR scope_completeness IN ('complete', 'partial', 'total_only')
  )
  NOT VALID;

ALTER TABLE app.financed_emissions
  VALIDATE CONSTRAINT financed_emissions_scope_completeness_check;

COMMENT ON COLUMN app.financed_emissions.financed_scope1_tco2e IS
  'Attributed financed Scope 1 (tCO2e). NULL means missing, excluded, unallocated, or historical total-only — never treat as zero. API currently persists the same key on results JSON.';
COMMENT ON COLUMN app.financed_emissions.financed_scope2_tco2e IS
  'Attributed financed Scope 2 (tCO2e). NULL means missing, excluded, unallocated, or historical total-only — never treat as zero.';
COMMENT ON COLUMN app.financed_emissions.financed_scope3_tco2e IS
  'Attributed financed Scope 3 (tCO2e). NULL means missing, excluded, unallocated, or historical total-only — never treat as zero.';
COMMENT ON COLUMN app.financed_emissions.financed_unallocated_tco2e IS
  'Estimated or method-total (tCO2e) that cannot be split into scopes. Do not add to Scope 1/2/3. NULL when a split exists or the record is historical total-only with no stored unallocated amount.';
COMMENT ON COLUMN app.financed_emissions.scope_completeness IS
  'complete | partial | total_only. NULL on historical rows and on new rows until FastAPI maps this column. Do not backfill by splitting financed_emissions.';

-- public.financed_emissions is SELECT * expanded at CREATE time. Recreate so
-- new columns appear at the end. CREATE OR REPLACE may add trailing columns.
CREATE OR REPLACE VIEW public.financed_emissions AS
SELECT * FROM app.financed_emissions;

GRANT SELECT ON public.financed_emissions TO app_user;

INSERT INTO public.schema_migrations (version, description)
VALUES (
  '0015_financed_scope_breakdown',
  'Nullable financed Scope 1/2/3 + unallocated + completeness on app.financed_emissions; no historical backfill'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
