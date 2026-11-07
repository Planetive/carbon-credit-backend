"""Server-side UoP factor binding. Client numbers are never authoritative."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from .factor_library import _norm, entry_to_factor, library_class_compatible
from .factor_library_models import FactorLibraryEntry

# Formula-unit tests may authorize a pre-bound typed factor. Production never sets this.
_ALLOW_UNBOUND_TYPED: ContextVar[bool] = ContextVar("uop_allow_unbound_typed", default=False)

UOP_OPTION_BINDINGS = (
    {
        "asset_classes": ("mortgage", "commercial-real-estate"),
        "options": ("1a", "1b", "2a", "2b", "3"),
        "library_class": "building",
        "accepts_library_class": ("building", "physical"),
        "activity_keys": ("electricity", "heat", "purchased_electricity", "purchased_heat"),
        "units": "kgCO2e/kWh or tCO2e/kWh (MWh accepted as energy, not substituted)",
        "method": "physical energy × grid or heat factor",
        "available_now": "UK DESNZ 2026 electricity and heat only",
    },
    {
        "asset_classes": ("motor-vehicle-loan",),
        "options": ("1a", "1b", "2a", "2b", "3a", "3b"),
        "library_class": "vehicle",
        "accepts_library_class": ("vehicle", "physical"),
        "activity_keys": ("vehicle-fuel", "fuel", "mobile-fuel"),
        "units": "kgCO2e/litre or tCO2e/litre; gallon factors are rejected",
        "method": "physical fuel or distance × fuel factor",
        "available_now": "none — no approved litre-basis library row",
    },
    {
        "asset_classes": ("listed-equity", "corporate-bond", "business-loan", "unlisted-equity", "project-finance"),
        "options": ("2a",),
        "library_class": "physical",
        "accepts_library_class": ("physical",),
        "activity_keys": ("electricity", "heat", "purchased_electricity", "purchased_heat"),
        "units": "kgCO2e/kWh (numerically equals tCO2e/MWh after intensity conversion)",
        "method": "energy consumption × grid or heat factor",
        "available_now": "UK DESNZ 2026 electricity and heat only",
    },
    {
        "asset_classes": ("listed-equity", "corporate-bond", "business-loan", "unlisted-equity", "project-finance"),
        "options": ("2b",),
        "library_class": "physical",
        "accepts_library_class": ("physical",),
        "activity_keys": ("production",),
        "units": "tCO2e per production unit",
        "method": "production × physical factor",
        "available_now": "none — no approved production library row",
    },
    {
        "asset_classes": ("listed-equity", "corporate-bond", "business-loan", "unlisted-equity", "project-finance"),
        "options": ("3a", "3c", "score5"),
        "library_class": "economic",
        "accepts_library_class": ("economic",),
        "activity_keys": ("sector-intensity", "manufacturing", "sector"),
        "units": "tCO2e per currency, with currency code and price year",
        "method": "economic intensity; unavailable until a verified EEIO row is approved",
        "available_now": "none — EXIOBASE/ICE Educational are blocked",
    },
)


def allow_unbound_typed_factors(enabled: bool = True) -> Token:
    """Test-only seam. Do not call from application routers."""
    return _ALLOW_UNBOUND_TYPED.set(enabled)


def reset_unbound_typed_factors(token: Token) -> None:
    _ALLOW_UNBOUND_TYPED.reset(token)


def unbound_typed_allowed() -> bool:
    return bool(_ALLOW_UNBOUND_TYPED.get())

BIND_ERRORS = {
    "FACTOR_NOT_BOUND": (
        "No verified factor available. Confirm an approved library factor. "
        "A typed number is not used."
    ),
    "FACTOR_NOT_CONFIRMED": "Confirm the approved factor before calculating.",
    "LIBRARY_UNAVAILABLE": (
        "The approved-factor library is not available on this database. "
        "Estimation cannot use a typed factor."
    ),
    "FACTOR_NOT_FOUND": "The selected factor was not found.",
    "FACTOR_NOT_APPROVED": (
        "That factor is not approved. Pending or rejected submissions are not used."
    ),
    "FACTOR_ORG_ISOLATION": "That factor belongs to another organization.",
    "FACTOR_SNAPSHOT_MISMATCH": (
        "The submitted factor value does not match the approved library row. "
        "The calculator will not use the typed number."
    ),
    "FACTOR_GEOGRAPHY_MISMATCH": (
        "The submitted geography does not match the approved factor. "
        "Another country will not be substituted."
    ),
    "FACTOR_YEAR_MISMATCH": (
        "The submitted year does not match the approved factor. "
        "Another year will not be substituted."
    ),
    "FACTOR_UNIT_MISMATCH": (
        "The approved factor units do not match this calculation option."
    ),
    "FACTOR_CLASS_MISMATCH": (
        "The approved factor class does not match this calculation option."
    ),
    "FACTOR_ACTIVITY_MISMATCH": (
        "The approved factor activity does not match this calculation option."
    ),
    "ECONOMIC_FACTOR_UNAVAILABLE": (
        "No verified economic intensity factor is available for this sector, "
        "currency, and price year."
    ),
    "INVALID_FACTOR_ID": "The selected factor id is not valid.",
}

ELECTRICITY_ACTIVITIES = frozenset({"electricity", "heat", "purchased_electricity", "purchased_heat"})
PRODUCTION_ACTIVITIES = frozenset({"production"})
VEHICLE_ACTIVITIES = frozenset({"vehicle-fuel", "fuel", "mobile-fuel"})
ECONOMIC_ACTIVITIES = frozenset({"sector-intensity", "manufacturing", "sector"})

ENERGY_OPTIONS = frozenset({"2a", "1a", "1b"})  # corporate 2a energy; building 1a/1b/2a/2b/3 handled by class
BUILDING_GRID_OPTIONS = frozenset({"1a", "1b", "2a", "2b", "3"})
MOTOR_OPTIONS = frozenset({"1a", "1b", "2a", "2b", "3a", "3b"})
ECONOMIC_OPTIONS = frozenset({"3a", "3c", "score5"})
PRODUCTION_OPTIONS = frozenset({"2b"})
BUILDING_CLASSES = frozenset({"mortgage", "commercial-real-estate"})
MOTOR_CLASSES = frozenset({"motor-vehicle-loan"})


@dataclass(frozen=True)
class BoundFactor:
    library_entry_id: str
    publication_id: str
    factor_row_id: Optional[str]
    dataset_code: str
    dataset_version: str
    library_class: str
    geography: str
    activity_key: str
    factor_value: float
    unit: str
    applicable_year: int
    publication_year: int
    source_organization: str
    currency_code: str
    price_year: Optional[int]
    status: str

    def apply_to_estimation(self, estimation: dict[str, Any]) -> dict[str, Any]:
        patched = dict(estimation)
        patched["libraryEntryId"] = self.library_entry_id
        patched["libraryPublicationId"] = self.publication_id
        patched["libraryFactorValue"] = self.factor_value
        patched["libraryFactorUnit"] = self.unit
        patched["libraryGeography"] = self.geography
        patched["libraryApplicableYear"] = str(self.applicable_year)
        patched["libraryDatasetVersion"] = self.dataset_version
        patched["libraryCurrencyCode"] = self.currency_code
        patched["libraryPriceYear"] = "" if self.price_year is None else str(self.price_year)
        patched["factorConfirmed"] = True
        patched["emissionFactor"] = self.factor_value
        patched["factorUnit"] = self.unit
        patched["factorGeography"] = self.geography
        patched["factorYear"] = str(self.applicable_year)
        patched["factorSource"] = self.source_organization
        patched["factorDatasetCode"] = self.dataset_code
        patched["activityCurrency"] = self.currency_code or patched.get("activityCurrency") or ""
        if self.price_year is not None:
            patched["priceYear"] = str(self.price_year)
        return patched

    def snapshot(self) -> dict[str, Any]:
        return {
            "library_entry_id": self.library_entry_id,
            "publication_id": self.publication_id,
            "factor_row_id": self.factor_row_id,
            "dataset_code": self.dataset_code,
            "dataset_version": self.dataset_version,
            "factor_value": self.factor_value,
            "unit": self.unit,
            "geography": self.geography,
            "applicable_year": self.applicable_year,
            "source": self.source_organization,
            "currency_code": self.currency_code or None,
            "price_year": self.price_year,
            "status": self.status,
            "bound_from": "ref.factor_library_entries",
            "client_value_used": False,
        }


@dataclass(frozen=True)
class BindResult:
    ok: bool
    code: str = ""
    message: str = ""
    factor: Optional[BoundFactor] = None


def _fail(code: str) -> BindResult:
    return BindResult(False, code, BIND_ERRORS.get(code, code))


def library_tables_ready(db: Optional[Session]) -> bool:
    if db is None:
        return False
    execute = getattr(db, "execute", None)
    if execute is None:
        return False
    try:
        return bool(
            execute(
                text(
                    "SELECT EXISTS ("
                    "  SELECT 1 FROM information_schema.tables "
                    "  WHERE table_schema = 'ref' AND table_name = 'factor_library_entries'"
                    ")"
                )
            ).scalar()
        )
    except Exception:
        return False


def _unit_key(unit: str) -> str:
    return _norm(unit).replace("per", "/").replace(" ", "")


def _is_electricity_unit(unit: str) -> bool:
    key = _unit_key(unit)
    return "kwh" in key or "mwh" in key


def _is_fuel_unit(unit: str) -> bool:
    key = _unit_key(unit)
    if "gallon" in key or "gal" == key or key.endswith("/gal"):
        return False
    return "litre" in key or "liter" in key or key.endswith("/l") or "/l" in key


def _is_economic_unit(unit: str) -> bool:
    key = _unit_key(unit)
    return any(token in key for token in ("pkr", "usd", "eur", "gbp", "currency", "revenue"))


def expected_library_class(asset_class: str, option: str) -> str:
    if asset_class in BUILDING_CLASSES:
        return "building"
    if asset_class in MOTOR_CLASSES:
        return "vehicle"
    if option in ECONOMIC_OPTIONS:
        return "economic"
    return "physical"


def class_compatible(asset_class: str, option: str, library_class: str) -> bool:
    return library_class_compatible(expected_library_class(asset_class, option), library_class)


def activity_compatible(asset_class: str, option: str, activity_key: str, sector_or_activity: str) -> bool:
    activity = _norm(activity_key) or _norm(sector_or_activity)
    if asset_class in MOTOR_CLASSES and option in MOTOR_OPTIONS:
        return activity in {_norm(item) for item in VEHICLE_ACTIVITIES} or "fuel" in activity
    if option in ECONOMIC_OPTIONS:
        return True
    if option in PRODUCTION_OPTIONS and asset_class not in BUILDING_CLASSES:
        return activity in {_norm(item) for item in PRODUCTION_ACTIVITIES}
    if asset_class in BUILDING_CLASSES or option in ENERGY_OPTIONS or option in BUILDING_GRID_OPTIONS:
        return activity in {_norm(item) for item in ELECTRICITY_ACTIVITIES} or activity in {"electricity", "heat"}
    return True


def unit_compatible(asset_class: str, option: str, unit: str) -> bool:
    if option in ECONOMIC_OPTIONS:
        return _is_economic_unit(unit)
    if asset_class in MOTOR_CLASSES:
        return _is_fuel_unit(unit)
    if option in PRODUCTION_OPTIONS and asset_class not in BUILDING_CLASSES:
        key = _unit_key(unit)
        return "tonne" in key or "ton" in key or "unit" in key
    return _is_electricity_unit(unit)


def _parse_uuid(value: str) -> Optional[UUID]:
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _close_enough(left: Any, right: Any) -> bool:
    try:
        return abs(float(left) - float(right)) <= 1e-9
    except (TypeError, ValueError):
        return False


def _entry_to_bound(entry: FactorLibraryEntry) -> BoundFactor:
    factor = entry_to_factor(entry)
    return BoundFactor(
        library_entry_id=str(entry.id),
        publication_id=str(entry.publication_id),
        factor_row_id=str(entry.factor_row_id) if entry.factor_row_id else None,
        dataset_code=factor.dataset_code,
        dataset_version=factor.dataset_version,
        library_class=factor.library_class,
        geography=factor.geography,
        activity_key=factor.activity_key,
        factor_value=float(factor.factor_value),
        unit=factor.unit,
        applicable_year=int(factor.applicable_year),
        publication_year=int(factor.publication_year),
        source_organization=factor.source_organization,
        currency_code=factor.currency_code,
        price_year=factor.price_year,
        status=factor.status,
    )


def resolve_uop_library_factor(
    estimation: dict[str, Any],
    *,
    db: Optional[Session] = None,
    organization_id: Any = None,
    asset_class: str = "",
    option: str = "",
    reporting_year: Optional[str] = None,
) -> BindResult:
    """Load the approved library row. Never returns a client-typed value as verified."""
    entry_id = str(
        estimation.get("libraryEntryId") or estimation.get("library_entry_id") or ""
    ).strip()
    if not entry_id:
        if unbound_typed_allowed():
            return BindResult(
                True,
                "TEST_SEAM_UNBOUND",
                "Typed factor authorized only for PCAF formula-unit tests.",
                None,
            )
        if option in ECONOMIC_OPTIONS:
            return _fail("ECONOMIC_FACTOR_UNAVAILABLE")
        return _fail("FACTOR_NOT_BOUND")

    confirmed = estimation.get("factorConfirmed")
    if confirmed is False or str(confirmed).lower() in {"0", "false", "no"}:
        return _fail("FACTOR_NOT_CONFIRMED")

    if not library_tables_ready(db):
        if unbound_typed_allowed():
            return BindResult(
                True,
                "TEST_SEAM_UNBOUND",
                "Typed factor authorized only for PCAF formula-unit tests.",
                None,
            )
        return _fail("LIBRARY_UNAVAILABLE")

    uid = _parse_uuid(entry_id)
    if uid is None:
        return _fail("INVALID_FACTOR_ID")

    entry = db.query(FactorLibraryEntry).filter(FactorLibraryEntry.id == uid).first()
    if entry is None:
        return _fail("FACTOR_NOT_FOUND")
    if str(entry.status) != "approved":
        return _fail("FACTOR_NOT_APPROVED")
    if entry.organization_id is not None and organization_id is not None:
        if str(entry.organization_id) != str(organization_id):
            return _fail("FACTOR_ORG_ISOLATION")

    bound = _entry_to_bound(entry)

    client_value = estimation.get("emissionFactor", estimation.get("libraryFactorValue"))
    if client_value is not None and client_value != "" and not _close_enough(client_value, bound.factor_value):
        return _fail("FACTOR_SNAPSHOT_MISMATCH")
    client_geo = str(estimation.get("factorGeography") or estimation.get("libraryGeography") or "")
    if client_geo and _norm(client_geo) not in {_norm(bound.geography), _norm(getattr(entry, "country_code", "") or "")}:
        return _fail("FACTOR_GEOGRAPHY_MISMATCH")
    client_year = str(estimation.get("factorYear") or estimation.get("libraryApplicableYear") or "")
    if client_year and client_year.strip() != str(bound.applicable_year):
        return _fail("FACTOR_YEAR_MISMATCH")
    if option and not class_compatible(asset_class, option, bound.library_class):
        if option in ECONOMIC_OPTIONS:
            return _fail("ECONOMIC_FACTOR_UNAVAILABLE")
        return _fail("FACTOR_CLASS_MISMATCH")
    if option and not activity_compatible(asset_class, option, bound.activity_key, entry.sector_or_activity):
        return _fail("FACTOR_ACTIVITY_MISMATCH")
    if option and not unit_compatible(asset_class, option, bound.unit):
        return _fail("FACTOR_UNIT_MISMATCH")

    return BindResult(True, "ok", "Approved library factor bound from PostgreSQL.", bound)
