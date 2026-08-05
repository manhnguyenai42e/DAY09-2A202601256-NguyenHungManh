"""Policy Agent: reads the EC_POLICY_V2 rulebook and the upstream agents'
self-computed facts, and must itself decide + format every remaining field
of the case — primary_issue, secondary_issues, root cause, responsible
parties, evidence_ids, refund amount, resolution_actions, confidence. No
tool assembles any of this; the model is the only author."""

from __future__ import annotations

import json

from src.a2a_common.protocol import AgentCard, HandoffPayload
from src.agents.base import agent_tool_loop, build_agent_app, mcp_session
from src.config import LIMITS, agent_url

ALLOWED_TOOLS = ["get_policy_rulebook", "get_order"]

VALID_ISSUES = [
    "canceled_order_paid", "unavailable_order_paid", "late_delivery_seller",
    "late_delivery_logistics", "valid_split_payment", "unsupported_late_claim",
]

SYSTEM = (
    "Bạn là Policy Agent của bộ phận xử lý khiếu nại thương mại điện tử Olist. "
    "Bạn nhận bằng chứng đã được các agent chuyên trách TỰ TÍNH TOÁN (số tiền, ngày giờ, "
    "ID đã đúng, không cần tính lại) và PHẢI TỰ RA PHÁN QUYẾT + TỰ DỰNG toàn bộ phần còn lại "
    "của hồ sơ. Không có công cụ nào làm sẵn hộ bạn — evidence_ids, refund, actions, "
    "confidence... tất cả do bạn tự viết ra.\n\n"
    "Quy trình bắt buộc:\n"
    "1. Gọi get_policy_rulebook() để đọc bảng luật EC_POLICY_V2 đầy đủ (thứ tự ưu tiên, "
    "root cause code, định dạng evidence ID, trần mảng, thứ tự action bổ sung).\n"
    "2. Gọi get_order(order_id) để lấy order_status (cần cho nhánh canceled/unavailable).\n"
    "3. TỰ ĐỐI CHIẾU bằng chứng đã có với từng nhánh luật THEO ĐÚNG THỨ TỰ ƯU TIÊN, chọn "
    "nhánh ĐẦU TIÊN thỏa mãn (xét lần lượt n1 -> n6, KHÔNG nhảy cóc):\n"
    "   n1 canceled_order_paid     : order_status == 'canceled' và payment_total_brl > 0\n"
    "   n2 unavailable_order_paid  : order_status == 'unavailable' và payment_total_brl > 0\n"
    "   n3 late_delivery_seller    : delivery_variance_hours > 0 và late_handoff_seller_ids KHÁC rỗng\n"
    "   n4 late_delivery_logistics : delivery_variance_hours > 0 và late_handoff_seller_ids rỗng\n"
    "   n5 valid_split_payment     : SỐ LƯỢNG phần tử trong payment_ids >= 2 và reconciled == true\n"
    "   n6 unsupported_late_claim  : delivery_variance_hours <= 0 và reconciled == true\n"
    "   LƯU Ý: nhánh 5 và 6 rất dễ nhầm. Đơn giao đúng hạn và tiền khớp mà payment_ids có TỪ "
    "2 PHẦN TỬ TRỞ LÊN thì phải chọn n5, KHÔNG được chọn n6. Chỉ chọn n6 khi payment_ids đúng "
    "1 phần tử. Đếm số phần tử trong payment_ids trước khi quyết định.\n"
    "4. Tự dựng secondary_issues theo đúng thứ tự (chỉ thêm khi đúng điều kiện): "
    "multi_item_order (item_ids có >=2 phần tử), multi_seller_order (seller_ids có >=2 phần "
    "tử), split_payment (payment_ids có >=2 phần tử), repeat_customer (related_order_ids có "
    ">=1 phần tử), multiple_categories (category_names có >=2 phần tử).\n"
    "5. Tự dựng root_cause_analysis: ranked_causes = [{cause_code lấy từ "
    "root_cause_codes[primary_issue] trong rulebook, rank: 1}]. responsible_parties theo "
    "rulebook: platform/OLIST_PLATFORM (n1,n2); MỖI seller_id trong late_handoff_seller_ids, "
    f"tối đa {LIMITS['responsible_parties']} (n3); logistics_provider/LOGISTICS_PROVIDER (n4); "
    "mảng rỗng (n5, n6).\n"
    "6. Tự dựng evidence_ids theo đúng thứ tự: order:<order_id>, rồi item:<item_id> cho từng "
    "item_id, rồi payment:<payment_id> cho từng payment_id, rồi seller:<seller_id> cho từng "
    f"seller trong responsible_parties (nếu có), rồi policy:<root_cause_code>. Tối đa "
    f"{LIMITS['evidence_ids']} phần tử.\n"
    "7. Tự chọn recommended_refund_brl từ SỐ LIỆU ĐÃ CÓ (không tính lại): payment_total_brl "
    "(n1, n2); freight_total_brl (n3, n4); 0.0 (n5, n6).\n"
    "8. Tự dựng resolution_actions: action chính trước "
    "(issue_full_refund/refund_freight/explain_valid_split_payment/reject_late_refund theo "
    "rulebook), rồi thêm theo đúng thứ tự nếu đúng điều kiện: review_seller_handoff (n3) hoặc "
    "review_carrier_delay (n4); verify_refund_completion (n1, n2); coordinate_multi_seller_case "
    "(nếu có secondary issue multi_seller_order); verify_payment_allocation (nếu có secondary "
    f"issue split_payment VÀ primary_issue != valid_split_payment). Tối đa {LIMITS['resolution_actions']}.\n"
    "9. case_status = 'action_required' nếu recommended_refund_brl > 0, ngược lại 'no_action'.\n"
    "10. confidence: tự đánh giá độ tin cậy phán quyết của chính bạn, số thực trong [0,1].\n"
    "11. Gọi report_case với toàn bộ trường trên và 2-3 câu tiếng Việt giải thích bạn chọn "
    "nhánh nào, vì sao bằng chứng thỏa mãn, có trích dẫn evidence ID.\n\n"
    f"primary_issue chỉ được là một trong: {', '.join(VALID_ISSUES)}."
)

