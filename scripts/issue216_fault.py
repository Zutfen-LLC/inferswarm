#!/usr/bin/env python3
"""Issue #216 — V2-D Phase-6 process-level fault isolation (inferswarm02).

Arm A: terminate participant A while B remains active; prove A gone;
require B finishes its bounded work correctly on die B without
fallback/reassignment; relaunch A from the exact frozen argv; require A
rebinds to die A and passes its sentinel; require a fresh A+B
concurrent sentinel passes.

Arm B: symmetric.

The frozen termination method is SIGKILL (process-level, unambiguous).
Survivor's own selected-device line + seam observe record prove it
stayed on its die; the assembler re-derives everything from bytes.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue216_concurrent as conc
import issue216_execution as ex
import issue216_host as host
import issue216_receipt as rc

ROOT = Path(__file__).resolve().parents[1]


def launch_participant(d: Path, die: str, mapping: dict[str, Any],
                       authority: dict[str, Any], attempt: str
                       ) -> tuple[subprocess.Popen, dict[str, Any]]:
    runtime = authority["runtime"]
    observe_exe = runtime["observe_runtime_executable"]
    participant = mapping["participants"][die]
    d.mkdir(parents=True, exist_ok=True)
    argv = ex.execution_argv(observe_exe, runtime["model"],
                             participant["fresh_selector"])
    env = dict(os.environ)
    env[runtime["observe_env_gate"]] = str(d / f"observe-{die}.jsonl")
    stdout_f = open(d / "run.stdout", "wb")
    stderr_f = open(d / "run.stderr", "wb")
    p = subprocess.Popen(argv, stdout=stdout_f, stderr=stderr_f,
                         env=env, cwd=str(d))
    return p, {"argv": argv, "pid": p.pid, "dir": d,
               "stdout_f": stdout_f, "stderr_f": stderr_f}


def finish_participant(die: str, spec: dict[str, Any],
                       proc: subprocess.Popen, repo: Path) -> dict:
    spec["stdout_f"].close()
    spec["stderr_f"].close()
    stdout = (spec["dir"] / "run.stdout").read_bytes()
    stderr = (spec["dir"] / "run.stderr").read_bytes()
    rc_ = proc.returncode if proc.poll() is not None else None
    host.durable_write(spec["dir"] / "run.exit-code",
                       f"{rc_ if rc_ is not None else 'RUNNING'}\n".encode())
    stderr_text = stderr.decode("utf-8", "replace")
    run = {
        "label": f"fault-{die}", "argv": spec["argv"],
        "workload_interval_ns": None,
        "timed_out": False,
        "exit_code": rc_ if rc_ is not None else -1,
        "stdout_sha256": ex.sha256_bytes(stdout),
        "stderr_sha256": ex.sha256_bytes(stderr),
        "stdout_bytes": len(stdout),
        "stderr_bytes": len(stderr),
        "stdout_rel": "run.stdout", "stderr_rel": "run.stderr",
        "exit_code_rel": "run.exit-code",
        "selected_bdf": ex.parse_selected_bdf(stderr_text),
        "offloaded_layers": ex.parse_offload(stderr_text),
        "fallback_present": "fallback" in stderr_text.lower(),
    }
    run = ex.derive_execution_facts(repo, run, spec["dir"])
    return run


def run_fault_arm(*, repo: Path, out: Path, attempt_id: str, arm: str,
                  authority: dict[str, Any],
                  mapping: dict[str, Any]) -> dict[str, Any]:
    """arm in ('a','b'): the die to terminate; sibling is the other."""
    rc.verify_closure(repo)
    victim = arm
    sibling = "b" if arm == "a" else "a"
    base = out / f"arm-{arm}-loss"
    # 1. start the frozen concurrent pair
    procs: dict[str, Any] = {}
    specs: dict[str, Any] = {}
    for die in ("a", "b"):
        p, spec = launch_participant(base / "initial" / die, die, mapping,
                                     authority, attempt_id)
        procs[die] = p
        specs[die] = spec
    # 2. establish both healthy: wait until both have loaded the model
    #    (selected-device line present in stderr) — bounded wait
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        states = {}
        for die in ("a", "b"):
            try:
                text = (specs[die]["dir"] / "run.stderr").read_text(
                    errors="replace")
            except OSError:
                text = ""
            states[die] = ex.parse_selected_bdf(text) is not None
        if all(states.values()):
            break
        if any(p.poll() is not None for p in procs.values()):
            break
        time.sleep(0.5)
    # 3. terminate victim with SIGKILL; prove gone
    kill_at = time.monotonic_ns()
    procs[victim].send_signal(signal.SIGKILL)
    procs[victim].wait(timeout=30)
    victim_gone = procs[victim].poll() is not None
    # 4. sibling must finish its bounded work
    sib_spec = specs[sibling]
    try:
        procs[sibling].wait(timeout=1900)
    except subprocess.TimeoutExpired:
        procs[sibling].kill()
        procs[sibling].wait(timeout=30)
    sibling_run = finish_participant(sibling, sib_spec, procs[sibling],
                                     repo)
    sibling_verdict = ex.reduce_run(sibling_run)
    sibling_run["killed_sibling_at_ns"] = kill_at
    # 5. relaunch victim from the exact frozen argv/config
    rproc, rspec = launch_participant(base / "relaunch" / victim, victim,
                                      mapping, authority, attempt_id)
    rproc.wait(timeout=1900)
    relaunch_run = finish_participant(victim, rspec, rproc, repo)
    relaunch_verdict = ex.reduce_run(relaunch_run)
    # 6. fresh A+B concurrent sentinel
    sentinel = conc.run_pair(repo=repo, out=base / "recovery-sentinel",
                             attempt_id=f"fault{arm}-recovery",
                             authority=authority, mapping=mapping,
                             phase="fault-recovery")
    record = {
        "schema": "inferswarm.v2d.fault-arm/2",
        "campaign_id": rc.CAMPAIGN_ID,
        "attempt_id": attempt_id,
        "arm": arm,
        "victim": victim,
        "sibling": sibling,
        "victim_gone": victim_gone,
        "kill_method": "SIGKILL",
        "sibling_run": sibling_run,
        "sibling_verdict": sibling_verdict,
        "relaunch_run": relaunch_run,
        "relaunch_verdict": relaunch_verdict,
        "recovery_sentinel": sentinel,
        "authority_digest": authority["authority_digest"],
        "mapping_digest": mapping["mapping_digest"],
    }
    (base / f"fault-arm-{arm}.json").write_bytes(
        json.dumps(record, indent=1, sort_keys=True).encode() + b"\n")
    return record


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--attempt-id", required=True)
    ap.add_argument("--authority", required=True)
    ap.add_argument("--mapping", required=True)
    ap.add_argument("--arm", choices=("a", "b"), required=True)
    args = ap.parse_args()
    repo = Path(args.repo)
    out = Path(args.out)
    authority = json.loads(Path(args.authority).read_text())
    mapping = json.loads(Path(args.mapping).read_text())
    record = run_fault_arm(repo=repo, out=out, attempt_id=args.attempt_id,
                           arm=args.arm, authority=authority,
                           mapping=mapping)
    ok = (record["victim_gone"] and record["sibling_verdict"]["correct"]
          and record["relaunch_verdict"]["correct"])
    print(json.dumps({"arm": args.arm, "ok": ok}))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
