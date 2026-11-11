"""
PCAF 2025 Part A §5.8 Securitisations & Structured Products (SSP) draft
persistence.

No emissions formulas. Never writes app.financed_emissions. Every holding is
forced to ``is_reportable=False`` / ``include_in_portfolio=False``. Identity of
a holding is ``financing_instance_id``; the deal (and its collateral / loan /
pool / pool-of-pools / tranche hierarchy) is shared between holdings.

Shared-data protection
----------------------
Deal-level ("shared") data: eligibility, deal.*, emissionsPath, collateral,
loans, pools, poolOfPools, tranches. Holding-level data: bank outstanding
investment, currency, holding name, tranche link, holding evidence.

* new deal                        -> shared data is written
* attaching to an existing deal   -> only the holding is written (unless
                                     ``update_shared`` is true)
* ``update_shared=True``          -> requires ``expected_deal_updated_at`` when
                                     sibling holdings exist (409 stale_deal)
* shared fields differ + siblings -> 409 shared_deal_conflict
* only holding fields differ      -> holding-only write; the shared hierarchy
                                     is not touched

Normalised child rows are keyed by the stable client ids (collateralId,
loanId, poolId, poolOfPoolsId, trancheId). Distinct loans are never merged just
because they point at the same collateral class.

Phase 6C will add calculations; until then no ``SspCalculation`` rows are
created here (only deleted together with their holding / deal).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .financing_instance import normalize_financing_instance_id
from .ssp_models import (
    SSP_METHODOLOGY_VERSION,
    SSP_NULL_COUNTERPARTY,
    SspCalculation,
    SspCollateral,
    SspDeal,
    SspHolding,
    SspLoan,
    SspLoanCollateral,
    SspPool,
    SspPoolLoan,
    SspPoolOfPools,
    SspPoolOfPoolsMember,
    SspTranche,
    SspTranchePool,
)
from .ssp_schemas import (
    SspCalculationOut,
    SspCollateralOut,
    SspDealOut,
    SspDraftPatch,
    SspDraftRecord,
    SspDraftUpsert,
    SspHoldingOut,
    SspLoanOut,
    SspPoolOut,
    SspTrancheOut,
)

ALLOWED_EMISSIONS_PATHS = frozenset({"lookthrough", "reported_pool"})
ALLOWED_COLLATERAL_EMISSIONS_PATHS = frozenset({"asset-class-estimate", "reported", ""})
ALLOWED_YES_NO = frozenset({"yes", "no"})
ALLOWED_VERIFICATION = frozenset({"verified", "unverified"})

_NUM_INT_DIGITS = {8: 12, 4: 6}  # Numeric(20,8) / Numeric(10,4)

_REPORTABLE_KEYS = frozenset(
    {"is_reportable", "include_in_portfolio", "isReportable", "includeInPortfolio"}
)

_SHARED_DRAFT_KEYS = frozenset(
    {
        "eligibility",
        "deal",
        "emissionsPath",
        "emissions_path",
        "collateral",
        "loans",
        "pools",
        "poolOfPools",
        "pool_of_pools",
        "tranches",
    }
)
_SERVER_DRAFT_KEYS = frozenset(
    {
        "dealId",
        "deal_id",
        "holdingId",
        "holding_id",
        "dealUpdatedAt",
        "holdingUpdatedAt",
        "siblingCount",
        "holdingCount",
        "holdings",
        "financingInstanceId",
        "financing_instance_id",
        "instanceKey",
        "instance_key",
    }
)
_HOLDING_SNAPSHOT_KEYS = frozenset(
    {
        "holdingName",
        "trancheClientId",
        "bankOutstandingInvestment",
        "holdingEvidence",
    }
)

# (attribute, camelCase key, kind)
_DEAL_FIELDS: Tuple[Tuple[str, str, str], ...] = (
    ("deal_name", "dealName", "text"),
    ("deal_identifier", "dealIdentifier", "text"),
    ("issuer_name", "issuerName", "text"),
    ("originator_name", "originatorName", "text"),
    ("spv_name", "spvName", "text"),
    ("structure_type", "structureType", "text"),
    ("reporting_year", "reportingYear", "opt"),
    ("currency", "currency", "text"),
    ("documentation_source", "documentationSource", "text"),
    ("has_tranches", "hasTranches", "yesno"),
    ("has_pool_of_pools", "hasPoolOfPools", "yesno"),
    ("collateral_remains_with_originator", "collateralRemainsWithOriginator", "yesno"),
    ("pools_linked_to_specific_tranches", "poolsLinkedToSpecificTranches", "yesno"),
)
_COLLATERAL_FIELDS: Tuple[Tuple[str, str, str], ...] = (
    ("name", "name", "text"),
    ("collateral_type", "collateralType", "text"),
    ("attribution_denominator", "attributionDenominator", "num"),
    ("denominator_label", "denominatorLabel", "text"),
    ("current_outstanding_amount", "currentOutstandingAmount", "num"),
    ("original_outstanding_amount", "originalOutstandingAmount", "num"),
    ("asset_value_at_origination", "assetValueAtOrigination", "num"),
    ("updated_asset_value", "updatedAssetValue", "num"),
    ("pcaf_method_option", "pcafMethodOption", "text"),
    ("emissions_path", "emissionsPath", "cpath"),
    ("scope1_emissions", "scope1Emissions", "num"),
    ("scope2_emissions", "scope2Emissions", "num"),
    ("scope3_emissions", "scope3Emissions", "num"),
    ("data_quality_score", "dataQualityScore", "dqs"),
    ("factor_library_entry_id", "factorLibraryEntryId", "text"),
    ("class_inputs", "classInputs", "json"),
    ("evidence", "evidence", "json"),
)
_LOAN_FIELDS: Tuple[Tuple[str, str, str], ...] = (
    ("name", "name", "text"),
    ("current_outstanding_amount", "currentOutstandingAmount", "num"),
    ("original_outstanding_amount", "originalOutstandingAmount", "num"),
    ("notes", "notes", "text"),
    ("evidence", "evidence", "json"),
)
_POOL_FIELDS: Tuple[Tuple[str, str, str], ...] = (
    ("name", "name", "text"),
    ("pool_current_outstanding_amount", "poolCurrentOutstandingAmount", "num"),
    ("reported_emissions_total", "reportedEmissionsTotal", "num"),
    ("reported_emissions_period", "reportedEmissionsPeriod", "text"),
    ("reported_scope_coverage", "reportedScopeCoverage", "text"),
    ("reported_verification", "reportedVerification", "verif"),
    ("reported_source", "reportedSource", "text"),
    ("evidence", "evidence", "json"),
)
_POP_FIELDS: Tuple[Tuple[str, str, str], ...] = (
    ("name", "name", "text"),
    ("current_outstanding_amount", "currentOutstandingAmount", "num"),
    ("evidence", "evidence", "json"),
)
_TRANCHE_FIELDS: Tuple[Tuple[str, str, str], ...] = (
    ("name", "name", "text"),
    ("seniority_label", "seniorityLabel", "text"),
    ("current_outstanding_amount", "currentOutstandingAmount", "num"),
    ("is_green_tranche", "isGreenTranche", "yesno"),
    ("evidence", "evidence", "json"),
)


# ---------------------------------------------------------------------------
# Public small helpers
# ---------------------------------------------------------------------------


def is_ssp_formula_id(formula_id: Optional[str]) -> bool:
    """True when a financed-emissions formula_id would be an SSP methodology key."""
    key = (formula_id or "").strip().lower()
    if not key:
        return False
    return (
        key == "ssp"
        or key.startswith("ssp")
        or "securitization" in key
        or "securitisation" in key
        or "structured-product" in key
    )


def ssp_reportable_blocked_detail() -> str:
    return (
        "Securitisations & Structured Products (SSP) cannot be calculated or "
        "saved as reportable financed emissions yet. Persist drafts via "
        "/api/v1/ssp/drafts."
    )


# ---------------------------------------------------------------------------
# Scalar helpers / validation
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _unprocessable(detail: Any) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail
    )


def _present(payload: Dict[str, Any], *keys: str) -> bool:
    return any(key in payload for key in keys)


def _pick(payload: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return default


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _optional_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _choice(
    value: Any, allowed: Iterable[str], field_name: str, *, strict: bool = True
) -> Optional[str]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        value = "yes" if value else "no"
    text = str(value).strip()
    if not text:
        return None
    if strict and text not in allowed:
        raise _unprocessable(f"{field_name} must be one of: {sorted(allowed)}")
    return text


def _dec(
    value: Any,
    *,
    places: int = 8,
    nonneg: bool = False,
    field_name: str = "value",
) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise _unprocessable(f"Invalid numeric value for {field_name}: {value!r}")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise _unprocessable(
            f"Invalid numeric value for {field_name}: {value!r}"
        ) from exc
    if not number.is_finite():
        raise _unprocessable(f"Invalid numeric value for {field_name}: {value!r}")
    if nonneg and number < 0:
        raise _unprocessable(f"{field_name} cannot be negative")
    limit = Decimal(10) ** _NUM_INT_DIGITS.get(places, 12)
    if abs(number) >= limit:
        raise _unprocessable(f"{field_name} is out of range")
    return number.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def _json_num(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(Decimal(str(value)))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _require_instance_id(value: Any) -> str:
    instance = normalize_financing_instance_id(value)
    if not instance:
        raise _unprocessable("financing_instance_id is required and cannot be blank")
    return instance


def _same_counterparty(
    left: Optional[uuid.UUID], right: Optional[uuid.UUID]
) -> bool:
    return (left or SSP_NULL_COUNTERPARTY) == (right or SSP_NULL_COUNTERPARTY)


def _truthy_flag(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value == 1
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return False


def _reject_reportable_payload(payload: Any) -> None:
    """Recursively refuse payloads that try to flag anything reportable."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in _REPORTABLE_KEYS and _truthy_flag(value):
                raise _unprocessable(
                    "SSP drafts cannot be marked reportable or included in the "
                    "portfolio. Totals are not saved as financed emissions."
                )
            _reject_reportable_payload(value)
    elif isinstance(payload, list):
        for item in payload:
            _reject_reportable_payload(item)


