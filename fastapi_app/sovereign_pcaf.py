"""
Sovereign debt PCAF calc helpers — ported from SPA sovereignDebtFormulaConfigs.ts
"""

from __future__ import annotations

from typing import Any, Dict, List

from .finance_models import CalculationStep
from .ppp_gdp import normalize_sovereign_field_aliases


def _num(v: Any) -> float:
    try:
        n = float(v)
        return n if n == n else 0.0
    except (TypeError, ValueError):
        return 0.0


def _ppp(inputs: Dict[str, Any]) -> float:
    return _num(inputs.get("pp_adjusted_gdp") or inputs.get("ppp_adjusted_gdp"))


def run_sovereign_calculation(
    formula_id: str,
    option_code: str,
    data_quality_score: int,
    methodology: str,
    inputs: Dict[str, Any],
    company_type: str,
) -> Dict[str, Any]:
    inputs = normalize_sovereign_field_aliases(dict(inputs))
    outstanding = _num(inputs.get("outstanding_amount"))
    pp_gdp = _ppp(inputs)
    if pp_gdp <= 0:
        raise ValueError("PPP-adjusted GDP must be greater than 0")
    if outstanding < 0:
        raise ValueError("Outstanding amount must be non-negative")

    attribution = outstanding / pp_gdp
    steps: List[CalculationStep] = [
        CalculationStep(
            step="PPP-Adjusted GDP",
            value=pp_gdp,
            formula=f"PPP-Adjusted GDP = {pp_gdp:.2f}",
        ),
        CalculationStep(
            step="Attribution Factor",
            value=attribution,
            formula=f"{outstanding} / {pp_gdp:.2f} = {attribution:.6f}",
        ),
    ]

    country_emissions = 0.0
    formula_note = ""

    if option_code == "1a":
        country_emissions = _num(
            inputs.get("verified_country_emissions") or inputs.get("verified_emissions")
        )
        if country_emissions <= 0:
            raise ValueError("Verified country emissions must be greater than 0")
        steps.append(
            CalculationStep(
                step="Verified Country Emissions",
                value=country_emissions,
                formula=f"Verified country emissions = {country_emissions:.2f} tCO2e",
            )
        )
        formula_note = "Σ (Outstanding / PPP-adjusted GDP) × Verified country emissions"

    elif option_code == "1b":
        country_emissions = _num(
            inputs.get("unverified_country_emissions") or inputs.get("unverified_emissions")
        )
        if country_emissions <= 0:
            raise ValueError("Unverified country emissions must be greater than 0")
        steps.append(
            CalculationStep(
                step="Unverified Country Emissions",
                value=country_emissions,
                formula=f"Unverified country emissions = {country_emissions:.2f} tCO2e",
            )
        )
        formula_note = "Σ (Outstanding / PPP-adjusted GDP) × Unverified country emissions"

    elif option_code == "2a":
        energy = _num(inputs.get("energy_consumption"))
        ef = _num(inputs.get("emission_factor"))
        process = _num(inputs.get("process_emissions"))
        if energy <= 0 or ef <= 0:
            raise ValueError(
                "Country energy consumption and emission factor must be greater than 0"
            )
        country_emissions = energy * ef + process
        steps.append(
            CalculationStep(
                step="Country Energy Emissions",
                value=country_emissions,
                formula=f"{energy} × {ef} + {process} = {country_emissions:.6f} tCO2e",
            )
        )
        formula_note = "Σ (Outstanding / PPP-adjusted GDP) × Energy × EF"

    elif option_code == "3a":
        sector_revenue = _num(inputs.get("sector_revenue"))
        raw_intensity = _num(inputs.get("sector_intensity"))
        if sector_revenue <= 0:
            raise ValueError("Revenue per sector must be greater than 0")
        if raw_intensity <= 0:
            raise ValueError("Select a sector with intensity data")
        unit = str(inputs.get("sector_intensity_unit") or "kgCO2e/PKR")
        intensity_t = raw_intensity / 1000.0 if "kg" in unit.lower() else raw_intensity
        country_emissions = sector_revenue * intensity_t
        steps.append(
            CalculationStep(
                step="Sector Intensity",
                value=intensity_t,
                formula=f"{raw_intensity} {unit} → {intensity_t:.6e} tCO2e/PKR",
            )
        )
        steps.append(
            CalculationStep(
                step="Sector Emissions",
                value=country_emissions,
                formula=f"{sector_revenue} × {intensity_t:.6e} = {country_emissions:.2f} tCO2e",
            )
        )
        formula_note = (
            "Σ (Outstanding / PPP-adjusted GDP) × Revenue per sector × sector intensity"
        )

    elif option_code == "3b":
        proxy_emissions = _num(inputs.get("proxy_country_emissions"))
        proxy_gdp = _num(
            inputs.get("proxy_pp_adjusted_gdp") or inputs.get("proxy_ppp_adjusted_gdp")
        )
        if proxy_emissions <= 0 or proxy_gdp <= 0:
            raise ValueError(
                "Proxy country GHG and proxy PPP-adjusted GDP must be greater than 0"
            )
        proxy_intensity = proxy_emissions / proxy_gdp
        country_emissions = pp_gdp * proxy_intensity
        steps.append(
            CalculationStep(
                step="Proxy Intensity",
                value=proxy_intensity,
                formula=f"{proxy_emissions} / {proxy_gdp} = {proxy_intensity:.8f} tCO2e / GDP",
            )
        )
        steps.append(
            CalculationStep(
                step="Implied Country Emissions",
                value=country_emissions,
                formula=f"{pp_gdp} × {proxy_intensity:.8f} = {country_emissions:.2f} tCO2e",
            )
        )
        formula_note = (
            "Σ (Outstanding / PPP-adjusted GDP) × PPP-GDP × (proxy GHG / proxy PPP-GDP)"
        )

    else:
        raise ValueError(f"Unsupported sovereign option: {option_code}")

    financed = attribution * country_emissions
    steps.append(
        CalculationStep(
            step="Financed Emissions",
            value=financed,
            formula=f"{attribution:.6f} × {country_emissions:.2f} = {financed:.2f} tCO2e",
        )
    )

    return {
        "attribution_factor": attribution,
        "emission_factor": country_emissions,
        "financed_emissions": financed,
        "data_quality_score": data_quality_score,
        "methodology": methodology,
        "calculation_steps": steps,
        "metadata": {
            "companyType": company_type,
            "optionCode": option_code,
            "category": "sovereign-debt",
            "formula_id": formula_id,
            "ppAdjustedGDP": pp_gdp,
            "formula": formula_note,
        },
    }
