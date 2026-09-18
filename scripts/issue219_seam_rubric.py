#!/usr/bin/env python3
"""Issue #219 — V2-D0 observation-seam selection rubric and candidate ledger.

Freezes, BEFORE any retained physical output:

1. the candidate observation-seam ledger (each candidate class audited on
   the exact accepted stack, classified per the issue's seven criteria);
2. the selection rubric (which candidate may be selected, and what
   disqualifies one);
3. the terminal vocabulary and the frozen conservative-overlap contract
   the reducer must implement.

Machine-checkable: ``main()`` re-validates the ledger invariants and
prints the canonical JSON.  The rubric document under the evidence
namespace is generated from this module (single source of truth).
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NS = "vulkan-v2-d0-overlap-seam"
AREA = ROOT / "docs" / "investigations" / NS
RUBRIC_SCHEMA = "inferswarm.v2d0.seam-rubric/1"

# ---------------------------------------------------------------------------
# Evaluation criteria (fixed by issue #219 Phase 0 step 7).
# ---------------------------------------------------------------------------
CRITERIA = (
    "physical_participant_binding",
    "gpu_work_bracketing",
    "common_time_domain",
    "uncertainty_authority",
    "replayability",
    "perturbation_risk",
    "inert_by_default",
)

VERDICTS = ("QUALIFIED_CANDIDATE", "REJECTED", "UNAVAILABLE")

# ---------------------------------------------------------------------------
# Candidate ledger.  Every candidate was audited against the exact accepted
# stack (llama.cpp 8ea290247c87ced2ab245b056ffe96dbcf90d36c ggml-vulkan.cpp
# bytes; RADV Mesa 25.0.7-2+deb13u1; Vulkan loader 1.4.309; both Vega 10
# dies reporting timestampComputeAndGraphics=true, timestampPeriod=37.037ns,
# timestampValidBits=64 on all queue families, VK_EXT_calibrated_timestamps
# revision 2 device support).
# ---------------------------------------------------------------------------
CANDIDATES = [
    {
        "id": "process-lifetime",
        "class": "process/wrapper lifetime + shared start gate",
        "verdict": "REJECTED",
        "reasons": [
            "explicitly insufficient per issue #219 and per the #216 "
            "pre-execution blocker record (RAW-EVIDENCE-AUTHORITY.md): "
            "wrapper overlap does not prove GPU-work overlap",
        ],
        "criteria": {
            "physical_participant_binding": "yes",
            "gpu_work_bracketing": "no",
            "common_time_domain": "host wall clock only",
            "uncertainty_authority": "none",
            "replayability": "partial",
            "perturbation_risk": "none",
            "inert_by_default": "n/a",
        },
    },
    {
        "id": "gpu-util-polling",
        "class": "polling-based GPU utilization as sole overlap proof",
        "verdict": "REJECTED",
        "reasons": [
            "explicitly prohibited by issue #219 (polling-based GPU "
            "utilization as sole overlap proof); sampling granularity "
            "cannot bound sub-millisecond decode submissions honestly",
        ],
        "criteria": {
            "physical_participant_binding": "yes",
            "gpu_work_bracketing": "no",
            "common_time_domain": "host",
            "uncertainty_authority": "none",
            "replayability": "partial",
            "perturbation_risk": "none",
            "inert_by_default": "n/a",
        },
    },
    {
        "id": "ggml-perf-logger",
        "class": "existing GGML_VK_PERF_LOGGER query-pool seam in the "
                 "pinned ggml-vulkan.cpp (writeTimestamp at the first "
                 "compute command buffer of each graph compute, "
                 "getQueryPoolResults readback at graph end)",
        "verdict": "REJECTED",
        "reasons": [
            "the perf-logger tail path ends the final command buffer, "
            "submits with device->fence, and blocks the host with "
            "waitForFences at EVERY graph compute (ggml-vulkan.cpp "
            "18426-18438 at the pinned commit): it adds host-blocking "
            "synchronization that changes async execution ordering, "
            "violating the no-added-synchronization constraint",
            "device-domain timestamps only: no calibrated-timestamp "
            "support anywhere in the file, so no mechanically "
            "established common time domain",
            "timestampValidBits is never checked (assumes 64-bit)",
        ],
        "criteria": {
            "physical_participant_binding": "selector only",
            "gpu_work_bracketing": "yes (graph compute envelope)",
            "common_time_domain": "no",
            "uncertainty_authority": "timestampPeriod only",
            "replayability": "CSV summary, not raw ticks",
            "perturbation_risk": "high (added fence wait per graph)",
            "inert_by_default": "yes (env-gated)",
        },
    },
    {
        "id": "vulkan-timestamp-observe-seam",
        "class": "new observation-only seam: env-gated VkQueryPool device "
                 "timestamps bracketing every compute command buffer of "
                 "the correctness-bearing graph computes, plus host-side "
                 "VK_EXT_calibrated_timestamps calibration pairs "
                 "(DEVICE_EXT + CLOCK_MONOTONIC_EXT) captured at each "
                 "readback drain; readback only at points where the "
                 "runtime itself has already waited (fence signaled)",
        "verdict": "QUALIFIED_CANDIDATE",
        "reasons": [
            "device timestamps are written by the GPU at pipeline "
            "positions inside the actual compute command buffers: the "
            "bracket is the GPU work itself, not process lifetime",
            "calibrated timestamp pairs mechanically establish the "
            "common CLOCK_MONOTONIC domain with a retained maxDeviation "
            "bound per capture (issue Phase 4)",
            "no added fences, semaphores, barriers, or host waits: "
            "timestamps are recorded into command buffers that already "
            "exist, and readback happens only after the runtime's own "
            "fence wait completes (results then available; no eWait)",
            "inert unless GGML_VK_OBSERVE_INTERVAL is set: zero code "
            "paths differ (no extension enabled, no query pool created)",
            "timestampValidBits checked for the exact compute queue "
            "family before the seam activates (fail-closed)",
        ],
        "criteria": {
            "physical_participant_binding":
                "deviceUUID + deviceName + backend selector label "
                "emitted with every record; selector->BDF bound by the "
                "accepted v2a_discovery_v3 zero-token identity probe "
                "retained in the same run",
            "gpu_work_bracketing":
                "first-to-last device timestamp across every compute "
                "command buffer of each generation graph compute; "
                "per-submission [begin,end] intervals retained raw",
            "common_time_domain":
                "VK_EXT_calibrated_timestamps DEVICE_EXT + "
                "CLOCK_MONOTONIC_EXT pairs at every drain; raw pairs "
                "retained; conversion done by the reducer, never inside "
                "the instrument",
            "uncertainty_authority":
                "maxDeviation from every calibrated-timestamp call plus "
                "timestampPeriod granularity; conservative overlap must "
                "remain strictly positive after the combined bound",
            "replayability":
                "append-only JSONL of raw device ticks, calibration "
                "pairs, capability facts; reducer replays from bytes",
            "perturbation_risk":
                "device-side timestamp commands only (no dependencies "
                "introduced); host-side reads only after signaled "
                "fences; non-perturbation proven per die in Phase 3",
            "inert_by_default":
                "single env gate read once at instance init; all "
                "activation points are behind that gate",
        },
    },
]

# ---------------------------------------------------------------------------
# Selection rubric (frozen BEFORE observing any overlap result).
# ---------------------------------------------------------------------------
RUBRIC = {
    "schema": RUBRIC_SCHEMA,
    "criteria": list(CRITERIA),
    "selection_rule": (
        "Select the single QUALIFIED_CANDIDATE whose classification "
        "satisfies ALL of: (a) brackets the correctness-bearing GPU work "
        "via device-side observations inside the compute submissions; "
        "(b) establishes a mechanically retained common time domain with "
        "a per-capture deviation bound; (c) adds no synchronization that "
        "changes execution ordering; (d) is inert unless explicitly "
        "enabled; (e) is replayable from retained raw bytes. If no "
        "candidate satisfies all five, the terminal is UNAVAILABLE with "
        "the exact capability blocker recorded."
    ),
    "conservative_overlap_contract": {
        "rule": (
            "Overlap is valid only when the lower bound on the overlap "
            "of the participants' correctness-bearing GPU-work interval "
            "unions remains strictly positive after subtracting the "
            "combined uncertainty bound; otherwise the observation is "
            "INDETERMINATE, never overlap"
        ),
        "uncertainty_terms": [
            "maxDeviation reported by each retained calibrated-timestamp "
            "capture, applied to both interval endpoints of both "
            "participants (the implementation bounds the deviation of "
            "the DEVICE and CLOCK_MONOTONIC readings together)",
            "timestampPeriod granularity of each participant, applied "
            "once per endpoint",
        ],
        "non_overlap_control": (
            "the frozen sequential schedule must classify NON_OVERLAP "
            "(upper bound on overlap <= 0 after adding the full "
            "uncertainty bound)"
        ),
    },
    "workload_interval_definition": {
        "workload_start": (
            "the first device timestamp written at the beginning of the "
            "first compute command buffer of the FIRST generation graph "
            "compute of the bounded run"
        ),
        "workload_end": (
            "the last device timestamp written at the end of the last "
            "compute command buffer of the LAST generation graph "
            "compute of the bounded run"
        ),
        "per_token_intervals": (
            "per graph compute, the union of per-submission "
            "[begin,end] device-timestamp intervals, converted to the "
            "common domain; the workload interval is the envelope of "
            "the per-token unions, and overlap is decided on the "
            "interval UNIONS, never on the envelope alone"
        ),
        "exclusions": (
            "model load, warmup, and any non-generation graph computes "
            "are excluded by graph-compute sequence counting bounded "
            "to the requested generation count (-n N), with the "
            "runtime's own generation accounting retained in the same "
            "capture"
        ),
    },
    "invariants": [
        "every candidate verdict is one of " + repr(list(VERDICTS)),
        "exactly one QUALIFIED_CANDIDATE may exist",
        "a REJECTED candidate may never be selected",
        "the selected seam identity (patch bytes, generator identity) "
        "is frozen before retained physical output",
    ],
}


def validate() -> dict:
    ledger = [dict(c) for c in CANDIDATES]
    rubric = json.loads(json.dumps(RUBRIC))
    qualified = [c["id"] for c in ledger if c["verdict"] == "QUALIFIED_CANDIDATE"]
    if len(qualified) > 1:
        raise ValueError(f"multiple qualified candidates: {qualified}")
    for c in ledger:
        if c["verdict"] not in VERDICTS:
            raise ValueError(f"bad verdict: {c['verdict']}")
        missing = [k for k in CRITERIA if k not in c["criteria"]]
        if missing:
            raise ValueError(f"{c['id']} missing criteria: {missing}")
    if rubric["criteria"] != list(CRITERIA):
        raise ValueError("rubric criteria drift")
    return {"rubric": rubric, "candidates": ledger,
            "selected_seam": qualified[0] if qualified else None}


def main() -> int:
    doc = validate()
    out = AREA / "SEAM-RUBRIC.json"
    AREA.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(f"selected seam: {doc['selected_seam']}")
    print(f"{len(doc['candidates'])} candidates -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