# ---------------------------------------------------------------------------
# Timestamps / locks
# ---------------------------------------------------------------------------


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _same_dt(left: Optional[datetime], right: Optional[datetime]) -> bool:
    """ISO-equality tolerant of sub-2ms drift (JS Date truncates to ms)."""
    if left is None or right is None:
        return left is right
    return abs((_aware(left) - _aware(right)).total_seconds()) < 0.002


def _conflict_detail(
    *,
    code: str,
    message: str,
    deal: SspDeal,
    changed_fields: Sequence[str],
    siblings: Sequence[SspHolding],
) -> Dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "changed_fields": list(changed_fields),
        "deal_id": str(deal.id),
        "deal_updated_at": _iso(deal.updated_at),
        "sibling_count": len(siblings),
        "sibling_financing_instance_ids": [
            row.financing_instance_id for row in siblings
        ],
    }


def _check_deal_lock(
    deal: SspDeal,
    expected: Optional[datetime],
    *,
    siblings: Sequence[SspHolding],
) -> None:
    if not siblings:
        return
    if expected is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_conflict_detail(
                code="stale_deal",
                message=(
                    "Confirm this shared-deal change with expected_deal_updated_at "
                    "so other holdings are not overwritten."
                ),
                deal=deal,
                changed_fields=[],
                siblings=siblings,
            ),
        )
    if not _same_dt(deal.updated_at, expected):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_conflict_detail(
                code="stale_deal",
                message=(
                    "The shared SSP deal was updated elsewhere. Refresh and review "
                    "before saving deal-level changes."
                ),
                deal=deal,
                changed_fields=[],
                siblings=siblings,
            ),
        )


def _check_holding_lock(holding: SspHolding, expected: Optional[datetime]) -> None:
    if expected is None:
        return
    if not _same_dt(holding.updated_at, expected):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "stale_holding",
                "message": (
                    "This holding was saved more recently. Refresh before "
                    "overwriting your outstanding investment or tranche link."
                ),
                "holding_id": str(holding.id),
                "holding_updated_at": _iso(holding.updated_at),
            },
        )


# ---------------------------------------------------------------------------
# Field normalisation (draft <-> canonical spec <-> DB row)
# ---------------------------------------------------------------------------


def _norm_value(
    kind: str, value: Any, field_name: str, *, strict: bool = True
) -> Any:
    if kind == "text":
        return _text(value).strip()
    if kind == "opt":
        return _optional_text(value)
    if kind == "num":
        return _dec(value, nonneg=strict, field_name=field_name)
    if kind == "dqs":
        score = _dec(value, places=4, field_name=field_name)
        if strict and score is not None and not (Decimal(1) <= score <= Decimal(5)):
            raise _unprocessable(f"{field_name} must be between 1 and 5")
        return score
    if kind == "json":
        if value is None or value == "":
            return {}
        if not isinstance(value, dict):
            if strict:
                raise _unprocessable(f"{field_name} must be an object")
            return {}
        return dict(value)
    if kind == "path":
        return _choice(value, ALLOWED_EMISSIONS_PATHS, field_name, strict=strict)
    if kind == "cpath":
        # Collateral look-through path (distinct from deal-level emissionsPath).
        return _choice(
            value, ALLOWED_COLLATERAL_EMISSIONS_PATHS, field_name, strict=strict
        )
    if kind == "yesno":
        return _choice(value, ALLOWED_YES_NO, field_name, strict=strict)
    if kind == "verif":
        return _choice(value, ALLOWED_VERIFICATION, field_name, strict=strict)
    raise ValueError(f"unknown kind {kind}")  # pragma: no cover


def _render_value(kind: str, value: Any) -> Any:
    if kind in ("num", "dqs"):
        return _json_num(value)
    if kind == "json":
        return dict(value or {})
    if kind == "text":
        return value or ""
    return value or ""


def _normalize_item(
    item: Dict[str, Any], fields: Sequence[Tuple[str, str, str]]
) -> Dict[str, Any]:
    return {
        attr: _norm_value(kind, _pick(item, camel, attr), camel)
        for attr, camel, kind in fields
    }


def _client_id(item: Dict[str, Any], camel: str, snake: str, label: str) -> str:
    raw = _pick(item, camel, snake)
    normalized = normalize_financing_instance_id(raw)
    if not normalized:
        raise _unprocessable(f"each {label} requires {camel}")
    return normalized


def _id_list(item: Dict[str, Any], camel: str, snake: str, label: str) -> List[str]:
    raw = _pick(item, camel, snake, default=[])
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise _unprocessable(f"{label}.{camel} must be an array")
    out: List[str] = []
    for entry in raw:
        normalized = normalize_financing_instance_id(entry)
        if not normalized:
            raise _unprocessable(f"{label}.{camel} contains a blank id")
        if normalized not in out:
            out.append(normalized)
    return out


def _list_section(
    draft: Dict[str, Any], camel: str, snake: str
) -> Optional[List[Dict[str, Any]]]:
    """None when the section was not provided (null counts as not provided)."""
    raw = _pick(draft, camel, snake)
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise _unprocessable(f"draft.{camel} must be an array")
    for item in raw:
        if not isinstance(item, dict):
            raise _unprocessable(f"each entry in draft.{camel} must be an object")
    return raw


def _unique_ids(specs: Sequence[Dict[str, Any]], id_attr: str, label: str) -> None:
    seen: set[str] = set()
    for spec in specs:
        value = spec[id_attr]
        if value in seen:
            raise _unprocessable(f"duplicate {label} id: {value}")
        seen.add(value)


