"""GHG activity calculators ported from SPA (no formula invention)."""

from .epa_fuel import (
    build_epa_fuel_map,
    calculate_epa_fuel,
    calculate_epa_fuel_emissions,
)
from .uk_fuel import (
    build_uk_factors_map,
    calculate_uk_fuel,
    calculate_uk_fuel_emissions,
)

__all__ = [
    "build_uk_factors_map",
    "calculate_uk_fuel",
    "calculate_uk_fuel_emissions",
    "build_epa_fuel_map",
    "calculate_epa_fuel",
    "calculate_epa_fuel_emissions",
]
