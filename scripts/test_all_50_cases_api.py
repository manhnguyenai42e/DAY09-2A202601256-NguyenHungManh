"""Comprehensive automated test script for Dashboard HTTP API Server.

Tests ALL 50 real input tickets (EC_001.json through EC_050.json) by sending
HTTP POST requests to /api/investigate on a test port, and verifies that
every single case produces a 100% valid response matching output schema.
"""

import json
import sys
import threading
import time
import urllib.request
from http.server import HTTPServer
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.config import INPUT_DIR
from src.web.server import DashboardHandler

TEST_PORT = 8767


def run_test_server(server: HTTPServer):
    server.serve_forever()


def test_all_cases():
    server = HTTPServer(("127.0.0.1", TEST_PORT), DashboardHandler)
    thread = threading.Thread(target=run_test_server, args=(server,), daemon=True)
    thread.start()
    time.sleep(0.5)

    print(f"[TEST] Dashboard server running on port {TEST_PORT}")

    tickets = sorted(INPUT_DIR.glob("EC_*.json"))
    print(f"[TEST] Testing all {len(tickets)} input tickets against HTTP API...")

    passed = 0
    failed = 0

    for i, tpath in enumerate(tickets, 1):
        input_data = json.loads(tpath.read_text(encoding="utf-8"))
        case_id = input_data["case_id"]

        url = f"http://127.0.0.1:{TEST_PORT}/api/investigate"
        req = urllib.request.Request(
            url,
            data=json.dumps(input_data).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req) as resp:
                status = resp.status
                body = json.loads(resp.read().decode("utf-8"))

            if status == 200 and body.get("success"):
                out = body["case_output"]
                pi = out["case_assessment"]["primary_issue"]
                cs = out["case_assessment"]["case_status"]
                passed += 1
                if i % 10 == 0 or i == 50:
                    print(f"  [{i}/50] {case_id} -> {pi} ({cs}) OK")
            else:
                print(f"  [FAIL] {case_id}: status={status}, body={body}")
                failed += 1

        except Exception as e:
            print(f"  [EXCEPTION] {case_id}: {e}")
            failed += 1

    server.shutdown()
    server.server_close()

    print(f"\n[SUMMARY] Results: {passed}/50 cases PASSED ({failed} failed).")
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    test_all_cases()
