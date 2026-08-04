"""IPCC stationary fuel combustion: emissions = quantity × factor."""

from __future__ import annotations

from typing import Any, Dict

from ._common import fail_payload, success_payload


def calculate_ipcc_stationary(*, quantity: float, factor: float) -> Dict[str, Any]:
    if quantity is None or factor is None:
        return fail_payload("quantity and factor required")
    emissions_kg = float(quantity) * float(factor)
    return success_payload(
        emissions_kg, factor=float(factor), extra={"quantity": quantity}
    )