def _parse_collateral(raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    specs = []
    for item in raw:
        spec = {
            "collateral_id": _client_id(item, "collateralId", "collateral_id", "collateral"),
            **_normalize_item(item, _COLLATERAL_FIELDS),
        }
        specs.append(spec)
    _unique_ids(specs, "collateral_id", "collateral")
    return specs


def _parse_loans(raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    specs = []
    for item in raw:
        spec = {
            "loan_id": _client_id(item, "loanId", "loan_id", "loan"),
            **_normalize_item(item, _LOAN_FIELDS),
            "collateral_ids": _id_list(item, "collateralIds", "collateral_ids", "loan"),
        }
        specs.append(spec)
    _unique_ids(specs, "loan_id", "loan")
    return specs


def _parse_loan_allocations(item: Dict[str, Any], loan_ids: List[str]) -> List[Dict[str, Any]]:
    """Optional per-loan amountInPool for LAF. Falls back to loanIds-only links."""
    raw = _pick(item, "loanAllocations", "loan_allocations")
    out: List[Dict[str, Any]] = []
    if isinstance(raw, list) and raw:
        for row in raw:
            if not isinstance(row, dict):
                raise _unprocessable("each loanAllocations entry must be an object")
            lid = _client_id(row, "loanId", "loan_id", "loanAllocations")
            amt = _dec(
                _pick(row, "amountInPool", "amount_in_pool"),
                nonneg=True,
                field_name="amountInPool",
            )
            out.append({"loan_id": lid, "amount_in_pool": amt})
        return out
    return [{"loan_id": lid, "amount_in_pool": None} for lid in loan_ids]


def _parse_pools(raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    specs = []
    for item in raw:
        loan_ids = _id_list(item, "loanIds", "loan_ids", "pool")
        allocations = _parse_loan_allocations(item, loan_ids)
        # Keep loan_ids aligned with allocations for association writes.
        linked_ids = [row["loan_id"] for row in allocations] or loan_ids
        spec = {
            "pool_id": _client_id(item, "poolId", "pool_id", "pool"),
            **_normalize_item(item, _POOL_FIELDS),
            "loan_ids": linked_ids,
            "loan_allocations": allocations,
        }
        specs.append(spec)
    _unique_ids(specs, "pool_id", "pool")
    return specs


def _parse_tranches(raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    specs = []
    for item in raw:
        spec = {
            "tranche_id": _client_id(item, "trancheId", "tranche_id", "tranche"),
            **_normalize_item(item, _TRANCHE_FIELDS),
            "linked_pool_ids": _id_list(
                item, "linkedPoolIds", "linked_pool_ids", "tranche"
            ),
        }
        specs.append(spec)
    _unique_ids(specs, "tranche_id", "tranche")
    return specs


def _parse_pool_of_pools(raw: Any) -> Optional[Dict[str, Any]]:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise _unprocessable("draft.poolOfPools must be an object or null")
    return {
        "pool_of_pools_id": _client_id(
            raw, "poolOfPoolsId", "pool_of_pools_id", "poolOfPools"
        ),
        **_normalize_item(raw, _POP_FIELDS),
        "pool_ids": _id_list(raw, "poolIds", "pool_ids", "poolOfPools"),
    }


def _shared_from_draft(draft: Dict[str, Any]) -> Dict[str, Any]:
    """Canonical view of ONLY the shared sections the payload provides."""
    view: Dict[str, Any] = {}

    eligibility = _pick(draft, "eligibility")
    if eligibility is not None:
        if not isinstance(eligibility, dict):
            raise _unprocessable("draft.eligibility must be an object")
        view["eligibility"] = dict(eligibility)

    deal = _pick(draft, "deal")
    if deal is not None:
        if not isinstance(deal, dict):
            raise _unprocessable("draft.deal must be an object")
        parsed: Dict[str, Any] = {}
        for attr, camel, kind in _DEAL_FIELDS:
            if not _present(deal, camel, attr):
                continue
            value = _norm_value(kind, _pick(deal, camel, attr), camel)
            if attr == "currency":
                value = value or "PKR"
            parsed[attr] = value
        view["deal"] = parsed

    if _present(draft, "emissionsPath", "emissions_path"):
        view["emissions_path"] = _choice(
            _pick(draft, "emissionsPath", "emissions_path"),
            ALLOWED_EMISSIONS_PATHS,
            "emissionsPath",
        )

    collateral = _list_section(draft, "collateral", "collateral")
    if collateral is not None:
        view["collateral"] = _parse_collateral(collateral)
    loans = _list_section(draft, "loans", "loans")
    if loans is not None:
        view["loans"] = _parse_loans(loans)
    pools = _list_section(draft, "pools", "pools")
    if pools is not None:
        view["pools"] = _parse_pools(pools)
    if _present(draft, "poolOfPools", "pool_of_pools"):
        view["pool_of_pools"] = _parse_pool_of_pools(
            _pick(draft, "poolOfPools", "pool_of_pools")
        )
    tranches = _list_section(draft, "tranches", "tranches")
    if tranches is not None:
        view["tranches"] = _parse_tranches(tranches)
    return view


def _validate_hierarchy(view: Dict[str, Any]) -> None:
    """Ensure association client-ids resolve within this deal view only.

    Cross-deal / cross-org links are additionally blocked by DB composite FKs
    and org-match triggers on association tables (migration 0020 / Phase 6B.2).
    """
    collateral_ids = [row["collateral_id"] for row in view["collateral"]]
    loan_ids = [row["loan_id"] for row in view["loans"]]
    pool_ids = [row["pool_id"] for row in view["pools"]]
    tranche_ids = [row["tranche_id"] for row in view["tranches"]]
    if len(collateral_ids) != len(set(collateral_ids)):
        raise _unprocessable("duplicate collateralId within deal")
    if len(loan_ids) != len(set(loan_ids)):
        raise _unprocessable("duplicate loanId within deal")
    if len(pool_ids) != len(set(pool_ids)):
        raise _unprocessable("duplicate poolId within deal")
    if len(tranche_ids) != len(set(tranche_ids)):
        raise _unprocessable("duplicate trancheId within deal")

    collateral_set = set(collateral_ids)
    loan_set = set(loan_ids)
    pool_set = set(pool_ids)
    for loan in view["loans"]:
        for cid in loan["collateral_ids"]:
            if cid not in collateral_set:
                raise _unprocessable(
                    f"loan {loan['loan_id']} references unknown collateralId {cid}"
                )
    for pool in view["pools"]:
        for lid in pool["loan_ids"]:
            if lid not in loan_set:
                raise _unprocessable(
                    f"pool {pool['pool_id']} references unknown loanId {lid}"
                )
    pop = view.get("pool_of_pools")
    if pop is not None:
        for pid in pop["pool_ids"]:
            if pid not in pool_set:
                raise _unprocessable(
                    f"poolOfPools references unknown poolId {pid}"
                )
    for tranche in view["tranches"]:
        for pid in tranche["linked_pool_ids"]:
            if pid not in pool_set:
                raise _unprocessable(
                    f"tranche {tranche['tranche_id']} references unknown poolId {pid}"
                )


# ---------------------------------------------------------------------------
# Canonical comparison
# ---------------------------------------------------------------------------


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        if value == 0:
            return "0"
        return format(value.normalize(), "f")
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _compact_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: compact
            for key, item in value.items()
            if (compact := _compact_json(item)) not in (None, "", [], {})
        }
    if isinstance(value, list):
        return [
            item
            for item in (_compact_json(item) for item in value)
            if item not in (None, "", [], {})
        ]
    if isinstance(value, str):
        return value.strip()
    return value


def _canon(value: Any) -> str:
    compact = _compact_json(_jsonable(value))
    if compact in (None, "", [], {}):
        compact = None
    return json.dumps(compact, sort_keys=True, default=str)


def _canon_specs(specs: Sequence[Dict[str, Any]]) -> str:
    """Order-sensitive over entities; link-id lists compare as sets."""
    normalized = []
    for spec in specs:
        item = dict(spec)
        for key, val in list(item.items()):
            if key.endswith("_ids") and isinstance(val, list):
                item[key] = sorted(val)
        normalized.append(item)
    return _canon(normalized)


def _canon_view_item(key: str, value: Any) -> str:
    if key in ("collateral", "loans", "pools", "tranches"):
        return _canon_specs(value or [])
    if key == "pool_of_pools":
        return _canon_specs([value] if value else [])
    return _canon(value)


def _shared_changes(
    db_view: Dict[str, Any], draft_view: Dict[str, Any]
) -> List[str]:
    changed: List[str] = []
    for key, new in draft_view.items():
        if key == "deal":
            current = db_view.get("deal", {})
            for sub, value in new.items():
                if _canon(current.get(sub)) != _canon(value):
                    changed.append(f"deal.{sub}")
            continue
        if _canon_view_item(key, db_view.get(key)) != _canon_view_item(key, new):
            changed.append(key)
    return changed


def _merge_view(db_view: Dict[str, Any], draft_view: Dict[str, Any]) -> Dict[str, Any]:
    effective = dict(db_view)
    for key, value in draft_view.items():
        if key == "deal":
            effective["deal"] = {**db_view.get("deal", {}), **value}
        else:
            effective[key] = value
    return effective


# ---------------------------------------------------------------------------
# DB graph loading
# ---------------------------------------------------------------------------


@dataclass
class _Graph:
    holdings: List[SspHolding] = field(default_factory=list)
    collateral: List[SspCollateral] = field(default_factory=list)
    loans: List[SspLoan] = field(default_factory=list)
    loan_collateral: List[SspLoanCollateral] = field(default_factory=list)
    pools: List[SspPool] = field(default_factory=list)
    pool_loans: List[SspPoolLoan] = field(default_factory=list)
    pop_rows: List[SspPoolOfPools] = field(default_factory=list)
    pop_members: List[SspPoolOfPoolsMember] = field(default_factory=list)
    tranches: List[SspTranche] = field(default_factory=list)
    tranche_pools: List[SspTranchePool] = field(default_factory=list)
    calcs: List[SspCalculation] = field(default_factory=list)


def _deal_rows(db: Session, model, organization_id: uuid.UUID, deal_id: uuid.UUID):
    return (
        db.query(model)
        .filter(model.organization_id == organization_id, model.deal_id == deal_id)
        .all()
    )


def _load_graph(
    db: Session, organization_id: uuid.UUID, deal_id: uuid.UUID
) -> _Graph:
    def rows(model):
        return _deal_rows(db, model, organization_id, deal_id)

    def ordered(model, id_attr):
        return sorted(
            rows(model), key=lambda r: (r.sort_order or 0, str(getattr(r, id_attr)))
        )

    holdings = sorted(
        rows(SspHolding),
        key=lambda r: (r.created_at or _now(), str(r.id)),
    )
    return _Graph(
        holdings=holdings,
        collateral=ordered(SspCollateral, "collateral_id"),
        loans=ordered(SspLoan, "loan_id"),
        loan_collateral=rows(SspLoanCollateral),
        pools=ordered(SspPool, "pool_id"),
        pool_loans=rows(SspPoolLoan),
        pop_rows=sorted(
            rows(SspPoolOfPools), key=lambda r: (r.created_at or _now(), str(r.id))
        ),
        pop_members=rows(SspPoolOfPoolsMember),
        tranches=ordered(SspTranche, "tranche_id"),
        tranche_pools=rows(SspTranchePool),
        calcs=rows(SspCalculation),
    )


def _row_spec(
    row: Any, id_attr: str, fields: Sequence[Tuple[str, str, str]]
) -> Dict[str, Any]:
    spec = {id_attr: getattr(row, id_attr)}
    for attr, camel, kind in fields:
        spec[attr] = _norm_value(kind, getattr(row, attr), camel, strict=False)
    return spec


def _shared_from_graph(deal: SspDeal, graph: _Graph) -> Dict[str, Any]:
    """Full canonical shared view as persisted in the normalised tables."""
    deal_view: Dict[str, Any] = {}
    for attr, camel, kind in _DEAL_FIELDS:
        value = _norm_value(kind, getattr(deal, attr, None), camel, strict=False)
        if attr == "currency":
            value = value or "PKR"
        deal_view[attr] = value

    collateral_by_row = {row.id: row.collateral_id for row in graph.collateral}
    loan_by_row = {row.id: row.loan_id for row in graph.loans}
    pool_by_row = {row.id: row.pool_id for row in graph.pools}

    def links(assoc, owner_attr: str, target_attr: str, target_map, order):
        owned: Dict[uuid.UUID, set] = {}
        for link in assoc:
            target = target_map.get(getattr(link, target_attr))
            if target is not None:
                owned.setdefault(getattr(link, owner_attr), set()).add(target)
        return {
            owner: [client for client in order if client in targets]
            for owner, targets in owned.items()
        }

    loan_links = links(
        graph.loan_collateral,
        "loan_row_id",
        "collateral_row_id",
        collateral_by_row,
        [row.collateral_id for row in graph.collateral],
    )
    pool_links = links(
        graph.pool_loans,
        "pool_row_id",
        "loan_row_id",
        loan_by_row,
        [row.loan_id for row in graph.loans],
    )
    pop_links = links(
        graph.pop_members,
        "pool_of_pools_row_id",
        "pool_row_id",
        pool_by_row,
        [row.pool_id for row in graph.pools],
    )
    tranche_links = links(
        graph.tranche_pools,
        "tranche_row_id",
        "pool_row_id",
        pool_by_row,
        [row.pool_id for row in graph.pools],
    )

    pop_row = graph.pop_rows[0] if graph.pop_rows else None
    pop_spec: Optional[Dict[str, Any]] = None
    if pop_row is not None:
        pop_spec = {
            **_row_spec(pop_row, "pool_of_pools_id", _POP_FIELDS),
            "pool_ids": pop_links.get(pop_row.id, []),
        }

    return {
        "eligibility": dict(deal.eligibility or {}),
        "deal": deal_view,
        "emissions_path": _optional_text(deal.emissions_path),
        "collateral": [
            _row_spec(row, "collateral_id", _COLLATERAL_FIELDS)
            for row in graph.collateral
        ],
        "loans": [
            {
                **_row_spec(row, "loan_id", _LOAN_FIELDS),
                "collateral_ids": loan_links.get(row.id, []),
            }
            for row in graph.loans
        ],
        "pools": [
            {
                **_row_spec(row, "pool_id", _POOL_FIELDS),
                "loan_ids": pool_links.get(row.id, []),
                "loan_allocations": [
                    {
                        "loan_id": loan_by_row[link.loan_row_id],
                        "amount_in_pool": link.amount_in_pool,
                    }
                    for link in graph.pool_loans
                    if link.pool_row_id == row.id and link.loan_row_id in loan_by_row
                ],
            }
            for row in graph.pools
        ],
        "pool_of_pools": pop_spec,
        "tranches": [
            {
                **_row_spec(row, "tranche_id", _TRANCHE_FIELDS),
                "linked_pool_ids": tranche_links.get(row.id, []),
            }
            for row in graph.tranches
        ],
    }


# ---------------------------------------------------------------------------
# Rendering (canonical spec -> SPA camelCase)
# ---------------------------------------------------------------------------


def _render_items(
    specs: Sequence[Dict[str, Any]],
    id_attr: str,
    id_camel: str,
    fields: Sequence[Tuple[str, str, str]],
    link_attr: Optional[str] = None,
    link_camel: Optional[str] = None,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for spec in specs:
        item: Dict[str, Any] = {id_camel: spec[id_attr]}
        for attr, camel, kind in fields:
            item[camel] = _render_value(kind, spec.get(attr))
        if link_attr and link_camel:
            item[link_camel] = list(spec.get(link_attr) or [])
        out.append(item)
    return out


def _render_pools(specs: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    pools = _render_items(
        specs,
        "pool_id",
        "poolId",
        _POOL_FIELDS,
        "loan_ids",
        "loanIds",
    )
    by_id = {spec["pool_id"]: spec for spec in specs}
    for pool in pools:
        spec = by_id.get(pool["poolId"]) or {}
        allocs = []
        for row in spec.get("loan_allocations") or []:
            allocs.append(
                {
                    "loanId": row.get("loan_id"),
                    "amountInPool": _json_num(row.get("amount_in_pool")),
                }
            )
        if allocs:
            pool["loanAllocations"] = allocs
    return pools


def _render_shared(view: Dict[str, Any]) -> Dict[str, Any]:
    deal_out: Dict[str, Any] = {}
    for attr, camel, kind in _DEAL_FIELDS:
        deal_out[camel] = _render_value(kind, view.get("deal", {}).get(attr))
    pop = view.get("pool_of_pools")
    return {
        "eligibility": dict(view.get("eligibility") or {}),
        "deal": deal_out,
        "emissionsPath": view.get("emissions_path") or "",
        "collateral": _render_items(
            view.get("collateral") or [],
            "collateral_id",
            "collateralId",
            _COLLATERAL_FIELDS,
        ),
        "loans": _render_items(
            view.get("loans") or [],
            "loan_id",
            "loanId",
            _LOAN_FIELDS,
            "collateral_ids",
            "collateralIds",
        ),
        "pools": _render_pools(view.get("pools") or []),
        "poolOfPools": (
            _render_items(
                [pop],
                "pool_of_pools_id",
                "poolOfPoolsId",
                _POP_FIELDS,
                "pool_ids",
                "poolIds",
            )[0]
            if pop
            else None
        ),
        "tranches": _render_items(
            view.get("tranches") or [],
            "tranche_id",
            "trancheId",
            _TRANCHE_FIELDS,
            "linked_pool_ids",
            "linkedPoolIds",
        ),
    }


def _holding_extras(draft: Dict[str, Any]) -> Dict[str, Any]:
    """Non-shared, non-server, non-holding-column draft keys (e.g. lastPreviewNote)."""
    return {
        key: value
        for key, value in draft.items()
        if key not in _SHARED_DRAFT_KEYS
        and key not in _SERVER_DRAFT_KEYS
        and key not in _HOLDING_SNAPSHOT_KEYS
    }


def _compose_draft(
    deal: SspDeal, holding: SspHolding, graph: _Graph
) -> Dict[str, Any]:
    snapshot = dict(holding.draft_snapshot or {})
    out: Dict[str, Any] = _holding_extras(snapshot)
    out.setdefault("lastPreviewNote", "")
    out.update(_render_shared(_shared_from_graph(deal, graph)))

    holdings_out: List[Dict[str, Any]] = []
    for row in graph.holdings:
        row_snapshot = dict(row.draft_snapshot or {})
        holdings_out.append(
            {
                "holdingId": str(row.id),
                "financingInstanceId": row.financing_instance_id,
                "name": row.holding_name or "",
                "trancheId": row.tranche_client_id or "",
                "trancheClientId": row.tranche_client_id or "",
                "bankOutstandingInvestment": _json_num(row.bank_outstanding_investment),
                "currency": row.currency or "PKR",
                "evidence": dict(row_snapshot.get("holdingEvidence") or {}),
            }
        )
    out.update(
        {
            "financingInstanceId": holding.financing_instance_id,
            "instanceKey": holding.instance_key or snapshot.get("instanceKey") or "",
            "dealId": str(deal.id),
            "holdingId": str(holding.id),
            "dealUpdatedAt": _iso(deal.updated_at),
            "holdingUpdatedAt": _iso(holding.updated_at),
            "holdings": holdings_out,
            "holdingName": holding.holding_name or "",
            "trancheClientId": holding.tranche_client_id or "",
            "bankOutstandingInvestment": _json_num(holding.bank_outstanding_investment),
        }
    )
    return out


# ---------------------------------------------------------------------------
# Holding-specific draft parsing
# ---------------------------------------------------------------------------


def _match_holding_entry(
    draft: Dict[str, Any], instance_id: str, holding_id: Optional[uuid.UUID]
) -> Optional[Dict[str, Any]]:
    raw = _pick(draft, "holdings")
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise _unprocessable("draft.holdings must be an array")
    entries = []
    for item in raw:
        if not isinstance(item, dict):
            raise _unprocessable("each entry in draft.holdings must be an object")
        entries.append(item)

    def entry_instance(item: Dict[str, Any]) -> Optional[str]:
        return normalize_financing_instance_id(
            _pick(item, "financingInstanceId", "financing_instance_id")
        )

    for item in entries:
        if entry_instance(item) == instance_id:
            return item
    if holding_id is not None:
        for item in entries:
            if str(_pick(item, "holdingId", "holding_id", default="")) == str(holding_id):
                return item
    for item in entries:
        if entry_instance(item) is None and not _present(item, "holdingId", "holding_id"):
            return item
    return None


def _holding_from_draft(
    draft: Dict[str, Any], instance_id: str, holding_id: Optional[uuid.UUID]
) -> Dict[str, Any]:
    """Only the holding fields the payload provides."""
    entry = _match_holding_entry(draft, instance_id, holding_id) or {}
    out: Dict[str, Any] = {}

    def lookup(entry_keys: Sequence[str], top_keys: Sequence[str]) -> Tuple[bool, Any]:
        if _present(entry, *entry_keys):
            return True, _pick(entry, *entry_keys)
        if _present(draft, *top_keys):
            return True, _pick(draft, *top_keys)
        return False, None

    found, value = lookup(("name", "holdingName"), ("holdingName", "holding_name"))
    if found:
        out["holding_name"] = _text(value).strip()
    found, value = lookup(
        ("trancheId", "trancheClientId", "tranche_client_id"),
        ("trancheClientId", "tranche_client_id"),
    )
    if found:
        out["tranche_client_id"] = normalize_financing_instance_id(value)
    found, value = lookup(
        ("bankOutstandingInvestment", "bank_outstanding_investment"),
        ("bankOutstandingInvestment", "bank_outstanding_investment"),
    )
    if found:
        out["bank_outstanding_investment"] = _dec(
            value, nonneg=True, field_name="bankOutstandingInvestment"
        )
    if _present(entry, "currency"):
        out["currency"] = _optional_text(_pick(entry, "currency")) or "PKR"
    if _present(entry, "evidence"):
        evidence = _pick(entry, "evidence", default={})
        if not isinstance(evidence, dict):
            raise _unprocessable("holdings[].evidence must be an object")
        out["holding_evidence"] = dict(evidence)
    return out


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


def _flush(db: Session) -> None:
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "SSP draft conflicts with an existing financing_instance_id "
                f"or client id in this deal. ({exc.orig})"
            ),
        ) from exc


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "SSP draft conflicts with an existing financing_instance_id "
                f"or client id in this deal. ({exc.orig})"
            ),
        ) from exc


def find_holding_by_instance(
    db: Session,
    *,
    organization_id: uuid.UUID,
    financing_instance_id: str,
    counterparty_id: Optional[uuid.UUID] = None,
    match_counterparty: bool = False,
) -> Optional[SspHolding]:
    """
    Locate a holding by financing_instance_id.

    Upsert uses match_counterparty=True so the key is
    (org, counterparty, instance). Resume/GET without a counterparty matches the
    org-scoped instance; multiple hits are a 409.
    """
    instance = normalize_financing_instance_id(financing_instance_id)
    if not instance:
        return None
    matches = (
        db.query(SspHolding)
        .filter(
            SspHolding.organization_id == organization_id,
            SspHolding.financing_instance_id == instance,
        )
        .all()
    )
    if match_counterparty or counterparty_id is not None:
        matches = [
            row
            for row in matches
            if _same_counterparty(row.counterparty_id, counterparty_id)
        ]
    if len(matches) > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "financing_instance_id is ambiguous across counterparties; "
                "pass counterparty_id"
            ),
        )
    return matches[0] if matches else None


