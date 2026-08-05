"""Real MCP server exposing the Olist data as raw tools + the schema/limit/
grounding validator. Every tool here does pure key-filtered retrieval from
the source CSVs (via src/data/loader.py) — no sums, no date arithmetic, no
evidence-ID formatting, no classification. All of that is the job of the LLM
agents that call these tools: they read the raw rows and must compute and
format everything themselves before reporting their findings.

The one exception is `validate_case_output`: it does not decide any content,
it only checks a finished case against schema/limits/grounding rules (the
Verifier Agent's documented job per README section 6) and rejects or accepts
it, never fills anything in.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd
from mcp.server import MCPServer

from src.config import MCP_SERVER_HOST, MCP_SERVER_PORT
from src.data import loader

server: MCPServer = MCPServer(name="ec-dispute-data", version="1.0.0")


def fmt_ts(ts) -> str | None:
    """Datetime -> the same 'YYYY-MM-DD HH:MM:SS' text the CSV already stores.
    Pure serialization (JSON has no datetime type) — carries no computed
    information beyond what the source cell already said."""
    if ts is None or (isinstance(ts, float) and math.isnan(ts)) or pd.isna(ts):
        return None
    return ts.strftime("%Y-%m-%d %H:%M:%S")


@server.tool()
def get_order(order_id: str) -> dict[str, Any]:
    """Raw order row: status, customer_id and the 4 raw timestamps for an order_id."""
    row = loader.get_order_row(order_id)
    if row is None:
        return {"found": False}
    return {
        "found": True,
        "order_id": row["order_id"],
        "customer_id": row["customer_id"],
        "order_status": row["order_status"],
        "order_purchase_timestamp": fmt_ts(row.get("order_purchase_timestamp")),
        "order_delivered_customer_date": fmt_ts(row.get("order_delivered_customer_date")),
        "order_estimated_delivery_date": fmt_ts(row.get("order_estimated_delivery_date")),
        "order_delivered_carrier_date": fmt_ts(row.get("order_delivered_carrier_date")),
    }


@server.tool()
def get_order_items(order_id: str) -> dict[str, Any]:
    """Raw order_items rows for an order_id: one entry per item, in source order.
    No dedup, no ID formatting, no sums — that is for the calling agent to do."""
    items = loader.get_order_items(order_id)
    rows = [
        {
            "order_item_id": int(r.order_item_id),
            "product_id": r.product_id,
            "seller_id": r.seller_id,
            "price": None if pd.isna(r.price) else float(r.price),
            "freight_value": None if pd.isna(r.freight_value) else float(r.freight_value),
            "shipping_limit_date": fmt_ts(r.shipping_limit_date),
        }
        for r in items.itertuples()
    ]
    return {"found": True, "items": rows}


@server.tool()
def get_order_payments(order_id: str) -> dict[str, Any]:
    """Raw order_payments rows for an order_id, in source order. No sums."""
    payments = loader.get_order_payments(order_id)
    rows = [
        {
            "payment_sequential": int(r.payment_sequential),
            "payment_type": r.payment_type,
            "payment_installments": int(r.payment_installments),
            "payment_value": None if pd.isna(r.payment_value) else float(r.payment_value),
        }
        for r in payments.itertuples()
    ]
    return {"found": True, "payments": rows}


@server.tool()
def get_customer(order_id: str) -> dict[str, Any]:
    """Raw customer identity for the order's customer_id: customer_id + customer_unique_id."""
    order_row = loader.get_order_row(order_id)
    if order_row is None:
        return {"found": False}
    customer = loader.get_customer_row(order_row["customer_id"])
    if customer is None:
        return {"found": False}
    return {
        "found": True,
        "customer_id": customer["customer_id"],
        "customer_unique_id": customer["customer_unique_id"],
    }


@server.tool()
def get_related_orders(customer_unique_id: str) -> dict[str, Any]:
    """All order_ids belonging to this customer_unique_id, including the current
    one — the calling agent must exclude the current order_id itself and cap
    the list per the schema limit."""
    return {"found": True, "order_ids": loader.get_related_order_ids(customer_unique_id, exclude_order_id="")}


@server.tool()
def get_products(product_ids: list[str]) -> dict[str, Any]:
    """Raw product rows (product_id, product_category_name) for the given product_ids."""
    products = loader.get_products(product_ids)
    rows = [
        {
            "product_id": row["product_id"],
            "product_category_name": row.get("product_category_name"),
        }
        for _, row in products.iterrows()
    ]
    return {"found": True, "products": rows}


