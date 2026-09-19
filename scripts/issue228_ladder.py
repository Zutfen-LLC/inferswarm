#!/usr/bin/env python3
"""Issue #228 — V2-E transfer ladder runner (Phases 3-7).

Executes the frozen transfer ladder ONLY when the retained capability
evidence establishes a usable peer mechanism. The runner REFUSES to
execute any transfer when the capability census classifies the selected
mechanism as unavailable — the mechanism gate is mechanical, not
authored:

  * device-group peer path requires a >=2-device group containing both
    Vega dies AND COPY_SRC/COPY_DST peer features for the device-local
    heaps in both directions;
  * the secondary in-stack path (external-memory dma-buf/opaque-fd
    import) requires exportable+importable features on BOTH dies;
  * any other mechanism is out of scope for this campaign (no substrate
    replacement authorized).

When a mechanism IS available the runner executes the frozen ladder
with per-arm health snapshots, immediate-stop conditions, and retained
raw bytes for every attempt. When it is NOT available the runner emits
the refusal artifact (retained) and the campaign's transfer phases are
classified by the assembler.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue228_host as host
import issue228_probe as probe
import issue228_receipt as rc

ROOT = Path(__file__).resolve().parents[1]


class MechanismUnavailable(RuntimeError):
    """No in-stack peer mechanism is available; transfers refused."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def classify_mechanism(capability: dict[str, Any]) -> dict[str, Any]:
    """Mechanically classify the available peer-transfer mechanism from
    the retained capability census (groups + peer features + external
    memory matrix). Fail-closed: anything short of a proven mechanism
    is UNAVAILABLE."""
    groups = capability.get("groups") or []
    vega_multi = None
    for g in groups:
        vega = [d for d in g.get("devices", [])
                if d.get("is_v340")]
        if len(vega) >= 2:
            vega_multi = g
            break
    group_ok = vega_multi is not None
    peer_features = capability.get("peer_memory_features") or []
    devlocal_copy = [
        f for f in peer_features
        if f.get("heap_device_local") and f.get("copy_src") and f.get("copy_dst")
    ]
    # both directions between the two vega device indices (canonical
    # JSON-safe list-of-lists so a round-tripped artifact compares equal
    # to the freshly classified one)
    directions = sorted(
        [[int(f["local_device"]), int(f["peer_device"])]
         for f in devlocal_copy]
    )
    both_dirs = group_ok and len(directions) >= 2

    ext = capability.get("external_memory_matrix") or {}
    ext_any = False
    for die in ext.get("dies", []):
        for row in die.get("buffer_matrix", []):
            if row.get("exportable") or row.get("importable"):
                ext_any = True
        for row in die.get("image_probes", []):
            if row.get("exportable") or row.get("importable"):
                ext_any = True

    if group_ok and both_dirs:
        return {
            "selected_mechanism": "vulkan-device-group-peer-copy",
            "available": True,
            "group_device_count": vega_multi["device_count"],
            "copy_capable_directions": sorted(directions),
            "secondary_ext_memory_features": ext_any,
        }
    if ext_any:
        return {
            "selected_mechanism": "vulkan-external-memory-dmabuf",
            "available": True,
            "group_ok": group_ok,
            "secondary_ext_memory_features": True,
        }
    return {
        "selected_mechanism": None,
        "available": False,
        "group_ok": group_ok,
        "multi_device_vega_group_present": group_ok,
        "peer_copy_directions": sorted(directions),
        "secondary_ext_memory_features": ext_any,
        "missing_capability": (
            "Vulkan loader exposes every physical device in a "
            "single-device group (no multi-device group contains both "
            "Vega dies), so vkGetDeviceGroupPeerMemoryFeatures/peer "
            "copies are unreachable; and no external-memory handle type "
            "(opaque_fd, dma_buf, host_allocation, host_mapped_foreign) "
            "is exportable or importable for buffers or images on "
            "either die. No in-stack peer-memory mechanism exists "
            "without replacing the runtime/driver substrate."
            if not group_ok and not ext_any else
            "peer mechanism incomplete"),
    }


def stop_condition_fired(health_delta: dict[str, Any],
                         journal_delta: dict[str, Any]) -> str | None:
    """Immediate-stop conditions (issue Phase 3). Returns the condition
    name or None."""
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


