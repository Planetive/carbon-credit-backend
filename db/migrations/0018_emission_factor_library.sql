-- PREPARED, NOT APPLIED TO PRODUCTION.
-- Phase 5D.2: reusable emission-factor library on top of ref.factor_datasets / ref.factor_rows.
--
-- Additive only. Does not DELETE, UPDATE, or overwrite existing factor_rows values.
-- Does not enable UoP reportable Save.
-- Approved library values are immutable; a new publication row is required for revisions.

BEGIN;

CREATE SCHEMA IF NOT EXISTS ref;

CREATE TABLE IF NOT EXISTS ref.factor_datasets (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code text NOT NULL UNIQUE,
  publisher text NOT NULL DEFAULT 'legacy',
  title text NOT NULL,
  version_label text NOT NULL DEFAULT 'imported',
  effective_from date NULL,
  effective_to date NULL,
  is_active boolean NOT NULL DEFAULT true,
  source_notes text NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ref.factor_rows (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  dataset_id uuid NOT NULL REFERENCES ref.factor_datasets(id) ON DELETE CASCADE,
  category text NOT NULL,
  label text NULL,
  attributes jsonb NOT NULL DEFAULT '{}'::jsonb,
  unit text NULL,
  kg_co2e numeric(20, 8) NULL,
  kg_co2 numeric(20, 8) NULL,
  kg_ch4 numeric(20, 8) NULL,
  kg_n2o numeric(20, 8) NULL,
  meta jsonb NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE ref.factor_datasets
  ADD COLUMN IF NOT EXISTS source_organization text,
  ADD COLUMN IF NOT EXISTS source_document text,
  ADD COLUMN IF NOT EXISTS source_url text,
  ADD COLUMN IF NOT EXISTS license_name text,
  ADD COLUMN IF NOT EXISTS permitted_use text;

CREATE TABLE IF NOT EXISTS ref.factor_library_entries (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  publication_id uuid NOT NULL DEFAULT gen_random_uuid(),
  supersedes_id uuid NULL REFERENCES ref.factor_library_entries(id),
  factor_row_id uuid NULL REFERENCES ref.factor_rows(id) ON DELETE SET NULL,
  dataset_id uuid NULL REFERENCES ref.factor_datasets(id) ON DELETE SET NULL,
  dataset_code text NULL,
  dataset_version text NULL,
  category text NOT NULL,
  library_class text NOT NULL,
  country_code text NULL,
  region text NULL,
  geography text NOT NULL,
  sector_or_activity text NOT NULL,
  activity_key text NOT NULL,
  factor_value numeric(20, 8) NOT NULL,
  numerator_unit text NOT NULL,
  denominator_unit text NOT NULL,
  unit text NOT NULL,
  applicable_year integer NOT NULL,
  publication_year integer NOT NULL,
  gas text NOT NULL DEFAULT 'CO2e',
  scope_boundary text NULL,
  emissions_boundary text NULL,
  source_organization text NOT NULL,
  source_document text NULL,
  source_url text NULL,
  provenance text NULL,
  license_name text NULL,
  permitted_use text NULL,
  currency_code text NULL,
  price_year integer NULL,
  status text NOT NULL DEFAULT 'draft',
  submitted_by uuid NULL,
  submitted_rationale text NULL,
  reviewed_by uuid NULL,
  reviewed_at timestamptz NULL,
  review_notes text NULL,
  organization_id uuid NULL,
  effective_from date NULL,
  effective_to date NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT factor_library_class_chk CHECK (
    library_class IN ('physical', 'economic', 'building', 'vehicle')
  ),
  CONSTRAINT factor_library_status_chk CHECK (
    status IN ('draft', 'pending_review', 'approved', 'rejected', 'retired')
  )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_factor_library_publication
  ON ref.factor_library_entries (publication_id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_factor_library_approved_identity
  ON ref.factor_library_entries (
    library_class,
    lower(btrim(geography)),
    lower(btrim(activity_key)),
    lower(btrim(unit)),
    applicable_year,
    publication_year,
    lower(btrim(gas)),
    COALESCE(lower(btrim(currency_code)), ''),
    COALESCE(price_year, 0)
  )
  WHERE status = 'approved';

CREATE INDEX IF NOT EXISTS ix_factor_library_lookup
  ON ref.factor_library_entries (
    status, library_class, lower(btrim(geography)), applicable_year, lower(btrim(activity_key))
  );

CREATE TABLE IF NOT EXISTS ref.factor_library_audit (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  entry_id uuid NOT NULL REFERENCES ref.factor_library_entries(id) ON DELETE CASCADE,
  action text NOT NULL,
  actor_user_id uuid NULL,
  organization_id uuid NULL,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION ref.factor_library_protect_approved()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.status = 'approved' THEN
      RAISE EXCEPTION 'Approved factor rows cannot be deleted. Retire them instead.';
    END IF;
    RETURN OLD;
  END IF;
  IF OLD.status = 'approved' THEN
    IF NEW.factor_value IS DISTINCT FROM OLD.factor_value
      OR NEW.unit IS DISTINCT FROM OLD.unit
      OR NEW.numerator_unit IS DISTINCT FROM OLD.numerator_unit
      OR NEW.denominator_unit IS DISTINCT FROM OLD.denominator_unit
      OR NEW.geography IS DISTINCT FROM OLD.geography
      OR NEW.activity_key IS DISTINCT FROM OLD.activity_key
      OR NEW.applicable_year IS DISTINCT FROM OLD.applicable_year
      OR NEW.publication_year IS DISTINCT FROM OLD.publication_year
      OR NEW.publication_id IS DISTINCT FROM OLD.publication_id
    THEN
      RAISE EXCEPTION
        'Approved factor values are immutable. Insert a new publication and retire the previous row.';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_factor_library_protect_approved ON ref.factor_library_entries;
CREATE TRIGGER trg_factor_library_protect_approved
  BEFORE UPDATE OR DELETE ON ref.factor_library_entries
  FOR EACH ROW
  EXECUTE PROCEDURE ref.factor_library_protect_approved();

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
    EXECUTE 'GRANT SELECT ON ref.factor_library_entries, ref.factor_library_audit TO app_user';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'catalog_reader') THEN
    EXECUTE 'GRANT SELECT ON ref.factor_library_entries, ref.factor_library_audit TO catalog_reader';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'migrator') THEN
    EXECUTE 'GRANT ALL ON ref.factor_library_entries, ref.factor_library_audit TO migrator';
  END IF;
END
$$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'schema_migrations'
  ) THEN
    INSERT INTO public.schema_migrations (version, description)
    VALUES (
      '0018_emission_factor_library',
      'Reusable approved-factor library; immutable publications; no overwrite of factor_rows'
    )
    ON CONFLICT (version) DO NOTHING;
  END IF;
END
$$;

COMMIT;
