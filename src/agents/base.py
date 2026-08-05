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
from src.config import (
    LLM_PROVIDER,
    LLM_TEMPERATURE,
    MCP_SERVER_URL,
    OLLAMA_HOST,
    OLLAMA_MODEL,
    OPENAI_API_KEY,
    OPENAI_MODEL,
)


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
    """One-shot completion against the configured provider (name kept for
    backwards compatibility with existing agent code)."""
    msg = await llm_chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        timeout=timeout,
    )
    return (msg.get("content") or "").strip()


async def _ollama_chat(messages: list[dict], tools: list[dict] | None, timeout: float) -> dict:
    body: dict = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {"temperature": LLM_TEMPERATURE},
    }
    if tools:
        body["tools"] = tools
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{OLLAMA_HOST}/api/chat", json=body)
        resp.raise_for_status()
        return resp.json().get("message", {})


async def _openai_chat(messages: list[dict], tools: list[dict] | None, timeout: float) -> dict:
    """OpenAI chat completion, normalised to the same shape as the Ollama reply
    so the agent loop is provider-agnostic."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=OPENAI_API_KEY, timeout=timeout)
    payload: list[dict] = []
    for m in messages:
        if m.get("role") == "tool":
            payload.append({
                "role": "tool",
                "tool_call_id": m.get("tool_call_id") or m.get("tool_name", "tool"),
                "content": m.get("content", ""),
            })
        elif m.get("role") == "assistant" and m.get("tool_calls"):
            payload.append({
                "role": "assistant",
                "content": m.get("content") or None,
                "tool_calls": [
                    {
                        "id": tc.get("id") or f"call_{i}",
                        "type": "function",
                        "function": {
                            "name": tc["function"]["name"],
                            "arguments": tc["function"]["arguments"]
                            if isinstance(tc["function"]["arguments"], str)
                            else json.dumps(tc["function"]["arguments"]),
                        },
                    }
                    for i, tc in enumerate(m["tool_calls"])
                ],
            })
        else:
            payload.append({"role": m["role"], "content": m.get("content", "")})

    kwargs: dict = {"model": OPENAI_MODEL, "messages": payload, "temperature": LLM_TEMPERATURE}
    if tools:
        kwargs["tools"] = tools
    resp = await client.chat.completions.create(**kwargs)
    choice = resp.choices[0].message

    out: dict = {"role": "assistant", "content": choice.content or ""}
    if choice.tool_calls:
        out["tool_calls"] = [
            {
                "id": tc.id,
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in choice.tool_calls
        ]
    return out


async def llm_chat(messages: list[dict], tools: list[dict] | None = None,
                   timeout: float = 180.0) -> dict:
    """One chat turn against the configured provider (see EC_LLM_PROVIDER in
    src/config.py). Returns the assistant message, which may carry `tool_calls`."""
    if LLM_PROVIDER == "openai":
        return await _openai_chat(messages, tools, timeout)
    return await _ollama_chat(messages, tools, timeout)


# Backwards-compatible alias used by earlier code paths.
ollama_chat = llm_chat


async def mcp_tools_as_ollama_schema(session: ClientSession, allowed: list[str]) -> list[dict]:
    """Expose the agent's permitted MCP tools to the model in function-calling form.
    An agent can only ever see the tools its role is allowed to use."""
    listed = await session.list_tools()
    schema = []
    for tool in listed.tools:
        if tool.name not in allowed:
            continue
        # SDK naming differs across versions (input_schema vs inputSchema).
        params = getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", None) or {}
        schema.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": params,
            },
        })
    return schema


async def agent_tool_loop(
    system: str,
    user: str,
    allowed_tools: list[str],
    session: ClientSession,
    max_rounds: int = 4,
) -> tuple[str, dict, list[str]]:
    """The real agent loop: the model is given its tools and decides which to
    call and with what arguments. We execute the calls it asks for against the
    MCP server, feed the real results back, and let it continue until it answers.

    Returns (final_text, {tool_name: real_tool_result}, [tools the model chose]).
    The facts handed onward are the *actual tool outputs* captured here, never
    the model's retelling of them — so the model drives the investigation while
    the data stays grounded in the source CSVs.
    """
    tools = await mcp_tools_as_ollama_schema(session, allowed_tools)
    messages: list[dict] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    collected: dict = {}
    chosen: list[str] = []

    for _ in range(max_rounds):
        msg = await ollama_chat(messages, tools=tools)
        messages.append(msg)
        calls = msg.get("tool_calls") or []
        if not calls:
            return (msg.get("content") or "").strip(), collected, chosen
        for idx, call in enumerate(calls):
            fn = call.get("function", {})
            name = fn.get("name", "")
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            chosen.append(name)
            try:
                result = await call_tool(session, name, args)
            except Exception as exc:
                result = {"error": str(exc)}
            collected[name] = result
            messages.append({
                "role": "tool",
                # OpenAI matches results to calls by id; Ollama ignores it.
                "tool_call_id": call.get("id") or f"call_{idx}",
                "tool_name": name,
                "content": json.dumps(result, ensure_ascii=False),
            })

    return "", collected, chosen


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
