"""Unit tests for policy_engine against real order_ids from data/, one per
EC_POLICY_V2 primary_issue branch (README.md section 4)."""

from src.mcp_server.policy_engine import build_case


def test_canceled_order_paid():
    case = build_case("1b9ecfe83cdc259250e1a8aca174f0ad")
    a = case["case_assessment"]
    assert a["primary_issue"] == "canceled_order_paid"
    assert a["case_status"] == "action_required"
    rp = case["root_cause_analysis"]["responsible_parties"]
    assert rp == [{"party_type": "platform", "party_id": "OLIST_PLATFORM"}]
    assert case["root_cause_analysis"]["ranked_causes"][0]["cause_code"] == "ORDER_CANCELED_AFTER_PAYMENT"
    assert case["financial_resolution"]["recommended_refund_brl"] > 0
    assert case["resolution_actions"][0] == "issue_full_refund"
    assert "verify_refund_completion" in case["resolution_actions"]


def test_unavailable_order_paid():
    case = build_case("8e24261a7e58791d10cb1bf9da94df5c")
    a = case["case_assessment"]
    assert a["primary_issue"] == "unavailable_order_paid"
    assert case["root_cause_analysis"]["ranked_causes"][0]["cause_code"] == "ORDER_UNAVAILABLE_AFTER_PAYMENT"
    assert case["resolution_actions"][0] == "issue_full_refund"


def test_late_delivery_seller():
    case = build_case("0005a1a1728c9d785b8e2b08b904576c")
    a = case["case_assessment"]
    assert a["primary_issue"] == "late_delivery_seller"
    assert case["delivery_analysis"]["delivery_variance_hours"] > 0
    assert any(s["late_handoff"] for s in case["delivery_analysis"]["seller_handoff_analysis"])
    rp = case["root_cause_analysis"]["responsible_parties"]
    assert all(p["party_type"] == "seller" for p in rp) and len(rp) >= 1
    assert case["resolution_actions"][:2] == ["refund_freight", "review_seller_handoff"]
    assert case["financial_resolution"]["recommended_refund_brl"] == case["payment_reconciliation"]["freight_total_brl"]


def test_late_delivery_logistics():
    case = build_case("00063b381e2406b52ad429470734ebd5")
    a = case["case_assessment"]
    assert a["primary_issue"] == "late_delivery_logistics"
    assert not any(s["late_handoff"] for s in case["delivery_analysis"]["seller_handoff_analysis"])
    assert case["root_cause_analysis"]["responsible_parties"] == [
        {"party_type": "logistics_provider", "party_id": "LOGISTICS_PROVIDER"}
    ]
    assert case["resolution_actions"][:2] == ["refund_freight", "review_carrier_delay"]


def test_valid_split_payment():
    case = build_case("0016dfedd97fc2950e388d2971d718c7")
    a = case["case_assessment"]
    assert a["primary_issue"] == "valid_split_payment"
    assert a["case_status"] == "no_action"
    assert case["payment_reconciliation"]["reconciled"] is True
    assert case["financial_resolution"]["recommended_refund_brl"] == 0.0
    assert case["resolution_actions"] == ["explain_valid_split_payment"]
    assert "verify_payment_allocation" not in case["resolution_actions"]


def test_unsupported_late_claim():
    case = build_case("53cdb2fc8bc7dce0b6741e2150273451")
    a = case["case_assessment"]
    assert a["primary_issue"] == "unsupported_late_claim"
    assert a["case_status"] == "no_action"
    assert case["delivery_analysis"]["delivery_variance_hours"] <= 0
    assert case["payment_reconciliation"]["reconciled"] is True
    assert case["resolution_actions"] == ["reject_late_refund"]


def test_evidence_ids_are_grounded_and_formatted():
    case = build_case("0005a1a1728c9d785b8e2b08b904576c")
    order_id = "0005a1a1728c9d785b8e2b08b904576c"
    for ev in case["evidence_ids"]:
        kind, _, rest = ev.partition(":")
        assert kind in ("order", "item", "payment", "seller", "policy")
        if kind == "order":
            assert rest == order_id
        if kind == "item":
            assert rest.startswith(order_id + ":")
    assert case["evidence_ids"][0] == f"order:{order_id}"
    assert case["evidence_ids"][-1].startswith("policy:")


def test_array_limits_respected():
    for order_id in [
        "1b9ecfe83cdc259250e1a8aca174f0ad",
        "0005a1a1728c9d785b8e2b08b904576c",
        "0016dfedd97fc2950e388d2971d718c7",
    ]:
        case = build_case(order_id)
        assert len(case["affected_entities"]["order_ids"]) <= 5
        assert len(case["affected_entities"]["item_ids"]) <= 5
        assert len(case["affected_entities"]["seller_ids"]) <= 3
        assert len(case["affected_entities"]["payment_ids"]) <= 5
        assert len(case["customer_context"]["related_order_ids"]) <= 5
        assert len(case["product_context"]["product_ids"]) <= 5
        assert len(case["product_context"]["category_names"]) <= 5
        assert len(case["root_cause_analysis"]["ranked_causes"]) <= 3
        assert len(case["root_cause_analysis"]["responsible_parties"]) <= 3
        assert len(case["evidence_ids"]) <= 20
        assert len(case["resolution_actions"]) <= 5
        assert 0.0 <= case["case_assessment"]["confidence"] <= 1.0