def get_org_holding(
    db: Session, organization_id: uuid.UUID, holding_id: uuid.UUID
) -> SspHolding:
    row = (
        db.query(SspHolding)
        .filter(
            SspHolding.organization_id == organization_id,
            SspHolding.id == holding_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="SSP draft not found"
        )
    return row


def get_org_deal(
    db: Session, organization_id: uuid.UUID, deal_id: uuid.UUID
) -> SspDeal:
    row = (
        db.query(SspDeal)
        .filter(SspDeal.organization_id == organization_id, SspDeal.id == deal_id)
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="SSP deal not found"
        )
    return row


def _new_deal(
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    counterparty_id: Optional[uuid.UUID],
) -> SspDeal:
    return SspDeal(
        id=uuid.uuid4(),
        organization_id=organization_id,
        user_id=user_id,
        counterparty_id=counterparty_id,
        deal_name="",
        deal_identifier="",
        issuer_name="",
        originator_name="",
        spv_name="",
        structure_type="",
        methodology_version=SSP_METHODOLOGY_VERSION,
        currency="PKR",
        documentation_source="",
        eligibility={},
        shared_snapshot={},
        status="draft",
        created_at=_now(),
        updated_at=_now(),
    )


def _decide_shared_write(
    *,
    deal: SspDeal,
    db_view: Dict[str, Any],
    draft_view: Dict[str, Any],
    siblings: Sequence[SspHolding],
    created_new_deal: bool,
    attaching: bool,
    update_shared: bool,
    expected_deal_updated_at: Optional[datetime],
) -> Tuple[bool, List[str]]:
    """Return (apply_shared, changed_fields)."""
    if created_new_deal:
        return True, list(draft_view.keys())
    changed = _shared_changes(db_view, draft_view)
    if attaching and not update_shared:
        # A new holding joining an existing deal never rewrites the deal.
        return False, changed
    if update_shared:
        _check_deal_lock(deal, expected_deal_updated_at, siblings=siblings)
        return True, changed
    if not changed:
        return False, changed
    if not siblings:
        return True, changed
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=_conflict_detail(
            code="shared_deal_conflict",
            message=(
                "This save would change shared SSP deal, collateral, loan, pool or "
                "tranche data used by other holdings. Confirm update_shared=true "
                "after reviewing, or save only this holding's investment."
            ),
            deal=deal,
            changed_fields=changed,
            siblings=siblings,
        ),
    )


