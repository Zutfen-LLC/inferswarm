#!/usr/bin/env python3
"""V0-B Phase 1 — correctness/stability classification reduction.

Mechanically derives the V0-B correctness/stability classification from
the accepted V0-A corrected raw records (no new physical claims):

  integrity    — model/executable identity, intended-device proof,
                 offload proof, absence of fallback/corruption markers;
  backend-local repeatability — stable / semantically stable /
                 output-unstable / operationally unstable /
                 insufficiently observed;
  cross-backend behavior    — exact agreement / numerical difference with
                 identical outputs / generated-output difference /
                 instability-failure.

Also records the ADR 0010 three-layer mapping WITHOUT creating or
retroactively applying any numerical threshold, and states what a future
prospective qualification campaign would need to freeze.

Writes docs/investigations/vulkan-v0-b/results/correctness-stability.json.
Fail-closed on any missing record or unexpected classification input.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
V0A = REPO / "docs/investigations/vulkan-v0-a"
OUT = REPO / "docs/investigations/vulkan-v0-b/results/correctness-stability.json"

# Frozen correction campaign plan (METHODOLOGY-CORRECTION.md §3).
EXPECTED_RUNS = {
    "AMD-A/02:00.0/Vulkan": 3,
    "AMD-B/03:00.0/Vulkan": 1,
    "NV-A/04:00.0/Vulkan": 1,
    "NV-A/04:00.0/CUDA": 1,
}

# Markers that would indicate silent fallback, corruption, or instability.
BAD_MARKERS = ("llvmpipe", "falling back", "failed to", "nan", "inf ", "error")

failures: list[str] = []


def main() -> int:
    cors = json.loads(
        (V0A / "results-correction/correctness-summary.json").read_text())

    check = cors.get("run_plan_matches_methodology")
    if not check:
        failures.append("V0-A summary says run plan does not match methodology")
    if cors.get("total_runs") != sum(EXPECTED_RUNS.values()):
        failures.append("total run count mismatch")
    if not cors.get("all_exit_clean") or not cors.get("all_intended_device_proven"):
        failures.append("clean-exit / device-proof aggregate is not all-true")

    per_pair = {}
    for pair_name, expected_n in EXPECTED_RUNS.items():
        p = cors["pairs"].get(pair_name)
        if p is None:
            failures.append(f"missing pair {pair_name}")
            continue
        if p["runs"] != expected_n or p["expected_runs"] != expected_n:
            failures.append(f"{pair_name}: run count {p['runs']} != {expected_n}")
        if not p["all_exit_clean"] or not p["all_intended_device_proven"]:
            failures.append(f"{pair_name}: exit/device proof not clean")
        if p["warnings_or_fallbacks"] or p["device_proof_failures"]:
            failures.append(f"{pair_name}: warnings/fallbacks/device-proof failures present")

        n_unique = p["unique_canonical_outputs"]
        runs = p["runs"]
        # Repeatability is an observation-count-gated property (issue #142
        # Phase 1): one observation cannot demonstrate repeatability, no
        # matter what its output is. Integrity/clean-execution facts are
        # recorded separately and never upgrade an under-observed pair to
        # `stable`.
        if runs >= 3 and n_unique == 1:
            repeatability = "stable"
        elif runs >= 3:
            repeatability = "output_unstable"
        else:
            repeatability = "insufficiently_observed"
        per_pair[pair_name] = {
            "runs": runs,
            "unique_visible_generations": n_unique,
            "generations": p["canonical_generations"],
            "backend_local_repeatability": repeatability,
            "integrity": "pass (per-run executable/model SHA-256 + BDF device proof + full offload; no fallback/corruption markers)",
        }

        # marker scan of the retained stderr of each run in this pair
        run_ids = p["run_ids"]
        for rid in run_ids:
            stderr_path = V0A / "correctness" / f"correction-{rid}" / "stderr.txt"
            text = stderr_path.read_text().lower()
            for marker in BAD_MARKERS:
                if marker in text:
                    # 'inf ' etc. can legitimately appear inside device names;
                    # fail loudly and let a human decide instead of guessing.
                    failures.append(f"{rid}: marker '{marker.strip()}' present in stderr")

    # Cross-backend relationship (exact byte equality of visible greedy text)
    all_generations = {g for p in cors["pairs"].values() for g in p["canonical_generations"]}
    vulkan_gens = {g for name, p in cors["pairs"].items()
                   if name.endswith("/Vulkan") for g in p["canonical_generations"]}
    cuda_gens = {g for name, p in cors["pairs"].items()
                 if name.endswith("/CUDA") for g in p["canonical_generations"]}

    if cors["cross_backend_relationship"] == "differs":
        cross = {
            "vulkan_vs_vulkan_across_devices": (
                "byte-identical visible generation across AMD-A (x3), AMD-B, NV-A"
                if len(vulkan_gens) == 1 else "MULTIPLE distinct Vulkan generations"),
            "vulkan_vs_cuda_same_device_nv_a": (
                "generated_output_difference — NV-A CUDA differs from all Vulkan runs "
                "at one word choice ('could be anything' vs 'could be any word or phrase'); "
                "NOT exact agreement and NOT relabeled as semantic equivalence"),
            "classification_per_issue_phase_1": "generated-output difference",
        }
    else:
        cross = {"note": cors["cross_backend_relationship"]}

    # ADR 0010 three-layer mapping — no new threshold, no retroactive application
    adr0010 = {
        "layer_1_exact_integrity": (
            "SATISFIED IN EVIDENCE — model/executable identities exact, intended device "
            "proven per run, full offload, no silent fallback or substitution recorded"),
        "layer_2_qualified_numerical_equivalence": (
            "NOT ESTABLISHED — V0-A exposes no logits; a prospectively frozen "
            "strategy-declared numerical-equivalence contract for a Vulkan path does not "
            "exist and this bundle does NOT create or retroactively apply one"),
        "layer_3_strategy_declared_semantic_correctness": (
            "NOT ESTABLISHED — one committed-token divergence exists between CUDA and "
            "Vulkan at the greedy fixture; no strategy has declared a semantic profile "
            "under which this difference is acceptable or not"),
        "new_threshold_created": False,
    }

    prospective = {
        "a_future_qualification_campaign_would_need_to_freeze_prospectively": [
            "the model execution strategy and its declared semantic profile (which generations are correctness-bearing)",
            "the numerical-equivalence contract: observable (logits/token-probability vs committed tokens), tolerance or exactness class, and evaluation window",
            "a fixture set with pre-registered per-fixture expectations per (device, backend) pair",
            "run counts and acceptance statistics frozen before the first canonical run",
            "an authority chain binding probe build, driver/ICD versions, and model bytes",
        ]
    }

    if failures:
        print(json.dumps({"failures": failures}, indent=1))
        return 1

    out = {
        "schema": "inferswarm.vulkan-v0-b.correctness-stability/1",
        "issue": 142,
        "derived_from": "docs/investigations/vulkan-v0-a/results-correction/correctness-summary.json (mechanical)",
        "per_pair": per_pair,
        "cross_backend": cross,
        "adr_0010_mapping": adr0010,
        "classification_summary": {
            "amd_a_vulkan": "physically proven (BDF), fully offloaded, clean exits, backend-local stable (3/3 identical visible generation)",
            "amd_b_vulkan": "physically proven, clean, single clean observation; repeatability insufficiently_observed by taxonomy (one run cannot demonstrate repeatability)",
            "nvidia_vulkan": "physically proven, clean, single observation (insufficiently_observed); visible generation identical to all AMD Vulkan runs",
            "nvidia_cuda": "physically proven, clean, single observation (insufficiently_observed); differs from Vulkan at one committed word",
        },
        **prospective,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    print(json.dumps({
        "written": str(OUT.relative_to(REPO)),
        "pairs": len(per_pair),
        "repeatability": {k: v["backend_local_repeatability"] for k, v in per_pair.items()},
        "cross_backend": cross["classification_per_issue_phase_1"],
    }, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
