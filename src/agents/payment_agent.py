"""Payment Agent: LLM agent for payment reconciliation. It reads raw item and
payment rows and must itself sum, round and compare them — no tool sums
anything for it."""

from __future__ import annotations

from src.a2a_common.protocol import AgentCard, HandoffPayload
from src.agents.base import agent_tool_loop, build_agent_app, mcp_session
from src.config import LIMITS, agent_url

ALLOWED_TOOLS = ["get_order_items", "get_order_payments"]

SYSTEM = (
    "Bạn là Payment Agent trong hệ thống điều tra khiếu nại thương mại điện tử Olist. "
    "Nhiệm vụ: đối soát thanh toán của đơn hàng, hoàn toàn tự mình cộng và làm tròn — "
    "không có công cụ nào tính tổng hộ bạn.\n\n"
    "Quy trình bắt buộc:\n"
    "1. Gọi get_order_items(order_id) để lấy các dòng item thô (price, freight_value).\n"
    "2. Gọi get_order_payments(order_id) để lấy các dòng payment thô (payment_sequential, "
    "payment_type, payment_value).\n"
    "3. Tự tính (làm tròn 2 chữ số thập phân ở MỖI bước):\n"
    "   item_total_brl = tổng price của mọi item\n"
    "   freight_total_brl = tổng freight_value của mọi item\n"
    "   expected_total_brl = item_total_brl + freight_total_brl\n"
    "   payment_total_brl = tổng payment_value của mọi payment\n"
    "   difference_brl = payment_total_brl - expected_total_brl\n"
    "   reconciled = true nếu |difference_brl| <= 0.10, ngược lại false\n"
    "4. NGOẠI LỆ: nếu KHÔNG có item row nào, đặt item_total_brl=0.0, freight_total_brl=0.0, "
    "payment_total_brl = tổng payment_value (0.0 nếu cũng không có payment), còn "
    "expected_total_brl, difference_brl, reconciled đều PHẢI là null.\n"
    f"5. Tự dựng payment_ids dạng \"<order_id>:<payment_sequential>\" (giữ thứ tự gốc, tối đa "
    f"{LIMITS['payment_ids']}), và payment_types là danh sách payment_type không trùng lặp "
    "(giữ thứ tự xuất hiện đầu tiên).\n"
    "6. Gọi report_payment với các số liệu đã tự tính và 1-2 câu tiếng Việt nhận định: tổng "
    "khách trả có khớp tổng tiền hàng + phí ship trong sai số 0.10 BRL không; nếu chia nhiều "
    "lần thanh toán thì có hợp lệ không."
)

FINAL_TOOL = {
    "name": "report_payment",
    "description": "Nộp kết quả cuối cùng về đối soát thanh toán của đơn hàng.",
    "parameters": {
        "type": "object",
        "properties": {
            "payment_ids": {"type": "array", "items": {"type": "string"}, "maxItems": LIMITS["payment_ids"]},
            "item_total_brl": {"type": "number"},
            "freight_total_brl": {"type": "number"},
            "expected_total_brl": {"type": ["number", "null"]},
            "payment_total_brl": {"type": "number"},
            "difference_brl": {"type": ["number", "null"]},
            "reconciled": {"type": ["boolean", "null"]},
            "payment_types": {"type": "array", "items": {"type": "string"}},
            "rationale": {"type": "string", "description": "1-2 câu tiếng Việt nhận định."},
        },
        "required": [
            "payment_ids", "item_total_brl", "freight_total_brl", "expected_total_brl",
            "payment_total_brl", "difference_brl", "reconciled", "payment_types", "rationale",
        ],
    },
}

CARD = AgentCard(
    name="payment-agent",
    description="Reconciles payment rows against item + freight totals.",
    url=agent_url("payment"),
    skills=ALLOWED_TOOLS,
)


async def handle(payload: HandoffPayload) -> HandoffPayload:
    order_id = payload.facts["order_id"]

    async with mcp_session() as session:
        args, chosen = await agent_tool_loop(
            SYSTEM, f"Đối soát thanh toán cho đơn hàng có order_id = {order_id}.",
            ALLOWED_TOOLS, FINAL_TOOL, session,
        )

    payment_ids = args.get("payment_ids", [])
    evidence = [f"payment:{p}" for p in payment_ids]
    missing = []
    if args.get("reconciled") is None:
        missing.append("order has no item rows: expected_total_brl/difference_brl/reconciled are null")

    facts = {
        "payment_reconciliation": {
            "currency": "BRL",
            "item_total_brl": args.get("item_total_brl"),
            "freight_total_brl": args.get("freight_total_brl"),
            "expected_total_brl": args.get("expected_total_brl"),
            "payment_total_brl": args.get("payment_total_brl"),
            "difference_brl": args.get("difference_brl"),
            "reconciled": args.get("reconciled"),
            "payment_types": args.get("payment_types", []),
        },
        "payment_ids": payment_ids,
        "tools_called_by_llm": chosen,
    }
    return HandoffPayload(
        ticket_id=payload.ticket_id,
        from_agent="payment",
        question=payload.question,
        facts=facts,
        evidence_ids=evidence,
        missing=missing,
        next_action="handoff to policy agent",
        note=args.get("rationale", ""),
    )


app = build_agent_app(CARD, handle)
