"""
Shared Formula Utilities - Migrated from TypeScript
This file contains common input field definitions, helper functions, and calculation utilities
shared across all loan types in the PCAF emission calculation system.

Migrated from: src/pages/finance_facilitated/config/sharedFormulaUtils.ts
No formulas or working logic has been changed - only converted from TypeScript to Python.
"""

from typing import Dict, Any, List
from .finance_models import FormulaInput, CalculationStep


# ============================================================================
# COMMON INPUT FIELD DEFINITIONS (shared across loan types)
# ============================================================================

COMMON_INPUTS: Dict[str, FormulaInput] = {
    'outstanding_amount': FormulaInput(
        name='outstanding_amount',
        label='Outstanding Amount',
        type='number',
        required=True,
        unit='PKR',
        description='Outstanding amount in the company'
    ),
    'total_assets': FormulaInput(
        name='total_assets',
        label='Total Assets Value',
        type='number',
        required=True,
        unit='PKR',
        description='Total assets value for attribution factor calculation'
    ),
    'evic': FormulaInput(
        name='evic',
        label='EVIC (Enterprise Value Including Cash)',
        type='number',
        required=True,
        unit='PKR',
        description='EVIC for listed companies'
    ),
    'total_equity_plus_debt': FormulaInput(
        name='total_equity_plus_debt',
        label='Total Equity + Debt',
        type='number',
        required=True,
        unit='PKR',
        description='Total equity plus debt for business loans and equity investments'
    )
}

# ============================================================================
# COMMON EMISSION UNIT OPTIONS
# ============================================================================

EMISSION_UNIT_OPTIONS = [
    {'value': 'tCO2e', 'label': 'tCO2e (Tonnes CO2e)'},
    {'value': 'MtCO2e', 'label': 'MtCO2e (Million Tonnes CO2e)'},
    {'value': 'ktCO2e', 'label': 'ktCO2e (Thousand Tonnes CO2e)'},
    {'value': 'GtCO2e', 'label': 'GtCO2e (Gigatonnes CO2e)'}
]

# ============================================================================
# HELPER FUNCTIONS (shared across loan types)
# ============================================================================

def calculate_attribution_factor_listed(outstanding_amount: float, evic: float) -> float:
    """
    Attribution factor for Corporate Bonds/Business Loans (Listed) - uses EVIC
    Migrated from: calculateAttributionFactorListed
    """
    return outstanding_amount / evic


def calculate_attribution_factor_unlisted(outstanding_amount: float, total_equity_plus_debt: float) -> float:
    """
    Attribution factor for Corporate Bonds/Business Loans (Unlisted) - uses Total Equity + Debt
    Migrated from: calculateAttributionFactorUnlisted
    """
    return outstanding_amount / total_equity_plus_debt


def calculate_attribution_factor_project(outstanding_amount: float, total_project_equity_plus_debt: float) -> float:
    """
    Attribution factor for Project Finance - uses Total Project Equity + Debt
    Migrated from: calculateAttributionFactorProject
    """
    return outstanding_amount / total_project_equity_plus_debt


def calculate_attribution_factor_commercial_real_estate(outstanding_amount: float, property_value_at_origination: float) -> float:
    """
    Attribution factor for Commercial Real Estate - uses Property Value at Origination
    Migrated from: calculateAttributionFactorCommercialRealEstate
    """
    return outstanding_amount / property_value_at_origination


def calculate_attribution_factor(outstanding_amount: float, total_assets: float) -> float:
    """
    Legacy function - kept for backward compatibility but should not be used
    Migrated from: calculateAttributionFactor
    """
    return outstanding_amount / total_assets


def calculate_evic(inputs: Dict[str, Any]) -> float:
    """
    Calculate EVIC (Enterprise Value Including Cash)
    Migrated from: calculateEVIC
    """
    return (inputs.get('share_price', 0) * inputs.get('outstanding_shares', 0) + 
            inputs.get('total_debt', 0) + 
            inputs.get('minority_interest', 0) + 
            inputs.get('preferred_stock', 0))


