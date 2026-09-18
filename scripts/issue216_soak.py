#!/usr/bin/env python3
"""Issue #216 — V2-D Phase-5 sustained simultaneous soak (inferswarm02).

Frozen: 60-minute minimum duration, 60s telemetry cadence, periodic
concurrent correctness checkpoints every 600s, one final post-soak
sentinel. The soak workload keeps both dies meaningfully active within
accepted Vulkan execution semantics: repeating bounded concurrent pairs
(sustained loop of the frozen concurrent subject).

The collector:
  * retains every telemetry sample's RAW receipt (probe argv + rc +
    stdout bytes) — never an authored summary;
  * derives nothing: classification happens in the assembler from
    these retained bytes;
  * never silently restarts a worker: any participant exit is retained
    as an event, ends the collection, and is classified by the
    assembler;
  * maintains a continuous liveness record (PID + /proc state per
    participant per sample);
  * scans the kernel journal incrementally (cursor-based) for
    amdgpu/AER/reset/thermal event deltas;
  * runs each checkpoint as a REAL bounded concurrent pair through the
    seam instrument, retaining raw bytes per checkpoint.

Duration/cadence are frozen CLI constants; shorter values fail closed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
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

MIN_DURATION_S = 3600
CADENCE_S = 60
CHECKPOINT_EVERY_S = 600
SCHED_TOLERANCE_S = 15

SCHEMA = "inferswarm.v2d.soak-run/2"


def telemetry_snapshot(out_dir: Path, sample: int, bdfs: list[str],
                       pids: dict[str, int]) -> dict[str, Any]:
    """One cadence tick: per-die telemetry + host health + PID states."""
    row: dict[str, Any] = {
        "sample": sample,
        "monotonic_ns": time.monotonic_ns(),
        "telemetry": {},
        "host": host.host_health(),
        "pids": {},
    }
    for bdf in bdfs:
        row["telemetry"][bdf] = host.telemetry_sample(bdf)
        row["aer"] = row.get("aer", {})
        row["aer"][bdf] = host.aer_counters(bdf)
    for die, pid in pids.items():
        state = None
        try:
            state = (Path(f"/proc/{pid}/stat").read_text()
                     .rsplit(")", 1)[1].split()[0])
        except (OSError, IndexError):
            state = "GONE"
        row["pids"][die] = {"pid": pid, "state": state}
    return row


def run_soak(*, repo: Path, out: Path, attempt_id: str,
             authority: dict[str, Any], mapping: dict[str, Any],
             duration_s: int) -> dict[str, Any]:
    rc.verify_closure(repo)
    if duration_s < MIN_DURATION_S:
        raise SystemExit("frozen soak parameters rejected: duration")
    bdfs = [mapping["participants"][d]["fresh_pci_bdf"]
            for d in ("a", "b")]
    raw = out / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    runtime = authority["runtime"]
    observe_exe = runtime["observe_runtime_executable"]
    env_gate = runtime["observe_env_gate"]

    # Sustained workload: rolling concurrent pairs; when a pair finishes,
    # the next starts. Pair i uses observe file observe-{i}.jsonl.
    pair_index = 0
    active: dict[str, subprocess.Popen] = {}
    events: list[dict[str, Any]] = []
    samples: list[dict[str, Any]] = []
    start = time.monotonic_ns()
    cursor = None
    next_checkpoint = CHECKPOINT_EVERY_S

    def launch_pair() -> None:
        nonlocal pair_index, active
        pair_index += 1
        idx = pair_index
        d = raw / f"pair-{idx:04d}"
        d.mkdir(parents=True, exist_ok=True)
        for die in ("a", "b"):
            participant = mapping["participants"][die]
            argv = ex.execution_argv(observe_exe, runtime["model"],
                                     participant["fresh_selector"])
            env = dict(os.environ)
            env[env_gate] = str(d / f"observe-{die}.jsonl")
            stdout_f = open(d / f"{die}.stdout", "wb")
            stderr_f = open(d / f"{die}.stderr", "wb")
            p = subprocess.Popen(argv, stdout=stdout_f,
                                 stderr=stderr_f, env=env,
                                 cwd=str(d))
            active[f"{idx}:{die}"] = p
        events.append({"event": "pair_launched", "pair": idx,
                       "monotonic_ns": time.monotonic_ns(),
                       "pids": {k: p.pid for k, p in active.items()}})

    launch_pair()
    sample_no = 0
    stop_reason = None
    while True:
        now = time.monotonic_ns()
        elapsed_s = (now - start) // 1_000_000_000
        if elapsed_s >= duration_s:
            stop_reason = "duration_reached"
            break
        # cadence tick
        sample_no += 1
        pids = {k.split(":")[1]: p.pid for k, p in active.items()}
        snap = telemetry_snapshot(raw, sample_no, bdfs, pids)
        snap_bytes = json.dumps(snap, sort_keys=True).encode()
        host.durable_write(raw / f"telemetry-{sample_no:04d}.json",
                           snap_bytes)
        samples.append({"sample": sample_no,
                        "rel": f"raw/telemetry-{sample_no:04d}.json",
                        "sha256": hashlib.sha256(snap_bytes).hexdigest(),
                        "monotonic_ns": snap["monotonic_ns"]})
        # journal delta
        j = host.journal_scan(cursor=cursor)
        host.durable_write(raw / f"journal-{sample_no:04d}.stdout",
                           j["text"].encode())
        cursor = j["next_cursor"] or cursor
        # worker liveness: any participant exit ends collection (no silent
        # restart); classify in assembler
        reaped = []
        for key, p in list(active.items()):
            if p.poll() is not None:
                reaped.append((key, p.returncode))
                del active[key]
        if reaped:
            events.append({"event": "participant_exit", "pair_die": reaped,
                           "monotonic_ns": time.monotonic_ns()})
            # a finished pair member: if the whole pair finished, that is
            # normal (bounded subject); relaunch to sustain load
            idx_done = {k.split(":")[0] for k, _ in reaped}
            still = [k for k in active if k.split(":")[0] in idx_done]
            if not still:
                events.append({"event": "pair_completed",
                               "pair": idx_done,
                               "monotonic_ns": time.monotonic_ns()})
                launch_pair()
            else:
                stop_reason = "participant_exit_with_sibling_active"
                break
        # periodic checkpoint
        if elapsed_s >= next_checkpoint:
            cp = conc.run_pair(repo=repo, out=raw / f"checkpoint-"
                               f"{next_checkpoint:04d}",
                               attempt_id=f"soakcp{next_checkpoint}",
                               authority=authority, mapping=mapping,
                               phase="soak-checkpoint")
            host.durable_write(
                raw / f"checkpoint-{next_checkpoint:04d}.json",
                json.dumps(cp, indent=1, sort_keys=True).encode())
            next_checkpoint += CHECKPOINT_EVERY_S
        target = now + CADENCE_S * 1_000_000_000
        sleep_s = (target - time.monotonic_ns()) / 1e9
        if sleep_s > 0:
            time.sleep(sleep_s)

    end = time.monotonic_ns()
    # stop remaining workers
    for p in active.values():
        p.terminate()
    for p in active.values():
        try:
            p.wait(timeout=30)
        except subprocess.TimeoutExpired:
            p.kill()
    # final post-soak sentinel pair
    final = conc.run_pair(repo=repo, out=raw / "final-sentinel",
                          attempt_id="soakfinal", authority=authority,
                          mapping=mapping, phase="soak-final")
    host.durable_write(raw / "final-sentinel.json",
                       json.dumps(final, indent=1, sort_keys=True).encode())
    j = host.journal_scan(cursor=cursor)
    host.durable_write(raw / "journal-final.stdout", j["text"].encode())

    record = {
        "schema": SCHEMA,
        "campaign_id": rc.CAMPAIGN_ID,
        "attempt_id": attempt_id,
        "started_ns": start,
        "ended_ns": end,
        "duration_s": (end - start) // 1_000_000_000,
        "requested_duration_s": duration_s,
        "cadence_s": CADENCE_S,
        "checkpoint_every_s": CHECKPOINT_EVERY_S,
        "sched_tolerance_s": SCHED_TOLERANCE_S,
        "stop_reason": stop_reason,
        "pairs_launched": pair_index,
        "events": events,
        "samples": samples,
        "authority_digest": authority["authority_digest"],
        "mapping_digest": mapping["mapping_digest"],
    }
    (out / f"soak-{attempt_id}.json").write_bytes(
        json.dumps(record, indent=1, sort_keys=True).encode() + b"\n")
    return record


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--attempt-id", required=True)
    ap.add_argument("--authority", required=True)
    ap.add_argument("--mapping", required=True)
    ap.add_argument("--duration", type=int, default=MIN_DURATION_S)
    args = ap.parse_args()
    repo = Path(args.repo)
    out = Path(args.out)
    authority = json.loads(Path(args.authority).read_text())
    mapping = json.loads(Path(args.mapping).read_text())
    record = run_soak(repo=repo, out=out, attempt_id=args.attempt_id,
                      authority=authority, mapping=mapping,
                      duration_s=args.duration)
    print(json.dumps({"duration_s": record["duration_s"],
                      "stop_reason": record["stop_reason"],
                      "pairs": record["pairs_launched"],
                      "samples": len(record["samples"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