FINAL_TOOL = {
    "name": "report_case",
    "description": "Nộp phán quyết cuối cùng và toàn bộ phần hồ sơ do Policy Agent chịu trách nhiệm.",
    "parameters": {
        "type": "object",
        "properties": {
            "primary_issue": {"type": "string", "enum": VALID_ISSUES},
            "secondary_issues": {"type": "array", "items": {"type": "string"}},
            "case_status": {"type": "string", "enum": ["action_required", "no_action"]},
            "confidence": {"type": "number"},
            "ranked_causes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"cause_code": {"type": "string"}, "rank": {"type": "integer"}},
                    "required": ["cause_code", "rank"],
                },
                "maxItems": LIMITS["ranked_causes"],
            },
            "responsible_parties": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"party_type": {"type": "string"}, "party_id": {"type": "string"}},
                    "required": ["party_type", "party_id"],
                },
                "maxItems": LIMITS["responsible_parties"],
            },
            "evidence_ids": {"type": "array", "items": {"type": "string"}, "maxItems": LIMITS["evidence_ids"]},
            "recommended_refund_brl": {"type": "number"},
            "resolution_actions": {"type": "array", "items": {"type": "string"}, "maxItems": LIMITS["resolution_actions"]},
            "rationale": {"type": "string", "description": "2-3 câu tiếng Việt giải thích, có trích evidence ID."},
        },
        "required": [
            "primary_issue", "secondary_issues", "case_status", "confidence", "ranked_causes",
            "responsible_parties", "evidence_ids", "recommended_refund_brl", "resolution_actions",
            "rationale",
        ],
    },
}

CARD = AgentCard(
    name="policy-agent",
    description="Applies EC_POLICY_V2 to upstream facts and drafts the full case rationale.",
    url=agent_url("policy"),
    skills=ALLOWED_TOOLS,
)


async def handle(payload: HandoffPayload) -> HandoffPayload:
    order_id = payload.facts["order_id"]
    upstream = {k: v for k, v in payload.facts.items() if k != "order_id"}

    async with mcp_session() as session:
        user = (
            f"Ticket cho đơn hàng order_id = {order_id}.\n"
            f"Bằng chứng các agent đã tự tính:\n{json.dumps(upstream, ensure_ascii=False)}"
        )
        args, chosen = await agent_tool_loop(SYSTEM, user, ALLOWED_TOOLS, FINAL_TOOL, session, max_rounds=10)

    # Some providers do not strictly enforce a function-calling schema's
    # "required" list server-side (it is a hint to the model, not always a
    # guarantee), so the model can occasionally submit report_case missing a
    # required field. Fail this case clearly rather than crash on a raw
    # KeyError or silently invent a value for a missing ruling.
    if "primary_issue" not in args or args["primary_issue"] not in VALID_ISSUES:
        raise RuntimeError(
            f"policy agent's report_case call is missing/invalid primary_issue: {args.get('primary_issue')!r}"
        )
    if "case_status" not in args:
        raise RuntimeError("policy agent's report_case call is missing required field case_status")

    return HandoffPayload(
        ticket_id=payload.ticket_id,
        from_agent="policy",
        question=payload.question,
        facts={
            "case_assessment": {
                "primary_issue": args["primary_issue"],
                "secondary_issues": args.get("secondary_issues", []),
                "case_status": args["case_status"],
                "confidence": args.get("confidence"),
            },
            "root_cause_analysis": {
                "ranked_causes": args.get("ranked_causes", []),
                "responsible_parties": args.get("responsible_parties", []),
            },
            "financial_resolution": {
                "currency": "BRL",
                "recommended_refund_brl": args.get("recommended_refund_brl"),
            },
            "resolution_actions": args.get("resolution_actions", []),
            "tools_called_by_llm": chosen,
        },
        evidence_ids=args.get("evidence_ids", []),
        next_action="handoff to verifier",
        note=args.get("rationale", ""),
    )


app = build_agent_app(CARD, handle)