def calculate_total_equity_plus_debt(inputs: Dict[str, Any]) -> float:
    """
    Calculate Total Equity + Debt
    Migrated from: calculateTotalEquityPlusDebt
    """
    return inputs.get('total_equity', 0) + inputs.get('total_debt', 0)


def calculate_financed_emissions(outstanding_amount: float, denominator: float, emission_data: float) -> float:
    """
    Calculate Financed Emissions
    Migrated from: calculateFinancedEmissions
    """
    return (outstanding_amount / denominator) * emission_data


def create_common_calculation_steps(
    outstanding_amount: float,
    total_assets: float,
    denominator: float,
    denominator_label: str,
    denominator_formula: str,
    emission_data: float,
    emission_label: str,
    financed_emissions: float
) -> List[CalculationStep]:
    """
    Create common calculation steps for display
    Migrated from: createCommonCalculationSteps
    """
    attribution_factor = calculate_attribution_factor(outstanding_amount, total_assets)

    return [
        CalculationStep(
            step='Attribution Factor',
            value=attribution_factor,
            formula=f"{outstanding_amount} / {total_assets} = {attribution_factor:.6f}"
        ),
        CalculationStep(
            step=denominator_label,
            value=denominator,
            formula=denominator_formula
        ),
        CalculationStep(
            step='Financed Emissions',
            value=financed_emissions,
            formula=f"({outstanding_amount} / {denominator:.2f}) × {emission_data} = {financed_emissions:.2f}"
        )
    ]


# ============================================================================
# ADDITIONAL HELPER FUNCTIONS FOR SPECIFIC FORMULA TYPES
# ============================================================================

def calculate_listed_company_attribution_factor(inputs: Dict[str, Any]) -> float:
    """
    Calculate attribution factor for listed companies using EVIC
    """
    outstanding_amount = inputs.get('outstanding_amount', 0)
    evic = inputs.get('evic', 0)
    
    if evic == 0:
        raise ValueError("EVIC cannot be zero for listed companies")
    
    return calculate_attribution_factor_listed(outstanding_amount, evic)


def calculate_unlisted_company_attribution_factor(inputs: Dict[str, Any]) -> float:
    """
    Calculate attribution factor for unlisted companies using Total Equity + Debt
    """
    outstanding_amount = inputs.get('outstanding_amount', 0)
    total_equity_plus_debt = inputs.get('total_equity_plus_debt', 0)
    
    if total_equity_plus_debt == 0:
        raise ValueError("Total Equity + Debt cannot be zero for unlisted companies")
    
    return calculate_attribution_factor_unlisted(outstanding_amount, total_equity_plus_debt)


def calculate_facilitated_emissions(
    facilitated_amount: float,
    company_value: float,
    weighting_factor: float,
    emission_data: float
) -> float:
    """
    Calculate facilitated emissions
    Formula: (Facilitated Amount / Company Value) × Weighting Factor × Emission Data
    """
    attribution_factor = facilitated_amount / company_value
    return attribution_factor * weighting_factor * emission_data


def validate_financial_inputs(inputs: Dict[str, Any], company_type: str) -> List[str]:
    """
    Validate financial inputs based on company type
    Returns list of validation errors
    """
    errors = []
    
    # Check outstanding amount
    outstanding_amount = inputs.get('outstanding_amount', 0)
    if outstanding_amount <= 0:
        errors.append("Outstanding amount must be greater than zero")
    
    if company_type == 'listed':
        # Check EVIC for listed companies
        evic = inputs.get('evic', 0)
        if evic <= 0:
            errors.append("EVIC must be greater than zero for listed companies")
        
        # Check if outstanding amount exceeds EVIC (warning, not error)
        if outstanding_amount > evic:
            # This is a warning, not an error
            pass
    
    elif company_type == 'unlisted':
        # Check Total Equity + Debt for unlisted companies
        total_equity_plus_debt = inputs.get('total_equity_plus_debt', 0)
        if total_equity_plus_debt <= 0:
            errors.append("Total Equity + Debt must be greater than zero for unlisted companies")
    
    return errors


