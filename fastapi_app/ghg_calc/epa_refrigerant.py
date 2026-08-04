"""
EPA refrigerant — ported from SPA epaRefrigerantGwp.ts calculateEpaRefrigerantEmissions.

leakage_record: leakage_kg given
estimated_leakage: charge_kg * (rate/100)
emissions_kg = Number((leakage * gwp).toFixed(6))
leakage_kg returned = Number(leakage.toFixed(6))
"""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from ._common import fail_payload, round6, success_payload

EpaMethod = Literal["leakage_record", "estimated_leakage"]


def calculate_epa_refrigerant(
    *,
    method: EpaMethod,
    gwp: float,
    leakage_kg: Optional[float] = None,
    charge_kg: Optional[float] = None,
    leakage_rate_percent: Optional[float] = None,
) -> Dict[str, Any]:
    if not (isinstance(gwp, (int, float)) and float(gwp) == float(gwp) and float(gwp) > 0):
        return fail_payload("gwp must be a finite number > 0")

    if method == "leakage_record":
        if leakage_kg is None or not isinstance(leakage_kg, (int, float)) or float(leakage_kg) < 0:
            return fail_payload("leakage_kg required and must be >= 0 for leakage_record")
        raw_leakage = float(leakage_kg)
    elif method == "estimated_leakage":
        if (
            charge_kg is None
            or leakage_rate_percent is None
            or not isinstance(charge_kg, (int, float))
            or not isinstance(leakage_rate_percent, (int, float))
            or float(charge_kg) < 0
            or float(leakage_rate_percent) < 0
        ):
            return fail_payload(
                "charge_kg and leakage_rate_percent required (>=0) for estimated_leakage"
            )
        raw_leakage = float(charge_kg) * (float(leakage_rate_percent) / 100.0)
    else:
        return fail_payload("method must be leakage_record or estimated_leakage")

    leakage_out = round6(raw_leakage)
    emissions_kg = round6(raw_leakage * float(gwp))
    emissions_tonnes = round6(emissions_kg / 1000.0)

    return success_payload(
        emissions_kg,
        factor=float(gwp),
        extra={
            "method": method,
            "gwp": float(gwp),
            "leakage_kg": leakage_out,
            "emissions_tonnes": emissions_tonnes,
            "charge_kg": charge_kg,
            "leakage_rate_percent": leakage_rate_percent,
        },
    )
