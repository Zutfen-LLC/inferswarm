#!/usr/bin/env python3
"""Issue #216 — V2-D Phase-4 shared-x1 transport matrix (inferswarm02).

Reuses the ACCEPTED #35 transport probe (scripts/issue35_link_probe.py,
imported never forked) per die. Modes:

  single-a: probe bound to die A only;
  single-b: probe bound to die B only;
  dual: two probe instances launched concurrently (one per die), each
        retaining its own raw output + the pair's launch intervals.

The probe measures H2D/D2H sustained bandwidth over frozen size ladder,
small-transfer service, bidirectional sample, and samples sysfs link
state DURING load (the idle link downtrains). All values are
DESCRIPTIVE: no throughput number is a correctness predicate (issue:
performance slowdown is not a correctness failure).

Sizes/reps frozen here (same ladder as #35: 4/16/64/128 MiB, 8 reps;
4 KiB x 200 service; 32 MiB x 8 bidir) so the sweep cannot be tuned
after observing results.
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
import issue216_receipt as rc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import issue35_link_probe as x1  # accepted transport probe


def _probe_argv(repo: Path, build_dir: Path, device_name_substring: str,
                match_index: int, selector_index: int, runtime: str,
                model: str) -> list[str]:
    return [sys.executable, str(repo / "scripts" / "issue35_link_probe.py"),
            "--device-name-substring", device_name_substring,
            "--name-match-index", str(match_index),
            "--selector-index", str(selector_index),
            "--runtime-executable", runtime,
            "--model", model,
            "--build-dir", str(build_dir)]


def run_probe_instance(argv: list[str], out_dir: Path, label: str,
                       timeout: int = 1800) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    start = time.monotonic_ns()
    try:
        p = subprocess.run(argv, capture_output=True, timeout=timeout)
        rc_, stdout, stderr = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as exc:
        rc_, stdout, stderr = 124, exc.stdout or b"", b"PROBE_TIMEOUT\n"
    end = time.monotonic_ns()
    host.durable_write(out_dir / f"{label}.stdout", stdout)
    host.durable_write(out_dir / f"{label}.stderr", stderr)
    host.durable_write(out_dir / f"{label}.exit-code", f"{rc_}\n".encode())
    return {"label": label, "argv": argv,
            "interval_ns": [start, end], "exit_code": rc_,
            "stdout_rel": f"{label}.stdout",
            "stderr_rel": f"{label}.stderr",
            "exit_code_rel": f"{label}.exit-code",
            "stdout_sha256": host.sha256_text(stdout),
            "stderr_sha256": host.sha256_text(stderr)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--attempt-id", required=True)
    ap.add_argument("--authority", required=True)
    ap.add_argument("--mapping", required=True)
    ap.add_argument("--build-dir", required=True,
                    help="writable dir for the probe's Vulkan binary build")
    args = ap.parse_args()
    repo = Path(args.repo)
    out = Path(args.out)
    rc.verify_closure(repo)
    authority = json.loads(Path(args.authority).read_text())
    mapping = json.loads(Path(args.mapping).read_text())
    runtime = authority["runtime"]

    runs: dict[str, Any] = {}
    # single-die arms
    for mode, die in (("single-a", "a"), ("single-b", "b")):
        p = mapping["participants"][die]
        argv = _probe_argv(repo, Path(args.build_dir),
                           "AMD Radeon Pro V340", _match_index(
                               mapping, die),
                           _selector_index(mapping, die),
                           runtime["executable"], runtime["model"])
        runs[mode] = run_probe_instance(argv, out / mode, mode)

    # dual arm: two concurrent instances
    argvs = {die: _probe_argv(repo, Path(args.build_dir),
                              "AMD Radeon Pro V340",
                              _match_index(mapping, die),
                              _selector_index(mapping, die),
                              runtime["executable"], runtime["model"])
             for die in ("a", "b")}
    procs = {}
    intervals: dict[str, list[int | None]] = {}
    for die in ("a", "b"):
        d = out / "dual" / die
        d.mkdir(parents=True, exist_ok=True)
        log = d / "probe.stdout"
        err = open(d / "probe.stderr", "wb")
        t0 = time.monotonic_ns()
        procs[die] = (subprocess.Popen(argvs[die], stdout=open(log, "wb"),
                                       stderr=err), log, err)
        intervals[die] = [t0, None]
    dual_runs = {}
    for die, (proc, log, err) in procs.items():
        proc.wait(timeout=1900)
        err.close()
        intervals[die][1] = time.monotonic_ns()
        stdout = log.read_bytes()
        stderrb = (d_err := (out / "dual" / die / "probe.stderr")
                   ).read_bytes()
        host.durable_write(out / "dual" / die / "probe.exit-code",
                           f"{proc.returncode}\n".encode())
        dual_runs[die] = {
            "argv": argvs[die], "interval_ns": intervals[die],
            "exit_code": proc.returncode,
            "stdout_rel": f"dual/{die}/probe.stdout",
            "stderr_rel": f"dual/{die}/probe.stderr",
            "exit_code_rel": f"dual/{die}/probe.exit-code",
            "stdout_sha256": host.sha256_text(stdout),
            "stderr_sha256": host.sha256_text(stderrb),
        }
    # require actual probe-process overlap (scheduling proof only; the
    # transport numbers themselves are per-probe measured facts)
    a0 = int(intervals["a"][0])
    b0 = int(intervals["b"][0])
    end_a = a0
    end_b = b0
    complete = True
    if intervals["a"][1] is not None:
        end_a = int(intervals["a"][1])
    else:
        complete = False
    if intervals["b"][1] is not None:
        end_b = int(intervals["b"][1])
    else:
        complete = False
    overlap = complete and max(a0, b0) < min(end_a, end_b)
    runs["dual"] = {"participants": dual_runs,
                    "probe_process_overlap": overlap,
                    "intervals_ns": intervals}

    (out / f"transport-{args.attempt_id}.json").write_bytes(
        json.dumps(runs, indent=1, sort_keys=True).encode() + b"\n")
    ok = all(r["exit_code"] == 0 for r in
             (runs["single-a"], runs["single-b"])) and \
        all(r["exit_code"] == 0 for r in dual_runs.values()) and overlap
    print(json.dumps({"ok": ok, "modes": sorted(runs)}))
    return 0 if ok else 1


def _match_index(mapping: dict[str, Any], die: str) -> int:
    sel = mapping["participants"][die]["fresh_selector"]
    return int(sel.replace("Vulkan", "")) - 1


def _selector_index(mapping: dict[str, Any], die: str) -> int:
    return _match_index(mapping, die)


if __name__ == "__main__":
    raise SystemExit(main())
