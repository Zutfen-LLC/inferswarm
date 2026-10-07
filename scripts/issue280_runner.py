#!/usr/bin/env python3
"""Corrected Issue #280 campaign runner: synchronous acceptance-aware STOP.

Issue #284 correction scope #1/#4/#5. The recovered #280 runner checked HTTP
completion, not frozen acceptance, so a failing first baseline request did not
stop the campaign. This module implements the launch/request loop as a PURE
gate engine over an injected executor, so the STOP law is CPU-testable without
any GPU/model execution:

- request/HTTP completion is not acceptance;
- all frozen per-request acceptance/STOP conditions are evaluated BEFORE any
  subsequent launch or request (synchronous STOP enforcement);
- task-correctness failure stops immediately;
- required observer evidence missing for an admitted request stops immediately;
- candidate requests additionally require boundary/transfer evidence
  (mechanism-admission gate) before any further candidate work;
- health/resource STOP inputs available at request completion are evaluated
  before the next launch;
- an aborted/failed request consumes its budget slot — no automatic
  replacement or selective rerun;
- peak RSS must be retained (or its absence blocks admission);
- the matrix is the minimal rerun contract: 2 launches / 4 requests maximum.

This module does not launch servers, load models, touch devices, or perform
any physical execution. It never authorizes the rerun itself; the prospective
matrix is prepared for a separately authorized minimal physical verification.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_task_check():
    path = Path(__file__).resolve().parent / "issue280_task_check.py"
    spec = importlib.util.spec_from_file_location("issue280_task_check", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


semantic_check = _load_task_check().check

# Minimal-rerun contract (issue #284 §5): one baseline launch + one two-die
# candidate launch; cold + warm request each; 2 launches / 4 requests maximum.
MINIMAL_RERUN_MATRIX = [
    {"label": "R1", "prompt": "P1", "rep": 1, "arm": "A", "requests": ("cold", "warm")},
    {"label": "R2", "P1_marker": None, "prompt": "P1", "rep": 1, "arm": "B", "requests": ("cold", "warm")},
]

# Required real-run observer evidence for an admitted BASELINE (single-die) request.
BASELINE_EVIDENCE = (
    "recording",
    "weight_inventory",       # named model-weight inventory/ownership
    "kv_inventory",           # KV/mutable-state inventory/ownership
    "graph_begin", "graph_end",
    "vk_graph_begin",
    "dispatch",               # completed attributable compute events
    "submit", "complete",     # causal submit/completion pairing
)

# Candidate (two-die) requests additionally require the boundary/transfer
# records needed by #280 mechanism admission (same-request two-die attribution).
CANDIDATE_EVIDENCE = BASELINE_EVIDENCE + (
    "boundary_begin", "boundary_end",
    "copy_manifest",
    "host_leg", "copy_path",
)


def _missing_evidence(row, events):
    required = CANDIDATE_EVIDENCE if row["arm"] == "B" else BASELINE_EVIDENCE
    return [name for name in required if name not in events]


def run_campaign(matrix, launch):
    """Run the gated loop. ``launch`` maps a matrix row to a callable that
    performs ONE request of a given kind ("cold"/"warm") and returns
    ``(record, launch_state)`` where record has keys label/arm/prompt/kind/
    text/transport_ok (and optional health_stop) and launch_state carries
    ``observer_events`` (set of event names retained for the request) and
    ``peak_rss_bytes``.

    Returns a summary dict; never raises on request outcomes (fail-closed
    instead). Pure with respect to the executor: all STOP decisions are made
    here, synchronously, before the next launch/request is requested.
    """
    requests = []

    def admit(row, kind, record, state):
        entry = {
            "launch": row["label"], "arm": row["arm"], "prompt": row["prompt"],
            "kind": kind, "disposition": "aborted",
            "reason": None, "peak_rss_bytes": state.get("peak_rss_bytes"),
            "observer_events": sorted(state.get("observer_events", ())),
        }
        requests.append(entry)
        if not record.get("transport_ok", False):
            entry["reason"] = "request transport failed (HTTP completion absent)"
            return entry, "stop"
        # task correctness (semantic, frozen per prompt)
        ok, reason = semantic_check(row["prompt"], record.get("text", ""))
        if not ok:
            entry["disposition"] = "rejected"
            entry["reason"] = f"task correctness failure: {reason}"
            return entry, "stop"
        # observer evidence fail-closed
        missing = _missing_evidence(row, state.get("observer_events", ()))
        if missing:
            entry["disposition"] = "rejected"
            entry["reason"] = f"required compute evidence missing: {missing}"
            return entry, "stop"
        # peak RSS retention fail-closed
        if state.get("peak_rss_bytes") is None:
            entry["disposition"] = "rejected"
            entry["reason"] = "peak_rss not retained; absence blocks admission"
            return entry, "stop"
        # health/resource STOP inputs already available at completion
        if record.get("health_stop"):
            entry["disposition"] = "rejected"
            entry["reason"] = f"health/resource stop input: {record['health_stop']}"
            return entry, "stop"
        entry["disposition"] = "accepted"
        return entry, None

    stop_reason = None
    for row in matrix:
        request = launch(row)
        for kind in row["requests"]:
            record, state = request(kind)
            entry, stop = admit(row, kind, record, state)
            if stop:
                stop_reason = entry["reason"]
                total = sum(len(r["requests"]) for r in matrix)
                for ordinal in range(len(requests) + 1, total + 1):
                    requests.append({"launch": None, "ordinal": ordinal,
                                     "disposition": "not_attempted"})
                return _summary(requests, matrix, stopped=True, reason=stop_reason)
    return _summary(requests, matrix, stopped=False, reason=None)


def _summary(requests, matrix, stopped, reason):
    return {
        "schema": "issue280-corrected-runner/1",
        "terminal": "STOP" if stopped else "COMPLETE",
        "stop_reason": reason,
        "requests": requests,
        "matrix_shape": {"launches": len(matrix), "requests": sum(len(r["requests"]) for r in matrix)},
        "physical_execution": "NONE; pure gate engine over an injected executor",
    }
