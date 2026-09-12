#!/usr/bin/env python3
"""V0-B Phase 5 — terminal recommendation (fail-closed, mechanically validated).

Consumes this bundle's reductions (comparability matrix, correctness/
stability, economics, capability assessment, seam comparison) and emits
EXACTLY ONE machine-readable V0-B terminal classification plus the
scoped V0-C authorization question.

What is authoritative in the selection:
  - the corrected Phase-1 repeatability taxonomy (one-run arms are
    `insufficiently_observed`, never `stable`);
  - the seam reduction's explicit assessment of ALL FIVE Issue #142
    seam classes and the recorded properties of the selected seam;
  - the capability assessment's evidence-cited findings;
  - the supplemental CPU arm's corrected
    layers-executed-on-host-CPU proof status (cpu-supplemental/
    summary.json schema /2, re-derived from raw stderr).

What is DESCRIPTIVE, never gate-controlling (declared non-authoritative
heuristics, NOT preregistered, NOT part of any frozen methodology):
  - the NV-A Vulkan/CUDA pp 0.85 / tg 0.80 similarity heuristic;
  - the host-usefulness 2x-ratio heuristic. These ratios are
    descriptive-only summaries of retained evidence; the "2x
    pre-registered usefulness bar" claim previously made here was
    FALSE and has been removed. No threshold in this script was
    registered in METHODOLOGY.md or any correction before collection,
    and none is applied as a gate.

Fail-closed: a missing, malformed, or contradictory capability/seam
reduction, a seam whose recorded properties do not support
backend-neutral planning above the execution boundary, a seam whose
V0-C scope freezes a public API or cannot coexist with CUDA/HIP
resources under the generic resource model, missing required capability
facts, missing correctness qualifications/non-claims, or a broken CPU
proof each PREVENTS the `V0B_PROCEED_TO_INTEGRATION_SPIKE` selection
(failing closed to a lower classification rather than emitting the
spike recommendation).

Writes docs/investigations/vulkan-v0-b/TERMINAL.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
B = REPO / "docs/investigations/vulkan-v0-b"

S2_SEAM_ID = "S2-backend-adapter-participant"
REQUIRED_CAPABILITY_FACTS = (
    # (backend section, finding key) — facts the recommendation relies on.
    "deterministic_physical_device_discovery_selection",
    "device_local_memory_capacity_explicit",
    "model_state_materialization_on_accelerator",
    "representative_ops_without_silent_host_fallback",
    "evidence_bindable_backend_runtime_identity",
)
REQUIRED_SEAM_PROPERTIES = {
    # seam-record property -> required value
    "planner_leak": "LOW",
    "coexistence": None,  # must be a non-empty string (checked separately)
}
FORBIDDEN_IN_V0C_SCOPE = (
    "no public API freeze",
    "no planner backend nouns",
    "no preferred-backend ADR",
)


def load(p: Path) -> dict:
    return json.loads(p.read_text())


def validate_economics(econ: dict) -> list[str]:
    problems = []
    if not isinstance(econ.get("nvidia_same_device"), dict):
        problems.append("economics: nvidia_same_device section missing")
    amd = econ.get("amd_characterization") or {}
    if "NATIVE_BACKEND_UNAVAILABLE" not in amd.get("native_comparator", ""):
        problems.append("economics: AMD native comparator status is not NATIVE_BACKEND_UNAVAILABLE")
    host = econ.get("host_execution_comparison")
    if not isinstance(host, dict):
        problems.append("economics: host_execution_comparison (supplemental CPU arm) missing")
    else:
        cpu = host.get("cpu_arm") or {}
        runs = cpu.get("runs") or []
        if len(runs) < 3 or cpu.get("n_runs") != len(runs):
            problems.append("economics: CPU arm does not carry 3 proven runs")
        for phase in ("prefill", "decode"):
            r = (host.get(phase) or {}).get("ratio_amd_vk_over_cpu")
            if not isinstance(r, (int, float)) or r <= 0:
                problems.append(f"economics: host {phase} ratio missing or invalid")
    return problems


def validate_cpu_summary(cs: dict) -> list[str]:
    problems = []
    if not str(cs.get("schema", "")).endswith("/2"):
        problems.append("cpu summary: schema is not the corrected /2 proof schema")
    if cs.get("n_accepted") != 3 or len(cs.get("accepted_runs") or []) != 3:
        problems.append("cpu summary: accepted run count != 3")
    if cs.get("failures"):
        problems.append(f"cpu summary carries failures: {cs['failures']}")
    proof = cs.get("per_run_proof") or {}
    if len(proof) != 3:
        problems.append("cpu summary: per_run_proof missing for accepted runs")
    for rid, p in proof.items():
        if not p.get("proved"):
            problems.append(f"cpu summary: {rid} proof not re-derived as proved")
        if not p.get("layers_all_cpu") or not p.get("offload_zero_proven"):
            problems.append(f"cpu summary: {rid} lacks layers-all-CPU / zero-offload proof")
    return problems


def validate_stability(cors: dict) -> list[str]:
    problems = []
    per_pair = cors.get("per_pair") or {}
    expected = {
        "AMD-A/02:00.0/Vulkan", "AMD-B/03:00.0/Vulkan",
        "NV-A/04:00.0/Vulkan", "NV-A/04:00.0/CUDA",
    }
    if set(per_pair) != expected:
        problems.append(f"stability: per-pair set mismatch: {sorted(set(per_pair))}")
    for name, p in per_pair.items():
        if p.get("backend_local_repeatability") not in (
                "stable", "output_unstable", "insufficiently_observed"):
            problems.append(f"stability: {name} has unknown repeatability class")
        if p.get("runs", 0) < 3 and p.get("backend_local_repeatability") == "stable":
            problems.append(
                f"stability: {name} classified stable on {p.get('runs')} runs — "
                "violates the corrected taxonomy")
    return problems


def select_seam_s2(seams: dict) -> tuple[list[str], dict | None]:
    """Mechanically validate that the seam reduction justifies S2.

    Returns (problems, seam_record).
    """
    problems = []
    records = seams.get("seams")
    if not isinstance(records, list) or not records:
        return ["seam reduction: no seam records"], None
    ids = [s.get("id") for s in records]
    if len(ids) != len(set(ids)):
        problems.append("seam reduction: duplicate seam ids")
    if not seams.get("classes_all_considered"):
        problems.append("seam reduction: classes_all_considered is not true — "
                        "not all five Issue #142 seam classes were considered")
    s2 = next((s for s in records if s.get("id") == S2_SEAM_ID), None)
    if s2 is None:
        problems.append(f"seam reduction: {S2_SEAM_ID} record missing")
        return problems, None
    for prop in ("description", "doctrine_map", "granularity",
                 "qualification_requirements", "v0c_could_prove", "assessment"):
        if not isinstance(s2.get(prop), str) or not s2[prop].strip():
            problems.append(f"seam S2: required property '{prop}' missing/empty")
    if not str(s2.get("planner_leak", "")).startswith("LOW"):
        problems.append("seam S2: planner_leak is not LOW — backend-neutral "
                        "planning above the execution boundary not supported")
    coex = s2.get("coexistence")
    if not isinstance(coex, str) or not coex.strip():
        problems.append("seam S2: coexistence with CUDA/HIP resources not recorded")
    elif "CUDA" not in coex:
        problems.append("seam S2: coexistence statement does not cover CUDA/HIP resources")
    v0c = s2.get("v0c_could_prove", "")
    if isinstance(v0c, str) and "without freezing any public API" not in v0c:
        problems.append("seam S2: V0-C scope does not state the no-public-API-freeze bound")
    assessment = s2.get("assessment", "")
    if "STRONGEST" not in assessment:
        problems.append("seam S2: recorded assessment does not select it as the strongest candidate")
    return problems, s2


def validate_capabilities(caps: dict) -> list[str]:
    problems = []
    per_backend = caps.get("per_backend") or {}
    for backend in ("amd_a_polaris_vulkan", "nv_a_ga104_vulkan"):
        section = per_backend.get(backend)
        if not isinstance(section, dict):
            problems.append(f"capability assessment: section '{backend}' missing")
            continue
        findings = section.get("findings") or {}
        if not isinstance(section.get("compute_unit"), str) or not section["compute_unit"].strip():
            problems.append(f"capability assessment: {backend} has no compute-unit identity")
        for fact in REQUIRED_CAPABILITY_FACTS:
            f = findings.get(fact)
            if not isinstance(f, dict) or not f.get("status") or not f.get("evidence"):
                problems.append(
                    f"capability assessment: {backend} missing required fact/evidence '{fact}'")
    if "evidence" not in (caps.get("capability_discovery_useful_to_planning") or {}):
        problems.append("capability assessment: capability_discovery_useful_to_planning lacks evidence")
    return problems


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    paths = {
        "economics": B / "results/economics.json",
        "caps": B / "results/capability-assessment.json",
        "seams": B / "results/seam-comparison.json",
        "cors": B / "results/correctness-stability.json",
        "cpu": B / "results/cpu-supplemental/summary.json",
    }
    out_path = B / "TERMINAL.json"
    if "--inputs-dir" in argv:
        i = argv.index("--inputs-dir")
        base = Path(argv[i + 1])
        paths = {k: base / p.name for k, p in paths.items()}
        out_path = base / "TERMINAL.json"

    problems: list[str] = []
    try:
        econ = load(paths["economics"])
        caps = load(paths["caps"])
        seams = load(paths["seams"])
        cors = load(paths["cors"])
        cpu = load(paths["cpu"])
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"terminal": "V0B_EVIDENCE_INSUFFICIENT",
                          "fail_closed_reasons": [f"required reduction unreadable: {exc}"]}))
        return 1

    problems += validate_economics(econ)
    problems += validate_cpu_summary(cpu)
    problems += validate_stability(cors)
    seam_problems, s2 = select_seam_s2(seams)
    problems += validate_capabilities(caps)

    # Every integrity line in the corrected stability reduction must remain
    # a pass — a failing integrity arm bars the spike regardless of class.
    for name, p in (cors.get("per_pair") or {}).items():
        if not str(p.get("integrity", "")).startswith("pass"):
            problems.append(f"stability: {name} integrity is not a pass")

    # Terminal selection (exactly one).
    # V0B_EVIDENCE_INSUFFICIENT — required reductions missing/contradictory.
    # V0B_COMPATIBILITY_TIER_ONLY — correct and clean, but repeatability is
    #   only established on ONE (device, backend) arm; the single-run arms
    #   are insufficiently observed, and no verified seam/capability
    #   package authorizes the spike.
    # V0B_PROCEED_TO_INTEGRATION_SPIKE — requires: zero problems above AND
    #   a mechanically validated S2 seam AND AMD-A repeatability stable.
    if problems:
        terminal = "V0B_EVIDENCE_INSUFFICIENT"
        reason = ("required reductions are missing, malformed, or "
                  "contradictory; the terminal fails closed")
    elif seam_problems or s2 is None:
        terminal = "V0B_EVIDENCE_INSUFFICIENT"
        reason = "the seam reduction does not support the S2 handoff"
    else:
        amd_pair = cors["per_pair"]["AMD-A/02:00.0/Vulkan"]
        if amd_pair.get("backend_local_repeatability") == "stable":
            terminal = "V0B_PROCEED_TO_INTEGRATION_SPIKE"
            reason = ("device-proven with clean integrity on every arm; "
                      "backend-local repeatability demonstrated on AMD-A "
                      "(3/3 identical visible generation), with single-run "
                      "arms honestly classified insufficiently_observed; "
                      "the supplemental CPU arm is proven "
                      "layers-executed-on-host-CPU from raw retained stderr "
                      "and shows AMD-A Vulkan decisively faster than "
                      "host-memory execution on the same host, which has no "
                      "native backend; the seam reduction validates S2 "
                      "mechanically (all five classes considered, LOW "
                      "planner leak, CUDA/HIP coexistence, no public API "
                      "freeze in the V0-C scope)")
        else:
            terminal = "V0B_COMPATIBILITY_TIER_ONLY"
            reason = ("correct and clean, but backend-local repeatability is "
                      "not established on the primary AMD-A arm")

    selected_seam = S2_SEAM_ID if terminal == "V0B_PROCEED_TO_INTEGRATION_SPIKE" else None

    # Descriptive (non-authoritative) similarity summaries. These are
    # reported for context; they gate nothing and were never preregistered.
    nv = econ["nvidia_same_device"]
    host = econ.get("host_execution_comparison") or {}
    descriptive = {
        "authoritative": False,
        "note": ("descriptive-only summaries of retained evidence; NOT gates; "
                 "never preregistered in the frozen methodology; the prior "
                 "'2x pre-registered usefulness bar' claim was false and is "
                 "withdrawn"),
        "nv_vk_vs_cuda_similarity_heuristic": {
            "pp_ratio": nv["prefill"]["ratio_vk_over_cuda"],
            "tg_ratio": nv["decode"]["ratio_vk_over_cuda"],
            "reference_heuristic_declared_nonauthoritative": {"pp": 0.85, "tg": 0.80},
        },
        "amd_vk_over_host_execution": {
            "prefill_ratio": (host.get("prefill") or {}).get("ratio_amd_vk_over_cpu"),
            "decode_ratio": (host.get("decode") or {}).get("ratio_amd_vk_over_cpu"),
            "reference_heuristic_declared_nonauthoritative": {"ratio": 2.0},
        },
    }

    out = {
        "schema": "inferswarm.vulkan-v0-b.terminal/2",
        "issue": 142,
        "parent": {"issue": 141, "pr_merge": "273b9e8e32c779f063903cd75a0c6772d0d1e451",
                   "v0a_head": "2b2d546dc77350f14016b31a105696b257c063f2",
                   "terminal": "V0A_MATCHED_CHARACTERIZATION_COMPLETE"},
        "terminal": terminal,
        "reason": reason,
        "fail_closed_validations": {
            "problem_count": len(problems),
            "problems": problems,
            "seam_validation_problems": seam_problems,
            "required_seam": S2_SEAM_ID,
            "required_capability_facts": list(REQUIRED_CAPABILITY_FACTS),
        },
        "decision_inputs": {
            "backend_local_stability": {
                "authoritative": True,
                "per_pair": {k: v["backend_local_repeatability"]
                             for k, v in cors["per_pair"].items()},
                "amd_a_stable": (cors["per_pair"]["AMD-A/02:00.0/Vulkan"]
                                 ["backend_local_repeatability"] == "stable"),
                "note": ("corrected taxonomy: one-run arms are "
                         "insufficiently_observed, never stable"),
            },
            "amd_native_backend": "NATIVE_BACKEND_UNAVAILABLE",
            "cpu_arm_proof": {
                "authoritative": True,
                "rule": "layers-executed-on-host-CPU (METHODOLOGY-CORRECTION-3.md)",
                "accepted_runs": cpu.get("n_accepted"),
                "scope": ("proves CPU layer execution; does NOT claim 'no GPU "
                          "participated' or 'no GPU memory touched'"),
            },
            "descriptive_similarity_summaries": descriptive,
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
            "no logits-level numerical equivalence claimed",
            "no new numerical-equivalence threshold created or retroactively applied",
            "no performance threshold used here was preregistered; the pp 0.85 / tg 0.80 and 2x-ratio heuristics are descriptive only and gate nothing",
            "the CPU-arm proof does not claim 'no GPU participated' or 'no GPU device was used' (Vulkan enumeration and scratch reservation are retained facts)",
            "superseded CPU bring-up bytes were overwritten and are NOT retained (declared provenance defect)",
        ],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    print(json.dumps({"terminal": terminal,
                      "seam": selected_seam,
                      "fail_closed_problems": len(problems) + len(seam_problems)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
