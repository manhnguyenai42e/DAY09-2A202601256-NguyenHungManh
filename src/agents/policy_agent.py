"""Policy Agent: applies EC_POLICY_V2 (deterministic, via MCP apply_policy tool)
and uses the local Ollama model for exactly one thing — narrating *why* in
plain language for trace.jsonl. The classification, refund and evidence IDs
themselves are never left to the LLM."""

from __future__ import annotations

import json

from src.a2a_common.protocol import AgentCard, HandoffPayload
from src.agents.base import agent_tool_loop, build_agent_app, call_tool, mcp_session
from src.config import agent_url

ALLOWED_TOOLS = ["apply_policy"]

SYSTEM = (
    "Bạn là Policy Agent của bộ phận xử lý khiếu nại thương mại điện tử Olist, áp dụng "
    "chính sách EC_POLICY_V2. Bạn nhận được bằng chứng do các agent chuyên trách thu thập. "
    "Bạn có công cụ áp dụng chính sách — hãy gọi công cụ đó để lấy phán quyết chính thức "
    "trên dữ liệu gốc; tuyệt đối không tự tính tiền, tự suy ra mã bằng chứng hay tự đặt "
    "kết luận. Sau khi có kết quả, hãy giải thích 2-3 câu tiếng Việt vì sao phán quyết này "
    "đúng theo bằng chứng, có trích dẫn các evidence ID trong kết quả."
)

CARD = AgentCard(
    name="policy-agent",
    description="Applies EC_POLICY_V2 to upstream facts and drafts the case rationale.",
    url=agent_url("policy"),
    skills=ALLOWED_TOOLS,
)


async def handle(payload: HandoffPayload) -> HandoffPayload:
    order_id = payload.facts["order_id"]
    skip = bool(payload.facts.get("skip_narration"))
    upstream = {k: v for k, v in payload.facts.items()
                if k not in ("order_id", "skip_narration")}

    async with mcp_session() as session:
        note, collected, chosen = ("", {}, [])
        if not skip:
            user = (
                f"Ticket cho đơn hàng order_id = {order_id}.\n"
                f"Bằng chứng các agent đã thu thập:\n{json.dumps(upstream, ensure_ascii=False)}"
            )
            note, collected, chosen = await agent_tool_loop(SYSTEM, user, ALLOWED_TOOLS, session)
        case = collected.get("apply_policy")
        if case is None:
            case = await call_tool(session, "apply_policy", {"order_id": order_id})
            chosen = chosen or ["apply_policy (deterministic fallback)"]

    return HandoffPayload(
        ticket_id=payload.ticket_id,
        from_agent="policy",
        question=payload.question,
        facts={"case": case, "tools_called_by_llm": chosen},
        evidence_ids=case["evidence_ids"],
        missing=[],
        next_action="handoff to verifier",
        note=note,
    )


app = build_agent_app(CARD, handle)
