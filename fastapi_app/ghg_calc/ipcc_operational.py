"""IPCC vehicular / kitchen / power / heating MeT calcs from EmissionCalculatorIPCC.tsx."""

from __future__ import annotations

from typing import Any, Dict, Optional

from ._common import success_payload
from .ipcc_common import DEFAULT_KITCHEN, DEFAULT_POWER, DEFAULT_VEHICULAR


def calculate_ipcc_vehicular(
    *,
    diesel_liters: float = 0,
    petrol_liters: float = 0,
    diesel_factor: Optional[float] = None,
    petrol_factor: Optional[float] = None,
) -> Dict[str, Any]:
    d_f = float(diesel_factor if diesel_factor is not None else DEFAULT_VEHICULAR["diesel"])
    p_f = float(petrol_factor if petrol_factor is not None else DEFAULT_VEHICULAR["petrol"])
    emissions_kg = float(diesel_liters) * d_f + float(petrol_liters) * p_f
    met = emissions_kg / 1000.0
    return success_payload(
        emissions_kg,
        extra={
            "emissions_tco2e": met,
            "diesel_liters": diesel_liters,
            "petrol_liters": petrol_liters,
            "diesel_factor": d_f,
            "petrol_factor": p_f,
        },
    )


def calculate_ipcc_kitchen(
    *,
    lpg_kg: float = 0,
    ng_mmscf: float = 0,
    ghv: float = 0,
    lpg_factor: Optional[float] = None,
    natural_gas_co2: Optional[float] = None,
) -> Dict[str, Any]:
    l_f = float(lpg_factor if lpg_factor is not None else DEFAULT_KITCHEN["lpg"])
    ng_f = float(
        natural_gas_co2
        if natural_gas_co2 is not None
        else DEFAULT_KITCHEN["natural_gas_co2"]
    )
    emissions_kg = float(lpg_kg) * l_f + float(ng_mmscf) * float(ghv) * ng_f
    met = emissions_kg / 1000.0
    return success_payload(
        emissions_kg,
        extra={
            "emissions_tco2e": met,
            "lpg_kg": lpg_kg,
            "ng_mmscf": ng_mmscf,
            "ghv": ghv,
            "lpg_factor": l_f,
            "natural_gas_co2": ng_f,
        },
    )


def calculate_ipcc_power(
    *,
    diesel_liters: float = 0,
    ng_mmscf: float = 0,
    ghv: float = 0,
    diesel_factor: Optional[float] = None,
    natural_gas_co2: Optional[float] = None,
) -> Dict[str, Any]:
    d_f = float(diesel_factor if diesel_factor is not None else DEFAULT_POWER["diesel"])
    ng_f = float(
        natural_gas_co2
        if natural_gas_co2 is not None
        else DEFAULT_POWER["natural_gas_co2"]
    )
    emissions_kg = float(diesel_liters) * d_f + float(ng_mmscf) * float(ghv) * ng_f
    met = emissions_kg / 1000.0
    return success_payload(
        emissions_kg,
        extra={
            "emissions_tco2e": met,
            "diesel_liters": diesel_liters,
            "ng_mmscf": ng_mmscf,
            "ghv": ghv,
            "diesel_factor": d_f,
            "natural_gas_co2": ng_f,
        },
    )


def calculate_ipcc_heating(
    *,
    ng_mmscf: float = 0,
    ghv: float = 0,
    natural_gas_co2: Optional[float] = None,
) -> Dict[str, Any]:
    ng_f = float(
        natural_gas_co2
        if natural_gas_co2 is not None
        else DEFAULT_POWER["natural_gas_co2"]
    )
    emissions_kg = float(ng_mmscf) * float(ghv) * ng_f
    met = emissions_kg / 1000.0
    return success_payload(
        emissions_kg,
        extra={
            "emissions_tco2e": met,
            "ng_mmscf": ng_mmscf,
            "ghv": ghv,
            "natural_gas_co2": ng_f,
        },
    )
