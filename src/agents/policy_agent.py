"""Policy Agent: applies EC_POLICY_V2 (deterministic, via MCP apply_policy tool)
and uses the local Ollama model for exactly one thing — narrating *why* in
plain language for trace.jsonl. The classification, refund and evidence IDs
themselves are never left to the LLM."""

from __future__ import annotations

import json

from src.a2a_common.protocol import AgentCard, HandoffPayload
from src.agents.base import build_agent_app, call_tool, mcp_session, ollama_generate
from src.config import agent_url

CARD = AgentCard(
    name="policy-agent",
    description="Applies EC_POLICY_V2 to upstream facts and drafts the case rationale.",
    url=agent_url("policy"),
    skills=["apply_policy"],
)

SYSTEM_PROMPT = (
    "You are a policy compliance agent for an e-commerce dispute desk. "
    "You are given a JSON object that is already the final, deterministic policy decision "
    "(primary_issue, evidence_ids, refund, actions). Do not change any values or invent new "
    "facts or evidence IDs. In 2-3 short sentences, explain in Vietnamese why this decision "
    "follows from the evidence, citing the evidence IDs given. Output plain text only."
)


async def handle(payload: HandoffPayload) -> HandoffPayload:
    order_id = payload.facts["order_id"]
    async with mcp_session() as session:
        case = await call_tool(session, "apply_policy", {"order_id": order_id})

    try:
        note = await ollama_generate(SYSTEM_PROMPT, json.dumps(case, ensure_ascii=False))
    except Exception as exc:  # local model unavailable/slow — never block the pipeline on narration
        note = f"[narration unavailable: {exc}]"

    return HandoffPayload(
        ticket_id=payload.ticket_id,
        from_agent="policy",
        question=payload.question,
        facts={"case": case},
        evidence_ids=case["evidence_ids"],
        missing=[],
        next_action="handoff to verifier",
        note=note,
    )


app = build_agent_app(CARD, handle)
