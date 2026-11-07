"""
Nested Use of Proceeds look-through (PCAF 2025 Part A §5.7).

A UoP structure may hold another UoP structure. Emissions are not invented at
the intermediate layer: look through to the child structure's financed objects,
apply the child object-level attribution once, then apply the parent
allocation to that child once. Circular references and duplicate child
exposure IDs are rejected.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

COMPLETE = "complete"
INCOMPLETE = "incomplete"
UNSUPPORTED = "unsupported"


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


def child_structure_identity(asset: Dict[str, Any], estimation: Dict[str, Any]) -> str:
    return _text(
        _pick(
            asset,
            "childStructureId",
            "child_structure_id",
            "nestedStructureId",
            "nested_structure_id",
            "childFinancingInstanceId",
            "child_financing_instance_id",
        )
        or _pick(
            estimation,
            "childStructureId",
            "child_structure_id",
            "nestedStructureId",
            "nested_structure_id",
            "childFinancingInstanceId",
            "child_financing_instance_id",
        )
    )


def extract_child_assets(asset: Dict[str, Any], estimation: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = _pick(asset, "childAssets", "child_assets", "nestedAssets", "nested_assets")
    if raw is None:
        raw = _pick(estimation, "childAssets", "child_assets", "nestedAssets", "nested_assets")
    if not isinstance(raw, list):
        return []
    return [row for row in raw if isinstance(row, dict)]


def child_total_capital(asset: Dict[str, Any], estimation: Dict[str, Any], child_assets: List[Dict[str, Any]]) -> Optional[float]:
    explicit = _num(
        _pick(
            asset,
            "childTotalCapital",
            "child_total_capital",
            "totalAssetValue",
            "total_asset_value",
        )
        or _pick(estimation, "childTotalCapital", "child_total_capital")
    )
    if explicit is not None and explicit > 0:
        return explicit
    debt = _num(_pick(estimation, "childTotalDebt", "child_total_debt", "totalStructureDebt"))
    equity = _num(_pick(estimation, "childTotalEquity", "child_total_equity", "totalStructureEquity"))
    if debt is not None or equity is not None:
        total = (debt or 0.0) + max(0.0, equity or 0.0)
        return total if total > 0 else None
    # Fall back to sum of child allocated outstanding only when no capital is given.
    allocated_sum = 0.0
    any_allocated = False
    for row in child_assets:
        value = _num(_pick(row, "allocatedOutstanding", "allocated_outstanding"))
        if value is not None:
            any_allocated = True
            allocated_sum += value
    return allocated_sum if any_allocated and allocated_sum > 0 else None


def detect_circular_nested(
    *,
    parent_id: str,
    child_id: str,
    stack: Set[str],
) -> Optional[str]:
    if not child_id:
        return None
    if child_id == parent_id:
        return "A Use of Proceeds structure cannot nest itself."
    if child_id in stack:
        return (
            "Circular nested Use of Proceeds reference detected. "
            "Each structure may appear once in the look-through path."
        )
    return None


def detect_duplicate_nested_ids(child_assets: List[Dict[str, Any]]) -> Optional[str]:
    seen: Set[str] = set()
    for row in child_assets:
        asset_id = _text(_pick(row, "underlyingAssetId", "underlying_asset_id"))
        if not asset_id:
            continue
        if asset_id in seen:
            return (
                f"Duplicate nested underlying asset id '{asset_id}'. "
                "The same exposure cannot be counted through multiple nested paths."
            )
        seen.add(asset_id)
    return None


def calculate_nested_uop_asset(
    result: Dict[str, Any],
    *,
    asset: Dict[str, Any],
    estimation: Dict[str, Any],
    allocated: float,
    name: str,
    parent_identity: str,
    visited: Optional[Set[str]] = None,
    calculate_child_asset,
    db: Any = None,
    organization_id: Any = None,
    reporting_year: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Look through a child UoP structure's underlying assets.

    Parent object attribution = allocated_to_child / child_total_capital.
    Child object attributions are applied inside calculate_child_asset.
    Investor attribution is applied later by uop_calc._scale_asset.
    """
    stack = set(visited or set())
    child_id = child_structure_identity(asset, estimation) or _text(
        _pick(asset, "underlyingAssetId", "underlying_asset_id")
    )
    circular = detect_circular_nested(parent_id=parent_identity, child_id=child_id, stack=stack)
    if circular:
        result.update(
            {
                "status": UNSUPPORTED,
                "code": "circular_nested_uop",
                "message": f"{name}: {circular}",
                "structure_financed_emissions": None,
            }
        )
        return result

    child_assets = extract_child_assets(asset, estimation)
    if not child_assets:
        result.update(
            {
                "status": INCOMPLETE,
                "code": "missing_nested_child_assets",
                "message": (
                    f"{name}: nested Use of Proceeds needs the child structure's "
                    "funded assets (look-through). PCAF §5.7 does not provide a "
                    "collapsed single-number nested formula."
                ),
                "structure_financed_emissions": None,
            }
        )
        return result

    duplicate = detect_duplicate_nested_ids(child_assets)
    if duplicate:
        result.update(
            {
                "status": UNSUPPORTED,
                "code": "duplicate_nested_exposure",
                "message": f"{name}: {duplicate}",
                "structure_financed_emissions": None,
            }
        )
        return result

    capital = child_total_capital(asset, estimation, child_assets)
    if capital is None or capital <= 0:
        result.update(
            {
                "status": INCOMPLETE,
                "code": "missing_child_capital",
                "message": (
                    f"{name}: enter the child structure's total capital "
                    "(loans/bonds + shares, or total assets) so the parent "
                    "allocation attribution can be applied once."
                ),
                "structure_financed_emissions": None,
            }
        )
        return result

    next_stack = set(stack)
    if parent_identity:
        next_stack.add(parent_identity)
    if child_id:
        next_stack.add(child_id)

    child_results: List[Dict[str, Any]] = []
    structure_fe = 0.0
    structure_s1 = 0.0
    structure_s2 = 0.0
    structure_s3 = 0.0
    have_s1 = have_s2 = have_s3 = False
    dq_weights: List[float] = []
    dq_scores: List[float] = []

    for child in child_assets:
        child_class = _text(_pick(child, "assetClass", "asset_class"))
        if child_class in ("use-of-proceeds", "uop"):
            nested = calculate_nested_uop_asset(
                {
                    "underlying_asset_id": _text(_pick(child, "underlyingAssetId", "underlying_asset_id")),
                    "name": _text(_pick(child, "name")) or "Nested child",
                    "asset_class": child_class,
                    "allocated_outstanding": _num(_pick(child, "allocatedOutstanding", "allocated_outstanding")),
                    "status": COMPLETE,
                },
                asset=child,
                estimation=_pick(child, "estimation", default={}) or {},
                allocated=_num(_pick(child, "allocatedOutstanding", "allocated_outstanding")) or 0.0,
                name=_text(_pick(child, "name")) or "Nested child",
                parent_identity=child_id or parent_identity,
                visited=next_stack,
                calculate_child_asset=calculate_child_asset,
                db=db,
                organization_id=organization_id,
                reporting_year=reporting_year,
            )
            child_results.append(nested)
        else:
            child_results.append(
                calculate_child_asset(
                    child,
                    db=db,
                    organization_id=organization_id,
                    reporting_year=reporting_year,
                )
            )

    for child_result in child_results:
        if child_result.get("status") != COMPLETE:
            result.update(
                {
                    "status": child_result.get("status") or INCOMPLETE,
                    "code": child_result.get("code") or "nested_child_incomplete",
                    "message": (
                        f"{name}: child look-through incomplete — "
                        f"{child_result.get('message') or child_result.get('name') or 'child asset'}"
                    ),
                    "structure_financed_emissions": None,
                    "nested_assets": child_results,
                }
            )
            return result
        fe = child_result.get("structure_financed_emissions")
        if fe is None:
            result.update(
                {
                    "status": INCOMPLETE,
                    "code": "nested_child_missing_total",
                    "message": f"{name}: a child asset is missing structure financed emissions.",
                    "structure_financed_emissions": None,
                    "nested_assets": child_results,
                }
            )
            return result
        structure_fe += float(fe)
        if child_result.get("structure_scope1_tco2e") is not None:
            structure_s1 += float(child_result["structure_scope1_tco2e"])
            have_s1 = True
        if child_result.get("structure_scope2_tco2e") is not None:
            structure_s2 += float(child_result["structure_scope2_tco2e"])
            have_s2 = True
        if child_result.get("structure_scope3_tco2e") is not None:
            structure_s3 += float(child_result["structure_scope3_tco2e"])
            have_s3 = True
        if child_result.get("data_quality_score") is not None:
            weight = float(child_result.get("allocated_outstanding") or 0.0)
            dq_weights.append(weight if weight > 0 else 1.0)
            dq_scores.append(float(child_result["data_quality_score"]))

    parent_af = allocated / capital
    result.update(
        {
            "status": COMPLETE,
            "asset_attribution_factor": parent_af,
            "denominator": capital,
            "denominator_kind": "child_total_capital",
            "denominator_label": "Child structure total capital",
            "structure_scope1_tco2e": (parent_af * structure_s1) if have_s1 else None,
            "structure_scope2_tco2e": (parent_af * structure_s2) if have_s2 else None,
            "structure_scope3_tco2e": (parent_af * structure_s3) if have_s3 else None,
            "structure_unallocated_tco2e": None,
            "structure_financed_emissions": parent_af * structure_fe,
            "data_quality_score": (
                sum(w * s for w, s in zip(dq_weights, dq_scores)) / sum(dq_weights)
                if dq_weights and sum(dq_weights) > 0
                else None
            ),
            "option_code": "nested-lookthrough",
            "estimated": any(bool(row.get("estimated")) for row in child_results),
            "reused_formula_id": "uop-nested-lookthrough",
            "reused_methodology": (
                "PCAF §5.7 nested UoP look-through: child object attributions "
                "applied once, then parent allocation / child capital applied once. "
                "No collapsed nested formula."
            ),
            "nested_assets": child_results,
            "child_structure_id": child_id or None,
        }
    )
    return result
