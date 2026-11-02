"""
Category 3 — Fuel- and Energy-Related Activities.

Well-to-tank (WTT) and electricity T&D loss methods are unavailable until
dedicated upstream / T&D factor datasets are verified. Scope 1 combustion and
Scope 2 generation factors must not be reused here. Manual typed kg is never
a verified calculation.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ._common import fail_payload

# Datasets required before Category 3 calculation can be enabled.
CATEGORY3_REQUIRED_DATASETS = (
    {
        "code": "fuel_wtt_upstream",
        "purpose": "Upstream fuel production and transportation (well-to-tank)",
        "required_fields": (
            "fuel_type",
            "factor_unit (e.g. kg CO2e per activity unit)",
            "reporting_year",
            "geography",
            "boundary=WTT/upstream",
        ),
    },
    {
        "code": "electricity_td_losses",
        "purpose": "Electricity transmission and distribution losses",
        "required_fields": (
            "grid_or_region",
            "loss_factor or kg CO2e/kWh T&D",
            "reporting_year",
            "boundary=T&D (not generation)",
        ),
    },
)


def calculate_category3_fuel_energy(
    *,
    method: Optional[str] = None,
    **_: Any,
) -> Dict[str, Any]:
    """Refuse all Category 3 calculation paths until verified WTT/T&D factors exist."""
    return fail_payload(
        "Category 3 calculation unavailable: verified WTT/T&D factor datasets "
        "are not mounted. Manual emissions entry is not a verified calculation. "
        "Do not reuse Scope 1 combustion or Scope 2 generation factors.",
        method=method,
        required_datasets=list(CATEGORY3_REQUIRED_DATASETS),
    )
