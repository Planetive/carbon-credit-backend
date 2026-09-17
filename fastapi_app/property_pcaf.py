"""
Property-backed PCAF calc (commercial real estate + mortgage).

Attribution: Outstanding / Property value at origination
Options:
  1a/1b: energy × EF
  2a: labels intensity × floor area × EF
  2b: stats intensity × floor area × EF
  3:  stats energy/building × buildings × EF
"""

from __future__ import annotations

from typing import Any, Dict, List

from .finance_models import CalculationStep
from .shared_formula_utils import calculate_attribution_factor_commercial_real_estate


def _num(v: Any) -> float:
    try:
        n = float(v)
        return n if n == n else 0.0
    except (TypeError, ValueError):
        return 0.0


def normalize_property_field_aliases(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """Map legacy backend field names to SPA field names."""
    out = dict(inputs)
    if not out.get("energy_consumption"):
        if out.get("actual_energy_consumption"):
            out["energy_consumption"] = out["actual_energy_consumption"]
    if not out.get("emission_factor"):
        if out.get("supplier_specific_emission_factor"):
            out["emission_factor"] = out["supplier_specific_emission_factor"]
        elif out.get("average_emission_factor") and out.get("energy_consumption"):
            # 1a/1b path may send average_emission_factor instead of emission_factor
            out["emission_factor"] = out["average_emission_factor"]
    return out


def run_property_loan_calculation(
    *,
    formula_id: str,
    option_code: str,
    data_quality_score: int,
    methodology: str,
    category: str,
    inputs: Dict[str, Any],
    company_type: str,
) -> Dict[str, Any]:
    inputs = normalize_property_field_aliases(inputs)
    outstanding = _num(inputs.get("outstanding_amount"))
    property_value = _num(inputs.get("property_value_at_origination"))
    if property_value <= 0:
        raise ValueError("Property value at origination must be greater than 0")
    if outstanding < 0:
        raise ValueError("Outstanding amount must be non-negative")

    attribution = calculate_attribution_factor_commercial_real_estate(
        outstanding, property_value
    )
    steps: List[CalculationStep] = [
        CalculationStep(
            step="Property Value at Origination",
            value=property_value,
            formula=f"Property Value at Origination = {property_value:.2f}",
        ),
        CalculationStep(
            step="Attribution Factor",
            value=attribution,
            formula=f"{outstanding} / {property_value:.2f} = {attribution:.6f}",
        ),
    ]

    total_emissions = 0.0
    formula_note = ""
    meta_extra: Dict[str, Any] = {}

    if option_code in ("1a", "1b"):
        energy = _num(inputs.get("energy_consumption"))
        ef = _num(inputs.get("emission_factor") or inputs.get("average_emission_factor"))
        if energy <= 0 or ef <= 0:
            raise ValueError(
                "Actual energy consumption and emission factor must be greater than 0"
            )
        total_emissions = energy * ef
        steps.append(
            CalculationStep(
                step="Building energy emissions",
                value=total_emissions,
                formula=f"{energy} × {ef} = {total_emissions:.6f} tCO2e",
            )
        )
        formula_note = (
            "Σ (Outstanding / Property value) × Actual energy × Supplier-specific EF"
            if option_code == "1a"
            else "Σ (Outstanding / Property value) × Actual energy × Average grid EF"
        )

    elif option_code == "2a":
        intensity = _num(inputs.get("estimated_energy_consumption_from_labels"))
        floor_area = _num(inputs.get("floor_area"))
        ef = _num(inputs.get("average_emission_factor") or inputs.get("emission_factor"))
        if intensity <= 0 or floor_area <= 0 or ef <= 0:
            raise ValueError(
                "Energy from labels, floor area, and average emission factor must be greater than 0"
            )
        total_energy = intensity * floor_area
        total_emissions = total_energy * ef
        steps.append(
            CalculationStep(
                step="Total Energy Consumption",
                value=total_energy,
                formula=(
                    f"{intensity:.2f} kWh/m² × {floor_area:.2f} m² financed = "
                    f"{total_energy:.2f} kWh"
                ),
            )
        )
        steps.append(
            CalculationStep(
                step="Total Emissions",
                value=total_emissions,
                formula=f"{total_energy:.2f} kWh × {ef} tCO2e/kWh = {total_emissions:.2f} tCO2e",
            )
        )
        formula_note = (
            "Σ (Outstanding / Property value) × Whole-building energy × "
            "Floor area financed × Average grid EF"
        )
        meta_extra = {
            "estimatedEnergyConsumptionFromLabels": intensity,
            "floorArea": floor_area,
            "totalEnergyConsumption": total_energy,
        }

    elif option_code == "2b":
        intensity = _num(inputs.get("estimated_energy_consumption_from_statistics"))
        floor_area = _num(inputs.get("floor_area"))
        ef = _num(inputs.get("average_emission_factor") or inputs.get("emission_factor"))
        if intensity <= 0 or floor_area <= 0 or ef <= 0:
            raise ValueError(
                "Energy from statistics, floor area, and average emission factor must be greater than 0"
            )
        total_energy = intensity * floor_area
        total_emissions = total_energy * ef
        steps.append(
            CalculationStep(
                step="Total Energy Consumption",
                value=total_energy,
                formula=(
                    f"{intensity:.2f} kWh/sqft × {floor_area:.2f} sqft = "
                    f"{total_energy:.2f} kWh"
                ),
            )
        )
        steps.append(
            CalculationStep(
                step="Total Emissions",
                value=total_emissions,
                formula=f"{total_energy:.2f} kWh × {ef} tCO2e/kWh = {total_emissions:.2f} tCO2e",
            )
        )
        formula_note = (
            "Σ (Outstanding / Property value) × Energy from statistics × Floor area × Average EF"
        )
        meta_extra = {
            "estimatedEnergyConsumptionFromStatistics": intensity,
            "floorArea": floor_area,
            "totalEnergyConsumption": total_energy,
        }

    elif option_code == "3":
        per_building = _num(inputs.get("estimated_energy_consumption_from_statistics"))
        buildings = _num(inputs.get("number_of_buildings"))
        ef = _num(inputs.get("average_emission_factor") or inputs.get("emission_factor"))
        if per_building <= 0 or buildings <= 0 or ef <= 0:
            raise ValueError(
                "Statistics energy, number of buildings, and average emission factor must be greater than 0"
            )
        total_energy = per_building * buildings
        total_emissions = total_energy * ef
        steps.append(
            CalculationStep(
                step="Total Energy Consumption",
                value=total_energy,
                formula=(
                    f"{per_building:.2f} kWh/building × {buildings} = "
                    f"{total_energy:.2f} kWh"
                ),
            )
        )
        steps.append(
            CalculationStep(
                step="Total Emissions",
                value=total_emissions,
                formula=f"{total_energy:.2f} kWh × {ef} tCO2e/kWh = {total_emissions:.2f} tCO2e",
            )
        )
        formula_note = (
            "Σ (Outstanding / Property value) × Energy from statistics × "
            "Number of buildings × Average EF"
        )
        meta_extra = {
            "estimatedEnergyFromStats": per_building,
            "numberOfBuildings": buildings,
            "totalEnergyConsumption": total_energy,
        }

    else:
        raise ValueError(f"Unsupported property loan option: {option_code}")

    financed = attribution * total_emissions
    steps.append(
        CalculationStep(
            step="Financed Emissions",
            value=financed,
            formula=f"{attribution:.6f} × {total_emissions:.6f} = {financed:.2f} tCO2e",
        )
    )

    metadata: Dict[str, Any] = {
        "companyType": company_type,
        "optionCode": option_code,
        "category": category,
        "formula_id": formula_id,
        "propertyValueAtOrigination": property_value,
        "totalEmissions": total_emissions,
        "formula": formula_note,
    }
    metadata.update(meta_extra)

    return {
        "attribution_factor": attribution,
        "emission_factor": total_emissions,
        "financed_emissions": financed,
        "data_quality_score": data_quality_score,
        "methodology": methodology,
        "calculation_steps": steps,
        "metadata": metadata,
    }
