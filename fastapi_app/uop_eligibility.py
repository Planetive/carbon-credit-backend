"""
PCAF 2025 Part A Figure 5.7-2 eligibility. Mirrors the frontend resolver.
Does not calculate emissions.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


PCAF_UOP_REF = "PCAF Part A 2025, §5.7 / Figure 5.7-2"
PCAF_FIGURE_5_1_REF = "PCAF Part A 2025, Figure 5-1"


def _yes(value: Any) -> bool:
    return str(value or "").strip().lower() == "yes"


def _no(value: Any) -> bool:
    return str(value or "").strip().lower() == "no"


def resolve_uop_accounting(answers: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    answers = answers or {}
    proceeds = answers.get("proceedsAllocatedToSpecificAssets")
    if not proceeds:
        return None
    if _no(proceeds):
        return {
            "kind": "not-uop",
            "method": "customer-segment",
            "title": "Not a use-of-proceeds structure",
            "pcafRef": f"{PCAF_UOP_REF} Question 1; Table 5.7-1",
        }

    if not answers.get("isSecuritized"):
        return None
    if _yes(answers.get("isSecuritized")):
        return {
            "kind": "other-method",
            "method": "securitization-structured-products",
            "title": "Account as securitization or structured product",
            "pcafRef": f"{PCAF_FIGURE_5_1_REF} Steps 3b and 4b",
        }

    if not answers.get("structureHasControl"):
        return None
    if _yes(answers.get("structureHasControl")):
        if not answers.get("controlOneFullyAllocatedAsset"):
            return None
        if _yes(answers.get("controlOneFullyAllocatedAsset")):
            if not answers.get("controlAssetIsProject"):
                return None
            if _yes(answers.get("controlAssetIsProject")):
                return {
                    "kind": "other-method",
                    "method": "project-finance",
                    "title": "Account as project finance",
                    "pcafRef": f"{PCAF_UOP_REF} Question 2 exception; Table 5.7-1",
                }
        if not answers.get("structureListing"):
            return None
        if str(answers.get("structureListing")) == "listed":
            return {
                "kind": "other-method",
                "method": "listed-equity-corporate-bonds",
                "title": "Account as listed equity or corporate bonds",
                "pcafRef": f"{PCAF_UOP_REF} Question 2; Table 5.7-1",
            }
        return {
            "kind": "other-method",
            "method": "business-loans-unlisted-equity",
            "title": "Account as business loans and unlisted equity",
            "pcafRef": f"{PCAF_UOP_REF} Question 2; Table 5.7-1",
        }

    if not answers.get("debtBasedWithOneFullyAllocatedAsset"):
        return None
    if _yes(answers.get("debtBasedWithOneFullyAllocatedAsset")):
        asset_class = str(answers.get("singleAssetClass") or "")
        if not asset_class:
            return None
        mapping = {
            "mortgage": "mortgages",
            "commercial-real-estate": "commercial-real-estate",
            "motor-vehicle-loan": "motor-vehicle-loans",
            "project-finance": "project-finance",
            "other": "figure-5-1-step-6",
        }
        method = mapping.get(asset_class, "figure-5-1-step-6")
        return {
            "kind": "other-method",
            "method": method,
            "title": f"Account as {method.replace('-', ' ')}",
            "pcafRef": f"{PCAF_UOP_REF} Question 3; Table 5.7-1",
        }

    if not answers.get("assetsOnIssuerBalanceSheet"):
        return None
    if _yes(answers.get("assetsOnIssuerBalanceSheet")):
        return {
            "kind": "uop",
            "classification": "integrated",
            "title": "Integrated use-of-proceeds structure",
            "pcafRef": f"{PCAF_UOP_REF} Question 4",
        }
    return {
        "kind": "uop",
        "classification": "separate",
        "title": "Separate use-of-proceeds structure",
        "pcafRef": f"{PCAF_UOP_REF} Question 4; footnote 167",
    }


def uop_qualifies(outcome: Optional[Dict[str, Any]]) -> bool:
    return bool(outcome and outcome.get("kind") == "uop")
