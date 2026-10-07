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
- every admitted request requires a PASS observer-admission verdict derived
  mechanically from its retained raw observer bytes under the frozen physical
  #280 contract (the existing collector's substantive laws, reused — no
  second validator). Event-name presence alone is diagnostic metadata and
  never admits a request;
- candidate requests additionally require completed cross-die boundary /
  transfer evidence under the two-die frozen contract before any further
  candidate work;
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


def _load_observer():
    path = Path(__file__).resolve().parent / "issue280_observer.py"
    spec = importlib.util.spec_from_file_location("issue280_observer", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_observer = _load_observer()

# Frozen physical #280 admission contracts (two retained V340L dies / frozen
# layer split for the candidate arm; single-die baseline arm), consumed by the
# structured observer validator. Replay of retained bytes only.
OBSERVER_CONTRACTS = _observer.physical_280_contracts()


def _observer_verdict(arm, state):
    """Mechanically validate retained observer bytes for a request.

    ``state`` must carry the raw retained observer bytes for the request
    (``observer_raw``) under the frozen contract for its arm. Returns the
    structured verdict from the collector's substantive laws. When no raw
    bytes were retained the verdict fails closed (problems name the gap).
    """
    raw = state.get("observer_raw")
    contract = OBSERVER_CONTRACTS["B" if arm == "B" else "A"]
    if raw is None:
        return {
            "schema": "issue280-observer-admission/1", "ok": False,
            "problems": ["no retained observer bytes for the request"],
            "claim": "FAIL_CLOSED_NO_BYTES", "contract_kind": contract["kind"],
            "contract_dies": list(contract["dies"]), "per_die": {},
            "graph_count": 0, "logical_boundary_bytes": 0, "host_leg_bytes": 0,
            "physical_execution": "NONE",
        }
    return _observer.validate_admission(raw, contract)


def _missing_evidence(row, events):
    """Diagnostic only (issue #284 round 2): event-name presence is metadata,
    never admission authority. Kept to surface WHICH expected names are absent
    in failure diagnostics."""
    required = CANDIDATE_EVIDENCE if row["arm"] == "B" else BASELINE_EVIDENCE
    return [name for name in required if name not in events]


def _compatibility_gate():
    return _observer._compat.check_compatibility()


def run_campaign(matrix, launch):
    """Run the gated loop. ``launch`` maps a matrix row to a callable that
    performs ONE request of a given kind ("cold"/"warm") and returns
    ``(record, launch_state)`` where record has keys label/arm/prompt/kind/
    text/transport_ok (and optional health_stop) and launch_state carries
    ``observer_raw`` (the raw retained observer bytes for the request) and
    ``peak_rss_bytes``. ``observer_events`` is optional diagnostic metadata
    only and never determines acceptance.

    Returns a summary dict; never raises on request outcomes (fail-closed
    instead). Pure with respect to the executor: all STOP decisions are made
    here, synchronously, before the next launch/request is requested.
    """
    requests = []
    compatibility = _compatibility_gate()
    if not compatibility.get("ok", False):
        for ordinal in range(1, sum(len(r["requests"]) for r in matrix) + 1):
            requests.append({"launch": None, "ordinal": ordinal, "disposition": "not_attempted"})
        summary = _summary(requests, matrix, stopped=True,
                           reason="prelaunch compatibility failure: " + "; ".join(compatibility.get("problems", [])))
        summary["compatibility_verdict"] = compatibility
        return summary

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
        # observer admission: mechanically validated retained bytes under the
        # frozen physical #280 contract (issue #284 round 2). Event-name
        # presence is diagnostic metadata only and never admits a request.
        verdict = _observer_verdict(row["arm"], state)
        entry["observer_verdict"] = {
            "ok": verdict["ok"], "problems": verdict["problems"],
            "contract_kind": verdict["contract_kind"],
        }
        if not verdict["ok"]:
            entry["disposition"] = "rejected"
            missing = _missing_evidence(row, state.get("observer_events", ()))
            detail = "; ".join(verdict["problems"][:5]) or "observer validation failed"
            if missing:
                detail += f" (diagnostic missing names: {missing})"
            entry["reason"] = f"observer admission failure: {detail}"
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
