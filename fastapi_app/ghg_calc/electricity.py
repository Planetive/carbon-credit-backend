"""
Scope 2 electricity — ported from SPA ElectricityEmissions.tsx / spaMath.spaElectricity.

grid = (grid_pct/100) * total_kwh * grid_factor
other = (other_pct/100) * total_kwh * other_row_emissions_sum
renewable = 0
total = Number((grid + other).toFixed(6))
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ._common import round6, success_payload


def calculate_electricity(
    *,
    total_kwh: float,
    grid_pct: Optional[float] = None,
    grid_factor: Optional[float] = None,
    other_pct: Optional[float] = None,
    other_row_emissions_sum: Optional[float] = None,
    renewable_pct: Optional[float] = None,
) -> Dict[str, Any]:
    _ = renewable_pct  # SPA: renewable always contributes 0
    if not total_kwh:
        return success_payload(
            0.0,
            factor=grid_factor,
            extra={
                "total_kwh": total_kwh,
                "grid_part": 0.0,
                "other_part": 0.0,
                "renewable_part": 0.0,
            },
        )

    grid_part = 0.0
    if grid_pct and grid_factor:
        grid_part = (float(grid_pct) / 100.0) * float(total_kwh) * float(grid_factor)

    other_part = 0.0
    if other_pct and float(other_pct) > 0 and other_row_emissions_sum:
        other_part = (
            (float(other_pct) / 100.0)
            * float(total_kwh)
            * float(other_row_emissions_sum)
        )

    renewable_part = 0.0
    emissions_kg = round6(grid_part + renewable_part + other_part)
    return success_payload(
        emissions_kg,
        factor=grid_factor,
        extra={
            "total_kwh": total_kwh,
            "grid_pct": grid_pct,
            "grid_factor": grid_factor,
            "other_pct": other_pct,
            "other_row_emissions_sum": other_row_emissions_sum,
            "grid_part": grid_part,
            "other_part": other_part,
            "renewable_part": renewable_part,
        },
    )
