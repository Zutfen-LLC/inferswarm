#!/usr/bin/env python3
"""Capture one V0-A correction correctness run as a complete raw record.

Executes the already-frozen greedy fixture on one pinned (physical GPU,
backend) arm and retains a full raw evidence record: exact argv, hashes,
enumeration banner, selected-device proof, offload proof, stdout/stderr
verbatim, exit code, canonicalized generation digest, and warning status.

This producer implements docs/investigations/vulkan-v0-a/
METHODOLOGY-CORRECTION.md. It must never be edited after that freeze
without a new correction document.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HOST = "inferswarm02"
MODELS = Path("/home/hermes/v0a/models")
BUILD_VULKAN = Path("/home/hermes/v0a/llama.cpp/build-vulkan/bin")
BUILD_CUDA = Path("/home/hermes/v0a/llama.cpp/build-cuda/bin")

PROMPT = (
    "The quick brown fox jumps over the lazy dog. "
    "Explain what happens next in one sentence:"
)

# Frozen identity (METHODOLOGY-CORRECTION.md); verified before every run.
MODEL_SHA256 = (
    "9c9f56a391a3abbd5b89d0245bf6106081bcc3173119d4229235dd9d23253f94"
)
EXPECTED_SHA256 = {
    str(BUILD_VULKAN / "llama-cli"):
        "c4bcd6a94e0b7fdb1959e6542ce0f85bb905c6c9083fcd1a7b6b0daf15e2c9be",
    str(BUILD_CUDA / "llama-cli"):
        "066d371207569e431cabe95191b38dc41683b722fdb6c2b6b41008d0b4ebda1e",
}

# physical BDF per Vulkan enumeration index, cross-checked against
# inventory/phase0-baseline.txt and inventory/04-link-caps...:
# 0 = Intel iGPU 00:02.0, 1 = AMD-A 02:00.0, 2 = AMD-B 03:00.0,
# 3 = NV-A 04:00.0.
ARMS = {
    "amd-a-vulkan": {
        "build": "build-vulkan", "device": "Vulkan1", "bdf": "02:00.0",
        "gpu_label": "AMD-A",
    },
    "amd-b-vulkan": {
        "build": "build-vulkan", "device": "Vulkan2", "bdf": "03:00.0",
        "gpu_label": "AMD-B",
    },
    "nvidia-vulkan": {
        "build": "build-vulkan", "device": "Vulkan3", "bdf": "04:00.0",
        "gpu_label": "NV-A",
    },
    "nvidia-cuda": {
        "build": "build-cuda", "device": "CUDA0", "bdf": "04:00.0",
        "gpu_label": "NV-A",
    },
}

# Strings that must appear in the run's stderr to prove the intended
# device/backend executed (device-identity proof chain).
VULKAN_DEVICE_PROOF = {
    "Vulkan1": "1 = AMD Radeon RX 580 Series (RADV POLARIS10)",
    "Vulkan2": "2 = AMD Radeon RX 580 Series (RADV POLARIS10)",
    "Vulkan3": "3 = NVIDIA GeForce RTX 3060 Ti",
}
CUDA_DEVICE_PROOF = "CUDA0 = NVIDIA GeForce RTX 3060 Ti"

WARN_PATTERNS = (
    "failed", "error", "fallback", "nan", "inf", "unsupported",
    "device loss", "shader compile", "warning",
)
FATAL_PATTERNS = (
    "llama_context: failed", "ggml_backend_alloc: failed",
    "device loss", "shader compile failed", "CUDA error",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonicalize_generation(stdout: str) -> str:
    """Strip spinner/control characters; keep the printable generation."""
    text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", stdout)
    text = re.sub(r".\b", "", text, flags=re.S) if "\b" in text else text
    return "".join(
        ch for ch in text if ch.isprintable() or ch in "\n\r\t"
    ).strip()


def classify_issues(stderr: str, stdout: str) -> tuple[list[str], list[str]]:
    warnings, failures = [], []
    lowered = (stderr + stdout).lower()
    for pattern in WARN_PATTERNS:
        for line in (stderr + stdout).splitlines():
            if pattern in line.lower() and (
                    line.lower().startswith(("llama_", "ggml_", "srv ", "warning"))):
                if any(f in line.lower() for f in FATAL_PATTERNS):
                    failures.append(line.strip())
                else:
                    warnings.append(line.strip())
    if "nan" in lowered or "infinity" in lowered:
        failures.append("NaN/Inf token observed")
    return sorted(set(warnings)), sorted(set(failures))


def run_fixture(arm: str, run_id: str, out_dir: Path) -> dict:
    spec = ARMS[arm]
    build = BUILD_VULKAN if spec["build"] == "build-vulkan" else BUILD_CUDA
    binary = build / "llama-cli"
    model = MODELS / "Qwen2.5-3B-Instruct-Q4_K_M.gguf"

    assert sha256(binary) == EXPECTED_SHA256[str(binary)], \
        f"probe identity drift: {binary}"
    assert sha256(model) == MODEL_SHA256, "model identity drift"

    argv = [
        str(binary), "-m", str(model), "--temp", "0", "--seed", "42",
        "-n", "48", "-ngl", "99", "--device", spec["device"],
        "-no-cnv", "-p", PROMPT, "-st",
    ]
    env = dict(os.environ)
    relevant_env = {
        k: env[k] for k in sorted(env)
        if k.startswith(("GGML_", "HIP_", "CUDA_VISIBLE", "LD_LIBRARY_PATH"))
        and env[k]
    }

    started = datetime.now(timezone.utc)
    t0 = time.monotonic()
    completed = subprocess.run(
        argv, capture_output=True, text=True, timeout=1200, env=env)
    wall_s = time.monotonic() - t0
    finished = datetime.now(timezone.utc)

    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    warnings, failures = classify_issues(stderr, stdout)

    enumeration = [ln for ln in stderr.splitlines()
                   if ln.startswith(("ggml_vulkan:", "ggml_cuda:",
                                     "llama_model:", "load_tensors:"))]
    device_proof_lines = [ln for ln in stderr.splitlines()
                          if "offloaded" in ln or "layers to GPU" in ln
                          or ln.startswith("ggml_vulkan:")
                          or ln.startswith("ggml_cuda:")]
    proof_token = (VULKAN_DEVICE_PROOF.get(spec["device"])
                   if spec["device"].startswith("Vulkan")
                   else CUDA_DEVICE_PROOF)
    device_proven = proof_token in stderr
    generation = canonicalize_generation(stdout)
    generation_digest = hashlib.sha256(generation.encode()).hexdigest()

    record = {
        "schema": "inferswarm.vulkan-v0-a.correctness-correction-run/1",
        "correction_authority": "METHODOLOGY-CORRECTION.md",
        "run_id": run_id,
        "host": HOST,
        "arm": arm,
        "timestamp_utc_start": started.isoformat(),
        "timestamp_utc_end": finished.isoformat(),
        "wall_seconds": round(wall_s, 3),
        "argv": argv,
        "relevant_environment": relevant_env,
        "executable": {
            "path": str(binary), "sha256": EXPECTED_SHA256[str(binary)],
        },
        "model": {
            "path": str(model), "sha256": MODEL_SHA256,
            "bytes": model.stat().st_size,
        },
        "intended": {
            "physical_bdf": spec["bdf"], "gpu_label": spec["gpu_label"],
            "device_selector": spec["device"], "backend": spec["build"],
        },
        "exit_code": completed.returncode,
        "stdout_verbatim": stdout,
        "stderr_verbatim": stderr,
        "backend_device_enumeration": enumeration,
        "selected_device_proof_lines": device_proof_lines,
        "intended_device_proven": device_proven,
        "offload_proof_lines": [ln for ln in stderr.splitlines()
                                if "offloaded" in ln],
        "generation_canonicalized": generation,
        "generation_canonicalized_sha256": generation_digest,
        "warnings": warnings,
        "failures": failures,
        "nan_inf_observed": bool(failures and "NaN/Inf" in failures[0]),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "run.json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8")
    (out_dir / "stdout.txt").write_text(stdout, encoding="utf-8")
    (out_dir / "stderr.txt").write_text(stderr, encoding="utf-8")
    return record


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: v0a_correctness_run.py <arm> <run_id> <out_dir>",
              file=sys.stderr)
        return 2
    arm, run_id, out_dir = argv
    if arm not in ARMS:
        print(f"unknown arm {arm}; expected one of {sorted(ARMS)}",
              file=sys.stderr)
        return 2
    record = run_fixture(arm, run_id, Path(out_dir))
    status = "OK" if (record["exit_code"] == 0
                      and record["intended_device_proven"]
                      and not record["failures"]) else "FAILED"
    print(f"{run_id} {arm} {status} "
          f"digest={record['generation_canonicalized_sha256']}")
    return 0 if status == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
