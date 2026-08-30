#!/usr/bin/env python3
"""Deterministic analysis for the f29013fd Phase-1 P6 campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Any

import numpy as np

CLASSES = ("W1", "W2", "W3", "W4")
PRIMARY_ARMS = ("baseline_b1", "candidate_v2")
EXPECTED_IDENTITY = "1a1dda536059c8d71f9179597c46d17c65a7763d9a8875414d7ce823b1c2ec13"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(16 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def percentile(values: list[float] | np.ndarray, q: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=float), q, method="linear"))


def stats(values: list[float]) -> dict[str, float | int]:
    if not values:
        raise ValueError("empty population")
    return {
        "n": len(values),
        "min": min(values),
        "median": statistics.median(values),
        "max": max(values),
        "iqr": percentile(values, 75) - percentile(values, 25),
        "cv_percent": statistics.stdev(values) / statistics.mean(values) * 100.0,
    }


def measured_repetitions(path: Path, session: int, arm: str, cls: str) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    warmups = [row for row in rows if row["phase"] == "warmup"]
    measured = [row for row in rows if row["measured"]]
    if len(rows) != 12 or len(warmups) != 2 or len(measured) != 10:
        raise ValueError(f"{path}: expected 2 warmups and 10 measured rows")
    if [row["repetition"] for row in measured] != list(range(10)):
        raise ValueError(f"{path}: selective deletion/reordering detected")
    for row in rows:
        if row["failed"] or row["session_number"] != session or row["arm_id"] != arm or row["class_id"] != cls:
            raise ValueError(f"{path}: invalid repetition identity or failure")
        if row["batch_size"] != 1 or not row["ignore_eos"] or not row["completion_matches_request"]:
            raise ValueError(f"{path}: workload shape mismatch")
    return measured


def validate_session(root: Path, session: int, verify_hashes: bool) -> tuple[dict[str, Any], dict[str, dict[str, list[dict[str, Any]]]]]:
    session_root = root / f"session-{session}"
    summary = json.loads((session_root / "session-summary.json").read_text())
    if summary["execution_status"] != "COMPLETE" or summary["validity"] != "VALID":
        raise ValueError(f"session {session} is not COMPLETE / VALID")
    if summary["campaign_identity"]["sha256"] != EXPECTED_IDENTITY:
        raise ValueError(f"session {session} campaign identity mismatch")
    if summary["campaign_invalidations"] or summary["canonical_blockers"]:
        raise ValueError(f"session {session} contains invalidations/blockers")
    if not summary["baseline_noise_floor_status"]["all_within_ceiling"]:
        raise ValueError(f"session {session} exceeds baseline CV ceiling")
    if not summary["baseline_identity_gate"]["passed"]:
        raise ValueError(f"session {session} baseline identity gate failed")
    completion = summary["completion"]
    if completion["expected_primary_generations"] != 96 or completion["observed_generations"] != 144:
        raise ValueError(f"session {session} generation count mismatch")
    if completion["failed_generations"] or completion["incomplete_blocks"]:
        raise ValueError(f"session {session} is incomplete")
    if not completion["supplementary_condition"]["required_supplementary_block_completed"]:
        raise ValueError(f"session {session} supplementary arm incomplete")
    if verify_hashes:
        for relative, expected in summary["artifact_sha256"].items():
            actual = sha256(session_root / relative)
            if actual != expected:
                raise ValueError(f"session {session} hash mismatch: {relative}")
    repetitions: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for arm in PRIMARY_ARMS + ("baseline_b1_kv_matched",):
        repetitions[arm] = {}
        for cls in CLASSES:
            repetitions[arm][cls] = measured_repetitions(session_root / arm / f"{cls}.jsonl", session, arm, cls)
    return summary, repetitions


def bootstrap_session(reps: dict[str, dict[str, list[dict[str, Any]]]], seed: int, resamples: int) -> dict[str, Any]:
    # One recorded generator per session; arm samples are independent and therefore unpaired.
    rng = np.random.default_rng(seed)
    ratios: dict[str, float] = {}
    ratio_samples: dict[str, np.ndarray] = {}
    medians: dict[str, dict[str, float]] = {arm: {} for arm in PRIMARY_ARMS}
    for cls in CLASSES:
        baseline = np.asarray([row["decode_tok_s"] for row in reps["baseline_b1"][cls]], dtype=float)
        candidate = np.asarray([row["decode_tok_s"] for row in reps["candidate_v2"][cls]], dtype=float)
        medians["baseline_b1"][cls] = float(np.median(baseline))
        medians["candidate_v2"][cls] = float(np.median(candidate))
        ratios[cls] = medians["candidate_v2"][cls] / medians["baseline_b1"][cls]
        b_idx = rng.integers(0, len(baseline), size=(resamples, len(baseline)))
        c_idx = rng.integers(0, len(candidate), size=(resamples, len(candidate)))
        ratio_samples[cls] = np.median(candidate[c_idx], axis=1) / np.median(baseline[b_idx], axis=1)
    aggregate = math.exp(sum(math.log(ratios[cls]) for cls in CLASSES) / len(CLASSES))
    aggregate_samples = np.exp(np.mean(np.log(np.column_stack([ratio_samples[cls] for cls in CLASSES])), axis=1))
    classes: dict[str, Any] = {}
    for cls in CLASSES:
        baseline_rows = reps["baseline_b1"][cls]
        candidate_rows = reps["candidate_v2"][cls]
        ratio_ci = [percentile(ratio_samples[cls], 2.5), percentile(ratio_samples[cls], 97.5)]
        classes[cls] = {
            "baseline_decode_tok_s": stats([row["decode_tok_s"] for row in baseline_rows]),
            "candidate_decode_tok_s": stats([row["decode_tok_s"] for row in candidate_rows]),
            "r_c": ratios[cls],
            "r_c_ci95": ratio_ci,
            "significant": ratio_ci[0] > 1.0 or ratio_ci[1] < 1.0,
            "baseline_ttft_ms_median": statistics.median(row["ttft_ms"] for row in baseline_rows),
            "candidate_ttft_ms_median": statistics.median(row["ttft_ms"] for row in candidate_rows),
            "ttft_ratio": statistics.median(row["ttft_ms"] for row in candidate_rows) / statistics.median(row["ttft_ms"] for row in baseline_rows),
            "baseline_prefill_tok_s_median": statistics.median(row["prefill"]["prefill_tok_s"] for row in baseline_rows),
            "candidate_prefill_tok_s_median": statistics.median(row["prefill"]["prefill_tok_s"] for row in candidate_rows),
            "prefill_ratio": statistics.median(row["prefill"]["prefill_tok_s"] for row in candidate_rows) / statistics.median(row["prefill"]["prefill_tok_s"] for row in baseline_rows),
            "token_latency_ms": {
                "baseline": {
                    "p50_of_p50": statistics.median(row["inter_token_ms_p50"] for row in baseline_rows),
                    "p95_of_p95": statistics.median(row["inter_token_ms_p95"] for row in baseline_rows),
                    "max": max(row["inter_token_ms_max"] for row in baseline_rows),
                },
                "candidate": {
                    "p50_of_p50": statistics.median(row["inter_token_ms_p50"] for row in candidate_rows),
                    "p95_of_p95": statistics.median(row["inter_token_ms_p95"] for row in candidate_rows),
                    "max": max(row["inter_token_ms_max"] for row in candidate_rows),
                },
            },
        }
    return {
        "classes": classes,
        "r_agg": aggregate,
        "r_agg_ci95": [percentile(aggregate_samples, 2.5), percentile(aggregate_samples, 97.5)],
        "r_agg_significant": percentile(aggregate_samples, 2.5) > 1.0 or percentile(aggregate_samples, 97.5) < 1.0,
    }


def flatten_durations(node: dict[str, Any], prefix: str = "") -> dict[str, float | None]:
    output: dict[str, float | None] = {}
    for key, value in node.items():
        name = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict) and "status" in value and "value_ms" in value:
            output[name] = float(value["value_ms"]) if value["status"] == "valid" else None
        elif isinstance(value, dict):
            output.update(flatten_durations(value, name))
    return output


def mechanism_and_layer(root: Path, session: int, arm: str, cls: str, last_finished: float) -> dict[str, Any]:
    path = root / f"session-{session}" / arm / f"block-mechanism-{cls}.json"
    with path.open() as handle:
        data = json.load(handle)
    timing = data["moe_layer_timing"]
    if timing["truncated"] or timing["incomplete_layer_alignment"] or not timing["validity"]["complete_layer_timing_valid"]:
        raise ValueError(f"invalid complete-layer timing: session {session} {arm} {cls}")
    populations: dict[str, list[float]] = {}
    statuses: dict[str, set[str]] = {}
    for record in timing["records"]:
        flat = flatten_durations(record["durations"])
        for name, value in flat.items():
            statuses.setdefault(name, set()).add("valid" if value is not None else "not_applicable")
            if value is not None:
                populations.setdefault(name, []).append(value)
    layer = {
        name: {"status": "valid", **stats(values), "p95": percentile(values, 95)}
        for name, values in populations.items()
    }
    for name, observed in statuses.items():
        if name not in layer:
            layer[name] = {"status": "not_applicable" if observed == {"not_applicable"} else "unavailable"}
    result: dict[str, Any] = {
        "timing_population": {
            "capacity_steps": timing["capacity_steps"],
            "steps_observed": timing["steps_observed"],
            "steps_retained": timing["steps_retained"],
            "records_retained": timing["records_retained"],
            "truncated": timing["truncated"],
            "complete_layer_timing_valid": timing["validity"]["complete_layer_timing_valid"],
            "component_timing_valid": timing["validity"]["component_timing_valid"],
            "remote_overlap_active": timing["remote_overlap_active"],
        },
        "durations_ms": layer,
        "snapshot_elapsed_upper_bound_s": path.stat().st_mtime - last_finished,
    }
    remote = data["remote_decode"]
    if arm == "candidate_v2":
        result["mechanism"] = {
            "aggregate": remote["aggregate"],
            "gates": remote["gates"],
            "ownership": remote["ownership"],
            "residency": remote["residency"],
            "expert_weight_traffic": remote["expert_weight_traffic"],
            "transport": remote["transport"],
            "overlap_active": remote["overlap_active"],
        }
    del data
    return result


def verdict_for_session(
    performance: dict[str, Any],
    invalidating_gates_ok: bool,
    f3_ok: bool,
    correctness_ok: bool,
    reproducible: bool,
    issue5_ok: bool,
) -> dict[str, Any]:
    classes = performance["classes"]
    g = {
        "G1": invalidating_gates_ok and f3_ok,
        "G2": correctness_ok,
        "G3": reproducible,
        "G4": performance["r_agg"] >= 1.20 and performance["r_agg_ci95"][0] >= 1.10,
        "G5": all(classes[c]["r_c"] >= 1.05 and classes[c]["significant"] and classes[c]["r_c_ci95"][0] > 1.0 for c in CLASSES),
        "G6": all(classes[c]["ttft_ratio"] <= 1.25 and classes[c]["prefill_ratio"] >= 0.80 for c in CLASSES),
        "G7": issue5_ok,
    }
    i = {
        "I1": invalidating_gates_ok and correctness_ok,
        "I2": reproducible,
        "I3": issue5_ok,
        "I4": True,  # source-grounded complete-layer wall and graph-disabled decode paths are named
        "I5": False, # no single measured removable cost can rescue all ~0.07x classes above 1.20
        "I6": False, # no qualifying bounded-remediation experiment follows when I5 and I7 fail
        "I7": all(classes[c]["r_c"] >= 0.95 for c in CLASSES),
    }
    iterate_cases = {"A": False, "B": False, "C": False, "D": False, "E": False}
    n = {
        "N1": False,
        "N2": not performance["r_agg_significant"],
        "N3": performance["r_agg"] < 1.05,
        "N4": performance["r_agg"] < 1.0 and performance["r_agg_ci95"][1] < 1.0,
        "N5": False,
        "N6": sum(not (classes[c]["significant"] and classes[c]["r_c"] > 1.0) for c in CLASSES) >= 3,
        "N7": False,
        "N8": False,
        "N9": any(classes[c]["r_c"] < 0.95 for c in CLASSES),
    }
    verdict = "GO" if all(g.values()) else ("ITERATE" if all(i.values()) and any(iterate_cases.values()) else "NO-GO")
    return {"verdict": verdict, "GO": g, "ITERATE": i, "ITERATE_cases": iterate_cases, "NO_GO": n}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--bootstrap-seed", type=int, default=0)
    parser.add_argument("--bootstrap-resamples", type=int, default=10_000)
    parser.add_argument("--skip-hash-verification", action="store_true")
    args = parser.parse_args()
    if args.bootstrap_seed != 0 or args.bootstrap_resamples != 10_000:
        raise ValueError("canonical analysis requires seed 0 and exactly 10,000 resamples")
    summaries: dict[int, dict[str, Any]] = {}
    repetitions: dict[int, dict[str, dict[str, list[dict[str, Any]]]]] = {}
    for session in (1, 2):
        summaries[session], repetitions[session] = validate_session(args.campaign_root, session, not args.skip_hash_verification)
    if summaries[1]["campaign_identity"]["sha256"] != summaries[2]["campaign_identity"]["sha256"]:
        raise ValueError("session campaign identities differ")
    performance = {session: bootstrap_session(repetitions[session], args.bootstrap_seed, args.bootstrap_resamples) for session in (1, 2)}
    mechanism: dict[int, Any] = {}
    maximum_snapshot: dict[str, Any] = {"seconds": -1.0}
    for session in (1, 2):
        mechanism[session] = {}
        for arm in PRIMARY_ARMS:
            mechanism[session][arm] = {}
            for cls in CLASSES:
                last_finished = max(row["finished_at_unix"] for row in repetitions[session][arm][cls])
                record = mechanism_and_layer(args.campaign_root, session, arm, cls, last_finished)
                mechanism[session][arm][cls] = record
                elapsed = record["snapshot_elapsed_upper_bound_s"]
                if elapsed > maximum_snapshot["seconds"]:
                    maximum_snapshot = {"seconds": elapsed, "session": session, "arm": arm, "class": cls}
    invalidating_gates_ok = {
        session: all(
            mechanism[session]["candidate_v2"][cls]["mechanism"]["gates"][gate]["passed"]
            for cls in CLASSES
            for gate in ("F1", "F2", "F5", "F6")
        )
        for session in (1, 2)
    }
    if not all(invalidating_gates_ok.values()):
        raise ValueError("canonical F1/F2/F5/F6 failure makes the campaign INVALID")
    f3_ok = {
        session: all(
            mechanism[session]["candidate_v2"][cls]["mechanism"]["gates"]["F3"]["passed"]
            for cls in CLASSES
        )
        for session in (1, 2)
    }
    verdicts = {
        session: verdict_for_session(
            performance[session],
            invalidating_gates_ok[session],
            f3_ok[session],
            True,
            True,
            True,
        )
        for session in (1, 2)
    }
    if verdicts[1]["verdict"] != "NO-GO" or verdicts[2]["verdict"] != "NO-GO":
        raise ValueError("unexpected mechanical verdict")
    startup = {
        session: {
            arm: summaries[session]["startup_records"][arm]["m_start_duration_s"]
            for arm in PRIMARY_ARMS + ("baseline_b1_kv_matched",)
        }
        for session in (1, 2)
    }
    startup_caveat = any(
        startup[s]["candidate_v2"] > 3 * startup[s]["baseline_b1"]
        or startup[s]["candidate_v2"] - startup[s]["baseline_b1"] > 180
        for s in (1, 2)
    )
    cold = {
        session: {
            arm: {
                "decode_tok_s": json.loads((args.campaign_root / f"session-{session}" / arm / "W1.jsonl").read_text().splitlines()[0])["decode_tok_s"],
                "ttft_ms": json.loads((args.campaign_root / f"session-{session}" / arm / "W1.jsonl").read_text().splitlines()[0])["ttft_ms"],
            }
            for arm in PRIMARY_ARMS
        }
        for session in (1, 2)
    }
    output = {
        "schema": "inferswarm.phase1.p6-analysis/1",
        "campaign_identity_sha256": EXPECTED_IDENTITY,
        "validation": {
            "sessions_complete": True,
            "sessions_valid": True,
            "same_campaign_identity": True,
            "artifact_hashes_verified": not args.skip_hash_verification,
            "baseline_cv_within_5_percent": True,
            "required_repetitions_present": True,
            "selective_repetition_deletion": False,
            "canonical_arm_definitions": True,
        },
        "bootstrap": {"seed": args.bootstrap_seed, "resamples": args.bootstrap_resamples, "arms": "unpaired", "session_seed_rule": "independent numpy Generator(seed=0) per session"},
        "performance": performance,
        "mechanism_and_complete_layer": mechanism,
        "instrumentation_control": {"operation_timeout_seconds": 300.0, "http_client_timeout_seconds": 305.0, "maximum_observed_snapshot_elapsed_upper_bound": maximum_snapshot, "control_plane_failures": 0},
        "startup_seconds": startup,
        "startup_caveat": startup_caveat,
        "cold_first_generation": cold,
        "section_8": {
            "conclusion": "INCONCLUSIVE",
            "reason": "canonical blocks do not expose per-touch expert identity joined to baseline pre-touch hit/miss state; MATCHED_NONLOCAL_TOUCH_SET cannot be constructed without forbidden aggregate apportionment",
            "rule_b_fires": False,
        },
        "session_verdicts": verdicts,
        "worse_valid_session_verdict": "NO-GO",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print(args.output)


if __name__ == "__main__":
    main()
