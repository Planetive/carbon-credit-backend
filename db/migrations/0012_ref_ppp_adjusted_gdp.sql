-- PPP-adjusted GDP reference data for sovereign debt PCAF calculations.
-- Import CSV via pgAdmin: country_name, gdp_2024, gdp_2025

BEGIN;

CREATE SCHEMA IF NOT EXISTS ref;

CREATE TABLE IF NOT EXISTS ref.ppp_adjusted_gdp (
  country_name TEXT PRIMARY KEY,
  gdp_2024 NUMERIC(20, 4),
  gdp_2025 NUMERIC(20, 4)
);

COMMENT ON TABLE ref.ppp_adjusted_gdp IS
  'World Bank-style PPP-adjusted GDP by country. Prefer gdp_2025; fall back to gdp_2024 when null.';

CREATE OR REPLACE VIEW public.ppp_adjusted_gdp AS
  SELECT country_name, gdp_2024, gdp_2025 FROM ref.ppp_adjusted_gdp;

INSERT INTO public.schema_migrations (version, description)
VALUES ('0012_ref_ppp_adjusted_gdp', 'PPP-adjusted GDP reference table for sovereign debt')
ON CONFLICT (version) DO NOTHING;

COMMIT;
