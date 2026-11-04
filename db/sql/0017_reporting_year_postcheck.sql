-- READ-ONLY post-migration verification for 0017.
-- Do not UPDATE/DELETE. Run after 0017 on the target database.

-- 1. 0014 index must be gone; year-aware index must exist.
SELECT
  indexname,
  indexdef
FROM pg_indexes
WHERE schemaname = 'app'
  AND tablename = 'financed_emissions'
  AND indexname IN (
    'uq_financed_emissions_financing_instance',
    'uq_financed_emissions_financing_instance_year',
    'ix_financed_emissions_financing_instance_id'
  )
ORDER BY indexname;

-- 2. reporting_year column exists and is nullable text.
SELECT
  column_name,
  data_type,
  is_nullable,
  column_default
FROM information_schema.columns
WHERE table_schema = 'app'
  AND table_name = 'financed_emissions'
  AND column_name = 'reporting_year';

-- 3. Sync trigger is in place.
SELECT tgname, tgenabled
FROM pg_trigger
WHERE tgrelid = 'app.financed_emissions'::regclass
  AND tgname = 'trg_financed_emissions_sync_reporting_year';

-- 4. No duplicate year-aware identity groups.
SELECT
  organization_id,
  calc_kind,
  btrim(inputs->>'financing_instance_id') AS financing_instance_id,
  COALESCE(
    NULLIF(btrim(reporting_year), ''),
    NULLIF(btrim(inputs->>'reporting_year'), ''),
    NULLIF(btrim(inputs->>'reportingYear'), ''),
    ''
  ) AS reporting_year_key,
  count(*) AS row_count
FROM app.financed_emissions
WHERE lower(COALESCE(formula_id, '')) <> 'aggregate'
  AND NULLIF(btrim(inputs->>'financing_instance_id'), '') IS NOT NULL
GROUP BY 1, 2, 3, 4
HAVING count(*) > 1;

-- 5. Historical totals were not rewritten: row counts and null-year rows remain.
SELECT
  count(*) AS total_rows,
  count(*) FILTER (WHERE financed_emissions IS NULL) AS null_totals,
  count(*) FILTER (
    WHERE NULLIF(btrim(COALESCE(reporting_year, '')), '') IS NULL
      AND NULLIF(btrim(inputs->>'reporting_year'), '') IS NULL
      AND NULLIF(btrim(inputs->>'reportingYear'), '') IS NULL
  ) AS still_without_year
FROM app.financed_emissions;

-- 6. public view exposes reporting_year when the view exists.
SELECT column_name
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'financed_emissions'
  AND column_name = 'reporting_year';
