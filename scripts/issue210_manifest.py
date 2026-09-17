#!/usr/bin/env python3
"""Issue #210 — write and verify the V2-B evidence MANIFEST.sha256.

Rows are repository-root-relative and cover every file in the V2-B
namespace except the manifest itself (self-reference is unsatisfiable).
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AREA = ROOT / "docs/investigations/vulkan-v2-b-v340l"
MANIFEST = AREA / "MANIFEST.sha256"


def rows() -> dict[str, str]:
    out = {}
    for path in sorted(AREA.rglob("*")):
        if path.is_file() and path != MANIFEST:
            out[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def write() -> int:
    lines = [f"{sha}  {rel}" for rel, sha in rows().items()]
    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {len(lines)} rows")
    return 0


def check() -> int:
    listed = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        sha, rel = line.split("  ", 1)
        listed[rel] = sha
    actual = rows()
    if listed != actual:
        missing = sorted(set(actual) - set(listed))
        extra = sorted(set(listed) - set(actual))
        drifted = [r for r in sorted(set(actual) & set(listed)) if actual[r] != listed[r]]
        print(f"MANIFEST mismatch: missing={missing} extra={extra} drifted={drifted}")
        return 1
    print(f"MANIFEST OK ({len(listed)} rows, on-disk set equals listed set)")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.write:
        return write()
    return check()


if __name__ == "__main__":
    raise SystemExit(main())
