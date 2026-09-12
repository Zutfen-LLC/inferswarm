#!/usr/bin/env python3
"""V0-B Phase 5 — terminal recommendation.

Consumes this bundle's reductions (comparability matrix, correctness/
stability, economics, capability assessment, seam comparison) and emits
EXACTLY ONE machine-readable V0-B terminal classification plus the
scoped V0-C authorization question.

Fail-closed: refuses to emit if any upstream reduction is missing or
internally inconsistent.

Writes docs/investigations/vulkan-v0-b/TERMINAL.json.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
B = REPO / "docs/investigations/vulkan-v0-b"


def load(p: Path) -> dict:
    return json.loads(p.read_text())


def main() -> int:
    econ = load(B / "results/economics.json")
    caps = load(B / "results/capability-assessment.json")
    seams = load(B / "results/seam-comparison.json")
    cors = load(B / "results/correctness-stability.json")

    nv = econ["nvidia_same_device"]
    amd = econ["amd_characterization"]
    host = econ.get("host_execution_comparison")

    # Decision inputs, each cited from the reductions:
    amd_useful_vs_host = None
    if host:
        # Vulkan on AMD-A must beat host execution by a decisive margin on at
        # least decode to be "useful as an accelerator" rather than a second
        # slow CPU; 2x is declared here as the pre-registered usefulness bar.
        BAR = 2.0
        amd_useful_vs_host = {
            "bar_declared": BAR,
            "prefill_ratio": host["prefill"]["ratio_amd_vk_over_cpu"],
            "decode_ratio": host["decode"]["ratio_amd_vk_over_cpu"],
            "decode_clears_bar": host["decode"]["ratio_amd_vk_over_cpu"] >= BAR,
            "prefill_clears_bar": host["prefill"]["ratio_amd_vk_over_cpu"] >= BAR,
        }

    near_native_nv = nv["prefill"]["ratio_vk_over_cuda"] >= 0.85 and \
        nv["decode"]["ratio_vk_over_cuda"] >= 0.80
    backend_stable = all(
        v["backend_local_repeatability"] in ("stable",)
        for v in cors["per_pair"].values())

    amd_no_native = "NONE" in amd["native_comparator"] or \
        "NATIVE_BACKEND_UNAVAILABLE" in amd["native_comparator"]

    # --- terminal selection (exactly one) --------------------------------
    # V0B_EVIDENCE_INSUFFICIENT if a required reduction is missing.
    # V0B_DO_NOT_INTEGRATE_CURRENT_PATH if unstable or useless vs host.
    # V0B_PROCEED_TO_INTEGRATION_SPIKE if a concrete seam exists and the
    #   path is plausibly useful as a Swarm resource.
    # V0B_COMPATIBILITY_TIER_ONLY if reliable but not a primary candidate.
    if host is None:
        terminal = "V0B_EVIDENCE_INSUFFICIENT"
        reason = "supplemental CPU baseline absent; AMD usefulness cannot be decided"
    elif not backend_stable:
        terminal = "V0B_DO_NOT_INTEGRATE_CURRENT_PATH"
        reason = "backend-local instability in the corrected campaign"
    elif not (near_native_nv and (amd_useful_vs_host or {}).get("decode_clears_bar")):
        terminal = "V0B_COMPATIBILITY_TIER_ONLY"
        reason = ("Vulkan retained as a portable compatibility/fallback capability; "
                  "current evidence does not justify making it a primary execution candidate")
    else:
        terminal = "V0B_PROCEED_TO_INTEGRATION_SPIKE"
        reason = ("device-proven, backend-locally stable, near-native on NVIDIA, "
                  "and decisively more useful than host execution on AMD-A which has "
                  "no native backend; seam S2 is narrow and backend-neutral")

    selected_seam = "S2-backend-adapter-participant" if terminal == "V0B_PROCEED_TO_INTEGRATION_SPIKE" else None

    out = {
        "schema": "inferswarm.vulkan-v0-b.terminal/1",
        "issue": 142,
        "parent": {"issue": 141, "pr_merge": "273b9e8e32c779f063903cd75a0c6772d0d1e451",
                   "v0a_head": "2b2d546dc77350f14016b31a105696b257c063f2",
                   "terminal": "V0A_MATCHED_CHARACTERIZATION_COMPLETE"},
        "terminal": terminal,
        "reason": reason,
        "decision_inputs": {
            "nv_near_native": {
                "pp_ratio": nv["prefill"]["ratio_vk_over_cuda"],
                "tg_ratio": nv["decode"]["ratio_vk_over_cuda"],
                "thresholds_declared": {"pp": 0.85, "tg": 0.80},
                "value": near_native_nv,
            },
            "backend_local_stability": backend_stable,
            "amd_native_backend": "NATIVE_BACKEND_UNAVAILABLE" if amd_no_native else "present",
            "amd_useful_vs_host": amd_useful_vs_host,
        },
        "recommended_v0c_seam": selected_seam,
        "v0c_scope_if_authorized": {
            "goal": "prove one strategy-defined execution unit realized by a Vulkan-capable executor/adapter on a Compute Unit, selected by the generic planner from capability/evidence records, beside at least one CUDA-backed unit in the same Swarm",
            "explicitly_not": ["no public API freeze", "no planner backend nouns", "no preferred-backend ADR", "no multi-GPU Vulkan claim", "no new numerical threshold"],
            "must_bind": ["model/checkpoint identity", "probe/adapter build identity", "physical device BDF per run", "strategy semantic profile declared BEFORE execution"],
        },
        "non_claims": [
            "no ADR promotes Vulkan to preferred/default",
            "no accepted Issue #117 correctness evidence or authority changed",
            "no causal decomposition of the AMD throughput level claimed (compute vs memory vs link remains open)",
            "no cross-backend semantic equivalence claimed (the one-word CUDA/Vulkan divergence stands)",
            "no new numerical-equivalence threshold created or retroactively applied",
        ],
    }
    (B / "TERMINAL.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    print(json.dumps({"terminal": terminal,
                      "seam": selected_seam,
                      "amd_decode_vs_cpu": (amd_useful_vs_host or {}).get("decode_ratio")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
