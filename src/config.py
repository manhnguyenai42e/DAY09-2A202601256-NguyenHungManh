"""Central configuration: model names, ports, paths, policy version.

Model name is declared here in code (not in .env) per submission rules.
"""

from pathlib import Path

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

# --- Local LLM (Ollama) ---
# Imported from an existing LM Studio GGUF via `ollama create` (see scripts/setup_ollama_model.ps1).
# 4B parameters, well under the 10B/agent limit; quantized Q4_K_M fits the 6GB VRAM laptop GPU.
OLLAMA_HOST = "http://localhost:11434"
OLLAMA_MODEL = "qwen3.5-4b-ec"
OLLAMA_MODEL_PARAMS = "4B"
OLLAMA_MODEL_QUANTIZATION = "Q4_K_M"
OLLAMA_MODEL_SOURCE = "Qwen3.5-4B-GGUF (lmstudio-community), imported into Ollama from local GGUF"
OLLAMA_TEMPERATURE = 0.1

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
