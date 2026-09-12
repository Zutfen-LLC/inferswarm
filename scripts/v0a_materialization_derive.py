#!/usr/bin/env python3
"""Derive corrected V0-A materialization/memory distributions.

Reads every results-correction/materialization/<arm>-<n>/run.json,
validates zero-inference proof and clean exits, and mechanically derives
per-arm distributions (medians) for startup/time-to-ready, peak and
ready-state GPU memory, persistent device memory at idle hold, peak host
RSS, ready-state host RSS, persistent host RSS at idle hold, and
Vulkan/CUDA deltas on NV-A. Writes
results-correction/materialization-correction.json.

No hand-edited values; nothing overwrites the preliminary mat2-* files.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1] / \
    "docs/investigations/vulkan-v0-a"
MAT_DIR = BUNDLE / "results-correction" / "materialization"
OUT = BUNDLE / "results-correction" / "materialization-correction.json"

EXPECTED_ARMS = ("amd-a-vulkan", "nvidia-vulkan", "nvidia-cuda")
MIN_RUNS = 3


def kb(x):
    return None if x is None else x  # Vm* fields are kB


def derive_arm(records: list[dict]) -> dict:
    ready_s = [r["startup_to_ready_s"] for r in records
               if r["startup_to_ready_s"] is not None]
    peaks_vram, ready_vram, idle_vram = [], [], []
    peaks_rss, ready_rss, idle_rss = [], [], []
    for r in records:
        if not r["zero_inference_proven"]:
            continue
        mem = r["memory"]
        vram_series = [s["gpu_vram_used_bytes"] for s in r["memory_samples_all"]
                       if s["gpu_vram_used_bytes"] is not None]
        if vram_series and mem["pre_launch"]["gpu_vram_used_bytes"] is not None:
            peaks_vram.append(max(vram_series))
        if mem["ready_boundary"] and mem["ready_boundary"][
                "gpu_vram_used_bytes"] is not None:
            ready_vram.append(mem["ready_boundary"]["gpu_vram_used_bytes"])
        if mem["idle_hold_end"] and mem["idle_hold_end"][
                "gpu_vram_used_bytes"] is not None:
            idle_vram.append(mem["idle_hold_end"]["gpu_vram_used_bytes"])
        rss_series = [s["proc"].get("VmRSS") for s in r["memory_samples_all"]
                      if s["proc"].get("VmRSS") is not None]
        if rss_series:
            peaks_rss.append(max(rss_series))
        if mem["ready_boundary"] and mem["ready_boundary"]["proc"].get("VmRSS"):
            ready_rss.append(mem["ready_boundary"]["proc"]["VmRSS"])
        if mem["idle_hold_end"] and mem["idle_hold_end"]["proc"].get("VmRSS"):
            idle_rss.append(mem["idle_hold_end"]["proc"]["VmRSS"])

    return {
        "runs": len(records),
        "run_ids": sorted(r["run_id"] for r in records),
        "all_zero_inference_proven": all(
            r["zero_inference_proven"] for r in records),
        "all_exit_clean": all(r["exit_code"] == 0 for r in records),
        "startup_to_ready_s_median": (
            round(statistics.median(ready_s), 3) if ready_s else None),
        "startup_to_ready_s_all": ready_s,
        "gpu_vram_peak_bytes_median": (
            round(statistics.median(peaks_vram)) if peaks_vram else None),
        "gpu_vram_ready_bytes_median": (
            round(statistics.median(ready_vram)) if ready_vram else None),
        "gpu_vram_idle_hold_bytes_median": (
            round(statistics.median(idle_vram)) if idle_vram else None),
        "host_rss_peak_kB_median": (
            round(statistics.median(peaks_rss)) if peaks_rss else None),
        "host_rss_ready_kB_median": (
            round(statistics.median(ready_rss)) if ready_rss else None),
        "host_rss_idle_hold_kB_median": (
            round(statistics.median(idle_rss)) if idle_rss else None),
    }


def main() -> int:
    arms = {}
    for arm in EXPECTED_ARMS:
        records = []
        for run_dir in sorted(MAT_DIR.glob(f"{arm}-*/run.json")):
            records.append(json.loads(run_dir.read_text(encoding="utf-8")))
        if records:
            arms[arm] = derive_arm(records)

    nv_vk = arms.get("nvidia-vulkan", {})
    nv_cuda = arms.get("nvidia-cuda", {})
    deltas = {}
    for field in ("startup_to_ready_s_median",
                  "gpu_vram_peak_bytes_median",
                  "gpu_vram_ready_bytes_median",
                  "gpu_vram_idle_hold_bytes_median",
                  "host_rss_peak_kB_median",
                  "host_rss_ready_kB_median",
                  "host_rss_idle_hold_kB_median"):
        v, c = nv_vk.get(field), nv_cuda.get(field)
        if v is not None and c is not None:
            deltas[field] = {"vulkan_minus_cuda": round(v - c, 3)}

    sufficient = all(
        arms.get(a, {}).get("runs", 0) >= MIN_RUNS
        and arms[a]["all_zero_inference_proven"]
        and arms[a]["all_exit_clean"]
        for a in EXPECTED_ARMS if a in arms) and len(arms) == 3

    summary = {
        "schema":
            "inferswarm.vulkan-v0-a.materialization-correction-summary/1",
        "derived_from": "results-correction/materialization/*/run.json",
        "derivation": "mechanical (scripts/v0a_materialization_derive.py)",
        "correction_authority": "METHODOLOGY-CORRECTION.md",
        "preliminary_disposition":
            "results/mat2-* and results/materialization-walltime.txt are "
            "RETAINED but PRELIMINARY/SUPERSEDED: the llama-cli -n 0 runs "
            "entered the interactive prompt, evaluated input, and produced "
            "output before exit, so their wall times are not load-only, "
            "time-to-ready, or pure materialization times; their RSS/VRAM "
            "streams have no ready-boundary event marker",
        "arms": arms,
        "nvidia_vulkan_minus_cuda_deltas": deltas,
        "sufficient_runs_per_arm": sufficient,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({a: {"runs": info["runs"],
                          "ready_s": info["startup_to_ready_s_median"],
                          "zero_inf": info["all_zero_inference_proven"]}
                      for a, info in arms.items()}))
    return 0 if sufficient else 1


if __name__ == "__main__":
    sys.exit(main())
