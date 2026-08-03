-- =============================================================================
-- 002_migrate_supabase_auth_users.sql
-- =============================================================================
-- Purpose:
--   Copy legacy Supabase auth.users into public.users (self-hosted JWT auth)
--   and retarget profiles / user_organizations FKs to public.users.
--
-- How to run (pgAdmin):
--   1. Connect to EC2 Postgres database: rethinkcarbon
--   2. Open Query Tool
--   3. Load this file and Execute (F5)
--   4. Review NOTICE / RAISE NOTICE output in the Messages panel
--
-- Prerequisites:
--   - Prefer running 001_auth_users_and_profiles.sql first (safe if already applied)
--   - Take a backup / snapshot before running on production
--
-- Password import notes (IMPORTANT):
--   Supabase GoTrue stores bcrypt in auth.users.encrypted_password.
--   Those hashes are compatible with this API's passlib[bcrypt] verifier.
--   If encrypted_password is NULL/blank, we insert a random unusable bcrypt
--   hash — that user MUST use a forced password reset (not yet implemented
--   in the API; set password manually or wait for /auth/password-reset).
--
-- Safety:
--   - Idempotent: CREATE IF NOT EXISTS, ON CONFLICT DO NOTHING / careful UPDATEs
--   - Does NOT DROP auth.users
--   - Does NOT rewrite activity / scope / portfolio tables yet
--     (see FOLLOW-UP FK REMAP CHECKLIST at the bottom)
-- =============================================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ---------------------------------------------------------------------------
-- 1) Ensure public.users exists (same shape as 001)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_users_email ON public.users (email);

-- ---------------------------------------------------------------------------
-- 2) Import from auth.users when the legacy table is present
-- ---------------------------------------------------------------------------
DO $$
DECLARE
  has_auth_users boolean;
  imported_count integer := 0;
  forced_reset_count integer := 0;
  skipped_email_conflict integer := 0;
BEGIN
  SELECT EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'auth'
      AND table_name = 'users'
  ) INTO has_auth_users;

  IF NOT has_auth_users THEN
    RAISE NOTICE
      '002: auth.users not found — skipping import. '
      'public.users left as-is (new JWT signups only).';
    RETURN;
  END IF;

  -- Preserve auth.users.id so profiles.user_id / user_organizations.user_id
  -- keep working without row rewrites.
  INSERT INTO public.users (id, email, password_hash, created_at, updated_at)
  SELECT
    au.id,
    lower(trim(au.email)),
    CASE
      WHEN au.encrypted_password IS NOT NULL
           AND length(trim(au.encrypted_password)) > 0
        THEN au.encrypted_password
      ELSE crypt(gen_random_uuid()::text, gen_salt('bf'))
    END,
    COALESCE(au.created_at, now()),
    COALESCE(au.updated_at, now())
  FROM auth.users au
  WHERE au.email IS NOT NULL
    AND length(trim(au.email)) > 0
    -- Skip if this email already belongs to a different public.users row
    AND NOT EXISTS (
      SELECT 1
      FROM public.users pu
      WHERE lower(trim(pu.email)) = lower(trim(au.email))
        AND pu.id <> au.id
    )
  ON CONFLICT (id) DO NOTHING;

  GET DIAGNOSTICS imported_count = ROW_COUNT;

  SELECT COUNT(*) INTO forced_reset_count
  FROM auth.users au
  JOIN public.users pu ON pu.id = au.id
  WHERE au.encrypted_password IS NULL
     OR length(trim(COALESCE(au.encrypted_password, ''))) = 0;

  SELECT COUNT(*) INTO skipped_email_conflict
  FROM auth.users au
  WHERE au.email IS NOT NULL
    AND EXISTS (
      SELECT 1
      FROM public.users pu
      WHERE lower(trim(pu.email)) = lower(trim(au.email))
        AND pu.id <> au.id
    );

  RAISE NOTICE
    '002: auth.users import attempted. new_or_noop_inserts≈%, '
    'forced_reset_candidates(null/blank password)=%, '
    'skipped_email_conflicts=%',
    imported_count, forced_reset_count, skipped_email_conflict;

  IF forced_reset_count > 0 THEN
    RAISE NOTICE
      '002: Users with blank encrypted_password received a random bcrypt hash. '
      'They cannot log in until password is reset. Sample emails:';
    RAISE NOTICE '%', (
      SELECT string_agg(lower(trim(au.email)), ', ')
      FROM (
        SELECT au.email
        FROM auth.users au
        WHERE au.encrypted_password IS NULL
           OR length(trim(COALESCE(au.encrypted_password, ''))) = 0
        LIMIT 20
      ) au
    );
  END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 3) Retarget profiles.user_id → public.users (if currently on auth.users)
