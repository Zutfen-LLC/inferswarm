#!/usr/bin/env python3
"""Issue #228 — V2-E transfer-mechanism gate (Phases 3-7) — DISABLED.

Correction round (maintainer NO-GO on c9822fe). Physical transfer
execution is HARD-DISABLED for this campaign:

* the attempt-1 transfer producer could not identify inter-die traffic
  (a single logical queue was retrieved for every group device and
  submits carried no device-group execution masks, so every copy
  executed on device zero), and its staged/bidir paths allocated two
  command buffers into scalar handles;
* no corrected transfer producer has been reviewed or frozen. Until one
  exists, ANY capability observation — including a corrected positive
  one — refuses execution rather than launching the old machinery;
* no reachable path may mislabel device-zero or same-die work as
  inter-die P2P, so no transfer path is reachable at all.

Discovery vs execution are now separate:

* ``classify_mechanism`` derives ADVERTISED capability from a VALIDATED
  census verdict (probe.validate_capability_census) — it never treats
  an exportable-OR-importable flag, a host-only handle type, or
  duplicated one-way rows as a usable mechanism;
* ``authorize_execution`` always refuses (0 transfers) and records why.

The frozen refusal artifact carries the same closure binding and the
census verdict, so the assembler can reduce without any transfer
evidence.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue228_receipt as rc

ROOT = Path(__file__).resolve().parents[1]

#: The transfer implementation this campaign once shipped is deleted;
#: no implementation exists behind this gate.
IMPLEMENTATION_STATUS = "no-transfer-implementation-reviewed-or-frozen"


class MechanismUnavailable(RuntimeError):
    """No in-stack peer mechanism is available; transfers refused."""


class TransferExecutionDisabled(RuntimeError):
    """Physical transfer execution is disabled for this campaign."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def classify_mechanism(verdict: dict[str, Any]) -> dict[str, Any]:
    """Classify ADVERTISED peer-transfer capability from a VALIDATED
    census verdict (probe.validate_capability_census output).

    Distinguishes advertised capability from an implemented mechanism:
    even when the census advertises a capable mechanism, this campaign
    has NO reviewed transfer implementation, so ``implementation`` is
    always None and execution is always refused.

    One-sided or host-only external-memory features, duplicated one-way
    peer rows, and missing directions never yield a usable mechanism.
    """
    if not verdict.get("census_valid"):
        return {
            "selected_mechanism": None,
            "available": False,
            "basis": "census-invalid",
            "census_failure_reasons":
                list(verdict.get("failure_reasons") or []),
            "implementation": None,
        }
    capable = list(verdict.get("capable_mechanisms") or [])
    group = verdict.get("group") or {}
    peer = verdict.get("peer_features") or {}
    ext = verdict.get("external_memory") or {}
    if not capable:
        reasons: list[str] = []
        if not group.get("both_dies_in_one_group"):
            reasons.append(
                "no Vulkan device group contains both V340 dies "
                "(co-membership absent; vkGetDeviceGroupPeerMemoryFeatures "
                "unreachable for the pair on this stack)")
        else:
            dirs = peer.get("directions") or {}
            missing = [d for d in ("a_to_b", "b_to_a")
                       if not (dirs.get(d) or {}).get("present")]
            if missing:
                reasons.append(
                    f"peer-memory features absent/incomplete for "
                    f"directions {missing} on device-local heaps")
        usable = ext.get("usable_handle_types") or []
        if not usable:
            reasons.append(
                "no fd-carried external-memory handle type "
                "(opaque_fd/dma_buf) is exportable on the source AND "
                "importable on the destination die with compatible "
                "handle types for transfer-usage buffers, in either "
                "required direction")
        return {
            "selected_mechanism": None,
            "available": False,
            "basis": "no-capable-mechanism-advertised",
            "capability_absence_reasons": reasons,
            "group": group,
            "peer_directions": peer.get("directions"),
            "external_memory_directions": ext.get("directions"),
            "implementation": None,
        }
    # capability advertised — but no implementation exists
    return {
        "selected_mechanism": None,
        "available": False,
        "basis": "capability-advertised-but-no-implementation",
        "advertised_mechanisms": capable,
        "group": group,
        "peer_directions": peer.get("directions"),
        "external_memory_directions": ext.get("directions"),
        "implementation": None,
        "implementation_status": IMPLEMENTATION_STATUS,
        "note": (
            "Advertised capability is NOT proof a usable mechanism "
            "exists on the installed runtime, and this campaign has no "
            "reviewed transfer implementation; execution is refused."),
    }


def authorize_execution(mechanism: dict[str, Any]) -> dict[str, Any]:
    """Execution authorization: always refuses under this campaign.

    Returns the refusal decision record. A capability-only correction
    can never authorize transfers; a future reviewed producer must
    replace this function wholesale.
    """
    return {
        "authorized": False,
        "executed_transfers": 0,
        "reason": (
            "Physical transfer execution is disabled for campaign "
            f"{rc.CAMPAIGN_ID}: no transfer producer has been reviewed "
            "or frozen (the attempt-1 producer could not identify "
            "inter-die traffic and was removed). Corrected capability "
            "observations do not authorize physical execution."),
        "mechanism_basis": mechanism.get("basis"),
    }


def stop_condition_fired(health_delta: dict[str, Any],
                         journal_delta: dict[str, Any]) -> str | None:
    """Immediate-stop conditions (issue Phase 3). Returns the condition
    name or None. Retained for the reducer's use on any future ladder
    evidence; no execution path reaches it in this campaign."""
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
        if any(v > 0 for v in fatal.values()) \
                or any(v > 0 for v in nonfatal.values()):
            return "uncorrectable_pcie_error"
    return None


def emit_refusal(*, repo: Path, out: Path, attempt_id: str,
                 verdict: dict[str, Any]) -> dict[str, Any]:
    """Emit the transfer-phase refusal artifact (retained evidence)."""
    closure = rc.verify_closure(repo)
    mechanism = classify_mechanism(verdict)
    decision = authorize_execution(mechanism)
    out.mkdir(parents=True, exist_ok=True)
    doc = {
        "schema": "inferswarm.v2e.ladder-refusal/2",
        "campaign_id": rc.CAMPAIGN_ID,
        "attempt_id": attempt_id,
        "captured_utc": _now(),
        "closure_digest": closure["closure_digest"],
        "producer_head": closure["producer_head"],
        "mechanism": mechanism,
        "execution_decision": decision,
        "refusal": decision["reason"],
        "executed_transfers": 0,
    }
    (out / "refusal.json").write_bytes(
        json.dumps(doc, indent=1, sort_keys=True).encode() + b"\n")
    return doc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(ROOT))
    ap.add_argument("--out", required=True)
    ap.add_argument("--attempt-id", default="lad2")
    ap.add_argument("--preflight", required=True,
                    help="path to a preflight.json (attempt pf2)")
    args = ap.parse_args()
    preflight = json.loads(Path(args.preflight).read_text())
    verdict = preflight.get("capability_verdict")
    if not verdict:
        raise SystemExit(
            "preflight carries no capability_verdict; only a corrected "
            "(pf2) preflight may drive the transfer gate")
    doc = emit_refusal(repo=Path(args.repo), out=Path(args.out),
                       attempt_id=args.attempt_id, verdict=verdict)
    print(json.dumps({"refusal": str(Path(args.out) / "refusal.json"),
                      "mechanism_available":
                          doc["mechanism"]["available"],
                      "executed_transfers":
                          doc["executed_transfers"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
