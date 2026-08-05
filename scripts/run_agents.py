"""Boots the MCP data server + all 7 A2A agent services concurrently, each on
its own port (see src/config.py), inside a single Python process (simpler
process management on Windows than 8 separate OS processes, while each is
still a real, independently-addressable HTTP service with its own agent
card and endpoint)."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn

from src.agents import (
    coordinator,
    customer_agent,
    delivery_agent,
    order_product_agent,
    payment_agent,
    policy_agent,
    verifier_agent,
)
from src.config import AGENT_PORTS, MCP_SERVER_HOST, MCP_SERVER_PORT
from src.mcp_server.server import server as mcp_server

AGENT_APPS = {
    "coordinator": coordinator.app,
    "customer": customer_agent.app,
    "order_product": order_product_agent.app,
    "payment": payment_agent.app,
    "delivery": delivery_agent.app,
    "policy": policy_agent.app,
    "verifier": verifier_agent.app,
}


async def _serve(app, host: str, port: int, name: str) -> None:
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    print(f"[run_agents] starting {name} on http://{host}:{port}")
    await server.serve()


async def main() -> None:
    tasks = [
        asyncio.create_task(
            mcp_server.run_streamable_http_async(host=MCP_SERVER_HOST, port=MCP_SERVER_PORT)
        )
    ]
    for name, app in AGENT_APPS.items():
        tasks.append(asyncio.create_task(_serve(app, "127.0.0.1", AGENT_PORTS[name], name)))
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
