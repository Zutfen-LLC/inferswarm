#!/usr/bin/env python3
"""CPU-only, deterministic range-measurement tool for Issue #200 Phase 5.

The tool is deliberately usable on a fleet node without importing llama.cpp.
It reads the local accepted member itself, checks its complete identity, then
emits a canonical receipt and (optionally) the exact bounded bytes it read.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from issue74_methodology import canonical_json_bytes


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def helper_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def measure_range(*, node_id: str, source_path: Path, member: str,
                  accepted_member_bytes: int, accepted_member_sha256: str,
                  offset: int, length: int, retained_range_path: Path | None = None) -> dict[str, Any]:
    """Measure an actual local member and return only checked facts."""
    if not source_path.is_absolute() or not node_id or Path(member).name != member:
        raise ValueError("node, absolute source path, and member filename are required")
    if offset < 0 or length <= 0:
        raise ValueError("offset/length are invalid")
    actual_bytes = source_path.stat().st_size
    if actual_bytes != accepted_member_bytes:
        raise ValueError("local member length differs from accepted authority")
    actual_sha = sha256_file(source_path)
    if actual_sha != accepted_member_sha256:
        raise ValueError("local member SHA-256 differs from accepted authority")
    if offset + length > actual_bytes:
        raise ValueError("range exceeds accepted member")
    with source_path.open("rb") as handle:
        handle.seek(offset)
        selected = handle.read(length)
    if len(selected) != length:
        raise ValueError("short local member read")
    if retained_range_path is not None:
        retained_range_path.parent.mkdir(parents=True, exist_ok=True)
        retained_range_path.write_bytes(selected)
    return {
        "schema": "inferswarm.issue200.accepted-range-measurement/1",
        "tool": {"path": "scripts/issue200_r8f_range_receipt.py", "sha256": helper_sha256()},
        "node_id": node_id, "source_path": str(source_path), "member": member,
        "accepted_member_bytes": actual_bytes, "accepted_member_sha256": actual_sha,
        "offset": offset, "length": length, "range_sha256": hashlib.sha256(selected).hexdigest(),
        "retained_range_path": str(retained_range_path) if retained_range_path else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--node-id", required=True)
    parser.add_argument("--source-path", type=Path, required=True)
    parser.add_argument("--member", required=True)
    parser.add_argument("--member-bytes", type=int, required=True)
    parser.add_argument("--member-sha256", required=True)
    parser.add_argument("--offset", type=int, required=True)
    parser.add_argument("--length", type=int, required=True)
    parser.add_argument("--write-range", type=Path)
    args = parser.parse_args()
    result = measure_range(node_id=args.node_id, source_path=args.source_path,
                           member=args.member, accepted_member_bytes=args.member_bytes,
                           accepted_member_sha256=args.member_sha256, offset=args.offset,
                           length=args.length, retained_range_path=args.write_range)
    print(canonical_json_bytes(result).decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
