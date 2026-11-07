"""
Reuse the existing sovereign PCAF engine inside a UoP underlying asset.

PCAF Part A 2025 §5.9 (and §5.7 Table 5.7-1 look-through): Outstanding /
PPP-adjusted GDP × country emissions. Does not invent GDP or emissions.
Does not treat national PPP-GDP as a regional (sub-sovereign) denominator.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .ppp_gdp import apply_ppp_resolution, load_ppp_gdp
from .sovereign_pcaf import run_sovereign_calculation
from .uop_sub_sovereign import calculate_uop_sub_sovereign_asset

SOVEREIGN_OPTIONS = {
    "1a": (1, "Verified country emissions (UNFCCC)"),
    "1b": (2, "Unverified country emissions"),
    "2a": (3, "Country energy × emission factor"),
    "3a": (4, "Sector revenue × sector intensity"),
    "3b": (5, "Proxy-country intensity"),
}

SUB_SOVEREIGN_UNSUPPORTED = (
    "Sub-sovereign territorial methods (PCAF §5.10) need employee-provided "
    "regional PPP-adjusted GDP and matching territorial emissions for the "
    "same region and reporting year. National PPP-adjusted GDP from "
    "ref.ppp_adjusted_gdp must not be used as a regional denominator, "
    "and national emissions must not silently substitute for regional "
    "emissions."
)


def _fallback_confirmed(estimation: Dict[str, Any]) -> bool:
    flag = _pick(
        estimation,
        "allowPppGdpFallback",
        "allow_ppp_gdp_fallback",
        "pppGdpFallbackConfirmed",
        "ppp_gdp_fallback_confirmed",
    )
    if isinstance(flag, str):
        return flag.strip().lower() in ("1", "true", "yes", "confirmed")
    return bool(flag)


def _assert_no_silent_ppp_fallback(
    inputs: Dict[str, Any],
    estimation: Dict[str, Any],
    *,
    name: str,
) -> Optional[str]:
    """
    Never silently use 2024 GDP when 2025 was preferred.
    Employee must confirm the year mismatch with source evidence.
    """
    used_fallback = bool(inputs.get("ppp_gdp_used_fallback"))
    year = inputs.get("ppp_gdp_year")
    try:
        year_int = int(year) if year is not None and str(year).strip() else None
    except (TypeError, ValueError):
        year_int = None
    preferred = _pick(estimation, "preferredPppGdpYear", "preferred_ppp_gdp_year", "reportingYear", "reporting_year")
    try:
        preferred_int = int(preferred) if preferred is not None and str(preferred).strip() else 2025
    except (TypeError, ValueError):
        preferred_int = 2025
    if used_fallback or (year_int is not None and preferred_int == 2025 and year_int == 2024):
        if not _fallback_confirmed(estimation):
            return (
                f"{name}: PPP-adjusted GDP year {year_int or year} does not match the "
                f"preferred year {preferred_int}. Confirm the permissible fallback "
                "with source evidence; 2024 data is never silently used for 2025."
            )
        inputs["ppp_gdp_fallback_confirmed"] = True
        inputs["ppp_gdp_fallback_note"] = (
            f"Employee-confirmed fallback from preferred {preferred_int} to catalog year {year_int}."
        )
    return None


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _num(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _pick(payload: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return default


def is_sub_sovereign_request(asset: Dict[str, Any], estimation: Dict[str, Any]) -> bool:
    level = _text(
        _pick(
            asset,
            "sovereignLevel",
            "sovereign_level",
            "territoryLevel",
            "territory_level",
        )
        or _pick(estimation, "sovereignLevel", "sovereign_level", "territoryLevel", "territory_level")
    ).lower()
    if level in ("sub-sovereign", "sub_sovereign", "regional", "municipal", "local"):
        return True
    if _pick(asset, "regionName", "region_name", "subSovereignName", "sub_sovereign_name") or _pick(
        estimation, "regionName", "region_name", "subSovereignName", "sub_sovereign_name"
    ):
        return True
    if _pick(estimation, "regionalGdp", "regional_gdp", "regionalPppGdp", "regional_ppp_gdp"):
        return True
    return False


def refuse_national_gdp_as_regional(
    *,
    regional_requested: bool,
    used_national_ppp: bool,
) -> Optional[str]:
    if regional_requested and used_national_ppp:
        return (
            "National PPP-adjusted GDP cannot be used as the regional "
            "denominator for sub-sovereign debt (PCAF §5.10)."
        )
    return None


def build_sovereign_inputs(
    asset: Dict[str, Any],
    estimation: Dict[str, Any],
    *,
    allocated: float,
    db: Any = None,
) -> Dict[str, Any]:
    country = _text(
        _pick(
            estimation,
            "sovereignCountryName",
            "sovereign_country_name",
            "factorGeography",
            "factor_geography",
        )
        or _pick(asset, "sovereignCountryName", "sovereign_country_name", "countryName", "country_name")
    )
    inputs: Dict[str, Any] = {
        "outstanding_amount": allocated,
        "sovereign_country_name": country,
        "resolve_ppp_gdp": True,
    }
    # Allow an already-resolved catalog value only when provenance is present.
    pp = _num(_pick(estimation, "ppAdjustedGdp", "pp_adjusted_gdp", "pppAdjustedGdp", "ppp_adjusted_gdp"))
    year = _pick(estimation, "pppGdpYear", "ppp_gdp_year")
    if pp is not None and pp > 0 and country and year:
        inputs["pp_adjusted_gdp"] = pp
        inputs["ppp_adjusted_gdp"] = pp
        inputs["ppp_gdp_year"] = year
        inputs["ppp_gdp_source"] = _text(
            _pick(estimation, "pppGdpSource", "ppp_gdp_source"),
            default="employee-confirmed catalog value",
        )
        inputs["resolve_ppp_gdp"] = False
        try:
            year_int = int(year)
        except (TypeError, ValueError):
            year_int = None
        if year_int == 2024 or _pick(estimation, "pppGdpUsedFallback", "ppp_gdp_used_fallback"):
            inputs["ppp_gdp_used_fallback"] = True

    inputs["verified_country_emissions"] = _num(
        _pick(
            estimation,
            "verifiedCountryEmissions",
            "verified_country_emissions",
            "verifiedEmissions",
            "verified_emissions",
        )
        or _pick(asset, "scope1Emissions", "scope1_emissions")
    )
    inputs["unverified_country_emissions"] = _num(
        _pick(
            estimation,
            "unverifiedCountryEmissions",
            "unverified_country_emissions",
            "unverifiedEmissions",
            "unverified_emissions",
        )
    )
    inputs["energy_consumption"] = _num(
        _pick(estimation, "energyConsumption", "energy_consumption", "physicalActivityAmount")
    )
    inputs["emission_factor"] = _num(
        _pick(estimation, "emissionFactor", "emission_factor", "libraryFactorValue", "library_factor_value")
    )
    inputs["process_emissions"] = _num(_pick(estimation, "processEmissions", "process_emissions"))
    inputs["sector_revenue"] = _num(_pick(estimation, "companyRevenue", "company_revenue", "sectorRevenue"))
    inputs["sector_intensity"] = _num(
        _pick(estimation, "sectorIntensity", "sector_intensity", "emissionFactor", "emission_factor")
    )
    inputs["sector_intensity_unit"] = _text(
        _pick(estimation, "sectorIntensityUnit", "sector_intensity_unit", "factorUnit", "factor_unit"),
        default="tCO2e/currency",
    )
    inputs["proxy_country_emissions"] = _num(
        _pick(estimation, "proxyCountryEmissions", "proxy_country_emissions")
    )
    inputs["proxy_sovereign_country_name"] = _text(
        _pick(estimation, "proxySovereignCountryName", "proxy_sovereign_country_name")
    )
    inputs["proxy_pp_adjusted_gdp"] = _num(
        _pick(estimation, "proxyPpAdjustedGdp", "proxy_pp_adjusted_gdp")
    )

    if db is not None and inputs.get("resolve_ppp_gdp"):
        inputs = apply_ppp_resolution(db, inputs, require_country=True)
        if country and inputs.get("pp_adjusted_gdp") is not None:
            inputs["ppp_gdp_source"] = "ref.ppp_adjusted_gdp"
    elif db is not None and country and inputs.get("pp_adjusted_gdp") is None:
        loaded = load_ppp_gdp(db, country)
        if not loaded:
            raise ValueError(f"No PPP-adjusted GDP for {country}")
        inputs.update(
            {
                "pp_adjusted_gdp": loaded["pp_adjusted_gdp"],
                "ppp_adjusted_gdp": loaded["pp_adjusted_gdp"],
                "ppp_gdp_year": loaded["ppp_gdp_year"],
                "ppp_gdp_used_fallback": loaded["ppp_gdp_used_fallback"],
                "ppp_gdp_source": "ref.ppp_adjusted_gdp",
            }
        )
    return inputs


def calculate_uop_sovereign_asset(
    result: Dict[str, Any],
    *,
    asset: Dict[str, Any],
    estimation: Dict[str, Any],
    allocated: float,
    name: str,
    db: Any = None,
) -> Dict[str, Any]:
    if is_sub_sovereign_request(asset, estimation):
        # Territory-based path lives in uop_sub_sovereign (user-provided regional data).
        return calculate_uop_sub_sovereign_asset(
            result,
            asset=asset,
            estimation=estimation,
            allocated=allocated,
            name=name,
        )

    option = _text(_pick(estimation, "pcafOption", "pcaf_option", "optionCode", "option_code"))
    if option not in SOVEREIGN_OPTIONS:
        result.update(
            {
                "status": "incomplete",
                "code": "missing_sovereign_option",
                "message": (
                    f"{name}: choose a sovereign PCAF option (1a, 1b, 2a, 3a, or 3b). "
                    "Standalone sovereign debt formulas are reused; no alternate formula is invented."
                ),
                "structure_financed_emissions": None,
            }
        )
        return result

    try:
        inputs = build_sovereign_inputs(asset, estimation, allocated=allocated, db=db)
    except ValueError as exc:
        result.update(
            {
                "status": "incomplete",
                "code": "missing_ppp_gdp",
                "message": f"{name}: {exc}",
                "structure_financed_emissions": None,
            }
        )
        return result

    if not inputs.get("sovereign_country_name"):
        result.update(
            {
                "status": "incomplete",
                "code": "missing_sovereign_country",
                "message": f"{name}: select the sovereign country so PPP-adjusted GDP can be loaded from the catalog.",
                "structure_financed_emissions": None,
            }
        )
        return result
    if not inputs.get("pp_adjusted_gdp"):
        result.update(
            {
                "status": "incomplete",
                "code": "missing_ppp_gdp",
                "message": (
                    f"{name}: no PPP-adjusted GDP is available for "
                    f"{inputs.get('sovereign_country_name')}. A sovereign calculator "
                    "without a catalog row is not enough."
                ),
                "structure_financed_emissions": None,
            }
        )
        return result

    fallback_error = _assert_no_silent_ppp_fallback(inputs, estimation, name=name)
    if fallback_error:
        result.update(
            {
                "status": "incomplete",
                "code": "ppp_gdp_year_fallback_unconfirmed",
                "message": fallback_error,
                "structure_financed_emissions": None,
                "ppp_gdp_year": inputs.get("ppp_gdp_year"),
                "ppp_gdp_used_fallback": True,
            }
        )
        return result

    score, _label = SOVEREIGN_OPTIONS[option]
    formula_id = f"{option}-sovereign-debt"
    try:
        calc = run_sovereign_calculation(
            formula_id=formula_id,
            option_code=option,
            data_quality_score=score,
            methodology="PCAF Part A 2025 §5.9 (reused inside UoP §5.7 look-through)",
            inputs=inputs,
            company_type="sovereign",
        )
    except ValueError as exc:
        result.update(
            {
                "status": "incomplete",
                "code": "sovereign_inputs_invalid",
                "message": f"{name}: {exc}",
                "structure_financed_emissions": None,
            }
        )
        return result

    fe = float(calc["financed_emissions"])
    af = float(calc["attribution_factor"])
    result.update(
        {
            "status": "complete",
            "asset_attribution_factor": af,
            "denominator": float(inputs["pp_adjusted_gdp"]),
            "denominator_kind": "ppp_adjusted_gdp",
            "denominator_label": "PPP-adjusted GDP",
            "structure_scope1_tco2e": fe,
            "structure_scope2_tco2e": None,
            "structure_scope3_tco2e": None,
            "structure_unallocated_tco2e": None,
            "structure_financed_emissions": fe,
            "data_quality_score": float(score),
            "option_code": option,
            "estimated": option not in ("1a", "1b"),
            "reused_formula_id": formula_id,
            "reused_methodology": (
                "PCAF §5.9 Outstanding / PPP-adjusted GDP × country emissions; "
                f"run_sovereign_calculation({formula_id}); GDP source="
                f"{inputs.get('ppp_gdp_source') or 'ref.ppp_adjusted_gdp'} "
                f"year={inputs.get('ppp_gdp_year')}"
                + (
                    f"; fallback confirmed={inputs.get('ppp_gdp_fallback_confirmed')}"
                    if inputs.get("ppp_gdp_fallback_confirmed")
                    else ""
                )
            ),
            "ppp_gdp_year": inputs.get("ppp_gdp_year"),
            "ppp_gdp_source": inputs.get("ppp_gdp_source"),
            "ppp_gdp_used_fallback": bool(inputs.get("ppp_gdp_used_fallback")),
            "ppp_gdp_fallback_confirmed": bool(inputs.get("ppp_gdp_fallback_confirmed")),
            "sovereign_country_name": inputs.get("sovereign_country_name"),
        }
    )
    return result
