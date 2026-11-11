-- CANONICAL Phase 6B migration.
-- Apply from this backend file only after human review.
-- DO NOT apply from the SPA copy. DO NOT run against production from this review.
-- Next number after 0019_uop_overlap_reviews is 0020.
--
-- PCAF 2025 Part A §5.8 Securitization & Structured Products — draft foundation:
--   * ssp_deals                 shared deal / structure
--   * ssp_holdings              FI investment; identity is financing_instance_id
--   * ssp_collateral            underlying collateral assets
--   * ssp_loans                 underlying loans
--   * ssp_loan_collateral       M:N loan ↔ collateral (deal-scoped composite FKs)
--   * ssp_pools / ssp_pool_loans
--   * ssp_pool_of_pools / ssp_pool_of_pools_members
--   * ssp_tranches / ssp_tranche_pools
--   * ssp_calculations          child provenance; never reportable
--
-- Hierarchy integrity (Phase 6B.2):
--   Association rows carry deal_id + organization_id and composite FKs so a loan
--   cannot link collateral (or a pool link a loan, etc.) from another deal.
--   Org-match triggers cover entity tables and association tables.
--
-- Phase 6B never writes SSP rows to app.financed_emissions.
-- Calculate / reportable Save stay disabled in application code.
--
-- Amendment note (6B.2): this file remains prepared-only / unapplied to staging
-- and production. Composite association FKs + association org-match triggers were
-- added here before any environment application.

BEGIN;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.schemata WHERE schema_name = 'app'
  ) THEN
    RAISE EXCEPTION '0020 abort: schema app does not exist';
  END IF;
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'app' AND table_name = 'financed_emissions'
  ) THEN
    RAISE EXCEPTION '0020 abort: app.financed_emissions does not exist';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_proc WHERE proname = 'gen_random_uuid'
  ) THEN
    RAISE EXCEPTION '0020 abort: gen_random_uuid() is unavailable';
  END IF;
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'organizations'
  ) THEN
    RAISE EXCEPTION '0020 abort: public.organizations does not exist';
  END IF;
END
$$;

CREATE TABLE IF NOT EXISTS app.ssp_deals (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES public.organizations (id),
  user_id uuid NOT NULL,
  counterparty_id uuid REFERENCES public.counterparties (id) ON DELETE SET NULL,
  deal_key text,
  deal_name text NOT NULL DEFAULT '',
  deal_identifier text NOT NULL DEFAULT '',
  issuer_name text NOT NULL DEFAULT '',
  originator_name text NOT NULL DEFAULT '',
  spv_name text NOT NULL DEFAULT '',
  structure_type text NOT NULL DEFAULT '',
  reporting_year text,
  methodology_version text NOT NULL DEFAULT 'PCAF-2025-PartA-5.8',
  currency text NOT NULL DEFAULT 'PKR',
  documentation_source text NOT NULL DEFAULT '',
  eligibility jsonb NOT NULL DEFAULT '{}'::jsonb,
  emissions_path text,
  has_tranches text,
  has_pool_of_pools text,
  collateral_remains_with_originator text,
  pools_linked_to_specific_tranches text,
  shared_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'draft',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ssp_deals_status_chk CHECK (status IN ('draft', 'in_progress')),
  CONSTRAINT ssp_deals_emissions_path_chk
    CHECK (emissions_path IS NULL OR emissions_path IN ('lookthrough', 'reported_pool')),
  CONSTRAINT ssp_deals_yes_no_chk
    CHECK (
      (has_tranches IS NULL OR has_tranches IN ('yes', 'no'))
      AND (has_pool_of_pools IS NULL OR has_pool_of_pools IN ('yes', 'no'))
      AND (
        collateral_remains_with_originator IS NULL
        OR collateral_remains_with_originator IN ('yes', 'no')
      )
      AND (
        pools_linked_to_specific_tranches IS NULL
        OR pools_linked_to_specific_tranches IN ('yes', 'no')
      )
    )
);

