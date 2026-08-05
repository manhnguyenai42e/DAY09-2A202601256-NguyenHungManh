"""Customer Agent: LLM agent for customer identity + order history.
Facts are grounded via MCP tools; the LLM reasons over them and writes the
expert assessment carried in the handoff note."""

from __future__ import annotations

from src.a2a_common.protocol import AgentCard, HandoffPayload
from src.agents.base import agent_tool_loop, build_agent_app, call_tool, mcp_session
from src.config import agent_url

ALLOWED_TOOLS = ["get_customer_context"]

SYSTEM = (
    "Bạn là Customer Agent trong hệ thống điều tra khiếu nại thương mại điện tử Olist. "
    "Nhiệm vụ: xác định danh tính khách hàng và lịch sử mua hàng của họ. "
    "Bạn có công cụ tra cứu dữ liệu — hãy gọi công cụ phù hợp để lấy dữ liệu thật, "
    "tuyệt đối không tự bịa dữ liệu. Sau khi có kết quả, nhận định ngắn gọn 1-2 câu "
    "tiếng Việt: khách này là khách quen hay khách mới, có đơn liên quan nào đáng đối chiếu."
)

CARD = AgentCard(
    name="customer-agent",
    description="Resolves customer identity and related order history for a claimed order.",
    url=agent_url("customer"),
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
        ctx = collected.get("get_customer_context")
        if ctx is None:
            # Safety net: the model did not (or was not asked to) call the tool.
            # Facts must exist regardless, so fetch deterministically and say so.
            ctx = await call_tool(session, "get_customer_context", {"order_id": order_id})
            chosen = chosen or ["get_customer_context (deterministic fallback)"]

    missing = [] if ctx.get("found") else ["order not found for customer lookup"]
    facts = {
        "customer_context": {k: v for k, v in ctx.items() if k != "found"},
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
        note=note,
    )


app = build_agent_app(CARD, handle)
