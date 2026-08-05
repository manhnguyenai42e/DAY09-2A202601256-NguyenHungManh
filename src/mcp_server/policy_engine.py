"""Deterministic implementation of EC_POLICY_V2 (README.md section 4).

All arithmetic, joins and evidence-ID formatting live here as tested, pure
Python so grading-critical values never depend on LLM arithmetic. Agents call
these functions (via the MCP server) to ground their handoffs; the policy
table itself is applied exactly as specified, in priority order.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from src.config import LIMITS
from src.data import loader

ROOT_CAUSE = {
    "late_delivery_seller": "SELLER_HANDOFF_AFTER_LIMIT",
    "late_delivery_logistics": "CARRIER_DELIVERED_AFTER_ESTIMATE",
    "canceled_order_paid": "ORDER_CANCELED_AFTER_PAYMENT",
    "unavailable_order_paid": "ORDER_UNAVAILABLE_AFTER_PAYMENT",
    "valid_split_payment": "MULTIPLE_PAYMENTS_RECONCILED",
    "unsupported_late_claim": "DELIVERY_WITHIN_ESTIMATE",
}


def round2(x: float | None) -> float | None:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    return round(float(x), 2)


def fmt_ts(ts) -> str | None:
    if ts is None or pd.isna(ts):
        return None
    return ts.strftime("%Y-%m-%d %H:%M:%S")


def hours_between(a, b) -> float | None:
    """(a - b) in hours, rounded to 2 decimals. None if either side is missing."""
    if a is None or b is None or pd.isna(a) or pd.isna(b):
        return None
    delta = (a - b).total_seconds() / 3600.0
    return round2(delta)


def truncate(items: list, key: str) -> list:
    return items[: LIMITS[key]]


# ---------------------------------------------------------------------------
# Fact builders (each maps to one domain agent's responsibility)
# ---------------------------------------------------------------------------


def build_affected_entities(order_id: str, items: pd.DataFrame) -> dict[str, Any]:
    seller_ids = list(dict.fromkeys(items["seller_id"].tolist()))
    item_ids = [f"{order_id}:{int(row.order_item_id)}" for row in items.itertuples()]
    return {
        "order_ids": [order_id],
        "item_ids": truncate(item_ids, "item_ids"),
        "seller_ids": truncate(seller_ids, "seller_ids"),
        # payment_ids filled in by build_payment_reconciliation's caller (needs payments df)
    }


def build_customer_context(order_id: str, order_row: pd.Series) -> dict[str, Any]:
    customer = loader.get_customer_row(order_row["customer_id"])
    if customer is None:
        return {"customer_unique_id": None, "related_order_ids": []}
    customer_unique_id = customer["customer_unique_id"]
    related = loader.get_related_order_ids(customer_unique_id, exclude_order_id=order_id)
    return {
        "customer_unique_id": customer_unique_id,
        "related_order_ids": truncate(related, "related_order_ids"),
    }


def build_product_context(items: pd.DataFrame) -> dict[str, Any]:
    product_ids = list(dict.fromkeys(items["product_id"].tolist()))
    products = loader.get_products(product_ids)
    products_by_id = {row["product_id"]: row for _, row in products.iterrows()}
    categories: list[str] = []
    for pid in product_ids:
        row = products_by_id.get(pid)
        if row is None:
            continue
        cat = loader.category_name_english(row.get("product_category_name"))
        if cat and cat not in categories:
            categories.append(cat)
    return {
        "product_ids": truncate(product_ids, "product_ids"),
        "category_names": truncate(categories, "category_names"),
    }


def build_delivery_analysis(order_row: pd.Series, items: pd.DataFrame) -> dict[str, Any]:
    delivered_at = order_row.get("order_delivered_customer_date")
    estimated_at = order_row.get("order_estimated_delivery_date")
    carrier_handoff_at = order_row.get("order_delivered_carrier_date")

    delivery_variance_hours = hours_between(delivered_at, estimated_at)

    seller_handoff_analysis = []
    late_handoff_seller_ids = []
    if not items.empty:
        for seller_id, group in items.groupby("seller_id", sort=False):
            shipping_limit_at = group["shipping_limit_date"].min()
            handoff_variance_hours = hours_between(carrier_handoff_at, shipping_limit_at)
            late_handoff = bool(handoff_variance_hours is not None and handoff_variance_hours > 0)
            seller_handoff_analysis.append(
                {
                    "seller_id": seller_id,
                    "shipping_limit_at": fmt_ts(shipping_limit_at),
                    "handoff_variance_hours": handoff_variance_hours,
                    "late_handoff": late_handoff,
                }
            )
            if late_handoff:
                late_handoff_seller_ids.append(seller_id)

    return {
        "delivered_at": fmt_ts(delivered_at),
        "estimated_delivery_at": fmt_ts(estimated_at),
        "carrier_handoff_at": fmt_ts(carrier_handoff_at),
        "delivery_variance_hours": delivery_variance_hours,
        "seller_handoff_analysis": seller_handoff_analysis,
        "late_handoff_seller_ids": late_handoff_seller_ids,
    }


def build_payment_reconciliation(items: pd.DataFrame, payments: pd.DataFrame) -> dict[str, Any]:
    payment_total_brl = round2(payments["payment_value"].sum()) if not payments.empty else 0.0
    payment_types = list(dict.fromkeys(payments["payment_type"].tolist()))

    if items.empty:
        return {
            "currency": "BRL",
            "item_total_brl": 0.0,
            "freight_total_brl": 0.0,
            "expected_total_brl": None,
            "payment_total_brl": payment_total_brl,
            "difference_brl": None,
            "reconciled": None,
            "payment_types": payment_types,
        }

    item_total_brl = round2(items["price"].sum())
    freight_total_brl = round2(items["freight_value"].sum())
    expected_total_brl = round2(item_total_brl + freight_total_brl)
    difference_brl = round2(payment_total_brl - expected_total_brl)
    reconciled = abs(difference_brl) <= 0.10

    return {
        "currency": "BRL",
        "item_total_brl": item_total_brl,
        "freight_total_brl": freight_total_brl,
        "expected_total_brl": expected_total_brl,
        "payment_total_brl": payment_total_brl,
        "difference_brl": difference_brl,
        "reconciled": reconciled,
        "payment_types": payment_types,
    }


# ---------------------------------------------------------------------------
# Policy decision (EC_POLICY_V2, priority order per README section 4)
# ---------------------------------------------------------------------------


def determine_primary_issue(
    order_row: pd.Series,
    payments: pd.DataFrame,
    delivery: dict[str, Any],
    reconciliation: dict[str, Any],
) -> str:
    order_status = order_row["order_status"]
    payment_total = round2(payments["payment_value"].sum()) if not payments.empty else 0.0
    payment_total = payment_total or 0.0

    delivery_variance = delivery["delivery_variance_hours"]
    late_delivery = delivery_variance is not None and delivery_variance > 0
    any_seller_late = len(delivery["late_handoff_seller_ids"]) > 0
    has_sellers = len(delivery["seller_handoff_analysis"]) > 0

    if order_status == "canceled" and payment_total > 0:
        return "canceled_order_paid"
    if order_status == "unavailable" and payment_total > 0:
        return "unavailable_order_paid"
    if late_delivery and any_seller_late:
        return "late_delivery_seller"
    if late_delivery and has_sellers and not any_seller_late:
        return "late_delivery_logistics"
    if len(payments) >= 2 and reconciliation.get("reconciled") is True:
        return "valid_split_payment"
    if delivery_variance is not None and delivery_variance <= 0 and reconciliation.get("reconciled") is True:
        return "unsupported_late_claim"

    # Defensive fallback for data shapes the 6-branch table doesn't cover
    # (e.g. canceled/unavailable order with zero payment, or missing dates).
    # Flagged with low confidence rather than invented as a "real" taxonomy code.
    return "unsupported_late_claim"


def determine_secondary_issues(
    items: pd.DataFrame,
    payments: pd.DataFrame,
    customer_context: dict[str, Any],
    product_context: dict[str, Any],
) -> list[str]:
    issues = []
    if len(items) >= 2:
        issues.append("multi_item_order")
    if items["seller_id"].nunique() >= 2:
        issues.append("multi_seller_order")
    if len(payments) >= 2:
        issues.append("split_payment")
    if len(customer_context.get("related_order_ids", [])) > 0:
        issues.append("repeat_customer")
    if len(product_context.get("category_names", [])) >= 2:
        issues.append("multiple_categories")
    return issues


def compute_confidence(
    primary_issue: str,
    reconciliation: dict[str, Any],
    items: pd.DataFrame,
    is_fallback: bool,
) -> float:
    """Deterministic heuristic (README does not define a formula).

    Starts high for a clean single-branch match, steps down for thin/ambiguous
    data. Documented here and in architecture.md for reproducibility.
    """
    confidence = 0.95
    if is_fallback:
        confidence -= 0.35
    if reconciliation.get("reconciled") is False:
        confidence -= 0.15
    if items.empty:
        confidence -= 0.2
    return max(0.0, min(1.0, round2(confidence)))


def build_evidence_ids(
    order_id: str,
    affected_entities: dict[str, Any],
    responsible_seller_ids: list[str],
    root_cause_code: str,
) -> list[str]:
    evidence = [f"order:{order_id}"]
    evidence += [f"item:{item_id}" for item_id in affected_entities["item_ids"]]
    evidence += [f"payment:{payment_id}" for payment_id in affected_entities["payment_ids"]]
    evidence += [f"seller:{sid}" for sid in responsible_seller_ids]
    evidence.append(f"policy:{root_cause_code}")
    return truncate(evidence, "evidence_ids")


def determine_resolution(
    primary_issue: str,
    secondary_issues: list[str],
    delivery: dict[str, Any],
    reconciliation: dict[str, Any],
) -> dict[str, Any]:
    freight_total = None
    if delivery["seller_handoff_analysis"] or reconciliation.get("freight_total_brl") is not None:
        freight_total = reconciliation.get("freight_total_brl")

    payment_total = reconciliation.get("payment_total_brl", 0.0)

    responsible_parties: list[dict[str, str]] = []
    late_seller_ids = delivery["late_handoff_seller_ids"]

    if primary_issue in ("canceled_order_paid", "unavailable_order_paid"):
        responsible_parties = [{"party_type": "platform", "party_id": "OLIST_PLATFORM"}]
        refund_brl = payment_total or 0.0
        primary_action = "issue_full_refund"
    elif primary_issue == "late_delivery_seller":
        responsible_parties = [
            {"party_type": "seller", "party_id": sid}
            for sid in truncate(late_seller_ids, "responsible_parties")
        ]
        refund_brl = freight_total or 0.0
        primary_action = "refund_freight"
    elif primary_issue == "late_delivery_logistics":
        responsible_parties = [{"party_type": "logistics_provider", "party_id": "LOGISTICS_PROVIDER"}]
        refund_brl = freight_total or 0.0
        primary_action = "refund_freight"
    elif primary_issue == "valid_split_payment":
        responsible_parties = []
        refund_brl = 0.0
        primary_action = "explain_valid_split_payment"
    else:  # unsupported_late_claim (incl. defensive fallback)
        responsible_parties = []
        refund_brl = 0.0
        primary_action = "reject_late_refund"

    case_status = "action_required" if refund_brl and refund_brl > 0 else "no_action"

    actions = [primary_action]
    if primary_issue == "late_delivery_seller":
        actions.append("review_seller_handoff")
    elif primary_issue == "late_delivery_logistics":
        actions.append("review_carrier_delay")
    if primary_issue in ("canceled_order_paid", "unavailable_order_paid"):
        actions.append("verify_refund_completion")
    if "multi_seller_order" in secondary_issues:
        actions.append("coordinate_multi_seller_case")
    if "split_payment" in secondary_issues and primary_issue != "valid_split_payment":
        actions.append("verify_payment_allocation")

    return {
        "responsible_parties": truncate(responsible_parties, "responsible_parties"),
        "refund_brl": round2(refund_brl) or 0.0,
        "case_status": case_status,
        "resolution_actions": truncate(actions, "resolution_actions"),
        "late_seller_ids": late_seller_ids,
    }


def build_case(order_id: str) -> dict[str, Any]:
    """Full deterministic case build for one order_id, matching README section 6 schema
    (everything except `case_id`, which the coordinator adds from the input ticket).
    """
    order_row = loader.get_order_row(order_id)
    if order_row is None:
        raise ValueError(f"order_id not found in data: {order_id}")

    items = loader.get_order_items(order_id)
    payments = loader.get_order_payments(order_id)

    affected_entities = build_affected_entities(order_id, items)
    payment_ids = [f"{order_id}:{int(row.payment_sequential)}" for row in payments.itertuples()]
    affected_entities["payment_ids"] = truncate(payment_ids, "payment_ids")

    customer_context = build_customer_context(order_id, order_row)
    product_context = build_product_context(items)
    delivery_analysis = build_delivery_analysis(order_row, items)
    payment_reconciliation = build_payment_reconciliation(items, payments)

    primary_issue = determine_primary_issue(order_row, payments, delivery_analysis, payment_reconciliation)
    is_fallback = primary_issue == "unsupported_late_claim" and not (
        delivery_analysis["delivery_variance_hours"] is not None
        and delivery_analysis["delivery_variance_hours"] <= 0
        and payment_reconciliation.get("reconciled") is True
    )
    secondary_issues = determine_secondary_issues(items, payments, customer_context, product_context)

    root_cause_code = ROOT_CAUSE[primary_issue]
    resolution = determine_resolution(primary_issue, secondary_issues, delivery_analysis, payment_reconciliation)

    evidence_ids = build_evidence_ids(
        order_id, affected_entities, resolution["responsible_parties"] and
        [p["party_id"] for p in resolution["responsible_parties"] if p["party_type"] == "seller"] or [],
        root_cause_code,
    )

    confidence = compute_confidence(primary_issue, payment_reconciliation, items, is_fallback)

    return {
        "case_assessment": {
            "primary_issue": primary_issue,
            "secondary_issues": secondary_issues,
            "case_status": resolution["case_status"],
            "confidence": confidence,
        },
        "affected_entities": {
            "order_ids": affected_entities["order_ids"],
            "item_ids": affected_entities["item_ids"],
            "seller_ids": affected_entities["seller_ids"],
            "payment_ids": affected_entities["payment_ids"],
        },
        "customer_context": customer_context,
        "product_context": product_context,
        "delivery_analysis": delivery_analysis,
        "payment_reconciliation": payment_reconciliation,
        "root_cause_analysis": {
            "ranked_causes": [{"cause_code": root_cause_code, "rank": 1}],
            "responsible_parties": resolution["responsible_parties"],
        },
        "evidence_ids": evidence_ids,
        "financial_resolution": {
            "currency": "BRL",
            "recommended_refund_brl": resolution["refund_brl"],
        },
        "resolution_actions": resolution["resolution_actions"],
    }
