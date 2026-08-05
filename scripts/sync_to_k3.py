"""Synchronization script to mirror web dashboard, scripts, and src modules to D:\\Workspace\\K3-Day9-Multi-Agent-A2A.
"""

import shutil
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent
TARGET_DIR = Path(r"D:\Workspace\K3-Day9-Multi-Agent-A2A")


def sync_workspace():
    if not TARGET_DIR.exists():
        print(f"[SYNC] Target directory {TARGET_DIR} does not exist. Creating it...")
        TARGET_DIR.mkdir(parents=True, exist_ok=True)

    items_to_sync = ["src", "scripts"]

    for item in items_to_sync:
        src_path = SRC_DIR / item
        dst_path = TARGET_DIR / item

        if src_path.exists():
            print(f"[SYNC] Copying {src_path} -> {dst_path}...")
            if dst_path.exists():
                shutil.rmtree(dst_path)
            shutil.copytree(src_path, dst_path)

    print("[SYNC] Synchronization completed successfully!")


if __name__ == "__main__":
    sync_workspace()
