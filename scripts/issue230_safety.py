#!/usr/bin/env python3
"""Issue #230 — V2-F #216 safety classification + execution-order gate.

Produces the machine-readable safety classification comparing the V2-F
external-memory seam to the #216 faulting transport seam BEFORE the
first physical transfer (issue Phase 2), and enforces the frozen
execution-order state machine:

  1. ONE 4-KiB correctness probe, a_to_b, mechanism opaque_fd only;
  2. only after a clean probe + clean health window: b_to_a 4-KiB;
  3. only then repeated small transfers / the frozen ladder;
  4. Arm B (dma_buf) runs the same order independently, never inferred
     from Arm A.

Every state transition is recorded in an append-only order-state file
whose digest chain binds predecessor states; the runner REFUSES any arm
whose predecessor state is absent or failed. No larger-size escalation
is possible after any earlier failure (issue control 16). Retained
output is the earliest failure; rerunning the same authority seeking a
cleaner result is structurally refused.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import issue230_receipt as rc
import issue230_host as host

SCHEMA_SAFETY = "inferswarm.v2f.safety-classification/1"
SCHEMA_ORDER = "inferswarm.v2f.execution-order/1"

#: The #216/#228 retained fault identity this classification is against
#: (pinned inside PHYSICAL-AUTHORITY.json -> v2d_safety_inheritance).
FAULTING_SEAM = {
    "issue": 216,
    "terminal": "V2D_V340L_PLATFORM_STRESS_FAIL",
    "mechanism": (
        "accepted #35 per-die x1 transport probe: llama.cpp serve/transport "
        "load driven through the host-facing Gen3 x1 upstream link under "
        "sustained CONCURRENT dual-die load"),
    "fault": ("amdgpu ring-gfx timeout on die B 0000:09:00.0, "
              "signaled seq=5131 emitted seq=5132, driver-initiated GPU "
              "reset FAILED ret=-62, reset kworker wedged in dm_suspend"),
}

#: The V2-F seam as designed (prospectively classified; frozen with the
#: producers before any physical output).
V2F_SEAM = {
    "mechanism": (
        "Vulkan external-memory fd export/import between two logical "
        "devices, one per Vega die, executing one fence-ordered "
        "vkCmdCopyBuffer of a bounded buffer, sequential (never "
        "concurrent with any other GPU work in this campaign)"),
    "material_differences": [
        "no transport/serving stack: no llama.cpp, no model, no "
        "sustained request loop; single bounded copies only",
        "no concurrency: exactly one submit in flight on the whole "
        "platform at any instant (the #216 fault struck under "
        "concurrent dual-die transport load)",
        "per-die queue submission through dedicated logical devices "
        "created from UUID-bound physical devices (not a device-group "
        "mask over one logical device)",
        "immediate-stop on the first anomaly with retained earliest "
        "failure; the #216 campaign escalated to soak after faults",
        "size ladder starts at 4 KiB — the #216 fault occurred at "
        "sustated transport scale, orders of magnitude above every "
        "early rung of this ladder",
    ],
    "initial_size": rc.PROBE_SIZE,
    "repetition_policy": (
        f"{rc.REPS_PER_SIZE} retained measured reps + "
        f"{rc.WARMUPS_PER_SIZE} warmup per size/direction, sequential; "
        "the first physical execution is a single 4-KiB probe"),
    "synchronization_model": (
        "explicit VkFence per submit; vkWaitForFences before any "
        "subsequent operation; no timeline semaphores, no concurrent "
        "access, no persistent submission threads"),
    "host_upstream_traffic_expected": (
        " Vulkan API/submit traffic only (kilobytes of command stream "
        "over the x1 link); the data path under test is the "
        "imported-memory copy itself, whose route is measured, not "
        "assumed"),
    "health_telemetry": (
        "per-arm AER deltas on all 7 health BDFs, amdgpu journal fault "
        "scan with cursor chaining, link state at every topology hop, "
        "VRAM/busy telemetry, host reachability sentinel (gateway "
        "ping), NIC byte counters, storage sentinel"),
    "immediate_stop_conditions": [
        "correctness mismatch",
        "ring timeout / hang",
        "GPU reset or failed reset",
        "device disappearance",
        "fatal/nonfatal uncorrectable PCIe/AER fault",
        "kernel wedge",
        "host reachability loss",
        "thermal critical condition",
        "unexpected fallback/staging that invalidates the arm's label",
        "any nonzero probe exit (fail-closed evidence failure)",
    ],
    "refusal_basis": None,  # set when execution is refused instead
}


def build_safety_classification() -> dict[str, Any]:
    """The machine-readable classification artifact (issue Phase 2)."""
    materially_different = bool(V2F_SEAM["material_differences"])
    doc = {
        "schema": SCHEMA_SAFETY,
        "campaign_id": rc.CAMPAIGN_ID,
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "faulting_seam": FAULTING_SEAM,
        "candidate_seam": V2F_SEAM,
        "classification": (
            "MATERIALLY_DIFFERENT_BOUNDED_PROBE"
            if materially_different else "EXECUTION_REFUSED"),
        "inherited_constraint": (
            "V2D_V340L_PLATFORM_STRESS_FAIL stands; the #35 transport "
            "seam is never executed by this campaign; absence of a "
            "fault in this mechanism is not permission for unbounded "
            "stress"),
        "first_physical_execution": {
            "size_bytes": rc.PROBE_SIZE,
            "direction": "a_to_b",
            "mechanism": "opaque_fd",
            "repetitions": 1,
        },
    }
    return doc


# ---------------------------------------------------------------------------
# Execution-order state machine (append-only, digest-chained).
# ---------------------------------------------------------------------------

#: Ordered arm identifiers. The ladder runs per (mechanism, direction)
#: AFTER the probe pair; controls after the ladder.
ORDER_SEQUENCE = [
    "probe-opaque_fd-a_to_b",
    "probe-opaque_fd-b_to_a",
    "ladder-opaque_fd-a_to_b",
    "ladder-opaque_fd-b_to_a",
    "controls",
    "probe-dma_buf-a_to_b",
    "probe-dma_buf-b_to_a",
    "ladder-dma_buf-a_to_b",
    "ladder-dma_buf-b_to_a",
    "controls-dma_buf",
]


class OrderError(RuntimeError):
    """Execution-order violation; the arm must not run."""


def _load_order(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"schema": SCHEMA_ORDER, "campaign_id": rc.CAMPAIGN_ID,
                "entries": [], "chain_digest": None}
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("schema") != SCHEMA_ORDER:
        raise OrderError(f"bad order-state schema: {path}")
    if doc.get("campaign_id") != rc.CAMPAIGN_ID:
        raise OrderError(f"order state belongs to another campaign: {path}")
    return doc


def _chain(doc: dict[str, Any]) -> str:
    import hashlib
    body = {k: v for k, v in doc.items() if k != "chain_digest"}
    return hashlib.sha256(rc.canonical(body)).hexdigest()


def _verify_chain(doc: dict[str, Any]) -> None:
    if doc.get("chain_digest") is None:
        if doc.get("entries"):
            raise OrderError("order state has entries but no chain digest")
        return
    if doc.get("chain_digest") != _chain(doc):
        raise OrderError("order-state chain digest mismatch (tampering)")


def order_state_path(evidence_root: Path) -> Path:
    return evidence_root / "order-state.json"


def authorize_arm(evidence_root: Path, arm: str) -> dict[str, Any]:
    """Fail-closed authorization for one arm against the order state.

    Rules (frozen):
      * the arm must exist in ORDER_SEQUENCE;
      * every predecessor arm must have state 'passed';
      * no arm anywhere in the state may be 'failed' (retained earliest
        failure stops escalation permanently — a rerun under the same
        authority is refused, not just discouraged);
      * no duplicate arm entries.
    """
    if arm not in ORDER_SEQUENCE:
        raise OrderError(f"unknown arm: {arm}")
    path = order_state_path(evidence_root)
    doc = _load_order(path)
    _verify_chain(doc)
    states = {e["arm"]: e["state"] for e in doc["entries"]}
    if arm in states:
        raise OrderError(
            f"arm {arm} already recorded ({states[arm]}); duplicate "
            "execution under the same authority is refused")
    if any(s == "failed" for s in states.values()):
        failed = [a for a, s in states.items() if s == "failed"]
        raise OrderError(
            f"campaign halted: earlier failure retained ({failed}); no "
            "escalation or rerun under the same authority")
    idx = ORDER_SEQUENCE.index(arm)
    for pred in ORDER_SEQUENCE[:idx]:
        if states.get(pred) != "passed":
            raise OrderError(
                f"predecessor arm {pred} has not passed "
                f"(state={states.get(pred)!r}); sequential order required")
    return {"arm": arm, "authorized": True,
            "predecessors_passed": ORDER_SEQUENCE[:idx]}


def record_arm_result(evidence_root: Path, arm: str, state: str,
                      detail: dict[str, Any]) -> dict[str, Any]:
    """Append one arm result to the digest-chained order state."""
    if state not in ("passed", "failed"):
        raise OrderError(f"bad arm state: {state}")
    path = order_state_path(evidence_root)
    doc = _load_order(path)
    _verify_chain(doc)
    states = {e["arm"]: e["state"] for e in doc["entries"]}
    if arm in states:
        raise OrderError(f"arm {arm} already recorded")
    if any(s == "failed" for s in states.values()):
        raise OrderError("campaign already halted by an earlier failure")
    entry = {
        "arm": arm,
        "state": state,
        "recorded_utc": datetime.now(timezone.utc).isoformat(),
        "detail": detail,
    }
    doc["entries"].append(entry)
    doc["chain_digest"] = _chain(doc)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(doc, indent=1, sort_keys=True).encode()
                     + b"\n")
    return doc


def stop_condition_fired(health_delta: dict[str, Any],
                         journal_delta: dict[str, Any],
                         probe_exit: int) -> str | None:
    """Immediate-stop conditions (issue Phase 2). Returns the condition
    name or None. Applied to EVERY arm's health window."""
    if probe_exit != 0:
        return "nonzero_probe_exit"
    counts = journal_delta.get("counts") or {}
    if counts.get("amdgpu_timeout"):
        return "ring_timeout_or_hang"
    if counts.get("amdgpu_reset"):
        return "gpu_reset"
    if counts.get("fatal_aer"):
        return "uncorrectable_pcie_error"
    if counts.get("thermal"):
        return "thermal_alarm"
    for bdf, row in (health_delta.get("aer") or {}).items():
        nonfatal = row.get("aer_dev_nonfatal") or {}
        fatal = row.get("aer_dev_fatal") or {}
        if any(isinstance(v, int) and v > 0 for v in fatal.values()) \
                or any(isinstance(v, int) and v > 0
                       for v in nonfatal.values()):
            return "uncorrectable_pcie_error"
    return None


