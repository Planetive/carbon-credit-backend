-- CANONICAL Phase 5B migration (Phase 5B.1 safety-reviewed).
-- Apply from this backend file only.
-- DO NOT apply from the SPA copy. DO NOT run against production from this review.
-- DO NOT reuse 0014/0015. Next number after 0015_financed_scope_breakdown is 0016.
--
-- Target: EC2 Postgres (app schema). Hosted Supabase is not the ledger.
--
-- Prerequisites (verified by DO blocks below — do not rely on numbering alone):
--   * schema app + table app.financed_emissions must exist
--   * 0014 financing_instance unique index should already be present (identity contract)
--   * 0015 scope columns are NOT DDL-required by this file; they are process-adjacent
--     and already applied on the current EC2 ledger. This migration does not alter
--     app.financed_emissions.
--
-- PCAF 2025 Part A §5.7 Use of Proceeds — parent/child draft foundation:
--   * uop_structures          parent Separate/Integrated vehicle
--   * uop_investments         FI holding; identity is financing_instance_id
--   * uop_underlying_assets   look-through assets (asset_class is NOT unique)
--   * uop_asset_calculations  independent underlying calc records
--
-- Identity contract (first-class column; btrim-normalized like 0014 JSON path):
--   Unique investment =
--     (organization_id, COALESCE(counterparty_id, zero-uuid), btrim(financing_instance_id))
--   Note: unlike 0014, calc_kind is omitted because UoP holdings live outside
--   app.financed_emissions. formula_id remains methodology-only.
--
-- Double-count guard:
--   Investments and underlying calculation rows CHECK is_reportable = false AND
--   include_in_portfolio = false for Phase 5B drafts.
--   Do not UNION these tables into app.financed_emissions, dashboards, or Category 15.
--   Phase 5B never writes UoP rows to app.financed_emissions.
--
-- Draft revisions: Phase 5B upserts in place (draft_snapshot / status draft|in_progress).
-- Historical revision rows are intentionally out of scope for this migration.

BEGIN;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.schemata WHERE schema_name = 'app'
  ) THEN
    RAISE EXCEPTION '0016 abort: schema app does not exist';
  END IF;
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'app' AND table_name = 'financed_emissions'
  ) THEN
    RAISE EXCEPTION '0016 abort: app.financed_emissions does not exist';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_proc WHERE proname = 'gen_random_uuid'
  ) THEN
    RAISE EXCEPTION '0016 abort: gen_random_uuid() is unavailable';
  END IF;
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'organizations'
  ) THEN
    RAISE EXCEPTION '0016 abort: public.organizations does not exist';
  END IF;
END
$$;

CREATE TABLE IF NOT EXISTS app.uop_structures (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL
    REFERENCES public.organizations (id),
  user_id uuid NOT NULL,
  counterparty_id uuid
    REFERENCES public.counterparties (id) ON DELETE SET NULL,
  name text NOT NULL DEFAULT '',
  issuer_name text NOT NULL DEFAULT '',
  structure_kind text NOT NULL DEFAULT '',
  classification text,
  eligibility jsonb NOT NULL DEFAULT '{}'::jsonb,
  total_structure_debt numeric(20, 8),
  total_structure_equity numeric(20, 8),
  reporting_year text,
  methodology_version text NOT NULL DEFAULT 'PCAF-2025-PartA-5.7',
  currency text NOT NULL DEFAULT 'PKR',
  evidence_source text NOT NULL DEFAULT '',
  evidence_notes text NOT NULL DEFAULT '',
  allocation_status text,
  allocated_proceeds numeric(20, 8),
  unallocated_proceeds numeric(20, 8),
  expected_allocation_evidence text NOT NULL DEFAULT '',
  unallocated_uses_asset_level_estimate text,
  emissions_path text,
  issuer_level_reason text,
  issuer_reported_financed_emissions numeric(20, 8),
  issuer_report_year text,
  issuer_report_verification text,
  issuer_report_source text NOT NULL DEFAULT '',
  status text NOT NULL DEFAULT 'draft',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uop_structures_classification_chk
    CHECK (classification IS NULL OR classification IN ('separate', 'integrated')),
  CONSTRAINT uop_structures_emissions_path_chk
    CHECK (
      emissions_path IS NULL
      OR emissions_path IN ('issuer_reported', 'underlying_assets', 'estimation')
    ),
  CONSTRAINT uop_structures_allocation_status_chk
    CHECK (
      allocation_status IS NULL
      OR allocation_status IN ('known', 'unknown', 'none_yet')
    ),
  CONSTRAINT uop_structures_status_chk
    CHECK (status IN ('draft', 'in_progress')),
  CONSTRAINT uop_structures_structure_kind_chk
    CHECK (
      structure_kind IN (
        '',
        'equity-fund',
        'debt-fund',
        'holding-spv-without-control',
        'labeled-bond',
        'labeled-loan',
        'multi-asset-loan',
        'other'
      )
    )
);

