"""Trace Log CLI Inspector for Multi-Agent Dispute Resolution System.

Usage:
  python scripts/view_trace.py EC_001
  python scripts/view_trace.py list
  python scripts/view_trace.py EC_005 --json
"""

import json
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT_DIR = Path(__file__).resolve().parent.parent
TRACE_FILE = ROOT_DIR / "logging" / "trace.jsonl"


def load_traces():
    if not TRACE_FILE.exists():
        print(f"[ERROR] File log trace không tồn tại tại: {TRACE_FILE}")
        sys.exit(1)

    traces_by_case = {}
    with open(TRACE_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            item = json.loads(line.strip())
            cid = item.get("case_id", "UNKNOWN")
            if cid not in traces_by_case:
                traces_by_case[cid] = []
            traces_by_case[cid].append(item)
    return traces_by_case


def list_cases(traces_by_case):
    print("=" * 75)
    print(f"📋 DANH SÁCH {len(traces_by_case)} CASES ĐÃ LƯU TRONG TRACE LOGS:")
    print("=" * 75)
    for cid in sorted(traces_by_case.keys()):
        steps = traces_by_case[cid]
        agents_called = [s.get("agent", "") for s in steps]
        print(f"  • {cid:<8} | Số bước: {len(steps)} | Agents: {', '.join(agents_called)}")
    print("-" * 75)
    print("💡 Hướng dẫn: Chạy 'python scripts/view_trace.py EC_001' để xem log chi tiết.")


def view_case_trace(cid, steps, raw_json=False):
    if raw_json:
        print(json.dumps(steps, indent=2, ensure_ascii=False))
        return

    print("\n" + "=" * 80)
    print(f"🔍 NHẬT KÝ CHI TIẾT CÁC AGENT ĐIỀU TRA CASE: {cid}")
    print("=" * 80)

    agent_names = {
        "coordinator_intake": "Coordinator Agent (:9100)",
        "customer": "Customer Agent (:9101)",
        "order_product": "Order & Product Agent (:9102)",
        "payment": "Payment Agent (:9103)",
        "delivery": "Delivery Agent (:9104)",
        "policy": "Policy Agent (:9105)",
        "verifier": "Verifier Agent (:9106)",
    }

    for idx, step in enumerate(steps, 1):
        raw_agent = step.get("agent", "")
        agent_display = agent_names.get(raw_agent, raw_agent.upper())
        timestamp = step.get("timestamp", "").split("T")[-1] if "T" in step.get("timestamp", "") else step.get("timestamp", "")
        next_act = step.get("next_action", "N/A")
        facts = step.get("facts_reported", [])
        evidence = step.get("evidence_ids", [])
        note = step.get("note", "").strip()

        print(f"\n📌 [BƯỚC {idx}/7] AGENT: {agent_display}")
        print(f"   ⏱️ Thời gian: {timestamp}")
        print(f"   📊 Báo cáo facts: {', '.join(facts) if facts else 'None'}")
        if evidence:
            print(f"   🧾 Evidence IDs: {', '.join(evidence)}")
        print(f"   ➡️ Hành động tiếp theo: {next_act}")
        print(f"   📝 Ghi chú phân tích / Kết quả trả lời:")
        print(f"      {note.replace('\n', '\n      ')}")
        print("   " + "-" * 74)

    print("\n✅ Hoàn tất hiển thị nhật ký điều phối A2A cho case " + cid)
    print("=" * 80 + "\n")


def main():
    traces_by_case = load_traces()

    if len(sys.argv) < 2:
        print("💡 CÁCH SỬ DỤNG:")
        print("  1. Xem danh sách tất cả các case:  python scripts/view_trace.py list")
        print("  2. Xem nhật ký Agent của 1 case:   python scripts/view_trace.py EC_001")
        print("  3. Xuất dạng JSON thô:             python scripts/view_trace.py EC_001 --json")
        sys.exit(0)

    arg = sys.argv[1].strip()

    if arg.lower() == "list":
        list_cases(traces_by_case)
        return

    case_id = arg.upper()
    if case_id not in traces_by_case:
        if not case_id.startswith("EC_"):
            try:
                case_id = f"EC_{int(arg):03d}"
            except ValueError:
                pass

    if case_id not in traces_by_case:
        print(f"❌ Không tìm thấy log trace cho case '{arg}'.")
        list_cases(traces_by_case)
        sys.exit(1)

    raw_json = "--json" in sys.argv
    view_case_trace(case_id, traces_by_case[case_id], raw_json)


if __name__ == "__main__":
    main()
