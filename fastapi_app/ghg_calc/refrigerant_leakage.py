"""
Backend-authoritative EPA Scope 1 refrigerant leakage.

Accounting version epa_refrigerant_v1. One leaked refrigerant mass becomes
Scope 1 tonnes of CO2e. The caller cannot supply a GWP or a total.

Blends are read from dataset code ``epa_refrigerant_gwp`` only:
attribute ``ASHRAE #`` is the name and ``100-year GWP`` is the factor.
Commas and surrounding whitespace in that text are ignored. ``kg_co2e`` is
not a GWP. UK refrigerant factors are never read. A missing, duplicate,
zero, or unreadable factor fails the calculation. No frontend map is
substituted.

Only these Table 12 blends are eligible. Other blend rows, including
HCFC/CFC mixtures and zero-GWP records, are rejected even when the sheet
contains them:

R-404A, R-407A, R-407B, R-407C, R-407D, R-410A, R-410B, R-417A, R-422A,
R-422D, R-424A, R-426A, R-428A, R-434A, R-507A, R-508A, R-508B.

Pure HFCs use an explicit EPA Hub Table 11 allowlist (IPCC AR5, 100-year).
Those values are not factor-row records and do not require
``epa_refrigerant_gwp`` to be present. Aliases are only the documented
ones. CO2, CH4, N2O, SF6, NF3, pure PFCs, R-22, R-12, and R-502 are refused.

Measured leakage is leaked kilograms times GWP, divided by 1000.
Estimated leakage is charge kilograms times a user-entered rate, then the
same conversion. The server never inserts a default rate. A missing rate
is not zero. An entered zero is a real estimate of no leakage.
``leakage_rate_source`` is ``user_assumption`` and is not an EPA factor.

This module does not write activities and does not change stationary
combustion, mobile combustion, flaring, or venting.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

ACCOUNTING_VERSION = "epa_refrigerant_v1"
DATASET_CODE = "epa_refrigerant_gwp"
GWP_ATTRIBUTE = "100-year GWP"
NAME_ATTRIBUTE = "ASHRAE #"
COMPOSITION_ATTRIBUTE = "Blend Composition"

EDITION = (
    "IPCC AR5 100-year GWP, Table 8.A.1 (2013), as republished by the "
    "EPA GHG Emission Factors Hub"
)
TABLE_12_PUBLICATION = (
    "EPA GHG Emission Factors Hub, Table 12, document last modified 05 June 2024"
)
TABLE_11_PUBLICATION = (
    "EPA GHG Emission Factors Hub, Table 11, document last modified 05 June 2024"
)
TABLE_11_REFERENCE = (
    "EPA GHG Emission Factors Hub Table 11 allowlist (IPCC AR5 100-year, "
    "Table 8.A.1). This value is not a ref.factor_rows record."
)
TABLE_12_BASIS = (
    "Published EPA Table 12 accounting factor for HFC and PFC constituents. "
    "It is not a separate physical-warming model of every constituent."
)
HYDROCARBON_BASIS = (
    "This blend's published EPA Table 12 accounting factor does not add a "
    "separate physical warming contribution for its hydrocarbon constituents."
)

METHODOLOGY = (
    "EPA GHG Emission Factors Hub 2024, Tables 11 and 12, using IPCC AR5 "
    "100-year GWP. Measured leakage is leaked refrigerant kilograms times GWP, "
    "divided by 1000, in Scope 1 tonnes CO2e. Estimated leakage multiplies "
    "equipment charge kilograms by a user-entered annual leakage rate before "
    "that conversion. The rate is a user assumption, not an EPA-published "
    "factor, and no default rate is applied. Blend GWPs come only from dataset "
    "epa_refrigerant_gwp. Pure HFC GWPs come from the Table 11 allowlist and "
    "are not database rows. UK factors and caller-supplied GWPs are not used."
)

_THOUSAND = Decimal("1000")
_HUNDRED = Decimal("100")

# Names only. The GWP number is read from the factor row.
_SUPPORTED_BLENDS = frozenset(
    {
        "r-404a",
        "r-407a",
        "r-407b",
        "r-407c",
        "r-407d",
        "r-410a",
        "r-410b",
        "r-417a",
        "r-422a",
        "r-422d",
        "r-424a",
        "r-426a",
        "r-428a",
        "r-434a",
        "r-507a",
        "r-508a",
        "r-508b",
    }
)

_HCFC_OR_CFC_BLENDS = {
    "r-401a": "R-401A",
    "r-401b": "R-401B",
    "r-401c": "R-401C",
    "r-402a": "R-402A",
    "r-402b": "R-402B",
    "r-403b": "R-403B",
    "r-408a": "R-408A",
    "r-411a": "R-411A",
    "r-411b": "R-411B",
}

_ZERO_GWP_BLENDS = {
    "r-406a": "R-406A",
    "r-409a": "R-409A",
    "r-414a": "R-414A",
    "r-414b": "R-414B",
}

_EXCLUDED = {
    "co2": "CO2",
    "carbon dioxide": "CO2",
    "ch4": "CH4",
    "methane": "CH4",
    "n2o": "N2O",
    "nitrous oxide": "N2O",
    "sf6": "SF6",
    "sulfur hexafluoride": "SF6",
    "sulphur hexafluoride": "SF6",
    "nf3": "NF3",
    "nitrogen trifluoride": "NF3",
    "r-22": "R-22",
    "hcfc-22": "R-22",
    "r-12": "R-12",
    "cfc-12": "R-12",
    "r-502": "R-502",
    "pfc-14": "PFC-14",
    "cf4": "PFC-14",
    "pfc-116": "PFC-116",
    "c2f6": "PFC-116",
    "pfc-218": "PFC-218",
    "c3f8": "PFC-218",
    "pfc-318": "PFC-318",
    "c-c4f8": "PFC-318",
    "pfc-3-1-10": "PFC-3-1-10",
    "c4f10": "PFC-3-1-10",
    "pfc-4-1-12": "PFC-4-1-12",
    "c5f12": "PFC-4-1-12",
    "pfc-5-1-14": "PFC-5-1-14",
    "c6f14": "PFC-5-1-14",
    "pfc-9-1-18": "PFC-9-1-18",
    "c10f18": "PFC-9-1-18",
    "perfluorocyclopropane": "perfluorocyclopropane",
    "c-c3f6": "perfluorocyclopropane",
}

# Canonical name, AR5 100-year GWP, documented aliases.
_PURE_SPECS: Tuple[Tuple[str, str, Tuple[str, ...]], ...] = (
    ("HFC-23", "12400", ()),
    ("HFC-32", "677", ("R-32",)),
    ("HFC-41", "116", ()),
    ("HFC-125", "3170", ("R-125",)),
    ("HFC-134", "1120", ()),
    ("HFC-134a", "1300", ("R-134a",)),
    ("HFC-143", "328", ()),
    ("HFC-143a", "4800", ("R-143a",)),
    ("HFC-152", "16", ()),
    ("HFC-152a", "138", ("R-152a",)),
    ("HFC-161", "4", ()),
    ("HFC-227ea", "3350", ()),
    ("HFC-236cb", "1210", ()),
    ("HFC-236ea", "1330", ()),
    ("HFC-236fa", "8060", ()),
    ("HFC-245ca", "716", ()),
    ("HFC-245fa", "858", ()),
    ("HFC-365mfc", "804", ()),
    ("HFC-43-10mee", "1650", ("HFC-43-I0mee",)),
)

_HYDROCARBON_TOKENS = ("isopentane", "isobutane", "butane", "propane")


def _normalize_name(value: Any) -> str:
    text = " ".join(str(value if value is not None else "").strip().casefold().split())
    text = text.replace("–", "-").replace("—", "-")
    text = text.replace(" - ", "-").replace(" -", "-").replace("- ", "-")
    return text


def _pure_index() -> Dict[str, Tuple[str, Decimal]]:
    index: Dict[str, Tuple[str, Decimal]] = {}
    for canonical, gwp_text, aliases in _PURE_SPECS:
        record = (canonical, Decimal(gwp_text))
        index[_normalize_name(canonical)] = record
        for alias in aliases:
            index[_normalize_name(alias)] = record
    return index


_PURE = _pure_index()


def _normalize_key(value: Any) -> str:
    return " ".join(str(value).casefold().replace("_", " ").split())


def _parse_decimal(value: Any) -> Optional[Decimal]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        if not value.is_finite():
            return None
        return value
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (value != value or abs(value) == float("inf")):
            return None
        try:
            parsed = Decimal(str(value))
        except InvalidOperation:
            return None
        return None if not parsed.is_finite() else parsed
    text = str(value).replace(",", "").strip()
    if not text:
        return None
    try:
        parsed = Decimal(text)
    except InvalidOperation:
        return None
    return None if not parsed.is_finite() else parsed


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _empty_result(**extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "success": False,
        "method": None,
        "refrigerant": None,
        "leakage_kg": None,
        "charge_kg": None,
        "leakage_rate_percent": None,
        "leakage_rate_source": None,
        "equipment_type": None,
        "gwp": None,
        "dataset_id": None,
        "factor_row_id": None,
        "dataset_code": None,
        "version_label": None,
        "factor_attribute": None,
        "gwp_publication": None,
        "gwp_edition": None,
        "factor_provenance": None,
        "gwp_basis": None,
        "table11_reference": None,
        "emissions_kg_co2e": None,
        "emissions_tco2e": None,
        "accounting": {
            "version": ACCOUNTING_VERSION,
            "methodology": METHODOLOGY,
        },
    }
    payload.update(extra)
    return payload


def _fail(message: str, **extra: Any) -> Dict[str, Any]:
    payload = _empty_result(**extra)
    payload["error"] = message
    return payload


def _attribute(row: Mapping[str, Any], canonical_key: str) -> Tuple[Optional[str], Any]:
    """Return the original key and value for one attribute. Conflicting duplicates fail."""
    want = _normalize_key(canonical_key)
    found: List[Tuple[str, Any]] = []
    for raw_key, value in row.items():
        if str(raw_key).startswith("_"):
            continue
        if _normalize_key(raw_key) == want:
            found.append((str(raw_key), value))
    if not found:
        return None, None
    if len(found) > 1:
        values = {repr(item[1]) for item in found}
        if len(values) > 1:
            return None, None
    return found[0]


def _composition_has_hydrocarbon(composition: Any) -> bool:
    text = _normalize_name(composition)
    return any(token in text for token in _HYDROCARBON_TOKENS)


def _active_blend_sheets(
    sheets: Sequence[Mapping[str, Any]],
) -> Tuple[Optional[Mapping[str, Any]], Optional[str]]:
    matches = []
    for sheet in sheets:
        if not isinstance(sheet, Mapping):
            return None, (
                "epa_refrigerant_gwp factor sheet is malformed. "
                "No other factor edition is substituted."
            )
        if _normalize_name(sheet.get("dataset_code")) != DATASET_CODE:
            continue
        if sheet.get("is_active") is False:
            continue
        matches.append(sheet)
    if not matches:
        return None, (
            "Authoritative dataset epa_refrigerant_gwp is missing or inactive. "
            "No other factor edition is substituted."
        )
    errors = [sheet.get("load_error") for sheet in matches if sheet.get("load_error")]
    if errors:
        return None, str(errors[0])
    if len(matches) > 1:
        return None, (
            "More than one active epa_refrigerant_gwp dataset is loaded. "
            "No factor edition is selected automatically."
        )
    return matches[0], None


def load_refrigerant_factor_sheets(db: Any) -> List[Dict[str, Any]]:
    """Read the one active epa_refrigerant_gwp dataset. UK factors are not queried."""
    from sqlalchemy import func

    from ..factor_models import FactorDataset
    from ..factor_service import factor_row_to_legacy_record, fetch_all_rows_for_dataset

    datasets = (
        db.query(FactorDataset)
        .filter(func.lower(FactorDataset.code) == DATASET_CODE)
        .filter(FactorDataset.is_active.is_(True))
        .all()
    )
    if len(datasets) != 1:
        message = (
            "Authoritative dataset epa_refrigerant_gwp is missing or inactive. "
            "No other factor edition is substituted."
            if len(datasets) == 0
            else (
                "More than one active epa_refrigerant_gwp dataset is loaded. "
                "No factor edition is selected automatically."
            )
        )
        return [
            {
                "dataset_code": DATASET_CODE,
                "is_active": True,
                "load_error": message,
                "rows": [],
            }
        ]

    dataset = datasets[0]
    rows = []
    for factor_row in fetch_all_rows_for_dataset(db, dataset.id):
        legacy = factor_row_to_legacy_record(factor_row)
        legacy["_factor_row_id"] = str(factor_row.id)
        legacy["_factor_dataset_id"] = str(dataset.id)
        rows.append(legacy)
    return [
        {
            "dataset_code": str(dataset.code),
            "dataset_id": str(dataset.id),
            "publisher": dataset.publisher,
            "title": dataset.title,
            "version_label": dataset.version_label,
            "source_notes": dataset.source_notes,
            "is_active": True,
            "rows": rows,
        }
    ]


def _resolve_identity(gas: Any) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Return (kind, canonical, error). kind is blend, pure, or None."""
    if gas is None or (isinstance(gas, str) and not str(gas).strip()):
        return None, None, "refrigerant gas is required"
    if not isinstance(gas, str):
        return None, None, "refrigerant gas must be a name"
    key = _normalize_name(gas)
    if not key:
        return None, None, "refrigerant gas is required"
    if key in _EXCLUDED:
        name = _EXCLUDED[key]
        return None, name, f"{name} is not calculated in the refrigerant-leakage method"
    if key in _HCFC_OR_CFC_BLENDS:
        name = _HCFC_OR_CFC_BLENDS[key]
        return (
            None,
            name,
            f"{name} is an HCFC- or CFC-containing blend and is not calculated "
            "in the refrigerant-leakage method",
        )
    if key in _ZERO_GWP_BLENDS:
        name = _ZERO_GWP_BLENDS[key]
        return (
            None,
            name,
            f"{name} is a zero-GWP Table 12 blend and is not calculated. "
            "A missing or zero factor is not treated as no emissions from a supported gas.",
        )
    if key in _SUPPORTED_BLENDS:
        return "blend", _display_blend_name(key), None
    if key in _PURE:
        return "pure", _PURE[key][0], None
    return None, None, f"{str(gas).strip()} is not a supported refrigerant"


