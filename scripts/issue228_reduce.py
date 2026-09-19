#!/usr/bin/env python3
"""Issue #228 — V2-E deterministic reduction helpers.

Every reduction in this module re-derives its output from PRIMARY RAW
BYTES retained under the evidence root. Nothing is taken from authored
summaries. Used by both the assembler and the negative-control tests.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

import issue228_receipt as rc


class ReduceError(RuntimeError):
    pass


def parse_probe_stream(stdout: str, exit_code: int) -> list[dict[str, Any]]:
    """Parse a transfer probe's JSON-lines stream (fail-closed)."""
    if exit_code != 0:
        raise ReduceError(f"probe exited {exit_code}")
    records = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        records.append(json.loads(line))  # malformed -> ValueError -> caller
    if not records or "schema" not in records[0]:
        raise ReduceError("probe stream lacks a header record")
    return records


def reduce_transfers(records: list[dict[str, Any]], direction: str
                     ) -> dict[str, Any]:
    """Reduce one direction's timed rows to the frozen distribution
    summary (median/min/max/p10/p90, count, bytes, gbps). Fail-closed on
    zero/negative times, mixed sizes, or missing correctness rows."""
    timed = [r for r in records
             if r.get("kind") == "transfer" and r.get("dir") == direction]
    checks = [r for r in records
              if r.get("kind") == "correctness" and r.get("dir") == direction]
    fails = [r for r in records
             if r.get("kind") == "correctness_fail"
             and r.get("dir") == direction]
    if not timed:
        raise ReduceError(f"no timed rows for direction {direction}")
    if fails:
        raise ReduceError(
            f"correctness failures retained for {direction}: "
            f"{[r.get('rep') for r in fails]}")
    if len(checks) != len(timed):
        raise ReduceError(
            f"correctness row count {len(checks)} != timed {len(timed)} "
            f"for {direction}")
    for row in timed:
        if row.get("ms", 0) <= 0 or row.get("bytes", 0) <= 0:
            raise ReduceError(f"invalid timed row: {row!r}")
    times_ms = [row["ms"] for row in timed]
    bytes_ = timed[0]["bytes"]
    if any(row["bytes"] != bytes_ for row in timed):
        raise ReduceError("mixed transfer sizes in one reduction")
    gbps = [bytes_ / (t / 1e3) / 1e9 for t in times_ms]

    def pct(values: list[float], fraction: float) -> float:
        ordered = sorted(values)
        idx = min(int(round(fraction * (len(ordered) - 1))),
                  len(ordered) - 1)
        return ordered[idx]

    return {
        "direction": direction,
        "count": len(timed),
        "bytes_per_transfer": bytes_,
        "time_ms_min": round(min(times_ms), 6),
        "time_ms_median": round(statistics.median(times_ms), 6),
        "time_ms_p10": round(pct(times_ms, 0.10), 6),
        "time_ms_p90": round(pct(times_ms, 0.90), 6),
        "time_ms_max": round(max(times_ms), 6),
        "gbps_median": round(statistics.median(gbps), 3),
        "gbps_min": round(min(gbps), 3),
        "gbps_max": round(max(gbps), 3),
        "correctness_ok": True,
    }


def reduce_route(assembly: dict[str, Any]) -> dict[str, Any]:
    """Derive the route conclusion from retained evidence.

    Route vocabulary (issue Phase 6, never collapsed):
      LOCAL_SWITCH_BYPASS_PROVEN — needs per-port byte counters proving
        downstream activity without upstream activity;
      UPSTREAM_OR_HOST_ROUTE_PROVEN — counters/observations prove the
        host-facing path carried the peer traffic;
      PEER_FUNCTIONAL_ROUTE_UNRESOLVED — peer copies work but route
        evidence cannot distinguish;
      NO_PEER_TRANSFER_AVAILABLE — no peer mechanism existed to observe.
    """
    route_counters = assembly.get("route_counters_available")
    mechanism = (assembly.get("mechanism") or {})
    if not mechanism.get("available"):
        return {
            "route_conclusion": "NO_PEER_TRANSFER_AVAILABLE",
            "basis": "no peer-transfer mechanism existed to observe",
        }
    if not route_counters:
        return {
            "route_conclusion": "PEER_FUNCTIONAL_ROUTE_UNRESOLVED",
            "basis": "peer transfers functional but no per-port byte "
                     "counters retained to distinguish local switch "
                     "bypass from upstream routing",
        }
    raise ReduceError(
        "per-port counter derivation not implemented in this campaign "
        "(counters unavailable on this kernel); refusing to fabricate a "
        "route conclusion")


def rederive_capability_facts(capability: dict[str, Any]) -> dict[str, Any]:
    """Re-derive the mechanism classification from the retained
    capability JSON (same logic as issue228_ladder.classify_mechanism,
    kept reduction-side so the assembler never trusts the collector's
    own summary)."""
    groups = capability.get("groups") or []
    multi = [g for g in groups
             if len([d for d in g.get("devices", [])
                     if d.get("is_v340")]) >= 2]
    group_ok = bool(multi)
    peer_features = capability.get("peer_memory_features") or []
    directions = sorted([[int(f["local_device"]), int(f["peer_device"])]
                         for f in peer_features
                         if f.get("heap_device_local")
                         and f.get("copy_src") and f.get("copy_dst")])
    ext = capability.get("external_memory_matrix") or {}
    ext_any = any(
        row.get("exportable") or row.get("importable")
        for die in ext.get("dies", [])
        for row in list(die.get("buffer_matrix", []))
        + list(die.get("image_probes", [])))
    return {
        "multi_device_vega_group_present": group_ok,
        "peer_copy_directions": directions,
        "secondary_ext_memory_features": ext_any,
    }
