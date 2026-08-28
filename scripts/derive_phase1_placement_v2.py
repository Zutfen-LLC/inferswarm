#!/usr/bin/env python3
"""Derive the frozen Phase-1 v2 placement from canonical P0-I evidence only.

The historical v1 derivation remains in ``derive_phase1_placement.py``.  This
entrypoint verifies the same immutable raw artifacts, retains each measured
repetition separately, and selects the smallest primary-proxy tail overlap for
which every measured repetition has at least 20% static remote route coverage.

This is a placement derivation tool, not a candidate benchmark.  It must never
read Phase-1 runtime observations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from fractions import Fraction
from pathlib import Path
from typing import Any

from derive_phase1_placement import (
    BYTES_PER_SLOT,
    EXPECTED_SHA256,
    GPU0_PRIMARY_PROXY_SLOTS,
    MANIFEST_SHA256,
    MODEL_REPOSITORY,
    MODEL_REVISION,
    NUM_EXPERTS,
    NUM_LAYERS,
    REMOTE_BUDGET_BYTES,
    REMOTE_RESIDENT_BYTES,
    REMOTE_SLOTS,
    REQUIRED_CLASSES,
    TOTAL_SLOTS,
    check_source,
    identities_from_flat,
    per_layer,
    read_jsonl,
    sha256,
)

POLICY_ID = "phase1-qwen36-placement-v2"
CANONICAL_PLACEMENT = "coverage_constrained_complement_5442"
SCHEMA = "inferswarm.phase1.placement/1"
STATUS = "FROZEN_BEFORE_PHASE1_PERFORMANCE"
MEASURED_REPETITIONS_PER_CLASS = 10
PLACEMENT_FLOOR = Fraction(1, 5)
V1_ARTIFACT_SHA256 = "255dce5d335c5017de06eff54cfd1c8a0599d2dbd6c84c7fb0fb856701596a2c"


def _validate_histogram(histogram: Any, class_id: str, repetition: int) -> list[int]:
    if not isinstance(histogram, list) or len(histogram) != NUM_LAYERS:
        raise ValueError(
            f"{class_id} repetition {repetition} has invalid layer histogram"
        )
    flattened: list[int] = []
    for layer, experts in enumerate(histogram):
        if not isinstance(experts, list) or len(experts) != NUM_EXPERTS:
            raise ValueError(
                f"{class_id} repetition {repetition} layer {layer} "
                "has invalid expert histogram"
            )
        for value in experts:
            count = int(value or 0)
            if count < 0:
                raise ValueError("routing histogram contains a negative count")
            flattened.append(count)
    if len(flattened) != TOTAL_SLOTS:
        raise ValueError("flattened routing histogram has invalid slot count")
    return flattened


def load_repetition_histograms(run_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """Load exactly ten complete, non-truncated measured repetitions per class."""

    by_class: dict[str, dict[int, dict[str, Any]]] = {
        class_id: {} for class_id in REQUIRED_CLASSES
    }
    for row in read_jsonl(run_dir / "exact-routing.jsonl"):
        if row.get("record_type") != "measured_repetition":
            continue
        class_id = row.get("class_id")
        if class_id not in by_class:
            raise ValueError(f"unexpected measured class: {class_id!r}")
        if row.get("measured") is not True:
            raise ValueError(
                "measured_repetition record does not declare measured=true"
            )
        repetition = row.get("repetition")
        if not isinstance(repetition, int):
            raise TypeError(f"invalid repetition id for {class_id}: {repetition!r}")
        if repetition in by_class[class_id]:
            raise ValueError(f"duplicate {class_id} measured repetition {repetition}")
        completeness = row.get("trace_completeness") or {}
        if completeness.get("complete") is not True:
            raise ValueError(
                f"incomplete exact trace for {class_id} repetition {repetition}: "
                f"{completeness}"
            )
        trace = row.get("trace") or {}
        if trace.get("truncated") is not False:
            raise ValueError(
                f"truncated exact trace for {class_id} repetition {repetition}"
            )
        histogram = (row.get("routing") or {}).get("histogram")
        counts = _validate_histogram(histogram, class_id, repetition)
        total = sum(counts)
        if total <= 0:
            raise ValueError(
                f"{class_id} repetition {repetition} has no route selections"
            )
        by_class[class_id][repetition] = {
            "repetition": repetition,
            "counts": counts,
            "total_routes": total,
        }

    result: dict[str, list[dict[str, Any]]] = {}
    expected_ids = set(range(MEASURED_REPETITIONS_PER_CLASS))
    for class_id in REQUIRED_CLASSES:
        observed_ids = set(by_class[class_id])
        if observed_ids != expected_ids:
            raise ValueError(
                f"expected measured repetition ids 0-9 for {class_id}, "
                f"got {sorted(observed_ids)}"
            )
        result[class_id] = [
            by_class[class_id][repetition]
            for repetition in range(MEASURED_REPETITIONS_PER_CLASS)
        ]
    return result


def aggregate_repetitions(
    repetitions: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, list[int]], dict[str, int]]:
    counts_by_class: dict[str, list[int]] = {}
    totals_by_class: dict[str, int] = {}
    for class_id in REQUIRED_CLASSES:
        aggregate = [0] * TOTAL_SLOTS
        for repetition in repetitions[class_id]:
            counts = repetition["counts"]
            if len(counts) != TOTAL_SLOTS:
                raise ValueError(
                    f"{class_id} repetition has invalid flattened slot count"
                )
            for flat_id, count in enumerate(counts):
                aggregate[flat_id] += count
        total = sum(aggregate)
        if total <= 0:
            raise ValueError(f"{class_id} has no aggregate route selections")
        counts_by_class[class_id] = aggregate
        totals_by_class[class_id] = total
    return counts_by_class, totals_by_class


def rank_identities(
    counts_by_class: dict[str, list[int]], totals_by_class: dict[str, int]
) -> list[int]:
    ranking: list[tuple[Fraction, int, int]] = []
    for flat_id in range(TOTAL_SLOTS):
        score = sum(
            (
                Fraction(counts_by_class[class_id][flat_id], totals_by_class[class_id])
                for class_id in REQUIRED_CLASSES
            ),
            Fraction(0, 1),
        ) / len(REQUIRED_CLASSES)
        total_raw_count = sum(
            counts_by_class[class_id][flat_id] for class_id in REQUIRED_CLASSES
        )
        ranking.append((score, total_raw_count, flat_id))
    ranking.sort(key=lambda row: (-row[0], -row[1], row[2]))
    ordered = [row[2] for row in ranking]
    if len(ordered) != TOTAL_SLOTS or set(ordered) != set(range(TOTAL_SLOTS)):
        raise ValueError("ranking does not contain exactly one copy of every identity")
    return ordered


def candidate_window(ordered: list[int], overlap: int) -> list[int]:
    if len(ordered) != TOTAL_SLOTS or len(set(ordered)) != TOTAL_SLOTS:
        raise ValueError(
            "ordered ranking must contain exactly 10,240 unique identities"
        )
    if not 0 <= overlap <= GPU0_PRIMARY_PROXY_SLOTS:
        raise ValueError(f"overlap is outside valid range: {overlap}")
    start = GPU0_PRIMARY_PROXY_SLOTS - overlap
    end = start + REMOTE_SLOTS
    if not 0 <= start < end <= TOTAL_SLOTS:
        raise ValueError(f"candidate rank bounds are invalid: [{start}, {end})")
    candidate = ordered[start:end]
    if len(candidate) != REMOTE_SLOTS or len(set(candidate)) != REMOTE_SLOTS:
        raise ValueError("candidate window does not contain 5,442 unique identities")
    return candidate


def repetition_coverage(
    ids: set[int], repetitions: dict[str, list[dict[str, Any]]]
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for class_id in REQUIRED_CLASSES:
        rows = []
        for repetition in repetitions[class_id]:
            selected = sum(repetition["counts"][flat_id] for flat_id in ids)
            total = repetition["total_routes"]
            rows.append(
                {
                    "repetition": repetition["repetition"],
                    "selected_routes": selected,
                    "total_routes": total,
                    "coverage": selected / total,
                }
            )
        result[class_id] = rows
    return result


def all_repetitions_clear(
    coverage: dict[str, list[dict[str, Any]]], floor: Fraction = PLACEMENT_FLOOR
) -> bool:
    return all(
        row["selected_routes"] * floor.denominator
        >= row["total_routes"] * floor.numerator
        for class_id in REQUIRED_CLASSES
        for row in coverage[class_id]
    )


def find_minimum_overlap(
    ordered: list[int], repetitions: dict[str, list[dict[str, Any]]]
) -> tuple[int, dict[str, list[dict[str, Any]]]]:
    """Find the first qualifying overlap using exact integer comparisons."""

    candidate = candidate_window(ordered, 0)
    candidate_set = set(candidate)
    selected: dict[str, list[int]] = {}
    for class_id in REQUIRED_CLASSES:
        selected[class_id] = [
            sum(rep["counts"][flat_id] for flat_id in candidate_set)
            for rep in repetitions[class_id]
        ]

    def current_coverage() -> dict[str, list[dict[str, Any]]]:
        return {
            class_id: [
                {
                    "repetition": rep["repetition"],
                    "selected_routes": selected[class_id][index],
                    "total_routes": rep["total_routes"],
                    "coverage": selected[class_id][index] / rep["total_routes"],
                }
                for index, rep in enumerate(repetitions[class_id])
            ]
            for class_id in REQUIRED_CLASSES
        }

    coverage = current_coverage()
    if all_repetitions_clear(coverage):
        return 0, coverage

    for overlap in range(1, GPU0_PRIMARY_PROXY_SLOTS + 1):
        admitted = ordered[GPU0_PRIMARY_PROXY_SLOTS - overlap]
        displaced = ordered[GPU0_PRIMARY_PROXY_SLOTS + REMOTE_SLOTS - overlap]
        for class_id in REQUIRED_CLASSES:
            for index, rep in enumerate(repetitions[class_id]):
                counts = rep["counts"]
                selected[class_id][index] += counts[admitted] - counts[displaced]
        coverage = current_coverage()
        if all_repetitions_clear(coverage):
            return overlap, coverage
    raise ValueError("no coverage-constrained complement window satisfies the F2 floor")


def aggregate_coverage(
    ids: set[int],
    counts_by_class: dict[str, list[int]],
    totals_by_class: dict[str, int],
) -> dict[str, Any]:
    per_class: dict[str, dict[str, Any]] = {}
    selected_global = 0
    total_global = 0
    for class_id in REQUIRED_CLASSES:
        selected = sum(counts_by_class[class_id][flat_id] for flat_id in ids)
        total = totals_by_class[class_id]
        per_class[class_id] = {
            "selected_routes": selected,
            "total_routes": total,
            "coverage": selected / total,
        }
        selected_global += selected
        total_global += total
    return {
        "global": {
            "selected_routes": selected_global,
            "total_routes": total_global,
            "coverage": selected_global / total_global,
        },
        "per_class": per_class,
    }


def detailed_coverage_evidence(
    aggregate: dict[str, Any], repetitions: dict[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    per_class: dict[str, Any] = {}
    for class_id in REQUIRED_CLASSES:
        rows = repetitions[class_id]
        per_class[class_id] = {
            **aggregate["per_class"][class_id],
            "minimum_repetition_coverage": min(row["coverage"] for row in rows),
            "maximum_repetition_coverage": max(row["coverage"] for row in rows),
            "repetitions": rows,
        }
    return {"global": aggregate["global"], "per_class": per_class}


def validate_v1(v1_path: Path, ordered: list[int]) -> dict[str, Any]:
    if not v1_path.is_file():
        raise ValueError(f"missing historical v1 artifact: {v1_path}")
    actual_sha = sha256(v1_path)
    if actual_sha != V1_ARTIFACT_SHA256:
        raise ValueError(
            f"historical v1 artifact hash mismatch: expected {V1_ARTIFACT_SHA256}, "
            f"got {actual_sha}"
        )
    document = json.loads(v1_path.read_text(encoding="utf-8"))
    if document.get("schema") != SCHEMA:
        raise ValueError("historical v1 schema mismatch")
    if document.get("policy_id") != "phase1-qwen36-placement-v1":
        raise ValueError("historical v1 policy id mismatch")
    canonical_name = document.get("canonical_remote_placement")
    if canonical_name != "complement_5442":
        raise ValueError("historical v1 canonical placement mismatch")
    v1_ids = document["placements"][canonical_name]["flat_ids_in_rank_order"]
    if v1_ids != candidate_window(ordered, 0):
        raise ValueError("historical v1 placement is not rank window [3774, 9216)")
    return document


def build_artifact(
    run: dict[str, Any],
    ordered: list[int],
    overlap: int,
    qualifying_repetition_coverage: dict[str, list[dict[str, Any]]],
    counts_by_class: dict[str, list[int]],
    totals_by_class: dict[str, int],
    v1_document: dict[str, Any],
) -> dict[str, Any]:
    candidate = candidate_window(ordered, overlap)
    candidate_set = set(candidate)
    primary = ordered[:GPU0_PRIMARY_PROXY_SLOTS]
    primary_set = set(primary)
    v1 = candidate_window(ordered, 0)
    v1_set = set(v1)
    global_hot = ordered[:REMOTE_SLOTS]

    proxy_intersection = [flat_id for flat_id in candidate if flat_id in primary_set]
    v1_intersection = [flat_id for flat_id in candidate if flat_id in v1_set]
    v1_removed = [flat_id for flat_id in v1 if flat_id not in candidate_set]
    if len(proxy_intersection) != overlap:
        raise ValueError("primary-proxy intersection does not equal selected overlap")
    if len(v1_intersection) != REMOTE_SLOTS - overlap:
        raise ValueError("v1 retained count does not equal remote slots minus overlap")

    canonical_aggregate = aggregate_coverage(
        candidate_set, counts_by_class, totals_by_class
    )

    start = GPU0_PRIMARY_PROXY_SLOTS - overlap
    end = start + REMOTE_SLOTS
    selection_rule = (
        "minimum integer primary-proxy tail overlap such that every one of the "
        "10 measured repetitions of every W1-W4 class has remote route coverage >= 0.20"
    )
    return {
        "schema": SCHEMA,
        "policy_id": POLICY_ID,
        "status": STATUS,
        "canonical_remote_placement": CANONICAL_PLACEMENT,
        "source": {
            "model_repository": MODEL_REPOSITORY,
            "model_revision": MODEL_REVISION,
            "workload_manifest_sha256": MANIFEST_SHA256,
            "run_json_sha256": EXPECTED_SHA256["run.json"],
            "exact_routing_sha256": EXPECTED_SHA256["exact-routing.jsonl"],
            "cache_pressure_sha256": EXPECTED_SHA256["cache-pressure.jsonl"],
            "canonical_headline": run["headline"],
        },
        "geometry": {
            "num_moe_layers": NUM_LAYERS,
            "num_experts_per_layer": NUM_EXPERTS,
            "total_expert_slots": TOTAL_SLOTS,
        },
        "score": {
            "definition": "mean over W1-W4 of slot_count_in_class / total_routes_in_class",
            "tie_break": [
                "workload_balanced_score descending",
                "total raw count descending",
                "flat_id ascending",
            ],
        },
        "budget": {
            "bytes_per_slot": BYTES_PER_SLOT,
            "remote_budget_bytes": REMOTE_BUDGET_BYTES,
            "remote_slots": REMOTE_SLOTS,
            "remote_resident_bytes": REMOTE_RESIDENT_BYTES,
            "gpu0_primary_proxy_slots": GPU0_PRIMARY_PROXY_SLOTS,
        },
        "policy": {
            "placement_floor": float(PLACEMENT_FLOOR),
            "selection_rule": selection_rule,
            "measured_repetitions_per_class": MEASURED_REPETITIONS_PER_CLASS,
            "selected_overlap_slots": overlap,
            "rank_window_start": start,
            "rank_window_end_exclusive": end,
            "v1_complement_slots_retained": REMOTE_SLOTS - overlap,
            "v1_complement_slots_displaced": overlap,
            "primary_proxy_overlap_slots": overlap,
            "primary_proxy_overlap_fraction": overlap / REMOTE_SLOTS,
            "primary_proxy_overlap_fraction_denominator": "remote_slots",
            "primary_proxy_tail_fraction": overlap / GPU0_PRIMARY_PROXY_SLOTS,
        },
        "placements": {
            CANONICAL_PLACEMENT: {
                "slot_count": len(candidate),
                "flat_ids_in_rank_order": candidate,
                "identities_in_rank_order": identities_from_flat(candidate),
                "per_layer": per_layer(candidate),
                "coverage_evidence": detailed_coverage_evidence(
                    canonical_aggregate, qualifying_repetition_coverage
                ),
            }
        },
        "comparison_aggregate_coverage": {
            "gpu0_primary_proxy_3774": aggregate_coverage(
                primary_set, counts_by_class, totals_by_class
            ),
            "phase1_v1_complement_5442": aggregate_coverage(
                v1_set, counts_by_class, totals_by_class
            ),
            "global_hot_5442": aggregate_coverage(
                set(global_hot), counts_by_class, totals_by_class
            ),
        },
        "relationship_to_v1": {
            "v1_policy_id": v1_document["policy_id"],
            "v1_artifact_sha256": V1_ARTIFACT_SHA256,
            "v1_remote_slots_retained": len(v1_intersection),
            "v1_remote_slots_removed": len(v1_removed),
            "newly_admitted_from_primary_proxy": len(proxy_intersection),
            "primary_proxy_intersection": {
                "slot_count": len(proxy_intersection),
                "flat_ids_in_rank_order": proxy_intersection,
            },
            "v1_complement_intersection": {
                "slot_count": len(v1_intersection),
                "flat_ids_in_rank_order": v1_intersection,
            },
            "v1_complement_removed": {
                "slot_count": len(v1_removed),
                "flat_ids_in_rank_order": v1_removed,
            },
        },
        "privacy": {
            "contains_prompt_text": False,
            "contains_output_text": False,
            "contains_hostname": False,
            "contains_host_local_paths": False,
        },
    }


def artifact_bytes(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, indent=2) + "\n").encode("utf-8")


def derive(run_dir: Path, v1_path: Path) -> tuple[dict[str, Any], int]:
    run = check_source(run_dir)
    repetitions = load_repetition_histograms(run_dir)
    counts_by_class, totals_by_class = aggregate_repetitions(repetitions)
    ordered = rank_identities(counts_by_class, totals_by_class)
    v1_document = validate_v1(v1_path, ordered)
    overlap, qualifying_coverage = find_minimum_overlap(ordered, repetitions)
    if overlap > 0:
        prior = repetition_coverage(
            set(candidate_window(ordered, overlap - 1)), repetitions
        )
        if all_repetitions_clear(prior):
            raise ValueError("selected overlap is not minimal")
    artifact = build_artifact(
        run,
        ordered,
        overlap,
        qualifying_coverage,
        counts_by_class,
        totals_by_class,
        v1_document,
    )
    return artifact, overlap


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument(
        "--v1-artifact",
        type=Path,
        default=(
            Path(__file__).resolve().parents[1]
            / "docs/investigations/data/phase1-qwen36-placement-v1.json"
        ),
    )
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    out_dir = args.out_dir.resolve()
    v1_path = args.v1_artifact.resolve()

    # Derive and validate fully before creating the output directory or bytes.
    artifact, overlap = derive(run_dir, v1_path)
    payload = artifact_bytes(artifact)
    digest = hashlib.sha256(payload).hexdigest()

    out_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = out_dir / "phase1-qwen36-placement-v2.json"
    checksum_path = out_dir / "phase1-placement-v2.sha256.txt"
    artifact_path.write_bytes(payload)
    checksum_path.write_text(f"{digest}  {artifact_path.name}\n", encoding="utf-8")

    print("PHASE-1 V2 PLACEMENT DERIVATION COMPLETE")
    print(f"source: {run_dir}")
    print(f"v1 SHA-256: {V1_ARTIFACT_SHA256}")
    print(f"selected primary-proxy tail overlap: {overlap}")
    print(
        "rank window: "
        f"[{GPU0_PRIMARY_PROXY_SLOTS - overlap}, "
        f"{GPU0_PRIMARY_PROXY_SLOTS - overlap + REMOTE_SLOTS})"
    )
    print(f"placement: {artifact_path}")
    print(f"placement SHA-256: {digest}")
    print(f"checksums: {checksum_path}")
    coverage = artifact["placements"][CANONICAL_PLACEMENT]["coverage_evidence"]
    for class_id in REQUIRED_CLASSES:
        row = coverage["per_class"][class_id]
        print(
            f"{class_id}: aggregate={row['coverage']:.6%}; "
            f"minimum repetition={row['minimum_repetition_coverage']:.6%}; "
            f"maximum repetition={row['maximum_repetition_coverage']:.6%}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
