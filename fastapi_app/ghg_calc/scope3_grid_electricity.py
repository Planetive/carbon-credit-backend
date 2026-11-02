"""
Scope 3 leased / sold-product electricity — refuse legacy placeholders and
legacy other-source × kWh mixing. Does not modify Scope 1/2 calculators.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Set

from ._common import fail_payload, round6, success_payload

# Same rejected values as verified Scope 2 UK engine — never use for Scope 3.
REJECTED_PLACEHOLDER_FACTORS: Set[float] = {0.425, 0.4041, 0.17355}


def _is_rejected_placeholder(factor: Optional[float]) -> bool:
    if factor is None:
        return False
    f = float(factor)
    for rejected in REJECTED_PLACEHOLDER_FACTORS:
        if abs(f - rejected) < 1e-9:
            return True
    return False


def calculate_scope3_grid_electricity(
    *,
    total_kwh: float,
    grid_pct: Optional[float] = None,
    grid_factor: Optional[float] = None,
    other_pct: Optional[float] = None,
    other_row_emissions_sum: Optional[float] = None,
    renewable_pct: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Only grid share × kWh × verified grid factor is supported.
    Refuse: missing factor, placeholder 0.4041/0.425/0.17355, and other×kWh mix.
    """
    _ = renewable_pct
    if not total_kwh or float(total_kwh) <= 0:
        return fail_payload("total_kwh must be > 0")

    if other_pct is not None and float(other_pct) > 0:
        return fail_payload(
            "Scope 3 electricity other-source × kWh mixing is unsupported; refuse calculation"
        )
    if other_row_emissions_sum is not None and float(other_row_emissions_sum) != 0:
        return fail_payload(
            "Scope 3 electricity other-source mixing is unsupported; refuse calculation"
        )

    gp = float(grid_pct or 0)
    if gp <= 0:
        return fail_payload(
            "Scope 3 electricity requires a positive grid share and verified grid factor"
        )
    if grid_factor is None:
        return fail_payload("Scope 3 electricity grid factor missing; refuse calculation")
    if _is_rejected_placeholder(grid_factor):
        return fail_payload(
            "Scope 3 electricity refuses placeholder grid factors (0.4041/0.425/0.17355)"
        )

    grid_part = (gp / 100.0) * float(total_kwh) * float(grid_factor)
    emissions_kg = round6(grid_part)
    return success_payload(
        emissions_kg,
        factor=float(grid_factor),
        extra={
            "total_kwh": total_kwh,
            "grid_pct": grid_pct,
            "grid_factor": grid_factor,
            "grid_part": grid_part,
            "other_part": 0.0,
            "renewable_part": 0.0,
        },
    )
