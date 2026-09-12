#!/usr/bin/env python3
"""Issue #153 Arm-C remediation: producer delta + applicability record.

Mechanically derives the behavioral delta between the accepted #117
producer (924cd22e) and the remediation candidate: exact changed file
hashes, the classification, the explicit unchanged list, and the
applicability caveats for the future Arm-C requalification.  Fails
closed if the delta is not chunk-selection-only.

CPU-only, stdlib-only. No model execution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACCEPTED_PRODUCER = "924cd22ea081f6d4ed471016faf01d427fc5b0d2"
STARTING_RESEARCH = "b05564a7f3f7ca1b141d54842357ff2624dc6a19"
SCHEMA = "inferswarm.issue117.arm-c-remediation.producer-delta/1"

# behavioral surface the remediation is allowed to touch (chunk policy
# seam only).  Anything else changing under benchmarks/ or python/ is a
# hard failure of this builder.
ALLOWED_CHANGED = {
    "benchmarks/inferswarm_r6/stage_chain.py",
    "benchmarks/inferswarm_r6/two_stage.py",
    "benchmarks/inferswarm_r6/last_stage_service.py",
    "python/freetoken/research/prefill_partition.py",
    "tests/research/test_issue117_arm_c_remediation.py",
}

# the frozen strategy constants must be byte-identical
MUST_BE_IDENTICAL = [
    "benchmarks/inferswarm_r6/strategy.py",
    "benchmarks/inferswarm_r6/stage_runtime.py",
    "benchmarks/inferswarm_r6/xc_strategy.py",
    "benchmarks/inferswarm_r6/coordinator.py",
    "benchmarks/inferswarm_r6/chain_runtime.py",
    "benchmarks/inferswarm_r6/node_agent.py",
    "python/freetoken/research/r5b_epochs.py",
    "python/freetoken/research/xc_coordinator.py",
    "python/freetoken/research/xc_wire.py",
    "python/freetoken/research/r4_wire.py",
    "python/freetoken/research/r5a_serving.py",
    "python/freetoken/research/r3_planner.py",
]


def changed_paths(repo: Path, frm: str, to: str) -> list[str]:
    out = subprocess.check_output(
        ["git", "-C", str(repo), "diff", "--name-only", frm, to], text=True
    )
    return sorted(line for line in out.splitlines() if line)


def blob_sha(repo: Path, commit: str, path: str) -> str | None:
    res = subprocess.run(
        ["git", "-C", str(repo), "show", f"{commit}:{path}"],
        capture_output=True,
    )
    if res.returncode != 0:
        return None
    return hashlib.sha256(res.stdout).hexdigest()


def build(repo: Path, remediated_commit: str) -> dict:
    changed = changed_paths(repo, ACCEPTED_PRODUCER, remediated_commit)
    unexpected = [p for p in changed if p not in ALLOWED_CHANGED]
    if unexpected:
        raise SystemExit(
            f"producer delta exceeds the chunk-policy seam: {unexpected}")
    drifted = [
        p for p in MUST_BE_IDENTICAL
        if blob_sha(repo, ACCEPTED_PRODUCER, p)
        != blob_sha(repo, remediated_commit, p)
    ]
    if drifted:
        raise SystemExit(f"frozen surface drifted: {drifted}")

    hashes = {
        p: {
            "accepted_sha256": blob_sha(repo, ACCEPTED_PRODUCER, p),
            "remediated_sha256": blob_sha(repo, remediated_commit, p),
        }
        for p in sorted(ALLOWED_CHANGED)
    }
    return {
        "schema": SCHEMA,
        "classification": "UNNECESSARY_PARTITION_POLICY",
        "accepted_producer": ACCEPTED_PRODUCER,
        "starting_research_base": STARTING_RESEARCH,
        "remediation_producer": remediated_commit,
        "changed_runtime_files": hashes,
        "behavioral_delta": (
            "chunk-selection policy only: a logical extend-prefill unit "
            "that fits the admitted capacity (frozen boundary contract "
            "prefill_chunk_rows = 64) now provably remains ONE backend "
            "call on the canonical chain seam and both two-stage/chain "
            "generate() loops; over-limit units partition deterministically "
            "at the same admitted capacity"
        ),
        "explicitly_unchanged": [
            "model math / weights / checkpoint identity",
            "frozen geometry (boundary planes, row width, prefill_chunk_rows)",
            "strategy constants (PREFILL_CHUNK untouched)",
            "planner semantics / candidate identity",
            "tokenizer, subject, qualification doctrine",
            "decode path",
            "session/request identity, plan digest surfaces",
            "fencing / epoch / position attribution",
        ],
        "no_case_specific_tuning": (
            "AST-level source audit in the remediation test suite and the "
            "phase-0 inventory builder: no case IDs, no regime nouns, no "
            "accepted divergent token ids in the remediation seam"
        ),
        "applicability_caveat": (
            "This producer is a CANDIDATE, not accepted execution "
            "authority. A fresh Arm-C requalification campaign requires a "
            "separately authorized issue that freezes this producer "
            "externally, audits the delta against the accepted subject, "
            "and authorizes correctness-bearing execution. The six "
            "historical divergent cases may serve as known regression "
            "identities only and may not be the sole basis for a pass."
        ),
        "non_claims": [
            "no GPU/model execution occurred",
            "CPU/static policy proof does not establish the GPU numerical "
            "result of a future campaign",
            "no ISSUE117_ARM_C_ORDINARY_SERVING_PASS or FAIL is derived "
            "here",
            "no h109-* material was accessed",
        ],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freetoken-repo", default=str(ROOT.parent / "FreeToken"))
    parser.add_argument("--remediation-commit", default=None)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    repo = Path(args.freetoken_repo).resolve()
    commit = args.remediation_commit
    if commit is None:
        commit = subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
        ).strip()
    record = build(repo, commit)
    rendered = json.dumps(record, indent=2, sort_keys=True) + "\n"
    if args.write:
        target = (
            ROOT
            / "docs/implementation/r6-successor-dense-full-integration-117/"
            "remediation/evidence/producer-delta.json"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered)
        print(f"wrote {target}")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
