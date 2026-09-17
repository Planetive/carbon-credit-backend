"""
Commercial Real Estate Formula Configurations — aligned with SPA PCAF.

Scores: 1a=1, 1b=2, 2a=3, 2b=4, 3=5
Attribution: Outstanding / Property value at origination
"""

from .finance_models import FormulaConfig, FormulaInput, FormulaInputType, FormulaCategory, ScopeType

outstanding_amount_input = FormulaInput(
    name="outstanding_amount",
    label="Outstanding Amount",
    type=FormulaInputType.NUMBER,
    required=True,
    unit="PKR",
    description="Outstanding amount in the commercial real estate loan",
)

property_value_input = FormulaInput(
    name="property_value_at_origination",
    label="Property Value at Origination",
    type=FormulaInputType.NUMBER,
    required=True,
    unit="PKR",
    description="Value of the commercial property at the time of loan origination",
)


def create_commercial_real_estate_formulas():
    return [
        FormulaConfig(
            id="1a-commercial-real-estate",
            name="Option 1a - Supplier-Specific Emission Factors (Commercial Real Estate)",
            description="Primary data on actual building energy consumption with supplier-specific emission factors",
            category=FormulaCategory.COMMERCIAL_REAL_ESTATE,
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
            id="1b-commercial-real-estate",
            name="Option 1b - Average Emission Factors (Commercial Real Estate)",
            description="Primary data on actual building energy consumption with average grid emission factors",
            category=FormulaCategory.COMMERCIAL_REAL_ESTATE,
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
            id="2a-commercial-real-estate",
            name="Option 2a - Estimated Energy Consumption from Energy Labels (Commercial Real Estate)",
            description="Energy labels intensity × floor area financed × average grid factor",
            category=FormulaCategory.COMMERCIAL_REAL_ESTATE,
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
            id="2b-commercial-real-estate",
            name="Option 2b - Estimated Energy Consumption from Statistics (Commercial Real Estate)",
            description="CBECS/statistics intensity × floor area × average emission factor",
            category=FormulaCategory.COMMERCIAL_REAL_ESTATE,
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
            id="3-commercial-real-estate",
            name="Option 3 - Estimated Energy from Statistics × Buildings (Commercial Real Estate)",
            description="Statistics energy per building × number of buildings × average emission factor",
            category=FormulaCategory.COMMERCIAL_REAL_ESTATE,
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


COMMERCIAL_REAL_ESTATE_FORMULAS = create_commercial_real_estate_formulas()
