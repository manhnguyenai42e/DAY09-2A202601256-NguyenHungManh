"""Runs all 50 real input/EC_*.json tickets through the coordinator, writes
output/EC_*.json, appends every agent handoff to logging/trace.jsonl (fresh
run, not appended across runs), and writes logging/metadata.json.

Requires `scripts/run_agents.py` to already be running (MCP server + all 7
A2A agent services)."""

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agents.coordinator import run_case
from src.config import (
    COHORT,
    INPUT_DIR,
    METADATA_PATH,
    OLLAMA_MODEL,
    OLLAMA_MODEL_PARAMS,
    OLLAMA_MODEL_QUANTIZATION,
    OLLAMA_MODEL_SOURCE,
    OUTPUT_DIR,
    POLICY_VERSION,
    STARTER_REPO,
    TRACE_PATH,
)


async def main() -> None:
    tickets = sorted(INPUT_DIR.glob("EC_*.json"))
    if len(tickets) != 50:
        print(f"WARNING: expected 50 input tickets, found {len(tickets)}")

    OUTPUT_DIR.mkdir(exist_ok=True)
    all_trace: list[dict] = []
    failures: list[str] = []

    t_start = time.time()
    for i, path in enumerate(tickets, 1):
        ticket = json.loads(path.read_text(encoding="utf-8"))
        case_id = ticket["case_id"]
        t0 = time.time()
        try:
            case, trace = await run_case(ticket)
        except Exception as exc:
            print(f"[{i}/{len(tickets)}] {case_id} FAILED: {exc}")
            failures.append(case_id)
            continue
        all_trace.extend(trace)
        out_path = OUTPUT_DIR / f"{case_id}.json"
        out_path.write_text(json.dumps(case, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[{i}/{len(tickets)}] {case_id} -> {case['case_assessment']['primary_issue']} "
              f"({time.time() - t0:.1f}s)")

    with TRACE_PATH.open("w", encoding="utf-8") as f:
        for event in all_trace:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    metadata = {
        "cohort": COHORT,
        "starter_repo": STARTER_REPO,
        "policy_version": POLICY_VERSION,
        "model": {
            "name": OLLAMA_MODEL,
            "params": OLLAMA_MODEL_PARAMS,
            "quantization": OLLAMA_MODEL_QUANTIZATION,
            "source": OLLAMA_MODEL_SOURCE,
            "runtime": "Ollama (local, http://localhost:11434)",
            "used_by": "policy_agent (case rationale narration only; classification/refund/evidence are deterministic)",
        },
        "framework": {
            "orchestration": "hand-rolled A2A wire layer (Agent Card + JSON-RPC message/send) over Starlette/httpx",
            "data_access": "MCP (Model Context Protocol) server, streamable-http transport, mcp Python SDK",
        },
        "runtime": {
            "os": "Windows",
            "gpu": "NVIDIA RTX 4050 Laptop, 6GB VRAM",
        },
        "cases_processed": len(tickets) - len(failures),
        "cases_failed": failures,
        "total_runtime_seconds": round(time.time() - t_start, 1),
    }
    METADATA_PATH.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nDone. {len(tickets) - len(failures)}/{len(tickets)} cases written to {OUTPUT_DIR}")
    if failures:
        print(f"FAILED case_ids: {failures}")


if __name__ == "__main__":
    asyncio.run(main())
