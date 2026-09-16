#!/usr/bin/env python3
"""Participant-side cache directory enumeration for Issue #200 Phase 5.

Lists every entry under a cache dir's rpc/ subtree with size and sha256,
emitting a raw receipt on stdout.  Runs ON THE PARTICIPANT (inferswarm04);
invoked by the orchestrator as
``python3 .../issue200_r8f_cache_enum.py <arm> <cache-dir>``.

Correction round 3 hardening (review item 11):

- emits its OWN tool identity (path + sha256 of the running helper source)
  so the validator can require the exact committed helper bytes;
- emits the actual executable/argv used (``sys.executable`` + ``sys.argv``),
  never a fictitious wrapper name;
- ``measured_at`` is the real clock at measurement time — the
  ``SOURCE_DATE_EPOCH`` override is REMOVED (a participant-controlled env
  can no longer forge the timestamp the reuse-arm ordering proof consumes).
"""
import hashlib
import json
import os
import sys
import time
from pathlib import Path


def helper_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def main() -> int:
    if len(sys.argv) != 3:
        print(json.dumps({"error": "usage: issue200_r8f_cache_enum.py <arm> <cache-dir>"}),
              file=sys.stderr)
        return 1
    arm, cache_dir = sys.argv[1], sys.argv[2]
    node_id = os.uname().nodename
    entries = []
    rpc = os.path.join(cache_dir, "rpc")
    if os.path.isdir(rpc):
        for name in sorted(os.listdir(rpc)):
            path = os.path.join(rpc, name)
            if os.path.isfile(path):
                digest = hashlib.sha256()
                with open(path, "rb") as handle:
                    for block in iter(lambda: handle.read(1 << 20), b""):
                        digest.update(block)
                entries.append({"name": f"rpc/{name}", "size": os.path.getsize(path),
                                "sha256": digest.hexdigest()})
    print(json.dumps({
        "schema": "inferswarm.issue200.cache-enumeration-receipt/2",
        "tool": {"path": "scripts/issue200_r8f_cache_enum.py", "sha256": helper_sha256()},
        "arm": arm, "node_id": node_id, "cache_dir": cache_dir,
        "measured_at": time.time(),
        "command": [sys.executable, os.path.abspath(__file__), arm, cache_dir],
        "entries": entries}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
