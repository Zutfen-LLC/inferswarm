#!/usr/bin/env python3
"""Issue #216 — V2-D terminal reducer.

Reduces the prospectively frozen campaign record into exactly one V2-D terminal.
The record is assembled by the dedicated collectors from retained receipts; this
module never turns a throughput loss into a correctness failure and never
promotes two independent 8-GiB resources into a coherent 16-GiB resource.
It supports an environment root seam for isolated mutation controls only.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from issue216_campaign_plan import build_plan, plan_document

ROOT_ENV = "INFERSWARM_ISSUE216_ROOT"
NS = "vulkan-v2-d-v340l-concurrent"
CLEAN_ACCOUNTING = ("unexplained_persistent_host_mirror_bytes", "source_fetches_after_ready",
                    "unplanned_state_movements")


class ReductionError(RuntimeError):
    pass


def _clean_participant(p: dict[str, Any], expected_die: str, expected_selector: str,
                       expected_bdf: str) -> bool:
    accounting = p.get("accounting") or {}
    return (p.get("die") == expected_die and p.get("selector") == expected_selector
            and p.get("bdf") == expected_bdf and p.get("result") == "PASS"
            and p.get("full_offload") is True and p.get("byte_exact") is True
            and p.get("clean_exit") is True and p.get("finite_output") is True
            and p.get("fallback") is False
            and all(accounting.get(k) == 0 for k in CLEAN_ACCOUNTING))


def _participants_clean(pair: dict[str, Any], plan: dict[str, Any]) -> bool:
    resources = plan["physical_resources"]
    a = pair.get("a") or {}
    b = pair.get("b") or {}
    return (_clean_participant(a, "a", resources["a"]["selector"], resources["a"]["expected_bdf"])
            and _clean_participant(b, "b", resources["b"]["selector"], resources["b"]["expected_bdf"])
            and a.get("bdf") != b.get("bdf") and a.get("selector") != b.get("selector"))


def _overlap(intervals: dict[str, Any]) -> bool:
    try:
        a0, a1 = intervals["a"]
        b0, b1 = intervals["b"]
        return isinstance(a0, int) and isinstance(a1, int) and isinstance(b0, int) and isinstance(b1, int) and max(a0, b0) < min(a1, b1)
    except (KeyError, TypeError, ValueError):
        return False


def _required_samples(soak: dict[str, Any], plan: dict[str, Any]) -> int:
    duration = plan["soak"]["minimum_duration_seconds"]
    cadence = plan["soak"]["telemetry_cadence_seconds"]
    return duration // cadence + 1


def reduce_record(record: dict[str, Any], plan: dict[str, Any] | None = None) -> dict[str, Any]:
    """Derive terminal status from a normalized record whose entries are bound
    to retained collector receipts. No caller-provided PASS field is trusted;
    every required predicate is recomputed here."""
    plan = plan or build_plan()
    checks: dict[str, bool] = {}
    preflight = record.get("preflight") or {}
    checks["preflight"] = (preflight.get("result") == "PASS"
                            and preflight.get("predecessors_preserved") is True
                            and preflight.get("two_distinct_dies") is True
                            and preflight.get("gen3_x1_topology") is True)

    baselines = record.get("baselines") or {}
    checks["baselines"] = all(len(baselines.get(die, [])) >= 3
                              and all(_clean_participant(p, die,
                                                         plan["physical_resources"][die]["selector"],
                                                         plan["physical_resources"][die]["expected_bdf"])
                                      for p in baselines.get(die, []))
                              for die in ("a", "b"))

    repeats = record.get("concurrent") or []
    expected_ids = [f"repeat-{n}" for n in range(1, plan["concurrent"]["retained_repetitions"] + 1)]
    checks["concurrent_repetitions"] = [r.get("id") for r in repeats] == expected_ids
    checks["concurrent_participants"] = bool(repeats) and all(
        r.get("status") == "PASS" and _participants_clean(r.get("participants") or {}, plan) for r in repeats)
    checks["actual_temporal_overlap"] = bool(repeats) and all(_overlap(r.get("intervals_ns") or {}) for r in repeats)
    valid_concurrent = all(checks[k] for k in ("concurrent_repetitions", "concurrent_participants", "actual_temporal_overlap"))

    transport = record.get("transport") or {}
    checks["transport"] = (transport.get("modes") == plan["transport"]["modes"]
                            and transport.get("directions") == plan["transport"]["directions"]
                            and transport.get("all_required_sizes_present") is True
                            and transport.get("uncertainty_present") is True
                            and transport.get("under_load_link_state") is True)

    soak = record.get("soak") or {}
    checks["soak_duration"] = soak.get("duration_seconds") >= plan["soak"]["minimum_duration_seconds"]
    checks["telemetry_continuity"] = (soak.get("telemetry_cadence_seconds") == plan["soak"]["telemetry_cadence_seconds"]
                                      and soak.get("telemetry_samples", 0) >= _required_samples(soak, plan)
                                      and soak.get("continuous_liveness") is True and soak.get("silent_restart") is False)
    checks["soak_health"] = all(soak.get(k) is False for k in (
        "fatal_aer", "amdgpu_fault", "uncorrected_ecc_ras_growth", "thermal_alarm", "host_peripheral_failure"))
    required_sentinels = plan["soak"]["minimum_duration_seconds"] // plan["soak"]["sentinel_checkpoint_seconds"] + 1
    checks["soak_sentinels"] = len(soak.get("sentinels") or []) >= required_sentinels and all(x == "PASS" for x in soak.get("sentinels") or [])

    isolation = record.get("fault_isolation") or {}
    checks["fault_isolation"] = (isolation.get("a-loss-b-survives") == "PASS"
                                  and isolation.get("b-loss-a-survives") == "PASS"
                                  and isolation.get("final_concurrent_sentinel") == "PASS")
    reset = record.get("device_reset") or {}
    checks["reset_disposition"] = reset.get("result") in (
        plan["device_reset"]["unsupported_terminal"], "PASS")
    scope = record.get("claim_scope") or {}
    checks["nonclaims"] = all(scope.get(k) is False for k in (
        "aggregate_16gib", "model_program", "planner_policy", "slowdown_is_correctness_failure"))

    if not checks["preflight"]:
        terminal = plan["terminals"]["blocked"]
    elif not valid_concurrent or not checks["baselines"]:
        terminal = plan["terminals"]["correctness_fail"]
    elif not all(checks[k] for k in ("transport", "soak_duration", "telemetry_continuity", "soak_health",
                                     "soak_sentinels", "fault_isolation", "reset_disposition", "nonclaims")):
        # After valid concurrent correctness, any failed or missing sustained
        # evidence is a stress failure; BLOCKED cannot erase observed output.
        terminal = plan["terminals"]["stress_fail"]
    else:
        terminal = plan["terminals"]["pass"]
    return {"schema": "inferswarm.v2d.terminal-reduction/1", "campaign_id": plan["campaign_id"],
            "checks": checks, "terminal": terminal}


def _root() -> Path:
    return Path(os.environ[ROOT_ENV]) if os.environ.get(ROOT_ENV) else Path(__file__).resolve().parents[1]


def main() -> int:
    root = _root()
    area = root / "docs" / "investigations" / NS
    doc = json.loads((area / "CAMPAIGN-PLAN.json").read_text(encoding="utf-8"))
    expected = plan_document()["campaign_plan_digest"]
    if doc.get("campaign_plan_digest") != expected:
        raise ReductionError("campaign plan digest does not bind the committed frozen plan")
    record = json.loads((area / "CAMPAIGN-RECORD.json").read_text(encoding="utf-8"))
    result = reduce_record(record, doc["campaign_plan"])
    (area / "TERMINAL.json").write_text(json.dumps(result, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"terminal": result["terminal"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