@server.tool()
def get_policy_rulebook() -> dict[str, Any]:
    """Return the EC_POLICY_V2 rule table so the Policy Agent can reason about which
    branch applies. Rules only — no data, no decision."""
    return {
        "policy_version": "EC_POLICY_V2",
        "evaluate_in_this_priority_order": [
            {"primary_issue": "canceled_order_paid",
             "condition": "order_status == 'canceled' AND payment_total > 0",
             "responsible": {"party_type": "platform", "party_id": "OLIST_PLATFORM"},
             "refund": "payment_total_brl", "action": "issue_full_refund"},
            {"primary_issue": "unavailable_order_paid",
             "condition": "order_status == 'unavailable' AND payment_total > 0",
             "responsible": {"party_type": "platform", "party_id": "OLIST_PLATFORM"},
             "refund": "payment_total_brl", "action": "issue_full_refund"},
            {"primary_issue": "late_delivery_seller",
             "condition": "delivery_variance_hours > 0 AND late_handoff_seller_ids is not empty",
             "responsible": {"party_type": "seller", "party_id": "each late seller id"},
             "refund": "freight_total_brl", "action": "refund_freight"},
            {"primary_issue": "late_delivery_logistics",
             "condition": "delivery_variance_hours > 0 AND late_handoff_seller_ids is empty",
             "responsible": {"party_type": "logistics_provider", "party_id": "LOGISTICS_PROVIDER"},
             "refund": "freight_total_brl", "action": "refund_freight"},
            {"primary_issue": "valid_split_payment",
             "condition": "payment row count >= 2 AND reconciled == true",
             "responsible": None, "refund": 0, "action": "explain_valid_split_payment"},
            {"primary_issue": "unsupported_late_claim",
             "condition": "delivery_variance_hours <= 0 AND reconciled == true",
             "responsible": None, "refund": 0, "action": "reject_late_refund"},
        ],
        "root_cause_codes": {
            "late_delivery_seller": "SELLER_HANDOFF_AFTER_LIMIT",
            "late_delivery_logistics": "CARRIER_DELIVERED_AFTER_ESTIMATE",
            "canceled_order_paid": "ORDER_CANCELED_AFTER_PAYMENT",
            "unavailable_order_paid": "ORDER_UNAVAILABLE_AFTER_PAYMENT",
            "valid_split_payment": "MULTIPLE_PAYMENTS_RECONCILED",
            "unsupported_late_claim": "DELIVERY_WITHIN_ESTIMATE",
        },
        "case_status": "action_required if refund > 0 else no_action",
        "secondary_issues_in_this_order": [
            {"code": "multi_item_order", "condition": ">= 2 item rows"},
            {"code": "multi_seller_order", "condition": ">= 2 distinct seller_id"},
            {"code": "split_payment", "condition": ">= 2 payment rows"},
            {"code": "repeat_customer", "condition": ">= 1 related_order_id"},
            {"code": "multiple_categories", "condition": ">= 2 distinct category_names"},
        ],
        "evidence_id_formats": [
            "order:<order_id>", "item:<order_id>:<order_item_id>",
            "payment:<order_id>:<payment_sequential>", "seller:<seller_id>",
            "policy:<root_cause_code>",
        ],
        "array_limits": {
            "item_ids": 5, "seller_ids": 3, "payment_ids": 5, "related_order_ids": 5,
            "product_ids": 5, "category_names": 5, "ranked_causes": 3,
            "responsible_parties": 3, "evidence_ids": 20, "resolution_actions": 5,
        },
        "additional_actions_appended_after_primary_in_this_order": [
            "review_seller_handoff (if late_delivery_seller)",
            "review_carrier_delay (if late_delivery_logistics)",
            "verify_refund_completion (if canceled_order_paid or unavailable_order_paid)",
            "coordinate_multi_seller_case (if multi_seller_order secondary issue present)",
            "verify_payment_allocation (if split_payment secondary issue present AND primary_issue != valid_split_payment)",
        ],
    }


@server.tool()
def validate_case_output(case_json: dict[str, Any]) -> dict[str, Any]:
    """Verifier tool: checks schema completeness, array limits and evidence/entity
    grounding against the source CSVs. Returns {"valid": bool, "violations": [...]}.
    This never fills in or changes a value — it only accepts or rejects."""
    from src.mcp_server.schema import validate_case

    violations = validate_case(case_json)
    return {"valid": len(violations) == 0, "violations": violations}


if __name__ == "__main__":
    server.run(transport="streamable-http", host=MCP_SERVER_HOST, port=MCP_SERVER_PORT)
