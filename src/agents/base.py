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
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    OPENROUTER_MODEL,
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


async def _openai_compatible_chat(
    messages: list[dict], tools: list[dict] | None, timeout: float,
    *, api_key: str, model: str, base_url: str | None = None, extra_body: dict | None = None,
) -> dict:
    """Chat completion against any OpenAI-compatible endpoint (OpenAI itself,
    or OpenRouter — same request/response shape), normalised to the same
    reply shape as the Ollama reply so the agent loop is provider-agnostic."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
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

    # Cap output tokens: never long-form text, but the Policy Agent's final
    # report_case call carries several arrays (up to 20 evidence_ids) plus a
    # rationale — too low a cap truncates that JSON mid-object and the args
    # silently fail to parse. Without any cap, some providers default to the
    # model's full context window and reject the request as unaffordable.
    kwargs: dict = {"model": model, "messages": payload, "temperature": LLM_TEMPERATURE, "max_tokens": 4096}
    if tools:
        kwargs["tools"] = tools
        # Some OpenRouter backends for small models reject a response that
        # attempts >1 tool call at once; our loop only needs one at a time anyway.
        kwargs["parallel_tool_calls"] = False
    if extra_body:
        kwargs["extra_body"] = extra_body
    resp = await client.chat.completions.create(**kwargs)
    if not resp.choices:
        raise RuntimeError(f"provider returned no choices (model={model}): {resp!r}")
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
        return await _openai_compatible_chat(messages, tools, timeout, api_key=OPENAI_API_KEY, model=OPENAI_MODEL)
    if LLM_PROVIDER == "openrouter":
        return await _openai_compatible_chat(
            messages, tools, timeout,
            api_key=OPENROUTER_API_KEY, model=OPENROUTER_MODEL, base_url=OPENROUTER_BASE_URL,
        )
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


def _strict_schema(schema: dict) -> dict:
    """Recursively normalise a JSON schema for OpenAI/OpenRouter "strict"
    function calling: every object needs additionalProperties=false and its
    "required" list must name every property (some providers only treat
    "required" as a hint otherwise, and a model can submit a tool call
    missing a field it was merely asked nicely to include — this makes the
    API itself reject that instead of us silently accepting a hole in the
    case). Ollama ignores the extra keys harmlessly."""
    if not isinstance(schema, dict):
        return schema
    schema = dict(schema)
    if schema.get("type") == "object" and "properties" in schema:
        schema["properties"] = {k: _strict_schema(v) for k, v in schema["properties"].items()}
        schema["required"] = list(schema["properties"].keys())
        schema["additionalProperties"] = False
    elif schema.get("type") == "array" and "items" in schema:
        schema["items"] = _strict_schema(schema["items"])
    return schema


async def agent_tool_loop(
    system: str,
    user: str,
    allowed_tools: list[str],
    final_tool: dict,
    session: ClientSession,
    max_rounds: int = 12,
) -> tuple[dict, list[str]]:
    """The real agent loop: the model is given its permitted MCP data tools
    plus exactly one more tool, `final_tool` — its only way to report a
    result. Data tool calls are executed for real against the MCP server and
    the real results fed back. When the model calls `final_tool`, whatever
    arguments it passes become the result verbatim: this function does not
    compute, sum, round or reformat any of it — that reasoning is the model's
    job, not ours.

    Returns (final_tool_arguments, [tool names the model chose, in order]).
    Raises RuntimeError if the model exhausts max_rounds without calling
    `final_tool` — callers must let that fail the case rather than invent a
    substitute answer.
    """
    data_tools = await mcp_tools_as_ollama_schema(session, allowed_tools)
    tools = data_tools + [{
        "type": "function",
        "function": {
            "name": final_tool["name"],
            "description": final_tool.get("description", ""),
            "parameters": _strict_schema(final_tool["parameters"]),
            "strict": True,
        },
    }]
    # Universal guard rail: small models under tool-calling pressure tend to
    # fire off every tool they can think of in one burst, including guessing
    # plausible-looking ID values for a second tool call before ever seeing
    # the first tool's real result. Spelling this out explicitly here (once,
    # for every agent) measurably reduces that — the loop below still refuses
    # any final-tool call bundled with another call, regardless.
    system += (
        "\n\nQUAN TRỌNG VỀ CÁCH GỌI TOOL: mỗi lượt chỉ gọi MỘT tool duy nhất. Không bao giờ "
        "đoán trước ID hay số liệu cho tool tiếp theo trước khi thấy kết quả THẬT của tool "
        "trước đó — ví dụ không được tự bịa product_id để gọi get_products trước khi đọc "
        f"product_id thật từ tool trước. Tool nộp kết quả cuối ({final_tool['name']}) PHẢI "
        "được gọi một mình, không kèm bất kỳ tool nào khác trong cùng lượt, và chỉ sau khi đã "
        "đọc đầy đủ kết quả thật cần thiết."
    )
    messages: list[dict] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    chosen: list[str] = []

    for _ in range(max_rounds):
        msg = await ollama_chat(messages, tools=tools)
        messages.append(msg)
        calls = msg.get("tool_calls") or []
        if not calls:
            messages.append({
                "role": "user",
                "content": (
                    f"Bạn phải gọi tool '{final_tool['name']}' để nộp kết quả cuối cùng, "
                    "không trả lời bằng văn bản thường."
                ),
            })
            continue

        parsed = []
        for call in calls:
            fn = call.get("function", {})
            name = fn.get("name", "")
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            if not isinstance(args, dict):
                args = {}
            parsed.append((call, name, args))

        final_calls = [p for p in parsed if p[1] == final_tool["name"]]
        has_data_calls = len(parsed) > len(final_calls)
        # Only trust a final-tool call when it arrives completely alone. A
        # model that bundles it with any data-tool call in the same message —
        # even a call it has made before — is guessing the answer instead of
        # reading that call's real result first; accepting it here would let
        # a hallucinated shortcut straight into the graded output.
        if final_calls and not has_data_calls:
            return final_calls[0][2], chosen + [final_calls[0][1]]

        for idx, (call, name, args) in enumerate(parsed):
            chosen.append(name)
            if name == final_tool["name"]:
                result = {
                    "error": (
                        f"REJECTED: you called {final_tool['name']} together with another "
                        "tool call in the same message. You must call it ALONE, in a message "
                        "with no other tool calls, only after you have already read that "
                        "other tool's real result in a previous turn. Read the real results "
                        f"below first, then call {final_tool['name']} by itself, using the "
                        "ACTUAL values from those results — never placeholders."
                    )
                }
            else:
                try:
                    result = await call_tool(session, name, args)
                except Exception as exc:
                    result = {"error": str(exc)}
            messages.append({
                "role": "tool",
                # OpenAI matches results to calls by id; Ollama ignores it.
                "tool_call_id": call.get("id") or f"call_{idx}",
                "tool_name": name,
                "content": json.dumps(result, ensure_ascii=False),
            })

    raise RuntimeError(
        f"agent did not call final tool '{final_tool['name']}' within {max_rounds} rounds"
    )


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
