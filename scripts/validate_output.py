"""Pre-submission checker: exactly 50 output/EC_*.json files, each parses,
matches the schema/limits, and every evidence ID is grounded in the source
CSVs. Run this before zipping output/."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import INPUT_DIR, OUTPUT_DIR
from src.mcp_server.schema import validate_case


def main() -> int:
    expected_ids = {p.stem for p in sorted(INPUT_DIR.glob("EC_*.json"))}
    output_files = sorted(OUTPUT_DIR.glob("EC_*.json"))
    output_ids = {p.stem for p in output_files}

    ok = True

    if len(output_files) != 50:
        print(f"FAIL: expected exactly 50 files in output/, found {len(output_files)}")
        ok = False

    missing = expected_ids - output_ids
    extra = output_ids - expected_ids
    if missing:
        print(f"FAIL: missing outputs for: {sorted(missing)}")
        ok = False
    if extra:
        print(f"FAIL: unexpected extra files: {sorted(extra)}")
        ok = False

    total_violations = 0
    for path in output_files:
        try:
            case = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"FAIL: {path.name} does not parse as JSON: {exc}")
            ok = False
            continue
        if case.get("case_id") != path.stem:
            print(f"FAIL: {path.name} case_id mismatch: {case.get('case_id')}")
            ok = False
        violations = validate_case(case)
        if violations:
            ok = False
            total_violations += len(violations)
            print(f"FAIL: {path.name}: {violations}")

    if ok:
        print(f"PASS: {len(output_files)}/50 files, schema+evidence clean.")
    else:
        print(f"\n{total_violations} field violation(s) across output files.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