def _upsert_rows(
    db: Session,
    *,
    model,
    id_attr: str,
    fields: Sequence[Tuple[str, str, str]],
    existing: Sequence[Any],
    specs: Sequence[Dict[str, Any]],
    organization_id: uuid.UUID,
    deal_id: uuid.UUID,
    sortable: bool = True,
) -> Dict[str, uuid.UUID]:
    by_client = {getattr(row, id_attr): row for row in existing}
    mapping: Dict[str, uuid.UUID] = {}
    for index, spec in enumerate(specs):
        client = spec[id_attr]
        row = by_client.get(client)
        if row is None:
            row = model(
                id=uuid.uuid4(),
                organization_id=organization_id,
                deal_id=deal_id,
                created_at=_now(),
            )
            setattr(row, id_attr, client)
            db.add(row)
        for attr, _camel, _kind in fields:
            setattr(row, attr, spec[attr])
        if sortable:
            row.sort_order = index
        mapping[client] = row.id
    return mapping


def _sync_hierarchy(
    db: Session,
    *,
    organization_id: uuid.UUID,
    deal: SspDeal,
    graph: _Graph,
    effective: Dict[str, Any],
    provided: Iterable[str],
) -> None:
    """
    Replace the deal's children / association rows from the effective view.

    Main rows are upserted by their stable client id (row UUIDs and therefore
    ssp_calculations links survive); rows whose client id disappeared are
    deleted; association tables are rebuilt in full.
    """
    provided = set(provided)
    deal_id = deal.id

    for link in (
        list(graph.loan_collateral)
        + list(graph.pool_loans)
        + list(graph.pop_members)
        + list(graph.tranche_pools)
    ):
        db.delete(link)
    _flush(db)

    def remove_missing(rows: Sequence[Any], id_attr: str, keep: set[str]) -> List[Any]:
        removed = [row for row in rows if getattr(row, id_attr) not in keep]
        return removed

    if "collateral" in provided:
        removed = remove_missing(
            graph.collateral,
            "collateral_id",
            {spec["collateral_id"] for spec in effective["collateral"]},
        )
        removed_ids = {row.id for row in removed}
        for calc in graph.calcs:
            if calc.collateral_row_id in removed_ids:
                db.delete(calc)
        for row in removed:
            db.delete(row)
    if "loans" in provided:
        for row in remove_missing(
            graph.loans, "loan_id", {s["loan_id"] for s in effective["loans"]}
        ):
            db.delete(row)
    if "pools" in provided:
        for row in remove_missing(
            graph.pools, "pool_id", {s["pool_id"] for s in effective["pools"]}
        ):
            db.delete(row)
    if "tranches" in provided:
        for row in remove_missing(
            graph.tranches,
            "tranche_id",
            {s["tranche_id"] for s in effective["tranches"]},
        ):
            db.delete(row)
    pop_spec = effective.get("pool_of_pools")
    if "pool_of_pools" in provided:
        keep = {pop_spec["pool_of_pools_id"]} if pop_spec else set()
        for row in remove_missing(graph.pop_rows, "pool_of_pools_id", keep):
            db.delete(row)
    _flush(db)

    def mapping_for(section: str, rows: Sequence[Any], id_attr: str, fields, model):
        if section in provided:
            return _upsert_rows(
                db,
                model=model,
                id_attr=id_attr,
                fields=fields,
                existing=rows,
                specs=effective[section],
                organization_id=organization_id,
                deal_id=deal_id,
            )
        return {getattr(row, id_attr): row.id for row in rows}

    collateral_map = mapping_for(
        "collateral", graph.collateral, "collateral_id", _COLLATERAL_FIELDS, SspCollateral
    )
    loan_map = mapping_for("loans", graph.loans, "loan_id", _LOAN_FIELDS, SspLoan)
    pool_map = mapping_for("pools", graph.pools, "pool_id", _POOL_FIELDS, SspPool)
    tranche_map = mapping_for(
        "tranches", graph.tranches, "tranche_id", _TRANCHE_FIELDS, SspTranche
    )
    if "pool_of_pools" in provided:
        pop_map = (
            _upsert_rows(
                db,
                model=SspPoolOfPools,
                id_attr="pool_of_pools_id",
                fields=_POP_FIELDS,
                existing=graph.pop_rows,
                specs=[pop_spec] if pop_spec else [],
                organization_id=organization_id,
                deal_id=deal_id,
                sortable=False,
            )
        )
    else:
        pop_map = {row.pool_of_pools_id: row.id for row in graph.pop_rows}
    _flush(db)

    def _row_id(mapping: Dict[str, uuid.UUID], client_id: str, kind: str) -> uuid.UUID:
        row_id = mapping.get(client_id)
        if row_id is None:
            raise _unprocessable(
                f"cannot associate {kind} {client_id}: not in this deal hierarchy"
            )
        return row_id

    for loan in effective["loans"]:
        loan_row_id = _row_id(loan_map, loan["loan_id"], "loan")
        for cid in loan["collateral_ids"]:
            db.add(
                SspLoanCollateral(
                    id=uuid.uuid4(),
                    organization_id=organization_id,
                    deal_id=deal_id,
                    loan_row_id=loan_row_id,
                    collateral_row_id=_row_id(collateral_map, cid, "collateral"),
                    created_at=_now(),
                )
            )
    for pool in effective["pools"]:
        pool_row_id = _row_id(pool_map, pool["pool_id"], "pool")
        allocations = pool.get("loan_allocations") or [
            {"loan_id": lid, "amount_in_pool": None} for lid in pool.get("loan_ids") or []
        ]
        for alloc in allocations:
            lid = alloc["loan_id"]
            db.add(
                SspPoolLoan(
                    id=uuid.uuid4(),
                    organization_id=organization_id,
                    deal_id=deal_id,
                    pool_row_id=pool_row_id,
                    loan_row_id=_row_id(loan_map, lid, "loan"),
                    amount_in_pool=alloc.get("amount_in_pool"),
                    created_at=_now(),
                )
            )
    if pop_spec:
        pop_row_id = _row_id(
            pop_map, pop_spec["pool_of_pools_id"], "poolOfPools"
        )
        for pid in pop_spec["pool_ids"]:
            db.add(
                SspPoolOfPoolsMember(
                    id=uuid.uuid4(),
                    organization_id=organization_id,
                    deal_id=deal_id,
                    pool_of_pools_row_id=pop_row_id,
                    pool_row_id=_row_id(pool_map, pid, "pool"),
                    created_at=_now(),
                )
            )
    for tranche in effective["tranches"]:
        tranche_row_id = _row_id(tranche_map, tranche["tranche_id"], "tranche")
        for pid in tranche["linked_pool_ids"]:
            db.add(
                SspTranchePool(
                    id=uuid.uuid4(),
                    organization_id=organization_id,
                    deal_id=deal_id,
                    tranche_row_id=tranche_row_id,
                    pool_row_id=_row_id(pool_map, pid, "pool"),
                    created_at=_now(),
                )
            )
    _flush(db)


