"""Delivery Agent: delivery variance + per-seller handoff variance, grounded
via MCP only (date-diff arithmetic is deterministic, not LLM-guessed)."""

from __future__ import annotations

from src.a2a_common.protocol import AgentCard, HandoffPayload
from src.agents.base import build_agent_app, call_tool, mcp_session
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

    return HandoffPayload(
        ticket_id=payload.ticket_id,
        from_agent="delivery",
        question=payload.question,
        facts={"delivery_analysis": {k: v for k, v in delivery.items() if k != "found"}},
        evidence_ids=evidence,
        missing=missing,
        next_action="handoff to policy agent",
    )


app = build_agent_app(CARD, handle)
