"""Central configuration: model names, ports, paths, policy version.

Model name is declared here in code (not in .env) per submission rules.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # API keys only; model names are declared in this file, per submission rules.

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
INPUT_DIR = ROOT_DIR / "input"
OUTPUT_DIR = ROOT_DIR / "output"
LOGGING_DIR = ROOT_DIR / "logging"
TRACE_PATH = LOGGING_DIR / "trace.jsonl"
METADATA_PATH = LOGGING_DIR / "metadata.json"

POLICY_VERSION = "EC_POLICY_V2"
COHORT = "K4"
STARTER_REPO = "K4-Day9-Multi-Agent-A2A"

# --- LLM provider ---
# Switch with EC_LLM_PROVIDER=ollama|openai (default below). Model NAMES live here
# in code, per submission rules; only API keys come from .env.
LLM_PROVIDER = os.environ.get("EC_LLM_PROVIDER", "openai").lower()
LLM_TEMPERATURE = 0.1

# Option A — local (Ollama). Imported from an existing LM Studio GGUF via
# `ollama create` (scripts/setup_ollama_model.ps1). 4B parameters, provably
# under the 10B/agent limit; Q4_K_M fits the 6GB VRAM laptop GPU.
OLLAMA_HOST = "http://localhost:11434"
OLLAMA_MODEL = "qwen3.5-4b-ec"
OLLAMA_MODEL_PARAMS = "4B"
OLLAMA_MODEL_QUANTIZATION = "Q4_K_M"
OLLAMA_MODEL_SOURCE = "Qwen3.5-4B-GGUF (lmstudio-community), imported into Ollama from local GGUF"
OLLAMA_TEMPERATURE = LLM_TEMPERATURE

# Option B — hosted (OpenAI). Faster and far more reliable at tool calling than a
# 4B local model. NOTE: OpenAI does not publish GPT-4o-mini's parameter count, so
# the "<=10B parameters" rule cannot be *proven* for this option — it is declared
# as undisclosed in metadata.json. Switch to the Ollama option above if that
# constraint must be demonstrable.
OPENAI_MODEL = "gpt-4o-mini"
OPENAI_MODEL_PARAMS = "undisclosed by provider (widely estimated ~8B)"
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")


def active_model_name() -> str:
    return OPENAI_MODEL if LLM_PROVIDER == "openai" else OLLAMA_MODEL

# --- MCP data server ---
MCP_SERVER_HOST = "127.0.0.1"
MCP_SERVER_PORT = 8765
MCP_SERVER_URL = f"http://{MCP_SERVER_HOST}:{MCP_SERVER_PORT}/mcp"

# --- A2A agent services (own port + agent card each) ---
AGENT_PORTS = {
    "coordinator": 9100,
    "customer": 9101,
    "order_product": 9102,
    "payment": 9103,
    "delivery": 9104,
    "policy": 9105,
    "verifier": 9106,
}


def agent_url(name: str) -> str:
    return f"http://127.0.0.1:{AGENT_PORTS[name]}"


# --- Output schema limits (README section 6) ---
LIMITS = {
    "order_ids": 5,
    "item_ids": 5,
    "seller_ids": 3,
    "payment_ids": 5,
    "related_order_ids": 5,
    "product_ids": 5,
    "category_names": 5,
    "ranked_causes": 3,
    "responsible_parties": 3,
    "evidence_ids": 20,
    "resolution_actions": 5,
}