def _apply_deal_fields(
    deal: SspDeal,
    *,
    effective: Dict[str, Any],
    user_id: uuid.UUID,
    counterparty_id: Optional[uuid.UUID],
    touch: bool,
) -> None:
    for attr, _camel, _kind in _DEAL_FIELDS:
        if attr in effective["deal"]:
            setattr(deal, attr, effective["deal"][attr])
    deal.currency = deal.currency or "PKR"
    deal.eligibility = dict(effective.get("eligibility") or {})
    deal.emissions_path = effective.get("emissions_path")
    deal.methodology_version = deal.methodology_version or SSP_METHODOLOGY_VERSION
    deal.shared_snapshot = _render_shared(effective)
    deal.status = "draft"
    deal.user_id = user_id
    if counterparty_id is not None and deal.counterparty_id is None:
        deal.counterparty_id = counterparty_id
    if touch:
        deal.updated_at = _now()


def _apply_holding_fields(
    holding: SspHolding,
    *,
    deal: SspDeal,
    draft: Dict[str, Any],
    holding_view: Dict[str, Any],
    instance_id: str,
    instance_key: Optional[str],
    formula_id: Optional[str],
    formula_name: Optional[str],
    exposure_id: Optional[uuid.UUID],
    counterparty_id: Optional[uuid.UUID],
    new_holding: bool,
    merge_previous: bool,
) -> None:
    holding.financing_instance_id = instance_id
    holding.instance_key = (
        _optional_text(instance_key)
        or _optional_text(_pick(draft, "instanceKey", "instance_key"))
        or holding.instance_key
    )
    if "holding_name" in holding_view:
        holding.holding_name = holding_view["holding_name"]
    elif new_holding:
        holding.holding_name = ""
    if "tranche_client_id" in holding_view:
        holding.tranche_client_id = holding_view["tranche_client_id"]
    if "bank_outstanding_investment" in holding_view:
        holding.bank_outstanding_investment = holding_view["bank_outstanding_investment"]
    if "currency" in holding_view:
        holding.currency = holding_view["currency"]
    elif new_holding or not holding.currency:
        holding.currency = deal.currency or "PKR"
    holding.formula_id = _optional_text(formula_id) or _optional_text(
        _pick(draft, "formulaId", "formula_id")
    ) or holding.formula_id
    if formula_name is not None:
        holding.formula_name = _optional_text(formula_name)
    if exposure_id is not None:
        holding.exposure_id = exposure_id
    if counterparty_id is not None:
        holding.counterparty_id = counterparty_id
    holding.status = "draft"
    holding.is_reportable = False
    holding.include_in_portfolio = False

    previous = dict(holding.draft_snapshot or {})
    snapshot: Dict[str, Any] = {}
    if merge_previous:
        snapshot.update(_holding_extras(previous))
        if "holdingEvidence" in previous:
            snapshot["holdingEvidence"] = previous["holdingEvidence"]
    snapshot.update(_holding_extras(draft))
    if "holding_evidence" in holding_view:
        snapshot["holdingEvidence"] = holding_view["holding_evidence"]
    snapshot["holdingName"] = holding.holding_name or ""
    snapshot["trancheClientId"] = holding.tranche_client_id or ""
    snapshot["bankOutstandingInvestment"] = _json_num(holding.bank_outstanding_investment)
    snapshot["financingInstanceId"] = instance_id
    if holding.instance_key:
        snapshot["instanceKey"] = holding.instance_key
    # Keep the previous shared parts from the deal's authoritative snapshot.
    shared_snapshot = dict(deal.shared_snapshot or {})
    for key in ("eligibility", "deal", "emissionsPath", "collateral", "loans", "pools", "poolOfPools", "tranches"):
        if key in shared_snapshot:
            snapshot[key] = shared_snapshot[key]
    holding.draft_snapshot = snapshot
    holding.updated_at = _now()


