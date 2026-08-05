"""Delivery Agent: LLM agent for delivery + seller-handoff analysis. Date
arithmetic is deterministic (MCP tool); the LLM reasons over the variances."""

from __future__ import annotations

from src.a2a_common.protocol import AgentCard, HandoffPayload
from src.agents.base import agent_tool_loop, build_agent_app, call_tool, mcp_session
from src.config import agent_url

ALLOWED_TOOLS = ["get_delivery_analysis"]

SYSTEM = (
    "Bạn là Delivery Agent trong hệ thống điều tra khiếu nại thương mại điện tử Olist. "
    "Nhiệm vụ: phân tích giao vận của đơn hàng. Bạn có công cụ tra cứu — hãy gọi công cụ "
    "để lấy số liệu thật, tuyệt đối không tự tính hay bịa số. Sau đó nhận định 1-2 câu "
    "tiếng Việt: đơn giao sớm hay trễ so với hẹn (delivery_variance_hours dương là trễ); "
    "nếu trễ thì lỗi thuộc seller (có seller bàn giao muộn hơn shipping_limit_date) hay "
    "thuộc đơn vị vận chuyển (không seller nào muộn)."
)

CARD = AgentCard(
    name="delivery-agent",
    description="Computes delivery variance and per-seller shipping-limit handoff variance.",
    url=agent_url("delivery"),
    skills=ALLOWED_TOOLS,
)


async def handle(payload: HandoffPayload) -> HandoffPayload:
    order_id = payload.facts["order_id"]
    skip = bool(payload.facts.get("skip_narration"))

    async with mcp_session() as session:
        note, collected, chosen = ("", {}, [])
        if not skip:
            note, collected, chosen = await agent_tool_loop(
                SYSTEM, f"Phân tích giao vận cho đơn hàng có order_id = {order_id}.",
                ALLOWED_TOOLS, session,
            )
        delivery = collected.get("get_delivery_analysis")
        if delivery is None:
            delivery = await call_tool(session, "get_delivery_analysis", {"order_id": order_id})

    late_sellers = delivery.get("late_handoff_seller_ids", [])
    evidence = [f"seller:{sid}" for sid in late_sellers]
    missing = []
    if delivery.get("delivered_at") is None:
        missing.append("order_delivered_customer_date is null: delivery lateness cannot be determined")

    facts = {
        "delivery_analysis": {k: v for k, v in delivery.items() if k != "found"},
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
        note=note,
    )


app = build_agent_app(CARD, handle)