def collect_health_window(evidence_root: Path, arm: str,
                          journal_cursor: str | None
                          ) -> dict[str, Any]:
    """Open a health window: snapshot before the arm runs."""
    return {
        "arm": arm,
        "health_before": host.health_snapshot(rc.HEALTH_BDFS),
        "telemetry_before": {
            "a": host.telemetry_sample("0000:06:00.0"),
            "b": host.telemetry_sample("0000:09:00.0"),
        },
        "upstream_before": host.upstream_traffic_snapshot(),
        "nic_before": host.nic_sentinel(),
        "host_health_before": host.host_health(),
        "journal_cursor": journal_cursor,
    }


def close_health_window(window: dict[str, Any]) -> dict[str, Any]:
    """Close the window; return the per-arm delta record (retained)."""
    journal = host.journal_scan(cursor=window.get("journal_cursor"))
    delta = {
        "arm": window["arm"],
        "health_after": host.health_snapshot(rc.HEALTH_BDFS),
        "telemetry_after": {
            "a": host.telemetry_sample("0000:06:00.0"),
            "b": host.telemetry_sample("0000:09:00.0"),
        },
        "upstream_after": host.upstream_traffic_snapshot(),
        "nic_after": host.nic_sentinel(),
        "host_health_after": host.host_health(),
        "journal_scan": {
            "argv": journal["argv"],
            "text": journal["text"],
            "next_cursor": journal["next_cursor"],
        },
        "aer_delta": host.aer_delta(window["health_before"],
                                    host.health_snapshot(rc.HEALTH_BDFS)),
        "journal_fault_counts": journal["counts"],
    }
    return delta


def write_safety_record(evidence_root: Path) -> Path:
    out = evidence_root / "safety-classification.json"
    doc = build_safety_classification()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(json.dumps(doc, indent=1, sort_keys=True).encode()
                    + b"\n")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence-root", required=True)
    ap.add_argument("--emit", action="store_true",
                    help="write the safety classification artifact")
    args = ap.parse_args()
    root = Path(args.evidence_root)
    if args.emit:
        out = write_safety_record(root)
        print(json.dumps({"safety_classification": str(out),
                          "classification":
                          build_safety_classification()["classification"]},
                         indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
