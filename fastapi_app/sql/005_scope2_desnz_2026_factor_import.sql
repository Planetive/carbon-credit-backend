-- REVIEW ONLY. Do not run this file from the application and do not apply it to production
-- as part of a code deploy. It is a reviewed data load for ref.factor_datasets and ref.factor_rows.
--
-- Replaces 005_scope2_desnz_2025_2026_factor_import.sql. That file is withdrawn.
-- This script inserts two DESNZ 2026 Scope 2 rows and nothing else:
--   UK electricity generated, 0.13096 kg CO2e/kWh
--   UK district heat and steam, 0.17529 kg CO2e/kWh
--
-- 2025 rows are not inserted. This script does not UPDATE or DELETE any dataset,
-- factor row, or emissions record. A 2025 factor that is already stored stays as it is.
--
-- Checked against the DESNZ 2026 full set and the revised flat file:
--   UK electricity, Electricity generated, Electricity: UK, kWh, year 2026, kg CO2e 0.13096
--   Flat-file ID 7_400_4000_5_1. Published 11 June 2026.
--   The 31 July 2026 flat-file correction did not change this cell.
--   Heat and steam, District heat and steam, kWh, year 2026, kg CO2e 0.17529
--   Flat-file ID 10_401_4003_5_1. The 2026 methodology holds this total at the 2025 published value.
-- 0.17355 is the CO2 component of the heat total and is not loaded as the factor.
-- Transmission and distribution, well-to-tank, on-site heat, Pakistan, and UAE rows are not loaded.
--
-- publication_year and reporting_year are both 2026. effective_from/effective_to cover 2026 only.
-- A request for another reporting year does not match these rows. The calculation engines
-- keep their own year checks and return a missing factor instead of reusing this edition.
--
-- A row is skipped when the same 2026 activity is already stored, or when the stable id
-- is already present. The UK engines read ref.factor_rows directly. No view is created here.
--
-- Schema, from db/migrations/0007_phase2c_factor_datasets_rows_etl.sql:
--   factor_datasets.code is UNIQUE. factor_rows.id is the primary key.
--   dataset_id references factor_datasets and is NOT NULL. category is NOT NULL.
--   attributes is NOT NULL jsonb. kg_co2e is numeric(20, 8).
--   There is no unique constraint on country, grid, or reporting year.
--   Duplicate prevention is the NOT EXISTS clause in each insert.
--   app_user and catalog_reader have SELECT only. migrator has ALL.
--   Run this as migrator or the table owner. The application role cannot insert.

INSERT INTO ref.factor_datasets (
    id, code, publisher, title, version_label,
    effective_from, effective_to, is_active, source_notes
)
SELECT
    'a4786746-5b46-5466-b878-acc5c9ab1e99'::uuid,
    'desnz_ghg_conversion_factors_2026',
    'Department for Energy Security and Net Zero (DESNZ)',
    'Greenhouse gas reporting: conversion factors 2026',
    '2026 full set and revised flat file',
    DATE '2026-01-01',
    DATE '2026-12-31',
    true,
    'Full set published 11 June 2026. Revised flat file dated 31 July 2026. The July correction did not change the electricity generated or district heat and steam cells loaded here. The 2025 edition is not loaded by this script.'
WHERE NOT EXISTS (
    SELECT 1 FROM ref.factor_datasets WHERE code = 'desnz_ghg_conversion_factors_2026'
);

INSERT INTO ref.factor_rows (
    id, dataset_id, category, label, attributes, unit,
    kg_co2e, kg_co2, kg_ch4, kg_n2o, meta
)
SELECT
    'fabac5f1-e547-52a3-b3d2-394eaa1c679d'::uuid,
    d.id,
    'purchased_electricity',
    'Electricity generated, Electricity: UK',
    jsonb_build_object(
        'verification', 'verified',
        'method', 'location_based',
        'boundary', 'electricity_generated',
        'source_document', 'Greenhouse gas reporting: conversion factors 2026, full set and revised flat file, UK electricity, Electricity generated, Electricity: UK, kWh. Flat-file ID 7_400_4000_5_1. Published 11 June 2026. The 31 July 2026 flat-file correction did not change this cell.',
        'publication_year', 2026,
        'reporting_year', 2026,
        'country', 'United Kingdom',
        'grid_region', 'national',
        'gas_coverage', 'CO2, CH4, and N2O, reported as kg CO2e',
        'flat_file_id', '7_400_4000_5_1',
        'official_grid_name', 'Electricity: UK',
        'kg_co2e_of_co2', '0.12943',
        'kg_co2e_of_ch4', '0.00067',
        'kg_co2e_of_n2o', '0.00086'
    ),
    'kg CO2e/kWh',
    0.13096,
    NULL,
    NULL,
    NULL,
    jsonb_build_object(
        'activity', 'Electricity generated',
        'measurement_boundary', 'generation_only',
        'scope', '2'
    )
