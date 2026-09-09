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
CHAIN_DIGEST = "sha256:" + "cd" * 32
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
        "chain_plan_digest": CHAIN_DIGEST,
        "case_count": 24,
        "results": [direct_case(i, c) for i, c in enumerate(CASES, 1)],
        "runtime_report": {},
    })
    import hashlib as _h
    (out / "direct").mkdir(parents=True, exist_ok=True)
    w(out / "direct/execution-plan.json", {
        "schema": "inferswarm.r5a.static-execution-plan/1",
        "digest": PLAN_DIGEST,
        "selection_authorization": {
            "mode": "CONTROLLED_EVIDENCE_COLLECTION_OVERRIDE",
            "candidate_id": "dense.6171f32b4413",
        },
        "strategy_realization": {
            "participant_plan_digest": CHAIN_DIGEST,
            "realization": "r6-dense-three-stage-chain",
        },
        "participants": ["node.inferswarm01", "node.inferswarm03"],
        "compute_units": ["gpu.node-a.0", "gpu.node-a.1", "gpu.node-b.0"],
        "semantic_boundaries": [],
        "mapping": {"slot-stage-1": "gpu.node-a.0",
                    "slot-stage-2": "gpu.node-a.1",
                    "slot-stage-3": "gpu.node-b.0"},
        "representations": [],
        "backend_choices": [],
        "state_placement": [],
        "state_authority": [],
    })
    content = "xxxxxxxx"
    content_sha = _h.sha256(content.encode()).hexdigest()
    w(out / "decoded-bytes.json", {
        "schema": "inferswarm.issue117.arm-c.decoded-bytes/1",
        "case_count": 24,
        "rows": [{
            "case_id": c, "session_id": i,
            "ordinary_decode_sha256": content_sha,
            "direct_decode_sha256": content_sha,
            "ordinary_http_content_sha256": content_sha,
            "ordinary_http_content_len": len(content),
        } for i, c in enumerate(CASES, 1)],
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
        "epochs": [{
            "epoch_id": EPOCH,
            "state": "RECLAIMED",
            "execution_plan": {
                "digest": PLAN_DIGEST,
                "selection_authorization": {
                    "mode": "AUTOMATIC_PLANNER_SELECTION",
                    "candidate_id": "dense.6171f32b4413",
                },
                "strategy_realization": {
                    "participant_plan_digest": CHAIN_DIGEST,
                    "realization": "r6-dense-three-stage-chain",
                },
                "participants": ["node.inferswarm01", "node.inferswarm03"],
                "compute_units": ["gpu.node-a.0", "gpu.node-a.1",
                                  "gpu.node-b.0"],
                "semantic_boundaries": [],
                "mapping": {"slot-stage-1": "gpu.node-a.0",
                            "slot-stage-2": "gpu.node-a.1",
                            "slot-stage-3": "gpu.node-b.0"},
                "representations": [],
                "backend_choices": [],
                "state_placement": [],
                "state_authority": [],
            },
        }],
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
                       "paths": [
                           "/srv/models/gemma-r6/config.json",
                           "/srv/models/gemma-r6/chat_template.jinja",
                           "/srv/models/gemma-r6/tokenizer.json",
                           "/srv/models/gemma-r6/tokenizer_config.json",
                           "/srv/inferswarm/state/arm-c/model-view/"
                           "stage-1.safetensors"]},
            "ordinary": {"collected": True,
                         "paths": ["/srv/inferswarm/state/arm-c/model-view/"
                                   "stage-2.safetensors"]},
        },
    })
    # pre-execution authority audit (frozen-rule Source accounting): a
    # clean synthetic campaign that still discloses the four retained
    # tokenizer-metadata reads counted under the frozen zero-Source rule
    w(out / "pre-execution-authority-audit.json", {
        "schema": "inferswarm.issue117.arm-c."
                  "pre-execution-authority-audit/1",
        "claimed_pre_execution_inferswarm_sha":
            "5e2c83a09031d68784c3098fc9dad319b684f0da",
        "source_read_accounting_frozen_rule": {
            "frozen_rule": "zero /srv/models/ opens (synthetic)",
            "total_opens_counted": 4,
            "tokenizer_metadata_file_reads": 4,
            "source_root_directory_stats": 0,
            "model_weight_file_reads": 0,
            "observed_paths": {"tokenizer_metadata_files": [
                "direct:/srv/models/gemma-r6/config.json",
                "direct:/srv/models/gemma-r6/chat_template.jinja",
                "direct:/srv/models/gemma-r6/tokenizer.json",
                "direct:/srv/models/gemma-r6/tokenizer_config.json"],
                "directory_stats": [], "model_weight_files": []},
            "historical_classification": "synthetic",
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
