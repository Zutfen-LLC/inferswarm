#!/usr/bin/env python3
"""Issue #228 — V2-E deterministic reduction helpers.

Correction round (maintainer NO-GO on c9822fe):

* ``reduce_transfers`` now REQUIRES per-repeat correctness: every timed
  row must have a matching correctness row (same direction, same rep
  identity) whose ``ok`` is exactly true; duplicate rep ids, dropped
  reps, rep-set mismatch against the frozen repetition count, and any
  ``ok=false`` or ``correctness_fail`` row are ReduceErrors — a
  correctness failure can never become a functional terminal;
* ``reduce_route`` separates advertised capability from validated
  execution: without measured correct transfers there is no functional
  route conclusion at all;
* census verdicts come from probe.validate_capability_census — the
  reduction never re-derives capability from raw rows with looser
  rules than the validator.

Every reduction re-derives its output from PRIMARY RAW BYTES retained
under the evidence root. Nothing is taken from authored summaries.
"""
from __future__ import annotations

import json
import statistics
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


def reduce_transfers(records: list[dict[str, Any]], direction: str,
                     expected_reps: int | None = None,
                     ) -> dict[str, Any]:
    """Reduce one direction's timed rows to the frozen distribution
    summary, requiring per-repeat correctness evidence.

    Fail-closed on: zero timed rows; any correctness_fail row; any
    correctness row with ok != true; timed/correctness rep-set
    mismatch; duplicate rep ids; dropped reps (when ``expected_reps``
    is given, the rep set must be exactly 0..expected_reps-1); zero/
    negative times or bytes; mixed sizes.
    """
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
    not_ok = [r for r in checks if r.get("ok") is not True]
    if not_ok:
        raise ReduceError(
            f"correctness rows with ok != true for {direction}: "
            f"{[(r.get('rep'), r.get('ok')) for r in not_ok]}")
    timed_ids = [r.get("rep") for r in timed]
    check_ids = [r.get("rep") for r in checks]
    int_timed = sorted(int(i) for i in timed_ids if isinstance(i, int))
    if len(set(timed_ids)) != len(timed_ids):
        raise ReduceError(
            f"duplicate timed rep ids for {direction}: {timed_ids}")
    if len(set(check_ids)) != len(check_ids):
        raise ReduceError(
            f"duplicate correctness rep ids for {direction}: {check_ids}")
    if set(timed_ids) != set(check_ids):
        raise ReduceError(
            f"timed/correctness rep-set mismatch for {direction}: "
            f"timed={sorted(timed_ids)} correctness={sorted(check_ids)}")
    if expected_reps is not None:
        if timed_ids != list(range(expected_reps)):
            raise ReduceError(
                f"incomplete repetition set for {direction}: expected "
                f"reps 0..{expected_reps - 1}, saw {sorted(timed_ids)}")
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
        "correctness_reps": int_timed,
    }


def reduce_route(assembly: dict[str, Any]) -> dict[str, Any]:
    """Derive the route conclusion from retained evidence.

    Route vocabulary (issue Phase 6, never collapsed):
      LOCAL_SWITCH_BYPASS_PROVEN — needs per-port byte counters proving
        downstream activity without upstream activity;
      UPSTREAM_OR_HOST_ROUTE_PROVEN — counters/observations prove the
        host-facing path carried the peer traffic;
      PEER_FUNCTIONAL_ROUTE_UNRESOLVED — peer transfers functional but
        route evidence cannot distinguish;
      NO_PEER_TRANSFER_AVAILABLE — no peer mechanism existed to observe.

    Correction: a functional-route conclusion of any kind requires
    MEASURED CORRECT TRANSFERS; without them the only derivable
    conclusions are NO_PEER_TRANSFER_AVAILABLE or none at all.
    """
    mechanism = (assembly.get("mechanism") or {})
    transfers = assembly.get("validated_transfers")
    if not mechanism.get("available"):
        return {
            "route_conclusion": "NO_PEER_TRANSFER_AVAILABLE",
            "basis": "no peer-transfer mechanism was available to observe",
        }
    if not transfers:
        raise ReduceError(
            "mechanism available but no measured correct transfers "
            "retained; a functional route conclusion requires validated "
            "transfer evidence")
    route_counters = assembly.get("route_counters_available")
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


def rederive_capability_facts(verdict: dict[str, Any]) -> dict[str, Any]:
    """Reduction-side capability facts FROM A VALIDATED CENSUS VERDICT.

    The raw-row derivation of the rejected round lived here and
    accepted one-sided/duplicated/host-only evidence; it is replaced by
    consumption of probe.validate_capability_census output, which the
    assembler re-runs over the retained raw bytes.
    """
    if not verdict.get("census_valid"):
        return {"census_valid": False,
                "failure_reasons":
                    list(verdict.get("failure_reasons") or [])}
    peer = verdict.get("peer_features") or {}
    dirs = peer.get("directions") or {}
    return {
        "census_valid": True,
        "multi_device_vega_group_present":
            (verdict.get("group") or {}).get(
                "both_dies_in_one_group", False),
        "peer_copy_directions_present": sorted(
            str(d) for d, row in dirs.items() if row.get("present")),
        "secondary_ext_memory_features":
            bool((verdict.get("external_memory") or {}).get(
                "usable_handle_types")),
        "capable_mechanisms":
            list(verdict.get("capable_mechanisms") or []),
    }
