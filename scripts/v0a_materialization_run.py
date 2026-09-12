#!/usr/bin/env python3
"""Corrected V0-A materialization harness (zero model inference).

Implements docs/investigations/vulkan-v0-a/METHODOLOGY-CORRECTION.md:
launch the pinned llama-cli on the pinned model/device, wait for the
mechanically detectable interactive-ready boundary WITHOUT submitting any
model prompt or generating any token, sample memory at pre-launch /
ready / predeclared idle-hold boundaries with explicit event markers,
then send only the CLI exit command ("/exit") and retain the raw
transcript, memory streams, and exit status.

The ready boundary is the interactive prompt ("> ") that llama-cli
prints after the model is fully loaded. No prompt text is ever written
to the process stdin except the exit command, so zero model prompt
evaluation and zero generated-token work occur; the retained transcript
is the zero-inference proof (it must contain no evaluation/timing
markers and no generated text).
"""
from __future__ import annotations

import hashlib
import json
import os
import pty
import re
import select
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HOST = "inferswarm02"
BUILD_VULKAN = Path("/home/hermes/v0a/llama.cpp/build-vulkan/bin")
BUILD_CUDA = Path("/home/hermes/v0a/llama.cpp/build-cuda/bin")
MODEL = Path("/home/hermes/v0a/models/Qwen2.5-3B-Instruct-Q4_K_M.gguf")
MODEL_SHA256 = (
    "9c9f56a391a3abbd5b89d0245bf6106081bcc3173119d4229235dd9d23253f94"
)
CLI_SHA256 = {
    str(BUILD_VULKAN / "llama-cli"):
        "c4bcd6a94e0b7fdb1959e6542ce0f85bb905c6c9083fcd1a7b6b0daf15e2c9be",
    str(BUILD_CUDA / "llama-cli"):
        "066d371207569e431cabe95191b38dc41683b722fdb6c2b6b41008d0b4ebda1e",
}

ARMS = {
    "amd-a-vulkan": {
        "build": "build-vulkan", "device": "Vulkan1", "bdf": "02:00.0",
        "vram_sysfs": "/sys/class/drm/card1/device/mem_info_vram_used",
    },
    "nvidia-vulkan": {
        "build": "build-vulkan", "device": "Vulkan3", "bdf": "04:00.0",
        "vram_sysfs": None,
    },
    "nvidia-cuda": {
        "build": "build-cuda", "device": "CUDA0", "bdf": "04:00.0",
        "vram_sysfs": None,
    },
}

READY_TIMEOUT_S = 300
IDLE_HOLD_S = 5.0
SAMPLE_INTERVAL_S = 0.5

READY_MARKER = "/glob <pattern>     add text files using globbing pattern"
READY_PROMPT = ">"
EVAL_MARKERS = (
    "prompt processing time", "eval time", "prompt evaluation",
    "timings per token",
)

INFERENCE_MARKERS = (
    "prompt processing time", "eval time", "generation output",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def gpu_vram_used_bytes(spec: dict) -> int | None:
    if spec["vram_sysfs"]:
        try:
            return int(Path(spec["vram_sysfs"]).read_text().strip())
        except OSError:
            return None
    out = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used",
         "--format=csv,noheader,nounits", "-i", "0"],
        capture_output=True, text=True, timeout=15)
    if out.returncode != 0:
        return None
    return int(out.stdout.strip()) * 1024 * 1024


def proc_status(pid: int) -> dict:
    try:
        status = Path(f"/proc/{pid}/status").read_text()
    except OSError:
        return {}
    fields = {}
    for line in status.splitlines():
        if line.startswith(("VmRSS:", "VmHWM:", "VmSize:")):
            key, value = line.split(":", 1)
            fields[key] = int(value.strip().split()[0])
    return fields