COMMENT ON TABLE app.uop_structures IS
  'PCAF 2025 §5.7 Use of Proceeds parent structure (Separate or Integrated). Not a reportable financed-emissions row.';
COMMENT ON COLUMN app.uop_structures.classification IS
  'separate | integrated. NULL while the Figure 5.7-2 questionnaire is incomplete.';
COMMENT ON COLUMN app.uop_structures.methodology_version IS
  'PCAF methodology edition for this structure. Default PCAF-2025-PartA-5.7.';

CREATE INDEX IF NOT EXISTS ix_uop_structures_organization_id
  ON app.uop_structures (organization_id);
CREATE INDEX IF NOT EXISTS ix_uop_structures_counterparty_id
  ON app.uop_structures (counterparty_id);

CREATE TABLE IF NOT EXISTS app.uop_investments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL
    REFERENCES public.organizations (id),
  user_id uuid NOT NULL,
  structure_id uuid NOT NULL REFERENCES app.uop_structures (id) ON DELETE CASCADE,
  counterparty_id uuid
    REFERENCES public.counterparties (id) ON DELETE SET NULL,
  exposure_id uuid
    REFERENCES public.exposures (id) ON DELETE SET NULL,
  financing_instance_id text NOT NULL,
  instance_key text,
  investment_type text,
  outstanding_amount numeric(20, 8),
  formula_id text,
  formula_name text,
  status text NOT NULL DEFAULT 'draft',
  is_reportable boolean NOT NULL DEFAULT false,
  include_in_portfolio boolean NOT NULL DEFAULT false,
  draft_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uop_investments_financing_instance_id_chk
    CHECK (NULLIF(btrim(financing_instance_id), '') IS NOT NULL),
  CONSTRAINT uop_investments_investment_type_chk
    CHECK (investment_type IS NULL OR investment_type IN ('debt', 'equity')),
  CONSTRAINT uop_investments_status_chk
    CHECK (status IN ('draft', 'in_progress')),
  -- Phase 5B drafts must not enter portfolio / Category 15 totals.
  CONSTRAINT uop_investments_not_portfolio_chk
    CHECK (include_in_portfolio IS FALSE),
  CONSTRAINT uop_investments_not_reportable_chk
    CHECK (is_reportable IS FALSE)
);

COMMENT ON TABLE app.uop_investments IS
  'Financial-institution holding in a UoP structure. Unique by financing_instance_id, never by formula_id. Phase 5B drafts are not reportable.';
COMMENT ON COLUMN app.uop_investments.financing_instance_id IS
  'Stable loan/investment identity. Same btrim contract as app.financed_emissions inputs.financing_instance_id. Not formula_id.';
COMMENT ON COLUMN app.uop_investments.formula_id IS
  'Methodology annotation only. Must not be used as a unique exposure key.';
COMMENT ON COLUMN app.uop_investments.exposure_id IS
  'FK to public.exposures.id only — not financing_instance_id.';
COMMENT ON COLUMN app.uop_investments.is_reportable IS
  'Phase 5B CHECK-forced false. A later migration may relax this for parent holdings only; underlying calculation rows must stay false.';
COMMENT ON COLUMN app.uop_investments.include_in_portfolio IS
  'Phase 5B CHECK-forced false so dashboards and Category 15 cannot pick up draft holdings.';

CREATE UNIQUE INDEX IF NOT EXISTS uq_uop_investments_financing_instance
  ON app.uop_investments (
    organization_id,
    COALESCE(counterparty_id, '00000000-0000-0000-0000-000000000000'::uuid),
    btrim(financing_instance_id)
  );

