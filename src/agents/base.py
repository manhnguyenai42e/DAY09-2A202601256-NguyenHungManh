"""Shared scaffolding for every agent: MCP client (data grounding), Ollama
client (reasoning/narration), and the tiny Starlette app that turns a handler
into a real A2A HTTP service (agent card + JSON-RPC message/send)."""

from __future__ import annotations

import contextlib
import json
from collections.abc import Callable, Awaitable

import httpx
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from src.a2a_common.protocol import (
    AgentCard,
    HandoffPayload,
    build_message_send_request,
    build_message_send_response,
    extract_payload,
)
from src.config import MCP_SERVER_URL, OLLAMA_HOST, OLLAMA_MODEL, OLLAMA_TEMPERATURE


@contextlib.asynccontextmanager
async def mcp_session():
    async with streamable_http_client(MCP_SERVER_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def call_tool(session: ClientSession, name: str, args: dict) -> dict:
    result = await session.call_tool(name, args)
    text = result.content[0].text if result.content else "{}"
    return json.loads(text)


async def ollama_generate(system: str, user: str, timeout: float = 120.0) -> str:
    """One-shot chat completion against the local Ollama model (see src/config.py)."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{OLLAMA_HOST}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "think": False,
                "options": {"temperature": OLLAMA_TEMPERATURE},
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("message", {}).get("content", "").strip()


async def agent_reflect(
    role_prompt: str, facts: dict, skip: bool = False, timeout: float = 90.0
) -> str:
    """Every domain agent's LLM step: read the grounded facts it just retrieved
    via MCP and write its own expert assessment for the handoff note.

    The LLM never changes the facts (they go into the handoff verbatim from the
    tools); it reasons about them. Returns "" when narration is skipped
    (fast-iteration mode) so callers can fall back to a plain template note.
    """
    if skip:
        return ""
    system = (
        "Bạn là một agent chuyên trách trong hệ thống điều tra khiếu nại thương mại "
        "điện tử. Vai trò của bạn: " + role_prompt + " "
        "Dưới đây là dữ kiện bạn vừa tra cứu được từ MCP tool (dữ liệu gốc, không được "
        "thay đổi hay bịa thêm). Hãy viết 1-2 câu tiếng Việt nhận định chuyên môn về "
        "dữ kiện này cho agent tiếp theo: điểm nào đáng chú ý, có bất thường không. "
        "Chỉ trả lời phần nhận định, không lặp lại dữ liệu."
    )
    try:
        return await ollama_generate(system, json.dumps(facts, ensure_ascii=False), timeout=timeout)
    except Exception as exc:
        return f"[narration unavailable: {exc}]"


async def send_handoff(url: str, payload: HandoffPayload, timeout: float = 180.0) -> HandoffPayload:
    """A2A client call: POST message/send to another agent's /a2a endpoint."""
    request_body = build_message_send_request(payload)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{url}/a2a", json=request_body)
        resp.raise_for_status()
        return HandoffPayload(**extract_payload(resp.json()))


AgentHandler = Callable[[HandoffPayload], Awaitable[HandoffPayload]]


def build_agent_app(card: AgentCard, handler: AgentHandler) -> Starlette:
    async def agent_card_endpoint(request: Request) -> JSONResponse:
        return JSONResponse(card.model_dump())

    async def a2a_endpoint(request: Request) -> JSONResponse:
        body = await request.json()
        payload = HandoffPayload(**extract_payload(body))
        result = await handler(payload)
        return JSONResponse(build_message_send_response(result, request_id=body.get("id", 1)))

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "agent": card.name})

    routes = [
        Route("/.well-known/agent-card.json", agent_card_endpoint, methods=["GET"]),
        Route("/a2a", a2a_endpoint, methods=["POST"]),
        Route("/health", health, methods=["GET"]),
    ]
    return Starlette(routes=routes)
