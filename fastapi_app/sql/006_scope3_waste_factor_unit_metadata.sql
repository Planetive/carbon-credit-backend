-- =============================================================================
-- REVIEW ONLY — do not execute without explicit approval.
-- Scope 3 Stage 4: waste factor unit metadata (no numeric value changes).
--
-- Evidence: public.waste dump values match EPA GHG Emission Factors Hub / WARM
-- Table 9 style intensities in MTCO2e per short ton of material. The dump has
-- no Units column; Stage 2 application code already requires
-- factor_unit = 'MTCO2e/short ton' and mass_unit = 'kg'.
--
-- This script only attaches dataset-level metadata. It does NOT:
--   - change Recycled / Landfilled / Combusted / ... numeric values
--   - mark individual rows "verified" for annual reporting
--   - invent factors for materials with NA cells
-- =============================================================================

BEGIN;

COMMENT ON TABLE public.waste IS
  'EPA Hub / WARM-style waste disposal factors. Confirmed factor unit for all '
  'numeric disposal columns: MTCO2e/short ton of material. Mass activity in the '
  'calculator is kilograms (converted to short tons). NA cells mean method not '
  'applicable — do not invent values. Metadata-only; values unchanged by Stage 4.';

COMMENT ON COLUMN public.waste."Material" IS
  'Waste material / product type (activity classification).';

COMMENT ON COLUMN public.waste."Landfilled" IS
  'Factor unit: MTCO2e/short ton. NULL/NA = method not applicable.';

COMMENT ON COLUMN public.waste."Recycled" IS
  'Factor unit: MTCO2e/short ton when numeric. Text NA = not applicable.';

COMMENT ON COLUMN public.waste."Combusted" IS
  'Factor unit: MTCO2e/short ton when numeric. Text NA = not applicable.';

COMMENT ON COLUMN public.waste."Composted" IS
  'Factor unit: MTCO2e/short ton when numeric. Text NA = not applicable.';

COMMENT ON COLUMN public.waste."Anaerobically Digested (Dry Digestate with Curing)" IS
  'Factor unit: MTCO2e/short ton when numeric. Text NA = not applicable.';

-- Dump column may use double space before Digestate; comment the live name if present.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'waste'
      AND column_name = 'Anaerobically Digested (Wet Digestate with Curing)'
  ) THEN
    EXECUTE $c$
      COMMENT ON COLUMN public.waste."Anaerobically Digested (Wet Digestate with Curing)" IS
        'Factor unit: MTCO2e/short ton when numeric. Text NA = not applicable.'
    $c$;
  END IF;
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'waste'
      AND column_name = 'Anaerobically Digested (Wet  Digestate with Curing)'
  ) THEN
    EXECUTE $c$
      COMMENT ON COLUMN public.waste."Anaerobically Digested (Wet  Digestate with Curing)" IS
        'Factor unit: MTCO2e/short ton when numeric. Text NA = not applicable. '
        'Note: dump column name contains a double space before Digestate.'
    $c$;
  END IF;
END $$;

-- Optional companion metadata table (empty of invented factors). Safe to create;
-- does not alter public.waste numerics. Application continues to pass
-- WASTE_DATASET_FACTOR_UNIT explicitly until reporting-year integration.
CREATE TABLE IF NOT EXISTS public.waste_factor_unit_metadata (
  dataset_code text PRIMARY KEY DEFAULT 'waste',
  factor_unit text NOT NULL DEFAULT 'MTCO2e/short ton',
  mass_activity_unit text NOT NULL DEFAULT 'kg',
  source_note text NOT NULL DEFAULT
    'EPA GHG Emission Factors Hub / WARM-style table; unit confirmed from value pattern and Stage 2 audit. Not an annual verification flag.',
  created_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO public.waste_factor_unit_metadata (dataset_code)
VALUES ('waste')
ON CONFLICT (dataset_code) DO NOTHING;

COMMENT ON TABLE public.waste_factor_unit_metadata IS
  'Metadata-only: confirmed unit for public.waste. Does not verify annual Scope 3 results.';

ROLLBACK;
-- Change ROLLBACK to COMMIT only after human review.
