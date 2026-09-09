#!/usr/bin/env python3
"""Issue #117 Arm C — synthetic retained-evidence builder (CPU-only, tests).

Builds a COMPLETE, internally consistent synthetic arm-c evidence directory
(fakeroot) exercising the reducer's real derivation path. The reducer must
derive PASS on the synthetic baseline; the mutation suite then mutates one
fact at a time and requires a non-PASS terminal (FAIL or BLOCKED) through
the same derivation.

The synthetic documents mirror the exact schemas of the physical campaign
records. Contains no model bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

PRODUCER = "924cd22ea081f6d4ed471016faf01d427fc5b0d2"
PLAN_DIGEST = "sha256:" + "ab" * 32
EPOCH = "research-generation-0:c0ffee123456"
CASES = [f"c109-{i:02d}" for i in range(1, 25)]


def w(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")


def build(out: Path) -> None:
    tokens = {c: [1000 + i for i in range(8)] for c in CASES}

    def direct_case(i: int, c: str) -> dict:
        return {
            "case_id": c, "session_id": i,
            "prompt_token_ids": [5, 6, 7],
            "generated_token_ids": tokens[c],
            "decoded_output": "xxxxxxxx",
            "decoded_output_sha256": hashlib.sha256(
                b"xxxxxxxx").hexdigest(),
            "plan_digest": PLAN_DIGEST, "wall_ns": 1,
        }

    def ordinary_record(i: int, c: str) -> dict:
        content = "xxxxxxxx"
        return {
            "case_id": c, "request_session_index": i,
            "http_status": 200,
            "response": {
                "choices": [{"index": 0,
                             "message": {"role": "assistant",
                                         "content": content},
                             "finish_reason": "length"}],
            },
            "wall_ns": 1,
        }

    def request(i: int, c: str) -> dict:
        return {
            "session_id": i,
            "generated_token_ids": tokens[c],
            "committed_epoch_ids": [EPOCH] * 8,
            "committed_plan_digests": [PLAN_DIGEST] * 8,
            "token_events": [
                {"step": s, "token_id": tokens[c][s],
                 "epoch_id": EPOCH, "plan_digest": PLAN_DIGEST,
                 "position": s}
                for s in range(8)
            ],
        }

    w(out / "run-record.json", {
        "schema": "inferswarm.issue117.arm-c.run-record/1",
        "frozen_producer": PRODUCER,
        "orchestration_audit": {
            "coordinator_model_byte_cotargeting_commands": 0,
            "coordinator_destructive_operations": 0,
        },
    })
    w(out / "attempt-lineage.json", {
        "schema": "inferswarm.issue117.arm-c.attempt-lineage/1",
        "attempts": [{
            "attempt_id": "armc-attempt-1", "valid": True,
            "correctness_bearing_result_emitted": True,
            "coordinator_commit_occurred": True,
            "accepted_arm_b_state_changed": False,
        }],
    })
    w(out / "reconciliation.json", {
        "schema": "inferswarm.issue117.arm-c.reconciliation/1",
        "reconciled": True, "armb_pins_verified": True,
    })
    w(out / "plan-verification.json", {
        "schema": "inferswarm.issue117.arm-c.plan-verification/1",
        "running_producer": PRODUCER,
        "equality_beyond_provenance_model_path": True,
        "arm_c_plan_digest": PLAN_DIGEST,
    })
    w(out / "direct-run.json", {
        "schema": "inferswarm.issue117.arm-c.direct-run/1",
        "producer": PRODUCER, "plan_digest": PLAN_DIGEST,
        "case_count": 24,
        "results": [direct_case(i, c) for i, c in enumerate(CASES, 1)],
        "runtime_report": {},
    })
    w(out / "ordinary-campaign.json", {
        "schema": "inferswarm.issue117.arm-c.ordinary-campaign/1",
        "case_count": 24, "ok_count": 24,
        "records": [ordinary_record(i, c)
                    for i, c in enumerate(CASES, 1)],
    })
    w(out / "coordinator-report.json", {
        "schema": "inferswarm.r5b.epoch-serving-report/1",
        "active_epoch_id": EPOCH,
        "active_plan_digest": PLAN_DIGEST,
        "active_realization_id": "realization-1-abc",
        "coordinator_scope": {
            "requests": [request(i, c) for i, c in enumerate(CASES, 1)],
        },
        "late_result_rejections": [
            {"reason": "NON_NEXT_COMMIT_POSITION",
             "envelope": {"injection":
                          "CONTROLLED_LATE_REAL_SERVING_RESULT"}},
            {"reason": "RETIRED_OR_SUPERSEDED_EPOCH",
             "envelope": {"injection":
                          "CONTROLLED_STALE_EPOCH_RESULT"}},
        ],
    })
    w(out / "fencing-arm.json", {
        "schema": "inferswarm.issue117.arm-c.fencing-arm/1",
        "http_status": 200,
    })

    def state_entries() -> list:
        return [
            {"path": "/srv/inferswarm/state/arm-c/serving-report.json",
             "type": "f", "size": 2048, "sha256": "cd" * 32,
             "mtime_ns": 1, "ino": 1},
        ]

    w(out / "coordinator-env.json", {
        "schema": "inferswarm.issue117.arm-c.coordinator-env/1",
        "nvidia_device_nodes_present": False,
        "torch_importable": False, "triton_importable": False,
    })
    w(out / "coordinator-census-pre.json",
      {"entries": state_entries()})
    w(out / "coordinator-census-post.json",
      {"entries": state_entries()})

    def host_census(materialized_sha: str) -> dict:
        mat = [
            {"path": f"/srv/inferswarm/materialized/issue117/s{i}",
             "type": "f", "size": 4096, "sha256": materialized_sha,
             "mtime_ns": 1, "ino": 100 + i}
            for i in range(1, 4)
        ]
        cache = [
            {"path": f"/srv/inferswarm/cache/issue117/objects/o{i}",
             "type": "f", "size": 4096, "sha256": "ef" * 32,
             "mtime_ns": 1, "ino": 200 + i}
            for i in range(1, 4)
        ]
        return {"roots": {
            "/srv/inferswarm/materialized/issue117": {
                "exists": True, "entry_count": len(mat), "entries": mat},
            "/srv/inferswarm/cache/issue117": {
                "exists": True, "entry_count": len(cache), "entries": cache},
        }}

    for host in ("01", "03"):
        w(out / f"host-census-pre-{host}.json", host_census("aa" * 32))
        w(out / f"host-census-post-{host}.json", host_census("aa" * 32))

    w(out / "strace-audit.json", {
        "schema": "inferswarm.issue117.arm-c.strace-audit/1",
        "windows": {
            "direct": {"collected": True,
                       "paths": ["/srv/inferswarm/state/arm-c/model-view/"
                                 "stage-1.safetensors"]},
            "ordinary": {"collected": True,
                         "paths": ["/srv/inferswarm/state/arm-c/model-view/"
                                   "stage-2.safetensors"]},
        },
    })
    for name in ("last-stage-direct.json", "last-stage-ordinary.json"):
        w(out / name, {"runtime": {"persistent_host_model_bytes": 0}})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    build(Path(args.out))
    print(json.dumps({"built": args.out}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
