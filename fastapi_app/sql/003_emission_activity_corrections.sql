-- Versioned EPA stationary corrections.
-- Review this file before running it. The reconciliation script does not execute it.
-- It does not update app.emission_activities, company_emissions,
-- counterparty_questionnaires, emission_calculations, or financed_emissions.

BEGIN;

CREATE TABLE IF NOT EXISTS app.emission_activity_corrections (
    id uuid PRIMARY KEY,
    batch_id uuid NOT NULL,
    activity_id uuid NOT NULL,
    group_id text NOT NULL,
    member_activity_ids uuid[] NOT NULL,
    correction_hash text NOT NULL,
    original_emissions_tco2e numeric(20, 8),
    corrected_total_tco2e numeric(20, 8) NOT NULL,
    corrected_gases jsonb NOT NULL,
    factor_source jsonb NOT NULL,
    status text NOT NULL CHECK (status IN ('applied', 'reverted')),
    created_at timestamptz NOT NULL DEFAULT now(),
    reverted_at timestamptz
);

CREATE INDEX IF NOT EXISTS idx_emission_activity_corrections_batch
    ON app.emission_activity_corrections (batch_id);

CREATE INDEX IF NOT EXISTS idx_emission_activity_corrections_members
    ON app.emission_activity_corrections USING gin (member_activity_ids);

CREATE UNIQUE INDEX IF NOT EXISTS uq_emission_activity_corrections_active_primary
    ON app.emission_activity_corrections (activity_id)
    WHERE status = 'applied';

COMMIT;
