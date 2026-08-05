"""Delivery Agent: LLM agent for delivery + seller-handoff analysis. It reads
raw timestamps and must itself do every hour-difference and grouping — no
tool computes variance for it."""

from __future__ import annotations

from src.a2a_common.protocol import AgentCard, HandoffPayload
from src.agents.base import agent_tool_loop, build_agent_app, mcp_session
from src.config import agent_url

ALLOWED_TOOLS = ["get_order", "get_order_items"]

SYSTEM = (
    "Bạn là Delivery Agent trong hệ thống điều tra khiếu nại thương mại điện tử Olist. "
    "Nhiệm vụ: phân tích giao vận của đơn hàng, hoàn toàn tự mình trừ ngày giờ và làm tròn — "
    "không có công cụ nào tính sẵn hộ bạn.\n\n"
    "Quy trình bắt buộc:\n"
    "1. Gọi get_order(order_id) để lấy order_delivered_customer_date (delivered_at), "
    "order_estimated_delivery_date (estimated_delivery_at), order_delivered_carrier_date "
    "(carrier_handoff_at).\n"
    "2. Gọi get_order_items(order_id) để lấy các dòng item thô (seller_id, shipping_limit_date).\n"
    "3. Tự tính delivery_variance_hours = (delivered_at - estimated_delivery_at) tính bằng "
    "giờ, làm tròn 2 chữ số thập phân, dương nghĩa là giao trễ. Nếu delivered_at là null thì "
    "delivery_variance_hours cũng là null.\n"
    "4. Nếu carrier_handoff_at là null: seller_handoff_analysis = [] và "
    "late_handoff_seller_ids = [] (không có sự kiện bàn giao để phân tích).\n"
    "5. Nếu carrier_handoff_at có giá trị: với MỖI seller_id xuất hiện trong item (gộp các "
    "item cùng seller lại), lấy shipping_limit_date NHỎ NHẤT (sớm nhất) trong các item của "
    "seller đó làm shipping_limit_at; tự tính handoff_variance_hours = (carrier_handoff_at - "
    "shipping_limit_at) tính bằng giờ, làm tròn 2 chữ số thập phân; late_handoff = true nếu "
    "handoff_variance_hours > 0, ngược lại false. late_handoff_seller_ids là danh sách "
    "seller_id có late_handoff = true.\n"
    "6. Gọi report_delivery với đầy đủ số liệu đã tự tính và 1-2 câu tiếng Việt nhận định: "
    "đơn giao sớm hay trễ (delivery_variance_hours dương là trễ); nếu trễ thì lỗi thuộc seller "
    "(có seller bàn giao muộn hơn shipping_limit_date) hay thuộc đơn vị vận chuyển (không "
    "seller nào muộn)."
)

FINAL_TOOL = {
    "name": "report_delivery",
    "description": "Nộp kết quả cuối cùng về phân tích giao vận của đơn hàng.",
    "parameters": {
        "type": "object",
        "properties": {
            "delivered_at": {"type": ["string", "null"]},
            "estimated_delivery_at": {"type": ["string", "null"]},
            "carrier_handoff_at": {"type": ["string", "null"]},
            "delivery_variance_hours": {"type": ["number", "null"]},
            "seller_handoff_analysis": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "seller_id": {"type": "string"},
                        "shipping_limit_at": {"type": ["string", "null"]},
                        "handoff_variance_hours": {"type": ["number", "null"]},
                        "late_handoff": {"type": "boolean"},
                    },
                    "required": ["seller_id", "shipping_limit_at", "handoff_variance_hours", "late_handoff"],
                },
            },
            "late_handoff_seller_ids": {"type": "array", "items": {"type": "string"}},
            "rationale": {"type": "string", "description": "1-2 câu tiếng Việt nhận định."},
        },
        "required": [
            "delivered_at", "estimated_delivery_at", "carrier_handoff_at",
            "delivery_variance_hours", "seller_handoff_analysis", "late_handoff_seller_ids",
            "rationale",
        ],
    },
}

CARD = AgentCard(
    name="delivery-agent",
    description="Computes delivery variance and per-seller shipping-limit handoff variance.",
    url=agent_url("delivery"),
    skills=ALLOWED_TOOLS,
)


async def handle(payload: HandoffPayload) -> HandoffPayload:
    order_id = payload.facts["order_id"]

    async with mcp_session() as session:
        args, chosen = await agent_tool_loop(
            SYSTEM, f"Phân tích giao vận cho đơn hàng có order_id = {order_id}.",
            ALLOWED_TOOLS, FINAL_TOOL, session,
        )

    late_sellers = args.get("late_handoff_seller_ids", [])
    evidence = [f"seller:{sid}" for sid in late_sellers]
    missing = []
    if args.get("delivered_at") is None:
        missing.append("order_delivered_customer_date is null: delivery lateness cannot be determined")

    facts = {
        "delivery_analysis": {
            "delivered_at": args.get("delivered_at"),
            "estimated_delivery_at": args.get("estimated_delivery_at"),
            "carrier_handoff_at": args.get("carrier_handoff_at"),
            "delivery_variance_hours": args.get("delivery_variance_hours"),
            "seller_handoff_analysis": args.get("seller_handoff_analysis", []),
            "late_handoff_seller_ids": late_sellers,
        },
        "tools_called_by_llm": chosen,
    }
    return HandoffPayload(
        ticket_id=payload.ticket_id,
        from_agent="delivery",
        question=payload.question,
        facts=facts,
        evidence_ids=evidence,
        missing=missing,
        next_action="handoff to policy agent",
        note=args.get("rationale", ""),
    )


app = build_agent_app(CARD, handle)
