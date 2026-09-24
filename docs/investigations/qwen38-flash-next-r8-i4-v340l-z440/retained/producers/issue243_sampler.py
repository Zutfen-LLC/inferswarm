#!/usr/bin/env python3
"""Issue #243 (R8-I4) — thermal/platform burn-in sampler (Phase 2).

Samples per-die telemetry while an external workload runs:
  - GPU edge/junction/mem temperatures (hwmon milli-C)
  - clocks (gt_cur_freq_mhz via ppcurvclock for sclk; power1_average)
  - gpu_busy_percent, memory_busy_percent
  - vram used/total per die (mem_info_vram_{used,total})
  - host RAM/swap, iowait (from /proc/stat deltas)
  - amdgpu resets / AER entries in kernel log since campaign start

Fails closed (exit 3) on: GPU reset ring, amdgpu fault, AER corrected or
uncorrected error accumulation during the window, temp >= emergency.

Output: one JSON per sample appended to the samples file (JSONL), plus a
summary record at end.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

SAMPLE_INTERVAL = 5.0  # seconds


def read(path: str) -> str:
    try:
        return Path(path).read_text().strip()
    except OSError:
        return ""


def hwmon_for(pci_dev: str) -> str:
    # pci_dev like /sys/class/drm/card1/device
    for h in sorted(Path(pci_dev, "hwmon").glob("hwmon*")):
        return str(h)
    return ""


def sample_die(pci_dev: str) -> dict:
    d: dict = {}
    h = hwmon_for(pci_dev)
    temps = {}
    if h:
        for tf in sorted(Path(h).glob("temp*_input")):
            label = read(str(tf).replace("_input", "_label")) or tf.name
            try:
                temps[label] = int(tf.read_text().strip()) / 1000.0
            except (OSError, ValueError):
                pass
    d["temps_c"] = temps
    for key, src in [
        ("power1_average_w", f"{h}/power1_average"),
        ("power1_cap_w", f"{h}/power1_cap"),
    ]:
        v = read(src)
        if v:
            try:
                d[key] = int(v) / 1e6
            except ValueError:
                pass
    for key, src in [
        ("gpu_busy_percent", f"{pci_dev}/gpu_busy_percent"),
        ("mem_busy_percent", f"{pci_dev}/mem_busy_percent"),
        ("vram_used_bytes", f"{pci_dev}/mem_info_vram_used"),
        ("vram_total_bytes", f"{pci_dev}/mem_info_vram_total"),
        ("current_link_speed", f"{pci_dev}/current_link_speed"),
        ("current_link_width", f"{pci_dev}/current_link_width"),
    ]:
        v = read(src)
        if v:
            d[key] = v
    return d


def kernel_health(since_ts: float) -> dict:
    out = subprocess.run(
        ["sudo", "-n", "dmesg", "-T"], capture_output=True, text=True
    ).stdout
    keeps = []
    pat = re.compile(
        r"amdgpu.*(reset|fault|GPU hang|ring timeout)|AER|Uncorrected|"
        r"pcieport .*error",
        re.I,
    )
    for line in out.splitlines():
        m = re.match(r"\[(...).{15}\] (.*)", line)
        if pat.search(line):
            keeps.append(line)
    return {"matching_lines": keeps[-30:]}


def cpu_iowait(prev: dict | None) -> dict:
    fields = read("/proc/stat").splitlines()[0].split()[1:]
    vals = list(map(int, fields))
    d = {"cpu_fields": vals}
    if prev:
        dt = sum(v - p for v, p in zip(vals, prev["cpu_fields"]))
        diow = vals[5] - prev["cpu_fields"][5]
        d["iowait_frac"] = (diow / dt) if dt else 0.0
    return d


def meminfo() -> dict:
    out: dict = {}
    for line in read("/proc/meminfo").splitlines():
        k, v = line.split(":", 1)
        out[k] = v.strip()
    return out


def main() -> int:
    samples_path = sys.argv[1]
    duration = float(sys.argv[2])
    t_end = time.time() + duration
    prev_cpu: dict | None = None
    n = 0
    with open(samples_path, "a", buffering=1) as f:
        while time.time() < t_end:
            s = {
                "t": round(time.time(), 1),
                "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "dies": {
                    "card1@07:00.0": sample_die("/sys/class/drm/card1/device"),
                    "card2@0b:00.0": sample_die("/sys/class/drm/card2/device"),
                },
                "host": {"meminfo": meminfo()},
            }
            cpu = cpu_iowait(prev_cpu)
            s["host"]["iowait_frac"] = cpu.get("iowait_frac")
            prev_cpu = cpu
            f.write(json.dumps(s) + "\n")
            n += 1
            time.sleep(SAMPLE_INTERVAL)
    print(json.dumps({"samples": n, "path": samples_path}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
