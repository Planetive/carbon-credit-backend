"""
Purchased heat and purchased steam for the EPA Scope 2 workflow.

The factors are the US EPA Emission Factors for Greenhouse Gas Inventories,
Table 7, Steam and Heat. They apply to energy purchased from an external
supplier and assume that supplier produced it from natural gas at 80 percent
thermal efficiency. A caller cannot replace them.

CO2 is kilograms per mmBtu. CH4 and N2O are grams per mmBtu and are divided
by 1000 before the AR5 GWPs used by the rest of this inventory (CH4 28, N2O
265). The result is tonnes of CO2e. On-site combustion is refused. The UK
DEFRA district-heat factor is not used here.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, Optional

ACCOUNTING_VERSION = "scope2_purchased_heat_steam_v1"
CATEGORY = "purchased_heat_steam"
METHOD = "purchased_energy"
DATASET_CODE = "heat_and_steam_ebt"
PUBLISHER = "US EPA"
SOURCE_DOCUMENT = (
    "Emission Factors for Greenhouse Gas Inventories, Table 7, Steam and Heat"
)
CO2_KG_PER_MMBTU = Decimal("66.33")
CH4_G_PER_MMBTU = Decimal("1.250")
N2O_G_PER_MMBTU = Decimal("0.125")
GWP_CO2 = Decimal("1")
GWP_CH4 = Decimal("28")
GWP_N2O = Decimal("265")
_GRAMS_PER_KG = Decimal("1000")
_KG_PER_TONNE = Decimal("1000")
_QUANT = Decimal("0.00000001")

_PURCHASED = {
    "purchased_heat": "purchased_heat",
    "purchased heat": "purchased_heat",
    "district heat": "purchased_heat",
    "purchased_steam": "purchased_steam",
    "purchased steam": "purchased_steam",
    "district steam": "purchased_steam",
}


def _text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def _norm(value: Any) -> str:
    return _text(value).lower().replace("_", " ").replace("-", " ")


def _decimal(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite():
        return None
    return number


def _quantize(value: Decimal) -> str:
    return format(value.quantize(_QUANT, rounding=ROUND_HALF_UP), "f")


def _energy_form(value: Any) -> Optional[str]:
    key = _norm(value)
    if not key:
        return None
    if "onsite" in key or "on site" in key or "combustion" in key:
        return "onsite"
    return _PURCHASED.get(key)


def _quantity_mmbtu(quantity: Any, unit: str) -> tuple[Optional[Decimal], Optional[str]]:
    number = _decimal(quantity)
    if number is None or number < 0:
        return None, "Purchased heat or steam quantity must be zero or a positive number."
    if _norm(unit).replace(" ", "") != "mmbtu":
        return None, "Purchased heat or steam must be entered in mmBtu. No other unit is converted."
    return number, None


def calculate_purchased_heat_steam(
    *,
    energy_form: str,
    quantity: Any,
    unit: str,
    period: str,
    supplier_name: Optional[str] = None,
    co2_factor: Any = None,
    ch4_factor: Any = None,
    n2o_factor: Any = None,
    emission_factor: Any = None,
    emissions_tco2e: Any = None,
) -> Dict[str, Any]:
    """Client factors and emission totals are ignored."""
    del co2_factor, ch4_factor, n2o_factor, emission_factor, emissions_tco2e
    text = _text(period)
    if (
        len(text) != 7
        or text[4] != "-"
        or not (text[:4].isdigit() and text[5:].isdigit())
        or not 1 <= int(text[5:]) <= 12
        or not 1990 <= int(text[:4]) <= 2200
    ):
        return {"ok": False, "status": "invalid_period", "error": "period must be YYYY-MM"}

    form = _energy_form(energy_form)
    if form == "onsite":
        return {
            "ok": False,
            "status": "onsite_combustion",
            "error": (
                "On-site combustion is Scope 1 stationary combustion. "
                "It cannot be reported as purchased heat or steam."
            ),
        }
    if form is None:
        return {
            "ok": False,
            "status": "invalid_energy",
            "error": "Choose purchased heat or purchased steam. On-site fuel combustion is not accepted.",
        }

    mmbtu, quantity_error = _quantity_mmbtu(quantity, unit)
    if quantity_error or mmbtu is None:
        return {"ok": False, "status": "invalid_quantity", "error": quantity_error}

    co2_kg = mmbtu * CO2_KG_PER_MMBTU
    ch4_kg = mmbtu * CH4_G_PER_MMBTU / _GRAMS_PER_KG
    n2o_kg = mmbtu * N2O_G_PER_MMBTU / _GRAMS_PER_KG
    co2e_kg = co2_kg * GWP_CO2 + ch4_kg * GWP_CH4 + n2o_kg * GWP_N2O
    tonnes = co2e_kg / _KG_PER_TONNE
    supplier = _text(supplier_name) or None
    factor = {
        "dataset_code": DATASET_CODE,
        "publisher": PUBLISHER,
        "source_document": SOURCE_DOCUMENT,
        "boundary": "purchased_energy",
        "production_fuel": "natural gas",
        "thermal_efficiency": "80%",
        "supplier_specific": False,
        "unit": "mmBtu",
        "co2_kg_per_mmbtu": _quantize(CO2_KG_PER_MMBTU),
        "ch4_g_per_mmbtu": _quantize(CH4_G_PER_MMBTU),
        "n2o_g_per_mmbtu": _quantize(N2O_G_PER_MMBTU),
        "gwp_version": "AR5",
        "gwp_ch4": int(GWP_CH4),
        "gwp_n2o": int(GWP_N2O),
        "gas_coverage": "CO2, CH4, and N2O",
    }
    return {
        "ok": True,
        "save_allowed": True,
        "status": "verified",
        "error": None,
        "energy_form": form,
        "period": text,
        "quantity": _quantize(mmbtu),
        "unit": "mmBtu",
        "supplier_name": supplier,
        "factor": factor,
        "gases": {
            "co2": {"mass_kg": _quantize(co2_kg), "gwp": int(GWP_CO2)},
            "ch4": {"mass_kg": _quantize(ch4_kg), "gwp": int(GWP_CH4), "input_unit": "g/mmBtu"},
            "n2o": {"mass_kg": _quantize(n2o_kg), "gwp": int(GWP_N2O), "input_unit": "g/mmBtu"},
        },
        "total_kg_co2e": _quantize(co2e_kg),
        "total_t_co2e": _quantize(tonnes),
        "methodology": (
            "GHG Protocol Scope 2 purchased energy. "
            "mmBtu of purchased heat or steam is multiplied by EPA Table 7 factors "
            "for steam and heat. CH4 and N2O grams are converted to kilograms, then "
            "AR5 GWPs are applied. The factors assume natural-gas production at "
            "80 percent thermal efficiency and are not supplier-specific. "
            "Stored tCO2e is that total rounded half-up to eight decimal places. "
            "On-site combustion is not included."
        ),
        "accounting": {
            "version": ACCOUNTING_VERSION,
            "method": METHOD,
            "status": "verified",
        },
    }
