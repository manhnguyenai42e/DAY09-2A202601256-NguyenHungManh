"""Verifier Agent: the final gate before a case is written to output/.

Two independent layers, deliberately asymmetric:

- **Deterministic check (MCP `validate_case_output`)** — schema, array limits
  and evidence/entity grounding against the source CSVs. This layer alone
  decides pass/fail. It cannot be overridden by the LLM, so a hallucinated
  "looks fine to me" can never let a broken case through.
- **LLM audit review** — the model independently re-reads the case against the
  EC_POLICY_V2 rules and writes its own review, raising semantic concerns the
  rule checker cannot express (e.g. a refund that does not match the issue
  type). Its concerns are recorded in the handoff and the trace; they add
  findings but never subtract them.

This is the standard LLM-as-judge + deterministic-guardrail split: the code
provides precision (never lets a bad case through), the model provides recall
(catches things the rules do not encode).
"""

from __future__ import annotations

import json

from src.a2a_common.protocol import AgentCard, HandoffPayload
from src.agents.base import build_agent_app, call_tool, mcp_session, ollama_generate
from src.config import agent_url

AUDIT_PROMPT = (
    "Bạn là agent kiểm định (verifier) cuối cùng của hệ thống xử lý khiếu nại thương mại "
    "điện tử, áp dụng chính sách EC_POLICY_V2. Dưới đây là một case đã được xử lý xong. "
    "Hãy soát lại tính nhất quán nghiệp vụ: primary_issue có khớp với bằng chứng giao vận "
    "và thanh toán không; số tiền hoàn có đúng loại vấn đề không (đơn hủy/không khả dụng "
    "hoàn toàn bộ payment, giao trễ hoàn phí ship, còn lại hoàn 0); case_status có khớp với "
    "số tiền hoàn không; resolution_actions có hợp lý không. "
    "Trả lời tối đa 2 câu tiếng Việt. Nếu mọi thứ nhất quán, nói rõ là nhất quán. "
    "Nếu thấy điểm đáng ngờ, nêu cụ thể. Không bịa thêm dữ liệu."
)

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

    # Layer 1: deterministic gate — this alone decides pass/fail.
    violations = result.get("violations", [])
    valid = result.get("valid", False)

    # Layer 2: independent LLM audit — adds findings, never removes them.
    if payload.facts.get("skip_narration"):
        audit = ""
    else:
        try:
            audit = await ollama_generate(AUDIT_PROMPT, json.dumps(case, ensure_ascii=False))
        except Exception as exc:
            audit = f"[audit unavailable: {exc}]"

    note = f"[schema/grounding: {'PASS' if valid else 'FAIL'}] {audit}".strip()

    return HandoffPayload(
        ticket_id=payload.ticket_id,
        from_agent="verifier",
        question=payload.question,
        facts={
            "valid": valid,
            "violations": violations,
            "llm_audit": audit,
        },
        evidence_ids=case.get("evidence_ids", []),
        missing=violations,
        next_action="submit" if valid else "return to policy agent for revision",
        note=note,
    )


app = build_agent_app(CARD, handle)
