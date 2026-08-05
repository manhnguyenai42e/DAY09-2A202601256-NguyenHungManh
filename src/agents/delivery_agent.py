"""Delivery Agent: LLM agent for delivery + seller-handoff analysis. Date
arithmetic is deterministic (MCP tool); the LLM reasons over the variances."""

from __future__ import annotations

from src.a2a_common.protocol import AgentCard, HandoffPayload
from src.agents.base import agent_reflect, build_agent_app, call_tool, mcp_session
from src.config import agent_url

CARD = AgentCard(
    name="delivery-agent",
    description="Computes delivery variance and per-seller shipping-limit handoff variance.",
    url=agent_url("delivery"),
    skills=["get_delivery_analysis"],
)


async def handle(payload: HandoffPayload) -> HandoffPayload:
    order_id = payload.facts["order_id"]
    async with mcp_session() as session:
        delivery = await call_tool(session, "get_delivery_analysis", {"order_id": order_id})

    late_sellers = delivery.get("late_handoff_seller_ids", [])
    evidence = [f"seller:{sid}" for sid in late_sellers]
    missing = []
    if delivery.get("delivered_at") is None:
        missing.append("order_delivered_customer_date is null: delivery lateness cannot be determined")

    facts = {"delivery_analysis": {k: v for k, v in delivery.items() if k != "found"}}
    note = await agent_reflect(
        "phân tích giao vận: đơn giao sớm hay trễ so với hẹn (delivery_variance_hours "
        "dương là trễ), và nếu trễ thì seller nào bàn giao cho carrier muộn hơn "
        "shipping_limit_date (trách nhiệm seller) hay không seller nào muộn (trách nhiệm "
        "đơn vị vận chuyển).",
        facts,
        skip=bool(payload.facts.get("skip_narration")),
    )
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
