"""
PCAF Table 10.1-6 — motor vehicle loans (multi-vehicle).
Financed emissions = Σ_v (Outstanding_v / Value_v) × Emissions_v

Ported from SPA: src/features/finance-emissions/utils/motorVehiclePcaf.ts
"""

from __future__ import annotations

from typing import Any, Dict, List


def _num(v: Any) -> float:
    try:
        n = float(v)
        return n if n == n else 0.0  # NaN → 0
    except (TypeError, ValueError):
        return 0.0


def allocate_outstanding_per_vehicle(
    outstanding_total: float, vehicles: List[Dict[str, Any]]
) -> List[float]:
    """Allocate loan outstanding across vehicles (explicit per row, then proportional remainder)."""
    if not vehicles:
        return []

    explicit = [
        _num(v.get("outstanding_amount")) if _num(v.get("outstanding_amount")) > 0 else 0.0
        for v in vehicles
    ]
    explicit_sum = sum(explicit)
    remaining = max(0.0, outstanding_total - explicit_sum)

    implicit_indices = [
        i for i, v in enumerate(vehicles) if not (_num(v.get("outstanding_amount")) > 0)
    ]
    implicit_value_total = sum(
        _num(vehicles[i].get("value_at_origination")) for i in implicit_indices
    )

    allocations: List[float] = []
    for i, v in enumerate(vehicles):
        if _num(v.get("outstanding_amount")) > 0:
            allocations.append(_num(v.get("outstanding_amount")))
        elif implicit_value_total <= 0:
            allocations.append(0.0)
        else:
            value = _num(v.get("value_at_origination"))
            allocations.append(remaining * (value / implicit_value_total))
    return allocations


def compute_motor_vehicle_pcaf_financed(
    outstanding_total: float, vehicles: List[Dict[str, Any]]
) -> Dict[str, Any]:
    if not vehicles:
        return {
            "total_financed_emissions": 0.0,
            "total_vehicle_emissions": 0.0,
            "total_value_at_origination": 0.0,
            "display_attribution_factor": 0.0,
            "vehicle_results": [],
        }

    allocations = allocate_outstanding_per_vehicle(outstanding_total, vehicles)
    vehicle_results: List[Dict[str, Any]] = []
    total_financed = 0.0
    total_emissions = 0.0
    total_value = 0.0

    for i, v in enumerate(vehicles):
        value = _num(v.get("value_at_origination"))
        emissions = _num(v.get("emissions_tco2e"))
        outstanding_v = allocations[i] if i < len(allocations) else 0.0
        name = str(v.get("name") or f"Vehicle {i + 1}")
        vid = str(v.get("id") or f"vehicle-{i + 1}")
        total_value += value
        total_emissions += emissions

        if value <= 0:
            vehicle_results.append(
                {
                    "id": vid,
                    "name": name,
                    "value_at_origination": value,
                    "outstanding_allocated": outstanding_v,
                    "attribution_factor": 0.0,
                    "vehicle_emissions": emissions,
                    "financed_emissions": 0.0,
                    "formula": f"{name}: value at origination must be > 0",
                }
            )
            continue

        attr = outstanding_v / value
        financed = attr * emissions
        total_financed += financed
        vehicle_results.append(
            {
                "id": vid,
                "name": name,
                "value_at_origination": value,
                "outstanding_allocated": outstanding_v,
                "attribution_factor": attr,
                "vehicle_emissions": emissions,
                "financed_emissions": financed,
                "formula": (
                    f"({outstanding_v:.2f} / {value:.2f}) × {emissions:.6f} = {financed:.6f} tCO2e"
                ),
            }
        )

    return {
        "total_financed_emissions": total_financed,
        "total_vehicle_emissions": total_emissions,
        "total_value_at_origination": total_value,
        "display_attribution_factor": (
            total_financed / total_emissions if total_emissions > 0 else 0.0
        ),
        "vehicle_results": vehicle_results,
    }


