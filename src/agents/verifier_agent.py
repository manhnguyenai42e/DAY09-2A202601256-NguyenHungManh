"""Verifier Agent: checks schema completeness, array limits and evidence
grounding against the source CSVs before a case is allowed to be written to
output/. Deterministic (via MCP validate_case_output); no LLM involved —
this is the last gate before submission and must not be able to hallucinate
a pass."""

from __future__ import annotations

from src.a2a_common.protocol import AgentCard, HandoffPayload
from src.agents.base import build_agent_app, call_tool, mcp_session
from src.config import agent_url

CARD = AgentCard(
    name="verifier-agent",
    description="Validates schema, array limits and evidence grounding before submission.",
    url=agent_url("verifier"),
    skills=["validate_case_output"],
)


async def handle(payload: HandoffPayload) -> HandoffPayload:
    case = dict(payload.facts["case"])
    case["case_id"] = payload.ticket_id

    async with mcp_session() as session:
        result = await call_tool(session, "validate_case_output", {"case_json": case})

    violations = result.get("violations", [])
    return HandoffPayload(
        ticket_id=payload.ticket_id,
        from_agent="verifier",
        question=payload.question,
        facts={"valid": result.get("valid", False), "violations": violations},
        evidence_ids=case.get("evidence_ids", []),
        missing=violations,
        next_action="submit" if result.get("valid") else "return to policy agent for revision",
    )


app = build_agent_app(CARD, handle)