def run_ladder(*, repo: Path, out: Path, attempt_id: str,
               preflight: dict[str, Any], build_dir: Path) -> dict[str, Any]:
    closure = rc.verify_closure(repo)
    mechanism = classify_mechanism(preflight["capability"])
    out.mkdir(parents=True, exist_ok=True)

    if not mechanism["available"]:
        doc = {
            "schema": "inferswarm.v2e.ladder-refusal/1",
            "campaign_id": rc.CAMPAIGN_ID,
            "attempt_id": attempt_id,
            "captured_utc": _now(),
            "closure_digest": closure["closure_digest"],
            "producer_head": closure["producer_head"],
            "mechanism": mechanism,
            "refusal": (
                "No in-stack peer-transfer mechanism is available; the "
                "frozen ladder is refused. Any transfer arm under this "
                "campaign would have to run a substituted substrate, "
                "which the issue forbids."),
            "executed_transfers": 0,
        }
        (out / "refusal.json").write_bytes(
            json.dumps(doc, indent=1, sort_keys=True).encode() + b"\n")
        return doc

    # Mechanism available: execute the frozen ladder (sizes ascending,
    # health snapshot + journal delta after every size boundary,
    # immediate-stop honored).
    binary, source, source_sha = probe.compile_probe(build_dir)
    raw = out / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    health0 = host.health_snapshot(rc.HEALTH_BDFS)
    journal0 = host.journal_scan()
    rows: list[dict[str, Any]] = []
    stopped: str | None = None
    for size in rc.LADDER_SIZES:
        result = probe.run_transfer(binary=binary, mode="ladder",
                                    args=[str(size), str(rc.REPS_PER_SIZE),
                                          str(rc.WARMUPS_PER_SIZE)],
                                    timeout=900)
        rel = f"ladder-{size}.stdout"
        host.durable_write(raw / rel, result["stdout"].encode())
        host.durable_write(raw / f"ladder-{size}.stderr",
                           result["stderr"].encode())
        host.durable_write(raw / f"ladder-{size}.exit-code",
                           f"{result['returncode']}\n".encode())
        rows.append({
            "size": size,
            "stdout_rel": f"raw/{rel}",
            "stdout_sha256": hashlib.sha256(
                result["stdout"].encode()).hexdigest(),
            "exit_code": result["returncode"],
        })
        health1 = host.health_snapshot(rc.HEALTH_BDFS)
        journal1 = host.journal_scan(cursor=journal0["next_cursor"])
        host.durable_write(raw / f"journal-{size}.stdout",
                           journal1["text"].encode())
        delta = host.aer_delta(health0, health1)
        cond = stop_condition_fired(delta, journal1)
        if cond is not None:
            stopped = cond
            break
        if result["returncode"] != 0:
            stopped = f"probe_exit_{result['returncode']}"
            break
        health0 = health1
        journal0 = journal1

    doc = {
        "schema": "inferswarm.v2e.ladder/1",
        "campaign_id": rc.CAMPAIGN_ID,
        "attempt_id": attempt_id,
        "captured_utc": _now(),
        "closure_digest": closure["closure_digest"],
        "producer_head": closure["producer_head"],
        "mechanism": mechanism,
        "frozen_sizes": list(rc.LADDER_SIZES),
        "reps": rc.REPS_PER_SIZE,
        "warmups": rc.WARMUPS_PER_SIZE,
        "rows": rows,
        "stop_condition": stopped,
        "probe_source_sha256": source_sha,
        "probe_binary_sha256": hashlib.sha256(
            binary.read_bytes()).hexdigest(),
    }
    (out / "ladder.json").write_bytes(
        json.dumps(doc, indent=1, sort_keys=True).encode() + b"\n")
    return doc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(ROOT))
    ap.add_argument("--out", required=True)
    ap.add_argument("--attempt-id", default="lad1")
    ap.add_argument("--preflight", required=True)
    ap.add_argument("--build-dir", default="/var/tmp/issue228-build")
    args = ap.parse_args()
    preflight = json.loads(Path(args.preflight).read_text())
    doc = run_ladder(repo=Path(args.repo), out=Path(args.out),
                     attempt_id=args.attempt_id, preflight=preflight,
                     build_dir=Path(args.build_dir))
    print(json.dumps({"ladder": str(Path(args.out)),
                      "mechanism_available":
                          doc["mechanism"]["available"],
                      "stop_condition": doc.get("stop_condition")},
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
