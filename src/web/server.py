"""Python HTTP Web Server for Multi-Agent E-commerce Dispute Resolution Dashboard.

Provides API endpoints for listing sample cases and running investigations,
while serving static web assets (HTML/CSS/JS).
"""

from __future__ import annotations

import json
import os
import sys
from http import HTTPStatus
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any

# Add workspace root to sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import asyncio

from src.agents.coordinator import run_case
from src.config import AGENT_PORTS, INPUT_DIR

# Real MCP tools each agent may call (must match ALLOWED_TOOLS + FINAL_TOOL in
# the agent implementations under src/agents/*.py — no invented tool names).
# The model chooses which of these to actually call at runtime; this list is
# the permitted set, not a fixed sequence.
AGENT_MCP_TOOLS = {
    "customer": ["get_customer", "get_related_orders", "report_customer"],
    "order_product": ["get_order_items", "get_products", "report_order_product"],
    "payment": ["get_order_items", "get_order_payments", "report_payment"],
    "delivery": ["get_order", "get_order_items", "report_delivery"],
    "policy": ["get_policy_rulebook", "get_order", "report_case"],
    "policy_retry": ["get_policy_rulebook", "get_order", "report_case"],
    "verifier": ["validate_case_output"],
    "verifier_retry": ["validate_case_output"],
    "coordinator": [],
    "coordinator_intake": [],
    "coordinator_synthesis": [],
}

AGENT_DISPLAY = {
    "coordinator": "Coordinator Agent",
    "coordinator_intake": "Coordinator Agent (triage)",
    "coordinator_synthesis": "Coordinator Agent (synthesis)",
    "customer": "Customer Agent",
    "order_product": "Order & Product Agent",
    "payment": "Payment Agent",
    "delivery": "Delivery Agent",
    "policy": "Policy Agent",
    "policy_retry": "Policy Agent (retry)",
    "verifier": "Verifier Agent",
    "verifier_retry": "Verifier Agent (retry)",
}

STATIC_DIR = Path(__file__).resolve().parent / "static"


class DashboardHandler(SimpleHTTPRequestHandler):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def do_GET(self):
        if self.path == "/api/sample_cases":
            self.handle_get_sample_cases()
        elif self.path.startswith("/api/case/"):
            case_id = self.path.split("/")[-1]
            self.handle_get_case_detail(case_id)
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == "/api/investigate":
            self.handle_post_investigate()
        else:
            self.send_error(HTTPStatus.NOT_FOUND, "Endpoint not found")

    def handle_get_sample_cases(self):
        cases = []
        if INPUT_DIR.exists():
            for p in sorted(INPUT_DIR.glob("EC_*.json")):
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    cases.append({
                        "case_id": data.get("case_id", p.stem),
                        "claimed_order_id": data.get("customer_request", {}).get("claimed_order_id", ""),
                        "message": data.get("customer_request", {}).get("message", ""),
                    })
                except Exception:
                    cases.append({"case_id": p.stem, "claimed_order_id": "", "message": ""})
        
        self.send_json_response({"cases": cases})

    def handle_get_case_detail(self, case_id: str):
        file_path = INPUT_DIR / f"{case_id}.json"
        if not file_path.exists():
            self.send_json_response({"error": "Case file not found"}, status=HTTPStatus.NOT_FOUND)
            return
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = json.load(f)
            self.send_json_response({"case_id": case_id, "input_json": content})
        except Exception as e:
            self.send_json_response({"error": str(e)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_post_investigate(self):
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)
        
        try:
            payload = json.loads(post_data.decode("utf-8"))
        except Exception as e:
            self.send_json_response({"error": f"Invalid JSON payload: {e}"}, status=HTTPStatus.BAD_REQUEST)
            return

        claimed_order_id = payload.get("claimed_order_id")
        case_id = payload.get("case_id", "CUSTOM_CASE")

        # If payload is full input format
        if not claimed_order_id and "customer_request" in payload:
            claimed_order_id = payload["customer_request"].get("claimed_order_id")
            case_id = payload.get("case_id", case_id)

        if not claimed_order_id:
            self.send_json_response(
                {"error": "Missing claimed_order_id in request input"},
                status=HTTPStatus.BAD_REQUEST
            )
            return

        try:
            # REAL run: dispatch the ticket through the live A2A coordinator ->
            # 4 evidence agents (parallel, each grounded via MCP) -> policy
            # (MCP + local LLM narration) -> verifier (MCP validation).
            # Requires scripts/run_agents.py to be running. Trace timestamps
            # below are the actual wall-clock ISO timestamps of each handoff.
            ticket = {
                "case_id": case_id,
                "customer_request": {"claimed_order_id": claimed_order_id},
            }
            case_output, trace = asyncio.run(run_case(ticket))

            trace_steps = [
                {
                    "step": 0,
                    "agent": "Coordinator Agent",
                    "agent_key": "coordinator",
                    "port": AGENT_PORTS["coordinator"],
                    "type": "A2A_DISPATCH",
                    "status": "DISPATCHED",
                    "action": f"Received ticket {case_id} for order {claimed_order_id}; "
                              f"A2A parallel dispatch to customer/order_product/payment/delivery.",
                    "mcp_tool": None,
                    "mcp_params": None,
                    "a2a_handoff": {"ticket_id": case_id, "claimed_order_id": claimed_order_id},
                    "timestamp": (trace[0]["timestamp"] if trace else ""),
                }
            ]
            for i, ev in enumerate(trace, start=1):
                agent = ev.get("agent", "")
                agent_key = agent.replace("_retry", "")
                tools = AGENT_MCP_TOOLS.get(agent, [])
                status = "COMPLETED"
                if agent.startswith("verifier"):
                    status = "VERIFIED" if not ev.get("missing") else "VIOLATIONS"
                elif ev.get("missing"):
                    status = "PARTIAL_DATA"
                trace_steps.append({
                    "step": i,
                    "agent": AGENT_DISPLAY.get(agent, agent),
                    "agent_key": agent_key,
                    "port": AGENT_PORTS.get(agent_key, None),
                    "type": "A2A_HANDOFF",
                    "status": status,
                    "action": f"facts: {', '.join(ev.get('facts_reported', []))}" if ev.get("facts_reported") else "",
                    "evidence_ids": ev.get("evidence_ids", []),
                    "missing": ev.get("missing", []),
                    "note": ev.get("note", ""),
                    "mcp_tool": ", ".join(tools) if tools else None,
                    "mcp_params": {"order_id": claimed_order_id},
                    "a2a_handoff": {
                        "question": ev.get("question", ""),
                        "next_action": ev.get("next_action", ""),
                    },
                    "timestamp": ev.get("timestamp", ""),
                })

            self.send_json_response({
                "success": True,
                "case_id": case_id,
                "claimed_order_id": claimed_order_id,
                "case_output": case_output,
                "trace_steps": trace_steps
            })

        except Exception as e:
            self.send_json_response(
                {"error": f"Failed during case investigation: {str(e)}"},
                status=HTTPStatus.INTERNAL_SERVER_ERROR
            )

    def send_json_response(self, data: dict[str, Any], status: int = HTTPStatus.OK):
        response_bytes = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response_bytes)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(response_bytes)

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.OK)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def run_server(port: int = 8000):
    server_address = ("", port)
    httpd = HTTPServer(server_address, DashboardHandler)
    print(f"Multi-Agent Testing Dashboard running at http://localhost:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard server stopped.")
        httpd.server_close()


if __name__ == "__main__":
    port_arg = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    run_server(port_arg)
