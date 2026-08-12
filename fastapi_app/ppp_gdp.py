"""PPP-adjusted GDP resolution for sovereign debt PCAF (ref.ppp_adjusted_gdp)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

PREFERRED_YEAR = 2025
FALLBACK_YEAR = 2024

SOVEREIGN_DEBT_FORMULA_SUFFIX = "-sovereign-debt"


def is_sovereign_formula(formula_id: str) -> bool:
    fid = (formula_id or "").strip().lower()
    return fid.endswith(SOVEREIGN_DEBT_FORMULA_SUFFIX) or "sovereign-debt" in fid


def resolve_ppp_gdp(
    row: dict, preferred_year: int = PREFERRED_YEAR
) -> Optional[Tuple[Decimal, int, bool]]:
    g2025 = row.get("gdp_2025")
    g2024 = row.get("gdp_2024")
    if preferred_year == PREFERRED_YEAR and g2025 is not None and Decimal(g2025) > 0:
        return Decimal(g2025), PREFERRED_YEAR, False
    if g2025 is not None and Decimal(g2025) > 0:
        return Decimal(g2025), PREFERRED_YEAR, False
    if g2024 is not None and Decimal(g2024) > 0:
        used_fallback = preferred_year == PREFERRED_YEAR
        return Decimal(g2024), FALLBACK_YEAR, used_fallback
    return None


def row_has_resolvable_ppp(row: dict) -> bool:
    return resolve_ppp_gdp(dict(row)) is not None


def load_ppp_gdp(
    db: Session, country_name: str, preferred_year: int = PREFERRED_YEAR
) -> Optional[Dict[str, Any]]:
    row = (
        db.execute(
            text(
                """
                SELECT country_name, gdp_2024, gdp_2025
                FROM ref.ppp_adjusted_gdp
                WHERE lower(country_name) = lower(:name)
                """
            ),
            {"name": country_name},
        )
        .mappings()
        .first()
    )
    if not row:
        return None
    resolved = resolve_ppp_gdp(dict(row), preferred_year)
    if not resolved:
        return None
    value, year, used_fallback = resolved
    return {
        "pp_adjusted_gdp": float(value),
        "ppp_gdp_year": year,
        "ppp_gdp_used_fallback": used_fallback,
    }


def normalize_sovereign_field_aliases(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """Map SPA field names to Python calculation_engine keys without changing math."""
    out = dict(inputs)
    pp = out.get("pp_adjusted_gdp") or out.get("ppp_adjusted_gdp")
    if pp:
        out["pp_adjusted_gdp"] = pp
        out["ppp_adjusted_gdp"] = pp
    proxy_pp = out.get("proxy_pp_adjusted_gdp") or out.get("proxy_ppp_adjusted_gdp")
    if proxy_pp:
        out["proxy_pp_adjusted_gdp"] = proxy_pp
        out["proxy_ppp_adjusted_gdp"] = proxy_pp
    if out.get("verified_country_emissions") and not out.get("verified_emissions"):
        out["verified_emissions"] = out["verified_country_emissions"]
    if out.get("unverified_country_emissions") and not out.get("unverified_emissions"):
        out["unverified_emissions"] = out["unverified_country_emissions"]
    return out


def apply_ppp_resolution(
    db: Session,
    inputs: Dict[str, Any],
    *,
    require_country: bool = False,
) -> Dict[str, Any]:
    """
    When resolve_ppp_gdp is true, load PPP GDP from ref.ppp_adjusted_gdp by country name.
    Raises ValueError if require_country and sovereign country has no PPP row.
    """
    out = dict(inputs)
    if not out.get("resolve_ppp_gdp"):
        return normalize_sovereign_field_aliases(out)

    country = (out.get("sovereign_country_name") or "").strip()
    if country:
        if not out.get("pp_adjusted_gdp") and not out.get("ppp_adjusted_gdp"):
            ppp = load_ppp_gdp(db, country)
            if not ppp:
                raise ValueError(f"No PPP-adjusted GDP for {country}")
            out["pp_adjusted_gdp"] = ppp["pp_adjusted_gdp"]
            out["ppp_adjusted_gdp"] = ppp["pp_adjusted_gdp"]
            out["ppp_gdp_year"] = ppp["ppp_gdp_year"]
            out["ppp_gdp_used_fallback"] = ppp["ppp_gdp_used_fallback"]

    proxy = (out.get("proxy_sovereign_country_name") or "").strip()
    if proxy and not out.get("proxy_pp_adjusted_gdp") and not out.get("proxy_ppp_adjusted_gdp"):
        proxy_ppp = load_ppp_gdp(db, proxy)
        if proxy_ppp:
            out["proxy_pp_adjusted_gdp"] = proxy_ppp["pp_adjusted_gdp"]
            out["proxy_ppp_adjusted_gdp"] = proxy_ppp["pp_adjusted_gdp"]
            out["proxy_ppp_gdp_year"] = proxy_ppp["ppp_gdp_year"]
            out["proxy_ppp_gdp_used_fallback"] = proxy_ppp["ppp_gdp_used_fallback"]

    return normalize_sovereign_field_aliases(out)
