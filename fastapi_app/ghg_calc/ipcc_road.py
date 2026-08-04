"""
IPCC road / road+vehicle / USA / alt-fuel / industry: emissions = quantity × selected_factor.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ._common import fail_payload, success_payload


def calculate_ipcc_qty_factor(*, quantity: float, factor: float) -> Dict[str, Any]:
    if quantity is None or factor is None:
        return fail_payload("quantity and factor required")
    emissions_kg = float(quantity) * float(factor)
    return success_payload(
        emissions_kg, factor=float(factor), extra={"quantity": quantity}
    )


def calculate_ipcc_road(**kwargs: Any) -> Dict[str, Any]:
    return calculate_ipcc_qty_factor(**kwargs)


def calculate_ipcc_road_vehicle(
    *,
    quantity: float,
    ch4_factor: Optional[float] = None,
    n2o_factor: Optional[float] = None,
    selected_factor: str = "CH4",
) -> Dict[str, Any]:
    sel = (selected_factor or "CH4").upper()
    if sel in ("N2O", "NO2"):
        factor = n2o_factor
    else:
        factor = ch4_factor
    if factor is None:
        return fail_payload("selected factor value missing")
    return calculate_ipcc_qty_factor(quantity=quantity, factor=float(factor))


def calculate_ipcc_usa_vehicles(
    *,
    quantity: float,
    factor: float,
) -> Dict[str, Any]:
    return calculate_ipcc_qty_factor(quantity=quantity, factor=factor)


def calculate_ipcc_alt_fuel(
    *,
    quantity: float,
    ch4_factor: Optional[float] = None,
    n2o_factor: Optional[float] = None,
    selected_factor: str = "CH4",
) -> Dict[str, Any]:
    sel = (selected_factor or "CH4").upper()
    factor = n2o_factor if sel in ("N2O", "NO2") else ch4_factor
    if factor is None:
        return fail_payload("selected factor value missing")
    return calculate_ipcc_qty_factor(quantity=quantity, factor=float(factor))


def calculate_ipcc_industry(
    *,
    quantity: float,
    ef_co2: Optional[float] = None,
    ef_ch4: Optional[float] = None,
    ef_n2o: Optional[float] = None,
    selected_factor: str = "CO2",
) -> Dict[str, Any]:
    sel = (selected_factor or "CO2").upper()
    if sel == "CH4":
        factor = ef_ch4
    elif sel in ("N2O", "NO2"):
        factor = ef_n2o
    else:
        factor = ef_co2
    if factor is None:
        return fail_payload("selected factor value missing")
    return calculate_ipcc_qty_factor(quantity=quantity, factor=float(factor))
