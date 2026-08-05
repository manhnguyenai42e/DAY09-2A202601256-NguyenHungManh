"""Order & Product Agent: LLM agent for order/item/seller entities and
product/category context. Facts grounded via MCP; LLM writes the assessment."""

from __future__ import annotations

from src.a2a_common.protocol import AgentCard, HandoffPayload
from src.agents.base import agent_reflect, build_agent_app, call_tool, mcp_session
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
    facts = {
        "affected_entities": {k: v for k, v in entities.items() if k != "found"},
        "product_context": {k: v for k, v in product_ctx.items() if k != "found"},
    }
    note = await agent_reflect(
        "kiểm tra cấu trúc đơn hàng: bao nhiêu item, bao nhiêu seller, ngành hàng nào; "
        "đơn nhiều seller hay nhiều ngành hàng thì phức tạp hơn khi xử lý khiếu nại.",
        facts,
        skip=bool(payload.facts.get("skip_narration")),
    )
    return HandoffPayload(
        ticket_id=payload.ticket_id,
        from_agent="order_product",
        question=payload.question,
        facts=facts,
        evidence_ids=evidence,
        missing=missing,
        next_action="handoff to policy agent",
        note=note,
    )


app = build_agent_app(CARD, handle)
