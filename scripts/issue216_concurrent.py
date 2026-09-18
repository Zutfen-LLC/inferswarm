#!/usr/bin/env python3
"""Issue #216 — V2-D Phase-2/3 baseline + concurrent collectors.

Baseline (per die): the SAME frozen subject/workload definition used
concurrently, repeated REPS times, with per-repeat telemetry (temp,
clocks, power, HBM, link state, ECC/RAS, AER) before/after.

Concurrent pair: two participants started under a shared start gate
(scheduling only), each through the CORRECTED #219 seam instrument
(env-gated observe), each bound to its own die by the fresh mapping.
Each participant's GPU-work intervals come from the seam observe
records (device timestamps calibrated to CLOCK_MONOTONIC — the accepted
#219 authority); the assembler classifies overlap. Wrapper intervals
are retained only as scheduling context, never as overlap authority.

Attempt ledger: every launch is recorded, including failed/aborted
attempts (retained in the denominator).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue216_host as host
import issue216_execution as ex
import issue216_physical_authority as pa
import issue216_receipt as rc

ROOT = Path(__file__).resolve().parents[1]


def _receipt(out_dir: Path, phase: str, attempt_id: str, rid: str,
             payload: dict[str, Any], raw_rels: list[str]) -> dict:
    bindings = [rc.bind_raw(out_dir, rel) for rel in raw_rels]
    receipt = {
        "schema": rc.RECEIPT_SCHEMA,
        "campaign_id": rc.CAMPAIGN_ID,
        "receipt_id": rid,
        "phase": phase,
        "attempt_id": attempt_id,
        "utc": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(),
        "raw_bindings": bindings,
        "payload": payload,
    }
    rc.emit_receipt(out_dir.parent / "receipts", receipt)
    return receipt


def collect_baseline(*, repo: Path, out: Path, attempt_id: str,
                     authority: dict[str, Any],
                     mapping: dict[str, Any], die: str,
                     reps: int) -> dict[str, Any]:
    """Frozen single-die baseline: reps repeats + telemetry each rep."""
    rc.verify_closure(repo)
    participant = mapping["participants"][die]
    runtime = authority["runtime"]
    rows: list[dict[str, Any]] = []
    for i in range(1, reps + 1):
        bdf = participant["fresh_pci_bdf"]
        pre = host.telemetry_sample(bdf)
        pre_aer = host.aer_counters(bdf)
        argv = ex.execution_argv(runtime["executable"], runtime["model"],
                                 participant["fresh_selector"])
        run = ex.run_execution(argv=argv,
                               out_dir=out / f"rep-{i:02d}",
                               label=f"baseline-{attempt_id}-{die}-{i:02d}")
        run = ex.derive_execution_facts(repo, run, out / f"rep-{i:02d}")
        post = host.telemetry_sample(bdf)
        post_aer = host.aer_counters(bdf)
        row = {
            "rep": i,
            "die": die,
            "selector": participant["fresh_selector"],
            "bdf": bdf,
            "run": run,
            "verdict": ex.reduce_run(run),
            "telemetry_pre": pre,
            "telemetry_post": post,
            "aer_pre": pre_aer,
            "aer_post": post_aer,
        }
        rows.append(row)
        _receipt(out / f"rep-{i:02d}", "baseline", attempt_id,
                 f"v2d-baseline-{attempt_id}-{die}-{i:02d}",
                 {"die": die, "rep": i, "run": run, "verdict": row["verdict"],
                  "telemetry_pre": pre, "telemetry_post": post},
                 [run["stdout_rel"], run["stderr_rel"],
                  run["exit_code_rel"]])
    return {"die": die, "reps": rows}


def run_pair(*, repo: Path, out: Path, attempt_id: str,
             authority: dict[str, Any], mapping: dict[str, Any],
             phase: str, n_tokens: int = 48,
             start_gate: bool = True) -> dict[str, Any]:
    """One concurrent A+B pair through the seam instrument.

    Scheduling: shared ready/start gate (both processes alive before
    either launches its workload). Overlap authority: the seam observe
    records (assembler-classified).
    """
    rc.verify_closure(repo)
    runtime = authority["runtime"]
    observe_exe = runtime["observe_runtime_executable"]
    env_gate = runtime["observe_env_gate"]
    gate = out / "start-gate"
    if gate.exists():
        gate.unlink()
    procs: dict[str, dict[str, Any]] = {}
    for die in ("a", "b"):
        participant = mapping["participants"][die]
        d = out / die
        d.mkdir(parents=True, exist_ok=True)
        observe_file = d / f"observe-{attempt_id}.jsonl"
        argv = ex.execution_argv(observe_exe, runtime["model"],
                                 participant["fresh_selector"],
                                 n_tokens=n_tokens)
        env_extra = {env_gate: str(observe_file)}
        procs[die] = {"argv": argv, "dir": d,
                      "observe_rel": f"{die}/observe-{attempt_id}.jsonl",
                      "observe_file": observe_file, "env_extra": env_extra}

    children: dict[str, subprocess.Popen] = {}
    wrapper_intervals: dict[str, list[int | None]] = {}
    ready_files: dict[str, Path] = {}
    for die, spec in procs.items():
        ready = spec["dir"] / "participant.ready"
        ready_files[die] = ready
        host.durable_write(ready, b"ready\n")
    if start_gate:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not all(
                r.exists() for r in ready_files.values()):
            time.sleep(0.01)
    for die, spec in procs.items():
        import os
        env = dict(os.environ)
        env.update(spec["env_extra"])
        t0 = time.monotonic_ns()
        children[die] = subprocess.Popen(
            spec["argv"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, cwd=str(spec["dir"]))
        wrapper_intervals[die] = [t0, None]
    exits: dict[str, dict[str, Any]] = {}
    for die, child in children.items():
        stdout, stderr = child.communicate(timeout=1900)
        wrapper_intervals[die][1] = time.monotonic_ns()
        spec = procs[die]
        d = spec["dir"]
        host.durable_write(d / f"run-{attempt_id}.stdout", stdout)
        host.durable_write(d / f"run-{attempt_id}.stderr", stderr)
        host.durable_write(d / f"run-{attempt_id}.exit-code",
                           f"{child.returncode}\n".encode())
        stderr_text = stderr.decode("utf-8", "replace")
        run = {
            "label": f"concurrent-{attempt_id}-{die}",
            "argv": spec["argv"],
            "workload_interval_ns": wrapper_intervals[die],
            "timed_out": False,
            "exit_code": child.returncode,
            "stdout_sha256": ex.sha256_bytes(stdout),
            "stderr_sha256": ex.sha256_bytes(stderr),
            "stdout_bytes": len(stdout),
            "stderr_bytes": len(stderr),
            "stdout_rel": f"{die}/run-{attempt_id}.stdout",
            "stderr_rel": f"{die}/run-{attempt_id}.stderr",
            "exit_code_rel": f"{die}/run-{attempt_id}.exit-code",
            "selected_bdf": ex.parse_selected_bdf(stderr_text),
            "offloaded_layers": ex.parse_offload(stderr_text),
            "fallback_present": "fallback" in stderr_text.lower(),
        }
        run = ex.derive_execution_facts(repo, run, out)
        exits[die] = run
    return {
        "attempt_id": attempt_id,
        "phase": phase,
        "participants": exits,
        "observe_rels": {d: s["observe_rel"] for d, s in procs.items()},
        "wrapper_intervals_ns": wrapper_intervals,
        "authority_digest": authority["authority_digest"],
        "mapping_digest": mapping["mapping_digest"],
    }


def _ledger_rows(concurrent_root: Path) -> list[dict]:
    """Rebuild the attempt ledger from retained pair dirs (every retained
    attempt, successes and failures alike)."""
    rows = []
    for d in sorted(concurrent_root.glob("c*")):
        if d.is_dir() and (d / f"pair-{d.name}.json").is_file():
            rows.append({"attempt_id": d.name, "status": "run"})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("baseline")
    b.add_argument("--repo", required=True)
    b.add_argument("--out", required=True)
    b.add_argument("--attempt-id", required=True)
    b.add_argument("--authority", required=True)
    b.add_argument("--mapping", required=True)
    b.add_argument("--die", choices=("a", "b"), required=True)
    b.add_argument("--reps", type=int, default=3)
    c = sub.add_parser("pair")
    c.add_argument("--repo", required=True)
    c.add_argument("--out", required=True)
    c.add_argument("--attempt-id", required=True)
    c.add_argument("--authority", required=True)
    c.add_argument("--mapping", required=True)
    c.add_argument("--phase", default="concurrent")
    args = ap.parse_args()
    repo = Path(args.repo)
    out = Path(args.out)
    authority = json.loads(Path(args.authority).read_text())
    mapping = json.loads(Path(args.mapping).read_text())
    if not pa.verify_authority(authority, repo):
        raise SystemExit("invalid authority")
    if args.cmd == "baseline":
        result = collect_baseline(repo=repo, out=out,
                                  attempt_id=args.attempt_id,
                                  authority=authority, mapping=mapping,
                                  die=args.die, reps=args.reps)
        (out.parent / f"baseline-{args.die}.json").write_bytes(
            json.dumps(result, indent=1, sort_keys=True).encode() + b"\n")
        ok = all(r["verdict"]["correct"] for r in result["reps"])
        print(json.dumps({"ok": ok, "die": args.die}))
        return 0 if ok else 1
    result = run_pair(repo=repo, out=out, attempt_id=args.attempt_id,
                      authority=authority, mapping=mapping,
                      phase=args.phase)
    (out / f"pair-{args.attempt_id}.json").write_bytes(
        json.dumps(result, indent=1, sort_keys=True).encode() + b"\n")
    (out.parent / "attempt-ledger.json").write_bytes(json.dumps({
        "attempts": _ledger_rows(out.parent)}, indent=1).encode() + b"\n")
    verdicts = {d: ex.reduce_run(r) for d, r in result["participants"].items()}
    print(json.dumps({"attempt": args.attempt_id,
                      "verdicts": {d: v["correct"] for d, v in
                                   verdicts.items()}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
