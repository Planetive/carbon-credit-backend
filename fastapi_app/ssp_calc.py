"""
PCAF 2025 Part A §5.8 SSP preview calculation engine (Phase 6C.1).

Formulas locked in PHASE_6C0B. Preview only — never reportable, never writes
app.financed_emissions. Absolute underlying emissions come from ssp_underlying;
CAF/LAF/TAF/IAF are applied here so attribution is never double-counted.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from .ssp_models import SSP_METHODOLOGY_VERSION
from .ssp_underlying import absolute_emissions_for_collateral

# First-release supported structure types (eligibility may list more).
SUPPORTED_STRUCTURE_TYPES = frozenset(
    {
        "rmbs",
        "cmbs",
        "auto-abs",
        "clo-cdo",
        "true-sale-abs",
        "untranched",
        "mortgage-covered-bond",
        "cre-covered-bond",
        "private-abs",
        "synthetic",
        "warehouse",
        "",  # allow blank if eligibility already passed SSP outcome
    }
)

BLOCKED_STRUCTURE_TYPES = frozenset(
    {
        "master-trust",  # complex re-lever deferred
        "whole-loan",  # boundary unresolved
    }
)

RE_TYPES = frozenset({"mortgage", "commercial-real-estate"})
MOTOR_TYPES = frozenset({"motor-vehicle-loan", "other-hard-asset"})
BUSINESS_TYPES = frozenset({"business-loan", "unlisted-equity"})
LISTED_TYPES = frozenset({"corporate-bond", "listed-equity"})


class SspCalcError(Exception):
    def __init__(self, code: str, message: str, *, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def _num(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    return str(value or "").strip()


def _pick(data: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if isinstance(data, dict) and key in data and data[key] is not None:
            return data[key]
    return default


def _round(value: Optional[float], ndigits: int = 8) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), ndigits)


def compute_caf(
    *,
    collateral_type: str,
    loan_coa: Optional[float],
    loan_ooa: Optional[float],
    avo: Optional[float],
    uav: Optional[float],
    equity_plus_debt: Optional[float],
    evic: Optional[float],
) -> Dict[str, Any]:
    """Table 5.8-2 CAF with min(1, ·) and fallback priority."""
    ctype = _text(collateral_type)
    if ctype in RE_TYPES or ctype in MOTOR_TYPES:
        pairs = [
            ("coa_avo", loan_coa, avo),
            ("ooa_avo", loan_ooa, avo),
            ("coa_uav", loan_coa, uav),
            ("ooa_uav", loan_ooa, uav),
        ]
    elif ctype in BUSINESS_TYPES:
        pairs = [
            ("coa_equity_debt", loan_coa, equity_plus_debt),
            ("ooa_equity_debt", loan_ooa, equity_plus_debt),
        ]
    elif ctype in LISTED_TYPES:
        pairs = [
            ("coa_evic", loan_coa, evic),
            ("ooa_evic", loan_ooa, evic),
        ]
    else:
        return {
            "status": "unsupported",
            "code": "unsupported_caf_type",
            "caf": None,
            "caf_basis": None,
            "message": f"No CAF mapping for collateral type '{ctype}'.",
        }

    for basis, num, den in pairs:
        if num is None or den is None:
            continue
        if den <= 0:
            return {
                "status": "error",
                "code": "zero_denominator",
                "caf": None,
                "caf_basis": basis,
                "message": f"CAF denominator must be > 0 (basis={basis}).",
            }
        if num < 0:
            return {
                "status": "error",
                "code": "negative_numerator",
                "caf": None,
                "caf_basis": basis,
                "message": f"CAF numerator must be >= 0 (basis={basis}).",
            }
        raw = num / den
        return {
            "status": "complete",
            "code": None,
            "caf": min(1.0, raw),
            "caf_raw": raw,
            "caf_capped": raw > 1.0,
            "caf_basis": basis,
            "numerator": num,
            "denominator": den,
            "message": None,
        }

    return {
        "status": "incomplete",
        "code": "missing_caf_inputs",
        "caf": None,
        "caf_basis": None,
        "message": "CAF needs loan COA/OOA and the class denominator (AVO/UAV/Equity+Debt/EVIC).",
    }


def _company_denoms(class_inputs: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    form = class_inputs.get("formData") or class_inputs.get("form_data") or {}
    if not isinstance(form, dict):
        form = {}
    equity = _num(_pick(form, "totalEquity", "total_equity"))
    debt = _num(_pick(form, "totalDebt", "total_debt"))
    equity_debt = None
    if equity is not None or debt is not None:
        equity_debt = (equity or 0.0) + (debt or 0.0)

    share_price = _num(_pick(form, "sharePrice", "share_price"))
    shares = _num(_pick(form, "outstandingShares", "outstanding_shares"))
    minority = _num(_pick(form, "minorityInterest", "minority_interest")) or 0.0
    preferred = _num(_pick(form, "preferredStock", "preferred_stock")) or 0.0
    total_debt = _num(_pick(form, "totalDebt", "total_debt")) or 0.0
    evic = None
    if share_price is not None and shares is not None:
        evic = share_price * shares + total_debt + minority + preferred
    elif _num(_pick(form, "evic", "EVIC")) is not None:
        evic = _num(_pick(form, "evic", "EVIC"))
    return equity_debt, evic


def _loan_pool_membership(
    pools: Sequence[Dict[str, Any]],
) -> Dict[str, List[Tuple[str, Optional[float]]]]:
    """loan_id -> [(pool_id, amount_in_pool), ...]"""
    membership: Dict[str, List[Tuple[str, Optional[float]]]] = {}
    for pool in pools:
        pid = _text(_pick(pool, "poolId", "pool_id"))
        allocations = _pick(pool, "loanAllocations", "loan_allocations", default=None)
        if isinstance(allocations, list) and allocations:
            for row in allocations:
                if not isinstance(row, dict):
                    continue
                lid = _text(_pick(row, "loanId", "loan_id"))
                amt = _num(_pick(row, "amountInPool", "amount_in_pool"))
                if lid:
                    membership.setdefault(lid, []).append((pid, amt))
            continue
        for lid in _pick(pool, "loanIds", "loan_ids", default=[]) or []:
            membership.setdefault(_text(lid), []).append((pid, None))
    return membership


def resolve_laf(
    *,
    loan_id: str,
    loan_coa: Optional[float],
    pool_id: str,
    membership: Dict[str, List[Tuple[str, Optional[float]]]],
) -> Dict[str, Any]:
    entries = membership.get(loan_id) or []
    in_pool = [e for e in entries if e[0] == pool_id]
    if not in_pool:
        return {
            "status": "error",
            "code": "loan_not_in_pool",
            "laf": None,
            "message": f"Loan {loan_id} is not linked to pool {pool_id}.",
        }
    amount = in_pool[0][1]
    if amount is None:
        # Exclusive single-pool membership → treat full loan COA as in-pool (explicit exclusive link).
        if len(entries) == 1 and loan_coa is not None and loan_coa >= 0:
            amount = loan_coa
            inferred = True
        else:
            return {
                "status": "incomplete",
                "code": "missing_laf_amount",
                "laf": None,
                "message": (
                    f"Loan {loan_id}: amountInPool is required when the loan is in multiple pools "
                    "or loan COA is missing."
                ),
            }
    else:
        inferred = False

    if loan_coa is None or loan_coa <= 0:
        return {
            "status": "error",
            "code": "zero_denominator",
            "laf": None,
            "message": f"Loan {loan_id}: total loan COA must be > 0 for LAF.",
        }
    if amount < 0:
        return {
            "status": "error",
            "code": "negative_laf_amount",
            "laf": None,
            "message": f"Loan {loan_id}: amountInPool cannot be negative.",
        }
    if amount - loan_coa > 1e-9:
        return {
            "status": "error",
            "code": "laf_exceeds_loan",
            "laf": None,
            "message": f"Loan {loan_id}: amountInPool cannot exceed loan COA.",
        }
    return {
        "status": "complete",
        "laf": amount / loan_coa,
        "amount_in_pool": amount,
        "loan_coa": loan_coa,
        "inferred_full_allocation": inferred,
        "code": None,
        "message": None,
    }


def calculate_ssp_draft(
    draft: Dict[str, Any],
    *,
    holding_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Pure preview calculation over an SspDraft-shaped dict.

    Returns status complete|incomplete|unsupported|error with layer results.
    Never fabricates zero FE for missing inputs.
    """
    notes: List[str] = []
    warnings: List[str] = []
    deal = draft.get("deal") if isinstance(draft.get("deal"), dict) else {}
    eligibility = draft.get("eligibility") if isinstance(draft.get("eligibility"), dict) else {}
    emissions_path = _text(_pick(draft, "emissionsPath", "emissions_path") or _pick(deal, "emissionsPath"))
    structure_type = _text(_pick(deal, "structureType", "structure_type"))
    has_pop = _text(_pick(deal, "hasPoolOfPools", "has_pool_of_pools") or _pick(eligibility, "hasPoolOfPools"))
    has_tranches = _text(_pick(deal, "hasTranches", "has_tranches") or _pick(eligibility, "hasTranches"))
    pools_linked = _text(
        _pick(deal, "poolsLinkedToSpecificTranches") or _pick(eligibility, "poolsLinkedToSpecificTranches")
    )

    result: Dict[str, Any] = {
        "status": "incomplete",
        "code": None,
        "message": None,
        "methodology_version": SSP_METHODOLOGY_VERSION,
        "pcaf_ref": "PCAF 2025 Part A §5.8 / Tables 5.8-2 & 5.8-3",
        "formula_id": "ssp-lookthrough" if emissions_path != "reported_pool" else "ssp-reported-pool",
        "formula_name": "SSP preview (Phase 6C.1)",
        "emissions_path": emissions_path or None,
        "structure_type": structure_type or None,
        "emissions_unit": "tCO2e",
        "is_reportable": False,
        "include_in_portfolio": False,
        "financed_emissions": None,
        "scope_breakdown": {"scope1": None, "scope2": None, "scope3": None},
        "data_quality_score": None,
        "collateral": [],
        "loans": [],
        "pools": [],
        "tranches": [],
        "holdings": [],
        "notes": notes,
        "warnings": warnings,
        "provenance": {
            "phase": "6C.1",
            "preview": True,
            "reportable": False,
            "engine": "ssp_calc.calculate_ssp_draft",
        },
    }

    # --- Eligibility / structure gates ---
    if structure_type in BLOCKED_STRUCTURE_TYPES:
        return _fail(result, "unsupported", "unsupported_structure", f"Structure '{structure_type}' is deferred.")

    if structure_type and structure_type not in SUPPORTED_STRUCTURE_TYPES:
        return _fail(
            result,
            "unsupported",
            "unsupported_structure",
            f"Structure '{structure_type}' is not enabled for Phase 6C.1 preview calculate.",
        )

    pop = draft.get("poolOfPools") or draft.get("pool_of_pools")
    if has_pop == "yes" or (isinstance(pop, dict) and pop):
        return _fail(
            result,
            "unsupported",
            "unsupported_pool_of_pools",
            "Multi-pool / pool-of-pools calculation is deferred pending methodology confirmation (6C.0B Q1).",
        )

    if emissions_path not in ("lookthrough", "reported_pool"):
        return _fail(
            result,
            "incomplete",
            "missing_emissions_path",
            "Select look-through or reported-pool emissions path (mutually exclusive).",
        )

    collateral_rows = [c for c in (draft.get("collateral") or []) if isinstance(c, dict)]
    loan_rows = [ln for ln in (draft.get("loans") or []) if isinstance(ln, dict)]
    pool_rows = [p for p in (draft.get("pools") or []) if isinstance(p, dict)]
    tranche_rows = [t for t in (draft.get("tranches") or []) if isinstance(t, dict)]
    holding_rows = [h for h in (draft.get("holdings") or []) if isinstance(h, dict)]

    if len(pool_rows) != 1:
        return _fail(
            result,
            "unsupported" if len(pool_rows) > 1 else "incomplete",
            "single_pool_required",
            "Phase 6C.1 supports exactly one collateral pool (no multi-pool PoP).",
        )

    pool = pool_rows[0]
    pool_id = _text(_pick(pool, "poolId", "pool_id"))

    # Reported vs look-through exclusivity
    reported_total = _num(_pick(pool, "reportedEmissionsTotal", "reported_emissions_total"))
    if emissions_path == "lookthrough" and reported_total is not None:
        warnings.append("reportedEmissionsTotal is ignored on look-through path (exclusivity).")
    if emissions_path == "reported_pool":
        if reported_total is None:
            return _fail(
                result,
                "incomplete",
                "missing_reported_pool_emissions",
                "Reported-pool path requires pools[].reportedEmissionsTotal.",
            )
        if not _text(_pick(pool, "reportedSource", "reported_source")):
            return _fail(
                result,
                "incomplete",
                "missing_reported_source",
                "Reported-pool path requires evidence source (reportedSource).",
            )

    # --- Build loan -> collateral map ---
    col_by_id = {_text(_pick(c, "collateralId", "collateral_id")): c for c in collateral_rows}
    loan_by_id = {_text(_pick(ln, "loanId", "loan_id")): ln for ln in loan_rows}
    membership = _loan_pool_membership(pool_rows)

    # Duplicate relationship check
    for lid, entries in membership.items():
        pool_ids = [e[0] for e in entries]
        if len(pool_ids) != len(set(pool_ids)):
            return _fail(result, "error", "duplicate_relationship", f"Duplicate loan↔pool link for {lid}.")

    collateral_results: List[Dict[str, Any]] = []
    loan_results: List[Dict[str, Any]] = []
    linked_loan_ids: List[str] = list(
        dict.fromkeys(
            [_text(x) for x in (_pick(pool, "loanIds", "loan_ids", default=[]) or [])]
            + [lid for lid, entries in membership.items() if any(e[0] == pool_id for e in entries)]
        )
    )
    loan_fe_by_id: Dict[str, Dict[str, Any]] = {}

    if emissions_path == "lookthrough":
        # Absolute emissions per collateral
        abs_by_col: Dict[str, Dict[str, Any]] = {}
        for col in collateral_rows:
            abs_res = absolute_emissions_for_collateral(col)
            collateral_results.append(abs_res)
            abs_by_col[_text(_pick(col, "collateralId", "collateral_id"))] = abs_res
            if abs_res["status"] == "unsupported":
                return _fail(result, "unsupported", abs_res.get("code") or "unsupported", abs_res.get("message") or "")
            if abs_res["status"] != "complete":
                result["collateral"] = collateral_results
                return _fail(
                    result,
                    "incomplete",
                    abs_res.get("code") or "incomplete_underlying",
                    abs_res.get("message") or "Underlying absolute emissions incomplete.",
                )

        # Loan FE = Σ absolute × CAF
        for loan in loan_rows:
            lid = _text(_pick(loan, "loanId", "loan_id"))
            loan_coa = _num(_pick(loan, "currentOutstandingAmount", "current_outstanding_amount"))
            loan_ooa = _num(_pick(loan, "originalOutstandingAmount", "original_outstanding_amount"))
            col_ids = [_text(x) for x in (_pick(loan, "collateralIds", "collateral_ids", default=[]) or [])]
            if not col_ids:
                return _fail(result, "incomplete", "loan_missing_collateral", f"Loan {lid} has no collateralIds.")
            parts = []
            s1 = s2 = s3 = 0.0
            has_s3 = False
            dq_weights: List[Tuple[float, float]] = []
            for cid in col_ids:
                col = col_by_id.get(cid)
                if not col:
                    return _fail(result, "error", "unknown_association", f"Loan {lid} references missing collateral {cid}.")
                abs_res = abs_by_col[cid]
                ctype = _text(_pick(col, "collateralType", "collateral_type"))
                class_inputs = _pick(col, "classInputs", "class_inputs", default={}) or {}
                if not isinstance(class_inputs, dict):
                    class_inputs = {}
                equity_debt, evic = _company_denoms(class_inputs)
                avo = _num(
                    _pick(col, "assetValueAtOrigination", "asset_value_at_origination", "attributionDenominator")
                )
                uav = _num(_pick(col, "updatedAssetValue", "updated_asset_value"))
                caf_res = compute_caf(
                    collateral_type=ctype,
                    loan_coa=loan_coa,
                    loan_ooa=loan_ooa,
                    avo=avo,
                    uav=uav,
                    equity_plus_debt=equity_debt,
                    evic=evic,
                )
                if caf_res["status"] != "complete":
                    result["collateral"] = collateral_results
                    return _fail(
                        result,
                        caf_res["status"],
                        caf_res.get("code") or "caf_error",
                        caf_res.get("message") or "CAF failed.",
                        extra={"loan_id": lid, "collateral_id": cid, "caf": caf_res},
                    )
                caf = float(caf_res["caf"])
                abs_total = float(abs_res["absolute_total_tco2e"])
                fe = abs_total * caf
                parts.append(
                    {
                        "collateral_id": cid,
                        "collateral_type": ctype,
                        "absolute_total_tco2e": _round(abs_total),
                        "caf": _round(caf),
                        "caf_basis": caf_res.get("caf_basis"),
                        "caf_capped": caf_res.get("caf_capped"),
                        "financed_emissions_tco2e": _round(fe),
                        "absolute_scope1_tco2e": abs_res.get("absolute_scope1_tco2e"),
                        "absolute_scope2_tco2e": abs_res.get("absolute_scope2_tco2e"),
                        "absolute_scope3_tco2e": abs_res.get("absolute_scope3_tco2e"),
                    }
                )
                s1 += float(abs_res.get("absolute_scope1_tco2e") or 0.0) * caf
                s2 += float(abs_res.get("absolute_scope2_tco2e") or 0.0) * caf
                if abs_res.get("absolute_scope3_tco2e") is not None:
                    has_s3 = True
                    s3 += float(abs_res["absolute_scope3_tco2e"]) * caf
                dq = abs_res.get("data_quality_score")
                if dq is not None and loan_coa:
                    dq_weights.append((loan_coa, float(dq)))

            loan_fe = sum(float(p["financed_emissions_tco2e"]) for p in parts)
            loan_results.append(
                {
                    "loan_id": lid,
                    "status": "complete",
                    "financed_emissions_tco2e": _round(loan_fe),
                    "scope1_tco2e": _round(s1),
                    "scope2_tco2e": _round(s2),
                    "scope3_tco2e": _round(s3) if has_s3 else None,
                    "current_outstanding_amount": loan_coa,
                    "collateral_parts": parts,
                    "data_quality_score": _coa_weighted(dq_weights),
                }
            )

        loan_fe_by_id = {r["loan_id"]: r for r in loan_results}

        # Pool aggregation via LAF
        pool_fe = 0.0
        pool_s1 = pool_s2 = pool_s3 = 0.0
        pool_has_s3 = False
        laf_rows = []
        dq_weights = []
        if not linked_loan_ids:
            return _fail(result, "incomplete", "pool_missing_loans", "Pool has no linked loans.")

        for lid in linked_loan_ids:
            loan_res = loan_fe_by_id.get(lid)
            if not loan_res:
                return _fail(result, "error", "unknown_association", f"Pool references missing loan {lid}.")
            laf_res = resolve_laf(
                loan_id=lid,
                loan_coa=loan_res.get("current_outstanding_amount"),
                pool_id=pool_id,
                membership=membership,
            )
            if laf_res["status"] != "complete":
                result["collateral"] = collateral_results
                result["loans"] = loan_results
                return _fail(
                    result,
                    laf_res["status"],
                    laf_res.get("code") or "laf_error",
                    laf_res.get("message") or "LAF failed.",
                    extra={"laf": laf_res},
                )
            if laf_res.get("inferred_full_allocation"):
                notes.append(f"LAF for {lid}: full allocation inferred from exclusive single-pool membership.")
            laf = float(laf_res["laf"])
            contrib = float(loan_res["financed_emissions_tco2e"]) * laf
            pool_fe += contrib
            pool_s1 += float(loan_res.get("scope1_tco2e") or 0.0) * laf
            pool_s2 += float(loan_res.get("scope2_tco2e") or 0.0) * laf
            if loan_res.get("scope3_tco2e") is not None:
                pool_has_s3 = True
                pool_s3 += float(loan_res["scope3_tco2e"]) * laf
            laf_rows.append(
                {
                    "loan_id": lid,
                    "laf": _round(laf),
                    "amount_in_pool": laf_res.get("amount_in_pool"),
                    "contribution_tco2e": _round(contrib),
                }
            )
            dq = loan_res.get("data_quality_score")
            coa = loan_res.get("current_outstanding_amount")
            if dq is not None and coa:
                dq_weights.append((float(coa) * laf, float(dq)))

        pool_result = {
            "pool_id": pool_id,
            "status": "complete",
            "path": "lookthrough",
            "financed_emissions_tco2e": _round(pool_fe),
            "scope1_tco2e": _round(pool_s1),
            "scope2_tco2e": _round(pool_s2),
            "scope3_tco2e": _round(pool_s3) if pool_has_s3 else None,
            "laf_rows": laf_rows,
            "data_quality_score": _coa_weighted(dq_weights),
        }
    else:
        # Reported pool path — no underlying / CAF / LAF
        pool_fe = float(reported_total)
        pool_result = {
            "pool_id": pool_id,
            "status": "complete",
            "path": "reported_pool",
            "financed_emissions_tco2e": _round(pool_fe),
            "scope1_tco2e": None,
            "scope2_tco2e": None,
            "scope3_tco2e": None,
            "reported_emissions_total": reported_total,
            "reported_source": _text(_pick(pool, "reportedSource", "reported_source")),
            "reported_period": _text(_pick(pool, "reportedEmissionsPeriod", "reported_emissions_period")),
            "data_quality_score": 2.0,
            "laf_rows": [],
        }
        notes.append("Reported-pool path: issuer/servicer pool FE used; look-through not applied.")

    # --- Tranches / TAF ---
    untranched = has_tranches == "no" or (has_tranches != "yes" and not tranche_rows)
    if untranched:
        # Synthetic single tranche covering the holding investment / pool
        synth_coa = None
        if holding_rows:
            # Deal COA for untranched = sum of holding investments or explicit tranche if any
            synth_coa = sum(
                _num(_pick(h, "bankOutstandingInvestment", "bank_outstanding_investment")) or 0.0
                for h in holding_rows
            )
        if not synth_coa:
            synth_coa = _num(_pick(pool, "poolCurrentOutstandingAmount", "pool_current_outstanding_amount"))
        if not synth_coa or synth_coa <= 0:
            # Fall back to sum of loan COAs in pool
            synth_coa = 0.0
            for lid in linked_loan_ids if emissions_path == "lookthrough" else []:
                synth_coa += float(loan_fe_by_id[lid].get("current_outstanding_amount") or 0.0)
        if emissions_path == "reported_pool" and (not synth_coa or synth_coa <= 0):
            synth_coa = sum(
                _num(_pick(h, "bankOutstandingInvestment", "bank_outstanding_investment")) or 0.0
                for h in holding_rows
            ) or None
        if not synth_coa or synth_coa <= 0:
            result["collateral"] = collateral_results
            result["loans"] = loan_results
            result["pools"] = [pool_result]
            return _fail(
                result,
                "incomplete",
                "missing_untranched_deal_coa",
                "Untranched structure needs tranche/holding/pool COA to form Deal COA for TAF.",
            )
        tranche_rows = [
            {
                "trancheId": "__untranched__",
                "name": "Untranched",
                "currentOutstandingAmount": synth_coa,
                "linkedPoolIds": [pool_id],
            }
        ]
        notes.append("Untranched: synthetic TAF=1 using Deal COA = synthetic tranche COA.")

    # Tranche-specific pools: only allow links to the single pool
    tranche_results = []
    deal_coa = 0.0
    usable_tranches: List[Dict[str, Any]] = []
    for tr in tranche_rows:
        tid = _text(_pick(tr, "trancheId", "tranche_id"))
        tcoa = _num(_pick(tr, "currentOutstandingAmount", "current_outstanding_amount"))
        linked = [_text(x) for x in (_pick(tr, "linkedPoolIds", "linked_pool_ids", default=[]) or [])]
        if pools_linked == "yes" and linked and pool_id not in linked:
            warnings.append(f"Tranche {tid} not linked to the sole pool — excluded from this graph.")
            continue
        if tcoa is None or tcoa < 0:
            result["collateral"] = collateral_results
            result["loans"] = loan_results
            result["pools"] = [pool_result]
            return _fail(result, "incomplete", "missing_tranche_coa", f"Tranche {tid} needs COA >= 0.")
        if tcoa == 0:
            warnings.append(f"Tranche {tid} has zero COA — TAF share will be 0.")
        deal_coa += tcoa
        usable_tranches.append({"tranche_id": tid, "coa": tcoa, "raw": tr})

    if deal_coa <= 0:
        return _fail(result, "error", "zero_denominator", "Applicable deal COA (Σ tranche COA) must be > 0.")

    pool_fe_val = float(pool_result["financed_emissions_tco2e"])
    sum_tranche_fe = 0.0
    for tr in usable_tranches:
        taf = tr["coa"] / deal_coa
        fe = taf * pool_fe_val
        sum_tranche_fe += fe
        # Scope split proportional for look-through
        scope_scale = taf
        tranche_results.append(
            {
                "tranche_id": tr["tranche_id"],
                "status": "complete",
                "taf": _round(taf),
                "tranche_coa": tr["coa"],
                "deal_coa": deal_coa,
                "financed_emissions_tco2e": _round(fe),
                "scope1_tco2e": _round(float(pool_result["scope1_tco2e"]) * scope_scale)
                if pool_result.get("scope1_tco2e") is not None
                else None,
                "scope2_tco2e": _round(float(pool_result["scope2_tco2e"]) * scope_scale)
                if pool_result.get("scope2_tco2e") is not None
                else None,
                "scope3_tco2e": _round(float(pool_result["scope3_tco2e"]) * scope_scale)
                if pool_result.get("scope3_tco2e") is not None
                else None,
            }
        )

    # Conservation check
    if abs(sum_tranche_fe - pool_fe_val) > max(1e-6, abs(pool_fe_val) * 1e-9):
        return _fail(
            result,
            "error",
            "taf_conservation_failed",
            f"Σ tranche FE ({sum_tranche_fe}) != pool FE ({pool_fe_val}).",
        )

    tranche_by_id = {t["tranche_id"]: t for t in tranche_results}

    # --- Holdings / IAF ---
    if not holding_rows:
        return _fail(result, "incomplete", "missing_holding", "At least one bank holding is required.")

    holding_results = []
    target_holdings = holding_rows
    if holding_id:
        target_holdings = [
            h
            for h in holding_rows
            if _text(_pick(h, "holdingId", "holding_id")) == holding_id
            or _text(_pick(h, "financingInstanceId", "financing_instance_id")) == holding_id
        ]
        if not target_holdings:
            return _fail(result, "error", "holding_not_found", f"Holding '{holding_id}' not found in draft.")

    for holding in target_holdings:
        hid = _text(_pick(holding, "holdingId", "holding_id"))
        inv = _num(_pick(holding, "bankOutstandingInvestment", "bank_outstanding_investment"))
        if inv is None or inv < 0:
            return _fail(
                result,
                "incomplete",
                "missing_investment",
                f"Holding {hid} needs bankOutstandingInvestment >= 0.",
            )
        tid = _text(_pick(holding, "trancheId", "tranche_id"))
        if untranched or tid in ("", "__untranched__"):
            tid = tranche_results[0]["tranche_id"]
        tr = tranche_by_id.get(tid)
        if not tr:
            return _fail(result, "error", "unknown_association", f"Holding {hid} references missing tranche {tid}.")
        tcoa = float(tr["tranche_coa"])
        if tcoa <= 0:
            return _fail(result, "error", "zero_denominator", f"Tranche {tid} COA must be > 0 for IAF.")
        if inv - tcoa > 1e-9:
            warnings.append(f"Holding {hid} investment exceeds tranche COA — IAF will exceed 1.")
        iaf = inv / tcoa
        fe = iaf * float(tr["financed_emissions_tco2e"])
        holding_results.append(
            {
                "holding_id": hid,
                "tranche_id": tid,
                "status": "complete",
                "iaf": _round(iaf),
                "investment_coa": inv,
                "tranche_coa": tcoa,
                "financed_emissions_tco2e": _round(fe),
                "scope1_tco2e": _round(float(tr["scope1_tco2e"]) * iaf) if tr.get("scope1_tco2e") is not None else None,
                "scope2_tco2e": _round(float(tr["scope2_tco2e"]) * iaf) if tr.get("scope2_tco2e") is not None else None,
                "scope3_tco2e": _round(float(tr["scope3_tco2e"]) * iaf) if tr.get("scope3_tco2e") is not None else None,
            }
        )

    primary = holding_results[0]
    result.update(
        {
            "status": "complete",
            "code": None,
            "message": None,
            "financed_emissions": primary["financed_emissions_tco2e"],
            "scope_breakdown": {
                "scope1": primary.get("scope1_tco2e"),
                "scope2": primary.get("scope2_tco2e"),
                "scope3": primary.get("scope3_tco2e"),
            },
            "data_quality_score": pool_result.get("data_quality_score"),
            "iaf": primary.get("iaf"),
            "taf": tranche_by_id[primary["tranche_id"]].get("taf"),
            "collateral": collateral_results,
            "loans": loan_results,
            "pools": [pool_result],
            "tranches": tranche_results,
            "holdings": holding_results,
            "deal_coa": deal_coa,
            "pool_financed_emissions": pool_result.get("financed_emissions_tco2e"),
        }
    )
    return result


def _coa_weighted(pairs: List[Tuple[float, float]]) -> Optional[float]:
    """COA-weighted DQ only — no equal-weight fallback."""
    total_w = sum(w for w, _ in pairs if w and w > 0)
    if total_w <= 0:
        return None
    return round(sum(w * score for w, score in pairs if w and w > 0) / total_w, 4)


def _fail(
    result: Dict[str, Any],
    status: str,
    code: str,
    message: str,
    *,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    result["status"] = status
    result["code"] = code
    result["message"] = message
    result["financed_emissions"] = None
    if extra:
        result["error_details"] = extra
    return result
