"""Payment Agent: LLM agent for payment reconciliation. The arithmetic is
deterministic (MCP tool); the LLM reasons over the reconciliation result."""

from __future__ import annotations

from src.a2a_common.protocol import AgentCard, HandoffPayload
from src.agents.base import agent_tool_loop, build_agent_app, call_tool, mcp_session
from src.config import agent_url

ALLOWED_TOOLS = ["get_payment_reconciliation", "get_affected_entities"]

SYSTEM = (
    "Bạn là Payment Agent trong hệ thống điều tra khiếu nại thương mại điện tử Olist. "
    "Nhiệm vụ: đối soát thanh toán của đơn hàng. Bạn có các công cụ tra cứu — hãy gọi "
    "công cụ cần thiết để lấy số liệu thật, tuyệt đối không tự tính hay bịa số. "
    "Sau đó nhận định 1-2 câu tiếng Việt: tổng khách trả có khớp tổng tiền hàng + phí ship "
    "trong sai số 0.10 BRL không; nếu thanh toán chia nhiều lần thì có hợp lệ không."
)

CARD = AgentCard(
    name="payment-agent",
    description="Reconciles payment rows against item + freight totals.",
    url=agent_url("payment"),
    skills=ALLOWED_TOOLS,
)


async def handle(payload: HandoffPayload) -> HandoffPayload:
    order_id = payload.facts["order_id"]
    skip = bool(payload.facts.get("skip_narration"))

    async with mcp_session() as session:
        note, collected, chosen = ("", {}, [])
        if not skip:
            note, collected, chosen = await agent_tool_loop(
                SYSTEM, f"Đối soát thanh toán cho đơn hàng có order_id = {order_id}.",
                ALLOWED_TOOLS, session,
            )
        recon = collected.get("get_payment_reconciliation")
        if recon is None:
            recon = await call_tool(session, "get_payment_reconciliation", {"order_id": order_id})
        entities = collected.get("get_affected_entities")
        if entities is None:
            entities = await call_tool(session, "get_affected_entities", {"order_id": order_id})

    payment_ids = entities.get("payment_ids", [])
    evidence = [f"payment:{p}" for p in payment_ids]
    missing = []
    if recon.get("reconciled") is None:
        missing.append("order has no item rows: expected_total_brl/difference_brl/reconciled are null")

    facts = {
        "payment_reconciliation": {k: v for k, v in recon.items() if k != "found"},
        "tools_called_by_llm": chosen,
    }
    return HandoffPayload(
        ticket_id=payload.ticket_id,
        from_agent="payment",
        question=payload.question,
        facts=facts,
        evidence_ids=evidence,
        missing=missing,
        next_action="handoff to policy agent",
        note=note,
    )


app = build_agent_app(CARD, handle)
