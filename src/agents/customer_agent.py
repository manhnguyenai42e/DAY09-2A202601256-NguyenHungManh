"""Customer Agent: LLM agent for customer identity + order history.
Every value in its report — customer_unique_id, the related-order list, the
exclusion of the current order, the 5-item cap — is decided and written by
the model itself from raw MCP data; nothing here computes or filters it."""

from __future__ import annotations

from src.a2a_common.protocol import AgentCard, HandoffPayload
from src.agents.base import agent_tool_loop, build_agent_app, mcp_session
from src.config import LIMITS, agent_url

ALLOWED_TOOLS = ["get_customer", "get_related_orders"]

SYSTEM = (
    "Bạn là Customer Agent trong hệ thống điều tra khiếu nại thương mại điện tử Olist. "
    "Nhiệm vụ: xác định danh tính khách hàng và lịch sử mua hàng của họ, hoàn toàn tự "
    "mình tra cứu và tính toán — không có công cụ nào tính sẵn hộ bạn.\n\n"
    "Quy trình bắt buộc:\n"
    "1. Gọi get_customer(order_id) để lấy customer_unique_id của khách đặt đơn này.\n"
    "2. Gọi get_related_orders(customer_unique_id) để lấy TOÀN BỘ order_id của khách này "
    "(bao gồm cả đơn hiện tại).\n"
    "3. Tự loại bỏ order_id của đơn đang điều tra khỏi danh sách, tự giữ tối đa "
    f"{LIMITS['related_order_ids']} order_id đầu tiên theo đúng thứ tự trả về.\n"
    "4. Gọi report_customer với customer_unique_id, related_order_ids (đã lọc) và 1-2 câu "
    "tiếng Việt nhận định (khách quen hay khách mới, có đơn nào đáng đối chiếu).\n"
    "Nếu get_customer trả found=false, đặt customer_unique_id=null và related_order_ids=[].\n"
    "LƯU Ý: nếu get_related_orders chỉ trả về đúng order_id của đơn đang xét (khách này chưa "
    "từng mua đơn nào khác), thì sau khi loại trừ, related_order_ids PHẢI là mảng rỗng [] — "
    "đây là kết quả HỢP LỆ và ĐẦY ĐỦ, không cần gọi lại get_related_orders để tìm thêm. Gọi "
    "report_customer ngay với related_order_ids=[]."
)

FINAL_TOOL = {
    "name": "report_customer",
    "description": "Nộp kết quả cuối cùng về danh tính khách hàng và lịch sử đơn liên quan.",
    "parameters": {
        "type": "object",
        "properties": {
            "customer_unique_id": {"type": ["string", "null"]},
            "related_order_ids": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": LIMITS["related_order_ids"],
            },
            "rationale": {"type": "string", "description": "1-2 câu tiếng Việt nhận định."},
        },
        "required": ["customer_unique_id", "related_order_ids", "rationale"],
    },
}

CARD = AgentCard(
    name="customer-agent",
    description="Resolves customer identity and related order history for a claimed order.",
    url=agent_url("customer"),
    skills=ALLOWED_TOOLS,
)


async def handle(payload: HandoffPayload) -> HandoffPayload:
    order_id = payload.facts["order_id"]

    async with mcp_session() as session:
        args, chosen = await agent_tool_loop(
            SYSTEM, f"Điều tra khiếu nại cho đơn hàng có order_id = {order_id}.",
            ALLOWED_TOOLS, FINAL_TOOL, session,
        )

    missing = [] if args.get("customer_unique_id") else ["customer not found for this order"]
    facts = {
        "customer_context": {
            "customer_unique_id": args.get("customer_unique_id"),
            "related_order_ids": args.get("related_order_ids", []),
        },
        "tools_called_by_llm": chosen,
    }
    return HandoffPayload(
        ticket_id=payload.ticket_id,
        from_agent="customer",
        question=payload.question,
        facts=facts,
        evidence_ids=[],
        missing=missing,
        next_action="handoff to policy agent",
        note=args.get("rationale", ""),
    )


app = build_agent_app(CARD, handle)
