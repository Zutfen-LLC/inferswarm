#!/usr/bin/env python3
"""V0-B supplemental matched CPU baseline runner (bounded, frozen).

Executes the ONE physical collection authorized by
docs/investigations/vulkan-v0-b/METHODOLOGY.md: the supplemental matched
CPU baseline on inferswarm02 (issue #142 Phase 2 accelerator-vs-host
question for the AMD Vulkan path, which has no native comparator).

Fail-closed preconditions (verified before the first run, recorded in
every run.json):
  - probe binaries byte-identical to the frozen V0-A build-vulkan
    identities;
  - model byte-identical to the frozen V0-A subject;
  - METHODOLOGY.md present in the bundle (freeze authority).

Per-run backend-selection proof: the CURRENT rule is
METHODOLOGY-CORRECTION-3.md — layers-executed-on-host-CPU, mechanically
derived from the run's own retained stderr by the shared implementation
in scripts/v0b_cpu_proof.py (exact zero GPU-layer offload; every
per-layer assignment line bound to CPU; CPU-mapped model buffer; CPU KV
buffer; CPU output buffer; clean exit). GPU device-preparation lines
(e.g. `llama_prepare_model_devices: using device Vulkan0 ...`) are
retained and dispositioned as ICD-enumeration context, not as proof and
not as a violation. Any proof violation discards the run (exit nonzero)
rather than reinterpreting it.

History (declared provenance, METHODOLOGY-CORRECTION-3.md): the
superseded original-rule and correction-1-rule bring-up runs were
discarded at collection time and their bytes were later OVERWRITTEN when
this runner re-used its sequential run IDs — they are NOT retained. This
is a provenance defect of the bundle, not retained evidence.

This is a NEW producer (successor under the frozen-producer rule); it
does not modify any pinned V0-A script.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from v0b_cpu_proof import PROOF_SPEC, proof_from_stderr  # noqa: E402

BUNDLE = REPO / "docs/investigations/vulkan-v0-b"
OUT_DIR = BUNDLE / "results" / "cpu-supplemental"

PROBE_DIR = Path("/home/hermes/v0a/llama.cpp/build-vulkan/bin")
MODEL_PATH = Path("/home/hermes/v0a/models/Qwen2.5-3B-Instruct-Q4_K_M.gguf")
V0A = REPO / "docs/investigations/vulkan-v0-a"

FROZEN = {
    "llama-bench": "f78e6786c7fbdeff3f89c97c02df078cfbc297b886fd3f8010a639720b66914c",
    "llama-cli": "c4bcd6a94e0b7fdb1959e6542ce0f85bb905c6c9083fcd1a7b6b0daf15e2c9be",
}
MODEL_SHA = "9c9f56a391a3abbd5b89d0245bf6106081bcc3173119d4229235dd9d23253f94"
MODEL_BYTES = 1_929_903_264
RUNS = 3
THREADS = 2
EXPECTED_LAYERS = 37


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def preflight() -> None:
    if os.uname().nodename != "inferswarm02":
        sys.exit(f"refusing to run off the frozen host: {os.uname().nodename}")
    if not (BUNDLE / "METHODOLOGY.md").exists():
        sys.exit("freeze authority missing: bundle METHODOLOGY.md not found")
    for name, want in FROZEN.items():
        got = sha256(PROBE_DIR / name)
        if got != want:
            sys.exit(f"probe identity drift: {name} {got} != {want}")
    msha, mbytes = sha256(MODEL_PATH), MODEL_PATH.stat().st_size
    if msha != MODEL_SHA or mbytes != MODEL_BYTES:
        sys.exit(f"model identity drift: {msha} {mbytes}")


def one_run(idx: int) -> int:
    run_id = f"v0b-cpu-{idx:02d}"
    run_dir = OUT_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    argv = [
        str(PROBE_DIR / "llama-bench"),
        "-m", str(MODEL_PATH),
        "-ngl", "0",
        "-fa", "0",
        "-p", "512",
        "-n", "128",
        "-r", "5",
        "-t", str(THREADS),
        "-v",
    ]
    started = dt.datetime.now(dt.timezone.utc)
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=3600)
    ended = dt.datetime.now(dt.timezone.utc)

    (run_dir / "stdout.txt").write_text(proc.stdout)
    (run_dir / "stderr.txt").write_text(proc.stderr)

    # Layers-executed-on-host-CPU proof per METHODOLOGY-CORRECTION-3.md,
    # shared with the deriver so collection and reduction cannot drift.
    proof = proof_from_stderr(proc.stderr, expected_layers=EXPECTED_LAYERS)
    proved = bool(proof["proved"] and proc.returncode == 0)

    record = {
        "schema": "inferswarm.vulkan-v0-b.cpu-supplemental-run/2",
        "run_id": run_id,
        "host": os.uname().nodename,
        "timestamp_utc_start": started.isoformat(),
        "timestamp_utc_end": ended.isoformat(),
        "argv": argv,
        "methodology_freeze_authority": "docs/investigations/vulkan-v0-b/METHODOLOGY.md",
        "proof_rule_authority": (
            "docs/investigations/vulkan-v0-b/METHODOLOGY-CORRECTION-3.md"),
        "proof_spec": PROOF_SPEC,
        "executable": {"path": str(PROBE_DIR / "llama-bench"),
                       "sha256": FROZEN["llama-bench"]},
        "model": {"path": str(MODEL_PATH), "sha256": MODEL_SHA,
                  "bytes": MODEL_BYTES},
        "intended": {"backend": "CPU", "device_selector": None,
                     "gpu_label": None, "physical_bdf": None,
                     "note": ("host-memory execution arm; model layers "
                              "must execute on host CPU")},
        "threads": THREADS,
        "exit_code": proc.returncode,
        "backend_selection_proven": proved,
        "proof_details": proof,
        "stdout_bytes": len(proc.stdout),
        "stderr_bytes": len(proc.stderr),
    }
    (run_dir / "run.json").write_text(json.dumps(record, indent=1) + "\n")

    if not proved:
        print(json.dumps({"run": run_id, "status": "DISCARDED",
                          "backend_selection_proven": proved,
                          "exit_code": proc.returncode}))
        return 1
    print(json.dumps({"run": run_id, "status": "collected",
                      "offload_zero_proven": proof["offload_zero_proven"],
                      "layers_all_cpu": proof["layers_all_cpu"]}))
    return 0


def main() -> int:
    preflight()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rc = 0
    for i in range(1, RUNS + 1):
        if one_run(i) != 0:
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
