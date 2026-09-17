#!/usr/bin/env python3
"""Issue #215 — V2-C campaign v2 authority: supersedes v1.

v1 terminal: V2C_EVIDENCE_BLOCKED (retained under cycles/). Root cause of
the block (capture-side, NOT platform instability): the operator power cut
for the cold cycle landed while the cycle-04 sentinel's final writes were
still in the page cache; the tool completed and printed PASS over SSH, but
sentinel-record.json and the die run outputs never reached disk. The
platform itself showed zero failures across every observed predicate
(cycles 1,2,3,5 + final canonical all PASS, including the cold boot).

v2 changes (capture-side only; no platform mutation, no predicate
loosening):
  1. fsync-durable artifact writes in BOTH collectors (snapshot + sentinel)
     — every file fsynced with its parent directory entry before the tool
     proceeds.
  2. Cold-cycle protocol: the operator power-off signal is issued ONLY
     after the collector has durably completed the final pre-power cycle's
     sentinel AND an explicit byte-level readback verification of every
     retained artifact (size > 0 + digest match) has passed on disk.

Supersession is honest: v1 is retained byte-for-byte; v2 derives from its
own fresh campaign cycles only. Campaign id: issue215-v2c-v340l-platform-stability-v2.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NS = "vulkan-v2-c-v340l-platform-stability"
AREA = ROOT / "docs/investigations" / NS

V1_CAMPAIGN_ID = "issue215-v2c-v340l-platform-stability-v1"
V2_CAMPAIGN_ID = "issue215-v2c-v340l-platform-stability-v2"
SUPERSEDED = "55b9f1ee6c2881a6de8ffb2875ea22237bdf6a34"  # durable-writes commit


def build_v2_plan(base_plan: dict) -> dict:
    plan = json.loads(json.dumps(base_plan))
    plan["campaign_id"] = V2_CAMPAIGN_ID
    plan["supersedes"] = {
        "v1_campaign_id": V1_CAMPAIGN_ID,
        "v1_terminal": "V2C_EVIDENCE_BLOCKED",
        "v1_terminal_cause": "sentinel capture unavailable on cycle 4 (power-cut page-cache loss)",
        "superseding_commit": SUPERSEDED,
        "changes": [
            "fsync-durable artifact writes in snapshot and sentinel collectors",
            "cold-cycle protocol: power-off signal only after durable sentinel completion + on-disk readback verification",
        ],
    }
    return plan


if __name__ == "__main__":
    v1 = json.loads((AREA / "CAMPAIGN-PLAN.json").read_text())
    plan = build_v2_plan(v1["campaign_plan"])
    payload = json.dumps(plan, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    digest = hashlib.sha256(payload).hexdigest()
    doc = {"campaign_plan": plan, "campaign_plan_digest": digest}
    (AREA / "CAMPAIGN-PLAN-V2.json").write_bytes(json.dumps(doc, indent=1, sort_keys=True).encode() + b"\n")
    print(digest)
