"""Coordinator: the A2A client that sequences the other 6 agents for one
ticket. Customer / Order&Product / Payment / Delivery run in parallel
(independent evidence gathering), then Policy, then Verifier — with one
bounded retry back to Policy if the Verifier finds violations. Also exposed
as its own A2A service (agent card + /a2a) for architectural symmetry, but
`run_case` is called in-process by scripts/run_batch.py to avoid an extra
network hop on the batch entry point itself.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from src.a2a_common.protocol import AgentCard, HandoffPayload
from src.agents.base import build_agent_app, send_handoff
from src.config import agent_url

CARD = AgentCard(
    name="coordinator-agent",
    description="Receives a dispute ticket, sequences the domain agents, and assembles the final case.",
    url=agent_url("coordinator"),
    skills=["investigate_case"],
)

MAX_VERIFIER_RETRIES = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _trace_event(case_id: str, agent: str, req: HandoffPayload, resp: HandoffPayload) -> dict[str, Any]:
    return {
        "timestamp": _now(),
        "case_id": case_id,
        "agent": agent,
        "question": req.question,
        "facts_reported": list(resp.facts.keys()),
        "evidence_ids": resp.evidence_ids,
        "missing": resp.missing,
        "next_action": resp.next_action,
        "note": resp.note,
    }


async def run_case(ticket: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    case_id = ticket["case_id"]
    order_id = ticket["customer_request"]["claimed_order_id"]
    trace: list[dict[str, Any]] = []

    def handoff(question: str, facts: dict[str, Any], from_agent: str = "coordinator") -> HandoffPayload:
        return HandoffPayload(ticket_id=case_id, from_agent=from_agent, question=question, facts=facts)

    import os as _os

    base_facts = {
        "order_id": order_id,
        "skip_narration": bool(_os.environ.get("EC_SKIP_NARRATION")),
    }
    (customer_resp, order_product_resp, payment_resp, delivery_resp) = await asyncio.gather(
        send_handoff(agent_url("customer"), handoff("resolve customer identity + history", base_facts)),
        send_handoff(agent_url("order_product"), handoff("resolve order/item/seller/product entities", base_facts)),
        send_handoff(agent_url("payment"), handoff("reconcile payments vs item+freight", base_facts)),
        send_handoff(agent_url("delivery"), handoff("compute delivery + seller handoff variance", base_facts)),
    )
    for name, resp in [
        ("customer", customer_resp),
        ("order_product", order_product_resp),
        ("payment", payment_resp),
        ("delivery", delivery_resp),
    ]:
        trace.append(_trace_event(case_id, name, handoff("", base_facts), resp))

    import os

    policy_facts = {
        "skip_narration": bool(os.environ.get("EC_SKIP_NARRATION")),
        "order_id": order_id,
        "customer_context": customer_resp.facts.get("customer_context"),
        "affected_entities": order_product_resp.facts.get("affected_entities"),
        "product_context": order_product_resp.facts.get("product_context"),
        "payment_reconciliation": payment_resp.facts.get("payment_reconciliation"),
        "delivery_analysis": delivery_resp.facts.get("delivery_analysis"),
    }
    policy_req = handoff("apply EC_POLICY_V2 and draft rationale", policy_facts)
    policy_resp = await send_handoff(agent_url("policy"), policy_req)
    trace.append(_trace_event(case_id, "policy", policy_req, policy_resp))

    verifier_req = handoff(
        "verify schema, limits and evidence grounding",
        {"case": policy_resp.facts["case"], "skip_narration": base_facts["skip_narration"]},
    )
    verifier_resp = await send_handoff(agent_url("verifier"), verifier_req)
    trace.append(_trace_event(case_id, "verifier", verifier_req, verifier_resp))

    retries = 0
    while not verifier_resp.facts.get("valid", True) and retries < MAX_VERIFIER_RETRIES:
        retries += 1
        policy_resp = await send_handoff(agent_url("policy"), policy_req)
        trace.append(_trace_event(case_id, "policy_retry", policy_req, policy_resp))
        verifier_req = handoff(
            "re-verify after policy retry",
            {"case": policy_resp.facts["case"], "skip_narration": base_facts["skip_narration"]},
        )
        verifier_resp = await send_handoff(agent_url("verifier"), verifier_req)
        trace.append(_trace_event(case_id, "verifier_retry", verifier_req, verifier_resp))

    case = dict(policy_resp.facts["case"])
    case["case_id"] = case_id
    # README section 6 lists case_id first; keep field order stable/readable.
    case = {"case_id": case["case_id"], **{k: v for k, v in case.items() if k != "case_id"}}

    if not verifier_resp.facts.get("valid", True):
        trace.append(
            {
                "timestamp": _now(),
                "case_id": case_id,
                "agent": "coordinator",
                "question": "final gate",
                "note": "UNRESOLVED VERIFIER VIOLATIONS after retry: " + "; ".join(verifier_resp.missing),
            }
        )

    return case, trace


async def handle(payload: HandoffPayload) -> HandoffPayload:
    ticket = payload.facts["ticket"]
    case, _trace = await run_case(ticket)
    return HandoffPayload(
        ticket_id=payload.ticket_id,
        from_agent="coordinator",
        question=payload.question,
        facts={"case": case},
        evidence_ids=case.get("evidence_ids", []),
        next_action="submitted",
    )


app = build_agent_app(CARD, handle)
