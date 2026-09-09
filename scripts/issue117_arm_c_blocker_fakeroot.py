#!/usr/bin/env python3
"""Issue #117 Arm C — extend the synthetic fakeroot with the three
retention/derivation-correctness documents consumed by the frozen-
evidence blocker reducer (CPU-only, tests). Adds:
  pre-execution-authority-audit.json (synthetic frozen identities),
  attempt-lineage.json (/2 schema with the stop boundary),
  invalid-attempt-6/ + direct-run.json + strace-audit.json + run-record
synthetic stand-ins bound to the blocker reducer's inputs.
The synthetic baseline mirrors the retained campaign shape: an invalid
stop-trigger attempt (24 result rows under invalid-attempt-6/) followed
by post-stop diagnostic attempts, and four tokenizer-metadata Source
reads under the frozen zero-Source rule.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

PRODUCER = "924cd22ea081f6d4ed471016faf01d427fc5b0d2"
FREEZE_SHA = "5e2c83a09031d68784c3098fc9dad319b684f0da"
CASES = [f"c109-{i:02d}" for i in range(1, 25)]
STOP_TRIGGER = "armc-direct-6"
REPLAY_MARKER = "per-token-replay-prefill/1"
TOKENIZER_METADATA_PATHS = [
    "/srv/models/gemma-r6/chat_template.jinja",
    "/srv/models/gemma-r6/config.json",
    "/srv/models/gemma-r6/tokenizer.json",
    "/srv/models/gemma-r6/tokenizer_config.json",
]


def w(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")


def build(out: Path) -> None:
    frozen_file_entry = {
        "git_blob_sha_at_freeze": "0" * 40,
        "sha256_at_freeze": "1" * 64,
        "sha256_at_campaign_commit": "1" * 64,
        "sha256_current_head": "2" * 64,
        "status_at_head": "changed_after_freeze",
    }
    w(out / "pre-execution-authority-audit.json", {
        "schema": "inferswarm.issue117.arm-c."
                  "pre-execution-authority-audit/1",
        "claimed_pre_execution_inferswarm_sha": FREEZE_SHA,
        "head_classified": "synthetic-head",
        "frozen_correctness_bearing_files": {
            "docs/implementation/r6-successor-dense-full-integration-"
            "117/METHODOLOGY-ARM-C.md": dict(
                frozen_file_entry,
                status_at_head="unchanged_since_freeze",
                sha256_current_head="1" * 64),
            "scripts/issue117_arm_c_direct.py": dict(frozen_file_entry),
            "scripts/issue117_arm_c_evidence.py": dict(frozen_file_entry),
        },
        "post_freeze_changes": [
            {"path": "scripts/issue117_arm_c_direct.py",
             "git_status": "M",
             "first_commit_after_freeze": "d" * 40,
             "classification": "disclosed post-freeze change",
             "note": "POST-FREEZE COMPARATOR CHANGE (synthetic)"},
            {"path": "scripts/issue117_arm_c_evidence.py",
             "git_status": "M",
             "first_commit_after_freeze": "d" * 40,
             "classification": "disclosed post-freeze change",
             "note": "POST-FREEZE REDUCER CHANGE (synthetic)"},
        ],
        "source_read_accounting_frozen_rule": {
            "frozen_rule": "zero /srv/models/ opens (synthetic)",
            "total_opens_counted": 5,
            "tokenizer_metadata_file_reads": 4,
            "source_root_directory_stats": 1,
            "model_weight_file_reads": 0,
            "observed_paths": {
                "tokenizer_metadata_files": [
                    f"direct:{p}" for p in TOKENIZER_METADATA_PATHS],
                "directory_stats": ["direct:/srv/models/gemma-r6"],
                "model_weight_files": [],
            },
            "historical_classification": "synthetic",
        },
    })

    def attempt(aid, order, cb_emitted, gpu, valid, classification):
        return {
            "attempt_id": aid, "order": order,
            "hosts": ["inferswarm01"],
            "phase_reached": "synthetic",
            "failure": None,
            "realization_request_made": True,
            "gpu_residency_achieved": gpu,
            "correctness_bearing_result_emitted": cb_emitted,
            "result_reached_coordinator": False,
            "coordinator_commit_occurred": False,
            "accepted_arm_b_state_changed": False,
            "cleanup_containment": "synthetic",
            "observed_timestamps": {},
            "code_identity": {},
            "evidence_bindings": {},
            "retained_validity_flag": valid,
            "campaign_classification": classification,
        }

    attempts = [
        attempt("armc-direct-5", 6, False, True, False,
                "pre-stop infrastructure (non-correctness-bearing)"),
        attempt(STOP_TRIGGER, 7, True, True, False,
                "correctness_bearing_stop_trigger: retained invalid "
                "attempt (synthetic) — mandatory STOP for maintainer "
                "review (METHODOLOGY-ARM-C §10)"),
        attempt("armc-direct-7", 8, False, False, False,
                "post-stop diagnostic / inadmissible to the Arm-C "
                "terminal serving claim"),
        attempt("armc-direct-8", 9, False, True, False,
                "post-stop diagnostic / inadmissible to the Arm-C "
                "terminal serving claim"),
        attempt("armc-direct-9", 10, True, True, True,
                "post-stop diagnostic / inadmissible to the Arm-C "
                "terminal serving claim"),
        attempt("armc-ordinary-1", 11, True, True, True,
                "post-stop diagnostic / inadmissible to the Arm-C "
                "terminal serving claim"),
    ]
    w(out / "attempt-lineage.json", {
        "schema": "inferswarm.issue117.arm-c.attempt-lineage/2",
        "attempts": attempts,
    })
    w(out / "invalid-attempt-6" / "direct-run.json", {
        "schema": "inferswarm.issue117.arm-c.direct-run/1",
        "attempt_id": STOP_TRIGGER,
        "case_count": 24,
        "results": [{"case_id": c, "generated_token_ids": [1] * 8}
                    for c in CASES],
    })
    w(out / "direct-run.json", {
        "schema": "inferswarm.issue117.arm-c.direct-run/1",
        "attempt_id": "armc-direct-9",
        "case_count": 24,
        "results": [{"case_id": c, "generated_token_ids": [1] * 8,
                     "invocation": REPLAY_MARKER}
                    for c in CASES],
    })
    w(out / "strace-audit.json", {
        "schema": "inferswarm.issue117.arm-c.strace-audit/1",
        "windows": {
            "direct": {"collected": True,
                       "paths": TOKENIZER_METADATA_PATHS
                                + ["/srv/models/gemma-r6",
                                   "/srv/inferswarm/state/arm-c/x"]},
            "ordinary": {"collected": True, "paths": []},
        },
    })
    w(out / "run-record.json", {
        "schema": "inferswarm.issue117.arm-c.run-record/1",
        "frozen_producer": PRODUCER,
        "pre_execution_inferwarm_sha": FREEZE_SHA,
        "orchestration_audit": {
            "coordinator_model_byte_cotargeting_commands": 0,
            "coordinator_destructive_operations": 0,
        },
    })


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    build(Path(args.out))
    print(json.dumps({"built": args.out}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
