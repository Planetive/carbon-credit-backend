"""
Facilitated Emission Formula Configurations - Migrated from TypeScript
This file contains all PCAF formulas for Facilitated Emissions.

Migrated from: src/pages/finance_facilitated/config/facilitatedEmissionFormulaConfigs.ts
No formulas or working logic has been changed - only converted from TypeScript to Python.
"""

from .finance_models import FormulaConfig, FormulaInput, FormulaInputType, FormulaCategory, ScopeType
from .shared_formula_utils import (
    calculate_evic,
    calculate_total_equity_plus_debt,
    calculate_facilitated_emissions,
    calculate_attribution_factor_listed,
    calculate_attribution_factor_unlisted
)

# ============================================================================
# CALCULATION FUNCTIONS (Matching Frontend Logic Exactly)
# ============================================================================

def _calculate_1a_facilitated_verified_listed(inputs: dict, company_type: str) -> dict:
    """Option 1a - Verified GHG Emissions (Facilitated - Listed)"""
    facilitated_amount = inputs.get('facilitated_amount', 0)
    weighting_factor = inputs.get('weighting_factor', 0)
    verified_emissions = inputs.get('verified_emissions', 0)
    evic = calculate_evic(inputs)
    attribution_factor = calculate_attribution_factor_listed(facilitated_amount, evic)
    facilitated_emissions = (facilitated_amount / evic) * weighting_factor * verified_emissions
    
    return {
        'attributionFactor': attribution_factor,
        'emissionFactor': verified_emissions,
        'financedEmissions': facilitated_emissions,
        'dataQualityScore': 1,
        'methodology': 'Option 1a - Verified GHG Emissions (Facilitated - Listed)',
        'calculationSteps': [
            {
                'step': 'EVIC Calculation',
                'value': evic,
                'formula': f'Share Price × Outstanding Shares + Total Debt + Minority Interest + Preferred Stock = {evic:.2f}'
            },
            {
                'step': 'Attribution Factor',
                'value': attribution_factor,
                'formula': f'{facilitated_amount} / {evic} = {attribution_factor:.6f}'
            },
            {
                'step': 'Facilitated Emissions',
                'value': facilitated_emissions,
                'formula': f'({facilitated_amount} / {evic}) × {weighting_factor} × {verified_emissions} = {facilitated_emissions:.2f} tCO2e'
            }
        ]
    }

def _calculate_1a_facilitated_verified_unlisted(inputs: dict, company_type: str) -> dict:
    """Option 1a - Verified GHG Emissions (Facilitated - Unlisted)"""
    facilitated_amount = inputs.get('facilitated_amount', 0)
    weighting_factor = inputs.get('weighting_factor', 0)
    verified_emissions = inputs.get('verified_emissions', 0)
    total_equity_plus_debt = calculate_total_equity_plus_debt(inputs)
    attribution_factor = calculate_attribution_factor_unlisted(facilitated_amount, total_equity_plus_debt)
    facilitated_emissions = (facilitated_amount / total_equity_plus_debt) * weighting_factor * verified_emissions
    
    return {
        'attributionFactor': attribution_factor,
        'emissionFactor': verified_emissions,
        'financedEmissions': facilitated_emissions,
        'dataQualityScore': 1,
        'methodology': 'Option 1a - Verified GHG Emissions (Facilitated - Unlisted)',
        'calculationSteps': [
            {
                'step': 'Total Equity + Debt Calculation',
                'value': total_equity_plus_debt,
                'formula': f'Total Equity + Total Debt = {total_equity_plus_debt:.2f}'
            },
            {
                'step': 'Attribution Factor',
                'value': attribution_factor,
                'formula': f'{facilitated_amount} / {total_equity_plus_debt} = {attribution_factor:.6f}'
            },
            {
                'step': 'Facilitated Emissions',
                'value': facilitated_emissions,
                'formula': f'({facilitated_amount} / {total_equity_plus_debt}) × {weighting_factor} × {verified_emissions} = {facilitated_emissions:.2f} tCO2e'
            }
        ]
    }

