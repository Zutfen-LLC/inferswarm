"""Arm-B node inventory snapshot (metadata-only receipt for the Coordinator).

Walks the verified objects of one node cache root, re-verifies each byte
digest, and emits a VerifiedInventory-shaped receipt (sequence-stamped).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import armb_plan_core as core  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache-root", required=True)
    ap.add_argument("--node-id", required=True)
    ap.add_argument("--sequence", type=int, default=1)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    root = Path(args.cache_root)
    verified = []
    for path in sorted((root / "objects").iterdir()):
        data = path.read_bytes()
        digest = "sha256:" + path.name.replace("sha256-", "")
        verified.append({"content_digest": digest, "length": len(data),
                         "byte_digest_verified": core.digest_of_bytes(data) == digest})
    doc = {
        "schema": "inferswarm.issue101.node-inventory-snapshot/1",
        "node_id": args.node_id,
        "sequence": args.sequence,
        "source": {"source_id": args.node_id, "endpoint": root.resolve().as_uri()},
        "verified_objects": verified,
        "collected_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_bytes(core.canonical_json_bytes(doc))
    print(json.dumps({"node": args.node_id, "verified": len(verified),
                      "bytes": sum(o["length"] for o in verified)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
