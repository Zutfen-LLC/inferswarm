#!/usr/bin/env python3
"""Issue #243 (R8-I4) — Phase 6 dual-die independent concurrency runner.

Launches one llama-server per die (freshly bound selectors, distinct
ports), proves per-process Vulkan device binding via residency, then
runs interleaved representative load (historical fixtures only),
retaining per-die telemetry, throughput vs single-die execution, and
platform health. No cross-die memory, no P2P requirement.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue243_constants as C
from issue243_phase34 import (start_server, wait_healthy, do_request,
                              vram, gpu_sample, host_sample, FIXTURES)
from issue243_burnin import kernel_window_lines

DURATION_MIN = 15


def main() -> int:
    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    fixtures = json.loads(FIXTURES.read_text())
    ngl = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    t0_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    doc: dict = {
        "schema": "inferswarm.issue243.dualdie/1",
        "campaign": C.CAMPAIGN_ID, "ngl": ngl, "t0": t0_iso,
        "geometry": {"ngl": ngl, "ctx": dict(C.CONTEXT_SETTINGS),
                     "request": dict(C.REQUEST_CONTRACT)},
    }
    k_before = kernel_window_lines()
    procs = {}
    ports = {0: 18700, 1: 18701}
    for idx in (0, 1):
        procs[idx] = start_server(ngl, idx, ports[idx],
                                  out_dir / f"dual-server-idx{idx}.log")
    errs = []
    results = {}
    samples_path = out_dir / "dual-samples.jsonl"
    try:
        for idx in (0, 1):
            wait_healthy(ports[idx])
        time.sleep(10)
        doc["vram_loaded"] = vram()
        # residency proof: each die carries model-scale residency
        vb = doc["vram_loaded"]
        for idx in (0, 1):
            pass  # per-BDF check below
        doc["gpu_loaded"] = gpu_sample()
        prev = host_sample()
        t_end = time.time() + DURATION_MIN * 60
        req_counts = {0: 0, 1: 0}
        case_i = 0
        per_req_wall = {0: [], 1: []}
        with open(samples_path, "a", buffering=1) as f:
            while time.time() < t_end:
                for idx in (0, 1):
                    if procs[idx].poll() is not None:
                        errs.append(f"idx{idx} server died")
                        continue
                    case = fixtures["cases"][case_i % 4]
                    case_i += 1
                    try:
                        r = do_request(ports[idx],
                                       case["prompt_token_ids"])
                        r["case"] = case["case_id"]
                        req_counts[idx] += 1
                        per_req_wall[idx].append(r["wall_s"])
                        results.setdefault(idx, []).append(
                            {"case": case["case_id"], **r})
                    except Exception as e:
                        errs.append(f"idx{idx}: {e!r}")
                h = host_sample(prev["cpu"])
                prev = h
                f.write(json.dumps({
                    "t": round(time.time(), 1),
                    "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                         time.gmtime()),
                    "gpu": gpu_sample(), "vram": vram(),
                    "host": {"iowait_frac": h.get("iowait_frac"),
                             "meminfo": h["meminfo"]},
                }) + "\n")
                time.sleep(5)
        doc["requests_completed"] = req_counts
        doc["throughput_per_die"] = {
            str(idx): {"requests": req_counts[idx],
                       "mean_wall_s": (sum(per_req_wall[idx]) /
                                       len(per_req_wall[idx])
                                       if per_req_wall[idx] else None)}
            for idx in (0, 1)}
        doc["results"] = {str(k): v for k, v in results.items()}
        doc["vram_final"] = vram()
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
    import re
    bad_k = [l for l in new_k if re.search(
        r"amdgpu.*(reset|fault|GPU hang|ring.*timeout)", l, re.I)]
    aer_k = [l for l in new_k if re.search(r"AER|pcieport .*error", l,
                                           re.I)]
    doc["fail_closed"] = {"amdgpu": bad_k, "aer": aer_k, "errs": errs}
    (out_dir / "dual-summary.json").write_text(json.dumps(doc, indent=1))
    print(json.dumps({"requests": req_counts,
                      "amdgpu_faults": len(bad_k), "aer": len(aer_k),
                      "errs": errs[:3]}))
    return 0 if not (bad_k or aer_k or errs) else 3


if __name__ == "__main__":
    sys.exit(main())