FROM ref.factor_datasets d
WHERE d.code = 'desnz_ghg_conversion_factors_2026'
  AND (d.publisher ILIKE '%desnz%' OR d.publisher ILIKE '%energy security%')
  AND NOT EXISTS (
      SELECT 1 FROM ref.factor_rows existing WHERE existing.id = 'fabac5f1-e547-52a3-b3d2-394eaa1c679d'::uuid
  )
  AND NOT EXISTS (
      SELECT 1
      FROM ref.factor_rows existing
      WHERE existing.category = 'purchased_electricity'
        AND lower(existing.attributes->>'verification') = 'verified'
        AND lower(existing.attributes->>'boundary') IN ('electricity_generated', 'generation', 'generation_only')
        AND existing.attributes->>'reporting_year' = '2026'
        AND lower(replace(existing.attributes->>'country', '.', '')) IN ('united kingdom', 'uk', 'great britain', 'britain', 'gb')
        AND lower(existing.attributes->>'grid_region') = 'national'
  );

INSERT INTO ref.factor_rows (
    id, dataset_id, category, label, attributes, unit,
    kg_co2e, kg_co2, kg_ch4, kg_n2o, meta
)
SELECT
    '134a44da-d317-5773-bafc-e1a7734851b6'::uuid,
    d.id,
    'purchased_heat_steam',
    'District heat and steam',
    jsonb_build_object(
        'verification', 'verified',
        'method', 'purchased_energy',
        'boundary', 'district_heat',
        'source_document', 'Greenhouse gas reporting: conversion factors 2026, full set and revised flat file, Heat and steam, District heat and steam, kWh. Flat-file ID 10_401_4003_5_1. Published 11 June 2026. The 2026 methodology holds this factor at the 2025 published total.',
        'publication_year', 2026,
        'reporting_year', 2026,
        'country', 'United Kingdom',
        'gas_coverage', 'CO2, CH4, and N2O, reported as complete kg CO2e',
        'treatment', 'complete_co2e',
        'flat_file_id', '10_401_4003_5_1',
        'kg_co2e_of_co2', '0.17355',
        'kg_co2e_of_ch4', '0.00122',
        'kg_co2e_of_n2o', '0.00052'
    ),
    'kg CO2e/kWh',
    0.17529,
    NULL,
    NULL,
    NULL,
    jsonb_build_object(
        'activity', 'District heat and steam',
        'measurement_boundary', 'purchased_district_heat_and_steam',
        'scope', '2'
    )
FROM ref.factor_datasets d
WHERE d.code = 'desnz_ghg_conversion_factors_2026'
  AND (d.publisher ILIKE '%desnz%' OR d.publisher ILIKE '%energy security%')
  AND NOT EXISTS (
      SELECT 1 FROM ref.factor_rows existing WHERE existing.id = '134a44da-d317-5773-bafc-e1a7734851b6'::uuid
  )
  AND NOT EXISTS (
      SELECT 1
      FROM ref.factor_rows existing
      WHERE existing.category = 'purchased_heat_steam'
        AND lower(existing.attributes->>'verification') = 'verified'
        AND lower(existing.attributes->>'boundary') IN ('district_heat', 'purchased_heat', 'purchased_heat_steam')
        AND existing.attributes->>'reporting_year' = '2026'
        AND lower(replace(existing.attributes->>'country', '.', '')) IN ('united kingdom', 'uk', 'great britain', 'britain', 'gb')
  );
