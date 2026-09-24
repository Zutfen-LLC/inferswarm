#!/usr/bin/env python3
"""Issue #243 (R8-I4) — Phase 2 thermal/platform burn-in driver.

For each requested die set, run sustained model-driven load for the
requested duration while sampling telemetry (issue243_sampler logic
inlined for a single process). Load = llama-server completion loop on
the historical case-256 fixture (never predictive material).

Modes:
  burnin.py single <vk_idx> <duration_s> <out_dir>
  burnin.py dual <duration_s> <out_dir>       # both dies concurrently

Fail-closed predicates evaluated at end:
  - any amdgpu reset/fault/GPU-hang/ring-timeout in window
  - any AER/pcieport error in window
  - any temp >= its emergency threshold
  - server process death
Terminal: THERMAL_PLATFORM_STABLE_FOR_BOUNDED_TESTING or smallest blocker.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue243_constants as C
from issue243_phase34 import (start_server, wait_healthy, do_request,
                              vram, gpu_sample, host_sample, FIXTURES)

SAMPLE_INTERVAL = 5.0


def kernel_window_lines() -> list[str]:
    out = subprocess.run(["sudo", "-n", "dmesg", "-T"],
                         capture_output=True, text=True).stdout
    pat = re.compile(
        r"amdgpu.*(reset|fault|GPU hang|ring.*timeout)|AER|"
        r"pcieport .*error", re.I)
    return [l for l in out.splitlines() if pat.search(l)]


def temp_emergencies(gpu: dict) -> list[str]:
    hits = []
    for bdf, e in gpu.items():
        for k, v in e.items():
            if k.startswith("temp_") and isinstance(v, (int, float)):
                # vega10 emergency: edge 90C, junction 110C, mem 100C
                lim = 90.0 if "edge" in k else (
                    110.0 if "junction" in k else (
                        100.0 if "mem" in k else None))
                if lim and v >= lim:
                    hits.append(f"{bdf} {k}={v}")
    return hits


def main() -> int:
    mode = sys.argv[1]
    out_dir = Path(sys.argv[-1])
    out_dir.mkdir(parents=True, exist_ok=True)
    fixtures = json.loads(FIXTURES.read_text())
    case = fixtures["cases"][0]

    # Burn-in placement: the top in-budget frozen ladder rung (ngl=7,
    # ~6.5 GiB residency, max sustained power/thermal draw under the
    # prospectively frozen HBM reserve; see placement-probe law).
    ngl = int(__import__("os").environ.get("IS243_BURNIN_NGL", "7"))
    t0_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    doc: dict = {
        "schema": "inferswarm.issue243.burnin/1",
        "campaign": C.CAMPAIGN_ID, "mode": mode, "ngl": ngl,
        "t0": t0_iso,
        "geometry": {"ngl": ngl, "ctx": dict(C.CONTEXT_SETTINGS),
                     "request": dict(C.REQUEST_CONTRACT)},
    }
    k_before = kernel_window_lines()

    procs = {}
    ports = {}
    if mode == "single":
        idxs = [int(sys.argv[2])]
        duration = float(sys.argv[3])
    else:
        idxs = [0, 1]
        duration = float(sys.argv[2])
    for i, idx in enumerate(idxs):
        port = 18600 + i
        ports[idx] = port
        log = open(out_dir / f"burnin-server-idx{idx}.log", "w")
        procs[idx] = start_server(ngl, idx, port,
                                  out_dir / f"burnin-server-idx{idx}.log")
    samples_path = out_dir / "burnin-samples.jsonl"
    errs: list[str] = []
    n_req = {idx: 0 for idx in idxs}
    try:
        for idx in idxs:
            wait_healthy(ports[idx])
        time.sleep(10)
        doc["vram_loaded"] = vram()
        doc["gpu_loaded"] = gpu_sample()
        t_end = time.time() + duration
        prev = host_sample()
        with open(samples_path, "a", buffering=1) as f:
            while time.time() < t_end:
                for idx in idxs:
                    if procs[idx].poll() is not None:
                        errs.append(f"server idx{idx} died rc="
                                    f"{procs[idx].returncode}")
                    else:
                        try:
                            do_request(ports[idx],
                                       case["prompt_token_ids"])
                            n_req[idx] += 1
                        except Exception as e:
                            errs.append(f"idx{idx} request error: {e!r}")
                g = gpu_sample()
                h = host_sample(prev["cpu"])
                prev = h
                f.write(json.dumps({
                    "t": round(time.time(), 1),
                    "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                         time.gmtime()),
                    "gpu": g,
                    "vram": vram(),
                    "host": {"iowait_frac": h.get("iowait_frac"),
                             "meminfo": h["meminfo"]},
                    "requests_done": dict(n_req),
                }) + "\n")
                em = temp_emergencies(g)
                if em:
                    errs.append("temp emergency: " + ";".join(em))
                time.sleep(SAMPLE_INTERVAL)
        doc["vram_final"] = vram()
        doc["requests_completed"] = dict(n_req)
    finally:
        for p in procs.values():
            p.terminate()
        time.sleep(5)
        for p in procs.values():
            if p.poll() is None:
                p.kill()

    k_after = kernel_window_lines()
    new_k = k_after[len(k_before):] if k_after[:len(k_before)] == \
        k_before else k_after
    doc["kernel_new_lines"] = new_k[-40:]
    bad_k = [l for l in new_k if re.search(
        r"amdgpu.*(reset|fault|GPU hang|ring.*timeout)", l, re.I)]
    aer_k = [l for l in new_k if re.search(r"AER|pcieport .*error", l,
                                           re.I)]
    doc["fail_closed"] = {
        "amdgpu_reset_or_fault": bad_k,
        "aer_or_pcieport_errors": aer_k,
        "process_failures": errs,
    }
    stable = not (bad_k or aer_k or errs)
    doc["terminal"] = ("THERMAL_PLATFORM_STABLE_FOR_BOUNDED_TESTING"
                       if stable else
                       "BLOCKED:" + json.dumps(
                           {"amdgpu": bad_k[:3], "aer": aer_k[:3],
                            "errs": errs[:3]})[:400])
    (out_dir / "burnin-summary.json").write_text(json.dumps(doc, indent=1))
    print(json.dumps({"terminal": doc["terminal"],
                      "requests": doc.get("requests_completed")}))
    return 0 if stable else 3


if __name__ == "__main__":
    sys.exit(main())