def _calculate_1b_facilitated_unverified_listed(inputs: dict, company_type: str) -> dict:
    """Option 1b - Unverified GHG Emissions (Facilitated - Listed)"""
    facilitated_amount = inputs.get('facilitated_amount', 0)
    weighting_factor = inputs.get('weighting_factor', 0)
    unverified_emissions = inputs.get('unverified_emissions', 0)
    evic = calculate_evic(inputs)
    attribution_factor = calculate_attribution_factor_listed(facilitated_amount, evic)
    facilitated_emissions = (facilitated_amount / evic) * weighting_factor * unverified_emissions
    
    return {
        'attributionFactor': attribution_factor,
        'emissionFactor': unverified_emissions,
        'financedEmissions': facilitated_emissions,
        'dataQualityScore': 2,
        'methodology': 'Option 1b - Unverified GHG Emissions (Facilitated - Listed)',
        'calculationSteps': [
            {
                'step': 'EVIC Calculation',
                'value': evic,
                'formula': f'Share Price × Outstanding Shares + Total Debt + Minority Interest + Preferred Stock = {evic:.2f}'
            },
            {
                'step': 'Attribution Factor',
                'value': attribution_factor,
                'formula': f'{facilitated_amount} / {evic} = {attribution_factor:.6f}'
            },
            {
                'step': 'Facilitated Emissions',
                'value': facilitated_emissions,
                'formula': f'({facilitated_amount} / {evic}) × {weighting_factor} × {unverified_emissions} = {facilitated_emissions:.2f} tCO2e'
            }
        ]
    }

def _calculate_1b_facilitated_unverified_unlisted(inputs: dict, company_type: str) -> dict:
    """Option 1b - Unverified GHG Emissions (Facilitated - Unlisted)"""
    facilitated_amount = inputs.get('facilitated_amount', 0)
    weighting_factor = inputs.get('weighting_factor', 0)
    unverified_emissions = inputs.get('unverified_emissions', 0)
    total_equity_plus_debt = calculate_total_equity_plus_debt(inputs)
    attribution_factor = calculate_attribution_factor_unlisted(facilitated_amount, total_equity_plus_debt)
    facilitated_emissions = (facilitated_amount / total_equity_plus_debt) * weighting_factor * unverified_emissions
    
    return {
        'attributionFactor': attribution_factor,
        'emissionFactor': unverified_emissions,
        'financedEmissions': facilitated_emissions,
        'dataQualityScore': 2,
        'methodology': 'Option 1b - Unverified GHG Emissions (Facilitated - Unlisted)',
        'calculationSteps': [
            {
                'step': 'Total Equity + Debt Calculation',
                'value': total_equity_plus_debt,
                'formula': f'Total Equity + Total Debt = {total_equity_plus_debt:.2f}'
            },
            {
                'step': 'Attribution Factor',
                'value': attribution_factor,
                'formula': f'{facilitated_amount} / {total_equity_plus_debt} = {attribution_factor:.6f}'
            },
            {
                'step': 'Facilitated Emissions',
                'value': facilitated_emissions,
                'formula': f'({facilitated_amount} / {total_equity_plus_debt}) × {weighting_factor} × {unverified_emissions} = {facilitated_emissions:.2f} tCO2e'
            }
        ]
    }

def _calculate_2a_facilitated_energy_listed(inputs: dict, company_type: str) -> dict:
    """Option 2a - Energy Consumption Data (Facilitated - Listed)"""
    facilitated_amount = inputs.get('facilitated_amount', 0)
    weighting_factor = inputs.get('weighting_factor', 0)
    energy_consumption = inputs.get('energy_consumption', 0)
    emission_factor = inputs.get('emission_factor', 0)
    process_emissions = inputs.get('process_emissions', 0) or 0
    evic = calculate_evic(inputs)
    attribution_factor = calculate_attribution_factor_listed(facilitated_amount, evic)
    energy_emissions = energy_consumption * emission_factor + process_emissions
    facilitated_emissions = (facilitated_amount / evic) * weighting_factor * energy_emissions
    
    return {
        'attributionFactor': attribution_factor,
        'emissionFactor': energy_emissions,
        'financedEmissions': facilitated_emissions,
        'dataQualityScore': 2,
        'methodology': 'Option 2a - Energy Consumption Data (Facilitated - Listed)',
        'calculationSteps': [
            {
                'step': 'EVIC Calculation',
                'value': evic,
                'formula': f'Share Price × Outstanding Shares + Total Debt + Minority Interest + Preferred Stock = {evic:.2f}'
            },
            {
                'step': 'Energy Emissions',
                'value': energy_emissions,
                'formula': f'{energy_consumption} × {emission_factor} = {energy_emissions:.2f} tCO2e'
            },
            {
                'step': 'Attribution Factor',
                'value': attribution_factor,
                'formula': f'{facilitated_amount} / {evic} = {attribution_factor:.6f}'
            },
            {
                'step': 'Facilitated Emissions',
                'value': facilitated_emissions,
                'formula': f'({facilitated_amount} / {evic}) × {weighting_factor} × {energy_emissions} = {facilitated_emissions:.2f} tCO2e'
            }
        ]
    }

