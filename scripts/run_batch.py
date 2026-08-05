"""Runs all 50 real input/EC_*.json tickets through the coordinator, writes
output/EC_*.json, appends every agent handoff to logging/trace.jsonl (fresh
run, not appended across runs), and writes logging/metadata.json.

Requires `scripts/run_agents.py` to already be running (MCP server + all 7
A2A agent services)."""

import argparse
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
    LLM_PROVIDER,
    METADATA_PATH,
    OLLAMA_MODEL,
    OLLAMA_MODEL_PARAMS,
    OLLAMA_MODEL_QUANTIZATION,
    OLLAMA_MODEL_SOURCE,
    OPENAI_MODEL,
    OPENAI_MODEL_PARAMS,
    OPENROUTER_MODEL,
    OPENROUTER_MODEL_PARAMS,
    OUTPUT_DIR,
    POLICY_VERSION,
    STARTER_REPO,
    TRACE_PATH,
)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parallel", type=int, default=6, help="concurrent cases (1 = sequential)")
    parser.add_argument("--start", type=int, default=0, help="slice: first ticket index (sorted, 0-based)")
    parser.add_argument("--end", type=int, default=None, help="slice: ticket index to stop before (exclusive)")
    parser.add_argument("--cases", type=str, default=None, help="comma-separated case_ids to run instead of a slice, e.g. EC_001,EC_004")
    parser.add_argument("--trace-out", type=Path, default=None, help="override trace.jsonl path (for split multi-lane runs)")
    parser.add_argument("--metadata-out", type=Path, default=None, help="override metadata.json path (for split multi-lane runs)")
    args = parser.parse_args()

    all_tickets = sorted(INPUT_DIR.glob("EC_*.json"))
    if len(all_tickets) != 50:
        print(f"WARNING: expected 50 input tickets, found {len(all_tickets)}")
    if args.cases:
        wanted = set(args.cases.split(","))
        tickets = [p for p in all_tickets if p.stem in wanted]
    else:
        tickets = all_tickets[args.start:args.end]

    trace_path = args.trace_out or TRACE_PATH
    metadata_path = args.metadata_out or METADATA_PATH

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

    with trace_path.open("w", encoding="utf-8") as f:
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
                    "Đề yêu cầu model <=10B tham số. OpenAI không công bố chính thức số tham "
                    "số của gpt-4o-mini (chỉ có ước tính ~8B từ một paper nghiên cứu của "
                    "Microsoft, không phải công bố chính thức) nên ràng buộc này không chứng "
                    "minh được chắc chắn. Cấu hình mặc định dùng OpenRouter/Qwen3-8B "
                    "(8B, có model card chính thức từ Qwen) hoặc local qwen3.5-4b-ec (4.2B)."
                ),
            }
            if LLM_PROVIDER == "openai"
            else {
                "name": OPENROUTER_MODEL,
                "params": OPENROUTER_MODEL_PARAMS,
                "runtime": "OpenRouter API (hosted, OpenAI-compatible)",
            }
            if LLM_PROVIDER == "openrouter"
            else {
                "name": OLLAMA_MODEL,
                "params": OLLAMA_MODEL_PARAMS,
                "quantization": OLLAMA_MODEL_QUANTIZATION,
                "source": OLLAMA_MODEL_SOURCE,
                "runtime": "Ollama (local, http://localhost:11434)",
            }
        ),
        "llm_usage": (
            "Cả 7 agent đều dùng LLM, không có hàm Python nào tính hộ nội dung nghiệp vụ. Các "
            "MCP tool chỉ trả dữ liệu thô lọc theo khóa từ CSV gốc (không sum, không trừ ngày "
            "giờ, không dựng evidence ID, không phân loại). 6 agent nghiệp vụ chạy vòng lặp "
            "tool-calling thật: model tự gọi tool dữ liệu thô cần thiết, rồi TỰ tính toán (cộng "
            "tiền, trừ giờ, định dạng evidence ID, chọn primary_issue theo bảng luật...) và tự "
            "nộp kết quả có cấu trúc qua một tool nội bộ (report_*) — hệ thống chỉ bắt lấy đúng "
            "arguments model đưa ra, không sửa. Coordinator gọi LLM 2 lần (triage lúc nhận "
            "ticket, synthesis lúc đóng hồ sơ) và chỉ ghép các sub-object các agent đã tự tính "
            "lại theo đúng schema, không tính toán. Lớp deterministic DUY NHẤT còn lại là "
            "Verifier's validate_case_output: kiểm schema/trần mảng/evidence tồn tại trong CSV "
            "— chỉ pass/fail, không bao giờ điền hay sửa giá trị."
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
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nDone. {len(tickets) - len(failures)}/{len(tickets)} cases written to {OUTPUT_DIR}")
    if failures:
        print(f"FAILED case_ids: {failures}")


if __name__ == "__main__":
    asyncio.run(main())
