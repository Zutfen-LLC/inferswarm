#!/usr/bin/env python3
"""Scheduling-equivalence check for an untimed MoE harness export.

Separate, narrower question than the numerical contracts: did the serial and
overlapped scheduling arms execute the SAME work (same inputs, routing,
ownership split, workload, shared branch) and produce bitwise-identical
outputs, with the native replay/determinism/status checks and the
omitted-work negative control in place?

This contract (moe-scheduling-equivalence/1) reuses the existing
`--dump-reference-case` exports and run.json unchanged. It never sets
hardware_qualified, claims no backend numerical correctness, and qualifies no
model: both arms can share a numerical defect, and the legacy
CPU-unsplit / moe-operand-reference diagnostics are preserved verbatim as
separate FAIL-able evidence. The case directory is only read, never written.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np

from operand_reference import _finite

CONTRACT = "moe-scheduling-equivalence/1"
N_EMBD = 2560
N_USED = 10
PIN = "llama.cpp b29c606e28a01b1bc8c1351026a0fa6e616bf6c4"

# What a scheduling PASS may claim — fixed scope text, echoed into reports.
SCOPE_LIMITS = (
    "Scheduling equivalence only: identical work executed under two schedules.",
    "No claim of backend numerical correctness; both arms can share a numerical defect.",
    "Not hardware qualification; hardware_qualified stays false and no full model is qualified.",
    "Model-weight identity and cross-arm input identity are single-process construction "
    "invariants of the resident harness (weights loaded once; both arms consume one "
    "ArmContext per repetition); the export retains one operand set per repetition, "
    "not per arm.",
    "T>1 zero-weight padding correctness is a harness construction invariant guarded by "
    "the unit-routing seam regressions; padded ids/weights are not part of this export.",
)


def _read(case: Path, name: str, dtype: str, shape) -> np.ndarray:
    try:
        raw = (case / name).read_bytes()
    except OSError as exc:
        raise ValueError(f"incomplete capture: {name} ({exc.strerror})") from exc
    if len(raw) != int(np.prod(shape)) * np.dtype(dtype).itemsize:
        raise ValueError(f"incomplete capture: {name}")
    return np.frombuffer(raw, dtype=dtype).reshape(shape)


def _classify_native(report: dict) -> tuple[str, list[str]]:
    """PASS / LEGACY_NUMERICAL_ONLY_FAIL / EXECUTION_FAILURE.

    An overall native FAIL is NOT an execution failure when the legacy
    cross-backend numerical comparison is the only failing diagnostic. Every
    other reason (routing defect, nondeterminism, compute/status failure,
    failed control) is an execution or schedule failure and blocks PASS.
    """
    v = report["verdict"]
    reps = report.get("reps", [])
    problems: list[str] = []
    if not reps or len(reps) != report["config"]["reps"]:
        problems.append("native run incomplete: repetition records missing")
        return "EXECUTION_FAILURE", problems
    schedule_ok = all(r["checks"].get(k) is True for r in reps for k in (
        "routed_counts_ok", "overlap_vs_serial_bitwise", "overlap_vs_serial_pass"))
    det = report.get("determinism_recheck", {})
    replay_ok = det.get("reference_bitwise") is True and det.get("serial_bitwise") is True
    control_ok = report.get("negative_control", {}).get("comparator_rejected") is True
    released = report.get("resources_released") is True
    if v.get("pass") is True:
        outcome = "PASS" if all([schedule_ok, replay_ok, control_ok, released]) else "EXECUTION_FAILURE"
    elif v.get("reason") == "validation failed" and schedule_ok and replay_ok and control_ok and released:
        # Only the legacy serial-vs-unsplit comparison may have failed.
        outcome = "LEGACY_NUMERICAL_ONLY_FAIL"
    else:
        outcome = "EXECUTION_FAILURE"
    if not schedule_ok:
        problems.append("native schedule/routing check failed")
    if not replay_ok:
        problems.append("native replay/determinism check failed")
    if not control_ok:
        problems.append("native negative control missing or not rejected")
    if not released:
        problems.append("native resources not released")
    return outcome, problems


def check_case(case) -> dict:
    """Evaluate scheduling equivalence from a retained export. Read-only."""
    case = Path(case)
    report = json.loads((case / "run.json").read_text())
    c = report["config"]
    problems: list[str] = []
    T, E, split = c["tokens"], c["n_expert"], c["split"]
    if (T not in (1, 128) or c["n_embd"] != N_EMBD or c["n_ff"] != 640
            or c["n_used"] != N_USED or E < N_USED or not 0 <= split <= E
            or c["weights_mode"] not in ("GGUF", "SYNTHETIC") or c["native_pin"] != PIN):
        raise ValueError("unsupported scheduling-reference configuration")

    outcome, problems = _classify_native(report)

    reps_out = []
    try:
        for i, rep in enumerate(report["reps"]):
            if rep.get("rep") != i:
                raise ValueError(f"repetition index mismatch at {i}")
            x = _read(case, f"rep-{i}-cur.f32", "<f4", (T, N_EMBD))
            ids = _read(case, f"rep-{i}-ids.i32", "<i4", (T, N_USED))
            w = _read(case, f"rep-{i}-weights.f32", "<f4", (T, N_USED))
            _finite(x); _finite(w)
            if ids.dtype.kind != "i" or (ids < 0).any() or (ids >= E).any():
                raise ValueError(f"rep {i}: captured expert id outside bank")
            if any(len(set(row.tolist())) != N_USED for row in ids):
                raise ValueError(f"rep {i}: duplicate selected expert id within a token")
            if (w < 0).any():
                raise ValueError(f"rep {i}: negative routing weight")
            # Re-derive ownership/workload from bytes and cross-check the
            # native accounting: this is what ties the retained routing to the
            # claimed ownership split and complete routed workload.
            per_tok_cpu = (ids < split).sum(axis=1)
            n_cpu, n_sec = int((ids < split).sum()), int((ids >= split).sum())
            if n_cpu + n_sec != N_USED * T:
                raise ValueError(f"rep {i}: routed workload below top-{N_USED} contract")
            if rep.get("k_cpu_real") != n_cpu or rep.get("k_sec_real") != n_sec:
                raise ValueError(f"rep {i}: ownership split inconsistent with captured routing")
            if T == 1:
                if rep.get("k_cpu") != n_cpu or rep.get("k_sec") != n_sec:
                    raise ValueError(f"rep {i}: padded width inconsistent at T=1")
            else:
                if rep.get("k_cpu") != int(per_tok_cpu.max()) or rep.get("k_sec") != int((N_USED - per_tok_cpu).max()):
                    raise ValueError(f"rep {i}: padded width inconsistent with per-token maxima")
            cpu = _read(case, f"rep-{i}-cpu.f32", "<f4", x.shape)
            sec = _read(case, f"rep-{i}-sec.f32", "<f4", x.shape)
            shared = _read(case, f"rep-{i}-shared.f32", "<f4", x.shape)
            serial = _read(case, f"rep-{i}-serial.f32", "<f4", x.shape)
            overlap = _read(case, f"rep-{i}-overlap.f32", "<f4", x.shape)
            for name, arr in (("cpu partial", cpu), ("secondary partial", sec),
                              ("shared branch", shared), ("serial output", serial),
                              ("overlapped output", overlap)):
                _finite(np.asarray(arr, dtype=np.float64))
                if arr.shape != x.shape:
                    raise ValueError(f"rep {i}: {name} shape mismatch")
            checks = {}
            checks["outputs_bitwise_identical"] = serial.tobytes() == overlap.tobytes()
            if not checks["outputs_bitwise_identical"]:
                problems.append(f"rep {i}: serial and overlapped outputs differ")
            # Same combine the harness performs: one F32 add per element,
            # (cpu + sec) + shared. Ties both arm outputs to the retained
            # expert subsets and shared branch (omitted work cannot match).
            combined = (cpu + sec) + shared
            checks["serial_combine_identity"] = serial.tobytes() == combined.tobytes()
            checks["overlap_combine_identity"] = overlap.tobytes() == combined.tobytes()
            for name in ("serial", "overlap"):
                if not checks[f"{name}_combine_identity"]:
                    problems.append(f"rep {i}: {name} output not composed of retained partials + shared")
            reps_out.append({"rep": i, "checks": checks, "k_cpu_real": n_cpu,
                             "k_sec_real": n_sec,
                             "legacy_cpu_unsplit_diagnostic": rep["checks"].get(
                                 "legacy_cpu_unsplit_diagnostic", {
                                     "pass": rep["checks"]["serial_vs_ref_pass"],
                                     "max_abs": rep["checks"]["serial_vs_ref_max_abs"],
                                     "max_ratio": rep["checks"]["serial_vs_ref_max_ratio"]})})
    except (ValueError, KeyError, OSError, TypeError) as exc:
        problems.append(str(exc))
        reps_out = reps_out or [{"rep": 0, "checks": {}, "error": str(exc)}]

    # Numerical diagnostics are retained separately, never re-derived here and
    # never rewritten: an old FAIL stays FAIL under this contract.
    try:
        operand_status = json.loads((case / "reference.json").read_text()).get("status", "FAIL")
    except (OSError, ValueError, AttributeError):
        operand_status = "NOT_REQUESTED"

    byte_checks_ok = bool(reps_out) and all(
        all(r.get("checks", {}).values()) for r in reps_out) and not problems
    passed = outcome in ("PASS", "LEGACY_NUMERICAL_ONLY_FAIL") and byte_checks_ok
    return {
        "contract": CONTRACT,
        "status": "SCHEDULING_EQUIVALENT" if passed else "FAIL",
        "hardware_qualified": False,
        "native_outcome": outcome,
        "checks": {
            "native_schedule_routing_replay_control": outcome in ("PASS", "LEGACY_NUMERICAL_ONLY_FAIL"),
            "same_inputs_routing_ownership_workload": byte_checks_ok,
            "outputs_bitwise_identical": byte_checks_ok and all(
                r.get("checks", {}).get("outputs_bitwise_identical") for r in reps_out),
            "combine_identity_all_reps": byte_checks_ok,
            "complete_exports": byte_checks_ok,
        },
        "problems": problems,
        "legacy_cpu_unsplit_verdict": report["verdict"],
        "moe_operand_reference_status": operand_status,
        "scope_limits": list(SCOPE_LIMITS),
        "reps": reps_out,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("case", type=Path)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    try:
        result = check_case(args.case)
    except (ValueError, KeyError, OSError, TypeError) as exc:
        result = {"contract": CONTRACT, "status": "INVALID_OR_INCOMPLETE",
                  "hardware_qualified": False, "error": str(exc)}
    text = json.dumps(result, indent=2, allow_nan=False) + "\n"
    if args.json:
        args.json.write_text(text)
    print(text, end="")
    return 0 if result["status"] == "SCHEDULING_EQUIVALENT" else 3


if __name__ == "__main__":
    raise SystemExit(main())
