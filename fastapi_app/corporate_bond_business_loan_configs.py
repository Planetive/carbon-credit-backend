"""
Corporate Bond and Business Loan Formula Configurations - Migrated from TypeScript
This file contains all PCAF formulas for Corporate Bonds and Business Loans.

Migrated from: src/pages/finance_facilitated/config/corporateBondAndBusinessLoanFormulaConfigs.ts
No formulas or working logic has been changed - only converted from TypeScript to Python.
"""

from .finance_models import FormulaConfig, FormulaInput, FormulaInputType, FormulaCategory, ScopeType
from .shared_formula_utils import (
    calculate_attribution_factor_listed,
    calculate_attribution_factor_unlisted,
    calculate_evic,
    calculate_total_equity_plus_debt,
    calculate_financed_emissions
)

# ============================================================================
# CORPORATE BOND AND BUSINESS LOAN FORMULA CONFIGURATIONS
# ============================================================================

def create_corporate_bond_business_loan_formulas():
    """Create all corporate bond and business loan formula configurations"""
    
    # Common inputs
    outstanding_amount_input = FormulaInput(
        name='outstanding_amount',
        label='Outstanding Amount',
        type=FormulaInputType.NUMBER,
        required=True,
        unit='PKR',
        description='Outstanding amount in the company'
    )
    
    total_assets_input = FormulaInput(
        name='total_assets',
        label='Total Assets Value',
        type=FormulaInputType.NUMBER,
        required=True,
        unit='PKR',
        description='Total assets value for attribution factor calculation'
    )
    
    evic_input = FormulaInput(
        name='evic',
        label='EVIC (Enterprise Value Including Cash)',
        type=FormulaInputType.NUMBER,
        required=True,
        unit='PKR',
        description='EVIC for listed companies'
    )
    
    total_equity_plus_debt_input = FormulaInput(
        name='total_equity_plus_debt',
        label='Total Equity + Debt',
        type=FormulaInputType.NUMBER,
        required=True,
        unit='PKR',
        description='Total equity plus debt for business loans and equity investments'
    )
    
    return [
        # LISTED COMPANIES - OPTION 1A - VERIFIED GHG EMISSIONS
        FormulaConfig(
            id='1a-listed-equity',
            name='Option 1a - Verified GHG Emissions (Listed)',
            description='Verified GHG emissions data from the company in accordance with the GHG Protocol',
            category=FormulaCategory.LISTED_EQUITY,
            option_code='1a',
            data_quality_score=1,
            inputs=[
                outstanding_amount_input,
                total_assets_input,
                evic_input,
                FormulaInput(
                    name='verified_emissions',
                    label='Verified GHG Emissions',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='tCO2e',
                    description='Total carbon emissions from the company (verified by third party)'
                )
            ],
            applicable_scopes=[ScopeType.SCOPE1, ScopeType.SCOPE2, ScopeType.SCOPE3]
        ),
        
        # LISTED COMPANIES - OPTION 1B - UNVERIFIED GHG EMISSIONS
        FormulaConfig(
            id='1b-listed-equity',
            name='Option 1b - Unverified GHG Emissions (Listed)',
            description='Unverified GHG emissions data from the company',
            category=FormulaCategory.LISTED_EQUITY,
            option_code='1b',
            data_quality_score=2,
            inputs=[
                outstanding_amount_input,
                total_assets_input,
                evic_input,
                FormulaInput(
                    name='unverified_emissions',
                    label='Unverified GHG Emissions',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='tCO2e',
                    description='Total carbon emissions from the company (unverified)'
                )
            ],
            applicable_scopes=[ScopeType.SCOPE1, ScopeType.SCOPE2, ScopeType.SCOPE3]
        ),
        
        # LISTED COMPANIES - OPTION 2A - ENERGY CONSUMPTION DATA
        FormulaConfig(
            id='2a-listed-equity',
            name='Option 2a - Energy Consumption Data (Listed)',
            description='Energy consumption data from the company',
            category=FormulaCategory.LISTED_EQUITY,
            option_code='2a',
            data_quality_score=2,
            inputs=[
                outstanding_amount_input,
                total_assets_input,
                evic_input,
                FormulaInput(
                    name='energy_consumption',
                    label='Energy Consumption',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='MWh',
                    description='Energy consumption data from the company'
                ),
                FormulaInput(
                    name='emission_factor',
                    label='Emission Factor',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='tCO2e/MWh',
                    description='Emission factor for the energy source'
                ),
                FormulaInput(
                    name='process_emissions',
                    label='Process Emissions',
                    type=FormulaInputType.NUMBER,
                    required=False,
                    unit='tCO2e',
                    description='Optional process emissions added to energy-related emissions before attribution'
                )
            ],
            applicable_scopes=[ScopeType.SCOPE1, ScopeType.SCOPE2]
        ),
        
        # LISTED COMPANIES - OPTION 2B - PRODUCTION DATA
        FormulaConfig(
            id='2b-listed-equity',
            name='Option 2b - Production Data (Listed)',
            description='Production data from the company',
            category=FormulaCategory.LISTED_EQUITY,
            option_code='2b',
            data_quality_score=3,
            inputs=[
                outstanding_amount_input,
                total_assets_input,
                evic_input,
                FormulaInput(
                    name='production',
                    label='Production',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='tonnes',
                    description='Production data from the company'
                ),
                FormulaInput(
                    name='production_emission_factor',
                    label='Production Emission Factor',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='tCO2e/tonne',
                    description='Emission factor per unit of production'
                )
            ],
            applicable_scopes=[ScopeType.SCOPE1, ScopeType.SCOPE2]
        ),
        
        # UNLISTED COMPANIES - OPTION 1A - VERIFIED GHG EMISSIONS
        FormulaConfig(
            id='1a-unlisted-equity',
            name='Option 1a - Verified GHG Emissions (Unlisted)',
            description='Verified GHG emissions data from the unlisted company in accordance with the GHG Protocol',
            category=FormulaCategory.BUSINESS_LOANS,
            option_code='1a',
            data_quality_score=1,
            inputs=[
                outstanding_amount_input,
                total_assets_input,
                total_equity_plus_debt_input,
                FormulaInput(
                    name='verified_emissions',
                    label='Verified GHG Emissions',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='tCO2e',
                    description='Total carbon emissions from the company (verified by third party)'
                )
            ],
            applicable_scopes=[ScopeType.SCOPE1, ScopeType.SCOPE2, ScopeType.SCOPE3]
        ),
        
        # UNLISTED COMPANIES - OPTION 1B - UNVERIFIED GHG EMISSIONS
        FormulaConfig(
            id='1b-unlisted-equity',
            name='Option 1b - Unverified GHG Emissions (Unlisted)',
            description='Unverified GHG emissions data from the unlisted company',
            category=FormulaCategory.BUSINESS_LOANS,
            option_code='1b',
            data_quality_score=2,
            inputs=[
                outstanding_amount_input,
                total_assets_input,
                total_equity_plus_debt_input,
                FormulaInput(
                    name='unverified_emissions',
                    label='Unverified GHG Emissions',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='tCO2e',
                    description='Total carbon emissions from the company (unverified)'
                )
            ],
            applicable_scopes=[ScopeType.SCOPE1, ScopeType.SCOPE2, ScopeType.SCOPE3]
        ),
        
        # UNLISTED COMPANIES - OPTION 2A - ENERGY CONSUMPTION DATA
        FormulaConfig(
            id='2a-unlisted-equity',
            name='Option 2a - Energy Consumption Data (Unlisted)',
            description='Energy consumption data from the unlisted company',
            category=FormulaCategory.BUSINESS_LOANS,
            option_code='2a',
            data_quality_score=2,
            inputs=[
                outstanding_amount_input,
                total_assets_input,
                total_equity_plus_debt_input,
                FormulaInput(
                    name='energy_consumption',
                    label='Energy Consumption',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='MWh',
                    description='Energy consumption data from the company'
                ),
                FormulaInput(
                    name='emission_factor',
                    label='Emission Factor',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='tCO2e/MWh',
                    description='Emission factor for the energy source'
                ),
                FormulaInput(
                    name='process_emissions',
                    label='Process Emissions',
                    type=FormulaInputType.NUMBER,
                    required=False,
                    unit='tCO2e',
                    description='Optional process emissions added to energy-related emissions before attribution'
                )
            ],
            applicable_scopes=[ScopeType.SCOPE1, ScopeType.SCOPE2]
        ),
        
        # UNLISTED COMPANIES - OPTION 2B - PRODUCTION DATA
        FormulaConfig(
            id='2b-unlisted-equity',
            name='Option 2b - Production Data (Unlisted)',
            description='Production data from the unlisted company',
            category=FormulaCategory.BUSINESS_LOANS,
            option_code='2b',
            data_quality_score=3,
            inputs=[
                outstanding_amount_input,
                total_assets_input,
                total_equity_plus_debt_input,
                FormulaInput(
                    name='production',
                    label='Production',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='tonnes',
                    description='Production data from the company'
                ),
                FormulaInput(
                    name='production_emission_factor',
                    label='Production Emission Factor',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='tCO2e/tonne',
                    description='Emission factor per unit of production'
                )
            ],
            applicable_scopes=[ScopeType.SCOPE1, ScopeType.SCOPE2]
        ),

        # LISTED COMPANIES - OPTION 3A - REVENUE × SECTOR INTENSITY
        FormulaConfig(
            id='3a-listed-equity',
            name='Option 3a - Revenue-based (Listed)',
            description='Company revenue × sector intensity (GHG / revenue from reference table)',
            category=FormulaCategory.LISTED_EQUITY,
            option_code='3a',
            data_quality_score=4,
            inputs=[
                outstanding_amount_input,
                evic_input,
                FormulaInput(
                    name='company_revenue',
                    label='Company Revenue',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='PKR',
                    description='Revenue of the borrower / investee'
                ),
                FormulaInput(
                    name='sector_intensity',
                    label='Sector intensity',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='kgCO2e/PKR',
                    description='Country-sector GHG intensity supplied by the caller (not invented by the engine)'
                ),
                FormulaInput(
                    name='sector_intensity_unit',
                    label='Sector intensity unit',
                    type=FormulaInputType.TEXT,
                    required=False,
                    description='kgCO2e/PKR or tCO2e/PKR'
                )
            ],
            applicable_scopes=[ScopeType.SCOPE1, ScopeType.SCOPE2, ScopeType.SCOPE3]
        ),

        # UNLISTED COMPANIES - OPTION 3A - REVENUE × SECTOR INTENSITY
        FormulaConfig(
            id='3a-unlisted-equity',
            name='Option 3a - Revenue-based (Unlisted/Private)',
            description='Company revenue × sector intensity (GHG / revenue from reference table)',
            category=FormulaCategory.BUSINESS_LOANS,
            option_code='3a',
            data_quality_score=4,
            inputs=[
                outstanding_amount_input,
                total_equity_plus_debt_input,
                FormulaInput(
                    name='company_revenue',
                    label='Company Revenue',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='PKR',
                    description='Revenue of the borrower / investee'
                ),
                FormulaInput(
                    name='sector_intensity',
                    label='Sector intensity',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='kgCO2e/PKR',
                    description='Country-sector GHG intensity supplied by the caller (not invented by the engine)'
                ),
                FormulaInput(
                    name='sector_intensity_unit',
                    label='Sector intensity unit',
                    type=FormulaInputType.TEXT,
                    required=False,
                    description='kgCO2e/PKR or tCO2e/PKR'
                )
            ],
            applicable_scopes=[ScopeType.SCOPE1, ScopeType.SCOPE2, ScopeType.SCOPE3]
        ),

        # LISTED COMPANIES - OPTION 3C - OUTSTANDING × ATR × SECTOR INTENSITY
        FormulaConfig(
            id='3c-listed-equity',
            name='Option 3c - Asset Turnover Ratio (Listed)',
            description='Outstanding × sector ATR × sector intensity (GHG / revenue from reference table)',
            category=FormulaCategory.LISTED_EQUITY,
            option_code='3c',
            data_quality_score=5,
            inputs=[
                outstanding_amount_input,
                FormulaInput(
                    name='asset_turnover_ratio',
                    label='Asset Turnover Ratio',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='ratio',
                    description='Asset turnover ratio for the sector'
                ),
                FormulaInput(
                    name='sector_intensity',
                    label='Sector intensity',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='kgCO2e/PKR',
                    description='Country-sector GHG intensity supplied by the caller (not invented by the engine)'
                ),
                FormulaInput(
                    name='sector_intensity_unit',
                    label='Sector intensity unit',
                    type=FormulaInputType.TEXT,
                    required=False,
                    description='kgCO2e/PKR or tCO2e/PKR'
                )
            ],
            applicable_scopes=[ScopeType.SCOPE1, ScopeType.SCOPE2, ScopeType.SCOPE3]
        ),

        # UNLISTED COMPANIES - OPTION 3C - OUTSTANDING × ATR × SECTOR INTENSITY
        FormulaConfig(
            id='3c-unlisted-equity',
            name='Option 3c - Asset Turnover Ratio (Unlisted/Private)',
            description='Outstanding × sector ATR × sector intensity (GHG / revenue from reference table)',
            category=FormulaCategory.BUSINESS_LOANS,
            option_code='3c',
            data_quality_score=5,
            inputs=[
                outstanding_amount_input,
                FormulaInput(
                    name='asset_turnover_ratio',
                    label='Asset Turnover Ratio',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='ratio',
                    description='Asset turnover ratio for the sector'
                ),
                FormulaInput(
                    name='sector_intensity',
                    label='Sector intensity',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='kgCO2e/PKR',
                    description='Country-sector GHG intensity supplied by the caller (not invented by the engine)'
                ),
                FormulaInput(
                    name='sector_intensity_unit',
                    label='Sector intensity unit',
                    type=FormulaInputType.TEXT,
                    required=False,
                    description='kgCO2e/PKR or tCO2e/PKR'
                )
            ],
            applicable_scopes=[ScopeType.SCOPE1, ScopeType.SCOPE2, ScopeType.SCOPE3]
        )
    ]

# Export the formulas
CORPORATE_BOND_BUSINESS_LOAN_FORMULAS = create_corporate_bond_business_loan_formulas()