def _display_blend_name(key: str) -> str:
    # r-404a -> R-404A, r-507a -> R-507A
    body = key[2:] if key.startswith("r-") else key
    return "R-" + body.upper()


def _select_blend_row(
    rows: Sequence[Mapping[str, Any]], canonical: str
) -> Tuple[Optional[Mapping[str, Any]], Optional[str]]:
    want = _normalize_name(canonical)
    hits = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        _key_used, raw_name = _attribute(row, NAME_ATTRIBUTE)
        if _normalize_name(raw_name) == want:
            hits.append(row)
    if not hits:
        return None, (
            f"No epa_refrigerant_gwp row matches {canonical}. "
            "A missing factor is not treated as zero."
        )
    if len(hits) > 1:
        return None, (
            f"More than one epa_refrigerant_gwp row matches {canonical}. "
            "The factor is ambiguous and is not selected automatically."
        )
    return hits[0], None


def _gwp_from_row(row: Mapping[str, Any], canonical: str) -> Tuple[Optional[Decimal], Optional[str], Optional[str]]:
    original_key, raw_value = _attribute(row, GWP_ATTRIBUTE)
    if original_key is None:
        return None, None, (
            f"{canonical} has no \"{GWP_ATTRIBUTE}\" factor. "
            "kg_co2e and other columns are not used as a substitute."
        )
    if raw_value is None or (isinstance(raw_value, str) and not str(raw_value).strip()):
        return None, None, (
            f"{canonical} has an empty \"{GWP_ATTRIBUTE}\" factor. "
            "A missing factor is not treated as zero."
        )
    parsed = _parse_decimal(raw_value)
    if parsed is None:
        return None, None, (
            f"{canonical} has a malformed \"{GWP_ATTRIBUTE}\" value {raw_value!s}."
        )
    if parsed == 0:
        return None, None, (
            f"{canonical} has a zero \"{GWP_ATTRIBUTE}\" factor and is not calculated."
        )
    if parsed < 0:
        return None, None, f"{canonical} has a negative \"{GWP_ATTRIBUTE}\" factor."
    return parsed, original_key, None


