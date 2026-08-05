"""Tool-level tests for the MCP server (in-process, via the registered tool
functions directly — see test_e2e in scripts/run_batch.py output for the
over-the-wire verification)."""

import asyncio

from src.mcp_server.server import server


def call(name: str, args: dict) -> dict:
    tools = asyncio.run(server.list_tools())
    assert any(t.name == name for t in tools), f"tool not registered: {name}"
    result = asyncio.run(server.call_tool(name, args, context=None))
    import json

    return json.loads(result.content[0].text)


ORDER_ID = "0005a1a1728c9d785b8e2b08b904576c"  # late_delivery_seller candidate


def test_get_order_found():
    result = call("get_order", {"order_id": ORDER_ID})
    assert result["found"] is True
    assert result["order_id"] == ORDER_ID
    assert result["order_status"] == "delivered"


def test_get_order_not_found():
    result = call("get_order", {"order_id": "does-not-exist"})
    assert result["found"] is False


def test_get_affected_entities_shape():
    result = call("get_affected_entities", {"order_id": ORDER_ID})
    assert result["order_ids"] == [ORDER_ID]
    assert all(i.startswith(ORDER_ID + ":") for i in result["item_ids"])
    assert all(p.startswith(ORDER_ID + ":") for p in result["payment_ids"])


def test_get_delivery_analysis_matches_policy_engine():
    from src.mcp_server.policy_engine import build_case

    via_tool = call("get_delivery_analysis", {"order_id": ORDER_ID})
    via_engine = build_case(ORDER_ID)["delivery_analysis"]
    assert via_tool["delivery_variance_hours"] == via_engine["delivery_variance_hours"]
    assert via_tool["late_handoff_seller_ids"] == via_engine["late_handoff_seller_ids"]


def test_apply_policy_matches_build_case():
    from src.mcp_server.policy_engine import build_case

    via_tool = call("apply_policy", {"order_id": ORDER_ID})
    via_engine = build_case(ORDER_ID)
    assert via_tool == via_engine


def test_validate_case_output_flags_bad_evidence():
    case = call("apply_policy", {"order_id": ORDER_ID})
    case["case_id"] = "EC_TEST"
    case["evidence_ids"] = case["evidence_ids"] + ["item:not-a-real-item:99"]
    result = call("validate_case_output", {"case_json": case})
    assert result["valid"] is False
    assert any("not found in source data" in v for v in result["violations"])


def test_validate_case_output_passes_clean_case():
    case = call("apply_policy", {"order_id": ORDER_ID})
    case["case_id"] = "EC_TEST"
    result = call("validate_case_output", {"case_json": case})
    assert result["valid"] is True
    assert result["violations"] == []
