-- Phase 5E: UoP vs general-purpose overlap review records.
-- DO NOT apply automatically. Prepare for human-reviewed migration only.
-- Does not enable reportable Save. Does not silently subtract emissions.

BEGIN;

CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE IF NOT EXISTS app.uop_overlap_reviews (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL,
  uop_financing_instance_id TEXT NOT NULL,
  general_purpose_financing_instance_id TEXT,
  counterparty_id UUID,
  issuer_name TEXT,
  reporting_year TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending_review'
    CHECK (status IN ('pending_review', 'approved', 'rejected', 'cancelled')),
  documented_allocation_notes TEXT,
  evidence_reference TEXT,
  evidence_is_verified BOOLEAN NOT NULL DEFAULT FALSE,
  uop_outstanding_adjustment NUMERIC(20, 6),
  general_purpose_outstanding_adjustment NUMERIC(20, 6),
  adjustment_basis TEXT,
  reviewer_user_id UUID,
  review_notes TEXT,
  decided_at TIMESTAMPTZ,
  created_by UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uop_overlap_reviews_evidence_not_auto_verified
    CHECK (evidence_is_verified = FALSE OR evidence_reference IS NOT NULL)
);

COMMENT ON TABLE app.uop_overlap_reviews IS
  'PCAF §5.7 pp.107–108 overlap review. Approved records document evidenced splits; they never auto-redistribute financed emissions. Organization-scoped; evidence_is_verified stays false unless a reviewer decision is recorded; unresolved reviews must not be treated as reportable.';

COMMENT ON COLUMN app.uop_overlap_reviews.evidence_is_verified IS
  'Must remain false until a human reviewer decides. Entering an evidence reference alone does not verify the document.';

COMMENT ON COLUMN app.uop_overlap_reviews.uop_outstanding_adjustment IS
  'Documented UoP outstanding after evidenced split. Not applied as automatic emission subtraction.';

COMMENT ON COLUMN app.uop_overlap_reviews.general_purpose_outstanding_adjustment IS
  'Documented general-purpose outstanding after evidenced split. Not applied as automatic emission subtraction.';

CREATE INDEX IF NOT EXISTS idx_uop_overlap_reviews_org_year
  ON app.uop_overlap_reviews (organization_id, reporting_year, status);

CREATE INDEX IF NOT EXISTS idx_uop_overlap_reviews_uop_instance
  ON app.uop_overlap_reviews (organization_id, uop_financing_instance_id);

INSERT INTO public.schema_migrations (version, description)
VALUES (
  '0019_uop_overlap_reviews',
  'UoP vs general-purpose overlap review workflow (prepared, not auto-applied)'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
