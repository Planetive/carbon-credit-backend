"""Reporting period helpers for verified Scope 3 activities (YYYY-MM)."""

from __future__ import annotations

from typing import Optional, Tuple

_YEAR_MIN = 1990
_YEAR_MAX = 2200


def parse_period_month(value: Optional[str]) -> Optional[Tuple[int, int]]:
    """Return (year, month) for YYYY-MM only. Reject YYYY-only and malformed strings."""
    text = (value or "").strip()
    if len(text) != 7 or text[4] != "-":
        return None
    if not (text[:4].isdigit() and text[5:].isdigit()):
        return None
    year = int(text[:4])
    month = int(text[5:])
    if year < _YEAR_MIN or year > _YEAR_MAX:
        return None
    if month < 1 or month > 12:
        return None
    return year, month


def parse_assessment_reporting_year(value: Optional[str]) -> Optional[int]:
    """Assessment reporting_period may be YYYY or YYYY-MM."""
    text = (value or "").strip()
    if len(text) == 4 and text.isdigit():
        year = int(text)
        if _YEAR_MIN <= year <= _YEAR_MAX:
            return year
        return None
    parsed = parse_period_month(text)
    return parsed[0] if parsed else None


def period_matches_assessment(period: Optional[str], assessment_reporting_period: Optional[str]) -> bool:
    parsed = parse_period_month(period)
    if parsed is None:
        return False
    assess_year = parse_assessment_reporting_year(assessment_reporting_period)
    if assess_year is None:
        return False
    return parsed[0] == assess_year


def period_error(period: Optional[str], assessment_reporting_period: Optional[str]) -> Optional[str]:
    if parse_period_month(period) is None:
        return "period must be YYYY-MM matching a valid calendar month"
    if parse_assessment_reporting_year(assessment_reporting_period) is None:
        return "assessment reporting year is missing or malformed"
    if not period_matches_assessment(period, assessment_reporting_period):
        return f"period {period} does not match the assessment reporting year"
    return None
