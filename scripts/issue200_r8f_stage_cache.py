#!/usr/bin/env python3
"""Controlled participant-side cache staging helper for Issue #200 Phase 5.

Runs ON THE PARTICIPANT (inferswarm04).  Reads the exact accepted member
range (verifying the complete member identity first, exactly like the range
receipt helper), then atomically publishes those bytes into the pinned
ggml-rpc-server cache directory at the FNV-1a-keyed final path:

  1. write to a temporary file INSIDE the target cache directory;
  2. verify the temporary file's exact SHA-256 and size;
  3. atomically rename into ``<cache_dir>/rpc/<fnv1a>``;
  4. re-read the FINAL path and verify exact SHA-256 and size;
  5. emit one canonical measured receipt on stdout.

FNV-1a is used only to compute the upstream cache filename; SHA-256 and the
accepted R8-D authority remain the trust anchor (never the filename).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path


def canonical_json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode()


def helper_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fnv1a64(data: bytes) -> str:
    value = 0xcbf29ce484222325
    for byte in data:
        value = ((value ^ byte) * 0x100000001b3) & 0xffffffffffffffff
    return f"{value:016x}"


def stage(*, node_id: str, source_path: Path, member: str,
          accepted_member_bytes: int, accepted_member_sha256: str,
          offset: int, length: int, cache_dir: Path) -> dict:
    if not source_path.is_absolute() or not cache_dir.is_absolute():
        raise ValueError("absolute source and cache paths are required")
    if Path(member).name != member or not node_id:
        raise ValueError("node id and bare member filename are required")
    if offset < 0 or length <= 0 or offset + length > accepted_member_bytes:
        raise ValueError("range is invalid for the accepted member")
    actual_bytes = source_path.stat().st_size
    if actual_bytes != accepted_member_bytes:
        raise ValueError("local member length differs from accepted authority")
    actual_sha = sha256_file(source_path)
    if actual_sha != accepted_member_sha256:
        raise ValueError("local member SHA-256 differs from accepted authority")
    rpc_dir = cache_dir / "rpc"
    rpc_dir.mkdir(parents=True, exist_ok=True)
    final_path = rpc_dir / "pending-fnv"  # replaced below after reading the range
    with source_path.open("rb") as handle:
        handle.seek(offset)
        selected = handle.read(length)
    if len(selected) != length:
        raise ValueError("short local member read")
    selected_sha = hashlib.sha256(selected).hexdigest()
    fnv = fnv1a64(selected)
    final_path = rpc_dir / fnv
    tmp_path = rpc_dir / f".{fnv}.stage-tmp"
    if final_path.exists():
        raise ValueError(f"final cache path already exists: {final_path}")
    with open(tmp_path, "wb") as handle:
        handle.write(selected)
        handle.flush()
        os.fsync(handle.fileno())
    tmp_size = tmp_path.stat().st_size
    tmp_sha = sha256_file(tmp_path)
    if tmp_size != length or tmp_sha != selected_sha:
        tmp_path.unlink(missing_ok=True)
        raise ValueError("temporary staged file failed exact size/SHA-256 verification")
    os.rename(tmp_path, final_path)
    final_size = final_path.stat().st_size
    final_sha = sha256_file(final_path)
    if final_size != length or final_sha != selected_sha:
        raise ValueError("final staged file failed exact re-read verification")
    return {
        "schema": "inferswarm.issue200.cache-staging-measurement/1",
        "tool": {"path": "scripts/issue200_r8f_stage_cache.py", "sha256": helper_sha256()},
        "node_id": node_id,
        "source_path": str(source_path),
        "member": member,
        "accepted_member_bytes": actual_bytes,
        "accepted_member_sha256": actual_sha,
        "offset": offset, "length": length,
        "range_sha256": selected_sha,
        "fnv1a_cache_key": fnv,
        "cache_dir": str(cache_dir),
        "staged_path": str(final_path),
        "tmp_path": str(tmp_path),
        "tmp_size": tmp_size, "tmp_sha256": tmp_sha,
        "final_size": final_size, "final_sha256": final_sha,
        "atomic_publish": "os.rename after fsync inside target directory",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node-id", required=True)
    parser.add_argument("--source-path", type=Path, required=True)
    parser.add_argument("--member", required=True)
    parser.add_argument("--member-bytes", type=int, required=True)
    parser.add_argument("--member-sha256", required=True)
    parser.add_argument("--offset", type=int, required=True)
    parser.add_argument("--length", type=int, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = stage(node_id=args.node_id, source_path=args.source_path,
                       member=args.member, accepted_member_bytes=args.member_bytes,
                       accepted_member_sha256=args.member_sha256, offset=args.offset,
                       length=args.length, cache_dir=args.cache_dir)
    except ValueError as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1
    print(canonical_json_bytes(result).decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
