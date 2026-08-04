"""
IPCC flaring — calculateFlaringEmissions from EmissionCalculatorIPCC.tsx.

volume_m3 = MMSCF ? volume * 28316.8466 : volume
total_moles = (volume_m3 / 22.414) * (273.15/288.71)
CO2_kg = total_moles * Σ(fraction * molarMass * multiplier)
CO2_tonnes = CO2_kg / 1000
"""

from __future__ import annotations

from typing import Any, Dict, List

from ._common import fail_payload, success_payload
from .ipcc_common import (
    FLARING_PRECISE_COMPONENT_FACTORS,
    FLARING_TEMPERATURE_CORRECTION,
    IDEAL_GAS_VOLUME_DIVISOR,
    M3_PER_MMSCF,
)


def calculate_ipcc_flaring(
    *,
    volume: float,
    unit: str,
    composition: List[Dict[str, Any]],
) -> Dict[str, Any]:
    if not (isinstance(volume, (int, float)) and float(volume) > 0):
        return fail_payload("Flare gas volume must be greater than 0.")

    percentages = [float(item.get("percentage", 0)) for item in composition]
    if any(p < 0 for p in percentages):
        return fail_payload("All gas composition values must be valid numbers >= 0.")
    percentage_total = sum(percentages)
    if abs(percentage_total - 100) > 0.001:
        return fail_payload(
            f"Gas composition must sum to 100%. Current total: {percentage_total:.2f}%."
        )

    volume_m3 = float(volume) * M3_PER_MMSCF if str(unit).upper() == "MMSCF" else float(volume)
    total_moles = (volume_m3 / IDEAL_GAS_VOLUME_DIVISOR) * FLARING_TEMPERATURE_CORRECTION

    weighted_factor_total = 0.0
    breakdown: List[Dict[str, Any]] = []
    for item in composition:
        formula = str(item.get("formula") or "").strip().upper()
        if not formula:
            return fail_payload("Each gas row must include a chemical formula.")
        fraction = float(item["percentage"]) / 100.0
        factor_def = FLARING_PRECISE_COMPONENT_FACTORS.get(formula)
        molar_mass = float(factor_def["molar_mass"]) if factor_def else 0.0
        multiplier = float(factor_def["multiplier"]) if factor_def else 0.0
        weighted = fraction * molar_mass * multiplier
        weighted_factor_total += weighted
        contribution_kg = total_moles * weighted
        breakdown.append(
            {
                "formula": formula,
                "fraction": fraction,
                "molar_mass": molar_mass,
                "multiplier": multiplier,
                "weighted_factor": weighted,
                "contribution_kg": contribution_kg,
            }
        )

    co2_kg = total_moles * weighted_factor_total
    co2_tonnes = co2_kg / 1000.0
    # emissions_kg = CO2 mass (same as SPA CO2_kg); MeT also returned
    return success_payload(
        co2_kg,
        extra={
            "emissions_tco2e": co2_tonnes,
            "CO2_kg": co2_kg,
            "CO2_tonnes": co2_tonnes,
            "total_moles": total_moles,
            "breakdown": breakdown,
            "volume": volume,
            "unit": unit,
        },
    )
