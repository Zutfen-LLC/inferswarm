#!/usr/bin/env python3
"""Issue #117 Arm C — extend the synthetic fakeroot with the documents
consumed by the frozen-evidence blocker reducer, correction /2 (CPU-only
tests). Adds:

  pre-execution-authority-audit.json (synthetic frozen identities,
      comparator-modification forensics, fail-closed correction
      allowlist, frozen-rule source-read accounting),
  attempt-lineage.json (/3 schema: separated chronology, historical
      validity classifications),
  frozen-freetoken/924cd22e/ synthetic ordinary-path sources (the
      replay-prefix controller, the dispatching coordinator, the
      replay-input strategy),
  invalid-attempt-6/ + direct-run.json + strace-audit.json + run-record
  synthetic stand-ins bound to the blocker reducer's inputs.

The synthetic baseline mirrors the retained campaign shape: a
correctness-bearing direct-6 observation whose single-shot invocation
matches the frozen comparator (exact driver bytes unknown / not
retained), a correctness-bearing ordinary-1 observation whose planner
provenance cites direct-6, three post-revision diagnostics in
timestamp-supported chronology, and four tokenizer-metadata Source file
reads + one Source-root stat under the frozen zero-Source rule.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

PRODUCER = "924cd22ea081f6d4ed471016faf01d427fc5b0d2"
FREEZE_SHA = "5e2c83a09031d68784c3098fc9dad319b684f0da"
CASES = [f"c109-{i:02d}" for i in range(1, 25)]
DIRECT_ATTEMPT = "armc-direct-6"
REPLAY_MARKER = "per-token-replay-prefill/1"
UNKNOWN = "unknown / not retained"
TOKENIZER_METADATA_PATHS = [
    "/srv/models/gemma-r6/chat_template.jinja",
    "/srv/models/gemma-r6/config.json",
    "/srv/models/gemma-r6/tokenizer.json",
    "/srv/models/gemma-r6/tokenizer_config.json",
]

#: synthetic ordinary-path FreeToken sources (shape-faithful to the
#: retained 924cd22e bytes; the REAL pinned bytes live in the repo and
#: are exercised by the real-evidence test + the frozen-pins suite)
SYNTHETIC_EPOCHS = '''# synthetic r5b_epochs.py (shape-faithful stand-in)
    def replay_input(self, *, session):
        return list(session.prompt_token_ids) + list(session.committed_token_ids)

    def serve_tokens(self, *, session_id, prompt_token_ids,
                     max_new_tokens, sampling_inputs,
                     on_token=None, after_commit=None):
        while session.committed_position < max_new_tokens:
            replay_input = list(self.transition_strategy.replay_input(session=session))
            def capture(_step, token, boundary):
                if _step == 0:
                    token_holder.append(int(token))
            result = dict(epoch.runtime.generate(
                session_id=runtime_session_id,
                prompt_token_ids=replay_input,
                # decode interval. Commit only step zero; step one is
                # explicitly speculative and discarded before replay.
                max_new_tokens=2,
                on_token=capture,
            ))
            commit = {
                "committed_at_ns": session.committed_at_ns[-1],
                "replay_input_token_count": len(replay_input),
                "speculative_uncommitted_tokens_discarded": 1,
            }
'''
SYNTHETIC_COORDINATOR = '''# synthetic inferswarm_r6/coordinator.py (shape-faithful stand-in)
from freetoken.research.r5b_epochs import EpochServingController
        return EpochServingController(
            transition_strategy=GemmaTokenBoundaryStrategy(),
        )
        completed = self.controller.serve_tokens(
            session_id=session_id,
            prompt_token_ids=prompt_ids,
            max_new_tokens=maximum,
            sampling_inputs=sampling,
            on_token=on_token,
        )
'''
SYNTHETIC_STRATEGY = '''# synthetic xc_strategy.py (shape-faithful stand-in)
class GemmaTokenBoundaryStrategy:
    def replay_input(self, *, session):
        return list(session.prompt_token_ids) + list(session.committed_token_ids)
'''


def w(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")


def synthetic_frozen_sources(out: Path) -> dict[str, str]:
    """Write the synthetic frozen FreeToken sources; return {rel:
    sha256} computed AFTER write (the mutation suite binds these pins
    into the frozen-pins seam). Paths arefakeroot-relative (out IS the
    arm-c evidence dir; rel paths keep their full repo-relative form
    so they can be bound directly into the pins seam)."""
    import hashlib
    prefix = ("docs/implementation/r6-successor-dense-full-integration-"
              "117/evidence/arm-c/")
    files = {
        f"{prefix}frozen-freetoken/924cd22e/python/freetoken/"
        "research/r5b_epochs.py": SYNTHETIC_EPOCHS,
        f"{prefix}frozen-freetoken/924cd22e/benchmarks/"
        "inferswarm_r6/coordinator.py": SYNTHETIC_COORDINATOR,
        f"{prefix}frozen-freetoken/924cd22e/benchmarks/"
        "inferswarm_r6/xc_strategy.py": SYNTHETIC_STRATEGY,
    }
    pins = {}
    for rel, text in files.items():
        assert rel.startswith(prefix)
        path = out / rel[len(prefix):]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        pins[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return pins


def build(out: Path) -> dict:
    """Builds the fakeroot evidence; returns the frozen-source pins so
    callers (the mutation suite) can install them into the seam."""
    frozen_file_entry = {
        "git_blob_sha_at_freeze": "0" * 40,
        "sha256_at_freeze": "1" * 64,
        "sha256_at_campaign_commit": "1" * 64,
        "sha256_current_head": "2" * 64,
        "status_at_head": "changed_after_freeze",
    }
    w(out / "pre-execution-authority-audit.json", {
        "schema": "inferswarm.issue117.arm-c."
                  "pre-execution-authority-audit/2",
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
        "comparator_modification_forensics": {
            "direct6_completed_utc":
                "2026-09-09T10:28:36.248255+00:00",
            "staged_driver_mtime_utc":
                "2026-09-09T10:43:07.698991040+00:00",
            "direct7_first_observed_utc":
                "2026-09-09T10:49:28.249147+00:00",
            "source": "synthetic",
        },
        "post_audit_correction_allowlist": {
            "scripts/issue117_arm_c_blocker_reducer.py": {
                "role": "correction /2 blocker reducer (synthetic)",
                "sha256": "3" * 64},
        },
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

    def attempt(aid, order, cb_emitted, gpu, valid, classification,
                timestamps, code_identity=None, historical=None):
        entry = {
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
            "observed_timestamps": timestamps,
            "code_identity": code_identity or {},
            "evidence_bindings": {},
            "retained_validity_flag": valid,
            "campaign_classification": classification,
        }
        if historical:
            entry["historical_validity_classification"] = historical
        return entry

    ts = lambda h, m=0: (  # noqa: E731 - synthetic timestamp helper
        f"2026-09-09T{h:02d}:{m:02d}:00.000000+00:00")
    attempts = [
        attempt("armc-direct-5", 6, False, True, False,
                "pre-stop infrastructure (non-correctness-bearing)",
                {"transcript_first_observed_utc": ts(8, 26)}),
        attempt(DIRECT_ATTEMPT, 7, True, True, False,
                "correctness-bearing physical observation; invocation "
                "consistent with the frozen single-shot comparator; "
                "exact staged driver bytes unknown / not retained; "
                "part of the evidence that exposes the frozen "
                "comparator defect; NOT accepted terminal comparator "
                "evidence",
                {"transcript_first_observed_utc": ts(10, 28),
                 "completion_evidence_utc":
                     "2026-09-09T10:28:36.248255+00:00"},
                code_identity={"driver_bytes": UNKNOWN},
                historical="invalid (synthetic post-hoc classification)"),
        attempt("armc-ordinary-1", 8, True, True, True,
                "correctness-bearing ordinary-path observation; part of "
                "the frozen-methodology campaign evidence; inadmissible "
                "to a semantic PASS/FAIL because the comparator "
                "methodology was defective",
                {"transcript_first_observed_utc": ts(10, 38),
                 "completion_evidence_utc":
                     "2026-09-09T10:38:52.091031+00:00"},
                historical="valid (synthetic authored classification)"),
        attempt("armc-direct-7", 9, False, False, False,
                "post-observation/post-methodology-revision diagnostic; "
                "inadmissible to the terminal campaign",
                {"transcript_first_observed_utc": ts(10, 49)}),
        attempt("armc-direct-8", 10, False, True, False,
                "post-observation/post-methodology-revision diagnostic; "
                "inadmissible to the terminal campaign",
                {"transcript_first_observed_utc": ts(10, 56)}),
        attempt("armc-direct-9", 11, True, True, True,
                "post-observation/post-methodology-revision diagnostic; "
                "inadmissible to the terminal campaign",
                {"transcript_first_observed_utc": ts(11, 9),
                 "completion_evidence_utc":
                     "2026-09-09T11:09:05.413012+00:00"}),
    ]
    w(out / "attempt-lineage.json", {
        "schema": "inferswarm.issue117.arm-c.attempt-lineage/3",
        "attempts": attempts,
    })
    w(out / "invalid-attempt-6" / "direct-run.json", {
        "schema": "inferswarm.issue117.arm-c.direct-run/1",
        "attempt_id": DIRECT_ATTEMPT,
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
    # ordinary-path physical shape: 24 sessions, each an 8-position
    # committed ledger with per-position attribution; the epoch's plan
    # provenance cites the direct-6 ranking record
    w(out / "ordinary-campaign.json", {
        "schema": "inferswarm.issue117.arm-c.ordinary-campaign/1",
        "attempt_id": "armc-ordinary-1",
        "case_count": 24,
        "ok_count": 24,
        "completed_at_ns": 1788950332091031330,
        "records": [],
    })
    w(out / "coordinator-report.json", {
        "schema": "inferswarm.r6.coordinator-report/1 (synthetic)",
        "epochs": [{
            "epoch_id": "research-generation-0:synthetic",
            "execution_plan": {"evidence_audit": [{
                "provenance": {"attempt_id": DIRECT_ATTEMPT}}]},
        }],
        "sessions": [
            {"session_id": i,
             "generated_token_ids": [1] * 8,
             "committed_epoch_ids": ["e"] * 8,
             "committed_plan_digests": ["p"] * 8,
             "latest_committed_boundary": {"committed_position": 8}}
            for i in range(1, 25)],
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
    return synthetic_frozen_sources(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    pins = build(Path(args.out))
    print(json.dumps({"built": args.out,
                      "frozen_source_pins": pins}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
