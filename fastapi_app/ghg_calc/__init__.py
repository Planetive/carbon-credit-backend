"""GHG activity calculators ported from SPA (no formula invention)."""

from .electricity import calculate_electricity
from .epa_fuel import (
    build_epa_fuel_map,
    calculate_epa_fuel,
    calculate_epa_fuel_emissions,
)
from .epa_refrigerant import calculate_epa_refrigerant
from .heat_steam import build_heat_steam_rows, calculate_heat_steam
from .mobile_fuel import build_mobile_options, calculate_mobile_fuel
from .non_road import build_non_road_rows, calculate_non_road
from .on_road import (
    build_on_road_diesel_rows,
    build_on_road_gasoline_rows,
    calculate_on_road_diesel,
    calculate_on_road_gasoline,
)
from .uk_fuel import (
    build_uk_factors_map,
    calculate_uk_fuel,
    calculate_uk_fuel_emissions,
)
from .uk_transport import (
    build_uk_delivery_map,
    build_uk_passenger_map,
    calculate_uk_delivery,
    calculate_uk_passenger,
)
from .waste import build_waste_materials, calculate_waste

__all__ = [
    "calculate_electricity",
    "calculate_epa_refrigerant",
    "build_uk_factors_map",
    "calculate_uk_fuel",
    "calculate_uk_fuel_emissions",
    "build_epa_fuel_map",
    "calculate_epa_fuel",
    "calculate_epa_fuel_emissions",
    "build_mobile_options",
    "calculate_mobile_fuel",
    "build_on_road_gasoline_rows",
    "build_on_road_diesel_rows",
    "calculate_on_road_gasoline",
    "calculate_on_road_diesel",
    "build_non_road_rows",
    "calculate_non_road",
    "build_heat_steam_rows",
    "calculate_heat_steam",
    "build_waste_materials",
    "calculate_waste",
    "build_uk_passenger_map",
    "build_uk_delivery_map",
    "calculate_uk_passenger",
    "calculate_uk_delivery",
]