def _calculate_2a_facilitated_energy_unlisted(inputs: dict, company_type: str) -> dict:
    """Option 2a - Energy Consumption Data (Facilitated - Unlisted)"""
    facilitated_amount = inputs.get('facilitated_amount', 0)
    weighting_factor = inputs.get('weighting_factor', 0)
    energy_consumption = inputs.get('energy_consumption', 0)
    emission_factor = inputs.get('emission_factor', 0)
    process_emissions = inputs.get('process_emissions', 0) or 0
    total_equity_plus_debt = calculate_total_equity_plus_debt(inputs)
    attribution_factor = calculate_attribution_factor_unlisted(facilitated_amount, total_equity_plus_debt)
    energy_emissions = energy_consumption * emission_factor + process_emissions
    facilitated_emissions = (facilitated_amount / total_equity_plus_debt) * weighting_factor * energy_emissions
    
    return {
        'attributionFactor': attribution_factor,
        'emissionFactor': energy_emissions,
        'financedEmissions': facilitated_emissions,
        'dataQualityScore': 2,
        'methodology': 'Option 2a - Energy Consumption Data (Facilitated - Unlisted)',
        'calculationSteps': [
            {
                'step': 'Total Equity + Debt Calculation',
                'value': total_equity_plus_debt,
                'formula': f'Total Equity + Total Debt = {total_equity_plus_debt:.2f}'
            },
            {
                'step': 'Energy Emissions',
                'value': energy_emissions,
                'formula': f'{energy_consumption} × {emission_factor} = {energy_emissions:.2f} tCO2e'
            },
            {
                'step': 'Attribution Factor',
                'value': attribution_factor,
                'formula': f'{facilitated_amount} / {total_equity_plus_debt} = {attribution_factor:.6f}'
            },
            {
                'step': 'Facilitated Emissions',
                'value': facilitated_emissions,
                'formula': f'({facilitated_amount} / {total_equity_plus_debt}) × {weighting_factor} × {energy_emissions} = {facilitated_emissions:.2f} tCO2e'
            }
        ]
    }

def _calculate_2b_facilitated_production_listed(inputs: dict, company_type: str) -> dict:
    """Option 2b - Production Data (Facilitated - Listed)"""
    facilitated_amount = inputs.get('facilitated_amount', 0)
    weighting_factor = inputs.get('weighting_factor', 0)
    production = inputs.get('production', 0)
    production_emission_factor = inputs.get('production_emission_factor', 0) or inputs.get('emission_factor', 0)
    evic = calculate_evic(inputs)
    attribution_factor = calculate_attribution_factor_listed(facilitated_amount, evic)
    production_emissions = production * production_emission_factor
    facilitated_emissions = (facilitated_amount / evic) * weighting_factor * production_emissions
    
    return {
        'attributionFactor': attribution_factor,
        'emissionFactor': production_emissions,
        'financedEmissions': facilitated_emissions,
        'dataQualityScore': 3,
        'methodology': 'Option 2b - Production Data (Facilitated - Listed)',
        'calculationSteps': [
            {
                'step': 'EVIC Calculation',
                'value': evic,
                'formula': f'Share Price × Outstanding Shares + Total Debt + Minority Interest + Preferred Stock = {evic:.2f}'
            },
            {
                'step': 'Production Emissions',
                'value': production_emissions,
                'formula': f'{production} × {production_emission_factor} = {production_emissions:.2f} tCO2e'
            },
            {
                'step': 'Attribution Factor',
                'value': attribution_factor,
                'formula': f'{facilitated_amount} / {evic} = {attribution_factor:.6f}'
            },
            {
                'step': 'Facilitated Emissions',
                'value': facilitated_emissions,
                'formula': f'({facilitated_amount} / {evic}) × {weighting_factor} × {production_emissions} = {facilitated_emissions:.2f} tCO2e'
            }
        ]
    }