COMMENT ON TABLE app.ssp_deals IS
  'PCAF 2025 §5.8 securitization deal (shared). Not a reportable financed-emissions row.';

CREATE INDEX IF NOT EXISTS ix_ssp_deals_organization_id ON app.ssp_deals (organization_id);
CREATE INDEX IF NOT EXISTS ix_ssp_deals_counterparty_id ON app.ssp_deals (counterparty_id);
CREATE INDEX IF NOT EXISTS ix_ssp_deals_reporting_year ON app.ssp_deals (organization_id, reporting_year);

CREATE TABLE IF NOT EXISTS app.ssp_holdings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES public.organizations (id),
  user_id uuid NOT NULL,
  deal_id uuid NOT NULL REFERENCES app.ssp_deals (id) ON DELETE CASCADE,
  counterparty_id uuid REFERENCES public.counterparties (id) ON DELETE SET NULL,
  exposure_id uuid REFERENCES public.exposures (id) ON DELETE SET NULL,
  financing_instance_id text NOT NULL,
  instance_key text,
  holding_name text NOT NULL DEFAULT '',
  tranche_client_id text,
  bank_outstanding_investment numeric(20, 8),
  currency text NOT NULL DEFAULT 'PKR',
  formula_id text,
  formula_name text,
  status text NOT NULL DEFAULT 'draft',
  is_reportable boolean NOT NULL DEFAULT false,
  include_in_portfolio boolean NOT NULL DEFAULT false,
  draft_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ssp_holdings_financing_instance_id_chk
    CHECK (NULLIF(btrim(financing_instance_id), '') IS NOT NULL),
  CONSTRAINT ssp_holdings_status_chk CHECK (status IN ('draft', 'in_progress')),
  CONSTRAINT ssp_holdings_not_portfolio_chk CHECK (include_in_portfolio IS FALSE),
  CONSTRAINT ssp_holdings_not_reportable_chk CHECK (is_reportable IS FALSE)
);

COMMENT ON TABLE app.ssp_holdings IS
  'FI holding in an SSP deal. Unique by financing_instance_id. Phase 6B drafts are not reportable.';
COMMENT ON COLUMN app.ssp_holdings.financing_instance_id IS
  'Stable investment identity. Same btrim contract as app.financed_emissions inputs.financing_instance_id.';

CREATE UNIQUE INDEX IF NOT EXISTS uq_ssp_holdings_financing_instance
  ON app.ssp_holdings (
    organization_id,
    COALESCE(counterparty_id, '00000000-0000-0000-0000-000000000000'::uuid),
    btrim(financing_instance_id)
  );

CREATE INDEX IF NOT EXISTS ix_ssp_holdings_organization_id ON app.ssp_holdings (organization_id);
CREATE INDEX IF NOT EXISTS ix_ssp_holdings_deal_id ON app.ssp_holdings (deal_id);

