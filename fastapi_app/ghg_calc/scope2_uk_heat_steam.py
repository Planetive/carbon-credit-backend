"""
Purchased heat and steam for the UK calculator.

The factor is one stored kg CO2e per kWh value. It is not split into CO2, CH4,
or N2O, and 0.17355 is not used as a fallback. Client factors are ignored.

United Kingdom, reporting years 2025 and 2026, accept only the DESNZ purchased
district heat and steam total of 0.17529 kg CO2e/kWh. The 2026 methodology
paper, paragraph 3.25, holds the heat and steam factors at the 2025 release.
Well-to-tank and district distribution losses stay out of this Scope 2 total.

That UK factor is not applied to Pakistan or any other country. A country
without its own verified purchased-heat row returns a missing factor.
EPA Table 7 steam factors, in kg or grams per mmBtu, are rejected here.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from ..factor_models import FactorDataset, FactorRow

ACCOUNTING_VERSION = "scope2_uk_purchased_heat_steam_v1"
CATEGORY = "purchased_heat_steam"
METHOD = "purchased_energy"
ACCEPTED_BOUNDARIES = {"district_heat", "purchased_heat", "purchased_heat_steam"}
ENERGY_FORMS = {
    "purchased_heat": "purchased_heat",
    "purchased heat": "purchased_heat",
    "district heat": "purchased_heat",
    "purchased_steam": "purchased_steam",
    "purchased steam": "purchased_steam",
    "district steam": "purchased_steam",
}
UK_HEAT_KG = {
    2025: Decimal("0.17529"),
    2026: Decimal("0.17529"),
}
_TONNE = Decimal("1000")
_QUANT = Decimal("0.00000001")
_MATCH = Decimal("0.00001")
_KWH_PER_MWH = Decimal("1000")
UK_NAMES = {"uk", "u.k.", "united kingdom", "great britain", "britain", "gb"}
PAKISTAN_NAMES = {"pakistan", "pk"}


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


def _energy_form(value: str) -> Optional[str]:
    key = _norm(value)
    if any(token in key for token in ("onsite", "on site", "on-site", "combustion")):
        return None
    return ENERGY_FORMS.get(key)


def _candidate_failure(row: FactorRow, dataset: FactorDataset) -> Optional[str]:
    if _norm(row.category) != CATEGORY:
        return None
    attributes = row.attributes or {}
    blob = " ".join(
        _norm(part)
        for part in (
            dataset.publisher,
            dataset.code,
            row.label,
            row.unit,
            attributes.get("source_document"),
            attributes.get("boundary"),
        )
    )
    if "heat_and_steam_ebt" in blob or "us epa" in blob or "mmbtu" in blob:
        return "An EPA steam factor cannot be used as a DESNZ heat factor."
    if _norm(attributes.get("verification")) != "verified":
        return "verification is not verified"
    if _norm(attributes.get("method")) != METHOD:
        return "method is not purchased energy"
    if _norm(attributes.get("boundary")) not in ACCEPTED_BOUNDARIES:
        return "boundary is not purchased district heat or steam"
    if any(token in _norm(attributes.get("boundary")) for token in ("wtt", "distribution", "transmission")):
        return "Well-to-tank and distribution losses are outside this Scope 2 factor."
    if not _text(dataset.publisher) or _norm(dataset.publisher) in {"legacy", "placeholder", "unverified"}:
        return "publisher is missing"
    if not _text(attributes.get("source_document")):
        return "source document is missing"
    if "co2e" not in _norm(attributes.get("gas_coverage")):
        return "gas coverage is not complete CO2e"
    if _year(attributes.get("publication_year")) is None or _year(attributes.get("reporting_year")) is None:
        return "publication year or reporting year is missing"
    if not _text(attributes.get("country")):
        return "country is missing"
    compact = _norm(row.unit).replace(" ", "")
    if compact not in {"kgco2e/kwh", "kgco2eperkwh"}:
        return "unit is not kg CO2e/kWh"
    factor = _decimal(row.kg_co2e)
    if factor is None:
        return "kg CO2e value is missing"
    if _same(factor, Decimal("0.17355")):
        return "0.17355 kg CO2/kWh is the CO2 component, not the CO2e factor."
    return ""


def resolve_uk_heat_factor(db: Session, *, country: str, reporting_year: int) -> Dict[str, Any]:
    kind = _country_kind(country)
    if not _text(country):
        return {"ok": False, "status": "missing_factor", "error": "The heat supplier country is required."}

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
        row_kind = _country_kind(_text(attributes.get("country")))
        if row_kind != kind or (kind == "other" and _norm(attributes.get("country")) != _norm(country)):
            continue
        if _year(attributes.get("reporting_year")) != reporting_year:
            continue
        if not _covers_year(dataset, reporting_year):
            continue
        factor = _decimal(row.kg_co2e)
        publication_year = _year(attributes.get("publication_year"))
        if factor is None or publication_year is None:
            continue
        publisher = _norm(dataset.publisher)
        if kind == "uk":
            expected = UK_HEAT_KG.get(reporting_year)
            if expected is None:
                rejection = (
                    f"No DESNZ purchased heat and steam edition is confirmed for reporting year {reporting_year}."
                )
                continue
            if "desnz" not in publisher and "energy security" not in publisher:
                rejection = "A UK heat factor must be published by DESNZ."
                continue
            if publication_year != reporting_year or not _same(factor, expected):
                rejection = (
                    f"The stored UK heat factor does not match the DESNZ {reporting_year} "
                    "purchased heat and steam CO2e factor."
                )
                continue
        elif _same(factor, Decimal("0.17529")):
            rejection = "The UK district heat factor was not applied to this supplier country."
            continue
        matched.append((row, dataset, factor))

    if not matched:
        detail = rejection or (
            f"No verified purchased heat or steam factor is stored for {_text(country)}, reporting year {reporting_year}."
        )
        return {"ok": False, "status": "missing_factor", "error": f"{detail} A result was not calculated."}
    if len(matched) > 1:
        return {
            "ok": False,
            "status": "ambiguous_factor",
            "error": "More than one verified heat factor matches this country and year. A result was not calculated.",
        }
    row, dataset, factor = matched[0]
    return {"ok": True, "factor_per_kwh": factor, "row": row, "dataset": dataset}


def calculate_uk_purchased_heat_steam(
    db: Session,
    *,
    country: str,
    energy_form: str,
    quantity: Any,
    unit: str,
    period: str,
    supplier_name: Optional[str] = None,
    co2_factor: Any = None,
    ch4_factor: Any = None,
    n2o_factor: Any = None,
    emission_factor: Any = None,
    emissions_tco2e: Any = None,
) -> Dict[str, Any]:
    del co2_factor, ch4_factor, n2o_factor, emission_factor, emissions_tco2e
    form = _energy_form(energy_form)
    if form is None:
        return {
            "ok": False,
            "status": "onsite_combustion",
            "error": "On-site fuel combustion is Scope 1. Enter purchased heat or purchased steam.",
        }
    text = _text(period)
    if (
        len(text) != 7
        or text[4] != "-"
        or not (text[:4].isdigit() and text[5:].isdigit())
        or not 1 <= int(text[5:]) <= 12
        or not 1990 <= int(text[:4]) <= 2200
    ):
        return {"ok": False, "status": "invalid_period", "error": "period must be YYYY-MM"}

    number = _decimal(quantity)
    if number is None or number < 0:
        return {"ok": False, "status": "invalid_quantity", "error": "Heat quantity must be zero or a positive number."}
    unit_key = _norm(unit)
    if unit_key == "kwh":
        kwh = number
        display_unit = "kWh"
    elif unit_key == "mwh":
        kwh = number * _KWH_PER_MWH
        display_unit = "MWh"
    else:
        return {"ok": False, "status": "invalid_quantity", "error": "Purchased heat unit must be kWh or MWh."}

    resolved = resolve_uk_heat_factor(db, country=country, reporting_year=int(text[:4]))
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
        "boundary": _text(attributes.get("boundary")),
        "method": METHOD,
        "unit": "kg CO2e/kWh",
        "value": _quantize(factor),
        "gas_coverage": _text(attributes.get("gas_coverage")),
        "treatment": "complete_co2e",
    }
    return {
        "ok": True,
        "save_allowed": True,
        "status": "verified",
        "country": _text(country),
        "energy_form": form,
        "supplier_name": _text(supplier_name),
        "period": text,
        "quantity": _quantize(number),
        "unit": display_unit,
        "energy_kwh": _quantize(kwh),
        "factor": provenance,
        "gases": {"co2e": {"mass_kg": _quantize(mass_kg), "coverage": provenance["gas_coverage"]}},
        "total_kg_co2e": _quantize(mass_kg),
        "total_t_co2e": _quantize(tonnes),
        "methodology": (
            "Purchased heat or steam is multiplied by the stored complete kg CO2e per kWh factor "
            "for the supplier country and reporting year. The factor is not split into separate gases. "
            "On-site combustion, distribution losses, and well-to-tank fuel are not included."
        ),
        "accounting": {"version": ACCOUNTING_VERSION, "method": METHOD, "status": "verified"},
        "error": None,
    }
