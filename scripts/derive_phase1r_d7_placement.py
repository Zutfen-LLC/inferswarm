#!/usr/bin/env python3
"""Derive the frozen D7 fan-in-sparse placement from exact P0-I routes.

The D3 top-6000 union is immutable.  This script changes only whether A or B
owns each member and intentionally keeps the optimization narrow: whole-layer
ownership first, then the slower A worker receives the lower observed burden.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path

from derive_phase1r_d3_placement import BYTES, CLASSES, EXPERTS, GPU0_SLOTS, LAYERS, TOTAL, UNION_SLOTS, WORKER_SLOTS, by_layer, identities

D7_SCHEMA = "inferswarm.phase1r.d7-placement/1"
D7_STATUS = "FROZEN_BEFORE_D7_PERFORMANCE"
D3_SHA256 = "6677fe1c506376a55aa8dcabb8d5761dc0373ced9d9b053209991059556d5887"
ROUTING_SHA256 = "4071e2bfd3c18f39e5c5a0b5ff8913ca0fb99b843cf7abca0ecc1f4ebd0a252f"
MODEL = "nvidia/Qwen3.6-35B-A3B-NVFP4"
REVISION = "491c2f1ea524c639598bf8fa787a93fed5a6fbce"
W4_SHA256 = "41226057cf336c5f7fb618bda61f11c98927167629ef4b5bdfbfa1ba48ae54f7"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fraction(value: Fraction) -> dict:
    return {"numerator": value.numerator, "denominator": value.denominator, "value": float(value)}


def read_events(path: Path) -> dict[str, list[tuple[int, tuple[int, ...]]]]:
    """Return exact (layer, flat-ID routes) events, preserving source order."""
    if digest(path) != ROUTING_SHA256:
        raise ValueError("exact-routing SHA-256 disagreement")
    result = {workload: [] for workload in CLASSES}
    repetitions = Counter()
    with path.open() as source:
        for line in source:
            row = json.loads(line)
            if row.get("record_type") != "measured_repetition":
                continue
            workload = row.get("class_id")
            if workload not in result or row.get("mode") != "exact_trace" or not row.get("measured"):
                raise ValueError("unexpected exact-routing observation contract")
            trace = row["trace"]
            complete = row["trace_completeness"]
            if (not trace["enabled"] or trace["truncated"] or trace["incomplete_layer_alignment"]
                    or trace["top_k"] != 8 or trace["max_tokens_per_step"] != 1
                    or not complete["complete"] or trace["steps_recorded"] != complete["observed_steps"]):
                raise ValueError("incomplete exact-routing observation")
            repetitions[workload] += 1
            for step in trace["records"]:
                if len(step["layers"]) != LAYERS:
                    raise ValueError("exact route step does not contain 40 layers")
                for expected_layer, layer_row in enumerate(step["layers"]):
                    layer = layer_row["layer"]
                    if layer != expected_layer:
                        raise ValueError("exact route layer ordering disagreement")
                    for route in layer_row["token_routes"]:
                        if len(route) != 8 or len(set(route)) != 8 or not all(0 <= expert < EXPERTS for expert in route):
                            raise ValueError("invalid exact top-k route")
                        result[workload].append((layer, tuple(layer * EXPERTS + expert for expert in route)))
    if repetitions != Counter({workload: 10 for workload in CLASSES}):
        raise ValueError(f"expected ten exact repetitions per workload, got {dict(repetitions)}")
    return result


def _distribution(counter: Counter, events: int) -> dict:
    def quantile(q: float) -> int:
        rank = max(0, math.ceil(events * q) - 1)
        cumulative = 0
        for value in (0, 1, 2):
            cumulative += counter[value]
            if rank < cumulative:
                return value
        raise AssertionError("invalid participation distribution")
    return {
        "mean_remote_workers_active": (counter[1] + 2 * counter[2]) / events,
        "median_remote_workers_active": quantile(.5),
        "p95_remote_workers_active": quantile(.95),
    }


def participation(events, a: set[int], b: set[int]) -> dict:
    counts = Counter()
    a_active_routes = 0
    b_active_routes = 0
    for _layer, route in events:
        ar = sum(flat in a for flat in route)
        br = sum(flat in b for flat in route)
        local = len(route) - ar - br
        a_active, b_active = bool(ar), bool(br)
        counts["events"] += 1
        counts["a_routes"] += ar
        counts["b_routes"] += br
        counts["local_routes"] += local
        counts["a_active"] += a_active
        counts["b_active"] += b_active
        counts["both"] += a_active and b_active
        counts["a_only"] += a_active and not b_active
        counts["b_only"] += b_active and not a_active
        counts["zero"] += not a_active and not b_active
        counts["a_routes_when_active"] += ar if a_active else 0
        counts["b_routes_when_active"] += br if b_active else 0
    n = counts["events"]
    dist = Counter({0: counts["zero"], 1: counts["a_only"] + counts["b_only"], 2: counts["both"]})
    total_routes = counts["a_routes"] + counts["b_routes"] + counts["local_routes"]
    return {
        "event_count": n,
        **_distribution(dist, n),
        "counts": {key: counts[key] for key in ("zero", "a_only", "b_only", "both", "a_active", "b_active")},
        "fractions": {key: counts[key] / n for key in ("zero", "a_only", "b_only", "both")},
        "mean_a_route_count_when_active": counts["a_routes"] / counts["a_active"] if counts["a_active"] else 0.0,
        "mean_b_route_count_when_active": counts["b_routes"] / counts["b_active"] if counts["b_active"] else 0.0,
        "routes": {
            "a": counts["a_routes"], "b": counts["b_routes"], "local": counts["local_routes"],
            "total": total_routes,
            "shares": {"a": counts["a_routes"] / total_routes, "b": counts["b_routes"] / total_routes,
                       "local": counts["local_routes"] / total_routes},
        },
    }


def participation_report(events_by_workload, a: set[int], b: set[int]) -> dict:
    per = {workload: participation(events_by_workload[workload], a, b) for workload in CLASSES}
    pooled = participation([event for workload in CLASSES for event in events_by_workload[workload]], a, b)
    equal = {
        "definition": "arithmetic mean of each W1-W4 normalized rate; each workload has weight 1/4",
        "mean_remote_workers_active": sum(Fraction(per[w]["counts"]["a_active"] + per[w]["counts"]["b_active"],
                                                       per[w]["event_count"]) for w in CLASSES) / 4,
        "p0": sum(Fraction(per[w]["counts"]["zero"], per[w]["event_count"]) for w in CLASSES) / 4,
        "pa": sum(Fraction(per[w]["counts"]["a_only"], per[w]["event_count"]) for w in CLASSES) / 4,
        "pb": sum(Fraction(per[w]["counts"]["b_only"], per[w]["event_count"]) for w in CLASSES) / 4,
        "pab": sum(Fraction(per[w]["counts"]["both"], per[w]["event_count"]) for w in CLASSES) / 4,
    }
    expected_active = {
        "a": {"pooled_event_count": pooled["counts"]["a_active"],
              "equal_workload_rate": _fraction(sum(Fraction(per[w]["counts"]["a_active"], per[w]["event_count"])
                                                      for w in CLASSES) / 4)},
        "b": {"pooled_event_count": pooled["counts"]["b_active"],
              "equal_workload_rate": _fraction(sum(Fraction(per[w]["counts"]["b_active"], per[w]["event_count"])
                                                      for w in CLASSES) / 4)},
    }
    return {"per_workload": per, "aggregate_pooled_events": pooled, "expected_active_layer_events": expected_active,
            "aggregate_equal_workload_weight": {key: value if isinstance(value, str) else _fraction(value)
                                                 for key, value in equal.items()}}


def layer_observations(events_by_workload, union: set[int]):
    active = {w: [0] * LAYERS for w in CLASSES}
    routes = {w: [0] * LAYERS for w in CLASSES}
    totals = {w: [0] * LAYERS for w in CLASSES}
    for workload in CLASSES:
        for layer, route in events_by_workload[workload]:
            remote = sum(flat in union for flat in route)
            totals[workload][layer] += 1
            active[workload][layer] += bool(remote)
            routes[workload][layer] += remote
    return active, routes, totals


def choose_whole_layers(layer_counts: list[int], events_by_workload, union: set[int]) -> tuple[int, ...] | None:
    """Capacity DP using the declared additive heterogeneous tie-break."""
    active, routes, totals = layer_observations(events_by_workload, union)
    layer_keys = []
    for layer in range(LAYERS):
        active_rates = [Fraction(active[w][layer], totals[w][layer]) for w in CLASSES]
        route_rates = [Fraction(routes[w][layer], totals[w][layer] * 8) for w in CLASSES]
        layer_keys.append((sum(active_rates, Fraction()) / 4,
                           sum(route_rates, Fraction()) / 4,
                           max(active_rates) - min(active_rates)))
    # Values are (sum active burden, sum route burden, sum stability penalty, layers).
    best = {0: (Fraction(), Fraction(), Fraction(), ())}
    for layer, count in enumerate(layer_counts):
        candidate = dict(best)
        for capacity, value in best.items():
            new_capacity = capacity + count
            if new_capacity > WORKER_SLOTS:
                continue
            key = (value[0] + layer_keys[layer][0], value[1] + layer_keys[layer][1],
                   value[2] + layer_keys[layer][2], value[3] + (layer,))
            if new_capacity not in candidate or key < candidate[new_capacity]:
                candidate[new_capacity] = key
        best = candidate
    return best.get(WORKER_SLOTS, (None, None, None, None))[3]


def minimum_split_layer_count(layer_counts: list[int], capacity: int = WORKER_SLOTS) -> int:
    reachable = {0}
    for count in layer_counts:
        reachable |= {value + count for value in tuple(reachable) if value + count <= capacity}
    if capacity in reachable:
        return 0
    for split, count in enumerate(layer_counts):
        other = [value for index, value in enumerate(layer_counts) if index != split]
        reachable = {0}
        for value in other:
            reachable |= {total + value for total in tuple(reachable) if total + value < capacity}
        if any(0 < capacity - total < count for total in reachable):
            return 1
    raise ValueError("exact capacity cannot be reached with at most one split layer")


def derive(routing: Path, d3_path: Path) -> dict:
    if digest(d3_path) != D3_SHA256:
        raise ValueError("D3 placement SHA-256 disagreement")
    d3 = json.loads(d3_path.read_text())
    if d3["model"] != {"repository": MODEL, "revision": REVISION}:
        raise ValueError("D3 model provenance disagreement")
    union_order = d3["ranking"]["ranked_union_flat_ids"]
    union = set(union_order)
    if len(union_order) != UNION_SLOTS or len(union) != UNION_SLOTS:
        raise ValueError("invalid D3 remote union")
    events = read_events(routing)
    baseline_a = set(d3["partition"]["worker_a"]["flat_ids_in_rank_order"])
    baseline_b = set(d3["partition"]["worker_b"]["flat_ids_in_rank_order"])
    baseline = participation_report(events, baseline_a, baseline_b)
    layer_counts = [sum(flat // EXPERTS == layer for flat in union) for layer in range(LAYERS)]
    a_layers = choose_whole_layers(layer_counts, events, union)
    if a_layers is None:
        raise ValueError("frozen D3 union unexpectedly requires a split layer; split optimizer not invoked")
    a_layer_set = set(a_layers)
    a = [flat for flat in union_order if flat // EXPERTS in a_layer_set]
    b = [flat for flat in union_order if flat // EXPERTS not in a_layer_set]
    local = d3["partition"]["local_remainder"]["flat_ids"]
    if len(a) != WORKER_SLOTS or len(b) != WORKER_SLOTS or set(a) & set(b) or set(a) | set(b) != union:
        raise ValueError("D7 capacity or union invariant failed")
    predicted = participation_report(events, set(a), set(b))
    base_equal = baseline["aggregate_equal_workload_weight"]
    d7_equal = predicted["aggregate_equal_workload_weight"]
    base_pab = Fraction(base_equal["pab"]["numerator"], base_equal["pab"]["denominator"])
    d7_pab = Fraction(d7_equal["pab"]["numerator"], d7_equal["pab"]["denominator"])
    base_mean = Fraction(base_equal["mean_remote_workers_active"]["numerator"], base_equal["mean_remote_workers_active"]["denominator"])
    d7_mean = Fraction(d7_equal["mean_remote_workers_active"]["numerator"], d7_equal["mean_remote_workers_active"]["denominator"])
    ownership = [{"layer": layer, "remote_identity_count": layer_counts[layer],
                  "owner": "A" if layer in a_layer_set else "B", "split": False}
                 for layer in range(LAYERS)]
    return {
        "schema": D7_SCHEMA, "status": D7_STATUS,
        "source": {
            "routing_artifact": routing.name, "exact_routing_sha256": ROUTING_SHA256,
            "routing_schema": "inferswarm.phase0.routing-observation/1",
            "routing_population": "ten measured exact-trace repetitions for each W1-W4; no new serving routes",
            "d3_placement": d3_path.name, "d3_placement_sha256": D3_SHA256,
            "workload_manifest_sha256": d3["source"]["workload_manifest_sha256"], "w4_prompt_sha256": W4_SHA256,
        },
        "model": {"repository": MODEL, "revision": REVISION},
        "geometry": {"num_moe_layers": LAYERS, "num_experts_per_layer": EXPERTS,
                     "logical_expert_identities": TOTAL, "bytes_per_native_nvfp4_identity": BYTES,
                     "gpu0_cache_slots": GPU0_SLOTS, "gpu0_logical_local_identities": 4240,
                     "worker_a_slots": WORKER_SLOTS, "worker_b_slots": WORKER_SLOTS,
                     "worker_resident_bytes_each": WORKER_SLOTS * BYTES,
                     "combined_worker_resident_bytes": UNION_SLOTS * BYTES},
        "ranking": {"ranked_union_flat_ids": union_order,
                    "union_policy": "byte-for-byte D3 ranking order and exact frozen top-6000 set"},
        "derivation": {
            "algorithm": "capacity DP over 40 whole-layer remote-identity counts",
            "primary_objective": "minimum exact observed equal-W1-W4 P(A and B active), then mean remote workers active",
            "whole_layer_result": "exact 3000/3000 capacity; P(A and B active)=0 by construction",
            "capability_tie_break": {
                "policy": "A is the slower D6 worker; among equal zero-co-participation whole-layer solutions minimize equal-W1-W4 expected A active events, then A owned-route share, then summed per-layer cross-workload active-rate spread, then ascending layer tuple",
                "evidence": {"worker_a_d6_branch_us_approx": 122.880, "worker_b_d6_branch_us_approx": 64.512,
                             "worker_a_zero_route_us_approx": 33.792, "worker_b_zero_route_us_approx": 16.384},
                "generic_worker_score_derived": False,
            },
            "remote_identity_count_per_layer": layer_counts,
            "worker_a_whole_layers": list(a_layers),
            "worker_b_whole_layers": [layer for layer in range(LAYERS) if layer not in a_layer_set],
            "split_layer_count": 0, "per_layer_ownership": ownership,
        },
        "partition": {
            "worker_a": {"flat_ids_in_rank_order": a, "identities": identities(a), "per_layer": by_layer(a),
                         "slot_mapping": [{"slot": slot, "flat_id": flat} for slot, flat in enumerate(a)]},
            "worker_b": {"flat_ids_in_rank_order": b, "identities": identities(b), "per_layer": by_layer(b),
                         "slot_mapping": [{"slot": slot, "flat_id": flat} for slot, flat in enumerate(b)]},
            "local_remainder": {"flat_ids": local, "identities": identities(local), "per_layer": by_layer(local)},
        },
        "baseline_equal_participation": baseline,
        "predicted_d7_participation": predicted,
        "predicted_reductions": {
            "P_BOTH_BASE": _fraction(base_pab), "P_BOTH_D7": _fraction(d7_pab),
            "P_BOTH_REDUCTION": _fraction(1 - d7_pab / base_pab),
            "MEAN_WORKERS_BASE": _fraction(base_mean), "MEAN_WORKERS_D7": _fraction(d7_mean),
            "PARTICIPATION_REDUCTION": _fraction(1 - d7_mean / base_mean),
        },
        "validation": {"union_slots": len(union), "worker_a_slots": len(a), "worker_b_slots": len(b),
                       "worker_sets_disjoint": not bool(set(a) & set(b)), "union_equals_d3": set(a) | set(b) == union,
                       "local_remainder_slots": len(local), "complete_logical_partition": set(a) | set(b) | set(local) == set(range(TOTAL)),
                       "minimum_split_layer_count": minimum_split_layer_count(layer_counts)},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exact-routing", required=True, type=Path)
    parser.add_argument("--d3-placement", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out.write_text(json.dumps(derive(args.exact_routing, args.d3_placement), indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
