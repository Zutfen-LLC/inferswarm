#!/usr/bin/env python3
"""Derive the frozen D3 two-worker placement from sanitized P0-I counts only."""

from __future__ import annotations

import argparse
import hashlib
import json
from fractions import Fraction
from pathlib import Path

SOURCE_SHA256 = {
    "workload_manifest_sha256": "10f81e5418a71a68f387632de422c3337cc7ba0518111a8746ad856d0210b24a",
    "run_json_sha256": "1ecd14c8c157eb6cde62f8514b8f2af82a36dfe69e3a7241f5be6c9908e539dc",
    "exact_routing_sha256": "4071e2bfd3c18f39e5c5a0b5ff8913ca0fb99b843cf7abca0ecc1f4ebd0a252f",
    "cache_pressure_sha256": "f02d96a079a6af94b3fec9d2c571322a1274cd408a3a9ff2ef162f538babab3a",
}
CLASSES = ("W1", "W2", "W3", "W4")
LAYERS, EXPERTS, TOTAL = 40, 256, 10240
GPU0_SLOTS, WORKER_SLOTS, UNION_SLOTS = 3774, 3000, 6000
BYTES = 1775616


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identities(ids):
    return [{"flat_id": i, "layer": i // EXPERTS, "expert_id": i % EXPERTS} for i in ids]


def by_layer(ids):
    values = [[] for _ in range(LAYERS)]
    for i in ids:
        values[i // EXPERTS].append(i % EXPERTS)
    return [{"layer": layer, "expert_ids": values[layer]} for layer in range(LAYERS)]


def route_mass(ids, rows, totals):
    result, selected_global = {}, 0
    for c in CLASSES:
        selected = sum(rows[i]["counts"][c] for i in ids)
        selected_global += selected
        result[c] = {"selected_routes": selected, "total_routes": totals[c], "normalized_mass": selected / totals[c]}
    return {"per_class": result, "global": {"selected_routes": selected_global, "total_routes": sum(totals.values()), "normalized_mass": selected_global / sum(totals.values())}}


def rank(rows, totals):
    return sorted(range(TOTAL), key=lambda i: (
        -sum((Fraction(rows[i]["counts"][c], totals[c]) for c in CLASSES), Fraction()) / len(CLASSES),
        -sum(rows[i]["counts"].values()), i))


def partition(ordered, rows, totals):
    assigned = {"A": [], "B": []}
    loads = {w: {c: 0 for c in CLASSES} for w in assigned}
    for i in ordered:
        remaining = UNION_SLOTS - len(assigned["A"]) - len(assigned["B"])
        choices = [w for w in ("A", "B") if len(assigned[w]) < WORKER_SLOTS]
        # Capacity override: a non-full worker must receive every remaining identity.
        if len(choices) == 1:
            chosen = choices[0]
        else:
            candidates = []
            for worker in choices:
                candidate = {w: dict(loads[w]) for w in loads}
                for c in CLASSES:
                    candidate[worker][c] += rows[i]["counts"][c]
                differences = [abs(Fraction(candidate["A"][c], totals[c]) - Fraction(candidate["B"][c], totals[c])) for c in CLASSES]
                total_mass = abs(sum(Fraction(candidate["A"][c], totals[c]) for c in CLASSES) - sum(Fraction(candidate["B"][c], totals[c]) for c in CLASSES))
                candidates.append(((max(differences), sum(differences), total_mass, worker), worker))
            chosen = min(candidates)[1]
        assigned[chosen].append(i)
        for c in CLASSES:
            loads[chosen][c] += rows[i]["counts"][c]
    return assigned, loads


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--histogram", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    source = json.loads(args.histogram.read_text())
    if source["source"]["model_repository"] != "nvidia/Qwen3.6-35B-A3B-NVFP4" or source["source"]["model_revision"] != "491c2f1ea524c639598bf8fa787a93fed5a6fbce":
        raise ValueError("unexpected P0-I model provenance")
    if {k: source["source"].get(k) for k in SOURCE_SHA256} != SOURCE_SHA256:
        raise ValueError("unexpected P0-I provenance hashes")
    rows = source["slots"]
    if len(rows) != TOTAL or [row["flat_id"] for row in rows] != list(range(TOTAL)):
        raise ValueError("invalid P0-I identity geometry")
    totals = source["class_route_totals"]
    ordered = rank(rows, totals)
    union = ordered[:UNION_SLOTS]
    assigned, loads = partition(union, rows, totals)
    a, b = assigned["A"], assigned["B"]
    if len(a) != WORKER_SLOTS or len(b) != WORKER_SLOTS or set(a) & set(b):
        raise ValueError("D3 partition invariant failed")
    cache = ordered[UNION_SLOTS:UNION_SLOTS + GPU0_SLOTS]
    remote = route_mass(union, rows, totals)
    a_mass, b_mass = route_mass(a, rows, totals), route_mass(b, rows, totals)
    local = route_mass(set(range(TOTAL)) - set(union), rows, totals)
    differences = {c: abs(a_mass["per_class"][c]["normalized_mass"] - b_mass["per_class"][c]["normalized_mass"]) for c in CLASSES}
    artifact = {
        "schema": "inferswarm.phase1r.d3-placement/1", "status": "FROZEN_BEFORE_D3_PERFORMANCE",
        "source": {"sanitized_histogram": args.histogram.name, "sanitized_histogram_sha256": digest(args.histogram), **source["source"]},
        "model": {"repository": source["source"]["model_repository"], "revision": source["source"]["model_revision"]},
        "ranking": {"definition": "mean(selections(s,c) / total_selections(c)) over W1,W2,W3,W4", "tie_break": ["score descending", "total raw selections descending", "flat ID ascending"], "ranked_union_flat_ids": union},
        "geometry": {"num_moe_layers": LAYERS, "num_experts_per_layer": EXPERTS, "logical_expert_identities": TOTAL, "bytes_per_native_nvfp4_identity": BYTES, "gpu0_cache_slots": GPU0_SLOTS, "worker_a_slots": WORKER_SLOTS, "worker_b_slots": WORKER_SLOTS, "worker_resident_bytes_each": WORKER_SLOTS * BYTES, "combined_worker_resident_bytes": 2 * WORKER_SLOTS * BYTES},
        "partition": {"algorithm": "rank-order deterministic greedy; lexicographically minimize maximum W1-W4 normalized A/B load difference, sum of differences, total normalized mass difference, then worker ID A before B; capacity override for a sole non-full worker", "worker_a": {"flat_ids_in_rank_order": a, "identities": identities(a), "per_layer": by_layer(a)}, "worker_b": {"flat_ids_in_rank_order": b, "identities": identities(b), "per_layer": by_layer(b)}, "gpu0_cache": {"flat_ids_in_rank_order": cache, "per_layer": by_layer(cache)}},
        "validation": {"union_slots": len(union), "unique_union_slots": len(set(union)), "worker_sets_disjoint": not bool(set(a) & set(b)), "flat_id_arithmetic": "flat_id = layer * 256 + expert_id", "worker_a_route_mass": a_mass, "worker_b_route_mass": b_mass, "remote_union_route_mass": remote, "local_remainder_route_mass": local, "ab_balance": {"absolute_normalized_difference_per_class": differences, "maximum": max(differences.values()), "sum": sum(differences.values()), "total_normalized_mass_difference": abs(sum(a_mass["per_class"][c]["normalized_mass"] for c in CLASSES) - sum(b_mass["per_class"][c]["normalized_mass"] for c in CLASSES))}}
    }
    args.out.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
