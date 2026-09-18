#!/usr/bin/env python3
"""Issue #216 terminal reducer: raw receipts -> assembly -> facts -> terminal."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from statistics import mean, median
from typing import Any

import issue216_assemble as assemble
import issue216_campaign_plan as campaign
import issue216_physical_authority as authority

ROOT = Path(__file__).resolve().parents[1]
AREA_REL = "docs/investigations/vulkan-v2-d-v340l-concurrent"


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def classify(facts: dict[str, Any], plan: dict[str, Any] | None = None) -> str:
    terms = (plan or campaign.build_plan())["terminals"]
    # Positive stress evidence wins over every missing later artifact.
    if facts.get("valid_concurrent_correctness") and facts.get("affirmative_stress_failure"):
        return terms["stress_fail"]
    if not facts.get("preflight_valid") or not facts.get("concurrency_established"):
        return terms["blocked"]
    if not facts.get("concurrent_correct"):
        return terms["correctness_fail"]
    if not facts.get("later_complete"):
        return terms["post_concurrency_incomplete"]
    return terms["pass"]


def _rows(data: dict[str, Any], schema: str) -> list[dict[str, Any]]:
    return [x for x in data["receipts"] if x["schema"] == schema]


def _interval_overlap(a: list[int], b: list[int]) -> bool:
    return len(a) == len(b) == 2 and max(a[0], b[0]) < min(a[1], b[1])


def _transport(samples: list[dict[str, Any]]) -> tuple[bool, dict[str, dict[str, float]]]:
    expected = {(mode, direction, size, repetition, participant)
                for mode in ("single-a", "single-b", "dual")
                for direction in ("h2d", "d2h")
                for size in (4096, 4 * 1024**2, 64 * 1024**2, 512 * 1024**2)
                for repetition in range(1, 6)
                for participant in (("a", "b") if mode == "dual" else (("a",) if mode == "single-a" else ("b",)))}
    observed = {(x["mode"], x["direction"], x["size_bytes"], x["repetition"], x["participant"]) for x in samples}
    groups: dict[str, list[float]] = {}
    for sample in samples:
        groups.setdefault(f"{sample['mode']}:{sample['direction']}:{sample['size_bytes']}", []).append(float(sample["measured_value"]))
    reductions = {key: {"count": len(values), "min": min(values), "max": max(values), "median": median(values), "mean": mean(values)} for key, values in groups.items()}
    return observed == expected, reductions


def facts_from_assembly(data: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    receipts = data["receipts"]
    preflight = _rows(data, "inferswarm.v2d.preflight-receipt/1")
    pairs = _rows(data, "inferswarm.v2d.concurrent-attempt/1")
    samples = _rows(data, "inferswarm.v2d.transport-sample/1")
    telemetry = sorted(_rows(data, "inferswarm.v2d.soak-telemetry/1"), key=lambda x: x.get("sequence", -1))
    checkpoints = _rows(data, "inferswarm.v2d.soak-checkpoint/1")
    soak = _rows(data, "inferswarm.v2d.soak-run/1")
    arms = _rows(data, "inferswarm.v2d.fault-isolation/1")
    resets = _rows(data, "inferswarm.v2d.reset-disposition/1")
    expected_ids = {"concurrent-1", "concurrent-2", "concurrent-3"}
    ids = {x["attempt_id"] for x in pairs}
    pair_overlap = bool(pairs) and all(_interval_overlap(x["workload_intervals_ns"]["a"], x["workload_intervals_ns"]["b"]) for x in pairs)
    concurrency_established = bool(pairs) and pair_overlap
    denominator_complete = expected_ids <= ids
    pair_ok = all(all(p["correctness"] is True and p["offload"] is True and p["fallback"] is False and p["accounting"] == [0, 0, 0] and p["clean_exit"] is True for p in row["participants"].values()) for row in pairs)
    valid_concurrent = concurrency_established and pair_ok
    matrix_ok, statistics = _transport(samples)
    soak_ok = False
    stress = False
    if len(soak) == 1:
        run = soak[0]
        duration = int(run.get("ended_monotonic_ns", 0)) - int(run.get("started_monotonic_ns", 0))
        cadence = int(run.get("telemetry_cadence_seconds", -1)); tolerance = int(run.get("allowed_scheduling_tolerance_seconds", -1))
        seq = [x.get("sequence") for x in telemetry]
        timestamps = [x.get("monotonic_ns") for x in telemetry]
        numeric_timestamps = [int(t) for t in timestamps if isinstance(t, int)]
        continuous = (seq == list(range(1, 62)) and len(set(numeric_timestamps)) == 61 and len(numeric_timestamps) == 61
                      and all((b-a) <= (cadence+tolerance) * 1_000_000_000 for a, b in zip(numeric_timestamps, numeric_timestamps[1:])))
        checkpoint_ids = {x.get("checkpoint_seconds") for x in checkpoints}
        soak_ok = duration >= 3600 * 1_000_000_000 and cadence == 60 and tolerance == 15 and continuous and checkpoint_ids == {0, 600, 1200, 1800, 2400, 3000, 3600} and run.get("final_sentinel_correct") is True
        stress = bool(run.get("raw_stress_events")) or any(x.get("amdgpu_reset") is True or x.get("fatal_aer") is True or x.get("uncorrected_ecc_growth") is True or x.get("worker_restarted") is True for x in telemetry)
    arm_ok = {x.get("arm") for x in arms} == {"a-loss-b-survives", "b-loss-a-survives"} and all(
        x.get("pre_health") is True and x.get("target_exited") is True and x.get("survivor_same_pid") is True and x.get("survivor_original_die") is True and x.get("survivor_no_fallback") is True and x.get("survivor_correctness") is True and x.get("relaunch_fresh_rebind") is True and x.get("per_die_recovery") is True and x.get("final_concurrent_sentinel") is True for x in arms)
    reset_ok = len(resets) == 1 and ((resets[0].get("disposition") == "DEVICE_RESET_ISOLATION_NOT_AVAILABLE" and resets[0].get("documented_support_absent") is True) or (resets[0].get("disposition") == "RESET_EXECUTED" and resets[0].get("documented_mechanism") and resets[0].get("post_reset_rediscovery") is True and resets[0].get("post_reset_independent_correctness") is True and resets[0].get("post_reset_concurrent_correctness") is True))
    later_complete = denominator_complete and matrix_ok and soak_ok and arm_ok and reset_ok
    return {
        "preflight_valid": len(preflight) == 1,
        "concurrency_established": concurrency_established,
        "concurrent_denominator_complete": denominator_complete,
        "concurrent_correct": valid_concurrent,
        "valid_concurrent_correctness": valid_concurrent,
        "affirmative_stress_failure": stress,
        "later_complete": later_complete,
        "transport_matrix_complete": matrix_ok,
        "transport_statistics": statistics,
        "soak_complete": soak_ok,
        "fault_arms_complete": arm_ok,
        "reset_disposition_complete": reset_ok,
        "source_receipt_identities": data["source_receipt_identities"],
    }


def reduce_tree(root: Path, authority_digest: str, *, fixture: bool = False, plan: dict[str, Any] | None = None) -> dict[str, Any]:
    manifest = assemble.build_input_manifest(root)
    data = assemble.assemble(root, manifest, authority_digest, fixture=fixture)
    current_plan = plan or campaign.build_plan()
    facts = facts_from_assembly(data, current_plan)
    return {"schema": "inferswarm.v2d.terminal-reduction/3", "campaign_id": data["campaign_id"], "fixture": fixture,
            "input_manifest_digest": manifest["manifest_digest"], "authority_digest": authority_digest,
            "facts": facts, "terminal": classify(facts, current_plan)}


def reduce(root: Path = ROOT) -> dict[str, Any]:
    area = root / AREA_REL
    plan_doc = json.loads((area / "CAMPAIGN-PLAN.json").read_text())
    plan = plan_doc["campaign_plan"]
    if plan_doc.get("campaign_plan_digest") != hashlib.sha256(canonical(plan)).hexdigest():
        raise ValueError("campaign plan digest mismatch")
    physical = json.loads((area / "PHYSICAL-AUTHORITY.json").read_text())
    if not authority.verify_authority(physical, root):
        raise ValueError("physical authority mismatch")
    return reduce_tree(area, physical["authority_digest"], plan=plan)


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--repo", default=str(ROOT)); ap.add_argument("--write", action="store_true")
    args = ap.parse_args(); result = reduce(Path(args.repo))
    if args.write:
        (Path(args.repo) / AREA_REL / "TERMINAL.json").write_bytes(json.dumps(result, indent=1, sort_keys=True).encode()+b"\n")
    print(json.dumps(result, indent=1, sort_keys=True)); return 0

if __name__ == "__main__":
    raise SystemExit(main())
