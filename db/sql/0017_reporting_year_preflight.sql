-- READ-ONLY production preflight for 0017_financed_emissions_reporting_year.
-- Run BEFORE applying 0017. Do not run as a migration. Do not UPDATE/DELETE.
-- Do not reference app.financed_emissions.reporting_year here: that column
-- does not exist until 0017. JSON inputs.reporting_year / reportingYear is
-- the pre-migration source of truth.
-- Expected: ops review this result set before applying 0017.

-- 1. Confirm 0014 identity index and 0015 scope columns still match intent.
SELECT
  i.schemaname,
  i.indexname,
  i.indexdef
FROM pg_indexes i
WHERE i.schemaname = 'app'
  AND i.tablename = 'financed_emissions'
ORDER BY i.indexname;

SELECT
  column_name,
  data_type,
  is_nullable
FROM information_schema.columns
WHERE table_schema = 'app'
  AND table_name = 'financed_emissions'
  AND column_name IN (
    'reporting_year',
    'financed_scope1_tco2e',
    'financed_scope2_tco2e',
    'financed_scope3_tco2e',
    'financed_unallocated_tco2e',
    'scope_completeness'
  )
ORDER BY column_name;

-- 2. 0014-era duplicate instances (would already violate 0014).
SELECT
  organization_id,
  counterparty_id,
  calc_kind,
  btrim(inputs->>'financing_instance_id') AS financing_instance_id,
  count(*) AS row_count
FROM app.financed_emissions
WHERE lower(COALESCE(formula_id, '')) <> 'aggregate'
  AND NULLIF(btrim(inputs->>'financing_instance_id'), '') IS NOT NULL
GROUP BY 1, 2, 3, 4
HAVING count(*) > 1
ORDER BY row_count DESC;

-- 3. Prospective 0017 duplicate groups (instance + JSON year).
-- reporting_year column does not exist until 0017; JSON is the pre-migration source.
-- Expected: 0 rows when 0014 is already in force (0017 only adds a uniqueness column).
SELECT
  organization_id,
  COALESCE(counterparty_id, '00000000-0000-0000-0000-000000000000'::uuid) AS counterparty_key,
  calc_kind,
  btrim(inputs->>'financing_instance_id') AS financing_instance_id,
  COALESCE(
    NULLIF(btrim(inputs->>'reporting_year'), ''),
    NULLIF(btrim(inputs->>'reportingYear'), ''),
    ''
  ) AS reporting_year_key,
  count(*) AS row_count
FROM app.financed_emissions
WHERE lower(COALESCE(formula_id, '')) <> 'aggregate'
  AND NULLIF(btrim(inputs->>'financing_instance_id'), '') IS NOT NULL
GROUP BY 1, 2, 3, 4, 5
HAVING count(*) > 1
ORDER BY row_count DESC;

-- 4. Historical compatibility: how many identified rows have no reporting year in JSON.
SELECT
  count(*) FILTER (
    WHERE NULLIF(btrim(inputs->>'reporting_year'), '') IS NULL
      AND NULLIF(btrim(inputs->>'reportingYear'), '') IS NULL
  ) AS rows_without_year,
  count(*) FILTER (
    WHERE COALESCE(
      NULLIF(btrim(inputs->>'reporting_year'), ''),
      NULLIF(btrim(inputs->>'reportingYear'), '')
    ) IS NOT NULL
  ) AS rows_with_year,
  count(*) AS total_rows
FROM app.financed_emissions
WHERE lower(COALESCE(formula_id, '')) <> 'aggregate'
  AND NULLIF(btrim(inputs->>'financing_instance_id'), '') IS NOT NULL;

-- 5. 0016 UoP draft tables must remain non-reportable (not part of 0017).
SELECT
  'uop_investments' AS table_name,
  count(*) FILTER (WHERE is_reportable OR include_in_portfolio) AS reportable_rows
FROM app.uop_investments
UNION ALL
SELECT
  'uop_asset_calculations',
  count(*) FILTER (WHERE is_reportable OR include_in_portfolio)
FROM app.uop_asset_calculations;