def _bundle(
    db: Session,
    organization_id: uuid.UUID,
    holding: SspHolding,
    *,
    created: bool = False,
    shared_write_applied: bool = False,
    graph: Optional[_Graph] = None,
) -> SspDraftRecord:
    deal = get_org_deal(db, organization_id, holding.deal_id)
    graph = graph or _load_graph(db, organization_id, deal.id)
    holding_count = len(graph.holdings)
    calcs = [
        row
        for row in graph.calcs
        if row.holding_id is None or row.holding_id == holding.id
    ]
    return SspDraftRecord(
        holding=SspHoldingOut.model_validate(holding),
        deal=SspDealOut.model_validate(deal),
        collateral=[SspCollateralOut.model_validate(row) for row in graph.collateral],
        loans=[SspLoanOut.model_validate(row) for row in graph.loans],
        pools=[SspPoolOut.model_validate(row) for row in graph.pools],
        tranches=[SspTrancheOut.model_validate(row) for row in graph.tranches],
        calculations=[SspCalculationOut.model_validate(row) for row in calcs],
        draft=_compose_draft(deal, holding, graph),
        created=created,
        sibling_count=max(0, holding_count - 1),
        holding_count=holding_count,
        shared_write_applied=shared_write_applied,
    )


def _persist(
    db: Session,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    deal: SspDeal,
    holding: SspHolding,
    draft: Dict[str, Any],
    has_draft: bool,
    created_new_deal: bool,
    new_holding: bool,
    attaching: bool,
    update_shared: bool,
    expected_deal_updated_at: Optional[datetime],
    instance_id: str,
    instance_key: Optional[str],
    formula_id: Optional[str],
    formula_name: Optional[str],
    exposure_id: Optional[uuid.UUID],
    counterparty_id: Optional[uuid.UUID],
    merge_previous: bool,
) -> bool:
    """Shared write decision + holding write. Returns apply_shared."""
    draft_view = _shared_from_draft(draft) if has_draft else {}
    holding_view = (
        _holding_from_draft(draft, instance_id, None if new_holding else holding.id)
        if has_draft
        else {}
    )

    graph = _load_graph(db, organization_id, deal.id)
    siblings = [row for row in graph.holdings if row.id != holding.id]
    db_view = _shared_from_graph(deal, graph)

    if has_draft:
        apply_shared, changed = _decide_shared_write(
            deal=deal,
            db_view=db_view,
            draft_view=draft_view,
            siblings=siblings,
            created_new_deal=created_new_deal,
            attaching=attaching,
            update_shared=update_shared,
            expected_deal_updated_at=expected_deal_updated_at,
        )
    else:
        apply_shared, changed = False, []

    effective = db_view
    if apply_shared:
        effective = _merge_view(db_view, draft_view)
        _validate_hierarchy(effective)
        _apply_deal_fields(
            deal,
            effective=effective,
            user_id=user_id,
            counterparty_id=counterparty_id,
            touch=created_new_deal or bool(changed),
        )
        db.add(deal)
        _sync_hierarchy(
            db,
            organization_id=organization_id,
            deal=deal,
            graph=graph,
            effective=effective,
            provided=draft_view.keys(),
        )

    tranche_id = holding_view.get("tranche_client_id")
    if tranche_id:
        known = {spec["tranche_id"] for spec in effective["tranches"]}
        if tranche_id not in known:
            raise _unprocessable(
                f"trancheId {tranche_id!r} is not a tranche of this SSP deal"
            )

    _apply_holding_fields(
        holding,
        deal=deal,
        draft=draft,
        holding_view=holding_view,
        instance_id=instance_id,
        instance_key=instance_key,
        formula_id=formula_id,
        formula_name=formula_name,
        exposure_id=exposure_id,
        counterparty_id=counterparty_id,
        new_holding=new_holding,
        merge_previous=merge_previous,
    )
    holding.user_id = user_id
    holding.deal_id = deal.id
    db.add(holding)
    return apply_shared


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def upsert_ssp_draft(
    db: Session,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    body: SspDraftUpsert,
) -> SspDraftRecord:
    draft = dict(body.draft or {})
    _reject_reportable_payload(draft)
    instance_id = _require_instance_id(body.financing_instance_id)
    draft_instance = normalize_financing_instance_id(
        _pick(draft, "financingInstanceId", "financing_instance_id")
    )
    if draft_instance and draft_instance != instance_id:
        raise _unprocessable(
            "draft.financingInstanceId does not match financing_instance_id"
        )
    # Validate the whole payload before touching the database.
    _shared_from_draft(draft)
    _holding_from_draft(draft, instance_id, None)

    existing = find_holding_by_instance(
        db,
        organization_id=organization_id,
        financing_instance_id=instance_id,
        counterparty_id=body.counterparty_id,
        match_counterparty=True,
    )
    created = existing is None
    created_new_deal = False
    attaching = False
    apply_shared = False
    try:
        if existing is not None:
            if body.deal_id is not None and body.deal_id != existing.deal_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "financing_instance_id already belongs to a different SSP "
                        "deal; updating this holding does not move or overwrite "
                        "unrelated holdings."
                    ),
                )
            deal = get_org_deal(db, organization_id, existing.deal_id)
            holding = existing
            _check_holding_lock(holding, body.expected_holding_updated_at)
        else:
            if body.deal_id is not None:
                deal = get_org_deal(db, organization_id, body.deal_id)
                if (
                    body.counterparty_id is not None
                    and deal.counterparty_id is not None
                    and deal.counterparty_id != body.counterparty_id
                ):
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="SSP deal belongs to a different counterparty",
                    )
                attaching = True
            else:
                deal = _new_deal(
                    organization_id=organization_id,
                    user_id=user_id,
                    counterparty_id=body.counterparty_id,
                )
                db.add(deal)
                created_new_deal = True
                _flush(db)
            holding = SspHolding(
                id=uuid.uuid4(),
                organization_id=organization_id,
                user_id=user_id,
                deal_id=deal.id,
                counterparty_id=body.counterparty_id,
                financing_instance_id=instance_id,
                holding_name="",
                currency=deal.currency or "PKR",
                status="draft",
                is_reportable=False,
                include_in_portfolio=False,
                draft_snapshot={},
                created_at=_now(),
                updated_at=_now(),
            )
            db.add(holding)
            _flush(db)

        apply_shared = _persist(
            db,
            organization_id=organization_id,
            user_id=user_id,
            deal=deal,
            holding=holding,
            draft=draft,
            has_draft=True,
            created_new_deal=created_new_deal,
            new_holding=created,
            attaching=attaching,
            update_shared=body.update_shared,
            expected_deal_updated_at=body.expected_deal_updated_at,
            instance_id=instance_id,
            instance_key=body.instance_key,
            formula_id=body.formula_id,
            formula_name=body.formula_name,
            exposure_id=body.exposure_id,
            counterparty_id=body.counterparty_id,
            merge_previous=False,
        )
        _commit(db)
    except Exception:
        db.rollback()
        raise
    db.refresh(holding)
    db.refresh(deal)
    return _bundle(
        db,
        organization_id,
        holding,
        created=created,
        shared_write_applied=apply_shared,
    )


