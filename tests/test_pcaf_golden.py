"""
Phase D — golden parity fixtures for PCAF shared formulas.

Rule: do not change formula implementations to make tests pass.
If a fixture fails, the port (or the fixture) is wrong — investigate, don't "fix" math.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fastapi_app.shared_formula_utils import (
    calculate_attribution_factor,
    calculate_attribution_factor_listed,
    calculate_attribution_factor_unlisted,
    calculate_financed_emissions,
)

FIXTURES = Path(__file__).parent / "fixtures" / "pcaf_golden.json"


@pytest.fixture(scope="module")
def golden():
    with FIXTURES.open(encoding="utf-8") as f:
        return json.load(f)


def test_attribution_factor_cases(golden):
    for case in golden["attribution_factor"]:
        got = calculate_attribution_factor(
            case["outstanding_amount"], case["total_assets"]
        )
        assert got == pytest.approx(case["expected"], rel=1e-9, abs=1e-9), case["id"]


def test_listed_attribution(golden):
    for case in golden["attribution_factor_listed"]:
        got = calculate_attribution_factor_listed(
            case["outstanding_amount"], case["evic"]
        )
        assert got == pytest.approx(case["expected"], rel=1e-9, abs=1e-9), case["id"]


def test_unlisted_attribution(golden):
    for case in golden["attribution_factor_unlisted"]:
        got = calculate_attribution_factor_unlisted(
            case["outstanding_amount"], case["total_equity_plus_debt"]
        )
        assert got == pytest.approx(case["expected"], rel=1e-9, abs=1e-9), case["id"]


def test_financed_emissions(golden):
    for case in golden["financed_emissions"]:
        got = calculate_financed_emissions(
            case["outstanding_amount"],
            case["denominator"],
            case["emission_data"],
        )
        assert got == pytest.approx(case["expected"], rel=1e-9, abs=1e-9), case["id"]