CREATE TABLE IF NOT EXISTS app.ssp_collateral (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES public.organizations (id),
  deal_id uuid NOT NULL REFERENCES app.ssp_deals (id) ON DELETE CASCADE,
  collateral_id text NOT NULL,
  name text NOT NULL DEFAULT '',
  collateral_type text NOT NULL DEFAULT '',
  attribution_denominator numeric(20, 8),
  denominator_label text NOT NULL DEFAULT '',
  current_outstanding_amount numeric(20, 8),
  original_outstanding_amount numeric(20, 8),
  asset_value_at_origination numeric(20, 8),
  updated_asset_value numeric(20, 8),
  pcaf_method_option text NOT NULL DEFAULT '',
  emissions_path text,
  scope1_emissions numeric(20, 8),
  scope2_emissions numeric(20, 8),
  scope3_emissions numeric(20, 8),
  data_quality_score numeric(10, 4),
  factor_library_entry_id text NOT NULL DEFAULT '',
  class_inputs jsonb NOT NULL DEFAULT '{}'::jsonb,
  evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
  sort_order integer NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ssp_collateral_id_chk CHECK (NULLIF(btrim(collateral_id), '') IS NOT NULL)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_ssp_collateral_deal_asset
  ON app.ssp_collateral (deal_id, btrim(collateral_id));
CREATE INDEX IF NOT EXISTS ix_ssp_collateral_deal_id ON app.ssp_collateral (deal_id);
-- Supports composite FKs from association tables (same deal).
CREATE UNIQUE INDEX IF NOT EXISTS uq_ssp_collateral_id_deal
  ON app.ssp_collateral (id, deal_id);

CREATE TABLE IF NOT EXISTS app.ssp_loans (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES public.organizations (id),
  deal_id uuid NOT NULL REFERENCES app.ssp_deals (id) ON DELETE CASCADE,
  loan_id text NOT NULL,
  name text NOT NULL DEFAULT '',
  current_outstanding_amount numeric(20, 8),
  original_outstanding_amount numeric(20, 8),
  notes text NOT NULL DEFAULT '',
  evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
  sort_order integer NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ssp_loans_id_chk CHECK (NULLIF(btrim(loan_id), '') IS NOT NULL)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_ssp_loans_deal_loan
  ON app.ssp_loans (deal_id, btrim(loan_id));
CREATE INDEX IF NOT EXISTS ix_ssp_loans_deal_id ON app.ssp_loans (deal_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_ssp_loans_id_deal
  ON app.ssp_loans (id, deal_id);

CREATE TABLE IF NOT EXISTS app.ssp_loan_collateral (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES public.organizations (id),
  deal_id uuid NOT NULL REFERENCES app.ssp_deals (id) ON DELETE CASCADE,
  loan_row_id uuid NOT NULL,
  collateral_row_id uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_ssp_loan_collateral UNIQUE (loan_row_id, collateral_row_id),
  CONSTRAINT fk_ssp_loan_collateral_loan_deal
    FOREIGN KEY (loan_row_id, deal_id)
    REFERENCES app.ssp_loans (id, deal_id)
    ON DELETE CASCADE,
  CONSTRAINT fk_ssp_loan_collateral_collateral_deal
    FOREIGN KEY (collateral_row_id, deal_id)
    REFERENCES app.ssp_collateral (id, deal_id)
    ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS app.ssp_pools (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES public.organizations (id),
  deal_id uuid NOT NULL REFERENCES app.ssp_deals (id) ON DELETE CASCADE,
  pool_id text NOT NULL,
  name text NOT NULL DEFAULT '',
  pool_current_outstanding_amount numeric(20, 8),
  reported_emissions_total numeric(20, 8),
  reported_emissions_period text NOT NULL DEFAULT '',
  reported_scope_coverage text NOT NULL DEFAULT '',
  reported_verification text,
  reported_source text NOT NULL DEFAULT '',
  evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
  sort_order integer NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ssp_pools_id_chk CHECK (NULLIF(btrim(pool_id), '') IS NOT NULL)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_ssp_pools_deal_pool
  ON app.ssp_pools (deal_id, btrim(pool_id));
CREATE INDEX IF NOT EXISTS ix_ssp_pools_deal_id ON app.ssp_pools (deal_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_ssp_pools_id_deal
  ON app.ssp_pools (id, deal_id);

CREATE TABLE IF NOT EXISTS app.ssp_pool_loans (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES public.organizations (id),
  deal_id uuid NOT NULL REFERENCES app.ssp_deals (id) ON DELETE CASCADE,
  pool_row_id uuid NOT NULL,
  loan_row_id uuid NOT NULL,
  -- Phase 6C.1: LAF numerator (loan COA allocated into this pool).
  amount_in_pool numeric(20, 8),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_ssp_pool_loans UNIQUE (pool_row_id, loan_row_id),
  CONSTRAINT fk_ssp_pool_loans_pool_deal
    FOREIGN KEY (pool_row_id, deal_id)
    REFERENCES app.ssp_pools (id, deal_id)
    ON DELETE CASCADE,
  CONSTRAINT fk_ssp_pool_loans_loan_deal
    FOREIGN KEY (loan_row_id, deal_id)
    REFERENCES app.ssp_loans (id, deal_id)
    ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS app.ssp_pool_of_pools (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES public.organizations (id),
  deal_id uuid NOT NULL REFERENCES app.ssp_deals (id) ON DELETE CASCADE,
  pool_of_pools_id text NOT NULL,
  name text NOT NULL DEFAULT '',
  current_outstanding_amount numeric(20, 8),
  evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ssp_pop_id_chk CHECK (NULLIF(btrim(pool_of_pools_id), '') IS NOT NULL)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_ssp_pool_of_pools_deal
  ON app.ssp_pool_of_pools (deal_id, btrim(pool_of_pools_id));
CREATE UNIQUE INDEX IF NOT EXISTS uq_ssp_pool_of_pools_id_deal
  ON app.ssp_pool_of_pools (id, deal_id);

CREATE TABLE IF NOT EXISTS app.ssp_pool_of_pools_members (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES public.organizations (id),
  deal_id uuid NOT NULL REFERENCES app.ssp_deals (id) ON DELETE CASCADE,
  pool_of_pools_row_id uuid NOT NULL,
  pool_row_id uuid NOT NULL,
  -- Reserved for deferred PoP weighting (Phase 6C.0B Q1). Unused in 6C.1.
  amount_in_pop numeric(20, 8),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_ssp_pop_members UNIQUE (pool_of_pools_row_id, pool_row_id),
  CONSTRAINT fk_ssp_pop_members_pop_deal
    FOREIGN KEY (pool_of_pools_row_id, deal_id)
    REFERENCES app.ssp_pool_of_pools (id, deal_id)
    ON DELETE CASCADE,
  CONSTRAINT fk_ssp_pop_members_pool_deal
    FOREIGN KEY (pool_row_id, deal_id)
    REFERENCES app.ssp_pools (id, deal_id)
    ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS app.ssp_tranches (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES public.organizations (id),
  deal_id uuid NOT NULL REFERENCES app.ssp_deals (id) ON DELETE CASCADE,
  tranche_id text NOT NULL,
  name text NOT NULL DEFAULT '',
  seniority_label text NOT NULL DEFAULT '',
  current_outstanding_amount numeric(20, 8),
  is_green_tranche text,
  is_virtual_overcollateralization boolean NOT NULL DEFAULT false,
  evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
  sort_order integer NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ssp_tranches_id_chk CHECK (NULLIF(btrim(tranche_id), '') IS NOT NULL)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_ssp_tranches_deal_tranche
  ON app.ssp_tranches (deal_id, btrim(tranche_id));
CREATE INDEX IF NOT EXISTS ix_ssp_tranches_deal_id ON app.ssp_tranches (deal_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_ssp_tranches_id_deal
  ON app.ssp_tranches (id, deal_id);

CREATE TABLE IF NOT EXISTS app.ssp_tranche_pools (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES public.organizations (id),
  deal_id uuid NOT NULL REFERENCES app.ssp_deals (id) ON DELETE CASCADE,
  tranche_row_id uuid NOT NULL,
  pool_row_id uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_ssp_tranche_pools UNIQUE (tranche_row_id, pool_row_id),
  CONSTRAINT fk_ssp_tranche_pools_tranche_deal
    FOREIGN KEY (tranche_row_id, deal_id)
    REFERENCES app.ssp_tranches (id, deal_id)
    ON DELETE CASCADE,
  CONSTRAINT fk_ssp_tranche_pools_pool_deal
    FOREIGN KEY (pool_row_id, deal_id)
    REFERENCES app.ssp_pools (id, deal_id)
    ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS app.ssp_calculations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES public.organizations (id),
  deal_id uuid NOT NULL REFERENCES app.ssp_deals (id) ON DELETE CASCADE,
  holding_id uuid REFERENCES app.ssp_holdings (id) ON DELETE CASCADE,
  collateral_row_id uuid REFERENCES app.ssp_collateral (id) ON DELETE CASCADE,
  reporting_year text,
  methodology_version text NOT NULL DEFAULT 'PCAF-2025-PartA-5.8',
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
  CONSTRAINT ssp_calculations_status_chk CHECK (status IN ('draft', 'in_progress')),
  CONSTRAINT ssp_calculations_not_portfolio_chk CHECK (include_in_portfolio IS FALSE),
  CONSTRAINT ssp_calculations_not_reportable_chk CHECK (is_reportable IS FALSE)
);

COMMENT ON TABLE app.ssp_calculations IS
  'SSP child/provenance calculation rows. CHECK-forced not reportable. Must not enter Category 15.';

CREATE UNIQUE INDEX IF NOT EXISTS uq_ssp_calculations_identity
  ON app.ssp_calculations (
    COALESCE(collateral_row_id, '00000000-0000-0000-0000-000000000000'::uuid),
    COALESCE(holding_id, '00000000-0000-0000-0000-000000000000'::uuid),
    COALESCE(NULLIF(btrim(reporting_year), ''), ''),
    methodology_version
  );

CREATE OR REPLACE FUNCTION app.ssp_enforce_org_match()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  parent_org uuid;
BEGIN
  SELECT organization_id INTO parent_org
  FROM app.ssp_deals
  WHERE id = NEW.deal_id;

  IF parent_org IS NULL THEN
    RAISE EXCEPTION 'ssp org match: deal % not found', NEW.deal_id;
  END IF;
  IF NEW.organization_id IS DISTINCT FROM parent_org THEN
    RAISE EXCEPTION
      'ssp org match: child organization_id % != deal organization_id %',
      NEW.organization_id, parent_org;
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_ssp_holdings_org_match ON app.ssp_holdings;
CREATE TRIGGER trg_ssp_holdings_org_match
  BEFORE INSERT OR UPDATE OF organization_id, deal_id
  ON app.ssp_holdings
  FOR EACH ROW
  EXECUTE FUNCTION app.ssp_enforce_org_match();

DROP TRIGGER IF EXISTS trg_ssp_collateral_org_match ON app.ssp_collateral;
CREATE TRIGGER trg_ssp_collateral_org_match
  BEFORE INSERT OR UPDATE OF organization_id, deal_id
  ON app.ssp_collateral
  FOR EACH ROW
  EXECUTE FUNCTION app.ssp_enforce_org_match();

DROP TRIGGER IF EXISTS trg_ssp_loans_org_match ON app.ssp_loans;
CREATE TRIGGER trg_ssp_loans_org_match
  BEFORE INSERT OR UPDATE OF organization_id, deal_id
  ON app.ssp_loans
  FOR EACH ROW
  EXECUTE FUNCTION app.ssp_enforce_org_match();

DROP TRIGGER IF EXISTS trg_ssp_pools_org_match ON app.ssp_pools;
CREATE TRIGGER trg_ssp_pools_org_match
  BEFORE INSERT OR UPDATE OF organization_id, deal_id
  ON app.ssp_pools
  FOR EACH ROW
  EXECUTE FUNCTION app.ssp_enforce_org_match();

DROP TRIGGER IF EXISTS trg_ssp_tranches_org_match ON app.ssp_tranches;
CREATE TRIGGER trg_ssp_tranches_org_match
  BEFORE INSERT OR UPDATE OF organization_id, deal_id
  ON app.ssp_tranches
  FOR EACH ROW
  EXECUTE FUNCTION app.ssp_enforce_org_match();

DROP TRIGGER IF EXISTS trg_ssp_calculations_org_match ON app.ssp_calculations;
CREATE TRIGGER trg_ssp_calculations_org_match
  BEFORE INSERT OR UPDATE OF organization_id, deal_id
  ON app.ssp_calculations
  FOR EACH ROW
  EXECUTE FUNCTION app.ssp_enforce_org_match();

DROP TRIGGER IF EXISTS trg_ssp_pool_of_pools_org_match ON app.ssp_pool_of_pools;
CREATE TRIGGER trg_ssp_pool_of_pools_org_match
  BEFORE INSERT OR UPDATE OF organization_id, deal_id
  ON app.ssp_pool_of_pools
  FOR EACH ROW
  EXECUTE FUNCTION app.ssp_enforce_org_match();

DROP TRIGGER IF EXISTS trg_ssp_loan_collateral_org_match ON app.ssp_loan_collateral;
CREATE TRIGGER trg_ssp_loan_collateral_org_match
  BEFORE INSERT OR UPDATE OF organization_id, deal_id
  ON app.ssp_loan_collateral
  FOR EACH ROW
  EXECUTE FUNCTION app.ssp_enforce_org_match();

DROP TRIGGER IF EXISTS trg_ssp_pool_loans_org_match ON app.ssp_pool_loans;
CREATE TRIGGER trg_ssp_pool_loans_org_match
  BEFORE INSERT OR UPDATE OF organization_id, deal_id
  ON app.ssp_pool_loans
  FOR EACH ROW
  EXECUTE FUNCTION app.ssp_enforce_org_match();

DROP TRIGGER IF EXISTS trg_ssp_pop_members_org_match ON app.ssp_pool_of_pools_members;
CREATE TRIGGER trg_ssp_pop_members_org_match
  BEFORE INSERT OR UPDATE OF organization_id, deal_id
  ON app.ssp_pool_of_pools_members
  FOR EACH ROW
  EXECUTE FUNCTION app.ssp_enforce_org_match();

DROP TRIGGER IF EXISTS trg_ssp_tranche_pools_org_match ON app.ssp_tranche_pools;
CREATE TRIGGER trg_ssp_tranche_pools_org_match
  BEFORE INSERT OR UPDATE OF organization_id, deal_id
  ON app.ssp_tranche_pools
  FOR EACH ROW
  EXECUTE FUNCTION app.ssp_enforce_org_match();

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
    GRANT SELECT, INSERT, UPDATE, DELETE ON
      app.ssp_deals,
      app.ssp_holdings,
      app.ssp_collateral,
      app.ssp_loans,
      app.ssp_loan_collateral,
      app.ssp_pools,
      app.ssp_pool_loans,
      app.ssp_pool_of_pools,
      app.ssp_pool_of_pools_members,
      app.ssp_tranches,
      app.ssp_tranche_pools,
      app.ssp_calculations
    TO app_user;
  END IF;
END
$$;

-- Phase 6C.1/6C.2 additive columns: safe when CREATE TABLE IF NOT EXISTS
-- skipped recreating an older disposable schema.
ALTER TABLE app.ssp_pool_loans
  ADD COLUMN IF NOT EXISTS amount_in_pool numeric(20, 8);
ALTER TABLE app.ssp_pool_of_pools_members
  ADD COLUMN IF NOT EXISTS amount_in_pop numeric(20, 8);
ALTER TABLE app.ssp_tranches
  ADD COLUMN IF NOT EXISTS is_virtual_overcollateralization boolean NOT NULL DEFAULT false;

INSERT INTO public.schema_migrations (version, description)
VALUES (
  '0020_ssp_structures',
  'PCAF 2025 Part A 5.8 SSP deal/holding/hierarchy draft tables, financing_instance_id identity, deal-scoped association FKs, child calcs not reportable'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
