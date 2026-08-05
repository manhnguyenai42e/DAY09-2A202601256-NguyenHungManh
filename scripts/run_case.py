"""CLI Case Runner for Multi-Agent Dispute Resolution System.

Runs a single input ticket (e.g. EC_001 or EC_005) live through the REAL
pipeline (src.agents.coordinator.run_case -> real A2A handoffs -> real MCP
tool calls -> real LLM tool-calling), printing each step from the trace the
run actually produced. Requires `scripts/run_agents.py` to already be
running (MCP server + all 7 A2A agent services), same as run_batch.py.

Usage:
  python scripts/run_case.py EC_001
  python scripts/run_case.py EC_005
  python scripts/run_case.py input/EC_012.json
"""

import asyncio
import json
import sys
import time
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.agents.coordinator import run_case


def resolve_input_path(case_input_arg: str) -> Path:
    if case_input_arg.endswith(".json") or "/" in case_input_arg or "\\" in case_input_arg:
        return Path(case_input_arg)
    cid = case_input_arg.upper()
    if not cid.startswith("EC_"):
        try:
            cid = f"EC_{int(case_input_arg):03d}"
        except ValueError:
            pass
    return ROOT_DIR / "input" / f"{cid}.json"


async def run_single_case(case_input_arg: str) -> None:
    input_path = resolve_input_path(case_input_arg)
    if not input_path.exists():
        print(f"[ERROR] Khong tim thay file ticket input tai: {input_path}")
        sys.exit(1)

    ticket = json.loads(input_path.read_text(encoding="utf-8"))
    case_id = ticket.get("case_id", "UNKNOWN")
    claimed_order_id = ticket["customer_request"]["claimed_order_id"]
    customer_message = ticket["customer_request"].get("message", "")

    print("=" * 80)
    print(f"CHAY DIEU TRA MULTI-AGENT (PIPELINE THAT) CHO CASE: {case_id}")
    print(f"Claimed Order ID: {claimed_order_id}")
    print(f"Yeu cau KH: '{customer_message}'")
    print("=" * 80)

    start_time = time.time()
    case, trace = await run_case(ticket)
    elapsed = time.time() - start_time

    print(f"\nTRACE THAT ({len(trace)} buoc, tu logging that trong lan chay nay):")
    for i, step in enumerate(trace, start=1):
        print(f"\n[{i}/{len(trace)}] agent={step.get('agent')}")
        print(f"   question: {step.get('question')}")
        if step.get("facts_reported"):
            print(f"   facts_reported: {step['facts_reported']}")
        if step.get("evidence_ids"):
            print(f"   evidence_ids: {step['evidence_ids']}")
        if step.get("missing"):
            print(f"   missing: {step['missing']}")
        if step.get("note"):
            print(f"   note: {step['note']}")

    print("\n" + "=" * 80)
    print(f"HOAN THANH TRONG {elapsed:.1f} GIAY")
    print("=" * 80)
    print("\nOUTPUT JSON CUOI CUNG:")
    print(json.dumps(case, indent=2, ensure_ascii=False))


def main() -> None:
    if len(sys.argv) < 2:
        print("CACH SU DUNG:")
        print("  1. Chay case 1:    python scripts/run_case.py EC_001")
        print("  2. Chay case 5:    python scripts/run_case.py EC_005")
        print("  3. Chay theo file: python scripts/run_case.py input/EC_010.json")
        print("\nYeu cau MCP server + 7 agent service dang chay (scripts/run_agents.py).")
        sys.exit(0)

    asyncio.run(run_single_case(sys.argv[1].strip()))


if __name__ == "__main__":
    main()
