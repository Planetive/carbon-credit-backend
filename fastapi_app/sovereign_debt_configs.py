"""
Sovereign Debt Formula Configurations — aligned with SPA PCAF Table 10.1-7.

Attribution (all options): Outstanding / PPP-adjusted GDP
Scores: 1a=1, 1b=2, 2a=3, 3a=4, 3b=5
"""

from .finance_models import FormulaConfig, FormulaInput, FormulaInputType, FormulaCategory, ScopeType

outstanding_amount_input = FormulaInput(
    name="outstanding_amount",
    label="Outstanding Amount",
    type=FormulaInputType.NUMBER,
    required=True,
    unit="PKR",
    description="Outstanding amount in the sovereign debt loan",
)

# SPA uses pp_adjusted_gdp; ppp_gdp.normalize aliases both names.
ppp_adjusted_gdp_input = FormulaInput(
    name="pp_adjusted_gdp",
    label="PPP-Adjusted GDP",
    type=FormulaInputType.NUMBER,
    required=True,
    unit="PKR",
    description="Purchasing Power Parity-adjusted GDP of the sovereign country",
)


def create_sovereign_debt_formulas():
    return [
        FormulaConfig(
            id="1a-sovereign-debt",
            name="Option 1a - Verified Country Emissions (Sovereign Debt)",
            description="Verified GHG emissions of the country, reported by the country to UNFCCC",
            category=FormulaCategory.SOVEREIGN_DEBT,
            option_code="1a",
            data_quality_score=1,
            inputs=[
                outstanding_amount_input,
                ppp_adjusted_gdp_input,
                FormulaInput(
                    name="verified_country_emissions",
                    label="Verified Country Emissions",
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit="tCO2e",
                    description="Verified country GHG emissions reported to UNFCCC",
                ),
            ],
            applicable_scopes=[ScopeType.SCOPE1, ScopeType.SCOPE2, ScopeType.SCOPE3],
        ),
        FormulaConfig(
            id="1b-sovereign-debt",
            name="Option 1b - Unverified Country Emissions (Sovereign Debt)",
            description="Unverified GHG emissions of the country",
            category=FormulaCategory.SOVEREIGN_DEBT,
            option_code="1b",
            data_quality_score=2,
            inputs=[
                outstanding_amount_input,
                ppp_adjusted_gdp_input,
                FormulaInput(
                    name="unverified_country_emissions",
                    label="Unverified Country Emissions",
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit="tCO2e",
                    description="Unverified country GHG emissions",
                ),
            ],
            applicable_scopes=[ScopeType.SCOPE1, ScopeType.SCOPE2, ScopeType.SCOPE3],
        ),
        FormulaConfig(
            id="2a-sovereign-debt",
            name="Option 2a - Energy Consumption Data (Sovereign Debt)",
            description="Energy consumption data of the country × emission factor",
            category=FormulaCategory.SOVEREIGN_DEBT,
            option_code="2a",
            data_quality_score=3,
            inputs=[
                outstanding_amount_input,
                ppp_adjusted_gdp_input,
                FormulaInput(
                    name="energy_consumption",
                    label="Country Energy Consumption",
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit="MWh",
                    description="Energy consumption data of the country",
                ),
                FormulaInput(
                    name="emission_factor",
                    label="Emission Factor",
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit="tCO2e/MWh",
                    description="Emission factor for the energy source",
                ),
                FormulaInput(
                    name="process_emissions",
                    label="Process Emissions",
                    type=FormulaInputType.NUMBER,
                    required=False,
                    unit="tCO2e",
                ),
            ],
            applicable_scopes=[ScopeType.SCOPE1, ScopeType.SCOPE2],
        ),
        FormulaConfig(
            id="3a-sovereign-debt",
            name="Option 3a - Country Sector Intensity (Sovereign Debt)",
            description="Revenue per sector × sector intensity (GHG / revenue from reference table)",
            category=FormulaCategory.SOVEREIGN_DEBT,
            option_code="3a",
            data_quality_score=4,
            inputs=[
                outstanding_amount_input,
                ppp_adjusted_gdp_input,
                FormulaInput(
                    name="sector_revenue",
                    label="Revenue per sector",
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit="PKR",
                    description="Revenue of the country sector",
                ),
                FormulaInput(
                    name="sector_intensity",
                    label="Sector intensity",
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit="kgCO2e/PKR",
                    description="Country-sector GHG intensity from reference table (GHG / revenue)",
                ),
                FormulaInput(
                    name="sector_intensity_unit",
                    label="Sector intensity unit",
                    type=FormulaInputType.TEXT,
                    required=False,
                    description="e.g. kgCO2e/PKR or tCO2e/PKR",
                ),
            ],
            applicable_scopes=[ScopeType.SCOPE1, ScopeType.SCOPE2, ScopeType.SCOPE3],
        ),
        FormulaConfig(
            id="3b-sovereign-debt",
            name="Option 3b - Proxy Country Intensity (Sovereign Debt)",
            description="Target PPP-adjusted GDP × (proxy country GHG / proxy PPP-adjusted GDP)",
            category=FormulaCategory.SOVEREIGN_DEBT,
            option_code="3b",
            data_quality_score=5,
            inputs=[
                outstanding_amount_input,
                ppp_adjusted_gdp_input,
                FormulaInput(
                    name="proxy_country_emissions",
                    label="Proxy Country GHG",
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit="tCO2e",
                ),
                FormulaInput(
                    name="proxy_pp_adjusted_gdp",
                    label="Proxy Country PPP-Adjusted GDP",
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit="PKR",
                ),
            ],
            applicable_scopes=[ScopeType.SCOPE1, ScopeType.SCOPE2, ScopeType.SCOPE3],
        ),
    ]


SOVEREIGN_DEBT_FORMULAS = create_sovereign_debt_formulas()
