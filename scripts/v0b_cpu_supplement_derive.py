#!/usr/bin/env python3
"""Derive the V0-B CPU-supplemental summary from retained raw runs.

Reads docs/investigations/vulkan-v0-b/results/cpu-supplemental/v0b-cpu-*/
run.json (+ retained stdout), keeps ONLY runs whose own record proves
CPU-only execution (correction-1 rule), validates one pp512 + one tg128
aggregate row per run, and derives the arm medians.

Writes results/cpu-supplemental/summary.json (or refreshes the one in
results/economics.json via scripts/v0b_economics.py on the next run).
Fail-closed: any unproven or malformed run is reported, never averaged.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CPU_DIR = REPO / "docs/investigations/vulkan-v0-b/results/cpu-supplemental"
OUT = CPU_DIR / "summary.json"

EXPECTED_RUNS = 3


def main() -> int:
    failures: list[str] = []
    accepted = []
    discarded = []

    run_dirs = sorted(CPU_DIR.glob("v0b-cpu-*"))
    for rd in run_dirs:
        rec_path = rd / "run.json"
        if not rec_path.exists():
            continue
        rec = json.loads(rec_path.read_text())
        rid = rec["run_id"]
        if not rec.get("backend_selection_proven"):
            discarded.append(rid)
            continue
        if rec.get("exit_code") != 0:
            failures.append(f"{rid}: nonzero exit {rec['exit_code']}")
            continue
        vals = {"pp512": [], "tg128": []}
        for line in (rd / "stdout.txt").read_text().splitlines():
            if not line.startswith("| qwen2"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            test = None
            for c in cells:
                if c.startswith("pp") or c.startswith("tg"):
                    test = c.split()[0]
            ts = float(cells[-1].split("±")[0].strip())
            if test and test.startswith("pp"):
                vals["pp512"].append(ts)
            elif test and test.startswith("tg"):
                vals["tg128"].append(ts)
        if len(vals["pp512"]) != 1 or len(vals["tg128"]) != 1:
            failures.append(
                f"{rid}: expected 1 pp512 + 1 tg128 aggregate row, got "
                f"{len(vals['pp512'])}/{len(vals['tg128'])}")
            continue
        accepted.append({"run_id": rid, **{k: v[0] for k, v in vals.items()}})

    # bring-up runs before correction 1 stay discarded, never averaged
    summary = {
        "schema": "inferswarm.vulkan-v0-b.cpu-supplemental-summary/1",
        "expected_accepted_runs": EXPECTED_RUNS,
        "accepted_runs": accepted,
        "n_accepted": len(accepted),
        "discarded_run_ids": discarded,
        "pp512_median_tps": (statistics.median(a["pp512"] for a in accepted)
                             if accepted else None),
        "tg128_median_tps": (statistics.median(a["tg128"] for a in accepted)
                             if accepted else None),
    }
    if failures:
        summary["failures"] = failures
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n")

    ok = (len(accepted) == EXPECTED_RUNS and not failures)
    print(json.dumps(summary, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