def get_denominator_for_company_type(inputs: Dict[str, Any], company_type: str) -> float:
    """
    Get the appropriate denominator based on company type and available inputs
    """
    # Try different denominator types in order of preference
    denominator_candidates = []
    
    if company_type == 'listed':
        # For listed companies, try EVIC first
        denominator_candidates = ['evic', 'total_equity_plus_debt', 'total_assets']
    else:
        # For unlisted companies, try total_equity_plus_debt first
        denominator_candidates = ['total_equity_plus_debt', 'evic', 'total_assets']
    
    # Also check for formula-specific denominators
    formula_specific_denominators = [
        'property_value_at_origination',  # Commercial real estate, mortgage
        'total_value_at_origination',     # Motor vehicle loans
        'total_project_equity_plus_debt', # Project finance
        'ppp_adjusted_gdp',               # Sovereign debt
        'pp_adjusted_gdp',                # Sovereign debt (SPA alias)
    ]
    
    # Add formula-specific denominators to the list
    denominator_candidates.extend(formula_specific_denominators)
    
    # Find the first available denominator
    for denominator_key in denominator_candidates:
        value = inputs.get(denominator_key, 0)
        if value > 0:
            return value
    
    # If no denominator found, raise an error
    available_keys = [k for k, v in inputs.items() if v > 0]
    raise ValueError(f"No valid denominator found. Available inputs: {available_keys}")


def format_calculation_step(step_name: str, value: float, formula: str) -> CalculationStep:
    """
    Format a calculation step for display
    """
    return CalculationStep(
        step=step_name,
        value=value,
        formula=formula
    )


def create_emission_calculation_steps(
    outstanding_amount: float,
    denominator: float,
    emission_data: float,
    emission_label: str,
    company_type: str
) -> List[CalculationStep]:
    """
    Create emission calculation steps
    """
    attribution_factor = outstanding_amount / denominator
    financed_emissions = attribution_factor * emission_data
    
    denominator_label = "EVIC" if company_type == 'listed' else "Total Equity + Debt"
    
    return [
        format_calculation_step(
            'Attribution Factor',
            attribution_factor,
            f"{outstanding_amount} / {denominator} = {attribution_factor:.6f}"
        ),
        format_calculation_step(
            emission_label,
            emission_data,
            f"Direct emission data"
        ),
        format_calculation_step(
            'Financed Emissions',
            financed_emissions,
            f"({outstanding_amount} / {denominator:.2f}) × {emission_data} = {financed_emissions:.2f}"
        )
    ]


def create_activity_calculation_steps(
    outstanding_amount: float,
    denominator: float,
    activity_data: float,
    activity_label: str,
    emission_factor: float,
    emission_factor_label: str,
    company_type: str
) -> List[CalculationStep]:
    """
    Create activity-based calculation steps
    """
    attribution_factor = outstanding_amount / denominator
    calculated_emissions = activity_data * emission_factor
    financed_emissions = attribution_factor * calculated_emissions
    
    denominator_label = "EVIC" if company_type == 'listed' else "Total Equity + Debt"
    
    return [
        format_calculation_step(
            'Attribution Factor',
            attribution_factor,
            f"{outstanding_amount} / {denominator} = {attribution_factor:.6f}"
        ),
        format_calculation_step(
            activity_label,
            activity_data,
            f"Activity data"
        ),
        format_calculation_step(
            emission_factor_label,
            emission_factor,
            f"Emission factor"
        ),
        format_calculation_step(
            'Calculated Emissions',
            calculated_emissions,
            f"{activity_data} × {emission_factor} = {calculated_emissions:.2f}"
        ),
        format_calculation_step(
            'Financed Emissions',
            financed_emissions,
            f"({outstanding_amount} / {denominator:.2f}) × {calculated_emissions:.2f} = {financed_emissions:.2f}"
        )
    ]
