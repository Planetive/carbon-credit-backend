-- Scope 1 activity-based screening answers (Yes/No/pending/calculated).
-- Apply on EC2 via pgAdmin / psql. SPA + FastAPI both expect this column.

BEGIN;

ALTER TABLE public.emission_calculator_preferences
  ADD COLUMN IF NOT EXISTS scope1_screening JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN public.emission_calculator_preferences.scope1_screening IS
  'Activity-group screening: { stationary, vehicles_mobile, leaks_releases, industrial_other }
   each in (not_assessed | not_applicable | applicable_pending | calculated).';

INSERT INTO public.schema_migrations (version, description)
VALUES (
  '0013_scope1_activity_screening',
  'Add scope1_screening jsonb to emission_calculator_preferences for activity-based Scope 1'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