CREATE INDEX IF NOT EXISTS ix_uop_investments_organization_id
  ON app.uop_investments (organization_id);
CREATE INDEX IF NOT EXISTS ix_uop_investments_structure_id
  ON app.uop_investments (structure_id);
CREATE INDEX IF NOT EXISTS ix_uop_investments_financing_instance_id
  ON app.uop_investments (btrim(financing_instance_id));

CREATE TABLE IF NOT EXISTS app.uop_underlying_assets (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL
    REFERENCES public.organizations (id),
  structure_id uuid NOT NULL REFERENCES app.uop_structures (id) ON DELETE CASCADE,
  underlying_asset_id text NOT NULL,
  name text NOT NULL DEFAULT '',
  asset_class text NOT NULL DEFAULT '',
  sort_order integer NOT NULL DEFAULT 0,
  allocated_outstanding numeric(20, 8),
  total_asset_value numeric(20, 8),
  has_reported_emissions text,
  verification_status text,
  verifier_name text NOT NULL DEFAULT '',
  scope1_emissions numeric(20, 8),
  scope2_emissions numeric(20, 8),
  scope3_emissions numeric(20, 8),
  data_source text NOT NULL DEFAULT '',
  evidence_notes text NOT NULL DEFAULT '',
  estimation jsonb NOT NULL DEFAULT '{}'::jsonb,
  inputs jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uop_underlying_assets_id_chk
    CHECK (NULLIF(btrim(underlying_asset_id), '') IS NOT NULL)
);

COMMENT ON TABLE app.uop_underlying_assets IS
  'Look-through assets of a UoP structure. Multiple rows may share the same asset_class. Identity is underlying_asset_id per structure, not formula_id.';
COMMENT ON COLUMN app.uop_underlying_assets.underlying_asset_id IS
  'Stable frontend UUID for this asset. Unique per structure (btrim). Not formula_id.';
COMMENT ON COLUMN app.uop_underlying_assets.asset_class IS
  'PCAF asset class of the underlying. Intentionally not unique — two mortgages in one structure are allowed.';

CREATE UNIQUE INDEX IF NOT EXISTS uq_uop_underlying_assets_structure_asset
  ON app.uop_underlying_assets (structure_id, btrim(underlying_asset_id));

CREATE INDEX IF NOT EXISTS ix_uop_underlying_assets_structure_id
  ON app.uop_underlying_assets (structure_id);
CREATE INDEX IF NOT EXISTS ix_uop_underlying_assets_organization_id
  ON app.uop_underlying_assets (organization_id);
CREATE INDEX IF NOT EXISTS ix_uop_underlying_assets_asset_class
  ON app.uop_underlying_assets (structure_id, asset_class);

CREATE TABLE IF NOT EXISTS app.uop_asset_calculations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL
    REFERENCES public.organizations (id),
  structure_id uuid NOT NULL REFERENCES app.uop_structures (id) ON DELETE CASCADE,
  asset_id uuid NOT NULL REFERENCES app.uop_underlying_assets (id) ON DELETE CASCADE,
  investment_id uuid REFERENCES app.uop_investments (id) ON DELETE CASCADE,
  reporting_year text,
  methodology_version text NOT NULL DEFAULT 'PCAF-2025-PartA-5.7',
  formula_id text,
  status text NOT NULL DEFAULT 'draft',
  inputs jsonb NOT NULL DEFAULT '{}'::jsonb,
  results jsonb NOT NULL DEFAULT '{}'::jsonb,
  financed_emissions numeric(20, 6),
  attribution_factor numeric(20, 8),
  data_quality_score numeric(10, 4),
  financed_scope1_tco2e numeric(20, 6),
  financed_scope2_tco2e numeric(20, 6),
  financed_scope3_tco2e numeric(20, 6),
  include_in_portfolio boolean NOT NULL DEFAULT false,
  is_reportable boolean NOT NULL DEFAULT false,
  provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uop_asset_calculations_status_chk
    CHECK (status IN ('draft', 'in_progress')),
  CONSTRAINT uop_asset_calculations_not_portfolio_chk
    CHECK (include_in_portfolio IS FALSE),
  CONSTRAINT uop_asset_calculations_not_reportable_chk
    CHECK (is_reportable IS FALSE)
);

