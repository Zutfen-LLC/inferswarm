#!/usr/bin/env python3
"""Derive the V0-A correction correctness summary from raw run records.

Reads every docs/investigations/vulkan-v0-a/correctness/correction-*/
run.json and mechanically derives:
  - runs per (physical GPU, backend);
  - unique canonical outputs per backend/device;
  - all-exit-clean status;
  - backend-local repeatability (single unique generation within a device);
  - exact / semantic cross-backend relationship;
  - any warning/fallback state;
  - device-proof failures.

Every count comes from the raw records; nothing is hand-edited. Run counts
are validated against the correction methodology's frozen plan.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1] / \
    "docs/investigations/vulkan-v0-a"
CORRECTNESS = BUNDLE / "correctness"
OUT = BUNDLE / "results-correction" / "correctness-summary.json"

# Frozen run plan from METHODOLOGY-CORRECTION.md.
EXPECTED_RUNS = {
    ("AMD-A", "02:00.0", "Vulkan"): 3,
    ("AMD-B", "03:00.0", "Vulkan"): 1,
    ("NV-A", "04:00.0", "Vulkan"): 1,
    ("NV-A", "04:00.0", "CUDA"): 1,
}


def derive() -> dict:
    records = []
    for run_dir in sorted(CORRECTNESS.glob("correction-*/run.json")):
        records.append(json.loads(run_dir.read_text(encoding="utf-8")))

    per_pair = defaultdict(list)
    for record in records:
        key = (record["intended"]["gpu_label"],
               record["intended"]["physical_bdf"],
               "Vulkan" if record["intended"]["device_selector"]
               .startswith("Vulkan") else "CUDA")
        per_pair[key].append(record)

    pairs = {}
    for key, runs in sorted(per_pair.items()):
        label, bdf, backend = key
        digests = {r["generation_canonicalized_sha256"] for r in runs}
        all_clean = all(r["exit_code"] == 0 and not r["failures"]
                        for r in runs)
        all_proven = all(r["intended_device_proven"] for r in runs)
        warnings = sorted({w for r in runs for w in r["warnings"]})
        pairs[f"{label}/{bdf}/{backend}"] = {
            "runs": len(runs),
            "expected_runs": EXPECTED_RUNS.get(key),
            "run_ids": sorted(r["run_id"] for r in runs),
            "unique_canonical_outputs": len(digests),
            "canonical_output_digests": sorted(digests),
            "all_exit_clean": all_clean,
            "all_intended_device_proven": all_proven,
            "backend_local_repeatability":
                "stable" if len(digests) == 1 and all_clean else "UNSTABLE",
            "warnings_or_fallbacks": warnings,
            "device_proof_failures": [
                r["run_id"] for r in runs
                if not r["intended_device_proven"]],
        }

    vk_digests = {d for key, info in pairs.items() if key.endswith("Vulkan")
                  for d in info["canonical_output_digests"]}
    cuda_digests = {d for key, info in pairs.items() if key.endswith("CUDA")
                    for d in info["canonical_output_digests"]}
    if vk_digests and cuda_digests:
        cross = ("exact-equal" if vk_digests == cuda_digests
                 else "semantically-equal-exactly"
                 if semantic_equal(vk_digests, cuda_digests)
                 else "differs")
    else:
        cross = "insufficient-data"

    summary = {
        "schema":
            "inferswarm.vulkan-v0-a.correctness-correction-summary/1",
        "derived_from": "correctness/correction-*/run.json",
        "derivation": "mechanical (scripts/v0a_correctness_derive.py)",
        "correction_authority": "METHODOLOGY-CORRECTION.md",
        "total_runs": len(records),
        "expected_total_runs": sum(EXPECTED_RUNS.values()),
        "run_plan_matches_methodology":
            all(info["runs"] == info["expected_runs"]
                for info in pairs.values())
            and len(pairs) == len(EXPECTED_RUNS),
        "pairs": pairs,
        "cross_backend_relationship": cross,
        "cross_backend_note":
            "exact byte-equality of canonicalized generations if "
            "exact-equal; semantic equality is judged only from the "
            "retained text and is NOT a logits claim",
        "all_exit_clean": all(info["all_exit_clean"]
                              for info in pairs.values()),
        "all_intended_device_proven": all(
            info["all_intended_device_proven"]
            for info in pairs.values()),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def semantic_equal(vk_digests: set, cuda_digests: set) -> bool:
    """Compare retained canonical texts for cross-backend equality."""
    texts = {}
    for run_dir in sorted(CORRECTNESS.glob("correction-*/run.json")):
        record = json.loads(run_dir.read_text(encoding="utf-8"))
        texts[record["generation_canonicalized_sha256"]] = (
            record["generation_canonicalized"])
    vk_texts = {texts[d] for d in vk_digests if d in texts}
    cuda_texts = {texts[d] for d in cuda_digests if d in texts}
    return vk_texts == cuda_texts


def main() -> int:
    summary = derive()
    print(json.dumps({
        "total_runs": summary["total_runs"],
        "plan_matches": summary["run_plan_matches_methodology"],
        "all_exit_clean": summary["all_exit_clean"],
        "all_device_proven": summary["all_intended_device_proven"],
        "cross_backend": summary["cross_backend_relationship"],
    }))
    ok = (summary["run_plan_matches_methodology"]
          and summary["all_intended_device_proven"]
          and summary["all_exit_clean"])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
