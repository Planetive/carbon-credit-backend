# Phase D golden parity tests
#
# Run from carbon-credit-backend root:
#   pip install pytest
#   python -m pytest tests/ -q
#
# Fixtures:
#   fixtures/pcaf_golden.json      — PCAF attribution / financed emissions
#   fixtures/uk_fuel_golden.json   — SPA UK fuel (FuelEmissions uk_supabase)
#   fixtures/ghg_expanded_golden.json — mobile / on-road / non-road / heat / waste / UK transport
#
# Never change formula code to satisfy a fixture — investigate the mismatch.
