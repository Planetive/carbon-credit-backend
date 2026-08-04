"""
IPCC venting — calculateVentingEmissions from EmissionCalculatorIPCC.tsx.

per gas: moles × molarMass × GWP; total_t = Σco2e_kg / 1000
"""

from __future__ import annotations

from typing import Any, Dict, List

from ._common import fail_payload, success_payload
from .ipcc_common import (
    IDEAL_GAS_VOLUME_DIVISOR,
    M3_PER_MMSCF,
    VENTING_GWP,
    VENTING_MOLAR_MASS,
    VENTING_TEMPERATURE_CORRECTION,
)


def calculate_ipcc_venting(
    *,
    volume: float,
    unit: str,
    composition: List[Dict[str, Any]],
) -> Dict[str, Any]:
    if not (isinstance(volume, (int, float)) and float(volume) > 0):
        return fail_payload("Vent gas volume must be greater than 0.")
    if not composition:
        return fail_payload("Please add at least one vent gas component.")

    percentages = [float(item.get("percentage", 0)) for item in composition]
    if any(p < 0 for p in percentages):
        return fail_payload("All vent gas composition values must be valid numbers >= 0.")
    percentage_total = sum(percentages)
    if abs(percentage_total - 100) > 0.001:
        return fail_payload(
            f"Gas composition must sum to 100%. Current total: {percentage_total:.2f}%."
        )

    volume_m3 = float(volume) * M3_PER_MMSCF if str(unit).upper() == "MMSCF" else float(volume)
    total_moles = (volume_m3 / IDEAL_GAS_VOLUME_DIVISOR) * VENTING_TEMPERATURE_CORRECTION

    percentage_by_gas: Dict[str, float] = {g: 0.0 for g in VENTING_GWP}
    for item in composition:
        gas = str(item.get("gas") or "").upper()
        if gas not in VENTING_GWP:
            return fail_payload("Each vent gas row must include a valid gas.")
        percentage_by_gas[gas] += float(item["percentage"])

    breakdown: List[Dict[str, Any]] = []
    for gas, pct in percentage_by_gas.items():
        if pct <= 0:
            continue
        gas_moles = total_moles * (pct / 100.0)
        molar_mass = VENTING_MOLAR_MASS[gas]
        gas_mass_kg = gas_moles * molar_mass
        co2e_kg = gas_mass_kg * VENTING_GWP[gas]
        breakdown.append(
            {
                "gas": gas,
                "gwp": VENTING_GWP[gas],
                "gas_moles": gas_moles,
                "molar_mass": molar_mass,
                "gas_mass_kg": gas_mass_kg,
                "co2e_kg": co2e_kg,
            }
        )

    total_co2e_kg = sum(item["co2e_kg"] for item in breakdown)
    total_co2e_tonnes = total_co2e_kg / 1000.0
    return success_payload(
        total_co2e_kg,
        extra={
            "emissions_tco2e": total_co2e_tonnes,
            "total_co2e_kg": total_co2e_kg,
            "total_co2e_tonnes": total_co2e_tonnes,
            "total_moles": total_moles,
            "breakdown": breakdown,
            "volume": volume,
            "unit": unit,
        },
    )
