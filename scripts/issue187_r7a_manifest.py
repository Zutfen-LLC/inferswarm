#!/usr/bin/env python3
"""Write/check the additive Issue #187 evidence integrity indexes."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AREA = ROOT / "docs/investigations/deepseek-v41-flash-r7-a"
PRODUCERS = ("scripts/issue187_r7a_census.py", "scripts/issue187_r7a_reducer.py",
             "scripts/issue187_r7a_manifest.py", "tests/test_issue187_r7a.py")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_or_check(path: Path, body: bytes, write: bool) -> None:
    if write:
        path.write_bytes(body)
    elif not path.is_file() or path.read_bytes() != body:
        raise ValueError(f"ISSUE187_FAIL: integrity drift in {path.name}")


def producer_hash_bytes(root: Path = ROOT) -> bytes:
    """Return the canonical Issue #187 producer identity ledger."""
    producers = {relative: digest(root / relative) for relative in PRODUCERS}
    return (json.dumps({"schema": "inferswarm.issue187.producer-hashes/1",
                       "producers": producers}, sort_keys=True,
                      separators=(",", ":")).encode() + b"\n")


def manifest_bytes(root: Path = ROOT) -> bytes:
    """Return the terminal manifest after all Issue #187 outputs exist."""
    area = root / AREA.relative_to(ROOT)
    entries = []
    for path in sorted(area.rglob("*")):
        if path.is_file() and path.name != "MANIFEST.sha256":
            entries.append(f"{digest(path)}  {path.relative_to(root)}")
    for relative in PRODUCERS:
        entries.append(f"{digest(root / relative)}  {relative}")
    return ("\n".join(entries) + "\n").encode()


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true",
                      help="verify the committed indexes (the default)")
    args = parser.parse_args()
    write_or_check(AREA / "producer-hashes.json", producer_hash_bytes(), args.write)
    write_or_check(AREA / "MANIFEST.sha256", manifest_bytes(), args.write)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
