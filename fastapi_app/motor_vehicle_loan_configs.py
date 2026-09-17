"""
Motor Vehicle Loan Formula Configurations — aligned with SPA PCAF Table 10.1-6.

Scores: 1a=1, 1b=1, 2a=2, 2b=3, 3a=4, 3b=5
Calc: multi-vehicle Σ (Outstanding_v / Value_v) × Emissions_v via motor_vehicle_pcaf.
"""

from .finance_models import FormulaConfig, FormulaInput, FormulaInputType, FormulaCategory, ScopeType

outstanding_amount_input = FormulaInput(
    name="outstanding_amount",
    label="Outstanding Amount",
    type=FormulaInputType.NUMBER,
    required=True,
    unit="PKR",
    description="Outstanding amount on the motor vehicle loan",
)

value_at_origination_input = FormulaInput(
    name="total_value_at_origination",
    label="Total Value at Origination",
    type=FormulaInputType.NUMBER,
    required=False,
    unit="PKR",
    description="Sum of vehicle values at origination (from vehicle rows or aggregate)",
)

vehicle_entries_input = FormulaInput(
    name="vehicle_entries",
    label="Vehicle entries",
    type=FormulaInputType.TEXT,
    required=False,
    description="Per-vehicle value, emissions, and optional outstanding (JSON array)",
)

fuel_consumption_input = FormulaInput(
    name="fuel_consumption",
    label="Actual Fuel Consumption",
    type=FormulaInputType.NUMBER,
    required=False,
    unit="L",
    description="Aggregate fallback when vehicle_entries absent",
)

distance_input = FormulaInput(
    name="distance_traveled",
    label="Distance Traveled",
    type=FormulaInputType.NUMBER,
    required=False,
    unit="km",
    description="Aggregate fallback when vehicle_entries absent",
)

efficiency_input = FormulaInput(
    name="efficiency",
    label="Fuel Efficiency",
    type=FormulaInputType.NUMBER,
    required=False,
    unit="L/km",
    description="Aggregate fallback when vehicle_entries absent",
)

emission_factor_input = FormulaInput(
    name="emission_factor",
    label="Fuel Emission Factor",
    type=FormulaInputType.NUMBER,
    required=False,
    unit="tCO2e/L",
    description="Aggregate fallback when vehicle_entries absent",
)

total_vehicle_emissions_input = FormulaInput(
    name="total_vehicle_emissions",
    label="Total Vehicle Emissions",
    type=FormulaInputType.NUMBER,
    required=False,
    unit="tCO2e",
    description="Aggregated vehicle emissions from the vehicle form",
)

_COMMON_FUEL = [
    outstanding_amount_input,
    value_at_origination_input,
    vehicle_entries_input,
    fuel_consumption_input,
    emission_factor_input,
    total_vehicle_emissions_input,
]

_COMMON_DISTANCE = [
    outstanding_amount_input,
    value_at_origination_input,
    vehicle_entries_input,
    distance_input,
    efficiency_input,
    emission_factor_input,
    total_vehicle_emissions_input,
]


def create_motor_vehicle_loan_formulas():
    return [
        FormulaConfig(
            id="1a-motor-vehicle",
            name="Option 1a - Actual Fuel Consumption (Motor Vehicle Loan)",
            description=(
                "Primary data on actual vehicle fuel consumption × EPA Mobile Fuel "
                "emission factor by fuel type"
            ),
            category=FormulaCategory.MOTOR_VEHICLE_LOAN,
            option_code="1a",
            data_quality_score=1,
            inputs=_COMMON_FUEL,
            applicable_scopes=[ScopeType.SCOPE1],
            notes=["fuel_path", "Σ_v (Outstanding_v / Value_v) × Fuel_v × EF_f"],
            metadata={"fuel_path": True},
        ),
        FormulaConfig(
            id="1b-motor-vehicle",
            name="Option 1b - Actual Distance + Make/Model Efficiency (Motor Vehicle Loan)",
            description=(
                "User-entered distance × make/model efficiency × EPA Mobile Fuel emission factor"
            ),
            category=FormulaCategory.MOTOR_VEHICLE_LOAN,
            option_code="1b",
            data_quality_score=1,
            inputs=_COMMON_DISTANCE,
            applicable_scopes=[ScopeType.SCOPE1],
            notes=["distance_path"],
            metadata={"fuel_path": False},
        ),
        FormulaConfig(
            id="2a-motor-vehicle",
            name="Option 2a - Local Distance Statistics (Motor Vehicle Loan)",
            description=(
                "Local distance stats × make/model efficiency × EPA Mobile Fuel emission factor"
            ),
            category=FormulaCategory.MOTOR_VEHICLE_LOAN,
            option_code="2a",
            data_quality_score=2,
            inputs=_COMMON_DISTANCE,
            applicable_scopes=[ScopeType.SCOPE1],
            notes=["distance_path"],
            metadata={"fuel_path": False},
        ),
        FormulaConfig(
            id="2b-motor-vehicle",
            name="Option 2b - Regional Distance Statistics (Motor Vehicle Loan)",
            description=(
                "Regional distance stats × make/model efficiency × EPA Mobile Fuel emission factor"
            ),
            category=FormulaCategory.MOTOR_VEHICLE_LOAN,
            option_code="2b",
            data_quality_score=3,
            inputs=_COMMON_DISTANCE,
            applicable_scopes=[ScopeType.SCOPE1],
            notes=["distance_path"],
            metadata={"fuel_path": False},
        ),
        FormulaConfig(
            id="3a-motor-vehicle",
            name="Option 3a - Combined EPA Vehicle Factors (Motor Vehicle Loan)",
            description=(
                "Statistical distance × vehicle-type efficiency × EPA EF "
                "(Table 3/4/Mobile/Non-Road)"
            ),
            category=FormulaCategory.MOTOR_VEHICLE_LOAN,
            option_code="3a",
            data_quality_score=4,
            inputs=_COMMON_DISTANCE,
            applicable_scopes=[ScopeType.SCOPE1],
            notes=["distance_path"],
            metadata={"fuel_path": False},
        ),
        FormulaConfig(
            id="3b-motor-vehicle",
            name="Option 3b - Average Vehicle Efficiency (Motor Vehicle Loan)",
            description=(
                "Distance from vehicle-use stats × efficiency by engine CC band × "
                "EPA Mobile Fuel emission factor"
            ),
            category=FormulaCategory.MOTOR_VEHICLE_LOAN,
            option_code="3b",
            data_quality_score=5,
            inputs=_COMMON_DISTANCE,
            applicable_scopes=[ScopeType.SCOPE1],
            notes=["distance_path"],
            metadata={"fuel_path": False},
        ),
    ]


MOTOR_VEHICLE_LOAN_FORMULAS = create_motor_vehicle_loan_formulas()
