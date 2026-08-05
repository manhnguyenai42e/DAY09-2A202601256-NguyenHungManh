"""Automated test script for Dashboard HTTP API Server.

Boots DashboardHandler on port 8766, executes real HTTP POST requests against
/api/investigate for multiple cases, and validates the response payload.
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

from src.web.server import DashboardHandler

TEST_PORT = 8766


def run_test_server(server: HTTPServer):
    server.serve_forever()


def test_api():
    server = HTTPServer(("127.0.0.1", TEST_PORT), DashboardHandler)
    thread = threading.Thread(target=run_test_server, args=(server,), daemon=True)
    thread.start()
    time.sleep(0.5)

    print(f"[TEST] Dashboard server running on port {TEST_PORT}")

    test_cases = [
        {"case_id": "EC_001", "claimed_order_id": "9b75cdaf2d85857ef023980e15d01546"},
        {"case_id": "EC_002", "claimed_order_id": "eb096356d402d08a54bc2828b49e19d7"},
        {"case_id": "EC_005", "claimed_order_id": "3a20bcc2f5e13d964f43425cb4d122f8"},
    ]

    all_passed = True
    for case_input in test_cases:
        url = f"http://127.0.0.1:{TEST_PORT}/api/investigate"
        req = urllib.request.Request(
            url,
            data=json.dumps(case_input).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req) as resp:
                status = resp.status
                body = json.loads(resp.read().decode("utf-8"))

            if status != 200 or not body.get("success"):
                print(f"[FAIL] for {case_input['case_id']}: status={status}, body={body}")
                all_passed = False
            else:
                output = body["case_output"]
                pi = output["case_assessment"]["primary_issue"]
                cs = output["case_assessment"]["case_status"]
                refund = output["financial_resolution"]["recommended_refund_brl"]
                print(f"[PASS] {case_input['case_id']}: status={cs}, issue='{pi}', refund={refund} BRL")

        except Exception as e:
            print(f"[EXCEPTION] for {case_input['case_id']}: {e}")
            all_passed = False

    server.shutdown()
    server.server_close()

    if all_passed:
        print("\n[SUCCESS] ALL DASHBOARD API ENDPOINT TESTS PASSED!")
    else:
        print("\n[FAIL] SOME TESTS FAILED.")
        sys.exit(1)


if __name__ == "__main__":
    test_api()
