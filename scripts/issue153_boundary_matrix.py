#!/usr/bin/env python3
"""Issue #153 Arm-C remediation: boundary-matrix evidence builder.

Runs the focused remediation boundary matrix DIRECTLY from the FreeToken
remediation worktree bytes (imports the remediation producer's own
policy module at the pinned SHA) and records the observed matrix plus
the suite results.  CPU-only; the FreeToken worktree must be clean at
the remediation commit.

Corrected (maintainer review): the PRIMARY matrix is the accepted
failing population 65/66/67 (classified multi-chunk under the frozen
contract, execution partition equal to the accepted 64+remainder path);
the 1/31/32/33/53/63/64 legal-single-chunk matrix and the 53-row C2
control are RETAINED as secondary/causal-control evidence.  This proves
policy selection only; it makes no claim about GPU numerical results.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "inferswarm.issue117.arm-c-remediation.boundary-matrix/2"
ACCEPTED_FAILING_POPULATION = [65, 66, 67]
LEGAL_SIZES = [1, 31, 32, 33, 53, 63, 64]
OVER_LIMIT = [65, 66, 67, 85, 128, 129]


def build_matrix(python_bin: str, env: dict) -> dict:
    code = r"""
import json, sys
sys.path.insert(0, "python")
from freetoken.research.prefill_partition import plan_prefill_partitions
from benchmarks.inferswarm_r6.stage_chain import admitted_prefill_rows
cap = admitted_prefill_rows()
matrix = {
    "admitted_capacity": cap,
    "accepted_failing_population": {
        str(n): [list(p) for p in plan_prefill_partitions(n, cap)]
        for n in [65, 66, 67]
    },
    "legal_single_chunk": {
        str(n): [list(p) for p in plan_prefill_partitions(n, cap)]
        for n in [1, 31, 32, 33, 53, 63, 64]
    },
    "over_limit": {
        str(n): [list(p) for p in plan_prefill_partitions(n, cap)]
        for n in [65, 66, 67, 85, 128, 129]
    },
    "historical_causal_control": {
        "unit_rows": 53,
        "single_chunk_53": [list(p) for p in plan_prefill_partitions(53, cap)],
        "multi_chunk_32_21_rejected": True,
        "role": (
            "causal CONTROL on a stable 53-row input (single call "
            "deterministic, 32+21 varied in #137 probe C2); NOT a "
            "substitute for the 65-67 failing population"
        ),
    },
}
print(json.dumps(matrix))
"""
    out = subprocess.check_output(
        [python_bin, "-c", code],
        cwd=str(env["repo"]),
        env={"PYTHONPATH": str(env["repo"] / "python"), "PATH": "/usr/bin:/bin"},
        text=True,
    )
    return json.loads(out)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freetoken-repo", default=str(ROOT.parent / "FreeToken"))
    parser.add_argument("--remediation-commit", default=None)
    parser.add_argument("--python", default=None)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    repo = Path(args.freetoken_repo).resolve()
    commit = args.remediation_commit
    if commit is None:
        commit = subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
        ).strip()
    status = subprocess.check_output(
        ["git", "-C", str(repo), "status", "--porcelain"], text=True
    ).strip()
    if status:
        raise SystemExit(f"FreeToken worktree dirty: {status!r}")
    head = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()
    if head != commit:
        raise SystemExit(f"worktree HEAD {head} != {commit}")

    python_bin = args.python or str(repo / ".venv/bin/python")
    matrix = build_matrix(python_bin, {"repo": repo})

    # focused suite result (recorded verbatim)
    suite = subprocess.run(
        [python_bin, "-m", "pytest",
         "tests/research/test_issue117_arm_c_remediation.py", "-q"],
        cwd=str(repo),
        env={"PYTHONPATH": str(repo / "python"), "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True,
    )
    tail = suite.stdout.strip().splitlines()[-1] if suite.stdout.strip() else ""

    record = {
        "schema": SCHEMA,
        "remediation_producer": commit,
        "worktree_clean": True,
        "proves": (
            "chunk-policy classification of the exact accepted failing "
            "population (65/66/67 -> multi-chunk, unchanged accepted "
            "partition) plus policy selection on the canonical seam"
        ),
        "does_not_prove": (
            "GPU numerical results of any future campaign; remediation "
            "of the 65-67 extend-path instability (terminal is BLOCKED)"
        ),
        "boundary_matrix": matrix,
        "failing_population_answers": {
            str(rows): {
                "accepted_execution_partition": [[0, 64], [64, rows - 64]],
                "corrected_execution_partition": matrix[
                    "accepted_failing_population"
                ][str(rows)],
                "single_call_legal_under_frozen_contract": False,
                "behavior_changed": (
                    matrix["accepted_failing_population"][str(rows)]
                    != [[0, 64], [64, rows - 64]]
                ),
            }
            for rows in ACCEPTED_FAILING_POPULATION
        },
        "legal_single_chunk_expected": {
            str(n): [[0, n]] for n in LEGAL_SIZES
        },
        "focused_suite": {
            "command": "pytest tests/research/test_issue117_arm_c_remediation.py -q",
            "exit_code": suite.returncode,
            "summary": tail,
        },
    }
    # verify every legal size stayed one call; the failing population is
    # exactly the accepted 64+remainder partition with no behavior change
    for n in LEGAL_SIZES:
        observed = matrix["legal_single_chunk"][str(n)]
        assert observed == [[0, n]], (n, observed)
    for rows in ACCEPTED_FAILING_POPULATION:
        observed = matrix["accepted_failing_population"][str(rows)]
        assert observed == [[0, 64], [64, rows - 64]], (rows, observed)
        assert record["failing_population_answers"][str(rows)]["behavior_changed"] is False
    assert matrix["historical_causal_control"]["single_chunk_53"] == [[0, 53]]
    assert suite.returncode == 0, tail

    rendered = json.dumps(record, indent=2, sort_keys=True) + "\n"
    if args.write:
        target = (
            ROOT
            / "docs/implementation/r6-successor-dense-full-integration-117/"
            "remediation/evidence/boundary-matrix.json"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered)
        print(f"wrote {target}")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
