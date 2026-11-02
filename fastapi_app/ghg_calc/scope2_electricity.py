"""
Location-based purchased electricity.

The factor is read from ref.factor_rows. A client number is never accepted.
A row is usable only when its stored metadata says it is a verified
location-based purchased-electricity factor for the requested country, grid
region, and reporting year. No Pakistan, UAE, or IGCEP value is hardcoded here.

DESNZ electricity generated is the UK Scope 2 factor and is selected by the UK
engine. It is not accepted here. The stored boundary stays electricity_generated.
Accepting that token, or generation, would also admit generation-intensity rows.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from ..factor_models import FactorDataset, FactorRow

ACCOUNTING_VERSION = "scope2_location_electricity_v1"
CATEGORY = "purchased_electricity"
LOCATION_METHOD = "location_based"
ACCEPTED_BOUNDARIES = {"consumption", "purchased_electricity"}
REJECTED_PUBLISHERS = {"", "legacy", "placeholder", "unverified"}
_TONNE = Decimal("1000")
_QUANT = Decimal("0.00000001")
_KWH_PER_MWH = Decimal("1000")


def _text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def _norm(value: Any) -> str:
    return _text(value).lower()


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


def _unit_kind(unit: Any) -> Optional[str]:
    compact = _norm(unit).replace(" ", "")
    if compact in {"kgco2e/kwh", "kgco2eperkwh"}:
        return "co2e"
    if compact in {"kgco2/kwh", "kgco2perkwh"}:
        return "co2"
    return None


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


def _quantize(value: Decimal) -> str:
    return format(value.quantize(_QUANT), "f")


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


def _candidate_failure(row: FactorRow, dataset: FactorDataset) -> Optional[str]:
    """None when the row is not a purchased-electricity candidate. Otherwise a reason it is unverified."""
    if _norm(row.category) != CATEGORY:
        return None
    attributes = row.attributes or {}
    if _norm(attributes.get("verification")) != "verified":
        return "verification is not verified"
    if _norm(attributes.get("method")) != LOCATION_METHOD:
        return "method is not location-based"
    if _norm(attributes.get("boundary")) not in ACCEPTED_BOUNDARIES:
        return "boundary is not purchased electricity consumption"
    if _norm(dataset.publisher) in REJECTED_PUBLISHERS:
        return "publisher is missing"
    if not _text(attributes.get("source_document")):
        return "source document is missing"
    if not _text(attributes.get("gas_coverage")):
        return "gas coverage is missing"
    if _year(attributes.get("publication_year")) is None:
        return "publication year is missing"
    if _year(attributes.get("reporting_year")) is None:
        return "reporting year is missing"
    if not _text(attributes.get("country")) or not _text(attributes.get("grid_region")):
        return "country or grid region is missing"
    if _unit_kind(row.unit) is None:
        return "unit is not kg CO2e/kWh or kg CO2/kWh"
    return ""


def resolve_location_factor(
    db: Session,
    *,
    country: str,
    grid_region: str,
    reporting_year: int,
) -> Dict[str, Any]:
    country_key = _norm(country)
    region_key = _norm(grid_region or "national")
    if not country_key:
        return {"ok": False, "status": "missing_factor", "error": "Electricity grid country is required."}
    if not region_key:
        return {"ok": False, "status": "missing_factor", "error": "Electricity grid region is required."}

    matched: List[Tuple[FactorRow, FactorDataset]] = []
    for row, dataset in _row_pairs(db):
        if not dataset.is_active:
            continue
        failure = _candidate_failure(row, dataset)
        if failure is None or failure != "":
            continue
        attributes = row.attributes or {}
        if _norm(attributes.get("country")) != country_key:
            continue
        if _norm(attributes.get("grid_region")) != region_key:
            continue
        if _year(attributes.get("reporting_year")) != reporting_year:
            continue
        if not _covers_year(dataset, reporting_year):
            continue
        matched.append((row, dataset))

    if not matched:
        return {
            "ok": False,
            "status": "missing_factor",
            "error": (
                f"No verified location-based purchased-electricity factor is stored for "
                f"{_text(country)}, grid region {_text(grid_region) or 'national'}, reporting year {reporting_year}. "
                "A result was not calculated."
            ),
        }
    if len(matched) > 1:
        return {
            "ok": False,
            "status": "ambiguous_factor",
            "error": (
                f"More than one verified electricity factor matches {_text(country)}, "
                f"{_text(grid_region) or 'national'}, {reporting_year}. A result was not calculated."
            ),
        }

    row, dataset = matched[0]
    attributes = row.attributes or {}
    kind = _unit_kind(row.unit)
    if kind == "co2e":
        factor = _decimal(row.kg_co2e)
        if factor is None or factor < 0:
            return {
                "ok": False,
                "status": "unverified_factor",
                "error": "The matched factor has no kg CO2e per kWh value. A result was not calculated.",
            }
        if "co2e" not in _norm(attributes.get("gas_coverage")):
            return {
                "ok": False,
                "status": "unverified_factor",
                "error": "The factor unit is CO2e but the stored gas coverage does not say CO2e. A result was not calculated.",
            }
    else:
        factor = _decimal(row.kg_co2)
        coverage = _norm(attributes.get("gas_coverage"))
        if factor is None or factor < 0 or "co2e" in coverage:
            return {
                "ok": False,
                "status": "unverified_factor",
                "error": "The matched CO2 factor cannot be reported as CO2e. A result was not calculated.",
            }
        kind = "co2"

    return {
        "ok": True,
        "kind": kind,
        "factor_per_kwh": factor,
        "row": row,
        "dataset": dataset,
    }


def calculate_location_electricity(
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
) -> Dict[str, Any]:
    """Client grid_factor and emissions_tco2e are ignored."""
    del grid_factor, emissions_tco2e
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

    resolved = resolve_location_factor(
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
    kind = resolved["kind"]
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
        "unit": _text(row.unit),
        "value": _quantize(factor),
        "gas_coverage": _text(attributes.get("gas_coverage")),
    }
    gases: Dict[str, Any] = {}
    if kind == "co2e":
        gases["co2e"] = {"mass_kg": _quantize(mass_kg), "coverage": provenance["gas_coverage"]}
        for gas, column in (("co2", row.kg_co2), ("ch4", row.kg_ch4), ("n2o", row.kg_n2o)):
            per_kwh = _decimal(column)
            if per_kwh is None:
                continue
            gases[gas] = {"mass_kg": _quantize(kwh * per_kwh), "per_kwh": _quantize(per_kwh)}
    else:
        gases["co2"] = {
            "mass_kg": _quantize(mass_kg),
            "coverage": provenance["gas_coverage"],
            "reported_as": "CO2",
        }

    base = {
        "ok": True,
        "country": _text(country),
        "grid_region": _text(grid_region or "national"),
        "period": text,
        "quantity": _quantize(_decimal(quantity) or Decimal("0")),
        "unit": "kWh" if _norm(unit) == "kwh" else "MWh",
        "electricity_kwh": _quantize(kwh),
        "renewable_kwh": None if renewable is None else _quantize(renewable),
        "renewable_applied": False,
        "factor": provenance,
        "gases": gases,
        "methodology": (
            "GHG Protocol Scope 2 location-based. "
            "Purchased electricity is multiplied by the stored grid-average factor. "
            "Contractual renewable electricity is not deducted."
        ),
        "accounting": {
            "version": ACCOUNTING_VERSION,
            "method": LOCATION_METHOD,
            "status": "verified" if kind == "co2e" else "disclosed_co2_not_co2e",
        },
    }
    if kind == "co2":
        return {
            **base,
            "save_allowed": False,
            "status": "disclosed_co2_not_co2e",
            "total_t_co2": _quantize(tonnes),
            "total_t_co2e": None,
            "error": (
                "This factor is kg CO2 per kWh, not kg CO2e per kWh. "
                f"The CO2 mass is {_quantize(tonnes)} t CO2. It was not reported as tCO2e and cannot be saved as verified."
            ),
        }
    return {
        **base,
        "save_allowed": True,
        "status": "verified",
        "total_kg_co2e": _quantize(mass_kg),
        "total_t_co2e": _quantize(tonnes),
        "error": None,
    }
