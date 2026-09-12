#!/usr/bin/env python3
"""Issue #153 Arm-C remediation: producer delta + applicability record.

Mechanically derives the behavioral delta between the accepted #117
producer (924cd22e) and the remediation candidate: exact changed file
hashes, the corrected classification (Branch B
BACKEND_REQUIRES_MULTI_CHUNK, terminal ISSUE117_ARM_C_REMEDIATION_BLOCKED),
the per-failing-population remediation answers, the explicit unchanged
list, and the applicability caveats.  Fails closed on any change outside
the remediation seam, on any drift of the frozen surface, and — after
the maintainer correction — on a nanosecond-timing regression in the
changed runtime files.

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
SCHEMA = "inferswarm.issue117.arm-c-remediation.producer-delta/2"
REVIEWED_HEAD_SUPERSEDED = "5e6bca586f6d960ac863f63cf9e9232ed80e362b"

# behavioral surface the remediation is allowed to touch (chunk policy
# seam, capacity-ownership derivation, nanosecond timing restoration,
# and the proof module/tests).  Anything else changing under benchmarks/
# or python/ is a hard failure of this builder.
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

# the accepted failing population (from the hash-pinned #137 record):
# every divergent case's correctness-bearing prompt length
FAILING_POPULATION_ROWS = [65, 66, 67]


def changed_paths(repo: Path, frm: str, to: str) -> list[str]:
    out = subprocess.check_output(
        ["git", "-C", str(repo), "diff", "--name-only", frm, to], text=True
    )
    return sorted(line for line in out.splitlines() if line)


def git_out(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), *args], text=True
    ).strip()


def blob_bytes(repo: Path, commit: str, path: str) -> bytes | None:
    res = subprocess.run(
        ["git", "-C", str(repo), "show", f"{commit}:{path}"],
        capture_output=True,
    )
    if res.returncode != 0:
        return None
    return res.stdout


def blob_sha(repo: Path, commit: str, path: str) -> str | None:
    data = blob_bytes(repo, commit, path)
    return None if data is None else hashlib.sha256(data).hexdigest()


def audit_changed_runtime_files(repo: Path, commit: str) -> dict:
    """Mechanical out-of-scope-behavior audit of every changed runtime
    file.  Rejects (fail-closed) any changed runtime file that:
    - contains a bare ``time.perf_counter()`` call (unit-drift class the
      maintainer found on the reviewed head), or
    - mentions the wire service from a runtime module (import-cycle
      class), or
    - carries case/regime/model special-casing nouns (AST-stripped).
    """
    import ast

    audit = {}
    for rel in sorted(ALLOWED_CHANGED):
        if not rel.startswith(("benchmarks/", "python/")):
            continue
        data = blob_bytes(repo, commit, rel)
        if data is None:
            raise SystemExit(f"changed runtime file absent at {commit}: {rel}")
        source = data.decode()
        if "time.perf_counter()" in source:
            raise SystemExit(
                f"out-of-scope behavior: bare perf_counter() in {rel} "
                "(nanosecond timing contract violated)"
            )
        if "last_stage_service" in source and not rel.endswith(
            "last_stage_service.py"
        ):
            raise SystemExit(
                f"out-of-scope dependency: {rel} references the wire service"
            )
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module,
                       ast.ClassDef)
            ):
                if (node.body and isinstance(node.body[0], ast.Expr)
                        and isinstance(node.body[0].value, ast.Constant)
                        and isinstance(node.body[0].value.value, str)):
                    node.body = node.body[1:] or [ast.Pass()]
        dumped = ast.dump(tree).lower()
        for token in ("c109", "regime4", "regime-4", "h109"):
            if token in dumped:
                raise SystemExit(
                    f"out-of-scope special-casing: {token!r} in {rel}"
                )
        audit[rel] = "clean"
    return audit


def build(repo: Path, remediated_commit: str) -> dict:
    changed = changed_paths(repo, ACCEPTED_PRODUCER, remediated_commit)
    unexpected = [p for p in changed if p not in ALLOWED_CHANGED]
    if unexpected:
        raise SystemExit(
            f"producer delta exceeds the remediation seam: {unexpected}")
    drifted = [
        p for p in MUST_BE_IDENTICAL
        if blob_sha(repo, ACCEPTED_PRODUCER, p)
        != blob_sha(repo, remediated_commit, p)
    ]
    if drifted:
        raise SystemExit(f"frozen surface drifted: {drifted}")
    audit = audit_changed_runtime_files(repo, remediated_commit)

    two_stage = blob_bytes(
        repo, remediated_commit, "benchmarks/inferswarm_r6/two_stage.py"
    ).decode()
    ns_timing_restored = (
        "t = time.perf_counter_ns()" in two_stage
        and "prefill_ns += time.perf_counter_ns() - t" in two_stage
    )
    if not ns_timing_restored:
        raise SystemExit("nanosecond prefill timing not restored in two_stage")

    hashes = {
        p: {
            "accepted_sha256": blob_sha(repo, ACCEPTED_PRODUCER, p),
            "remediated_sha256": blob_sha(repo, remediated_commit, p),
        }
        for p in sorted(ALLOWED_CHANGED)
    }

    return {
        "schema": SCHEMA,
        "classification": "BACKEND_REQUIRES_MULTI_CHUNK",
        "terminal": "ISSUE117_ARM_C_REMEDIATION_BLOCKED",
        "superseded_reviewed_head": REVIEWED_HEAD_SUPERSEDED,
        "accepted_producer": ACCEPTED_PRODUCER,
        "starting_research_base": STARTING_RESEARCH,
        "remediation_producer": remediated_commit,
        "changed_runtime_files": hashes,
        "changed_runtime_files_audit": audit,
        "behavioral_delta": (
            "for legal (<= capacity) units only: chunk-selection policy "
            "(capacity-derived single call, no drifting literals; the "
            "legacy two_stage 32 default is gone).  For the accepted "
            "failing population (65-67 rows) the execution path is "
            "UNCHANGED (64 + remainder, same requests as the accepted "
            "hand-literal loop) — remediation-only in the sense that no "
            "other behavior changed; the failing path's instability is "
            "NOT remediated"
        ),
        "failing_population_remediation_answers": {
            str(rows): {
                "accepted_execution_partition": [[0, 64], [64, rows - 64]],
                "corrected_execution_partition": [[0, 64], [64, rows - 64]],
                "behavior_changed": False,
                "why": (
                    "single-call is illegal under the frozen 64-row "
                    "boundary/wire contract; no CPU-provable backend/"
                    "state defect exists in the required multi-chunk "
                    "extend path, so branch-B option 1 is unavailable "
                    "without new physical evidence"
                ),
            }
            for rows in FAILING_POPULATION_ROWS
        },
        "timing_unit_correction": (
            "two_stage prefill accumulator restored to perf_counter_ns on "
            "both sides (prefill_ns is nanoseconds); enforced "
            "mechanically by this builder and by a structural AST "
            "regression contract in the FreeToken suite"
        ),
        "capacity_ownership": (
            "strategy (frozen constant owner) -> stage_chain + two_stage "
            "(chunk policy) and strategy -> last_stage_service (wire "
            "bound); the wire service no longer imports the chain "
            "runtime; no runtime module imports the wire service"
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
            "AST-level source audit in the remediation test suite, the "
            "phase-0 inventory builder, and this builder's "
            "changed-runtime-files audit: no case IDs, no regime nouns, "
            "no accepted divergent token ids in the remediation seam"
        ),
        "applicability_caveat": (
            "This producer is a CANDIDATE, not accepted execution "
            "authority, and it does NOT remediate the accepted Arm-C "
            "failure: the terminal is BLOCKED.  Fresh Arm-C "
            "requalification MUST NOT be authorized from this producer. "
            "The required next remediation slice is a deeper authority "
            "(physical execution or contract change) targeting the "
            "multi-chunk extend path's execution-level instability "
            "localized by #137 to the second prefill chunk inside "
            "stage 1 at/before global layer 1."
        ),
        "non_claims": [
            "no GPU/model execution occurred",
            "CPU/static policy proof does not establish the GPU numerical "
            "result of a future campaign",
            "no ISSUE117_ARM_C_ORDINARY_SERVING_PASS or FAIL is derived "
            "here",
            "no h109-* material was accessed",
            "no remediation of the accepted 65-67 failing execution path "
            "is claimed (terminal is BLOCKED)",
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