def _calculate_2b_facilitated_production_unlisted(inputs: dict, company_type: str) -> dict:
    """Option 2b - Production Data (Facilitated - Unlisted)"""
    facilitated_amount = inputs.get('facilitated_amount', 0)
    weighting_factor = inputs.get('weighting_factor', 0)
    production = inputs.get('production', 0)
    production_emission_factor = inputs.get('production_emission_factor', 0) or inputs.get('emission_factor', 0)
    total_equity_plus_debt = calculate_total_equity_plus_debt(inputs)
    attribution_factor = calculate_attribution_factor_unlisted(facilitated_amount, total_equity_plus_debt)
    production_emissions = production * production_emission_factor
    facilitated_emissions = (facilitated_amount / total_equity_plus_debt) * weighting_factor * production_emissions
    
    return {
        'attributionFactor': attribution_factor,
        'emissionFactor': production_emissions,
        'financedEmissions': facilitated_emissions,
        'dataQualityScore': 3,
        'methodology': 'Option 2b - Production Data (Facilitated - Unlisted)',
        'calculationSteps': [
            {
                'step': 'Total Equity + Debt Calculation',
                'value': total_equity_plus_debt,
                'formula': f'Total Equity + Total Debt = {total_equity_plus_debt:.2f}'
            },
            {
                'step': 'Production Emissions',
                'value': production_emissions,
                'formula': f'{production} × {production_emission_factor} = {production_emissions:.2f} tCO2e'
            },
            {
                'step': 'Attribution Factor',
                'value': attribution_factor,
                'formula': f'{facilitated_amount} / {total_equity_plus_debt} = {attribution_factor:.6f}'
            },
            {
                'step': 'Facilitated Emissions',
                'value': facilitated_emissions,
                'formula': f'({facilitated_amount} / {total_equity_plus_debt}) × {weighting_factor} × {production_emissions} = {facilitated_emissions:.2f} tCO2e'
            }
        ]
    }

# ============================================================================
# FACILITATED EMISSION FORMULA CONFIGURATIONS
# ============================================================================

