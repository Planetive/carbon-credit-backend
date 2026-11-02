-- Scope 2 purchased electricity factor contract.
-- DO NOT RUN this file from the application. Apply it only in a reviewed database change.
-- It creates a read-only view. It does not insert a factor value.
-- The hardcoded calculator value 0.425 is not a verified factor and is not loaded here.
-- IGCEP generation intensity is not a purchased-electricity consumption factor and is not loaded here.
-- A verified row has to be inserted by an authorized data load with its own source document.

CREATE OR REPLACE VIEW ref.scope2_purchased_electricity_factors AS
SELECT
    d.id AS dataset_id,
    d.code AS dataset_code,
    d.publisher,
    d.title,
    d.version_label,
    d.effective_from,
    d.effective_to,
    d.source_notes,
    r.id AS factor_row_id,
    r.category,
    r.label,
    r.unit,
    r.kg_co2e,
    r.kg_co2,
    r.kg_ch4,
    r.kg_n2o,
    r.attributes,
    r.attributes->>'source_document' AS source_document,
    r.attributes->>'publication_year' AS publication_year,
    r.attributes->>'reporting_year' AS reporting_year,
    r.attributes->>'country' AS country,
    r.attributes->>'grid_region' AS grid_region,
    r.attributes->>'boundary' AS boundary,
    r.attributes->>'method' AS method,
    r.attributes->>'gas_coverage' AS gas_coverage,
    r.attributes->>'verification' AS verification
FROM ref.factor_rows r
JOIN ref.factor_datasets d ON d.id = r.dataset_id
WHERE d.is_active
  AND r.category = 'purchased_electricity'
  AND r.attributes->>'verification' = 'verified'
  AND r.attributes->>'method' = 'location_based'
  AND r.attributes->>'boundary' IN ('consumption', 'purchased_electricity')
  AND COALESCE(d.publisher, '') NOT IN ('', 'legacy', 'placeholder', 'unverified')
  AND COALESCE(r.attributes->>'source_document', '') <> ''
  AND COALESCE(r.attributes->>'gas_coverage', '') <> ''
  AND COALESCE(r.attributes->>'publication_year', '') <> ''
  AND COALESCE(r.attributes->>'reporting_year', '') <> ''
  AND COALESCE(r.attributes->>'country', '') <> ''
  AND COALESCE(r.attributes->>'grid_region', '') <> '';