def run_once(arm: str, run_id: str, out_dir: Path,
             idle_hold_s: float = IDLE_HOLD_S) -> dict:
    spec = ARMS[arm]
    binary = (BUILD_VULKAN if spec["build"] == "build-vulkan"
              else BUILD_CUDA) / "llama-cli"
    assert sha256(binary) == CLI_SHA256[str(binary)], "probe identity drift"
    assert sha256(MODEL) == MODEL_SHA256, "model identity drift"

    argv = [
        str(binary), "-m", str(MODEL), "-ngl", "99",
        "--device", spec["device"], "-lv", "4",
    ]
    out_dir.mkdir(parents=True, exist_ok=True)

    baseline = {
        "gpu_vram_used_bytes": gpu_vram_used_bytes(spec),
        "proc": {},
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }

    pid, fd = pty.fork()
    if pid == 0:  # child: exec the probe on the pty
        os.execv(argv[0], argv)

    transcript = bytearray()
    samples = [{
        "t_rel_s": 0.0, "event": "pre_launch_baseline",
        "gpu_vram_used_bytes": baseline["gpu_vram_used_bytes"],
        "proc": {},
    }]
    started = time.monotonic()
    ready_t = None
    ready_sample = None
    hold_samples = []
    timed_out = False
    last_sample = started

    def sample(event: str | None = None) -> dict:
        nonlocal last_sample
        now = time.monotonic()
        last_sample = now
        entry = {
            "t_rel_s": round(now - started, 3),
            "event": event,
            "gpu_vram_used_bytes": gpu_vram_used_bytes(spec),
            "proc": proc_status(pid),
        }
        samples.append(entry)
        return entry

    while True:
        timeout = SAMPLE_INTERVAL_S - (time.monotonic() - last_sample)
        readable, _, _ = select.select([fd], [], [], max(timeout, 0.01))
        if readable:
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                chunk = b""
            if not chunk:
                break
            transcript.extend(chunk)
        if ready_t is None:
            text = transcript.decode("utf-8", errors="replace")
            stripped = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)
            if (READY_MARKER in stripped
                    and stripped.rstrip().endswith(READY_PROMPT)):
                entry = sample("ready_boundary")
                ready_t = time.monotonic()
                ready_sample = entry
        else:
            if time.monotonic() - ready_t >= idle_hold_s:
                sample("idle_hold_end")
                break
            if time.monotonic() - last_sample >= SAMPLE_INTERVAL_S:
                hold_samples.append(sample("idle_hold"))
        if time.monotonic() - started > READY_TIMEOUT_S and ready_t is None:
            timed_out = True
            break

    if ready_t is not None and not timed_out:
        os.write(fd, b"/exit\r")
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            readable, _, _ = select.select([fd], [], [], 1.0)
            if readable:
                try:
                    chunk = os.read(fd, 65536)
                except OSError:
                    chunk = b""
                if not chunk:
                    break
                transcript.extend(chunk)
            else:
                break
    try:
        _, exit_status = os.waitpid(pid, os.WNOHANG)
        if os.WIFEXITED(exit_status) or os.WIFSIGNALED(exit_status):
            exited = True
        else:
            exited = False
    except ChildProcessError:
        exited, exit_status = True, -1
    if not exited:
        _, exit_status = os.waitpid(pid, 0)
    exit_code = (os.WEXITSTATUS(exit_status)
                 if os.WIFEXITED(exit_status) else -1)
    ended = datetime.now(timezone.utc)

    text = transcript.decode("utf-8", errors="replace")
    evaluation_markers = [m for m in EVAL_MARKERS if m in text]
    zero_inference_proven = (
        ready_t is not None and not timed_out and not evaluation_markers)
    ready_iso = (datetime.now(timezone.utc).isoformat()
                 if ready_t is not None else None)

    record = {
        "schema": "inferswarm.vulkan-v0-a.materialization-correction-run/1",
        "correction_authority": "METHODOLOGY-CORRECTION.md",
        "run_id": run_id,
        "host": HOST,
        "arm": arm,
        "argv": argv,
        "timestamp_utc_start": baseline["timestamp_utc"],
        "timestamp_utc_end": ended.isoformat(),
        "ready_boundary_timestamp_utc": ready_iso,
        "startup_to_ready_s": (
            round(ready_t - started, 3) if ready_t is not None else None),
        "idle_hold_s": idle_hold_s,
        "executable": {
            "path": str(binary), "sha256": CLI_SHA256[str(binary)],
        },
        "model": {"path": str(MODEL), "sha256": MODEL_SHA256},
        "intended": {
            "physical_bdf": spec["bdf"],
            "device_selector": spec["device"],
            "backend": spec["build"],
        },
        "memory": {
            "pre_launch": baseline,
            "ready_boundary": ready_sample,
            "idle_hold_samples": hold_samples,
            "idle_hold_end": samples[-1] if samples else None,
        },
        "memory_samples_all": samples,
        "zero_inference_proven": zero_inference_proven,
        "evaluation_markers_found": evaluation_markers,
        "ready_boundary_detected": ready_t is not None,
        "timed_out": timed_out,
        "exit_code": exit_code,
    }
    (out_dir / "run.json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8")
    (out_dir / "transcript.txt").write_text(text, encoding="utf-8")
    status = ("OK" if zero_inference_proven and exit_code == 0
              else "FAILED")
    print(f"{run_id} {arm} {status} "
          f"ready_s={record['startup_to_ready_s']}")
    return record


def main(argv_list: list[str]) -> int:
    if len(argv_list) < 3:
        print("usage: v0a_materialization_run.py <arm> <run_id> <out_dir> "
              "[idle_hold_s]", file=sys.stderr)
        return 2
    arm = argv_list[0]
    if arm not in ARMS:
        print(f"unknown arm {arm}", file=sys.stderr)
        return 2
    idle = float(argv_list[3]) if len(argv_list) > 3 else IDLE_HOLD_S
    record = run_once(arm, argv_list[1], Path(argv_list[2]), idle)
    ok = record["zero_inference_proven"] and record["exit_code"] == 0
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
