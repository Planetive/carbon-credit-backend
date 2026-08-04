"""Shared IPCC constants — EmissionCalculatorIPCC.tsx."""

from __future__ import annotations

M3_PER_MMSCF = 28316.8466
IDEAL_GAS_VOLUME_DIVISOR = 22.414
FLARING_TEMPERATURE_CORRECTION = 273.15 / 288.71
VENTING_TEMPERATURE_CORRECTION = 273.15 / 288.71

FLARING_PRECISE_COMPONENT_FACTORS = {
    "CO2": {"molar_mass": 44.01, "multiplier": 1.0},
    "CH4": {"molar_mass": 16.04, "multiplier": 28.0},
    "C2H6": {"molar_mass": 30.07, "multiplier": 5.5},
    "C3H8": {"molar_mass": 44.1, "multiplier": 3.0},
    "C4H10": {"molar_mass": 58.12, "multiplier": 4.0},
    "C5H12": {"molar_mass": 72.15, "multiplier": 4.0},
    "C6H14": {"molar_mass": 86.18, "multiplier": 4.0},
}

VENTING_GWP = {
    "N2": 0.0,
    "CO2": 1.0,
    "CH4": 28.0,
    "C2H6": 5.5,
    "C3H8": 3.0,
    "C4H10": 4.0,
    "C5H12": 4.0,
    "C6H14": 4.0,
}

VENTING_MOLAR_MASS = {
    "N2": 28.014,
    "CO2": 44.01,
    "CH4": 16.04,
    "C2H6": 30.07,
    "C3H8": 44.1,
    "C4H10": 58.12,
    "C5H12": 72.15,
    "C6H14": 86.18,
}

DEFAULT_VEHICULAR = {"diesel": 2.7, "petrol": 2.32}
DEFAULT_KITCHEN = {"lpg": 1.51, "natural_gas_co2": 53.06}
DEFAULT_POWER = {"diesel": 2.7, "natural_gas_co2": 53.06}