def patch_ssp_draft(
    db: Session,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    holding_id: uuid.UUID,
    body: SspDraftPatch,
) -> SspDraftRecord:
    holding = get_org_holding(db, organization_id, holding_id)
    deal = get_org_deal(db, organization_id, holding.deal_id)
    _check_holding_lock(holding, body.expected_holding_updated_at)
    draft = dict(body.draft or {})
    has_draft = body.draft is not None
    if has_draft:
        _reject_reportable_payload(draft)
        draft_instance = normalize_financing_instance_id(
            _pick(draft, "financingInstanceId", "financing_instance_id")
        )
        if draft_instance and draft_instance != holding.financing_instance_id:
            raise _unprocessable(
                "draft.financingInstanceId does not match this holding"
            )
        _shared_from_draft(draft)
        _holding_from_draft(draft, holding.financing_instance_id, holding.id)

    apply_shared = False
    try:
        apply_shared = _persist(
            db,
            organization_id=organization_id,
            user_id=user_id,
            deal=deal,
            holding=holding,
            draft=draft,
            has_draft=has_draft,
            created_new_deal=False,
            new_holding=False,
            attaching=False,
            update_shared=body.update_shared,
            expected_deal_updated_at=body.expected_deal_updated_at,
            instance_id=holding.financing_instance_id,
            instance_key=body.instance_key,
            formula_id=body.formula_id,
            formula_name=body.formula_name,
            exposure_id=body.exposure_id,
            counterparty_id=body.counterparty_id,
            merge_previous=True,
        )
        _commit(db)
    except Exception:
        db.rollback()
        raise
    db.refresh(holding)
    db.refresh(deal)
    return _bundle(
        db, organization_id, holding, shared_write_applied=apply_shared
    )


def get_ssp_draft(
    db: Session, organization_id: uuid.UUID, holding_id: uuid.UUID
) -> SspDraftRecord:
    holding = get_org_holding(db, organization_id, holding_id)
    return _bundle(db, organization_id, holding)


def get_ssp_draft_by_instance(
    db: Session,
    *,
    organization_id: uuid.UUID,
    financing_instance_id: str,
    counterparty_id: Optional[uuid.UUID] = None,
) -> SspDraftRecord:
    instance_id = _require_instance_id(financing_instance_id)
    holding = find_holding_by_instance(
        db,
        organization_id=organization_id,
        financing_instance_id=instance_id,
        counterparty_id=counterparty_id,
    )
    if holding is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="SSP draft not found"
        )
    return _bundle(db, organization_id, holding)


def list_ssp_drafts(
    db: Session,
    *,
    organization_id: uuid.UUID,
    counterparty_id: Optional[uuid.UUID] = None,
    deal_id: Optional[uuid.UUID] = None,
    financing_instance_id: Optional[str] = None,
) -> List[SspDraftRecord]:
    query = db.query(SspHolding).filter(SspHolding.organization_id == organization_id)
    if counterparty_id is not None:
        query = query.filter(SspHolding.counterparty_id == counterparty_id)
    if deal_id is not None:
        query = query.filter(SspHolding.deal_id == deal_id)
    instance = normalize_financing_instance_id(financing_instance_id)
    if instance:
        query = query.filter(SspHolding.financing_instance_id == instance)
    rows = query.all()
    rows.sort(key=lambda row: row.created_at or _now(), reverse=True)
    graphs: Dict[uuid.UUID, _Graph] = {}
    records: List[SspDraftRecord] = []
    for row in rows:
        graph = graphs.get(row.deal_id)
        if graph is None:
            graph = graphs[row.deal_id] = _load_graph(db, organization_id, row.deal_id)
        records.append(_bundle(db, organization_id, row, graph=graph))
    return records


def delete_ssp_draft(
    db: Session, organization_id: uuid.UUID, holding_id: uuid.UUID
) -> None:
    holding = get_org_holding(db, organization_id, holding_id)
    deal_id = holding.deal_id
    graph = _load_graph(db, organization_id, deal_id)
    remaining = [row for row in graph.holdings if row.id != holding.id]
    try:
        if remaining:
            for calc in graph.calcs:
                if calc.holding_id == holding.id:
                    db.delete(calc)
            db.delete(holding)
        else:
            for calc in graph.calcs:
                db.delete(calc)
            for link in (
                list(graph.loan_collateral)
                + list(graph.pool_loans)
                + list(graph.pop_members)
                + list(graph.tranche_pools)
            ):
                db.delete(link)
            db.flush()
            for row in (
                list(graph.pop_rows)
                + list(graph.tranches)
                + list(graph.pools)
                + list(graph.loans)
                + list(graph.collateral)
            ):
                db.delete(row)
            db.delete(holding)
            db.flush()
            db.delete(get_org_deal(db, organization_id, deal_id))
        _commit(db)
    except Exception:
        db.rollback()
        raise
