#!/usr/bin/env python3
"""Issue #219 — V2-D0 Phase 1 exact-stack capability collector.

Runs DIRECTLY on inferswarm02. Retains the exact Vulkan capability
facts the selected seam depends on, from the exact stack (loader/ICD/
driver/runtime binaries the accepted campaigns froze):

  * exact loader/ICD/driver identity (vulkaninfo raw bytes retained);
  * per-V340L-die: device identity, queue families with
    timestampValidBits + queue flags, limits.timestampComputeAndGraphics,
    limits.timestampPeriod, calibrated-timestamps extension revision,
    calibrateable time domains (raw probe output);
  * a live calibrated-timestamp probe through a minimal Vulkan program
    is NOT constructed here (the seam's own device-creation proof is
    the live probe); this collector pins the PHYSICAL capability
    surface only, and the live proof is retained per-run by the
    instrumented runtime itself.

Usage (on inferswarm02):
  python3 issue219_capability_probe.py --out-root <dir>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "inferswarm.v2d0.capability-probe/1"


def _durable_write(path: Path, data: bytes) -> None:
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


def _run(argv: list[str]) -> dict:
    p = subprocess.run(argv, capture_output=True, text=False, timeout=300)
    return {"argv": argv, "rc": p.returncode,
            "stdout": p.stdout, "stderr": p.stderr}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-root", required=True)
    args = parser.parse_args()
    out = Path(args.out_root)
    raw = out / "raw"
    raw.mkdir(parents=True, exist_ok=True)

    probes: dict[str, dict] = {}
    probes["vulkaninfo_summary"] = _run(["vulkaninfo", "--summary"])
    probes["vulkaninfo_full"] = _run(["vulkaninfo"])
    probes["loader_version"] = _run(["dpkg-query", "-W", "-f=${Version}\\n",
                                     "libvulkan1"])
    probes["mesa_version"] = _run(["dpkg-query", "-W", "-f=${Version}\\n",
                                   "libvulkan-dev"])
    probes["radv_icd"] = _run(["cat",
                               "/usr/share/vulkan/icd.d/radeon_icd.x86_64.json"])
    probes["uname"] = _run(["uname", "-a"])
    probes["cmdline"] = _run(["cat", "/proc/cmdline"])
    probes["boot_id"] = _run(["cat", "/proc/sys/kernel/random/boot_id"])
    probes["lspci_nn"] = _run(["lspci", "-nn"])
    probes["runtime_pristine_sha"] = _run(
        ["sha256sum",
         "/home/zutfen/.cache/v0c-llama.cpp/build-v0c-vulkan/bin/llama-cli"])
    probes["model_sha"] = _run(
        ["sha256sum",
         "/home/zutfen/.cache/v0c-models/Qwen2.5-3B-Instruct-Q4_K_M.gguf"])

    for name, probe in probes.items():
        _durable_write(raw / f"{name}.stdout", probe["stdout"])
        _durable_write(raw / f"{name}.stderr", probe["stderr"])
        _durable_write(raw / f"{name}.meta.json", json.dumps(
            {"argv": probe["argv"], "rc": probe["rc"],
             "stdout_sha256": hashlib.sha256(probe["stdout"]).hexdigest(),
             "stdout_bytes": len(probe["stdout"]),
             "stderr_bytes": len(probe["stderr"])}, indent=2).encode())

    # Derived: per-die timestamp capability facts, parsed from the FULL
    # retained vulkaninfo (fail-closed parse).
    text = probes["vulkaninfo_full"]["stdout"].decode("utf-8", "replace")
    dies = []
    blocks = text.split("GPU")
    for block in blocks[1:]:
        name_m = None
        for line in block.splitlines():
            if "deviceName" in line and "=" in line:
                name_m = line.split("=", 1)[1].strip()
                break
        if not name_m or "V340" not in name_m:
            continue
        period = None
        tcg = None
        valid_bits = []
        for line in block.splitlines():
            if "timestampPeriod" in line and "=" in line:
                period = line.split("=", 1)[1].strip()
            if "timestampComputeAndGraphics" in line and "=" in line:
                tcg = line.split("=", 1)[1].strip()
            if "timestampValidBits" in line and "=" in line:
                valid_bits.append(line.split("=", 1)[1].strip())
        has_calibrated = "VK_EXT_calibrated_timestamps" in block
        dies.append({"device_name": name_m,
                     "timestamp_period_ns": period,
                     "timestamp_compute_and_graphics": tcg,
                     "timestamp_valid_bits_queue_families": valid_bits,
                     "vk_ext_calibrated_timestamps": has_calibrated})
    if len(dies) != 2:
        raise SystemExit(f"expected exactly 2 V340L dies in vulkaninfo, saw {len(dies)}")
    for die in dies:
        if die["timestamp_compute_and_graphics"] != "true":
            raise SystemExit(f"die {die['device_name']} lacks timestampComputeAndGraphics")
        if not die["vk_ext_calibrated_timestamps"]:
            raise SystemExit(f"die {die['device_name']} lacks calibrated timestamps ext")
        if len(die["timestamp_valid_bits_queue_families"]) < 1:
            raise SystemExit(f"die {die['device_name']} no queue family timestampValidBits")

    record = {
        "schema": SCHEMA,
        "measured_utc": datetime.now(timezone.utc).isoformat(),
        "hostname": probes["uname"]["stdout"].decode().split()[1],
        "dies": dies,
        "raw_probes": sorted(probes),
    }
    _durable_write(out / "CAPABILITY.json",
                   (json.dumps(record, indent=2, sort_keys=True) + "\n").encode())
    print(json.dumps(record["dies"], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
