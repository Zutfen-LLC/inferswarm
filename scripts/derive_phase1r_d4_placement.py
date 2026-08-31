#!/usr/bin/env python3
"""Derive D4 capability-weighted placement from frozen P0-I and calibration only."""
from __future__ import annotations

import argparse
import hashlib
import json
from fractions import Fraction
from pathlib import Path

from derive_phase1r_d3_placement import (BYTES, CLASSES, EXPERTS, GPU0_SLOTS, LAYERS,
                                         SOURCE_SHA256, TOTAL, UNION_SLOTS, WORKER_SLOTS,
                                         by_layer, digest, identities, route_mass)

D4_SCHEMA = "inferswarm.phase1r.d4-placement/1"
D4_STATUS = "FROZEN_BEFORE_D4_PERFORMANCE"


def exact_float(value: Fraction) -> dict[str, int | float]:
    return {"numerator": value.numerator, "denominator": value.denominator, "value": float(value)}


def objective(loads, totals, ca: Fraction, cb: Fraction, target_a: Fraction, remote_totals):
    predicted = [abs(Fraction(loads["A"][c], totals[c]) * ca -
                     Fraction(loads["B"][c], totals[c]) * cb) for c in CLASSES]
    target_deviation = [abs(Fraction(loads["A"][c], totals[c]) -
                            target_a * Fraction(remote_totals[c], totals[c])) for c in CLASSES]
    normalized_imbalance = abs(sum((Fraction(loads["A"][c], totals[c]) -
                                    Fraction(loads["B"][c], totals[c])) for c in CLASSES))
    return max(predicted), sum(predicted), sum(target_deviation), normalized_imbalance


def partition(ordered, rows, totals, ca, cb, target_a):
    assigned = {"A": [], "B": []}
    loads = {w: {c: 0 for c in CLASSES} for w in assigned}
    remote_totals = {c: sum(rows[i]["counts"][c] for i in ordered) for c in CLASSES}
    for flat in ordered:
        choices = [w for w in ("A", "B") if len(assigned[w]) < WORKER_SLOTS]
        if len(choices) == 1:
            chosen = choices[0]
        else:
            candidates = []
            for worker in choices:
                candidate = {w: dict(loads[w]) for w in loads}
                for c in CLASSES:
                    candidate[worker][c] += rows[flat]["counts"][c]
                candidates.append(((*objective(candidate, totals, ca, cb, target_a, remote_totals), worker, flat), worker))
            chosen = min(candidates)[1]
        assigned[chosen].append(flat)
        for c in CLASSES:
            loads[chosen][c] += rows[flat]["counts"][c]
    remote_totals = {c: sum(rows[i]["counts"][c] for i in ordered) for c in CLASSES}
    # The cardinality override at the tail of the greedy pass can leave a correct but
    # improvable partition. Deterministically exchange one A/B identity at a time. Candidate
    # shortlists are selected with integer counts; every accept/reject uses the full exact
    # rational lexicographic objective.
    def candidates_for(current_loads):
        pairs = set()
        for c in CLASSES:
            delta = (Fraction(current_loads["A"][c], totals[c]) * ca -
                     Fraction(current_loads["B"][c], totals[c]) * cb)
            if delta >= 0:
                aa = sorted(assigned["A"], key=lambda i: (-rows[i]["counts"][c], i))[:32]
                bb = sorted(assigned["B"], key=lambda i: (rows[i]["counts"][c], i))[:32]
            else:
                aa = sorted(assigned["A"], key=lambda i: (rows[i]["counts"][c], i))[:32]
                bb = sorted(assigned["B"], key=lambda i: (-rows[i]["counts"][c], i))[:32]
            pairs.update((a, b) for a in aa for b in bb)
        return sorted(pairs)

    def exchange(a, b, current_loads):
        candidate = {w: dict(current_loads[w]) for w in current_loads}
        for c in CLASSES:
            change = rows[b]["counts"][c] - rows[a]["counts"][c]
            candidate["A"][c] += change; candidate["B"][c] -= change
        return candidate

    def energy(current_loads):
        values = [(Fraction(current_loads["A"][c], totals[c]) * ca -
                   Fraction(current_loads["B"][c], totals[c]) * cb) for c in CLASSES]
        return sum((value * value for value in values), Fraction())

    # A scalar exact service-error descent can cross a lexicographic ridge (improving three
    # classes while briefly worsening the current maximum). The final pass below restores the
    # declared lexicographic objective and never accepts a maximum regression.
    current_energy = energy(loads)
    for _ in range(512):
        best = None
        for a, b in candidates_for(loads):
            candidate = exchange(a, b, loads); score = energy(candidate); key = (score, a, b)
            if score < current_energy and (best is None or key < best[0]):
                best = key, a, b, candidate, score
        if best is None:
            break
        _, a, b, loads, current_energy = best
        ai, bi = assigned["A"].index(a), assigned["B"].index(b)
        assigned["A"][ai], assigned["B"][bi] = b, a
    current = objective(loads, totals, ca, cb, target_a, remote_totals)
    for _ in range(512):
        best = None
        for a, b in candidates_for(loads):
            candidate = exchange(a, b, loads)
            score = objective(candidate, totals, ca, cb, target_a, remote_totals); key = (*score, a, b)
            if score < current and (best is None or key < best[0]):
                best = key, a, b, candidate, score
        if best is None:
            break
        _, a, b, loads, current = best
        ai, bi = assigned["A"].index(a), assigned["B"].index(b)
        assigned["A"][ai], assigned["B"][bi] = b, a
    return assigned, loads


