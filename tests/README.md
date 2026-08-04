# Phase D golden parity tests
#
# Run from carbon-credit-backend root:
#   pip install pytest
#   python -m pytest tests/ -q
#
# Fixtures:
#   fixtures/pcaf_golden.json
#   fixtures/uk_fuel_golden.json / epa_fuel_golden.json / ghg_expanded_golden.json
#   fixtures/spa_parity_cases.json — copy of sibling SPA parity/cases.json
#   fixtures/scope3_batch2_golden.json — Scope 3 freight/travel/spend/leased (sync to SPA later)
#   fixtures/ipcc_batch3_golden.json — IPCC category calcs
#
# Shared SPA harness:
#   python -m pytest tests/test_spa_parity_cases.py -q
#   Prefers ../carbon-credit-app-main/parity/cases.json (includes electricity + epa_refrigerant)
#
# Never change formula code to satisfy a fixture — investigate the mismatch.
