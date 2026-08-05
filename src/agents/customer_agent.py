"""Customer Agent: identity + order history, grounded via MCP only (no LLM —
pure retrieval, nothing to judge)."""

from __future__ import annotations

from src.a2a_common.protocol import AgentCard, HandoffPayload
from src.agents.base import build_agent_app, call_tool, mcp_session
from src.config import agent_url

CARD = AgentCard(
    name="customer-agent",
    description="Resolves customer identity and related order history for a claimed order.",
    url=agent_url("customer"),
    skills=["get_customer_context"],
)


async def handle(payload: HandoffPayload) -> HandoffPayload:
    order_id = payload.facts["order_id"]
    async with mcp_session() as session:
        ctx = await call_tool(session, "get_customer_context", {"order_id": order_id})

    missing = [] if ctx.get("found") else ["order not found for customer lookup"]
    return HandoffPayload(
        ticket_id=payload.ticket_id,
        from_agent="customer",
        question=payload.question,
        facts={"customer_context": {k: v for k, v in ctx.items() if k != "found"}},
        evidence_ids=[],
        missing=missing,
        next_action="handoff to policy agent",
    )


app = build_agent_app(CARD, handle)
