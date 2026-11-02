-- Phase 2B/2C: financing_instance_id uniqueness for non-aggregate financed rows.
--
-- DO NOT RUN against production from this task without an explicit ops review.
-- Confirm indexes/constraints on app.financed_emissions before applying.
--
-- Semantics (aligned with SPA + Phase 2C safety review):
--   Unique active identity =
--     (organization_id, counterparty_id, calc_kind, btrim(inputs.financing_instance_id))
--   Applies only when btrim(financing_instance_id) is present and non-empty.
--   Aggregates excluded case-insensitively:
--     lower(COALESCE(formula_id, '')) <> 'aggregate'
--   Legacy rows without financing_instance_id are intentionally excluded
--   (NULL/absent keys do not participate — no silent rewrite of history).
--
-- Prerequisite: resolve any pre-existing duplicate active instance ids, e.g.:
--   SELECT organization_id, counterparty_id, calc_kind,
--          btrim(inputs->>'financing_instance_id') AS fid, count(*)
--   FROM app.financed_emissions
--   WHERE lower(COALESCE(formula_id, '')) <> 'aggregate'
--     AND NULLIF(btrim(inputs->>'financing_instance_id'), '') IS NOT NULL
--   GROUP BY 1,2,3,4
--   HAVING count(*) > 1;

BEGIN;

-- Expression unique index: one non-aggregate row per financing instance.
-- counterparty_id NULL is coalesced so NULL counterparties still collide safely.
-- Index expression AND predicate both use btrim() so whitespace variants collide.
CREATE UNIQUE INDEX IF NOT EXISTS uq_financed_emissions_financing_instance
ON app.financed_emissions (
  organization_id,
  COALESCE(counterparty_id, '00000000-0000-0000-0000-000000000000'::uuid),
  calc_kind,
  (btrim(inputs->>'financing_instance_id'))
)
WHERE
  NULLIF(btrim(inputs->>'financing_instance_id'), '') IS NOT NULL
  AND lower(COALESCE(formula_id, '')) <> 'aggregate';

COMMENT ON INDEX app.uq_financed_emissions_financing_instance IS
  'One non-aggregate financed row per (org, counterparty, calc_kind, btrim(financing_instance_id)). Legacy/aggregate (case-insensitive) rows excluded.';

-- Optional lookup helper (non-unique) for filters / GET-by-instance.
-- Expression uses btrim() to match unique-index normalization.
CREATE INDEX IF NOT EXISTS ix_financed_emissions_financing_instance_id
ON app.financed_emissions ((btrim(inputs->>'financing_instance_id')))
WHERE NULLIF(btrim(inputs->>'financing_instance_id'), '') IS NOT NULL;

INSERT INTO public.schema_migrations (version, description)
VALUES (
  '0014_financed_emissions_financing_instance',
  'Unique index for btrim(financing_instance_id) on non-aggregate financed_emissions'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
