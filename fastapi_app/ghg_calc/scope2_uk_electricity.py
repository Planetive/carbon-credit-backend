"""
Location-based purchased electricity for the UK calculator.

The factor is read from ref.factor_rows. A client number is never accepted.
The grid country, grid region, reporting year, and generation-only boundary
choose the row. Opening the UK calculator does not select a UK factor.

No factor value is invented when a row is missing. These published figures are
acceptance checks for a stored row, not fallbacks:

- United Kingdom, national grid, reporting year 2025: DESNZ 2025 electricity
  generated, 0.17700 kg CO2e/kWh. Transmission and distribution (0.01853) and
  electricity consumed (0.19553) are rejected.
- United Kingdom, national grid, reporting year 2026: DESNZ 2026 electricity
  generated, 0.13096 kg CO2e/kWh. The 2026 methodology paper, paragraph 1.10,
  applies that edition to activity in 2026. Paragraph 3.9 keeps generation in
  Scope 2 and grid losses in Scope 3.
- United Arab Emirates: only a DEWA generation factor for the Dubai grid and
  the same reporting year. The national placeholder 0.4041 is rejected.
  Abu Dhabi and a UAE-wide grid are not given the Dubai factor.
- Pakistan: 0.425, IGCEP generation intensity, and Ember lifecycle data are
  rejected. Any other country or year without a verified generation row is
  reported as a missing factor.

Contractual renewable kWh are stored and are not deducted. Fuel burned by the
organisation is not part of this calculation.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from ..factor_models import FactorDataset, FactorRow

ACCOUNTING_VERSION = "scope2_uk_location_electricity_v1"
CATEGORY = "purchased_electricity"
LOCATION_METHOD = "location_based"
GENERATION_BOUNDARIES = {"electricity_generated", "generation", "generation_only"}
_TONNE = Decimal("1000")
_QUANT = Decimal("0.00000001")
_MATCH = Decimal("0.00001")
_KWH_PER_MWH = Decimal("1000")

UK_GENERATION_KG = {
    2025: Decimal("0.17700"),
    2026: Decimal("0.13096"),
}
REJECTED_PLACEHOLDERS = (
    Decimal("0.425"),
    Decimal("0.4041"),
    Decimal("0.17355"),
)
UK_NAMES = {"uk", "u.k.", "united kingdom", "great britain", "britain", "gb"}
UK_GRIDS = {"national", "uk", "united kingdom", "great britain", "gb", "electricity: uk"}
UAE_NAMES = {"uae", "u.a.e.", "united arab emirates"}
PAKISTAN_NAMES = {"pakistan", "pk"}
DUBAI_GRIDS = {"dubai", "dewa", "dubai grid", "emirate of dubai"}


def _text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def _norm(value: Any) -> str:
    return _text(value).lower().replace(".", "")


def _decimal(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite():
        return None
    return number


def _same(left: Decimal, right: Decimal) -> bool:
    return left.quantize(_MATCH) == right.quantize(_MATCH)


def _year(value: Any) -> Optional[int]:
    if isinstance(value, int) and not isinstance(value, bool):
        year = value
    else:
        text = _text(value)
        if len(text) != 4 or not text.isdigit():
            return None
        year = int(text)
    if year < 1990 or year > 2200:
        return None
    return year


def _quantize(value: Decimal) -> str:
    return format(value.quantize(_QUANT), "f")


def _country_kind(country: str) -> str:
    key = _norm(country)
    if key in UK_NAMES:
        return "uk"
    if key in UAE_NAMES or key == "dubai":
        return "uae"
    if key in PAKISTAN_NAMES:
        return "pakistan"
    return "other"


def _row_pairs(db: Session) -> Sequence[Tuple[FactorRow, FactorDataset]]:
    return (
        db.query(FactorRow, FactorDataset)
        .join(FactorDataset, FactorDataset.id == FactorRow.dataset_id)
        .all()
    )


def _covers_year(dataset: FactorDataset, year: int) -> bool:
    if dataset.effective_from is not None and year < dataset.effective_from.year:
        return False
    if dataset.effective_to is not None and year > dataset.effective_to.year:
        return False
    return True


def _blob(*values: Any) -> str:
    return " ".join(_norm(value) for value in values if _text(value))


def _rejected_source(row: FactorRow, dataset: FactorDataset) -> Optional[str]:
    attributes = row.attributes or {}
    identity = _blob(dataset.publisher, dataset.code, dataset.title, row.label, attributes.get("source_document"))
    boundary = _blob(attributes.get("boundary"), attributes.get("method"), row.label, attributes.get("includes"))
    if "igcep" in identity or "igcep" in boundary:
        return "IGCEP generation intensity is not a verified purchased-electricity factor."
    if any(token in identity or token in boundary for token in ("ember", "lifecycle", "life cycle")):
        return "Ember lifecycle intensity is not a verified purchased-electricity factor."
    if any(token in boundary for token in ("well-to-tank", "well to tank", "wtt")):
        return "Well-to-tank electricity is Scope 3 and was not used."
    if any(token in boundary for token in ("transmission", "distribution", "t&d", "grid losses", "grid loss")):
        return "Transmission and distribution losses are Scope 3 and were not used."
    if "consumed" in boundary or "including losses" in boundary:
        return "Electricity consumed, including losses, is not the generation-only Scope 2 factor."
    if "market" in _norm(attributes.get("method")) or "market" in _norm(attributes.get("boundary")):
        return "A market-based electricity factor is not used for this location-based total."
    if "water" in _norm(row.label) or "water" in _norm(attributes.get("boundary")):
        return "A combined electricity and water factor is not a purchased-electricity factor."
    return None


def _unit_kg_co2e_per_kwh(row: FactorRow) -> Optional[Decimal]:
    compact = _norm(row.unit).replace(" ", "")
    if compact in {"kgco2e/kwh", "kgco2eperkwh"}:
        return _decimal(row.kg_co2e)
    if compact in {"tco2e/mwh", "tco2epermwh"}:
        # 1 t CO2e/MWh is the same intensity as 1 kg CO2e/kWh.
        return _decimal(row.kg_co2e)
    return None


def _candidate_failure(row: FactorRow, dataset: FactorDataset) -> Optional[str]:
    if _norm(row.category) != CATEGORY:
        return None
    attributes = row.attributes or {}
    if _norm(attributes.get("verification")) != "verified":
        return "verification is not verified"
    if _norm(attributes.get("method")) != LOCATION_METHOD:
        return "method is not location-based"
    if _norm(attributes.get("boundary")) not in GENERATION_BOUNDARIES:
        return "boundary is not generation-only purchased electricity"
    if not _text(dataset.publisher) or _norm(dataset.publisher) in {"legacy", "placeholder", "unverified"}:
        return "publisher is missing"
    if not _text(attributes.get("source_document")):
        return "source document is missing"
    if "co2e" not in _norm(attributes.get("gas_coverage")):
        return "gas coverage is not complete CO2e"
    if _year(attributes.get("publication_year")) is None:
        return "publication year is missing"
    if _year(attributes.get("reporting_year")) is None:
        return "reporting year is missing"
    if not _text(attributes.get("country")) or not _text(attributes.get("grid_region")):
        return "country or grid region is missing"
    if _unit_kg_co2e_per_kwh(row) is None:
        return "unit is not kg CO2e/kWh"
    source_error = _rejected_source(row, dataset)
    if source_error:
        return source_error
    return ""


def _geography_error(kind: str, grid_region: str, factor: Decimal, dataset: FactorDataset, reporting_year: int, publication_year: int) -> Optional[str]:
    publisher = _norm(dataset.publisher)
    if any(_same(factor, banned) for banned in REJECTED_PLACEHOLDERS):
        return "This stored value is an undocumented placeholder and was not used."
    if kind == "uk":
        if _norm(grid_region) not in UK_GRIDS:
            return (
                "The DESNZ national generation factor applies to the UK grid. "
                f"No verified factor is stored for grid region {_text(grid_region)}."
            )
        if "desnz" not in publisher and "energy security" not in publisher:
            return "A UK electricity factor must be published by DESNZ."
        expected = UK_GENERATION_KG.get(reporting_year)
        if expected is None:
            return (
                f"No DESNZ generation-only electricity edition is confirmed for reporting year {reporting_year}. "
                "A result was not calculated."
            )
        if publication_year != reporting_year or not _same(factor, expected):
            return (
                f"The stored UK factor does not match the DESNZ {reporting_year} generation-only "
                "Scope 2 factor. A result was not calculated."
            )
        return None
    if any(_same(factor, official) for official in UK_GENERATION_KG.values()) or _same(factor, Decimal("0.17529")):
        return "A UK DESNZ factor was not applied outside the United Kingdom."
    if kind == "uae":
        if _norm(grid_region) not in DUBAI_GRIDS:
            return (
                "A DEWA electricity factor applies only to the Dubai grid and the reporting year it was published for. "
                "It was not applied to another UAE grid."
            )
        if "dewa" not in publisher:
            return "A Dubai electricity factor must be published by DEWA."
        if publication_year != reporting_year:
            return "The DEWA factor publication year does not match the reporting year. A result was not calculated."
        return None
    if kind == "pakistan":
        return None
    return None


def resolve_uk_location_factor(
    db: Session,
    *,
    country: str,
    grid_region: str,
    reporting_year: int,
) -> Dict[str, Any]:
    kind = _country_kind(country)
    region = _text(grid_region or "national")
    if not _text(country):
        return {"ok": False, "status": "missing_factor", "error": "Electricity grid country is required."}
    if not region:
        return {"ok": False, "status": "missing_factor", "error": "Electricity grid region is required."}

    matched: List[Tuple[FactorRow, FactorDataset, Decimal]] = []
    rejection: Optional[str] = None
    for row, dataset in _row_pairs(db):
        if not dataset.is_active:
            continue
        failure = _candidate_failure(row, dataset)
        if failure is None or failure != "":
            if failure:
                rejection = rejection or failure
            continue
        attributes = row.attributes or {}
        if _country_kind(_text(attributes.get("country"))) != kind and _norm(attributes.get("country")) != _norm(country):
            continue
        if kind == "other" and _norm(attributes.get("country")) != _norm(country):
            continue
        if _norm(attributes.get("grid_region")) != _norm(region):
            continue
        if _year(attributes.get("reporting_year")) != reporting_year:
            continue
        if not _covers_year(dataset, reporting_year):
            continue
        factor = _unit_kg_co2e_per_kwh(row)
        publication_year = _year(attributes.get("publication_year"))
        if factor is None or publication_year is None:
            continue
        geography = _geography_error(kind, region, factor, dataset, reporting_year, publication_year)
        if geography:
            rejection = geography
            continue
        matched.append((row, dataset, factor))

    if not matched:
        detail = rejection or (
            f"No verified generation-only purchased-electricity factor is stored for "
            f"{_text(country)}, grid region {region}, reporting year {reporting_year}."
        )
        return {"ok": False, "status": "missing_factor", "error": f"{detail} A result was not calculated."}
    if len(matched) > 1:
        return {
            "ok": False,
            "status": "ambiguous_factor",
            "error": (
                f"More than one verified electricity factor matches {_text(country)}, {region}, {reporting_year}. "
                "A result was not calculated."
            ),
        }

    row, dataset, factor = matched[0]
    return {"ok": True, "factor_per_kwh": factor, "row": row, "dataset": dataset}


def _quantity_kwh(quantity: Any, unit: str) -> Tuple[Optional[Decimal], Optional[str]]:
    number = _decimal(quantity)
    if number is None or number < 0:
        return None, "Electricity quantity must be zero or a positive number."
    kind = _norm(unit)
    if kind == "kwh":
        return number, None
    if kind == "mwh":
        return number * _KWH_PER_MWH, None
    return None, "Electricity unit must be kWh or MWh."


def calculate_uk_location_electricity(
    db: Session,
    *,
    country: str,
    quantity: Any,
    unit: str,
    period: str,
    grid_region: str = "national",
    renewable_kwh: Any = None,
    grid_factor: Any = None,
    emissions_tco2e: Any = None,
    other_pct: Any = None,
    other_row_emissions_sum: Any = None,
) -> Dict[str, Any]:
    """Client factors, totals, and other-source fuel masses are ignored."""
    del grid_factor, emissions_tco2e, other_pct, other_row_emissions_sum
    text = _text(period)
    if (
        len(text) != 7
        or text[4] != "-"
        or not (text[:4].isdigit() and text[5:].isdigit())
        or not 1 <= int(text[5:]) <= 12
        or not 1990 <= int(text[:4]) <= 2200
    ):
        return {"ok": False, "status": "invalid_period", "error": "period must be YYYY-MM"}

    kwh, quantity_error = _quantity_kwh(quantity, unit)
    if quantity_error or kwh is None:
        return {"ok": False, "status": "invalid_quantity", "error": quantity_error}

    renewable = None
    if renewable_kwh is not None and _text(renewable_kwh) != "":
        renewable = _decimal(renewable_kwh)
        if renewable is None or renewable < 0:
            return {
                "ok": False,
                "status": "invalid_quantity",
                "error": "Contractual renewable electricity must be zero or a positive number of kWh.",
            }

    resolved = resolve_uk_location_factor(
        db,
        country=country,
        grid_region=grid_region,
        reporting_year=int(text[:4]),
    )
    if not resolved.get("ok"):
        return resolved

    factor: Decimal = resolved["factor_per_kwh"]
    row: FactorRow = resolved["row"]
    dataset: FactorDataset = resolved["dataset"]
    attributes = row.attributes or {}
    mass_kg = kwh * factor
    tonnes = mass_kg / _TONNE
    provenance = {
        "dataset_id": str(dataset.id),
        "dataset_code": dataset.code,
        "factor_row_id": str(row.id),
        "publisher": dataset.publisher,
        "source_document": _text(attributes.get("source_document")),
        "publication_year": _year(attributes.get("publication_year")),
        "version_label": dataset.version_label,
        "reporting_year": int(text[:4]),
        "country": _text(attributes.get("country")),
        "grid_region": _text(attributes.get("grid_region")),
        "boundary": _text(attributes.get("boundary")),
        "method": LOCATION_METHOD,
        "unit": "kg CO2e/kWh",
        "value": _quantize(factor),
        "gas_coverage": _text(attributes.get("gas_coverage")),
    }
    return {
        "ok": True,
        "save_allowed": True,
        "status": "verified",
        "country": _text(country),
        "grid_region": _text(grid_region or "national"),
        "period": text,
        "quantity": _quantize(_decimal(quantity) or Decimal("0")),
        "unit": "kWh" if _norm(unit) == "kwh" else "MWh",
        "electricity_kwh": _quantize(kwh),
        "renewable_kwh": None if renewable is None else _quantize(renewable),
        "renewable_applied": False,
        "on_site_fuel_included": False,
        "factor": provenance,
        "gases": {"co2e": {"mass_kg": _quantize(mass_kg), "coverage": provenance["gas_coverage"]}},
        "total_kg_co2e": _quantize(mass_kg),
        "total_t_co2e": _quantize(tonnes),
        "methodology": (
            "GHG Protocol Scope 2 location-based. Purchased electricity is multiplied by the stored "
            "generation-only grid factor for the selected grid and reporting year. Contractual renewable "
            "electricity is not deducted. Fuel burned by the organisation is Scope 1 and is not included."
        ),
        "accounting": {"version": ACCOUNTING_VERSION, "method": LOCATION_METHOD, "status": "verified"},
        "error": None,
    }