def _quantity(value: Any, label: str) -> Tuple[Optional[Decimal], Optional[str]]:
    if value is None or (isinstance(value, str) and not str(value).strip()):
        return None, f"{label} is required"
    parsed = _parse_decimal(value)
    if parsed is None:
        return None, f"{label} must be a finite number greater than or equal to 0"
    if parsed < 0:
        return None, f"{label} must be a finite number greater than or equal to 0"
    return parsed, None


def _rate(value: Any) -> Tuple[Optional[Decimal], Optional[str]]:
    if value is None or (isinstance(value, str) and not str(value).strip()):
        return None, (
            "A leakage rate is required for estimated leakage. "
            "A missing rate is not treated as zero, and no EPA default rate is applied."
        )
    parsed = _parse_decimal(value)
    if parsed is None:
        return None, (
            "leakage_rate_percent must be a finite number from 0 through 100. "
            "A missing or invalid rate is not treated as zero."
        )
    if parsed < 0 or parsed > _HUNDRED:
        return None, "leakage_rate_percent must be from 0 through 100"
    return parsed, None


def _equipment_type(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def calculate_refrigerant_leakage(
    *,
    method: str,
    gas: Any,
    sheets: Sequence[Mapping[str, Any]],
    leakage_kg: Any = None,
    charge_kg: Any = None,
    leakage_rate_percent: Any = None,
    equipment_type: Any = None,
    gwp: Any = None,
    factor: Any = None,
    emissions: Any = None,
    emissions_kg: Any = None,
    emissions_kg_co2e: Any = None,
    emissions_tco2e: Any = None,
    total_kg_co2e: Any = None,
    total_t_co2e: Any = None,
    **_ignored: Any,
) -> Dict[str, Any]:
    """
    Calculate one refrigerant leak.

    Caller ``gwp``, ``factor``, and every emissions total are discarded.
    """
    del (
        gwp,
        factor,
        emissions,
        emissions_kg,
        emissions_kg_co2e,
        emissions_tco2e,
        total_kg_co2e,
        total_t_co2e,
        _ignored,
    )

    kind, canonical, identity_error = _resolve_identity(gas)
    if identity_error:
        return _fail(identity_error, refrigerant=canonical)

    if method not in {"leakage_record", "estimated_leakage"}:
        return _fail(
            "method must be leakage_record or estimated_leakage",
            refrigerant=canonical,
        )

    leakage_rate_source = None
    charge = None
    rate = None
    equipment = _equipment_type(equipment_type) if method == "estimated_leakage" else None

    if method == "leakage_record":
        leakage, quantity_error = _quantity(leakage_kg, "leakage_kg")
        if quantity_error or leakage is None:
            return _fail(quantity_error or "leakage_kg is required", method=method, refrigerant=canonical)
    else:
        charge, charge_error = _quantity(charge_kg, "charge_kg")
        if charge_error or charge is None:
            return _fail(charge_error or "charge_kg is required", method=method, refrigerant=canonical)
        rate, rate_error = _rate(leakage_rate_percent)
        if rate_error or rate is None:
            return _fail(rate_error or "leakage_rate_percent is required", method=method, refrigerant=canonical)
        leakage = charge * rate / _HUNDRED
        leakage_rate_source = "user_assumption"

    if kind == "blend":
        sheet, sheet_error = _active_blend_sheets(sheets)
        if sheet_error or sheet is None:
            return _fail(
                sheet_error or "Authoritative dataset epa_refrigerant_gwp is missing or inactive.",
                method=method,
                refrigerant=canonical,
            )
        row, row_error = _select_blend_row(list(sheet.get("rows") or []), canonical or "")
        if row_error or row is None:
            return _fail(row_error or "factor row is missing", method=method, refrigerant=canonical)
        resolved_gwp, attribute_key, gwp_error = _gwp_from_row(row, canonical or "")
        if gwp_error or resolved_gwp is None or attribute_key is None:
            return _fail(gwp_error or "factor is invalid", method=method, refrigerant=canonical)
        _composition_key, composition = _attribute(row, COMPOSITION_ATTRIBUTE)
        basis = TABLE_12_BASIS
        if _composition_has_hydrocarbon(composition):
            basis = f"{TABLE_12_BASIS} {HYDROCARBON_BASIS}"
        dataset_id = row.get("_factor_dataset_id") or sheet.get("dataset_id")
        factor_row_id = row.get("_factor_row_id")
        if not dataset_id or not factor_row_id:
            return _fail(
                f"{canonical} matched a factor row without a dataset id and row id.",
                method=method,
                refrigerant=canonical,
            )
        provenance = (
            f"Resolved from dataset {DATASET_CODE} attribute \"{attribute_key}\". "
            f"{TABLE_12_PUBLICATION}. {basis} "
            "Not a frontend GWP map and not a UK refrigerant factor."
        )
        publication = TABLE_12_PUBLICATION
        table11 = None
        dataset_code = DATASET_CODE
        stored_dataset_id = str(dataset_id)
        stored_row_id = str(factor_row_id)
        stored_attribute = attribute_key
        version_label = sheet.get("version_label")
    else:
        resolved_gwp = _PURE[_normalize_name(canonical)][1]
        basis = (
            "Explicit Table 11 allowlist value. The number was not read from "
            "epa_refrigerant_gwp or from uk_refrigerant_factors."
        )
        provenance = f"{TABLE_11_REFERENCE} {basis}"
        publication = TABLE_11_PUBLICATION
        table11 = TABLE_11_REFERENCE
        dataset_code = None
        stored_dataset_id = None
        stored_row_id = None
        stored_attribute = None
        version_label = None

    emissions_kg = leakage * resolved_gwp
    emissions_t = emissions_kg / _THOUSAND

    return {
        "success": True,
        "method": method,
        "refrigerant": canonical,
        "leakage_kg": _decimal_text(leakage),
        "charge_kg": None if charge is None else _decimal_text(charge),
        "leakage_rate_percent": None if rate is None else _decimal_text(rate),
        "leakage_rate_source": leakage_rate_source,
        "equipment_type": equipment,
        "gwp": _decimal_text(resolved_gwp),
        "dataset_id": stored_dataset_id,
        "factor_row_id": stored_row_id,
        "dataset_code": dataset_code,
        "version_label": None if version_label is None else str(version_label),
        "factor_attribute": stored_attribute,
        "gwp_publication": publication,
        "gwp_edition": EDITION,
        "factor_provenance": provenance,
        "gwp_basis": basis,
        "table11_reference": table11,
        "emissions_kg_co2e": _decimal_text(emissions_kg),
        "emissions_tco2e": _decimal_text(emissions_t),
        "accounting": {
            "version": ACCOUNTING_VERSION,
            "methodology": METHODOLOGY,
            "edition": EDITION,
        },
    }
