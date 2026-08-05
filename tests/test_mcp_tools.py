"""Tool-level tests for the MCP server (in-process, via the registered tool
functions directly). Every tool here is a raw, key-filtered fetch from the
source CSVs — no sums, no date arithmetic, no evidence-ID formatting, no
classification — so these stay fully deterministic and unit-testable even
though the business decisions themselves now live entirely in agent prompts
(and are no longer unit-testable as pure functions)."""

import asyncio
import json

from src.mcp_server.server import server

ORDER_ID = "0005a1a1728c9d785b8e2b08b904576c"  # single item, single payment, delivered


def call(name: str, args: dict) -> dict:
    tools = asyncio.run(server.list_tools())
    assert any(t.name == name for t in tools), f"tool not registered: {name}"
    result = asyncio.run(server.call_tool(name, args, context=None))
    return json.loads(result.content[0].text)


def test_get_order_found():
    result = call("get_order", {"order_id": ORDER_ID})
    assert result["found"] is True
    assert result["order_id"] == ORDER_ID
    assert result["order_status"] == "delivered"


def test_get_order_not_found():
    result = call("get_order", {"order_id": "does-not-exist"})
    assert result["found"] is False


def test_get_order_items_raw_shape():
    result = call("get_order_items", {"order_id": ORDER_ID})
    assert result["found"] is True
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["order_item_id"] == 1
    assert item["price"] == 145.95
    assert item["freight_value"] == 11.65
    assert "seller_id" in item and "shipping_limit_date" in item
    # No derived fields (no totals, no formatted evidence IDs) leak through.
    assert "item_id" not in item and "item_total_brl" not in result


def test_get_order_payments_raw_shape():
    result = call("get_order_payments", {"order_id": ORDER_ID})
    assert result["found"] is True
    assert len(result["payments"]) == 1
    payment = result["payments"][0]
    assert payment["payment_sequential"] == 1
    assert payment["payment_type"] == "credit_card"
    assert payment["payment_value"] == 157.6
    assert "payment_total_brl" not in result and "reconciled" not in result


def test_get_customer_raw_shape():
    result = call("get_customer", {"order_id": ORDER_ID})
    assert result["found"] is True
    assert "customer_id" in result and "customer_unique_id" in result
    assert "related_order_ids" not in result  # that's the agent's job, not the tool's


def test_get_related_orders_includes_current_order():
    customer = call("get_customer", {"order_id": ORDER_ID})
    related = call("get_related_orders", {"customer_unique_id": customer["customer_unique_id"]})
    assert related["found"] is True
    # Raw tool does not exclude the current order; the agent must do that itself.
    assert ORDER_ID in related["order_ids"]


def test_get_products_raw_shape():
    items = call("get_order_items", {"order_id": ORDER_ID})
    product_ids = [i["product_id"] for i in items["items"]]
    result = call("get_products", {"product_ids": product_ids})
    assert result["found"] is True
    assert len(result["products"]) == 1
    assert result["products"][0]["product_id"] == product_ids[0]
    assert "category_names" not in result  # dedup/truncation is the agent's job


def test_get_policy_rulebook_has_no_case_data():
    rulebook = call("get_policy_rulebook", {})
    assert rulebook["policy_version"] == "EC_POLICY_V2"
    assert len(rulebook["evaluate_in_this_priority_order"]) == 6
    # Reference text only: no real order/case data, just rule descriptions.
    assert ORDER_ID not in json.dumps(rulebook)


def _valid_case_for_order_id() -> dict:
    """Hand-built fixture (test-only) mirroring what a correctly-reasoning
    agent pipeline would produce for ORDER_ID — used to exercise the
    validator's pass/fail logic, not to test any production computation."""
    return {
        "case_id": "EC_TEST",
        "case_assessment": {
            "primary_issue": "unsupported_late_claim",
            "secondary_issues": [],
            "case_status": "no_action",
            "confidence": 0.9,
        },
        "affected_entities": {
            "order_ids": [ORDER_ID],
            "item_ids": [f"{ORDER_ID}:1"],
            "seller_ids": ["a416b6a846a11724393025641d4edd5e"],
            "payment_ids": [f"{ORDER_ID}:1"],
        },
        "customer_context": {"customer_unique_id": "x", "related_order_ids": []},
        "product_context": {"product_ids": ["310ae3c140ff94b03219ad0adc3c778f"], "category_names": []},
        "delivery_analysis": {
            "delivered_at": None, "estimated_delivery_at": None, "carrier_handoff_at": None,
            "delivery_variance_hours": None, "seller_handoff_analysis": [], "late_handoff_seller_ids": [],
        },
        "payment_reconciliation": {
            "currency": "BRL", "item_total_brl": 145.95, "freight_total_brl": 11.65,
            "expected_total_brl": 157.6, "payment_total_brl": 157.6, "difference_brl": 0.0,
            "reconciled": True, "payment_types": ["credit_card"],
        },
        "root_cause_analysis": {
            "ranked_causes": [{"cause_code": "DELIVERY_WITHIN_ESTIMATE", "rank": 1}],
            "responsible_parties": [],
        },
        "evidence_ids": [f"order:{ORDER_ID}", f"item:{ORDER_ID}:1", f"payment:{ORDER_ID}:1",
                          "seller:a416b6a846a11724393025641d4edd5e", "policy:DELIVERY_WITHIN_ESTIMATE"],
        "financial_resolution": {"currency": "BRL", "recommended_refund_brl": 0.0},
        "resolution_actions": ["reject_late_refund"],
    }


def test_validate_case_output_passes_clean_case():
    result = call("validate_case_output", {"case_json": _valid_case_for_order_id()})
    assert result["valid"] is True
    assert result["violations"] == []


def test_validate_case_output_flags_bad_evidence():
    case = _valid_case_for_order_id()
    case["evidence_ids"] = case["evidence_ids"] + ["item:not-a-real-item:99"]
    result = call("validate_case_output", {"case_json": case})
    assert result["valid"] is False
    assert any("not found in source data" in v for v in result["violations"])


def test_validate_case_output_flags_missing_field():
    case = _valid_case_for_order_id()
    del case["financial_resolution"]
    result = call("validate_case_output", {"case_json": case})
    assert result["valid"] is False
    assert any("financial_resolution" in v for v in result["violations"])
