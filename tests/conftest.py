"""Pytest fixtures. The unbound-typed seam is for PCAF formula tests only."""

from __future__ import annotations

import pytest

from fastapi_app.uop_factor_bind import allow_unbound_typed_factors, reset_unbound_typed_factors

FORMULA_SEAM_FILES = {
    "test_uop_calculate.py",
    "test_uop_reportable.py",
    "test_uop_reportable_postgres.py",
    "test_uop_phase5e.py",
    "test_uop_phase5e1.py",
}


@pytest.fixture(autouse=True)
def _uop_formula_factor_seam(request):
    filename = getattr(getattr(request, "fspath", None), "basename", None) or ""
    path = str(getattr(request.module, "__file__", "")).replace("\\", "/")
    if filename not in FORMULA_SEAM_FILES and not any(path.endswith(name) for name in FORMULA_SEAM_FILES):
        yield
        return
    token = allow_unbound_typed_factors(True)
    try:
        yield
    finally:
        reset_unbound_typed_factors(token)
