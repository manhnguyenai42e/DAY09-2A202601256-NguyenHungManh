"""Minimal, spec-shaped A2A wire layer: Agent Card discovery + JSON-RPC 2.0
`message/send`, hand-rolled with Starlette/httpx instead of the full a2a-sdk
server runtime (task stores, gRPC, push notifications) which is far more than
a synchronous, single-shot batch pipeline needs. Every agent is still a real,
independently-addressable HTTP service with its own card and endpoint.

Handoff payload (the domain content carried inside the A2A message) always
carries the lab's minimum contract: ticket id, question, facts with source
evidence IDs, what's missing, and the suggested next step.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field


class AgentCard(BaseModel):
    name: str
    description: str
    url: str
    version: str = "1.0.0"
    skills: list[str] = Field(default_factory=list)


class HandoffPayload(BaseModel):
    ticket_id: str
    from_agent: str
    question: str
    facts: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    next_action: str = ""
    note: str = ""  # LLM-authored rationale/narration, when applicable


def build_message_send_request(payload: HandoffPayload, request_id: int = 1) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": payload.model_dump_json()}],
            }
        },
    }


def build_message_send_response(payload: HandoffPayload, request_id: int = 1) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "message": {
                "role": "agent",
                "parts": [{"kind": "text", "text": payload.model_dump_json()}],
            }
        },
    }


def extract_payload(jsonrpc_message: dict[str, Any]) -> dict[str, Any]:
    """Pull the JSON handoff payload out of a message/send request or response."""
    node = jsonrpc_message.get("params") or jsonrpc_message.get("result") or {}
    message = node.get("message", {})
    parts = message.get("parts", [])
    text = parts[0]["text"] if parts else "{}"
    return json.loads(text)
