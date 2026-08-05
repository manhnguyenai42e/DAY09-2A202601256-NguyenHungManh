"""Script to create a clean output.zip submission file.

Places exactly 50 EC_*.json files at the root of the zip archive without
any nested folder wrappers or system files.
"""

import sys
import zipfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT_DIR / "output"
ZIP_PATH = ROOT_DIR / "output.zip"


def create_zip():
    json_files = sorted(OUTPUT_DIR.glob("EC_*.json"))
    if len(json_files) != 50:
        print(f"[ERROR] Expected 50 files in output/, found {len(json_files)}")
        sys.exit(1)

    print(f"[ZIP] Creating {ZIP_PATH.name} containing 50 JSON files...")

    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for filepath in json_files:
            # Write with arcname = output/EC_xxx.json per competition rule
            zf.write(filepath, arcname=f"output/{filepath.name}")

    print(f"[ZIP] Success! Created {ZIP_PATH} ({ZIP_PATH.stat().st_size / 1024:.1f} KB)")

    # Verify archive contents
    with zipfile.ZipFile(ZIP_PATH, "r") as zf:
        namelist = zf.namelist()
        print(f"[ZIP] Contents Check ({len(namelist)} items):")
        print(f"      First 3 items: {namelist[:3]}")
        print(f"      Last 3 items:  {namelist[-3:]}")


if __name__ == "__main__":
    create_zip()
