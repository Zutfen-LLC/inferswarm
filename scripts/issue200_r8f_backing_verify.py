#!/usr/bin/env python3
"""Participant-side full-release backing verification for Issue #200 Phase 5.

Runs ON THE PARTICIPANT.  Verifies the complete accepted three-member
release is co-resident under the participant's durable backing directory:
every member's exact byte count and SHA-256 is live-verified against the
accepted R8-D split-rehash authority (derived from the committed authority
JSON, never duplicated as unaudited constants), and the accepted total
(72,546,461,344 bytes) is checked.  Emits a canonical raw receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
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
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_backing(*, node_id: str, backing_dir: Path, authority_path: Path) -> dict:
    authority = json.loads(authority_path.read_text())
    if authority.get("schema") != "inferswarm.issue195.split-rehash/2":
        raise ValueError("accepted R8-D split authority is malformed")
    members = []
    for item in authority["members"]:
        member_path = backing_dir / item["file"]
        present = member_path.is_file()
        actual_size = member_path.stat().st_size if present else None
        actual_sha = sha256_file(member_path) if present else None
        members.append({
            "file": item["file"], "expected_bytes": item["bytes"],
            "expected_sha256": item["sha256"], "present": present,
            "actual_bytes": actual_size, "actual_sha256": actual_sha,
            "verified": present and actual_size == item["bytes"] and actual_sha == item["sha256"],
        })
    total = sum(m["expected_bytes"] for m in members)
    if total != authority.get("total_bytes"):
        raise ValueError("authority member sizes do not sum to the accepted total")
    return {
        "schema": "inferswarm.issue200.participant-full-release-receipt/1",
        "tool": {"path": "scripts/issue200_r8f_backing_verify.py", "sha256": helper_sha256()},
        "node_id": node_id, "backing_dir": str(backing_dir),
        "authority_path": str(authority_path),
        "members": members, "total_bytes": total,
        "all_members_verified": all(m["verified"] for m in members),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node-id", required=True)
    parser.add_argument("--backing-dir", type=Path, required=True)
    parser.add_argument("--authority", type=Path, required=True)
    args = parser.parse_args()
    try:
        if not args.backing_dir.is_absolute():
            raise ValueError("backing directory must be absolute")
        receipt = verify_backing(node_id=args.node_id, backing_dir=args.backing_dir,
                                 authority_path=args.authority)
        ok = receipt["all_members_verified"]
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1
    print(canonical_json_bytes(receipt).decode())
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
