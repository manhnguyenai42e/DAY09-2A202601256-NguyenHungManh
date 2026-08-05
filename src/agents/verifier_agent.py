"""Verifier Agent: the final gate before a case is written to output/.

Two independent layers:

- **Deterministic check (MCP `validate_case_output`)** — schema, array limits
  and evidence/entity grounding against the source CSVs. It never fills in or
  changes a value, so a hallucinated "looks fine to me" can never let a
  broken case through, and it never invents a correct answer either — it
  only accepts or rejects what the agents produced.
- **LLM consistency audit** — the model independently re-reads the case
  against EC_POLICY_V2 and against its own dates/numbers, and must report a
  structured consistent/inconsistent verdict (via `report_audit`, not free
  text) — catching things the schema check cannot express: a
  delivery_variance_hours sign that contradicts delivered_at vs
  estimated_delivery_at, a primary_issue that does not match its own
  evidence (e.g. late_delivery_seller with no late seller), a refund that
  does not match the issue type.

Both layers can only ever push the verdict toward FAIL, never toward PASS:
`valid = schema_valid AND audit_consistent`. The audit can catch mistakes the
schema check misses, but it can never wave through something the schema
check rejected — a single hallucinated "looks fine" from the audit layer can
never let a broken case slip out. Neither layer computes or overrides any
business value itself — that stays the agents' job; this layer only
accepts or rejects what they produced.
"""

from __future__ import annotations

import json

from src.a2a_common.protocol import AgentCard, HandoffPayload
from src.agents.base import build_agent_app, call_tool, llm_chat, mcp_session
from src.config import agent_url

AUDIT_PROMPT = (
    "Bạn là agent kiểm định (verifier) cuối cùng của hệ thống xử lý khiếu nại thương mại điện "
    "tử, áp dụng chính sách EC_POLICY_V2. Dưới đây là một case đã được xử lý xong (JSON). Hãy "
    "tự kiểm tra kỹ, không tin tưởng mù quáng vào số liệu đã có, và gọi report_audit với kết "
    "quả.\n\n"
    "Kiểm tra bắt buộc:\n"
    "1. DẤU delivery_variance_hours: so sánh delivered_at với estimated_delivery_at theo thời "
    "gian thực. Nếu delivered_at SAU estimated_delivery_at (giao trễ) thì delivery_variance_hours "
    "PHẢI dương; nếu delivered_at TRƯỚC estimated_delivery_at (giao sớm) thì PHẢI âm. Tự so "
    "sánh 2 timestamp này, đừng chỉ tin số đã cho.\n"
    "2. DẤU handoff_variance_hours của từng seller trong seller_handoff_analysis: so sánh "
    "carrier_handoff_at với shipping_limit_at theo cùng logic trên; late_handoff phải khớp "
    "(true khi handoff_variance_hours > 0).\n"
    "3. primary_issue có khớp với chính bằng chứng trong case không (vd: late_delivery_seller "
    "phải có seller trong late_handoff_seller_ids VÀ delivery_variance_hours dương; "
    "valid_split_payment phải có >= 2 payment_ids VÀ reconciled=true; unsupported_late_claim "
    "phải có delivery_variance_hours <= 0).\n"
    "4. recommended_refund_brl có đúng loại vấn đề không (đơn hủy/không khả dụng hoàn toàn bộ "
    "payment_total_brl, giao trễ hoàn freight_total_brl, còn lại hoàn 0).\n"
    "5. case_status có khớp với refund (action_required nếu refund > 0, ngược lại no_action) "
    "không.\n\n"
    "Gọi report_audit(consistent, issues, summary). consistent=false nếu VI PHẠM BẤT KỲ điều "
    "nào ở trên — nêu cụ thể từng vi phạm trong issues. Không bịa vi phạm không có thật."
)

AUDIT_TOOL = {
    "type": "function",
    "function": {
        "name": "report_audit",
        "description": "Report the independent consistency audit result for this case.",
        "parameters": {
            "type": "object",
            "properties": {
                "consistent": {"type": "boolean"},
                "issues": {"type": "array", "items": {"type": "string"}},
                "summary": {"type": "string", "description": "1-2 câu tiếng Việt tóm tắt kết luận."},
            },
            "required": ["consistent", "issues", "summary"],
        },
    },
}

CARD = AgentCard(
    name="verifier-agent",
    description="Validates schema, array limits, evidence grounding and cross-field consistency before submission.",
    url=agent_url("verifier"),
    skills=["validate_case_output"],
)


async def _run_audit(case: dict) -> tuple[bool, list[str], str]:
    """Structured LLM audit. Returns (consistent, issues, summary). On any
    failure to get a structured verdict, fails OPEN (consistent=True) — audit
    unavailability is not itself a violation, only a reported inconsistency is."""
    try:
        msg = await llm_chat(
            [
                {"role": "system", "content": AUDIT_PROMPT},
                {"role": "user", "content": json.dumps(case, ensure_ascii=False)},
            ],
            tools=[AUDIT_TOOL],
        )
    except Exception as exc:
        return True, [], f"[audit unavailable: {exc}]"

    calls = msg.get("tool_calls") or []
    if not calls:
        return True, [], (msg.get("content") or "[audit: model did not call report_audit]").strip()

    fn = calls[0].get("function", {})
    args = fn.get("arguments", {})
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    if not isinstance(args, dict):
        args = {}
    return (
        bool(args.get("consistent", True)),
        [str(i) for i in (args.get("issues") or [])],
        str(args.get("summary", "")),
    )


async def handle(payload: HandoffPayload) -> HandoffPayload:
    case = dict(payload.facts["case"])
    case["case_id"] = payload.ticket_id

    async with mcp_session() as session:
        result = await call_tool(session, "validate_case_output", {"case_json": case})

    # Layer 1: deterministic gate — schema, limits, grounding.
    violations = result.get("violations", [])
    schema_valid = result.get("valid", False)

    # Layer 2: independent structured LLM audit — can only push toward FAIL.
    audit_consistent, audit_issues, audit_summary = await _run_audit(case)

    valid = schema_valid and audit_consistent
    all_issues = violations + audit_issues
    note = (
        f"[schema/grounding: {'PASS' if schema_valid else 'FAIL'}] "
        f"[consistency audit: {'PASS' if audit_consistent else 'FAIL'}] {audit_summary}"
    ).strip()

    return HandoffPayload(
        ticket_id=payload.ticket_id,
        from_agent="verifier",
        question=payload.question,
        facts={
            "valid": valid,
            "violations": violations,
            "audit_consistent": audit_consistent,
            "audit_issues": audit_issues,
            "verified_case": case,
        },
        evidence_ids=case.get("evidence_ids", []),
        missing=all_issues,
        next_action="submit" if valid else "return to policy agent for revision",
        note=note,
    )


app = build_agent_app(CARD, handle)
