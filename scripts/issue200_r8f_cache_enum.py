#!/usr/bin/env python3
"""Participant-side cache directory enumeration for Issue #200 Phase 5.

Lists every entry under a cache dir's rpc/ subtree with size and sha256,
emitting a raw receipt on stdout.  Runs ON THE PARTICIPANT (inferswarm04);
invoked by the orchestrator as
``bash .../issue200_r8f_cache_enum.sh <arm> <cache-dir>``.
"""
import hashlib
import json
import os
import sys

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
    "schema": "inferswarm.issue200.cache-enumeration-receipt/1",
    "arm": arm, "node_id": node_id, "cache_dir": cache_dir,
    "measured_at": int(os.environ.get("SOURCE_DATE_EPOCH", __import__("time").time())),
    "command": ["cache-enum.sh", arm, cache_dir],
    "entries": entries}, indent=1))
