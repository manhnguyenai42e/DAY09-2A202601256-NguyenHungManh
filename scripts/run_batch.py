"""Runs all 50 real input/EC_*.json tickets through the coordinator, writes
output/EC_*.json, appends every agent handoff to logging/trace.jsonl (fresh
run, not appended across runs), and writes logging/metadata.json.

Requires `scripts/run_agents.py` to already be running (MCP server + all 7
A2A agent services)."""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agents.coordinator import run_case
from src.config import (
    COHORT,
    INPUT_DIR,
    LLM_PROVIDER,
    METADATA_PATH,
    OLLAMA_MODEL,
    OLLAMA_MODEL_PARAMS,
    OLLAMA_MODEL_QUANTIZATION,
    OLLAMA_MODEL_SOURCE,
    OPENAI_MODEL,
    OPENAI_MODEL_PARAMS,
    OUTPUT_DIR,
    POLICY_VERSION,
    STARTER_REPO,
    TRACE_PATH,
)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parallel", type=int, default=6, help="concurrent cases (1 = sequential)")
    parser.add_argument("--fast", action="store_true",
                        help="skip LLM narration (trace note only; scored JSON is unaffected) for quick iterations")
    args = parser.parse_args()
    if args.fast:
        os.environ["EC_SKIP_NARRATION"] = "1"

    tickets = sorted(INPUT_DIR.glob("EC_*.json"))
    if len(tickets) != 50:
        print(f"WARNING: expected 50 input tickets, found {len(tickets)}")

    OUTPUT_DIR.mkdir(exist_ok=True)
    trace_by_case: dict[str, list[dict]] = {}
    failures: list[str] = []
    sem = asyncio.Semaphore(max(1, args.parallel))
    done_count = 0

    t_start = time.time()

    async def process(path: Path) -> None:
        nonlocal done_count
        ticket = json.loads(path.read_text(encoding="utf-8"))
        case_id = ticket["case_id"]
        t0 = time.time()
        async with sem:
            try:
                case, trace = await run_case(ticket)
            except Exception as exc:
                print(f"{case_id} FAILED: {exc}")
                failures.append(case_id)
                return
        trace_by_case[case_id] = trace
        out_path = OUTPUT_DIR / f"{case_id}.json"
        out_path.write_text(json.dumps(case, indent=2, ensure_ascii=False), encoding="utf-8")
        done_count += 1
        print(f"[{done_count}/{len(tickets)}] {case_id} -> {case['case_assessment']['primary_issue']} "
              f"({time.time() - t0:.1f}s)")

    await asyncio.gather(*(process(p) for p in tickets))
    all_trace = [ev for cid in sorted(trace_by_case) for ev in trace_by_case[cid]]

    with TRACE_PATH.open("w", encoding="utf-8") as f:
        for event in all_trace:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    metadata = {
        "cohort": COHORT,
        "starter_repo": STARTER_REPO,
        "policy_version": POLICY_VERSION,
        "model": (
            {
                "name": OPENAI_MODEL,
                "params": OPENAI_MODEL_PARAMS,
                "runtime": "OpenAI API (hosted)",
                "compliance_note": (
                    "Đề yêu cầu model <=10B tham số. OpenAI không công bố số tham số của "
                    "gpt-4o-mini nên ràng buộc này không chứng minh được. Cấu hình thay thế "
                    "chạy local (qwen3.5-4b-ec, 4B, chứng minh được) có sẵn: đặt "
                    "EC_LLM_PROVIDER=ollama."
                ),
            }
            if LLM_PROVIDER == "openai"
            else {
                "name": OLLAMA_MODEL,
                "params": OLLAMA_MODEL_PARAMS,
                "quantization": OLLAMA_MODEL_QUANTIZATION,
                "source": OLLAMA_MODEL_SOURCE,
                "runtime": "Ollama (local, http://localhost:11434)",
            }
        ),
        "llm_usage": (
            "Cả 7 agent đều dùng LLM. 6 agent nghiệp vụ chạy vòng lặp tool-calling thật: model "
            "nhận schema các MCP tool được phép dùng, tự quyết định gọi tool nào với tham số gì; "
            "hệ thống thực thi lời gọi đó lên MCP server và đưa kết quả thật về cho model. "
            "Coordinator gọi LLM 2 lần (triage lúc nhận ticket, synthesis lúc đóng hồ sơ). "
            "Mọi giá trị trong file output là output nguyên vẹn của MCP tool, không phải lời "
            "model thuật lại — số học và định dạng evidence ID luôn deterministic."
        ),
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
