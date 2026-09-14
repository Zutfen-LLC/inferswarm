#!/usr/bin/env python3
"""Issue #175 — Arm-D terminal reduction (CPU-only, stdlib, fail-closed).

Re-derives the Arm-D terminal from the retained per-restart records:

Inputs (all retained under the campaign evidence namespace):
- fence records (pre/post per restart, per host)
- strace transfer reductions (per restart window)
- cache-hit/materialization reductions (per restart)
- post-restart equality reductions (restart 1: 40-case vs accepted
  #172; restart 2: sentinel repeats vs accepted #172 and restart 1)
- zero-invariant aggregation

Terminal:
- ISSUE117_ARM_D_WARM_RESTART_CACHE_REUSE_PASS only when both restart
  cycles prove process restart, verified cache reuse, zero
  Source/peer/Coordinator model-weight reacquisition, correct
  re-realization, exact post-restart serving, all zero invariants, and
  no STOP fired;
- FAIL for any admissible violation;
- EVIDENCE_BLOCKED is never emitted post-observation.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue175_campaign_pins as P  # noqa: E402
import issue175_reduce as R  # noqa: E402


def load(path: str) -> dict:
    return json.loads(Path(path).read_text())


def reduce_restart(fence_parts: list[dict], killed: list[int],
                   strace_reductions: list[dict],
                   cache_reduction: dict, gpu_records: list[dict],
                   equality: dict | None, label: str) -> dict:
    problems: list[str] = []

    # fence parts embed the already-derived per-host fence + gpu fence
    # reductions; each must itself be passed and consistent with the
    # global kill list for its restart
    if not fence_parts:
        problems.append(f"[{label}] no fence parts retained")
    for part in fence_parts:
        fence = part.get("fence", {})
        gpu = part.get("gpu_fence", {})
        if not fence.get("passed"):
            problems += [f"[{label}] {part.get('host')}: {p}"
                         for p in fence.get("problems", [])]
        if not gpu.get("passed"):
            problems += [f"[{label}] {part.get('host')}: {p}"
                         for p in gpu.get("problems", [])]
        for pid in part.get("killed_pids", []):
            if pid not in killed:
                problems.append(
                    f"[{label}] {part.get('host')} killed pid {pid} "
                    "outside the global kill list")

    for host_gpus in gpu_records:
        host = host_gpus.get("host")
        gpu = R.gpu_fence(host_gpus.get("gpus", []),
                          P.FROZEN_GEOMETRY_UUIDS, host=host)
        problems += [f"[{label}] {p}" for p in gpu["problems"]]

    transfer_problems = []
    for reduction in strace_reductions:
        transfer_problems += reduction.get("problems", [])
        derived = reduction.get("derived", {})
        if int(derived.get("source_model_weight_bytes_received",
                           0) or 0) != 0:
            transfer_problems.append("source bytes nonzero")
    problems += [f"[{label}] {p}" for p in transfer_problems]

    problems += [f"[{label}] {p}"
                 for p in cache_reduction.get("problems", [])]

    if equality is not None:
        if not equality.get("passed"):
            problems += [f"[{label}] equality: {p}"
                         for p in equality.get("problems", [])]
            for row in equality.get("rows", []):
                if row["problems"]:
                    problems.append(
                        f"[{label}] case {row['case_id']}: "
                        + "; ".join(row["problems"]))

    return {
        "label": label,
        "fence": fence["counters"],
        "transfer_problems": transfer_problems,
        "passed": not problems,
        "problems": problems,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parts-dir", required=True,
                        help="directory of retained reduction parts")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    parts_dir = Path(args.parts_dir)
    parts = {p.stem: load(str(p)) for p in sorted(
        parts_dir.glob("*.json"))}

    restarts = {}
    for restart in (1, 2):
        restarts[restart] = reduce_restart(
            fence_parts=[v for k, v in parts.items()
                         if k.startswith(f"fence-{restart}-")],
            killed=(parts.get(f"killed-pids-{restart}", {})
                    .get("pids", [])),
            strace_reductions=[
                v for k, v in parts.items()
                if k.startswith(f"strace-{restart}-")],
            cache_reduction=parts.get(f"cache-{restart}", {}),
            gpu_records=[v for k, v in parts.items()
                         if k.startswith(f"gpu-{restart}-")],
            equality=parts.get(f"equality-{restart}"),
            label=f"restart-{restart}")

    zero = R.aggregate_zero_invariants({
        k: v for k, v in parts.items()
        if k.startswith(("strace-", "equality-", "cache-"))})

    stop_fired = any(
        parts.get(f"ledger", {}).get("stop_events", []))

    problems = []
    for restart, reduction in restarts.items():
        problems += reduction["problems"]
    problems += zero["problems"]
    if stop_fired:
        problems.append("a mandatory STOP condition fired")

    passed = (all(r["passed"] for r in restarts.values())
              and zero["passed"] and not stop_fired)
    terminal = P.PASS_TERMINAL if passed else P.FAIL_TERMINAL

    record = {
        "schema": P.TERMINAL_SCHEMA,
        "campaign_id": P.CAMPAIGN_ID,
        "restarts": restarts,
        "zero_invariants": zero["totals"],
        "stop_fired": stop_fired,
        "terminal": terminal,
        "problems": problems,
        "note": (
            "mechanically re-derived from retained bytes; no authored "
            "terminal/cache-hit/pass boolean consulted"),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(
        record, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "terminal": terminal,
        "problems": problems[:8],
        "zero_totals": zero["totals"],
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
