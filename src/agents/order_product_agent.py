"""Order & Product Agent: order/item/seller entities + product/category
context, grounded via MCP only."""

from __future__ import annotations

from src.a2a_common.protocol import AgentCard, HandoffPayload
from src.agents.base import build_agent_app, call_tool, mcp_session
from src.config import agent_url

CARD = AgentCard(
    name="order-product-agent",
    description="Resolves order/item/seller entities and product/category context.",
    url=agent_url("order_product"),
    skills=["get_affected_entities", "get_product_context"],
)


async def handle(payload: HandoffPayload) -> HandoffPayload:
    order_id = payload.facts["order_id"]
    async with mcp_session() as session:
        entities = await call_tool(session, "get_affected_entities", {"order_id": order_id})
        product_ctx = await call_tool(session, "get_product_context", {"order_id": order_id})

    evidence = [f"order:{order_id}"] + [f"item:{i}" for i in entities.get("item_ids", [])]
    missing = [] if entities.get("found") else ["order not found for entity lookup"]

    return HandoffPayload(
        ticket_id=payload.ticket_id,
        from_agent="order_product",
        question=payload.question,
        facts={
            "affected_entities": {k: v for k, v in entities.items() if k != "found"},
            "product_context": {k: v for k, v in product_ctx.items() if k != "found"},
        },
        evidence_ids=evidence,
        missing=missing,
        next_action="handoff to policy agent",
    )


app = build_agent_app(CARD, handle)