-- ---------------------------------------------------------------------------
DO $$
DECLARE
  fk_name text;
  already_public boolean;
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'profiles'
  ) THEN
    RAISE NOTICE '002: public.profiles missing — skip profiles FK remap';
    RETURN;
  END IF;

  -- Already points at public.users?
  SELECT EXISTS (
    SELECT 1
    FROM information_schema.table_constraints tc
    JOIN information_schema.constraint_column_usage ccu
      ON ccu.constraint_name = tc.constraint_name
     AND ccu.constraint_schema = tc.constraint_schema
    JOIN information_schema.key_column_usage kcu
      ON kcu.constraint_name = tc.constraint_name
     AND kcu.constraint_schema = tc.constraint_schema
    WHERE tc.table_schema = 'public'
      AND tc.table_name = 'profiles'
      AND tc.constraint_type = 'FOREIGN KEY'
      AND kcu.column_name = 'user_id'
      AND ccu.table_schema = 'public'
      AND ccu.table_name = 'users'
  ) INTO already_public;

  IF already_public THEN
    RAISE NOTICE '002: profiles.user_id already references public.users';
    RETURN;
  END IF;

  -- Drop any FK on profiles.user_id (typically auth.users)
  FOR fk_name IN
    SELECT tc.constraint_name
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
      ON kcu.constraint_name = tc.constraint_name
     AND kcu.constraint_schema = tc.constraint_schema
    WHERE tc.table_schema = 'public'
      AND tc.table_name = 'profiles'
      AND tc.constraint_type = 'FOREIGN KEY'
      AND kcu.column_name = 'user_id'
  LOOP
    EXECUTE format('ALTER TABLE public.profiles DROP CONSTRAINT %I', fk_name);
    RAISE NOTICE '002: dropped profiles FK %', fk_name;
  END LOOP;

  -- Orphan guard: every profiles.user_id must exist in public.users
  IF EXISTS (
    SELECT 1
    FROM public.profiles p
    LEFT JOIN public.users u ON u.id = p.user_id
    WHERE u.id IS NULL
  ) THEN
    RAISE EXCEPTION
      '002: Aborting profiles FK remap — orphan profiles.user_id rows exist '
      'with no matching public.users.id. Import auth.users first or fix orphans.';
  END IF;

  ALTER TABLE public.profiles
    ADD CONSTRAINT profiles_user_id_fkey
    FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

  RAISE NOTICE '002: profiles.user_id now references public.users';
END
$$;

-- ---------------------------------------------------------------------------
-- 4) Retarget user_organizations.user_id → public.users
-- ---------------------------------------------------------------------------
DO $$
DECLARE
  fk_name text;
  already_public boolean;
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'user_organizations'
  ) THEN
    RAISE NOTICE '002: public.user_organizations missing — skip membership FK remap';
    RETURN;
  END IF;

  SELECT EXISTS (
    SELECT 1
    FROM information_schema.table_constraints tc
    JOIN information_schema.constraint_column_usage ccu
      ON ccu.constraint_name = tc.constraint_name
     AND ccu.constraint_schema = tc.constraint_schema
    JOIN information_schema.key_column_usage kcu
      ON kcu.constraint_name = tc.constraint_name
     AND kcu.constraint_schema = tc.constraint_schema
    WHERE tc.table_schema = 'public'
      AND tc.table_name = 'user_organizations'
      AND tc.constraint_type = 'FOREIGN KEY'
      AND kcu.column_name = 'user_id'
      AND ccu.table_schema = 'public'
      AND ccu.table_name = 'users'
  ) INTO already_public;

  IF already_public THEN
    RAISE NOTICE '002: user_organizations.user_id already references public.users';
    RETURN;
  END IF;

  FOR fk_name IN
    SELECT tc.constraint_name
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
      ON kcu.constraint_name = tc.constraint_name
     AND kcu.constraint_schema = tc.constraint_schema
    WHERE tc.table_schema = 'public'
      AND tc.table_name = 'user_organizations'
      AND tc.constraint_type = 'FOREIGN KEY'
      AND kcu.column_name = 'user_id'
  LOOP
    EXECUTE format(
      'ALTER TABLE public.user_organizations DROP CONSTRAINT %I', fk_name
    );
    RAISE NOTICE '002: dropped user_organizations FK %', fk_name;
  END LOOP;

  IF EXISTS (
    SELECT 1
    FROM public.user_organizations uo
    LEFT JOIN public.users u ON u.id = uo.user_id
    WHERE u.id IS NULL
  ) THEN
    RAISE EXCEPTION
      '002: Aborting user_organizations FK remap — orphan user_id rows exist.';
  END IF;

  ALTER TABLE public.user_organizations
    ADD CONSTRAINT user_organizations_user_id_fkey
    FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

  RAISE NOTICE '002: user_organizations.user_id now references public.users';
END
$$;

-- Optional ledger (ignore if table absent)
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'schema_migrations'
  ) THEN
    INSERT INTO public.schema_migrations (version, description)
    VALUES (
      '002_migrate_supabase_auth_users',
      'Import auth.users → public.users; retarget profiles + user_organizations FKs'
    )
    ON CONFLICT (version) DO NOTHING;
  END IF;
END
$$;

COMMIT;

-- =============================================================================
-- FOLLOW-UP FK REMAP CHECKLIST (do NOT run in this script)
-- =============================================================================
-- After public.users is the source of truth, retarget these user_id / created_by
-- columns from auth.users → public.users (same UUID preserve strategy).
-- Review live FKs with:
--   SELECT conrelid::regclass AS table_name, conname, pg_get_constraintdef(oid)
--   FROM pg_constraint
--   WHERE contype = 'f'
--     AND confrelid = 'auth.users'::regclass;
--
-- Likely candidates (from legacy schema_recreate.sql / product tables):
--   [ ] organizations.created_by
--   [ ] organization_invitations.invited_by / accepted_by
--   [ ] user_organizations.invited_by
--   [ ] counterparties.user_id
--   [ ] exposures.user_id
--   [ ] emission_calculations.user_id
--   [ ] emission_calculator.user_id
--   [ ] finance_emission_calculations.user_id (if present)
--   [ ] esg_assessments.user_id
--   [ ] project_inputs.user_id
--   [ ] scope1_* / scope2_* / scope3_* entry tables.user_id
--   [ ] app.emission_assessments.user_id / app.emission_activities.user_id
--   [ ] app.financed_emissions.user_id
--   [ ] any audit / activity log tables referencing auth.users
--
-- Only AFTER all FKs are remapped and the SPA is fully on JWT auth:
--   [ ] Drop or freeze auth.users (NOT yet)
-- =============================================================================
