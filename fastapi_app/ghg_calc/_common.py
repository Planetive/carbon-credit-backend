"""Shared helpers for GHG calc parsers (SPA parity)."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence


def parse_number(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        n = float(value)
        return n if n == n and abs(n) != float("inf") else None
    if value is None:
        return None
    cleaned = str(value).replace(",", "")
    try:
        n = float(cleaned)
    except (TypeError, ValueError):
        return None
    return n if n == n and abs(n) != float("inf") else None


def norm_cell(value: Any) -> str:
    return str(value if value is not None else "").strip()


def round6(value: float) -> float:
    """SPA Number(x.toFixed(6))."""
    return float(f"{value:.6f}")


def pick_first_key(row: Dict[str, Any], patterns: Sequence[str]) -> Any:
    """Return first column value whose key matches any regex pattern."""
    keys = list(row.keys())
    for pat in patterns:
        rx = re.compile(pat, re.IGNORECASE)
        for k in keys:
            if rx.search(str(k)):
                return row[k]
    return None


def pick_number(row: Dict[str, Any], patterns: Sequence[str]) -> Optional[float]:
    return parse_number(pick_first_key(row, patterns))


def pick_first_value(row: Dict[str, Any], patterns: Sequence[str]) -> Any:
    return pick_first_key(row, patterns)


def success_payload(
    emissions_kg: float,
    *,
    factor: Optional[float] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "success": True,
        "emissions": emissions_kg,
        "emissions_kg": emissions_kg,
        "emissions_tco2e": float(f"{(emissions_kg / 1000.0):.9f}"),
        "factor": factor,
    }
    if extra:
        out.update(extra)
    return out


def fail_payload(error: str, **extra: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "success": False,
        "error": error,
        "emissions": None,
        "emissions_kg": None,
        "emissions_tco2e": None,
        "factor": None,
    }
    out.update(extra)
    return out
