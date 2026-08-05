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
# Switch with EC_LLM_PROVIDER=ollama|openrouter|openai (default below). Model
# NAMES live here in code, per submission rules; only API keys come from .env.
# Default is OpenRouter running Qwen3-8B: Qwen's own model card officially
# states 8B parameters (provably <=10B per README note #1), it's hosted (no
# local GPU bottleneck: ~1-2s/call vs ~10s/call for the local 4B model), and
# it tests reliably one-tool-call-at-a-time (see OPENROUTER_MODEL below for
# why that specifically ruled out Llama-3.1-8B-Instruct).
LLM_PROVIDER = os.environ.get("EC_LLM_PROVIDER", "openrouter").lower()
LLM_TEMPERATURE = 0.1

# Option A — local (Ollama). Imported from an existing LM Studio GGUF via
# `ollama create` (scripts/setup_ollama_model.ps1). 4B parameters, provably
# under the 10B/agent limit; Q4_K_M fits the 6GB VRAM laptop GPU. Slowest
# option (~10s/LLM call) since it runs on a laptop GPU instead of a
# datacenter, but needs no API key / network access.
OLLAMA_HOST = "http://localhost:11434"
OLLAMA_MODEL = "qwen3.5-4b-ec"
OLLAMA_MODEL_PARAMS = "4B"
OLLAMA_MODEL_QUANTIZATION = "Q4_K_M"
OLLAMA_MODEL_SOURCE = "Qwen3.5-4B-GGUF (lmstudio-community), imported into Ollama from local GGUF"
OLLAMA_TEMPERATURE = LLM_TEMPERATURE

# Option B — hosted via OpenRouter (default, used for the submitted output/).
# Qwen3-8B: Qwen's official model card states 8B parameters — provable,
# unlike GPT-4o-mini below. OpenRouter's API is OpenAI-compatible.
# (Llama-3.1-8B-Instruct was tried first — also officially 8B — but in
# practice it has a very stubborn habit of bundling the "submit result" tool
# call together with a data-fetch call in the same turn, before ever reading
# that data tool's real result; our tool loop correctly refuses to accept
# that (it would mean grounding the case in a guess, not real data), so the
# agent just deadlocks retrying forever. Qwen3-8B and Ministral-8B-2512 both
# tested reliably one-tool-call-at-a-time; Qwen3-8B was chosen as primary.)
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = "qwen/qwen3-8b"
OPENROUTER_MODEL_PARAMS = "8B (Qwen official model card: https://huggingface.co/Qwen/Qwen3-8B)"
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

# Option C — hosted (OpenAI). NOTE: OpenAI has never officially disclosed
# GPT-4o-mini's parameter count. A Microsoft research paper (unrelated topic)
# estimated ~8B, widely cited since, but it is a third-party estimate, not an
# official spec — the "<=10B parameters" rule cannot be *proven* for this
# option. Declared as such in metadata.json when this option is selected.
OPENAI_MODEL = "gpt-4o-mini"
OPENAI_MODEL_PARAMS = "not officially disclosed by OpenAI (third-party estimate ~8B, e.g. a Microsoft research paper — not a confirmed spec)"
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")


def active_model_name() -> str:
    if LLM_PROVIDER == "openai":
        return OPENAI_MODEL
    if LLM_PROVIDER == "openrouter":
        return OPENROUTER_MODEL
    return OLLAMA_MODEL


# --- MCP data server ---
# EC_PORT_OFFSET lets a second full stack (different EC_LLM_PROVIDER) run
# alongside the default one without port clashes — e.g. to split a batch run
# across two independent backends (OpenRouter + local Ollama) at once for
# real parallel throughput, since each backend's own capacity is the actual
# bottleneck, not client-side concurrency within one backend.
_PORT_OFFSET = int(os.environ.get("EC_PORT_OFFSET", "0"))
MCP_SERVER_HOST = "127.0.0.1"
MCP_SERVER_PORT = 8765 + _PORT_OFFSET
MCP_SERVER_URL = f"http://{MCP_SERVER_HOST}:{MCP_SERVER_PORT}/mcp"

# --- A2A agent services (own port + agent card each) ---
AGENT_PORTS = {
    "coordinator": 9100 + _PORT_OFFSET,
    "customer": 9101 + _PORT_OFFSET,
    "order_product": 9102 + _PORT_OFFSET,
    "payment": 9103 + _PORT_OFFSET,
    "delivery": 9104 + _PORT_OFFSET,
    "policy": 9105 + _PORT_OFFSET,
    "verifier": 9106 + _PORT_OFFSET,
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
