#!/usr/bin/env python3
"""Offline structural demand reduction for a single native, opt-in request.

This is not a placement ranker or device/link benchmark. Expected identity is
caller-supplied independent authority; producer identity fields are attestations.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from inferswarm.operator.profiles import parse_profiles, utc_timestamp

IDENTITY = ("model_source", "model_revision", "model_sha256", "representation",
            "native_source", "native_build_sha256", "workload_sha256")


def summarize(capture, expected, resource_profiles=None):
    if capture.get("schema") != "native-demand/1":
        raise ValueError("unsupported demand schema")
    identity = capture["identity"]
    if any(not expected.get(k) or identity.get(k) != expected[k] for k in IDENTITY):
        raise ValueError("model/native/workload identity mismatch")
    if identity.get("cohort") != "profiling":
        raise ValueError("evaluation cohort cannot train a placement profile")
    layers, experts, top_k, steps = (capture[k] for k in ("layers", "expert_count", "top_k", "steps"))
    if any(type(x) is not int for x in (layers, experts, top_k, steps)) or not (0 < layers <= 256 and
            0 < top_k <= experts <= 4096 and 0 < steps <= 257):
        raise ValueError("invalid capture dimensions")
    step_meta = capture["step_meta"]
    if not isinstance(step_meta, list) or len(step_meta) != steps:
        raise ValueError("truncated step metadata")
    for i, meta in enumerate(step_meta):
        if (not isinstance(meta, dict) or meta.get("phase") != ("prefill" if i == 0 else "decode") or
                type(meta.get("step")) is not int or meta["step"] != i or
                type(meta.get("tokens")) is not int or not 1 <= meta["tokens"] <= 4096):
            raise ValueError("invalid step phase/token metadata")
    rows = capture["rows"]
    if (any(type(capture[k]) is not int or capture[k] < 0 for k in
            ("observed_rows", "dropped_rows", "capacity_rows")) or
            not isinstance(rows, list) or len(rows) > 100000 or
            len(rows) != capture["observed_rows"] - capture["dropped_rows"] or
            len(rows) > capture["capacity_rows"]):
        raise ValueError("truncated or inconsistent capture rows")
    seen, phases, cost_observations, cost_rows = set(), {}, [], []
    by_phase = {"prefill": {}, "decode": {}}
    for row in rows:
        phase, step, layer, tokens = (row[k] for k in ("phase", "step", "layer", "tokens"))
        if phase not in by_phase or type(step) is not int or not 0 <= step < steps or type(layer) is not int or not 0 <= layer < layers:
            raise ValueError("invalid phase/step/layer")
        if (step, layer) in seen:
            raise ValueError("duplicate layer observation")
        seen.add((step, layer))
        if phase != step_meta[step]["phase"]:
            raise ValueError("phase differs from step metadata")
        phases[step] = phase
        if not isinstance(tokens, list) or len(tokens) != step_meta[step]["tokens"]:
            raise ValueError("invalid token grouping")
        dest = by_phase[phase].setdefault(str(layer), {"frequency": Counter(), "co_selection": Counter(), "tokens": 0, "rows": 0, "readback_ms": 0.0})
        dest["rows"] += 1
        overhead = row["readback_ms"]
        if type(overhead) not in (int, float) or not math.isfinite(overhead) or not 0 <= overhead < 1e9:
            raise ValueError("invalid readback cost")
        dest["readback_ms"] += overhead
        observations = row.get("cost_observations", [])
        if not isinstance(observations, list) or len(observations) > 6:
            raise ValueError("invalid cost observations")
        for item in observations:
            metric = item.get("metric", {})
            if (item.get("evidence_class") != "measured" or
                metric.get("name") not in ("dispatch_ms", "shared_ms", "join_ms", "input_bytes", "routing_bytes", "result_bytes") or
                metric.get("unit") != ("byte" if metric["name"].endswith("bytes") else "ms") or
                metric.get("statistic") != "observation" or
                type(metric.get("value")) not in (int, float) or
                not math.isfinite(metric["value"]) or metric["value"] < 0):
                raise ValueError("invalid measured cost")
        cost_observations.extend(observations)
        if observations:
            cost_rows.append({"phase": phase, "step": step, "layer": layer,
                              "observations": observations})
        for selection in tokens:
            if (not isinstance(selection, list) or len(selection) != top_k or
                    any(type(x) is not int or not 0 <= x < experts for x in selection) or
                    len(set(selection)) != top_k):
                raise ValueError("invalid selected IDs")
            dest["tokens"] += 1
            dest["frequency"].update(str(x) for x in selection)
            dest["co_selection"].update([",".join(map(str, sorted(selection)))])
    missing = sorted(set(range(layers)) - {layer for _, layer in seen})
    complete = (len(seen) == steps * layers and capture["dropped_rows"] == 0 and
                capture["observed_rows"] == steps * layers and len(phases) == steps)
    resources = {"validation": "unknown", "digest": None, "runtime_ids": [], "link_ids": [],
                 "runtime_evidence": {}, "link_evidence": {}}
    if resource_profiles is not None:
        snapshot = parse_profiles(resource_profiles)
        matching = [r for r in snapshot.runtime_capabilities
                    if r.source_revision == expected["native_source"] and
                       r.binary_sha256 == expected["native_build_sha256"]]
        if not matching:
            raise ValueError("resource snapshot has no matching native runtime source/build")
        expired = any(utc_timestamp(e.expires_at) <= datetime.now(timezone.utc) for e in snapshot.evidence)
        evidence = {e.evidence_id: e.sha256 for e in snapshot.evidence}
        resources = {"validation": "expired" if expired else "unvalidated",
                     "digest": snapshot.digest, "runtime_ids": [r.runtime_id for r in matching],
                     "link_ids": [r.link_id for r in snapshot.links],
                     "runtime_evidence": {r.evidence_id: evidence[r.evidence_id] for r in matching},
                     "link_evidence": {r.evidence_id: evidence[r.evidence_id] for r in snapshot.links}}
    return {"schema": "native-demand-summary/1", "identity": identity,
            "identity_provenance": capture.get("identity_provenance"),
            "observed_gguf": capture.get("observed_gguf"), "resources": resources,
            "phase_demand": by_phase,
            "coverage": {"complete": complete, "expected_rows": steps * layers,
                         "observed_rows": capture["observed_rows"], "retained_rows": len(rows),
                         "dropped_rows": capture["dropped_rows"], "missing_layers": missing,
                         "steps_without_retained_rows": sorted(set(range(steps)) - set(phases)),
                         "step_meta": step_meta},
            "costs": {"observations": cost_observations, "rows": cost_rows,
                      "unknown": [{"evidence_class": "unknown", "metric": {
                          "name": name, "value": None, "unit": "ms", "statistic": "observation"}}
                          for name in ("device_kernel_ms", "per_expert_execution_ms", "link_ms")],
                      "observed_id_readback_and_collection_ms": sum(
                          item["readback_ms"] for item in rows),
                      "class": "measured (callback readback and collection only; extra graph synchronization unmeasured)",
                      "per_expert_execution_ms": None, "link_ms": None,
                      "rpc_client_wait_is_device_time": False}}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("capture", type=Path)
    for key in IDENTITY:
        p.add_argument("--" + key.replace("_", "-"), required=True)
    p.add_argument("--resource-profiles", type=Path)
    args = p.parse_args()
    if args.capture.stat().st_size > 16 * 1024 * 1024:
        p.error("capture exceeds 16 MiB budget")
    profiles = None
    if args.resource_profiles is not None:
        if args.resource_profiles.stat().st_size > 16 * 1024 * 1024:
            p.error("resource profiles exceed 16 MiB budget")
        profiles = json.loads(args.resource_profiles.read_text())
    print(json.dumps(summarize(json.loads(args.capture.read_text()),
                               {k: getattr(args, k) for k in IDENTITY}, profiles), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
