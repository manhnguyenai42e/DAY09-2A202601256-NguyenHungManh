"""Payment Agent: LLM agent for payment reconciliation. The arithmetic is
deterministic (MCP tool); the LLM reasons over the reconciliation result."""

from __future__ import annotations

from src.a2a_common.protocol import AgentCard, HandoffPayload
from src.agents.base import agent_reflect, build_agent_app, call_tool, mcp_session
from src.config import agent_url

CARD = AgentCard(
    name="payment-agent",
    description="Reconciles payment rows against item + freight totals.",
    url=agent_url("payment"),
    skills=["get_payment_reconciliation"],
)


async def handle(payload: HandoffPayload) -> HandoffPayload:
    order_id = payload.facts["order_id"]
    async with mcp_session() as session:
        recon = await call_tool(session, "get_payment_reconciliation", {"order_id": order_id})
        entities = await call_tool(session, "get_affected_entities", {"order_id": order_id})

    payment_ids = entities.get("payment_ids", [])
    evidence = [f"payment:{p}" for p in payment_ids]
    missing = []
    if recon.get("reconciled") is None:
        missing.append("order has no item rows: expected_total_brl/difference_brl/reconciled are null")

    facts = {"payment_reconciliation": {k: v for k, v in recon.items() if k != "found"}}
    note = await agent_reflect(
        "đối soát thanh toán: tổng khách trả có khớp tổng item + phí ship trong sai số "
        "0.10 BRL không; thanh toán chia nhiều lần (split) có hợp lệ không.",
        facts,
        skip=bool(payload.facts.get("skip_narration")),
    )
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
