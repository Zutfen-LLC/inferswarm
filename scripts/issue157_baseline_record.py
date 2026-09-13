#!/usr/bin/env python3
"""Issue #157 Phase-2 baseline-reproduction record producer.

Regenerates baseline-reproduction.json in the #157 evidence bundle
from the RETAINED fresh BASE run record bytes (never by hand):
observation lists, boundary digests, chunk-1 digest summaries, and
the tooling provenance block — including the supersession history of
the pre-freeze BASE run i157-BASE-1789261211 (2026-09-13
physical-authority correction).

Inputs (fail-closed):
  --source-run   path to the fresh i157-BASE-*.json driver record
                 (executed under the frozen execution-bearing tool
                 bytes; verified against the authority pin before
                 anything is written)
  --prev-record  path to the previous committed
                 baseline-reproduction.json (its physical
                 observations are PRESERVED VERBATIM as the
                 superseded historical record; nothing is edited or
                 concealed)

The emitted record keeps the same schema
(inferswarm.issue157.baseline-reproduction/1) the conclusions reducer
consumes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

SCHEMA = "inferswarm.issue157.baseline-reproduction/1"
DIAGNOSTIC_ONLY = "DIAGNOSTIC_ONLY"
AUTHORITY_INSTRUMENTATION_SHA256 = "sha256:" + "00a1c2c1452f87ca56289eeb3716e9cd08ba1c5a36e7d06ac6abdb79283024fc"
PRODUCER_PIN = "55e8baaebabe67aeb967d4bd407ef26696933104"
OLD_RUN_ID = "i157-BASE-1789261211"

ANCHOR_A = "c109-04-02-047"
ANCHOR_B = "c109-04-06-074"
STABLE_CONTROL = "c109-03-04-003"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", required=True)
    parser.add_argument("--prev-record", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    run_path = Path(args.source_run)
    prev_path = Path(args.prev_record)
    out_path = Path(args.out)
    run = json.loads(run_path.read_text())
    prev = json.loads(prev_path.read_text())

    # ---- fail-closed authority checks on the fresh run -----------
    if run.get("classification") != DIAGNOSTIC_ONLY:
        print("FAIL: source run is not DIAGNOSTIC_ONLY")
        return 1
    if run.get("probe") != "BASE":
        print("FAIL: source run is not a BASE probe")
        return 1
    if not (run.get("run_id") or "").startswith("i157-BASE-"):
        print("FAIL: source run id is not a fresh i157-BASE-* id")
        return 1
    if run.get("run_id") == OLD_RUN_ID:
        print("FAIL: source run is the OLD pre-freeze run itself")
        return 1
    if run.get("producer") != PRODUCER_PIN:
        print(f"FAIL: producer {run.get('producer')} != {PRODUCER_PIN}")
        return 1
    instrumentation = run["driver"]["instrumentation_sha256"]
    if f"sha256:{instrumentation}" != AUTHORITY_INSTRUMENTATION_SHA256:
        print(
            "FAIL: source run instrumentation bytes are not the "
            "frozen execution-bearing authority (2611ee1): "
            f"{instrumentation}"
        )
        return 1
    observations = run.get("observations") or []
    if len(observations) != 3:
        print(f"FAIL: expected 3 realizations, got {len(observations)}")
        return 1

    # ---- physical observations, copied verbatim from the run -----
    def case_rows(case_id):
        rows = []
        for obs in observations:
            if case_id not in obs:
                print(f"FAIL: realization missing case {case_id}")
                raise SystemExit(1)
            rows.append({
                "realization": obs["realization"],
                "repeats": [
                    {
                        "repeat": rep["repeat"],
                        "committed_step0": rep["committed_step0"],
                        "speculative_step1": rep["speculative_step1"],
                        "boundary_digests": rep["boundary_digests"],
                    }
                    for rep in obs[case_id]
                ],
            })
        return rows

    anchor_a = case_rows(ANCHOR_A)
    anchor_b = case_rows(ANCHOR_B)
    stable = case_rows(STABLE_CONTROL)

    def chunk1_digests(rows):
        digests = []
        for row in rows:
            for rep in row["repeats"]:
                for bd in rep["boundary_digests"]:
                    if bd["position"] == 0 and bd["stage_out"] == 0:
                        digests.append(bd["sha256"])
        return digests

    a_c1 = chunk1_digests(anchor_a)
    b_c1 = chunk1_digests(anchor_b)
    c_c1 = chunk1_digests(stable)

    prev_binding = prev.get("accepted_137_binding") or {}
    # recompute the recurrence summary from THIS run's anchor-A
    # observations (the reducer independently re-derives it and fails
    # closed on disagreement — never carry a stale derived summary)
    accepted_seq = prev_binding.get(
        "anchor_a_accepted_in_session_values") or []
    accepted = sorted(set(accepted_seq))
    a_tokens = [
        rep["committed_step0"]
        for row in anchor_a for rep in row["repeats"]
    ]
    binding = dict(prev_binding)
    binding["recurred_in_this_baseline"] = sorted(
        {v for v in accepted if v in set(a_tokens)})
    record = {
        "schema": SCHEMA,
        "classification": DIAGNOSTIC_ONLY,
        "producer": run["producer"],
        "source_run": run["run_id"],
        "source_run_sha256": sha256_file(run_path),
        "anchor_a": anchor_a,
        "anchor_b": anchor_b,
        "stable_control": stable,
        "anchor_a_chunk1_boundary_digests": a_c1,
        "anchor_b_chunk1_boundary_digests": b_c1,
        "stable_control_single_call_boundary_digests": c_c1,
        "accepted_137_binding": binding,
        "tooling_provenance": {
            "executed_under_committed_2611ee1_bytes": True,
            "instrumentation_sha256_at_execution":
                AUTHORITY_INSTRUMENTATION_SHA256,
            "execution_bearing_freeze_instrumentation_sha256":
                AUTHORITY_INSTRUMENTATION_SHA256,
            "driver_sha256_at_execution":
                f"sha256:{run['driver']['sha256']}",
            "binding_module_sha256_at_execution":
                run["driver"]["binding_module_sha256"],
            "sitecustomize_sha256_at_execution":
                f"sha256:{run['driver']['sitecustomize_sha256']}",
            "note": (
                "Authoritative Phase-2 BASE (2026-09-13 "
                "physical-authority correction): executed under the "
                "committed execution-bearing tool bytes (2611ee1), "
                "node bytes sha256-verified equal to the authority "
                "pins before and after the run. Supersedes "
                f"{OLD_RUN_ID} for Phase-2 authority."
            ),
            "superseded_run": {
                "run_id": OLD_RUN_ID,
                "disposition": (
                    "retained historical evidence only — preserved "
                    "verbatim in the launch ledger and in git history "
                    "(baseline-reproduction.json at 3518480); never "
                    "deleted, rewritten, relabeled, or concealed"
                ),
                # frozen constant (adversarial-review Lane B P2):
                # never derived from --prev-record, so re-running this
                # producer with the CURRENT record as prev cannot
                # erode the pre-freeze disclosure
                "instrumentation_sha256_at_execution":
                    "sha256:98fa2a80d893dcae20f373d94064d55c9ab2314"
                    "cb868fbe9000e166d667d8d77",
                "superseded_because": (
                    "executed under uncommitted pre-freeze "
                    "instrumentation bytes; cannot carry Phase-2 "
                    "reproduction authority under the corrected "
                    "reducer gate"
                ),
            },
        },
    }
    out_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(f"[issue157-baseline-record] wrote {out_path}")
    print(f"  source_run={record['source_run']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