COMMENT ON TABLE app.uop_asset_calculations IS
  'Independent look-through calculation records. CHECK-forced not reportable and not portfolio. Must not be summed into Category 15 or dashboards.';
COMMENT ON COLUMN app.uop_asset_calculations.formula_id IS
  'Underlying-class methodology key only. Not a unique exposure identifier.';
COMMENT ON COLUMN app.uop_asset_calculations.investment_id IS
  'Optional holding this look-through belongs to, so two investments in the same structure can recalculate independently.';
COMMENT ON COLUMN app.uop_asset_calculations.is_reportable IS
  'Always false. Underlying rows are never reportable parent results.';
COMMENT ON COLUMN app.uop_asset_calculations.include_in_portfolio IS
  'Always false. Prevents dashboard / Category 15 double-count of look-through components.';

-- One draft/in-progress calc per (asset, investment, reporting year, methodology).
-- In-place upsert covers Phase 5B draft revisions; historical revision rows are out of scope.
CREATE UNIQUE INDEX IF NOT EXISTS uq_uop_asset_calculations_identity
  ON app.uop_asset_calculations (
    asset_id,
    COALESCE(investment_id, '00000000-0000-0000-0000-000000000000'::uuid),
    COALESCE(NULLIF(btrim(reporting_year), ''), ''),
    methodology_version
  );

CREATE INDEX IF NOT EXISTS ix_uop_asset_calculations_organization_id
  ON app.uop_asset_calculations (organization_id);
CREATE INDEX IF NOT EXISTS ix_uop_asset_calculations_structure_id
  ON app.uop_asset_calculations (structure_id);
CREATE INDEX IF NOT EXISTS ix_uop_asset_calculations_asset_id
  ON app.uop_asset_calculations (asset_id);
CREATE INDEX IF NOT EXISTS ix_uop_asset_calculations_investment_id
  ON app.uop_asset_calculations (investment_id);

-- Defense in depth: child organization_id must match parent structure.
CREATE OR REPLACE FUNCTION app.uop_enforce_org_match()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  parent_org uuid;
BEGIN
  SELECT organization_id INTO parent_org
  FROM app.uop_structures
  WHERE id = NEW.structure_id;

  IF parent_org IS NULL THEN
    RAISE EXCEPTION 'uop org match: structure % not found', NEW.structure_id;
  END IF;
  IF NEW.organization_id IS DISTINCT FROM parent_org THEN
    RAISE EXCEPTION
      'uop org match: child organization_id % != structure organization_id %',
      NEW.organization_id, parent_org;
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_uop_investments_org_match ON app.uop_investments;
CREATE TRIGGER trg_uop_investments_org_match
  BEFORE INSERT OR UPDATE OF organization_id, structure_id
  ON app.uop_investments
  FOR EACH ROW
  EXECUTE FUNCTION app.uop_enforce_org_match();

DROP TRIGGER IF EXISTS trg_uop_underlying_assets_org_match ON app.uop_underlying_assets;
CREATE TRIGGER trg_uop_underlying_assets_org_match
  BEFORE INSERT OR UPDATE OF organization_id, structure_id
  ON app.uop_underlying_assets
  FOR EACH ROW
  EXECUTE FUNCTION app.uop_enforce_org_match();

DROP TRIGGER IF EXISTS trg_uop_asset_calculations_org_match ON app.uop_asset_calculations;
CREATE TRIGGER trg_uop_asset_calculations_org_match
  BEFORE INSERT OR UPDATE OF organization_id, structure_id
  ON app.uop_asset_calculations
  FOR EACH ROW
  EXECUTE FUNCTION app.uop_enforce_org_match();

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
    GRANT SELECT, INSERT, UPDATE, DELETE ON
      app.uop_structures,
      app.uop_investments,
      app.uop_underlying_assets,
      app.uop_asset_calculations
    TO app_user;
  END IF;
END
$$;

INSERT INTO public.schema_migrations (version, description)
VALUES (
  '0016_uop_structures',
  'PCAF 2025 §5.7 UoP parent/child draft tables; financing_instance_id identity; underlying calcs not reportable'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
