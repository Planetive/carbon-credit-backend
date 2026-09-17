"""
Mortgage Formula Configurations — aligned with SPA PCAF Table 10.1-5.

Scores: 1a=1, 1b=2, 2a=3, 2b=4, 3=5
Attribution: Outstanding / Property value at origination
(Same math as commercial real estate; category label differs.)
"""

from .finance_models import FormulaConfig, FormulaInput, FormulaInputType, FormulaCategory, ScopeType

outstanding_amount_input = FormulaInput(
    name="outstanding_amount",
    label="Outstanding Amount",
    type=FormulaInputType.NUMBER,
    required=True,
    unit="PKR",
    description="Outstanding amount in the mortgage loan",
)

property_value_input = FormulaInput(
    name="property_value_at_origination",
    label="Property Value at Origination",
    type=FormulaInputType.NUMBER,
    required=True,
    unit="PKR",
    description="Property value at the time of mortgage origination",
)


def create_mortgage_formulas():
    return [
        FormulaConfig(
            id="1a-mortgage",
            name="Option 1a - Supplier-Specific Emission Factors (Mortgage)",
            description="Primary data on actual building energy consumption with supplier-specific emission factors",
            category=FormulaCategory.MORTGAGE,
            option_code="1a",
            data_quality_score=1,
            inputs=[
                outstanding_amount_input,
                property_value_input,
                FormulaInput(
                    name="energy_consumption",
                    label="Actual building energy consumption",
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit="kWh",
                ),
                FormulaInput(
                    name="emission_factor",
                    label="Emission Factor",
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit="tCO2e/kWh",
                ),
            ],
            applicable_scopes=[ScopeType.SCOPE1, ScopeType.SCOPE2],
        ),
        FormulaConfig(
            id="1b-mortgage",
            name="Option 1b - Average Emission Factors (Mortgage)",
            description="Primary data on actual building energy consumption with average grid emission factors",
            category=FormulaCategory.MORTGAGE,
            option_code="1b",
            data_quality_score=2,
            inputs=[
                outstanding_amount_input,
                property_value_input,
                FormulaInput(
                    name="energy_consumption",
                    label="Actual building energy consumption",
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit="kWh",
                ),
                FormulaInput(
                    name="emission_factor",
                    label="Average Grid Emission Factor",
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit="tCO2e/kWh",
                ),
            ],
            applicable_scopes=[ScopeType.SCOPE1, ScopeType.SCOPE2],
        ),
        FormulaConfig(
            id="2a-mortgage",
            name="Option 2a - Energy Labels Data (Mortgage)",
            description="Energy labels intensity × floor area financed × average grid factor",
            category=FormulaCategory.MORTGAGE,
            option_code="2a",
            data_quality_score=3,
            inputs=[
                outstanding_amount_input,
                property_value_input,
                FormulaInput(
                    name="estimated_energy_consumption_from_labels",
                    label="Estimated Energy Consumption of Whole Building",
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit="kWh/m²",
                ),
                FormulaInput(
                    name="floor_area",
                    label="Floor Area Financed",
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit="m²",
                ),
                FormulaInput(
                    name="average_emission_factor",
                    label="Average Grid Emission Factor",
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit="tCO2e/kWh",
                ),
            ],
            applicable_scopes=[ScopeType.SCOPE1, ScopeType.SCOPE2],
        ),
        FormulaConfig(
            id="2b-mortgage",
            name="Option 2b - Statistical Data (Mortgage)",
            description="Statistics intensity × floor area × average emission factor",
            category=FormulaCategory.MORTGAGE,
            option_code="2b",
            data_quality_score=4,
            inputs=[
                outstanding_amount_input,
                property_value_input,
                FormulaInput(
                    name="estimated_energy_consumption_from_statistics",
                    label="Estimated Energy Consumption from Statistics",
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit="kWh/sqft",
                ),
                FormulaInput(
                    name="floor_area",
                    label="Floor Area",
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit="sqft",
                ),
                FormulaInput(
                    name="average_emission_factor",
                    label="Average Emission Factor",
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit="tCO2e/kWh",
                ),
            ],
            applicable_scopes=[ScopeType.SCOPE1, ScopeType.SCOPE2],
        ),
        FormulaConfig(
            id="3-mortgage",
            name="Option 3 - Estimated Energy from Statistics × Buildings (Mortgage)",
            description="Statistics energy per building × number of buildings × average emission factor",
            category=FormulaCategory.MORTGAGE,
            option_code="3",
            data_quality_score=5,
            inputs=[
                outstanding_amount_input,
                property_value_input,
                FormulaInput(
                    name="estimated_energy_consumption_from_statistics",
                    label="Estimated Energy Consumption from Statistics",
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit="kWh/building",
                ),
                FormulaInput(
                    name="number_of_buildings",
                    label="Number of Buildings",
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit="buildings",
                ),
                FormulaInput(
                    name="average_emission_factor",
                    label="Average Emission Factor",
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit="tCO2e/kWh",
                ),
            ],
            applicable_scopes=[ScopeType.SCOPE1, ScopeType.SCOPE2],
        ),
    ]


MORTGAGE_FORMULAS = create_mortgage_formulas()
