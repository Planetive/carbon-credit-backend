-- =============================================================================
-- REVIEW ONLY — do not execute without explicit approval.
-- Scope 3 Stage 5: structured waste factor-unit metadata for verified Cat 5/12.
--
-- Why: Stage 4 COMMENT ON TABLE / uncommitted transactions are NOT proof of
-- factor verification. Verified waste saves require a readable metadata row
-- with the exact unit string used by the calculator.
--
-- This script:
--   - Creates public.waste_factor_unit_metadata (if missing)
--   - Upserts dataset_code=waste with factor_unit=MTCO2e/short ton
--   - Does NOT change public.waste numeric factor values
--   - Does NOT mark annual Scope 3 results verified
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS public.waste_factor_unit_metadata (
  dataset_code text PRIMARY KEY,
  factor_unit text NOT NULL,
  mass_activity_unit text NOT NULL DEFAULT 'kg',
  source_note text NOT NULL,
  treatment_methods text[] NOT NULL DEFAULT ARRAY[
    'Recycled',
    'Landfilled',
    'Combusted',
    'Composted',
    'Anaerobically Digested (Dry Digestate with Curing)',
    'Anaerobically Digested (Wet Digestate with Curing)'
  ],
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO public.waste_factor_unit_metadata (
  dataset_code,
  factor_unit,
  mass_activity_unit,
  source_note
)
VALUES (
  'waste',
  'MTCO2e/short ton',
  'kg',
  'EPA GHG Emission Factors Hub / WARM-style disposal intensities. '
  'Unit confirmed for the waste sheet; NA cells remain not applicable. '
  'Not an annual verification flag.'
)
ON CONFLICT (dataset_code) DO UPDATE
SET
  factor_unit = EXCLUDED.factor_unit,
  mass_activity_unit = EXCLUDED.mass_activity_unit,
  source_note = EXCLUDED.source_note,
  updated_at = now();

COMMENT ON TABLE public.waste_factor_unit_metadata IS
  'Authoritative unit metadata for verified Scope 3 waste calculations. '
  'Application refuses Cat 5/12 verified saves when this row is absent.';

ROLLBACK;
-- Change ROLLBACK to COMMIT only after human review.
