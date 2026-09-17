#!/usr/bin/env python3
"""Build or verify Issue #209's CPU/static evidence manifest.

Verification fails closed when any retained evidence-manifest or producer-hash
byte differs from its deterministic, repository-relative derivation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AREA = ROOT / "docs/investigations/deepseek-v41-flash-r7-b"
OUTPUT = AREA / "MANIFEST.sha256"
PRODUCERS = (
    "scripts/issue209_r7b_manifest.py",
    "scripts/issue209_r7b_reducer.py",
    "tests/test_issue209_r7b.py",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def producer_hash_bytes(root: Path = ROOT) -> bytes:
    producers = {relative: digest(root / relative) for relative in PRODUCERS}
    return (json.dumps({"schema": "inferswarm.issue209.producer-hashes/1",
                       "producers": producers}, sort_keys=True,
                      separators=(",", ":")).encode() + b"\n")


def manifest_bytes(root: Path = ROOT) -> bytes:
    area = root / AREA.relative_to(ROOT)
    entries = []
    for path in sorted(area.rglob("*")):
        if path.is_file() and path.name != "MANIFEST.sha256":
            entries.append(f"{digest(path)}  {path.relative_to(root)}")
    for relative in PRODUCERS:
        entries.append(f"{digest(root / relative)}  {relative}")
    return ("\n".join(entries) + "\n").encode()


def manifest_text() -> str:
    return manifest_bytes().decode()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.write == args.check:
        raise SystemExit("choose exactly one of --write or --check")
    hashes = producer_hash_bytes()
    text = manifest_bytes()
    if args.write:
        (AREA / "producer-hashes.json").write_bytes(hashes)
        OUTPUT.write_bytes(manifest_bytes())
    elif (AREA / "producer-hashes.json").read_bytes() != hashes \
            or not OUTPUT.is_file() or OUTPUT.read_bytes() != text:
        raise SystemExit("ISSUE209_FAIL: evidence manifest drift; run with --write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
