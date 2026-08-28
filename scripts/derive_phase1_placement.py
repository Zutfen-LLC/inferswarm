#!/usr/bin/env python3
"""Derive sanitized P0-I routing evidence and the frozen Phase-1 placement.

This is a publication/derivation tool, not a benchmark. It consumes the byte-preserved
canonical P0-I run, verifies the fixed source hashes and canonical verdict, then emits only
count/identity data suitable for the public InferSwarm repository.

No prompt text, generated output text, hostname, model path, or server logs are copied.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
from fractions import Fraction
from pathlib import Path
from typing import Any

POLICY_ID = "phase1-qwen36-placement-v1"
MODEL_REPOSITORY = "nvidia/Qwen3.6-35B-A3B-NVFP4"
MODEL_REVISION = "491c2f1ea524c639598bf8fa787a93fed5a6fbce"
MANIFEST_SHA256 = "10f81e5418a71a68f387632de422c3337cc7ba0518111a8746ad856d0210b24a"

EXPECTED_SHA256 = {
    "run.json": "1ecd14c8c157eb6cde62f8514b8f2af82a36dfe69e3a7241f5be6c9908e539dc",
    "exact-routing.jsonl": "4071e2bfd3c18f39e5c5a0b5ff8913ca0fb99b843cf7abca0ecc1f4ebd0a252f",
    "cache-pressure.jsonl": "f02d96a079a6af94b3fec9d2c571322a1274cd408a3a9ff2ef162f538babab3a",
}

REQUIRED_CLASSES = ("W1", "W2", "W3", "W4")
NUM_LAYERS = 40
NUM_EXPERTS = 256
TOTAL_SLOTS = NUM_LAYERS * NUM_EXPERTS
GPU0_PRIMARY_PROXY_SLOTS = 3774
BYTES_PER_SLOT = 1_775_616
REMOTE_BUDGET_BYTES = 9 * 1024**3
REMOTE_SLOTS = REMOTE_BUDGET_BYTES // BYTES_PER_SLOT
REMOTE_RESIDENT_BYTES = REMOTE_SLOTS * BYTES_PER_SLOT

assert REMOTE_SLOTS == 5442
assert GPU0_PRIMARY_PROXY_SLOTS + REMOTE_SLOTS == 9216


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path: Path):
    with path.open(encoding="utf-8") as source:
        for lineno, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{lineno}: {exc}") from exc


def check_source(run_dir: Path) -> dict[str, Any]:
    for name, expected in EXPECTED_SHA256.items():
        path = run_dir / name
        if not path.is_file():
            raise ValueError(f"missing canonical source artifact: {path}")
        actual = sha256(path)
        if actual != expected:
            raise ValueError(
                f"canonical source hash mismatch for {name}: expected {expected}, got {actual}"
            )

    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    if run.get("headline") != "VALID CANONICAL CAMPAIGN":
        raise ValueError(f"unexpected canonical headline: {run.get('headline')!r}")
    if run.get("execution_status") != "COMPLETE" or run.get("validity") != "VALID":
        raise ValueError(
            f"source run is not COMPLETE/VALID: "
            f"{run.get('execution_status')!r}/{run.get('validity')!r}"
        )
    observations = run.get("observations") or {}
    if observations.get("expected") != 288 or observations.get("observed") != 288:
        raise ValueError(f"unexpected source observation counts: {observations}")
    return run


def load_histograms(run_dir: Path):
    class_counts = {
        class_id: [[0 for _ in range(NUM_EXPERTS)] for _ in range(NUM_LAYERS)]
        for class_id in REQUIRED_CLASSES
    }
    repetitions = collections.Counter()

    for row in read_jsonl(run_dir / "exact-routing.jsonl"):
        if row.get("record_type") != "measured_repetition":
            continue
        class_id = row.get("class_id")
        if class_id not in class_counts:
            raise ValueError(f"unexpected measured class: {class_id!r}")
        if row.get("measured") is not True:
            raise ValueError("measured_repetition record does not declare measured=true")
        completeness = row.get("trace_completeness") or {}
        if completeness.get("complete") is not True:
            raise ValueError(
                f"incomplete exact trace for {class_id} repetition {row.get('repetition')}: "
                f"{completeness}"
            )
        trace = row.get("trace") or {}
        if trace.get("truncated") is not False:
            raise ValueError(
                f"truncated exact trace for {class_id} repetition {row.get('repetition')}"
            )
        histogram = (row.get("routing") or {}).get("histogram")
        if not isinstance(histogram, list) or len(histogram) != NUM_LAYERS:
            raise ValueError(
                f"{class_id} repetition {row.get('repetition')} has invalid layer histogram"
            )
        for layer, experts in enumerate(histogram):
            if not isinstance(experts, list) or len(experts) != NUM_EXPERTS:
                raise ValueError(
                    f"{class_id} repetition {row.get('repetition')} layer {layer} "
                    "has invalid expert histogram"
                )
            target = class_counts[class_id][layer]
            for expert, value in enumerate(experts):
                count = int(value or 0)
                if count < 0:
                    raise ValueError("routing histogram contains a negative count")
                target[expert] += count
        repetitions[class_id] += 1

    for class_id in REQUIRED_CLASSES:
        if repetitions[class_id] != 10:
            raise ValueError(
                f"expected 10 measured exact repetitions for {class_id}, "
                f"got {repetitions[class_id]}"
            )

    totals = {
        class_id: sum(sum(layer) for layer in class_counts[class_id])
        for class_id in REQUIRED_CLASSES
    }
    if any(total <= 0 for total in totals.values()):
        raise ValueError(f"one or more classes have no routing selections: {totals}")
    return class_counts, totals


def flat_id(layer: int, expert: int) -> int:
    return layer * NUM_EXPERTS + expert


def identities_from_flat(ids: list[int]) -> list[dict[str, int]]:
    return [
        {
            "flat_id": value,
            "layer": value // NUM_EXPERTS,
            "expert_id": value % NUM_EXPERTS,
        }
        for value in ids
    ]


def per_layer(ids: list[int]) -> list[dict[str, Any]]:
    grouped = [[] for _ in range(NUM_LAYERS)]
    for value in ids:
        grouped[value // NUM_EXPERTS].append(value % NUM_EXPERTS)
    return [
        {"layer": layer, "expert_ids": sorted(experts)}
        for layer, experts in enumerate(grouped)
    ]


def placement_coverage(ids: set[int], class_counts, class_totals):
    per_class = {}
    selected_global = 0
    total_global = sum(class_totals.values())
    for class_id in REQUIRED_CLASSES:
        selected = 0
        matrix = class_counts[class_id]
        for value in ids:
            selected += matrix[value // NUM_EXPERTS][value % NUM_EXPERTS]
        total = class_totals[class_id]
        per_class[class_id] = {
            "selected_routes": selected,
            "total_routes": total,
            "coverage": selected / total,
        }
        selected_global += selected
    return {
        "global": {
            "selected_routes": selected_global,
            "total_routes": total_global,
            "coverage": selected_global / total_global,
        },
        "per_class": per_class,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    run = check_source(run_dir)
    class_counts, class_totals = load_histograms(run_dir)

    ranking = []
    for layer in range(NUM_LAYERS):
        for expert in range(NUM_EXPERTS):
            counts = {
                class_id: class_counts[class_id][layer][expert]
                for class_id in REQUIRED_CLASSES
            }
            # Exact rational score: equal contribution from each workload class.
            score = sum(
                (Fraction(counts[class_id], class_totals[class_id]) for class_id in REQUIRED_CLASSES),
                Fraction(0, 1),
            ) / len(REQUIRED_CLASSES)
            ranking.append(
                {
                    "flat_id": flat_id(layer, expert),
                    "layer": layer,
                    "expert_id": expert,
                    "counts": counts,
                    "total_count": sum(counts.values()),
                    "score": score,
                }
            )

    ranking.sort(
        key=lambda row: (
            -row["score"],
            -row["total_count"],
            row["flat_id"],
        )
    )
    ordered = [row["flat_id"] for row in ranking]
    if len(ordered) != TOTAL_SLOTS or len(set(ordered)) != TOTAL_SLOTS:
        raise ValueError("ranking does not contain exactly one copy of every expert identity")

    primary = ordered[:GPU0_PRIMARY_PROXY_SLOTS]
    global_hot = ordered[:REMOTE_SLOTS]
    primary_set = set(primary)
    complement = [value for value in ordered if value not in primary_set][:REMOTE_SLOTS]

    if len(primary) != GPU0_PRIMARY_PROXY_SLOTS:
        raise ValueError("primary proxy slot count mismatch")
    if len(global_hot) != REMOTE_SLOTS or len(complement) != REMOTE_SLOTS:
        raise ValueError("remote slot count mismatch")
    if set(primary) & set(complement):
        raise ValueError("canonical complement overlaps primary proxy")

    histogram_rows = []
    for row in sorted(ranking, key=lambda item: item["flat_id"]):
        histogram_rows.append(
            {
                "flat_id": row["flat_id"],
                "layer": row["layer"],
                "expert_id": row["expert_id"],
                "counts": row["counts"],
                "total_count": row["total_count"],
                "workload_balanced_score": {
                    "numerator": row["score"].numerator,
                    "denominator": row["score"].denominator,
                    "decimal": float(row["score"]),
                },
            }
        )

    histogram_doc = {
        "schema": "inferswarm.phase0.routing-histogram/1",
        "label": "MEASURED_COUNTS_WITH_CALCULATED_SCORE",
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
        "measured_repetitions_per_class": 10,
        "class_route_totals": class_totals,
        "score": {
            "definition": "mean over W1-W4 of slot_count_in_class / total_routes_in_class",
            "tie_break": [
                "workload_balanced_score descending",
                "total raw count descending",
                "flat_id ascending",
            ],
        },
        "slots": histogram_rows,
        "privacy": {
            "contains_prompt_text": False,
            "contains_output_text": False,
            "contains_hostname": False,
            "contains_host_local_paths": False,
        },
    }

    placements = {
        "gpu0_primary_proxy_3774": primary,
        "global_hot_5442": global_hot,
        "complement_5442": complement,
    }
    placement_doc = {
        "schema": "inferswarm.phase1.placement/1",
        "policy_id": POLICY_ID,
        "status": "FROZEN_BEFORE_PHASE1_PERFORMANCE",
        "canonical_remote_placement": "complement_5442",
        "source": histogram_doc["source"],
        "geometry": histogram_doc["geometry"],
        "score": histogram_doc["score"],
        "budget": {
            "bytes_per_slot": BYTES_PER_SLOT,
            "remote_budget_bytes": REMOTE_BUDGET_BYTES,
            "remote_slots": REMOTE_SLOTS,
            "remote_resident_bytes": REMOTE_RESIDENT_BYTES,
            "gpu0_primary_proxy_slots": GPU0_PRIMARY_PROXY_SLOTS,
            "primary_proxy_plus_remote_slots": GPU0_PRIMARY_PROXY_SLOTS + REMOTE_SLOTS,
            "primary_proxy_plus_remote_fraction": (
                GPU0_PRIMARY_PROXY_SLOTS + REMOTE_SLOTS
            ) / TOTAL_SLOTS,
        },
        "placements": {},
        "privacy": histogram_doc["privacy"],
    }

    for name, ids in placements.items():
        placement_doc["placements"][name] = {
            "slot_count": len(ids),
            "flat_ids_in_rank_order": ids,
            "identities_in_rank_order": identities_from_flat(ids),
            "per_layer": per_layer(ids),
            "trace_coverage": placement_coverage(set(ids), class_counts, class_totals),
        }

    histogram_path = out_dir / "p0i-routing-histogram.json"
    placement_path = out_dir / "phase1-qwen36-placement-v1.json"
    histogram_path.write_text(json.dumps(histogram_doc, indent=2) + "\n", encoding="utf-8")
    placement_path.write_text(json.dumps(placement_doc, indent=2) + "\n", encoding="utf-8")

    histogram_sha = sha256(histogram_path)
    placement_sha = sha256(placement_path)
    checksum_path = out_dir / "p0i-publication.sha256.txt"
    checksum_path.write_text(
        f"{histogram_sha}  {histogram_path.name}\n"
        f"{placement_sha}  {placement_path.name}\n",
        encoding="utf-8",
    )

    print("P0-I PUBLICATION DERIVATION COMPLETE")
    print(f"source: {run_dir}")
    print(f"histogram: {histogram_path}")
    print(f"histogram SHA-256: {histogram_sha}")
    print(f"placement: {placement_path}")
    print(f"placement SHA-256: {placement_sha}")
    print(f"checksums: {checksum_path}")
    print()
    for name in ("gpu0_primary_proxy_3774", "global_hot_5442", "complement_5442"):
        coverage = placement_doc["placements"][name]["trace_coverage"]
        print(f"{name}: {placement_doc['placements'][name]['slot_count']} slots")
        print(f"  global trace coverage: {coverage['global']['coverage']:.6%}")
        for class_id in REQUIRED_CLASSES:
            print(
                f"  {class_id}: "
                f"{coverage['per_class'][class_id]['coverage']:.6%}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