def create_facilitated_emission_formulas():
    """Create all facilitated emission formula configurations"""
    
    # Common inputs for facilitated emissions
    facilitated_amount_input = FormulaInput(
        name='facilitated_amount',
        label='Facilitated Amount',
        type=FormulaInputType.NUMBER,
        required=True,
        unit='PKR',
        description='Total amount of financial services provided to the client'
    )
    
    weighting_factor_input = FormulaInput(
        name='weighting_factor',
        label='Weighting Factor',
        type=FormulaInputType.NUMBER,
        required=True,
        unit='ratio',
        description='Factor representing the proportion of services provided (0-1)',
        validation={'min': 0, 'max': 1}
    )
    
    return [
        # OPTION 1A - VERIFIED GHG EMISSIONS (FACILITATED - LISTED)
        FormulaConfig(
            id='1a-facilitated-verified-listed',
            name='Option 1a - Verified GHG Emissions (Facilitated - Listed)',
            description='Verified GHG emissions data from the listed client company in accordance with the GHG Protocol',
            category=FormulaCategory.FACILITATED_EMISSION,
            option_code='1a',
            data_quality_score=1,
            inputs=[
                facilitated_amount_input,
                FormulaInput(
                    name='total_assets',
                    label='Total Assets',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='PKR',
                    description='Total assets value for attribution factor calculation'
                ),
                FormulaInput(
                    name='evic',
                    label='EVIC (Enterprise Value Including Cash)',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='PKR',
                    description='EVIC for listed companies'
                ),
                weighting_factor_input,
                FormulaInput(
                    name='verified_emissions',
                    label='Verified GHG Emissions',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='tCO2e',
                    description='Total carbon emissions from the client company (verified by third party)'
                )
            ],
            applicable_scopes=[ScopeType.SCOPE1, ScopeType.SCOPE2, ScopeType.SCOPE3],
            calculate=_calculate_1a_facilitated_verified_listed
        ),
        
        # OPTION 1A - VERIFIED GHG EMISSIONS (FACILITATED - UNLISTED)
        FormulaConfig(
            id='1a-facilitated-verified-unlisted',
            name='Option 1a - Verified GHG Emissions (Facilitated - Unlisted)',
            description='Verified GHG emissions data from the unlisted client company in accordance with the GHG Protocol',
            category=FormulaCategory.FACILITATED_EMISSION,
            option_code='1a',
            data_quality_score=1,
            inputs=[
                facilitated_amount_input,
                FormulaInput(
                    name='total_assets',
                    label='Total Assets',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='PKR',
                    description='Total assets value for attribution factor calculation'
                ),
                FormulaInput(
                    name='total_equity_plus_debt',
                    label='Total Equity + Debt',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='PKR',
                    description='Total equity plus debt for unlisted companies'
                ),
                weighting_factor_input,
                FormulaInput(
                    name='verified_emissions',
                    label='Verified GHG Emissions',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='tCO2e',
                    description='Total carbon emissions from the client company (verified by third party)'
                )
            ],
            applicable_scopes=[ScopeType.SCOPE1, ScopeType.SCOPE2, ScopeType.SCOPE3],
            calculate=_calculate_1a_facilitated_verified_unlisted
        ),
        
        # OPTION 1B - UNVERIFIED GHG EMISSIONS (FACILITATED - LISTED)
        FormulaConfig(
            id='1b-facilitated-unverified-listed',
            name='Option 1b - Unverified GHG Emissions (Facilitated - Listed)',
            description='Unverified GHG emissions data from the listed client company',
            category=FormulaCategory.FACILITATED_EMISSION,
            option_code='1b',
            data_quality_score=2,
            inputs=[
                facilitated_amount_input,
                FormulaInput(
                    name='total_assets',
                    label='Total Assets',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='PKR',
                    description='Total assets value for attribution factor calculation'
                ),
                FormulaInput(
                    name='evic',
                    label='EVIC (Enterprise Value Including Cash)',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='PKR',
                    description='EVIC for listed companies'
                ),
                weighting_factor_input,
                FormulaInput(
                    name='unverified_emissions',
                    label='Unverified GHG Emissions',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='tCO2e',
                    description='Total carbon emissions from the client company (unverified)'
                )
            ],
            applicable_scopes=[ScopeType.SCOPE1, ScopeType.SCOPE2, ScopeType.SCOPE3],
            calculate=_calculate_1b_facilitated_unverified_listed
        ),
        
        # OPTION 1B - UNVERIFIED GHG EMISSIONS (FACILITATED - UNLISTED)
        FormulaConfig(
            id='1b-facilitated-unverified-unlisted',
            name='Option 1b - Unverified GHG Emissions (Facilitated - Unlisted)',
            description='Unverified GHG emissions data from the unlisted client company',
            category=FormulaCategory.FACILITATED_EMISSION,
            option_code='1b',
            data_quality_score=2,
            inputs=[
                facilitated_amount_input,
                FormulaInput(
                    name='total_assets',
                    label='Total Assets',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='PKR',
                    description='Total assets value for attribution factor calculation'
                ),
                FormulaInput(
                    name='total_equity_plus_debt',
                    label='Total Equity + Debt',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='PKR',
                    description='Total equity plus debt for unlisted companies'
                ),
                weighting_factor_input,
                FormulaInput(
                    name='unverified_emissions',
                    label='Unverified GHG Emissions',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='tCO2e',
                    description='Total carbon emissions from the client company (unverified)'
                )
            ],
            applicable_scopes=[ScopeType.SCOPE1, ScopeType.SCOPE2, ScopeType.SCOPE3],
            calculate=_calculate_1b_facilitated_unverified_unlisted
        ),
        
        # OPTION 2A - ENERGY CONSUMPTION DATA (FACILITATED - LISTED)
        FormulaConfig(
            id='2a-facilitated-energy-listed',
            name='Option 2a - Energy Consumption Data (Facilitated - Listed)',
            description='Energy consumption data with energy-specific emission factors for facilitated emissions from listed companies',
            category=FormulaCategory.FACILITATED_EMISSION,
            option_code='2a',
            data_quality_score=2,
            inputs=[
                facilitated_amount_input,
                FormulaInput(
                    name='total_assets',
                    label='Total Assets',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='PKR',
                    description='Total assets value for attribution factor calculation'
                ),
                FormulaInput(
                    name='evic',
                    label='EVIC (Enterprise Value Including Cash)',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='PKR',
                    description='EVIC for listed companies'
                ),
                weighting_factor_input,
                FormulaInput(
                    name='energy_consumption',
                    label='Energy Consumption',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='MWh',
                    description='How much energy the client company used (from utility bills)'
                ),
                FormulaInput(
                    name='emission_factor',
                    label='Emission Factor',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='tCO2e/MWh',
                    description='How much carbon is released per unit of energy used'
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
            applicable_scopes=[ScopeType.SCOPE1, ScopeType.SCOPE2],
            calculate=_calculate_2a_facilitated_energy_listed
        ),
        
        # OPTION 2A - ENERGY CONSUMPTION DATA (FACILITATED - UNLISTED)
        FormulaConfig(
            id='2a-facilitated-energy-unlisted',
            name='Option 2a - Energy Consumption Data (Facilitated - Unlisted)',
            description='Energy consumption data with energy-specific emission factors for facilitated emissions from unlisted companies',
            category=FormulaCategory.FACILITATED_EMISSION,
            option_code='2a',
            data_quality_score=2,
            inputs=[
                facilitated_amount_input,
                FormulaInput(
                    name='total_assets',
                    label='Total Assets',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='PKR',
                    description='Total assets value for attribution factor calculation'
                ),
                FormulaInput(
                    name='total_equity_plus_debt',
                    label='Total Equity + Debt',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='PKR',
                    description='Total equity plus debt for unlisted companies'
                ),
                weighting_factor_input,
                FormulaInput(
                    name='energy_consumption',
                    label='Energy Consumption',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='MWh',
                    description='How much energy the client company used (from utility bills)'
                ),
                FormulaInput(
                    name='emission_factor',
                    label='Emission Factor',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='tCO2e/MWh',
                    description='How much carbon is released per unit of energy used'
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
            applicable_scopes=[ScopeType.SCOPE1, ScopeType.SCOPE2],
            calculate=_calculate_2a_facilitated_energy_unlisted
        ),
        
        # OPTION 2B - PRODUCTION DATA (FACILITATED - LISTED)
        FormulaConfig(
            id='2b-facilitated-production-listed',
            name='Option 2b - Production Data (Facilitated - Listed)',
            description='Production data with production-specific emission factors for facilitated emissions from listed companies',
            category=FormulaCategory.FACILITATED_EMISSION,
            option_code='2b',
            data_quality_score=3,
            inputs=[
                facilitated_amount_input,
                FormulaInput(
                    name='total_assets',
                    label='Total Assets',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='PKR',
                    description='Total assets value for attribution factor calculation'
                ),
                FormulaInput(
                    name='evic',
                    label='EVIC (Enterprise Value Including Cash)',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='PKR',
                    description='EVIC for listed companies'
                ),
                weighting_factor_input,
                FormulaInput(
                    name='production',
                    label='Production',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='tonnes',
                    description='How much the client company produced (e.g., tonnes of rice, steel, etc.)'
                ),
                FormulaInput(
                    name='emission_factor',
                    label='Emission Factor',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='tCO2e/tonne',
                    description='How much carbon is released per unit of production'
                )
            ],
            applicable_scopes=[ScopeType.SCOPE1, ScopeType.SCOPE2, ScopeType.SCOPE3],
            calculate=_calculate_2b_facilitated_production_listed
        ),
        
        # OPTION 2B - PRODUCTION DATA (FACILITATED - UNLISTED)
        FormulaConfig(
            id='2b-facilitated-production-unlisted',
            name='Option 2b - Production Data (Facilitated - Unlisted)',
            description='Production data with production-specific emission factors for facilitated emissions from unlisted companies',
            category=FormulaCategory.FACILITATED_EMISSION,
            option_code='2b',
            data_quality_score=3,
            inputs=[
                facilitated_amount_input,
                FormulaInput(
                    name='total_assets',
                    label='Total Assets',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='PKR',
                    description='Total assets value for attribution factor calculation'
                ),
                FormulaInput(
                    name='total_equity_plus_debt',
                    label='Total Equity + Debt',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='PKR',
                    description='Total equity plus debt for unlisted companies'
                ),
                weighting_factor_input,
                FormulaInput(
                    name='production',
                    label='Production',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='tonnes',
                    description='How much the client company produced (e.g., tonnes of rice, steel, etc.)'
                ),
                FormulaInput(
                    name='emission_factor',
                    label='Emission Factor',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='tCO2e/tonne',
                    description='How much carbon is released per unit of production'
                )
            ],
            applicable_scopes=[ScopeType.SCOPE1, ScopeType.SCOPE2, ScopeType.SCOPE3],
            calculate=_calculate_2b_facilitated_production_unlisted
        ),

        # OPTION 3A - REVENUE-BASED (FACILITATED - LISTED)
        FormulaConfig(
            id='3a-facilitated-revenue-listed',
            name='Option 3a - Revenue-based (Facilitated - Listed)',
            description='Company revenue × sector intensity with EVIC attribution and weighting factor',
            category=FormulaCategory.FACILITATED_EMISSION,
            option_code='3a',
            data_quality_score=4,
            inputs=[
                facilitated_amount_input,
                FormulaInput(
                    name='evic',
                    label='EVIC (Enterprise Value Including Cash)',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='PKR',
                ),
                weighting_factor_input,
                FormulaInput(
                    name='company_revenue',
                    label='Company Revenue',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='PKR',
                ),
                FormulaInput(
                    name='sector_intensity',
                    label='Sector intensity',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='kgCO2e/PKR',
                ),
                FormulaInput(
                    name='sector_intensity_unit',
                    label='Sector intensity unit',
                    type=FormulaInputType.TEXT,
                    required=False,
                ),
            ],
            applicable_scopes=[ScopeType.SCOPE1, ScopeType.SCOPE2, ScopeType.SCOPE3],
        ),

        # OPTION 3A - REVENUE-BASED (FACILITATED - UNLISTED)
        FormulaConfig(
            id='3a-facilitated-revenue-unlisted',
            name='Option 3a - Revenue-based (Facilitated - Unlisted)',
            description='Company revenue × sector intensity with equity+debt attribution and weighting factor',
            category=FormulaCategory.FACILITATED_EMISSION,
            option_code='3a',
            data_quality_score=4,
            inputs=[
                facilitated_amount_input,
                FormulaInput(
                    name='total_equity_plus_debt',
                    label='Total Equity + Debt',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='PKR',
                ),
                weighting_factor_input,
                FormulaInput(
                    name='company_revenue',
                    label='Company Revenue',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='PKR',
                ),
                FormulaInput(
                    name='sector_intensity',
                    label='Sector intensity',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='kgCO2e/PKR',
                ),
                FormulaInput(
                    name='sector_intensity_unit',
                    label='Sector intensity unit',
                    type=FormulaInputType.TEXT,
                    required=False,
                ),
            ],
            applicable_scopes=[ScopeType.SCOPE1, ScopeType.SCOPE2, ScopeType.SCOPE3],
        ),

        # OPTION 3C - ATR (FACILITATED - LISTED)
        FormulaConfig(
            id='3c-facilitated-atr-listed',
            name='Option 3c - Asset Turnover Ratio (Facilitated - Listed)',
            description='Facilitated amount × weighting factor × ATR × sector intensity',
            category=FormulaCategory.FACILITATED_EMISSION,
            option_code='3c',
            data_quality_score=5,
            inputs=[
                facilitated_amount_input,
                weighting_factor_input,
                FormulaInput(
                    name='asset_turnover_ratio',
                    label='Asset Turnover Ratio',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='ratio',
                ),
                FormulaInput(
                    name='sector_intensity',
                    label='Sector intensity',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='kgCO2e/PKR',
                ),
                FormulaInput(
                    name='sector_intensity_unit',
                    label='Sector intensity unit',
                    type=FormulaInputType.TEXT,
                    required=False,
                ),
            ],
            applicable_scopes=[ScopeType.SCOPE1, ScopeType.SCOPE2, ScopeType.SCOPE3],
        ),

        # OPTION 3C - ATR (FACILITATED - UNLISTED)
        FormulaConfig(
            id='3c-facilitated-atr-unlisted',
            name='Option 3c - Asset Turnover Ratio (Facilitated - Unlisted)',
            description='Facilitated amount × weighting factor × ATR × sector intensity',
            category=FormulaCategory.FACILITATED_EMISSION,
            option_code='3c',
            data_quality_score=5,
            inputs=[
                facilitated_amount_input,
                weighting_factor_input,
                FormulaInput(
                    name='asset_turnover_ratio',
                    label='Asset Turnover Ratio',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='ratio',
                ),
                FormulaInput(
                    name='sector_intensity',
                    label='Sector intensity',
                    type=FormulaInputType.NUMBER,
                    required=True,
                    unit='kgCO2e/PKR',
                ),
                FormulaInput(
                    name='sector_intensity_unit',
                    label='Sector intensity unit',
                    type=FormulaInputType.TEXT,
                    required=False,
                ),
            ],
            applicable_scopes=[ScopeType.SCOPE1, ScopeType.SCOPE2, ScopeType.SCOPE3],
        )
    ]

# Export the formulas
FACILITATED_EMISSION_FORMULAS = create_facilitated_emission_formulas()
