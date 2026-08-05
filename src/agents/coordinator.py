"""Coordinator: the A2A client that sequences the other 6 agents for one
ticket. Customer / Order&Product / Payment / Delivery run in parallel
(independent evidence gathering, each self-computing its own numbers), then
Policy, then Verifier — with one bounded retry of the *entire* investigation
(all 4 domain agents + Policy, fresh) if the Verifier finds violations. A
full retry, not just a Policy retry, matters here: the Verifier's audit can
catch a mistake that originated in a domain agent (e.g. a sign error in
Delivery Agent's own date-arithmetic) which re-running Policy alone — it
only reasons over facts already handed to it — could never fix. Also
exposed as its own A2A service (agent card + /a2a) for architectural
symmetry, but `run_case` is called in-process by scripts/run_batch.py to
avoid an extra network hop on the batch entry point itself.

The Coordinator itself never computes or decides any business value — it
only routes payloads between agents and merges their already-authored
sub-objects into the final case shape (README section 6 key order).
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from src.a2a_common.protocol import AgentCard, HandoffPayload
from src.agents.base import build_agent_app, ollama_generate, send_handoff
from src.config import agent_url

TRIAGE_PROMPT = (
    "Bạn là agent điều phối (coordinator) của hệ thống điều tra khiếu nại thương mại điện tử. "
    "Bạn vừa nhận một ticket khiếu nại. Dựa trên nội dung khiếu nại của khách, hãy nêu trong "
    "1-2 câu tiếng Việt: cần tập trung điều tra những khía cạnh nào và giao việc cho các agent "
    "chuyên trách nào (customer / order & product / payment / delivery). Không suy đoán kết luận."
)

SYNTHESIS_PROMPT = (
    "Bạn là agent điều phối (coordinator) đang đóng hồ sơ một vụ khiếu nại thương mại điện tử. "
    "Dưới đây là kết quả điều tra cuối cùng đã qua kiểm định. Hãy viết 1-2 câu tiếng Việt tổng "
    "kết hồ sơ cho người đọc: vấn đề là gì, ai chịu trách nhiệm, xử lý ra sao. Không đổi số liệu, "
    "không bịa thêm dữ kiện."
)

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


def _assemble_case(
    case_id: str,
    order_id: str,
    customer_resp: HandoffPayload,
    order_product_resp: HandoffPayload,
    payment_resp: HandoffPayload,
    delivery_resp: HandoffPayload,
    policy_resp: HandoffPayload,
) -> dict[str, Any]:
    """Pure plumbing: copy each agent's self-authored sub-object into the
    README section 6 shape. No value is computed or altered here."""
    affected_entities = {
        "order_ids": [order_id],
        "item_ids": order_product_resp.facts["affected_entities"]["item_ids"],
        "seller_ids": order_product_resp.facts["affected_entities"]["seller_ids"],
        "payment_ids": payment_resp.facts["payment_ids"],
    }
    return {
        "case_id": case_id,
        "case_assessment": policy_resp.facts["case_assessment"],
        "affected_entities": affected_entities,
        "customer_context": customer_resp.facts["customer_context"],
        "product_context": order_product_resp.facts["product_context"],
        "delivery_analysis": delivery_resp.facts["delivery_analysis"],
        "payment_reconciliation": payment_resp.facts["payment_reconciliation"],
        "root_cause_analysis": policy_resp.facts["root_cause_analysis"],
        "evidence_ids": policy_resp.evidence_ids,
        "financial_resolution": policy_resp.facts["financial_resolution"],
        "resolution_actions": policy_resp.facts["resolution_actions"],
    }


async def _investigate(
    case_id: str, order_id: str, trace: list[dict[str, Any]], suffix: str = ""
) -> dict[str, Any]:
    """One full pass: dispatch all 4 domain agents fresh (parallel), hand
    their self-computed facts to Policy, assemble the case. Used for both the
    initial attempt and each retry — a retry re-runs everything, not just
    Policy, since a Verifier finding can originate in any domain agent."""

    def handoff(question: str, facts: dict[str, Any], from_agent: str = "coordinator") -> HandoffPayload:
        return HandoffPayload(ticket_id=case_id, from_agent=from_agent, question=question, facts=facts)

    base_facts = {"order_id": order_id}

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
        trace.append(_trace_event(case_id, name + suffix, handoff("", base_facts), resp))

    policy_facts = {
        "order_id": order_id,
        "customer_context": customer_resp.facts["customer_context"],
        "affected_entities": {
            **order_product_resp.facts["affected_entities"],
            "payment_ids": payment_resp.facts["payment_ids"],
        },
        "product_context": order_product_resp.facts["product_context"],
        "payment_reconciliation": payment_resp.facts["payment_reconciliation"],
        "delivery_analysis": delivery_resp.facts["delivery_analysis"],
    }
    policy_req = handoff("apply EC_POLICY_V2 and draft rationale", policy_facts)
    policy_resp = await send_handoff(agent_url("policy"), policy_req)
    trace.append(_trace_event(case_id, "policy" + suffix, policy_req, policy_resp))

    return _assemble_case(case_id, order_id, customer_resp, order_product_resp, payment_resp, delivery_resp, policy_resp)


async def run_case(ticket: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    case_id = ticket["case_id"]
    order_id = ticket["customer_request"]["claimed_order_id"]
    trace: list[dict[str, Any]] = []

    def handoff(question: str, facts: dict[str, Any], from_agent: str = "coordinator") -> HandoffPayload:
        return HandoffPayload(ticket_id=case_id, from_agent=from_agent, question=question, facts=facts)

    # Intake triage: the coordinator reasons about the incoming complaint and
    # states what the investigation should focus on before dispatching work.
    try:
        triage_note = await ollama_generate(TRIAGE_PROMPT, json.dumps(ticket, ensure_ascii=False))
    except Exception as exc:
        triage_note = f"[triage unavailable: {exc}]"
    trace.append({
        "timestamp": _now(),
        "case_id": case_id,
        "agent": "coordinator_intake",
        "question": "phân định trọng tâm điều tra và giao việc",
        "facts_reported": ["order_id"],
        "evidence_ids": [],
        "missing": [],
        "next_action": "dispatch to customer/order_product/payment/delivery in parallel",
        "note": triage_note,
    })

    case = await _investigate(case_id, order_id, trace)

    verifier_req = handoff("verify schema, limits and evidence grounding", {"case": case})
    verifier_resp = await send_handoff(agent_url("verifier"), verifier_req)
    trace.append(_trace_event(case_id, "verifier", verifier_req, verifier_resp))

    retries = 0
    while not verifier_resp.facts.get("valid", True) and retries < MAX_VERIFIER_RETRIES:
        retries += 1
        case = await _investigate(case_id, order_id, trace, suffix="_retry")
        verifier_req = handoff("re-verify after full retry", {"case": case})
        verifier_resp = await send_handoff(agent_url("verifier"), verifier_req)
        trace.append(_trace_event(case_id, "verifier_retry", verifier_req, verifier_resp))

    # Prefer the Verifier's copy: it is the one that carries the definitive case_id.
    case = dict(verifier_resp.facts.get("verified_case") or case)

    if not verifier_resp.facts.get("valid", True):
        trace.append({
            "timestamp": _now(),
            "case_id": case_id,
            "agent": "coordinator",
            "question": "final gate",
            "note": "UNRESOLVED VERIFIER VIOLATIONS after retry: " + "; ".join(verifier_resp.missing),
        })

    try:
        synthesis_note = await ollama_generate(SYNTHESIS_PROMPT, json.dumps(case, ensure_ascii=False))
    except Exception as exc:
        synthesis_note = f"[synthesis unavailable: {exc}]"
    trace.append({
        "timestamp": _now(),
        "case_id": case_id,
        "agent": "coordinator_synthesis",
        "question": "tổng kết hồ sơ đã kiểm định",
        "facts_reported": [],
        "evidence_ids": case.get("evidence_ids", []),
        "missing": [],
        "next_action": "closed",
        "note": synthesis_note,
    })

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
