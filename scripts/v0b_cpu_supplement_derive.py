#!/usr/bin/env python3
"""Derive the V0-B CPU-supplemental summary from retained raw runs.

Reads docs/investigations/vulkan-v0-b/results/cpu-supplemental/v0b-cpu-*/
and re-derives the layers-executed-on-host-CPU proof for EVERY run
DIRECTLY FROM ITS RAW RETAINED STDERR via the shared implementation in
scripts/v0b_cpu_proof.py (METHODOLOGY-CORRECTION-3.md rule) — a
`backend_selection_proven: true` boolean in run.json is NEVER trusted on
its own. A run is accepted only if the re-derived proof holds, the
re-derivation agrees with the collected-time verdict, and the run's exit
code is 0. Keeps exactly one pp512 + one tg128 aggregate row per run and
derives the arm medians.

Writes results/cpu-supplemental/summary.json (or refreshes the one in
results/economics.json via scripts/v0b_economics.py on the next run).
Fail-closed: any unproven, malformed, or contradicted run is reported,
never averaged.

History: superseded bring-up runs under the original and correction-1
rules were discarded at collection time and their bytes later OVERWRITTEN
by the accepted campaign's re-use of the runner's sequential run IDs —
they are NOT retained (declared provenance defect,
METHODOLOGY-CORRECTION-3.md); they are never averaged.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from v0b_cpu_proof import recheck_run  # noqa: E402

CPU_DIR = REPO / "docs/investigations/vulkan-v0-b/results/cpu-supplemental"
OUT = CPU_DIR / "summary.json"

EXPECTED_RUNS = 3
EXPECTED_LAYERS = 37


def main() -> int:
    failures: list[str] = []
    accepted = []
    rejected = []
    proof_by_run = {}

    run_dirs = sorted(CPU_DIR.glob("v0b-cpu-*"))
    for rd in run_dirs:
        rec_path = rd / "run.json"
        if not rec_path.exists():
            continue
        rec = json.loads(rec_path.read_text())
        rid = rec["run_id"]

        # Re-derive the proof from the raw retained stderr bytes.
        stderr_path = rd / "stderr.txt"
        if not stderr_path.exists():
            failures.append(f"{rid}: retained stderr missing; proof cannot be re-derived")
            rejected.append(rid)
            continue
        proof = recheck_run(rd, rec, expected_layers=EXPECTED_LAYERS)
        proof_by_run[rid] = proof
        if not proof["proved"]:
            failures.append(f"{rid}: CPU-execution proof does not hold on the raw retained stderr")
            rejected.append(rid)
            continue
        if not proof["matches_collected_verdict"]:
            failures.append(
                f"{rid}: re-derived proof contradicts the collected-time "
                f"backend_selection_proven verdict ({rec.get('backend_selection_proven')})")
            rejected.append(rid)
            continue
        if rec.get("exit_code") != 0:
            failures.append(f"{rid}: nonzero exit {rec['exit_code']}")
            rejected.append(rid)
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
            rejected.append(rid)
            continue
        accepted.append({"run_id": rid, **{k: v[0] for k, v in vals.items()}})

    accepted_ids = {a["run_id"] for a in accepted}
    discarded = [r for r in rejected if r not in accepted_ids]

    summary = {
        "schema": "inferswarm.vulkan-v0-b.cpu-supplemental-summary/3",
        "proof_rule_authority": (
            "docs/investigations/vulkan-v0-b/METHODOLOGY-CORRECTION-3.md"),
        "proof": "layers-executed-on-host-CPU re-derived per run from raw retained stderr (scripts/v0b_cpu_proof.py); run.json booleans are never trusted alone",
        "governance": {
            "physical_factual_finding": "layers-executed-on-host-CPU",
            "final_proof_timing": "retrospective_after_collection",
            "prospectively_frozen_decision_grade": False,
            "evidence_use": "retrospective_descriptive_only",
            "rationale": ("correction 2 was the final declared rule before the "
                          "canonical runs, but its CUDA0/Vulkan0 banner prohibition "
                          "was violated and its detector missed the retained Vulkan0 "
                          "line; correction 3 replaced that criterion after collection"),
        },
        "expected_accepted_runs": EXPECTED_RUNS,
        "accepted_runs": accepted,
        "n_accepted": len(accepted),
        "discarded_run_ids": sorted(discarded),
        "per_run_proof": {
            rid: {k: p[k] for k in (
                "proved", "offload_zero_proven", "layers_all_cpu",
                "cpu_mapped_model_buffer", "cpu_kv_buffer", "cpu_output_buffer",
                "matches_collected_verdict",
                "gpu_device_binding_lines")}
            for rid, p in proof_by_run.items() if rid in accepted_ids},
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