def derive(histogram: Path, calibration: Path, d3_placement: Path) -> dict:
    source = json.loads(histogram.read_text()); cal = json.loads(calibration.read_text())
    d3 = json.loads(d3_placement.read_text())
    if source["source"]["model_repository"] != "nvidia/Qwen3.6-35B-A3B-NVFP4" or source["source"]["model_revision"] != "491c2f1ea524c639598bf8fa787a93fed5a6fbce":
        raise ValueError("unexpected P0-I model provenance")
    if {k: source["source"].get(k) for k in SOURCE_SHA256} != SOURCE_SHA256:
        raise ValueError("unexpected P0-I provenance hashes")
    if cal["schema"] != "inferswarm.d4.worker-calibration/1" or cal["status"] != "FROZEN_BEFORE_D4_PLACEMENT_AND_PERFORMANCE":
        raise ValueError("D4 calibration is not frozen")
    rows, totals = source["slots"], source["class_route_totals"]
    if len(rows) != TOTAL or [row["flat_id"] for row in rows] != list(range(TOTAL)):
        raise ValueError("invalid P0-I identity geometry")
    ca, cb = (Fraction(str(cal["service_medians_us"][worker])) for worker in ("a", "b"))
    targets = cal["normalized_capacity_targets"]
    target_a = Fraction(targets["a"]["numerator"], targets["a"]["denominator"])
    target_b = Fraction(targets["b"]["numerator"], targets["b"]["denominator"])
    if target_a + target_b != 1 or target_a != cb / (ca + cb):
        raise ValueError("calibration target arithmetic disagreement")
    union = d3["ranking"]["ranked_union_flat_ids"]
    if len(union) != UNION_SLOTS or len(set(union)) != UNION_SLOTS:
        raise ValueError("D3 top-6000 union invalid")
    assigned, loads = partition(union, rows, totals, ca, cb, target_a)
    a, b = assigned["A"], assigned["B"]
    local = [i for i in range(TOTAL) if i not in set(union)]
    if len(a) != WORKER_SLOTS or len(b) != WORKER_SLOTS or set(a) & set(b):
        raise ValueError("D4 partition invariant failed")
    masses = {"a": route_mass(a, rows, totals), "b": route_mass(b, rows, totals),
              "remote": route_mass(union, rows, totals), "local": route_mass(local, rows, totals)}
    predicted = {}
    for c in CLASSES:
        pa = Fraction(loads["A"][c], totals[c]) * ca
        pb = Fraction(loads["B"][c], totals[c]) * cb
        predicted[c] = {"worker_a_normalized_mass_times_service_us": float(pa),
                        "worker_b_normalized_mass_times_service_us": float(pb),
                        "absolute_difference_us": float(abs(pa-pb)),
                        "worker_a_route_share_of_remote": float(Fraction(loads["A"][c], loads["A"][c]+loads["B"][c])),
                        "worker_b_route_share_of_remote": float(Fraction(loads["B"][c], loads["A"][c]+loads["B"][c]))}
    d3_compare = {}
    for worker in ("a", "b"):
        old = d3["validation"][f"worker_{worker}_route_mass"]
        d3_compare[worker] = {c: {"d3_normalized_mass": old["per_class"][c]["normalized_mass"],
                                   "d4_normalized_mass": masses[worker]["per_class"][c]["normalized_mass"],
                                   "delta": masses[worker]["per_class"][c]["normalized_mass"] - old["per_class"][c]["normalized_mass"]}
                              for c in CLASSES}
    return {
        "schema": D4_SCHEMA, "status": D4_STATUS,
        "source": {"sanitized_histogram": histogram.name, "sanitized_histogram_sha256": digest(histogram),
                   **source["source"], "d3_placement": d3_placement.name,
                   "d3_placement_sha256": digest(d3_placement), "d4_calibration_artifact_sha256": digest(calibration)},
        "model": {"repository": source["source"]["model_repository"], "revision": source["source"]["model_revision"]},
        "calibration": {"freetoken_sha": cal["freetoken_sha"], "worker_a_uuid": cal["workers"]["a"]["physical_uuid"],
                        "worker_b_uuid": cal["workers"]["b"]["physical_uuid"],
                        "service_medians_us": {"a": float(ca), "b": float(cb)},
                        "normalized_capacity_targets": {"a": exact_float(target_a), "b": exact_float(target_b)}},
        "ranking": {"definition": d3["ranking"]["definition"], "tie_break": d3["ranking"]["tie_break"],
                    "ranked_union_flat_ids": union, "union_policy": "exact D3 frozen top-6000 remote union preserved"},
        "geometry": {"num_moe_layers": LAYERS, "num_experts_per_layer": EXPERTS,
                     "logical_expert_identities": TOTAL, "bytes_per_native_nvfp4_identity": BYTES,
                     "gpu0_cache_slots": GPU0_SLOTS, "gpu0_cache_capacity_description": "runtime capacity; not logical ownership",
                     "worker_a_slots": WORKER_SLOTS, "worker_b_slots": WORKER_SLOTS,
                     "worker_resident_bytes_each": WORKER_SLOTS * BYTES,
                     "combined_worker_resident_bytes": 2 * WORKER_SLOTS * BYTES},
        "semantics": d3["semantics"],
        "partition": {"algorithm": "D3 rank-order deterministic greedy; exact rational lexicographic minimization after each identity of: max W1-W4 predicted A/B service-wall difference, sum differences, capacity-target route-mass deviation, total normalized A/B imbalance, worker then flat-ID tie-break; exact 3000/3000 capacity override",
                      "worker_a": {"flat_ids_in_rank_order": a, "identities": identities(a), "per_layer": by_layer(a),
                                   "slot_mapping": [{"slot": slot, "flat_id": flat} for slot, flat in enumerate(a)]},
                      "worker_b": {"flat_ids_in_rank_order": b, "identities": identities(b), "per_layer": by_layer(b),
                                   "slot_mapping": [{"slot": slot, "flat_id": flat} for slot, flat in enumerate(b)]},
                      "local_remainder": {"flat_ids": local, "identities": identities(local), "per_layer": by_layer(local)}},
        "validation": {"union_slots": len(union), "unique_union_slots": len(set(union)),
                       "worker_sets_disjoint": not bool(set(a) & set(b)), "local_remainder_slots": len(local),
                       "logical_owner_sets_pairwise_disjoint": not bool(set(a)&set(b) or set(a)&set(local) or set(b)&set(local)),
                       "logical_owner_partition_covers_all_identities": set(a)|set(b)|set(local) == set(range(TOTAL)),
                       "worker_a_route_mass": masses["a"], "worker_b_route_mass": masses["b"],
                       "remote_union_route_mass": masses["remote"], "local_remainder_route_mass": masses["local"],
                       "predicted_service_balance": predicted, "d3_vs_d4_route_mass": d3_compare}
    }


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--histogram", required=True, type=Path)
    parser.add_argument("--calibration", required=True, type=Path); parser.add_argument("--d3-placement", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path); args = parser.parse_args()
    args.out.write_text(json.dumps(derive(args.histogram, args.calibration, args.d3_placement), indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
