"""Customer Agent: LLM agent for customer identity + order history.
Facts are grounded via MCP tools; the LLM reasons over them and writes the
expert assessment carried in the handoff note."""

from __future__ import annotations

from src.a2a_common.protocol import AgentCard, HandoffPayload
from src.agents.base import agent_reflect, build_agent_app, call_tool, mcp_session
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
    facts = {"customer_context": {k: v for k, v in ctx.items() if k != "found"}}
    note = await agent_reflect(
        "xác định danh tính khách hàng và lịch sử mua hàng (khách quen hay khách mới, "
        "có đơn liên quan nào đáng đối chiếu không).",
        facts,
        skip=bool(payload.facts.get("skip_narration")),
    )
    return HandoffPayload(
        ticket_id=payload.ticket_id,
        from_agent="customer",
        question=payload.question,
        facts=facts,
        evidence_ids=[],
        missing=missing,
        next_action="handoff to policy agent",
        note=note,
    )


app = build_agent_app(CARD, handle)
