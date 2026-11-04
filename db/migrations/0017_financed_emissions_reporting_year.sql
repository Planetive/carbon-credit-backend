-- PREPARED, NOT APPLIED TO PRODUCTION.
-- Phase 5D.1: reporting-year-aware identity for app.financed_emissions.
--
-- DO NOT run against production from this task.
-- DO NOT DELETE or UPDATE financed_emissions totals, status, inputs, or results.
-- The only data change is an additive fill of the new reporting_year column
-- from inputs->>'reporting_year' where that JSON key is already present.
--
-- Replaces 0014 unique index:
--   0014: (org, COALESCE(counterparty, zero-uuid), calc_kind, btrim(instance))
--   0017: same key plus coalesced reporting year
--
-- NULL / blank reporting years coalesce to '' so historical rows without a
-- year keep 0014 uniqueness (one active instance). Two years for the same
-- financing_instance_id become legal only after this index exists.
--
-- Index expression reads the column first, then inputs JSON, so rows written
-- before the ORM maps reporting_year still participate correctly.
--
-- Prerequisite: run db/sql/0017_reporting_year_preflight.sql (read-only).
-- Abort rather than drop duplicates.

BEGIN;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.schemata WHERE schema_name = 'app'
  ) THEN
    RAISE EXCEPTION '0017 abort: schema app does not exist';
  END IF;
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'app' AND table_name = 'financed_emissions'
  ) THEN
    RAISE EXCEPTION '0017 abort: app.financed_emissions does not exist';
  END IF;
END
$$;

ALTER TABLE app.financed_emissions
  ADD COLUMN IF NOT EXISTS reporting_year text;

COMMENT ON COLUMN app.financed_emissions.reporting_year IS
  'Reporting year for the financed result. Additive backfill from inputs.reporting_year only. NULL/blank historical rows keep 0014-style uniqueness via coalescing to empty string.';

-- Additive column fill. Does not rewrite financed_emissions, attribution,
-- data_quality_score, status, inputs, or results.
UPDATE app.financed_emissions
SET reporting_year = COALESCE(
  NULLIF(btrim(inputs->>'reporting_year'), ''),
  NULLIF(btrim(inputs->>'reportingYear'), '')
)
WHERE reporting_year IS NULL
  AND COALESCE(
    NULLIF(btrim(inputs->>'reporting_year'), ''),
    NULLIF(btrim(inputs->>'reportingYear'), '')
  ) IS NOT NULL;

CREATE OR REPLACE FUNCTION app.financed_emissions_sync_reporting_year()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF NEW.reporting_year IS NULL OR btrim(NEW.reporting_year) = '' THEN
    NEW.reporting_year := COALESCE(
      NULLIF(btrim(NEW.inputs->>'reporting_year'), ''),
      NULLIF(btrim(NEW.inputs->>'reportingYear'), '')
    );
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_financed_emissions_sync_reporting_year
  ON app.financed_emissions;
CREATE TRIGGER trg_financed_emissions_sync_reporting_year
  BEFORE INSERT OR UPDATE OF reporting_year, inputs
  ON app.financed_emissions
  FOR EACH ROW
  EXECUTE FUNCTION app.financed_emissions_sync_reporting_year();

DO $$
DECLARE
  dup_count integer;
BEGIN
  SELECT count(*) INTO dup_count
  FROM (
    SELECT 1
    FROM app.financed_emissions
    WHERE NULLIF(btrim(inputs->>'financing_instance_id'), '') IS NOT NULL
      AND lower(COALESCE(formula_id, '')) <> 'aggregate'
    GROUP BY
      organization_id,
      COALESCE(counterparty_id, '00000000-0000-0000-0000-000000000000'::uuid),
      calc_kind,
      btrim(inputs->>'financing_instance_id'),
      COALESCE(
        NULLIF(btrim(reporting_year), ''),
        NULLIF(btrim(inputs->>'reporting_year'), ''),
        NULLIF(btrim(inputs->>'reportingYear'), ''),
        ''
      )
    HAVING count(*) > 1
  ) duplicates;
  IF dup_count > 0 THEN
    RAISE EXCEPTION
      '0017 abort: % duplicate (org, counterparty, calc_kind, instance, year) groups exist. Resolve before replacing the 0014 unique index. No rows were deleted.',
      dup_count;
  END IF;
END
$$;

DROP INDEX IF EXISTS app.uq_financed_emissions_financing_instance;

CREATE UNIQUE INDEX IF NOT EXISTS uq_financed_emissions_financing_instance_year
ON app.financed_emissions (
  organization_id,
  COALESCE(counterparty_id, '00000000-0000-0000-0000-000000000000'::uuid),
  calc_kind,
  btrim(inputs->>'financing_instance_id'),
  COALESCE(
    NULLIF(btrim(reporting_year), ''),
    NULLIF(btrim(inputs->>'reporting_year'), ''),
    NULLIF(btrim(inputs->>'reportingYear'), ''),
    ''
  )
)
WHERE
  NULLIF(btrim(inputs->>'financing_instance_id'), '') IS NOT NULL
  AND lower(COALESCE(formula_id, '')) <> 'aggregate';

COMMENT ON INDEX app.uq_financed_emissions_financing_instance_year IS
  'Replaces 0014: one non-aggregate financed row per (org, counterparty, calc_kind, instance, reporting_year). NULL year coalesces to empty string.';

-- 0015 recreated this view after adding scope columns. Recreate so the new
-- reporting_year column is visible. Do not drop the view.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.views
    WHERE table_schema = 'public' AND table_name = 'financed_emissions'
  ) THEN
    EXECUTE 'CREATE OR REPLACE VIEW public.financed_emissions AS SELECT * FROM app.financed_emissions';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
    EXECUTE 'GRANT SELECT ON public.financed_emissions TO app_user';
  END IF;
END
$$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'schema_migrations'
  ) THEN
    INSERT INTO public.schema_migrations (version, description)
    VALUES (
      '0017_financed_emissions_reporting_year',
      'Year-aware unique index for app.financed_emissions; additive reporting_year column only'
    )
    ON CONFLICT (version) DO NOTHING;
  END IF;
END
$$;

COMMIT;
