"""Approved emission-factor library matching. No silent geography/year substitution."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Optional


ALLOWED_CLASSES = frozenset({"physical", "economic", "building", "vehicle"})
APPROVED = "approved"
NO_FACTOR = "NO_VERIFIED_FACTOR"

MASS_TO_TCO2E = {
    "tco2e": 1.0,
    "t co2e": 1.0,
    "tonne co2e": 1.0,
    "tonnes co2e": 1.0,
    "kgco2e": 0.001,
    "kg co2e": 0.001,
    "kgco2": 0.001,
}


@dataclass(frozen=True)
class LibraryFactor:
    id: str
    publication_id: str
    dataset_code: str
    dataset_version: str
    category: str
    library_class: str
    geography: str
    country_code: str
    sector_or_activity: str
    activity_key: str
    factor_value: float
    unit: str
    numerator_unit: str
    denominator_unit: str
    applicable_year: int
    publication_year: int
    gas: str
    source_organization: str
    source_document: str
    source_url: str
    provenance: str
    license_name: str
    permitted_use: str
    currency_code: str
    price_year: Optional[int]
    status: str

    def snapshot(self) -> dict[str, Any]:
        data = asdict(self)
        data["confirmed"] = True
        return data


@dataclass(frozen=True)
class MatchQuery:
    library_class: str
    geography: str
    activity_key: str
    reporting_year: int
    unit: str = ""
    currency_code: str = ""
    price_year: Optional[int] = None


@dataclass(frozen=True)
class MatchResult:
    status: str
    factors: tuple[LibraryFactor, ...]
    message: str

    @property
    def available(self) -> bool:
        return self.status == "ok" and len(self.factors) > 0


def _norm(value: str | None) -> str:
    return " ".join(str(value or "").strip().lower().split())


def compatible_mass_factor(value: float, unit: str) -> Optional[float]:
    """Convert only CO2e mass totals. Intensity units (per kWh, per currency) are unchanged."""
    raw = (unit or "").strip().lower()
    if "/" in raw or " per " in raw:
        return None
    key = _norm(raw).replace("_", " ")
    for token, multiplier in MASS_TO_TCO2E.items():
        if token in key:
            return value * multiplier
    return None


def library_class_compatible(query_class: str, factor_class: str) -> bool:
    """Building/vehicle screens may reuse a physical electricity or fuel row."""
    query = _norm(query_class)
    factor = _norm(factor_class)
    if query == factor:
        return True
    if query == "building" and factor in {"building", "physical"}:
        return True
    if query == "vehicle" and factor in {"vehicle", "physical"}:
        return True
    return False


def units_compatible(requested: str, candidate: str) -> bool:
    req = _norm(requested)
    cand = _norm(candidate)
    if not req or not cand:
        return True
    if req == cand:
        return True
    req_tokens = set(req.replace("/", " ").split())
    cand_tokens = set(cand.replace("/", " ").split())
    if req_tokens and req_tokens <= cand_tokens:
        return True
    if {"kwh", "mwh"} & req_tokens and {"kwh", "mwh"} & cand_tokens:
        return False
    return False


def economic_basis_ok(query: MatchQuery, factor: LibraryFactor) -> bool:
    if factor.library_class != "economic":
        return True
    if _norm(query.currency_code) and _norm(factor.currency_code):
        if _norm(query.currency_code) != _norm(factor.currency_code):
            return False
    if query.price_year and factor.price_year and int(query.price_year) != int(factor.price_year):
        return False
    return True


def match_factors(query: MatchQuery, catalog: Iterable[LibraryFactor]) -> MatchResult:
    cls = _norm(query.library_class)
    if cls not in ALLOWED_CLASSES:
        return MatchResult("unsupported_class", (), "Unsupported factor class.")
    geo = _norm(query.geography)
    activity = _norm(query.activity_key)
    year = int(query.reporting_year)
    if not geo or not activity or year <= 0:
        return MatchResult("invalid_query", (), "Country, activity, and reporting year are required.")

    hits: list[LibraryFactor] = []
    for item in catalog:
        if item.status != APPROVED:
            continue
        if not library_class_compatible(cls, item.library_class):
            continue
        if _norm(item.geography) != geo and _norm(item.country_code) != geo:
            continue
        if _norm(item.activity_key) != activity and _norm(item.sector_or_activity) != activity:
            continue
        if int(item.applicable_year) != year:
            continue
        if not units_compatible(query.unit, item.unit):
            continue
        if not economic_basis_ok(query, item):
            continue
        hits.append(item)

    if not hits:
        return MatchResult(
            NO_FACTOR,
            (),
            "No verified factor available for this country, activity, and year.",
        )
    if len(hits) == 1:
        return MatchResult("ok", tuple(hits), "One approved factor matches.")
    return MatchResult("multiple", tuple(hits), "Multiple approved factors match. Confirm one.")


def require_confirmed_snapshot(estimation: dict[str, Any]) -> Optional[str]:
    """Return an error code if a library factor was selected but not confirmed or drifted."""
    entry_id = str(estimation.get("libraryEntryId") or estimation.get("library_entry_id") or "").strip()
    if not entry_id:
        return None
    confirmed = estimation.get("factorConfirmed")
    if confirmed is False or str(confirmed).lower() in {"0", "false", "no"}:
        return "FACTOR_NOT_CONFIRMED"
    live = estimation.get("emissionFactor")
    snap = estimation.get("libraryFactorValue")
    if live is not None and snap is not None:
        try:
            if abs(float(live) - float(snap)) > 1e-9:
                return "FACTOR_SNAPSHOT_MISMATCH"
        except (TypeError, ValueError):
            return "FACTOR_SNAPSHOT_MISMATCH"
    geo = str(estimation.get("factorGeography") or "")
    snap_geo = str(estimation.get("libraryGeography") or "")
    if snap_geo and _norm(geo) != _norm(snap_geo):
        return "FACTOR_GEOGRAPHY_MISMATCH"
    year = str(estimation.get("factorYear") or "")
    snap_year = str(estimation.get("libraryApplicableYear") or "")
    if snap_year and year and year != snap_year:
        return "FACTOR_YEAR_MISMATCH"
    return None


SNAPSHOT_ERRORS = {
    "FACTOR_NOT_CONFIRMED": "Confirm the approved factor before calculating. The calculator will not guess one.",
    "FACTOR_SNAPSHOT_MISMATCH": "The factor value no longer matches the approved library snapshot. Recalculation is blocked so the historical value is not silently replaced.",
    "FACTOR_GEOGRAPHY_MISMATCH": "The factor geography no longer matches the approved library snapshot. Another country will not be substituted.",
    "FACTOR_YEAR_MISMATCH": "The factor year no longer matches the approved library snapshot. Another year will not be substituted.",
}

SOURCE_REGISTRY = (
    {
        "code": "desnz_ghg_conversion_factors_2026",
        "organization": "UK DESNZ",
        "status": "catalog_verified_not_auto_approved",
        "integrated": False,
        "notes": (
            "UK electricity 0.13096 kgCO2e/kWh and district heat 0.17529 kgCO2e/kWh "
            "are already stored as verified catalog rows. Promote into the library "
            "only after administrator approval. Applicable year 2026 only."
        ),
        "permitted_use": "UK government conversion factors already loaded in-catalog.",
        "geographies": ["United Kingdom"],
    },
    {
        "code": "epa_ghg_emission_factors_hub",
        "organization": "US EPA",
        "status": "not_imported_this_phase",
        "integrated": False,
        "notes": "Edition, license, and permitted commercial use must be reviewed before bulk import.",
        "permitted_use": "unverified",
        "geographies": ["United States"],
    },
    {
        "code": "ipcc_physical_factors",
        "organization": "IPCC",
        "status": "not_imported_this_phase",
        "integrated": False,
        "notes": "No IPCC physical factor set is auto-loaded into the library.",
        "permitted_use": "unverified",
        "geographies": [],
    },
    {
        "code": "pakistan_uae_electricity",
        "organization": "unverified",
        "status": "unsupported",
        "integrated": False,
        "notes": (
            "SPA placeholders 0.4041 (UAE) and 0.425 (Pakistan) are refused by server "
            "Scope 2 engines. They are not promoted. Do not substitute US or UK grid factors."
        ),
        "permitted_use": "blocked",
        "geographies": ["Pakistan", "United Arab Emirates"],
    },
    {
        "code": "pcaf_building_financed",
        "organization": "PCAF",
        "status": "not_imported_this_phase",
        "integrated": False,
        "notes": "Building intensity methods stay on existing PCAF formula IDs. No extra PCAF factor table is invented.",
        "permitted_use": "unverified",
        "geographies": [],
    },
    {
        "code": "exiobase",
        "organization": "EXIOBASE",
        "status": "license_blocked",
        "integrated": False,
        "notes": "Not imported. Commercial use is not assumed.",
        "permitted_use": "blocked_pending_license",
        "geographies": [],
    },
    {
        "code": "ice_eeio_educational",
        "organization": "ICE",
        "status": "license_blocked",
        "integrated": False,
        "notes": "ICE Educational V5.0 is educational-only and is not imported for commercial calculations.",
        "permitted_use": "blocked",
        "geographies": [],
    },
)


def factor_snapshot_from_estimation(estimation: dict[str, Any]) -> dict[str, Any]:
    return {
        "library_entry_id": str(estimation.get("libraryEntryId") or estimation.get("library_entry_id") or "") or None,
        "publication_id": str(estimation.get("libraryPublicationId") or estimation.get("library_publication_id") or "") or None,
        "factor_value": estimation.get("libraryFactorValue", estimation.get("emissionFactor")),
        "unit": estimation.get("libraryFactorUnit") or estimation.get("factorUnit"),
        "dataset_code": estimation.get("factorDatasetCode"),
        "dataset_version": estimation.get("libraryDatasetVersion"),
        "source": estimation.get("factorSource"),
        "geography": estimation.get("libraryGeography") or estimation.get("factorGeography"),
        "applicable_year": estimation.get("libraryApplicableYear") or estimation.get("factorYear"),
        "currency_code": estimation.get("activityCurrency") or estimation.get("libraryCurrencyCode"),
        "price_year": estimation.get("priceYear") or estimation.get("libraryPriceYear"),
        "confirmed": bool(estimation.get("factorConfirmed")),
    }


def entry_to_factor(row: Any) -> LibraryFactor:
    return LibraryFactor(
        id=str(row.id),
        publication_id=str(row.publication_id),
        dataset_code=str(row.dataset_code or ""),
        dataset_version=str(row.dataset_version or ""),
        category=str(row.category or ""),
        library_class=str(row.library_class),
        geography=str(row.geography),
        country_code=str(row.country_code or ""),
        sector_or_activity=str(row.sector_or_activity),
        activity_key=str(row.activity_key),
        factor_value=float(row.factor_value),
        unit=str(row.unit),
        numerator_unit=str(row.numerator_unit),
        denominator_unit=str(row.denominator_unit),
        applicable_year=int(row.applicable_year),
        publication_year=int(row.publication_year),
        gas=str(row.gas or "CO2e"),
        source_organization=str(row.source_organization),
        source_document=str(row.source_document or ""),
        source_url=str(row.source_url or ""),
        provenance=str(row.provenance or ""),
        license_name=str(row.license_name or ""),
        permitted_use=str(row.permitted_use or ""),
        currency_code=str(row.currency_code or ""),
        price_year=int(row.price_year) if row.price_year is not None else None,
        status=str(row.status),
    )


def split_unit(unit: str) -> tuple[str, str]:
    text = (unit or "").strip()
    for sep in ("/", " per ", " PER "):
        if sep in text:
            left, right = text.split(sep, 1)
            return left.strip() or "kgCO2e", right.strip() or "unit"
    return text or "kgCO2e", "unit"

