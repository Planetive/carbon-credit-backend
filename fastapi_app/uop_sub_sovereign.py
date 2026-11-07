"""
PCAF Part A 2025 §5.10 sub-sovereign debt (territory-based / sovereign-like).

AF = Outstanding / regional PPP-adjusted GDP (capped at 1)
FE = AF × regional territorial emissions

Regional PPP-GDP must be employee-supplied (direct PPP-GDP, or regional
nominal GDP × country PPP adjustment factor per Annex 10.3). National
catalog PPP-GDP and national emissions are never used as if they were
regional values.

Corporate-like sub-sovereign issuers are redirected to business-loan /
unlisted-equity methods (Table 5.10-2) — not calculated here.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from .sovereign_pcaf import run_sovereign_calculation

SUB_SOVEREIGN_OPTIONS = {
    "1a": (1, "Verified regional territorial emissions"),
    "1b": (2, "Unverified regional territorial emissions"),
    "2": (3, "Regional energy × emission factor"),
    "2a": (3, "Regional energy × emission factor"),
    "3": (4, "Regional sector revenue × intensity"),
    "3a": (4, "Regional sector revenue × intensity"),
    "4a": (5, "Proxy emissions one administrative level above"),
    "4b": (5, "Proxy emissions two administrative levels above"),
}


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


def is_corporate_like_sub_sovereign(asset: Dict[str, Any], estimation: Dict[str, Any]) -> bool:
    kind = _text(
        _pick(
            asset,
            "subSovereignIssuerKind",
            "sub_sovereign_issuer_kind",
            "issuerKind",
            "issuer_kind",
        )
        or _pick(estimation, "subSovereignIssuerKind", "sub_sovereign_issuer_kind", "issuerKind", "issuer_kind")
    ).lower()
    return kind in ("corporate-like", "corporate_like", "corporate", "utility", "entity")


def resolve_regional_ppp_gdp(
    estimation: Dict[str, Any],
    asset: Dict[str, Any],
) -> Tuple[Optional[float], Dict[str, Any]]:
    """
    Returns (regional_ppp_gdp, provenance).

    Permitted paths:
    1) Direct regional PPP-adjusted GDP with currency, year, source.
    2) Regional nominal GDP × country PPP adjustment factor (Annex 10.3).

    National catalog GDP alone is refused.
    """
    provenance: Dict[str, Any] = {
        "method": None,
        "currency": None,
        "year": None,
        "source": None,
        "used_national_catalog": False,
    }

    # Refuse silent national catalog substitution.
    if _pick(estimation, "useNationalPppGdp", "use_national_ppp_gdp") or _pick(
        asset, "useNationalPppGdp", "use_national_ppp_gdp"
    ):
        return None, {**provenance, "error": "national_catalog_refused"}

    direct = _num(
        _pick(
            estimation,
            "regionalPppAdjustedGdp",
            "regional_ppp_adjusted_gdp",
            "regionalPpAdjustedGdp",
            "ppAdjustedGdp",
            "pp_adjusted_gdp",
        )
    )
    currency = _text(
        _pick(
            estimation,
            "regionalGdpCurrency",
            "regional_gdp_currency",
            "activityCurrency",
            "activity_currency",
        )
    )
    year = _text(
        _pick(
            estimation,
            "regionalGdpYear",
            "regional_gdp_year",
            "pppGdpYear",
            "ppp_gdp_year",
            "reportingYear",
            "reporting_year",
        )
    )
    source = _text(
        _pick(
            estimation,
            "regionalGdpSource",
            "regional_gdp_source",
            "pppGdpSource",
            "ppp_gdp_source",
        )
    )

    if direct is not None and direct > 0:
        if not currency or not year or not source:
            return None, {
                **provenance,
                "error": "missing_regional_gdp_provenance",
                "message": (
                    "Regional PPP-adjusted GDP requires currency, reporting year, and source evidence."
                ),
            }
        if "national" in source.lower() and "catalog" in source.lower():
            return None, {
                **provenance,
                "error": "national_catalog_refused",
                "message": (
                    "National PPP-adjusted GDP from ref.ppp_adjusted_gdp cannot be used "
                    "as the regional denominator (PCAF §5.10)."
                ),
            }
        provenance.update(
            {
                "method": "direct_regional_ppp_gdp",
                "currency": currency,
                "year": year,
                "source": source,
            }
        )
        return direct, provenance

    nominal = _num(
        _pick(
            estimation,
            "regionalNominalGdp",
            "regional_nominal_gdp",
            "regionalGdp",
            "regional_gdp",
        )
    )
    ppp_factor = _num(
        _pick(
            estimation,
            "countryPppAdjustmentFactor",
            "country_ppp_adjustment_factor",
            "pppAdjustmentFactor",
            "ppp_adjustment_factor",
        )
    )
    # Annex 10.3: factor = country_PPP_GDP / country_nominal_GDP
    if ppp_factor is None:
        country_ppp = _num(
            _pick(estimation, "countryPppAdjustedGdp", "country_ppp_adjusted_gdp")
        )
        country_nominal = _num(
            _pick(estimation, "countryNominalGdp", "country_nominal_gdp")
        )
        if country_ppp is not None and country_nominal is not None and country_nominal > 0:
            ppp_factor = country_ppp / country_nominal

    if nominal is not None and nominal > 0 and ppp_factor is not None and ppp_factor > 0:
        if not currency or not year or not source:
            return None, {
                **provenance,
                "error": "missing_regional_gdp_provenance",
                "message": (
                    "Regional nominal GDP converted with a country PPP factor still "
                    "requires currency, year, and source evidence for the regional GDP."
                ),
            }
        converted = nominal * ppp_factor
        provenance.update(
            {
                "method": "annex_10_3_ppp_factor",
                "currency": currency,
                "year": year,
                "source": source,
                "regional_nominal_gdp": nominal,
                "country_ppp_adjustment_factor": ppp_factor,
            }
        )
        return converted, provenance

    return None, {
        **provenance,
        "error": "missing_regional_ppp_gdp",
        "message": (
            "Enter regional PPP-adjusted GDP (with currency, year, source), or "
            "regional nominal GDP plus the country PPP adjustment factor (Annex 10.3). "
            "National catalog GDP alone is not accepted."
        ),
    }


def build_sub_sovereign_inputs(
    asset: Dict[str, Any],
    estimation: Dict[str, Any],
    *,
    allocated: float,
) -> Dict[str, Any]:
    region = _text(
        _pick(estimation, "regionName", "region_name", "subSovereignName", "sub_sovereign_name")
        or _pick(asset, "regionName", "region_name", "name")
    )
    country = _text(
        _pick(
            estimation,
            "sovereignCountryName",
            "sovereign_country_name",
            "countryName",
            "country_name",
        )
        or _pick(asset, "sovereignCountryName", "sovereign_country_name", "countryName", "country_name")
    )
    reporting_year = _text(
        _pick(estimation, "reportingYear", "reporting_year", "regionalEmissionsYear", "regional_emissions_year")
    )
    regional_ppp, provenance = resolve_regional_ppp_gdp(estimation, asset)
    if provenance.get("error"):
        raise ValueError(provenance.get("message") or provenance["error"])
    if regional_ppp is None or regional_ppp <= 0:
        raise ValueError(provenance.get("message") or "Regional PPP-adjusted GDP is required.")

    inputs: Dict[str, Any] = {
        "outstanding_amount": allocated,
        "pp_adjusted_gdp": regional_ppp,
        "ppp_adjusted_gdp": regional_ppp,
        "ppp_gdp_year": provenance.get("year"),
        "ppp_gdp_source": provenance.get("source"),
        "ppp_gdp_method": provenance.get("method"),
        "ppp_gdp_currency": provenance.get("currency"),
        "region_name": region,
        "sovereign_country_name": country,
        "reporting_year": reporting_year,
        "cap_attribution_at_one": True,
    }

    inputs["verified_country_emissions"] = _num(
        _pick(
            estimation,
            "verifiedRegionalEmissions",
            "verified_regional_emissions",
            "verifiedCountryEmissions",
            "verified_country_emissions",
        )
    )
    inputs["unverified_country_emissions"] = _num(
        _pick(
            estimation,
            "unverifiedRegionalEmissions",
            "unverified_regional_emissions",
            "unverifiedCountryEmissions",
            "unverified_country_emissions",
        )
    )
    inputs["energy_consumption"] = _num(
        _pick(estimation, "energyConsumption", "energy_consumption", "physicalActivityAmount")
    )
    inputs["emission_factor"] = _num(
        _pick(estimation, "emissionFactor", "emission_factor", "libraryFactorValue")
    )
    inputs["process_emissions"] = _num(_pick(estimation, "processEmissions", "process_emissions"))
    inputs["sector_revenue"] = _num(
        _pick(estimation, "companyRevenue", "company_revenue", "sectorRevenue", "regionalSectorRevenue")
    )
    inputs["sector_intensity"] = _num(
        _pick(estimation, "sectorIntensity", "sector_intensity", "emissionFactor", "emission_factor")
    )
    inputs["sector_intensity_unit"] = _text(
        _pick(estimation, "sectorIntensityUnit", "sector_intensity_unit", "factorUnit", "factor_unit"),
        default="tCO2e/currency",
    )
    # Explicit higher-admin proxy emissions (options 4a/4b) — never silent national catalog.
    inputs["proxy_country_emissions"] = _num(
        _pick(
            estimation,
            "proxyRegionalEmissions",
            "proxy_regional_emissions",
            "proxyCountryEmissions",
            "proxy_country_emissions",
        )
    )
    inputs["proxy_emissions_source"] = _text(
        _pick(estimation, "proxyEmissionsSource", "proxy_emissions_source", "regionalEmissionsSource")
    )
    inputs["regional_emissions_source"] = _text(
        _pick(
            estimation,
            "regionalEmissionsSource",
            "regional_emissions_source",
            "factorSource",
            "factor_source",
        )
    )
    inputs["regional_emissions_unit"] = _text(
        _pick(estimation, "regionalEmissionsUnit", "regional_emissions_unit", "factorUnit"),
        default="tCO2e",
    )
    inputs["regional_emissions_year"] = _text(
        _pick(estimation, "regionalEmissionsYear", "regional_emissions_year", "factorYear")
    )
    return inputs


def calculate_uop_sub_sovereign_asset(
    result: Dict[str, Any],
    *,
    asset: Dict[str, Any],
    estimation: Dict[str, Any],
    allocated: float,
    name: str,
) -> Dict[str, Any]:
    if is_corporate_like_sub_sovereign(asset, estimation):
        result.update(
            {
                "status": "unsupported",
                "code": "corporate_like_sub_sovereign",
                "message": (
                    f"{name}: corporate-like sub-sovereign issuers use Business Loans / "
                    "Unlisted Equity (PCAF §5.10 Table 5.10-2), not the territorial method."
                ),
                "structure_financed_emissions": None,
            }
        )
        return result

    region = _text(
        _pick(estimation, "regionName", "region_name") or _pick(asset, "regionName", "region_name", "name")
    )
    country = _text(
        _pick(estimation, "sovereignCountryName", "sovereign_country_name", "countryName")
        or _pick(asset, "sovereignCountryName", "countryName")
    )
    if not region or not country:
        result.update(
            {
                "status": "incomplete",
                "code": "missing_sub_sovereign_geography",
                "message": f"{name}: enter the region and country for PCAF §5.10 territorial attribution.",
                "structure_financed_emissions": None,
            }
        )
        return result

    option = _text(_pick(estimation, "pcafOption", "pcaf_option", "optionCode", "option_code"))
    if option not in SUB_SOVEREIGN_OPTIONS:
        result.update(
            {
                "status": "incomplete",
                "code": "missing_sub_sovereign_option",
                "message": (
                    f"{name}: choose a sub-sovereign PCAF option (1a, 1b, 2, 3, 4a, or 4b). "
                    "National emissions must not silently replace regional emissions."
                ),
                "structure_financed_emissions": None,
            }
        )
        return result

    try:
        inputs = build_sub_sovereign_inputs(asset, estimation, allocated=allocated)
    except ValueError as exc:
        result.update(
            {
                "status": "incomplete",
                "code": "missing_regional_ppp_gdp",
                "message": f"{name}: {exc}",
                "structure_financed_emissions": None,
            }
        )
        return result

    emissions_source = inputs.get("regional_emissions_source") or ""
    emissions_year = inputs.get("regional_emissions_year") or ""
    if option in ("1a", "1b", "4a", "4b") and (not emissions_source or not emissions_year):
        result.update(
            {
                "status": "incomplete",
                "code": "missing_regional_emissions_provenance",
                "message": (
                    f"{name}: regional territorial emissions require source and year evidence. "
                    "Do not use national inventory values as if they were regional."
                ),
                "structure_financed_emissions": None,
            }
        )
        return result

    if option in ("4a", "4b"):
        if not inputs.get("proxy_country_emissions"):
            result.update(
                {
                    "status": "incomplete",
                    "code": "missing_proxy_emissions",
                    "message": (
                        f"{name}: option {option} requires explicitly entered proxy emissions "
                        "from a higher administrative level, with source evidence (PCAF §5.10). "
                        "National catalog values are not auto-substituted."
                    ),
                    "structure_financed_emissions": None,
                }
            )
            return result
        # Map proxy into unverified slot for engine reuse (score already 5).
        inputs["unverified_country_emissions"] = inputs["proxy_country_emissions"]
        engine_option = "1b"
    elif option in ("2", "2a"):
        engine_option = "2a"
    elif option in ("3", "3a"):
        engine_option = "3a"
    else:
        engine_option = option

    score, _label = SUB_SOVEREIGN_OPTIONS[option]
    # Reuse sovereign engine math; AF cap at 1 is applied after.
    formula_id = f"{option}-sub-sovereign-debt"
    try:
        calc = run_sovereign_calculation(
            formula_id=formula_id,
            option_code=engine_option,
            data_quality_score=score,
            methodology="PCAF Part A 2025 §5.10 (territory-based sub-sovereign)",
            inputs=inputs,
            company_type="sub-sovereign",
        )
    except ValueError as exc:
        result.update(
            {
                "status": "incomplete",
                "code": "sub_sovereign_inputs_invalid",
                "message": f"{name}: {exc}",
                "structure_financed_emissions": None,
            }
        )
        return result

    raw_af = float(calc["attribution_factor"])
    af = min(1.0, raw_af)  # PCAF §5.10: cap outstanding/GDP at 1
    country_emissions = float(calc.get("emission_factor") or 0.0)
    if country_emissions <= 0 and raw_af > 0:
        country_emissions = float(calc["financed_emissions"]) / raw_af
    fe = af * country_emissions

    result.update(
        {
            "status": "complete",
            "asset_attribution_factor": af,
            "denominator": float(inputs["pp_adjusted_gdp"]),
            "denominator_kind": "regional_ppp_adjusted_gdp",
            "denominator_label": "Regional PPP-adjusted GDP",
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
                "PCAF §5.10 Outstanding / regional PPP-adjusted GDP × regional "
                f"territorial emissions (AF capped at 1); option {option}; "
                f"GDP method={inputs.get('ppp_gdp_method')} "
                f"source={inputs.get('ppp_gdp_source')} year={inputs.get('ppp_gdp_year')}"
            ),
            "region_name": inputs.get("region_name"),
            "sovereign_country_name": inputs.get("sovereign_country_name"),
            "ppp_gdp_year": inputs.get("ppp_gdp_year"),
            "ppp_gdp_source": inputs.get("ppp_gdp_source"),
            "ppp_gdp_currency": inputs.get("ppp_gdp_currency"),
            "attribution_capped_at_one": af < raw_af - 1e-15,
            "pcaf_ref": "PCAF Part A 2025 §5.10 / Annex 10.3",
        }
    )
    return result
