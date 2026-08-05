"""Order & Product Agent: LLM agent for order/item/seller entities and
product/category context. Facts grounded via MCP; LLM writes the assessment."""

from __future__ import annotations

from src.a2a_common.protocol import AgentCard, HandoffPayload
from src.agents.base import agent_tool_loop, build_agent_app, call_tool, mcp_session
from src.config import agent_url

ALLOWED_TOOLS = ["get_affected_entities", "get_product_context"]

SYSTEM = (
    "Bạn là Order & Product Agent trong hệ thống điều tra khiếu nại thương mại điện tử Olist. "
    "Nhiệm vụ: xác định cấu trúc đơn hàng (item, seller) và bối cảnh sản phẩm (ngành hàng). "
    "Bạn có các công cụ tra cứu — hãy gọi những công cụ cần thiết để lấy dữ liệu thật, "
    "tuyệt đối không bịa dữ liệu. Sau đó nhận định 1-2 câu tiếng Việt về độ phức tạp của đơn: "
    "nhiều item / nhiều seller / nhiều ngành hàng thì việc xử lý khiếu nại phức tạp hơn."
)

CARD = AgentCard(
    name="order-product-agent",
    description="Resolves order/item/seller entities and product/category context.",
    url=agent_url("order_product"),
    skills=ALLOWED_TOOLS,
)


async def handle(payload: HandoffPayload) -> HandoffPayload:
    order_id = payload.facts["order_id"]
    skip = bool(payload.facts.get("skip_narration"))

    async with mcp_session() as session:
        note, collected, chosen = ("", {}, [])
        if not skip:
            note, collected, chosen = await agent_tool_loop(
                SYSTEM, f"Điều tra khiếu nại cho đơn hàng có order_id = {order_id}.",
                ALLOWED_TOOLS, session,
            )
        entities = collected.get("get_affected_entities")
        if entities is None:
            entities = await call_tool(session, "get_affected_entities", {"order_id": order_id})
        product_ctx = collected.get("get_product_context")
        if product_ctx is None:
            product_ctx = await call_tool(session, "get_product_context", {"order_id": order_id})

    evidence = [f"order:{order_id}"] + [f"item:{i}" for i in entities.get("item_ids", [])]
    missing = [] if entities.get("found") else ["order not found for entity lookup"]
    facts = {
        "affected_entities": {k: v for k, v in entities.items() if k != "found"},
        "product_context": {k: v for k, v in product_ctx.items() if k != "found"},
        "tools_called_by_llm": chosen,
    }
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