def parse_motor_vehicle_entries(raw: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for idx, row in enumerate(raw):
        if not isinstance(row, dict):
            continue
        value = _num(row.get("value_at_origination", row.get("totalValueAtOrigination")))
        emissions = _num(row.get("emissions_tco2e", row.get("emissions")))
        vid = str(row.get("id") or "")
        if not vid and value <= 0 and emissions <= 0:
            continue
        entry: Dict[str, Any] = {
            "id": vid or f"vehicle-{idx + 1}",
            "name": str(row.get("name") or f"Vehicle {idx + 1}"),
            "value_at_origination": value,
            "emissions_tco2e": emissions,
        }
        oa = _num(row.get("outstanding_amount"))
        if oa > 0:
            entry["outstanding_amount"] = oa
        for key in (
            "fuel_consumption",
            "efficiency",
            "emission_factor",
            "emission_factor_tco2e",
        ):
            n = _num(row.get(key))
            if n > 0:
                entry[key if key != "emission_factor_tco2e" else "emission_factor"] = n
        dist = _num(row.get("distance_traveled", row.get("distance")))
        if dist > 0:
            entry["distance_traveled"] = dist
        for key in ("fuel_type", "activity", "vehicle_type", "make", "model"):
            if row.get(key):
                entry[key] = str(row[key])
        out.append(entry)
    return out


def resolve_vehicle_rows(inputs: Dict[str, Any], *, fuel_path: bool) -> List[Dict[str, Any]]:
    parsed = parse_motor_vehicle_entries(inputs.get("vehicle_entries"))
    if parsed:
        return parsed

    emissions = _num(inputs.get("total_vehicle_emissions"))
    value = _num(inputs.get("total_value_at_origination"))
    if emissions <= 0:
        if fuel_path:
            emissions = _num(inputs.get("fuel_consumption")) * _num(inputs.get("emission_factor"))
        else:
            emissions = (
                _num(inputs.get("distance_traveled"))
                * _num(inputs.get("efficiency"))
                * _num(inputs.get("emission_factor"))
            )
    if emissions > 0 and value > 0:
        return [
            {
                "id": "single",
                "name": "Vehicle 1",
                "value_at_origination": value,
                "emissions_tco2e": emissions,
            }
        ]
    return []


def run_motor_vehicle_calculation(
    inputs: Dict[str, Any],
    company_type: str,
    option_code: str,
    data_quality_score: int,
    methodology: str,
    formula_note: str,
    *,
    fuel_path: bool,
) -> Dict[str, Any]:
    outstanding_amount = _num(inputs.get("outstanding_amount"))
    vehicles = resolve_vehicle_rows(inputs, fuel_path=fuel_path)

    if not vehicles:
        raise ValueError(
            "Add at least one vehicle with fuel data and value at origination."
            if fuel_path
            else "Add at least one vehicle with distance, efficiency, and value at origination."
        )
    if any(_num(v.get("value_at_origination")) <= 0 for v in vehicles):
        raise ValueError("Each vehicle must have a value at origination greater than 0.")
    if any(_num(v.get("emissions_tco2e")) <= 0 for v in vehicles):
        raise ValueError("Each vehicle must have emissions greater than 0.")
    if outstanding_amount <= 0:
        raise ValueError("Outstanding loan amount must be greater than 0.")

    pcaf = compute_motor_vehicle_pcaf_financed(outstanding_amount, vehicles)
    steps = [
        {
            "step": "Total value at origination",
            "value": pcaf["total_value_at_origination"],
            "formula": f"Σ Value_v = {pcaf['total_value_at_origination']:.2f} PKR",
        }
    ]
    for vr in pcaf["vehicle_results"]:
        steps.append(
            {
                "step": f"{vr['name']} — attribution",
                "value": vr["attribution_factor"],
                "formula": (
                    f"{vr['outstanding_allocated']:.2f} / {vr['value_at_origination']:.2f} "
                    f"= {vr['attribution_factor']:.6f}"
                ),
            }
        )
    for vr in pcaf["vehicle_results"]:
        steps.append(
            {
                "step": f"{vr['name']} — financed",
                "value": vr["financed_emissions"],
                "formula": vr["formula"],
            }
        )
    steps.append(
        {
            "step": "Total financed emissions",
            "value": pcaf["total_financed_emissions"],
            "formula": (
                f"Σ_v (Outstanding_v / Value_v) × Emissions_v = "
                f"{pcaf['total_financed_emissions']:.6f} tCO2e"
            ),
        }
    )

    return {
        "attribution_factor": pcaf["display_attribution_factor"],
        "emission_factor": pcaf["total_vehicle_emissions"],
        "financed_emissions": pcaf["total_financed_emissions"],
        "data_quality_score": data_quality_score,
        "methodology": methodology,
        "calculation_steps": steps,
        "metadata": {
            "companyType": company_type,
            "optionCode": option_code,
            "category": "motor_vehicle_loan",
            "totalValueAtOrigination": pcaf["total_value_at_origination"],
            "totalVehicleEmissions": pcaf["total_vehicle_emissions"],
            "vehicleCount": len(vehicles),
            "vehicleResults": pcaf["vehicle_results"],
            "formula": formula_note,
        },
    }
