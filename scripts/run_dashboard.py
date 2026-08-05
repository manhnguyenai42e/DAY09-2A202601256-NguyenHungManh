"""Launcher script for Multi-Agent Dispute Resolution Testing Dashboard.

Launches the Python HTTP server on port 8000 and opens the browser.
"""

from __future__ import annotations

import sys
import webbrowser
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.web.server import run_server

if __name__ == "__main__":
    port = 8000
    print(f"[DASHBOARD] Launching Multi-Agent Testing Dashboard at http://localhost:{port}...")
    webbrowser.open(f"http://localhost:{port}")
    run_server(port)
