"""Payment Agent: payment rows + reconciliation against item+freight totals,
grounded via MCP only (arithmetic is deterministic, not LLM-guessed)."""

from __future__ import annotations

from src.a2a_common.protocol import AgentCard, HandoffPayload
from src.agents.base import build_agent_app, call_tool, mcp_session
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

    return HandoffPayload(
        ticket_id=payload.ticket_id,
        from_agent="payment",
        question=payload.question,
        facts={"payment_reconciliation": {k: v for k, v in recon.items() if k != "found"}},
        evidence_ids=evidence,
        missing=missing,
        next_action="handoff to policy agent",
    )


app = build_agent_app(CARD, handle)
