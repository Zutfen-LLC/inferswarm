#!/usr/bin/env python3
"""Issue #219 — V2-D0 non-perturbation + bounded-discrimination runner.

Runs DIRECTLY on inferswarm02. For the instrumented runtime build
(separate tree; the accepted runtime bytes are never touched):

Phase 3 (non-perturbation), per die (Vulkan1 / Vulkan2):
  * disabled arm: bounded accepted V2-compatible execution with the
    seam env unset, through the ACCEPTED argv template;
  * enabled arm: identical argv + GGML_VK_OBSERVE_INTERVAL=<out>;
  * both arms reduced through the ACCEPTED comparator/accounting
    (imported, never forked): byte-exact visible output vs the accepted
    frozen reference, accounting tuple 0/0/0, full offload, no
    fallback, clean exit, selected BDF via the accepted zero-token
    identity probe semantics (the run's own selected-device line).

Phase 5 (bounded discrimination):
  * NON-OVERLAP control: two sequential executions, die A then die B,
    with the seam enabled; retained records for both;
  * OVERLAP-CANDIDATE: two concurrent executions (die A + die B in
    parallel processes), with the seam enabled;
  * scheduling only — argv, model, placement identical everywhere.

Every launch retains: exact argv, stdout/stderr bytes, exit code, seam
JSONL record file, monotonic start/end, and the identity probe for the
die's selector on the SAME boot.

Usage (on inferswarm02):
  python3 issue219_observe_collector.py --phase {perturbation|discrimination}
      --runtime <instrumented llama-cli> --out-root <dir> [--reference <ref>]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "inferswarm.v2d0.observe-run/1"
RUNTIME_ACCEPTED = "/home/zutfen/.cache/v0c-llama.cpp/build-v0c-vulkan/bin/llama-cli"
MODEL = "/home/zutfen/.cache/v0c-models/Qwen2.5-3B-Instruct-Q4_K_M.gguf"
PROMPT = "The quick brown fox jumps over the lazy dog. Explain what happens next in one sentence:"
N_TOKENS = 48
REFERENCE_DEFAULT = ("docs/investigations/vulkan-v1-a/"
                     "reference-visible-output.txt")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import v0c_correctness  # noqa: E402  accepted comparator
import v1c_accounting  # noqa: E402  accepted accounting reducer


def _durable_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    dfd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


def execution_argv(selector: str) -> list[str]:
    return [RUNTIME_ACCEPTED, "-m", MODEL, "--temp", "0", "--seed", "42",
            "-n", str(N_TOKENS), "-ngl", "99", "--device", selector,
            "-lv", "4", "-p", PROMPT, "-st"]


def run_one(argv: list[str], env_extra: dict[str, str], out_dir: Path,
            label: str) -> dict:
    env = dict(os.environ)
    env.update(env_extra)
    t0 = time.monotonic()
    p = subprocess.run(argv, capture_output=True, text=False,
                       timeout=1800, env=env)
    wall = round(time.monotonic() - t0, 3)
    _durable_write(out_dir / f"{label}.stdout", p.stdout)
    _durable_write(out_dir / f"{label}.stderr", p.stderr)
    _durable_write(out_dir / f"{label}.exit-code", f"{p.returncode}\n".encode())
    selected = None
    for line in p.stderr.decode("utf-8", "replace").splitlines():
        m = re.search(r"using device.*?([0-9a-f]{2}:[0-9a-f]{2}\.[0-9])", line)
        if m:
            selected = m.group(1)
            break
    return {"label": label, "argv": argv,
            "env_extra": sorted(env_extra),
            "started_utc": datetime.now(timezone.utc).isoformat(),
            "wall_seconds": wall, "exit_code": p.returncode,
            "selected_bdf": selected,
            "stdout_sha256": hashlib.sha256(p.stdout).hexdigest(),
            "stderr_sha256": hashlib.sha256(p.stderr).hexdigest()}


def reduce_accepted(run: dict, out_dir: Path, reference: bytes) -> dict:
    stdout = (out_dir / f"{run['label']}.stdout").read_bytes()
    stderr = (out_dir / f"{run['label']}.stderr").read_bytes()
    correctness = v0c_correctness.reduce(stdout, PROMPT.encode(), reference)
    accounting = v1c_accounting.parse_accounting(
        stderr.decode("utf-8", "replace"), selector=run["argv"][run["argv"].index("--device") + 1])
    return {"correctness": correctness, "accounting": accounting}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True,
                        choices=["perturbation", "discrimination"])
    parser.add_argument("--runtime", required=True,
                        help="instrumented llama-cli path")
    parser.add_argument("--out-root", required=True)
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--reference",
                        default=str(Path(__file__).resolve().parents[1] / REFERENCE_DEFAULT))
    args = parser.parse_args()
    global RUNTIME_ACCEPTED
    RUNTIME_ACCEPTED = args.runtime
    out = Path(args.out_root)
    reference = Path(args.reference).read_bytes()

    runs: list[dict] = []

    if args.phase == "perturbation":
        for selector in ("Vulkan1", "Vulkan2"):
            for arm in ("disabled", "enabled"):
                for rep in range(1, 4):
                    label = f"{selector}-{arm}-{rep}"
                    env_extra = ({"GGML_VK_OBSERVE_INTERVAL":
                                  str(out / label / "observe.jsonl")}
                                 if arm == "enabled" else {})
                    (out / label).mkdir(parents=True, exist_ok=True)
                    run = run_one(execution_argv(selector), env_extra,
                                  out / label, label)
                    reduced = reduce_accepted(run, out / label, reference)
                    run["reduced"] = reduced
                    runs.append(run)
                    _durable_write(out / label / "run.json",
                                   (json.dumps(run, indent=2, sort_keys=True)
                                    + "\n").encode())
    else:
        # Phase 5: sequential control, then concurrent candidate.
        for schedule in ("sequential", "concurrent"):
            sched_dir = out / schedule
            sched_dir.mkdir(parents=True, exist_ok=True)
            if schedule == "sequential":
                for selector in ("Vulkan1", "Vulkan2"):
                    label = f"{schedule}-{selector}"
                    env_extra = {"GGML_VK_OBSERVE_INTERVAL":
                                 str(sched_dir / f"{label}.observe.jsonl")}
                    run = run_one(execution_argv(selector), env_extra,
                                  sched_dir, label)
                    reduced = reduce_accepted(run, sched_dir, reference)
                    run["reduced"] = reduced
                    runs.append(run)
                    _durable_write(sched_dir / f"{label}.run.json",
                                   (json.dumps(run, indent=2, sort_keys=True)
                                    + "\n").encode())
            else:
                procs = []
                metas = []
                for selector in ("Vulkan1", "Vulkan2"):
                    label = f"{schedule}-{selector}"
                    env = dict(os.environ)
                    env["GGML_VK_OBSERVE_INTERVAL"] = str(
                        sched_dir / f"{label}.observe.jsonl")
                    argv = execution_argv(selector)
                    t0 = time.monotonic()
                    procs.append((label, argv, env,
                                  subprocess.Popen(argv, stdout=subprocess.PIPE,
                                                   stderr=subprocess.PIPE,
                                                   env=env)))
                    metas.append({"label": label, "argv": argv,
                                  "started_utc": datetime.now(timezone.utc).isoformat(),
                                  "t0": t0})
                for (label, argv, env, proc), meta in zip(procs, metas):
                    so, se = proc.communicate(timeout=1800)
                    wall = round(time.monotonic() - meta.pop("t0"), 3)
                    _durable_write(sched_dir / f"{label}.stdout", so)
                    _durable_write(sched_dir / f"{label}.stderr", se)
                    _durable_write(sched_dir / f"{label}.exit-code",
                                   f"{proc.returncode}\n".encode())
                    run = {"label": label, **meta, "wall_seconds": wall,
                           "exit_code": proc.returncode,
                           "stdout_sha256": hashlib.sha256(so).hexdigest(),
                           "stderr_sha256": hashlib.sha256(se).hexdigest()}
                    selected = None
                    for line in se.decode("utf-8", "replace").splitlines():
                        m = re.search(r"using device.*?([0-9a-f]{2}:[0-9a-f]{2}\.[0-9])", line)
                        if m:
                            selected = m.group(1)
                            break
                    run["selected_bdf"] = selected
                    reduced = reduce_accepted(run, sched_dir, reference)
                    run["reduced"] = reduced
                    runs.append(run)
                    _durable_write(sched_dir / f"{label}.run.json",
                                   (json.dumps(run, indent=2, sort_keys=True)
                                    + "\n").encode())

    ledger = {"schema": SCHEMA,
              "phase": args.phase,
              "measured_utc": datetime.now(timezone.utc).isoformat(),
              "runs": [{k: v for k, v in r.items() if k != "reduced"} | 
                       {"reduced_summary": {
                           "byte_exact": r["reduced"]["correctness"]["byte_exact_visible_output"],
                           "accounting": {k: r["reduced"]["accounting"][k] for k in
                                          ("unexplained_persistent_host_mirror_bytes",
                                           "source_fetches_after_ready",
                                           "unplanned_state_movements")}}}
                       for r in runs]}
    _durable_write(out / f"LEDGER-{args.phase}.json",
                   (json.dumps(ledger, indent=2, sort_keys=True) + "\n").encode())
    ok = True
    for r in runs:
        c = r["reduced"]["correctness"]
        a = r["reduced"]["accounting"]
        clean = (c["byte_exact_visible_output"] and r["exit_code"] == 0
                 and a["unexplained_persistent_host_mirror_bytes"] == 0
                 and a["source_fetches_after_ready"] == 0
                 and a["unplanned_state_movements"] == 0)
        if not clean:
            ok = False
            print(f"NOT CLEAN: {r['label']}")
    print("ALL CLEAN" if ok else "FAILURES PRESENT")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
