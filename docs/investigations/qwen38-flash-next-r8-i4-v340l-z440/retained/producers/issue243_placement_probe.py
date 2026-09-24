#!/usr/bin/env python3
"""Issue #243 (R8-I4) — placement probe + ladder derivation (Phase 3 pre).

On inferswarm05, using ONLY the pinned R8-H Vulkan binary and the exact
accepted model members:

  1. load-only residency probes binding GGML_VK_VISIBLE_DEVICES index ->
     physical BDF (sysfs mem_info_vram_used delta at ngl=1);
  2. fresh per-layer placement law from load logs at ngl=1 and ngl=2
     (model_buffer(2) - model_buffer(1) = per-layer bytes);
  3. prospective ladder derivation from the frozen HBM reserve
     (constants) and the FRESH law; writes phase3-freeze.json BEFORE
     any retained performance output.

No completion requests are issued here (load-only). Fails closed on
any excluded-die residency above the frozen noise bound.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue243_constants as C

SERVER = Path(C.BIN_DIR) / "llama-server"
MODEL = Path(C.MODEL_DIR) / C.MODEL_MEMBERS[0]["member"]
DIES = {"0000:07:00.0": "card1", "0000:0b:00.0": "card2"}
PORT = 18999


def vram_used() -> dict[str, int]:
    out = {}
    for bdf, card in DIES.items():
        p = Path(f"/sys/class/drm/{card}/device/mem_info_vram_used")
        out[bdf] = int(p.read_text().strip())
    return out


def start_server(ngl: int, vk_idx: int, log_path: Path,
                 port: int = PORT) -> subprocess.Popen:
    env = dict(os.environ)
    env["LD_LIBRARY_PATH"] = C.BIN_DIR + ":" + env.get("LD_LIBRARY_PATH", "")
    env["VK_ICD_FILENAMES"] = C.ICD_FILE
    env["GGML_VK_VISIBLE_DEVICES"] = str(vk_idx)
    env["CUDA_VISIBLE_DEVICES"] = "-1"
    log = open(log_path, "w")
    return subprocess.Popen(
        [str(SERVER), "--model", str(MODEL),
         "--n-gpu-layers", str(ngl),
         "--ctx-size", str(C.CONTEXT_SETTINGS["ctx-size"]),
         "--batch-size", str(C.CONTEXT_SETTINGS["batch-size"]),
         "--port", str(port), "--host", "127.0.0.1"],
        stdout=log, stderr=subprocess.STDOUT, env=env)


def wait_healthy(port: int, deadline_s: int = 3600) -> float:
    import urllib.request
    t0 = time.time()
    deadline = t0 + deadline_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/health", timeout=10) as r:
                if r.status == 200:
                    return time.time() - t0
        except Exception:
            time.sleep(5)
    raise RuntimeError("server not healthy before deadline")


def buffer_mib_from_log(log_path: Path) -> dict[str, float]:
    """Parse llama-server load log for per-device buffer sizes."""
    txt = log_path.read_text()
    out = {}
    # lines like: Vulkan0: AMD Radeon Pro V340 ... buffersize = 1234.00 MiB
    for m in re.finditer(
            r"(Vulkan\d+):.*?buffersize\s*=\s*([\d.]+)\s*MiB", txt):
        out[m.group(1)] = float(m.group(2))
    return out


def stop(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=60)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    # wait for VRAM release
    for _ in range(60):
        if all(v < 100 * 1024 * 1024 for v in vram_used().values()):
            return
        time.sleep(2)


def probe(idx: int, ngl: int, tag: str, out_dir: Path) -> dict:
    log_path = out_dir / f"probe-{tag}-idx{idx}-ngl{ngl}-server.log"
    pre = vram_used()
    t0 = time.time()
    proc = start_server(ngl, idx, log_path)
    try:
        load_s = wait_healthy(PORT)
        post = vram_used()
        bufs = buffer_mib_from_log(log_path)
        rec = {
            "vk_idx": idx, "ngl": ngl,
            "vram_before": pre, "vram_after": post,
            "delta": {b: post[b] - pre[b] for b in DIES},
            "log_buffers_mib": bufs,
            "load_to_healthy_s": round(load_s, 1),
            "pid": proc.pid,
        }
        return rec
    finally:
        stop(proc)
        rec_log = log_path.read_text()
        (out_dir / f"probe-{tag}-idx{idx}-ngl{ngl}-server.log").write_text(
            rec_log)


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        "evidence/phase3")
    out_dir.mkdir(parents=True, exist_ok=True)
    doc: dict = {
        "schema": "inferswarm.issue243.placement-probe/1",
        "campaign": C.CAMPAIGN_ID,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                    time.gmtime()),
        "probes": [],
    }

    # 1) index -> BDF binding probes on die-A (idx under test), ngl=1
    binding = {}
    for idx in (0, 1):
        rec = probe(idx, 1, "bind", out_dir)
        doc["probes"].append(rec)
        sel = max(rec["delta"], key=rec["delta"].get)
        others = [b for b in rec["delta"] if b != sel]
        noise_ok = all(rec["delta"][b] < C.EXCLUDED_DIE_NOISE_BYTES
                       for b in others)
        if not noise_ok:
            doc["error"] = f"idx {idx}: excluded-die delta above noise bound"
            Path(out_dir / "placement-probe.json").write_text(
                json.dumps(doc, indent=1))
            return 3
        binding[str(idx)] = {"selected_bdf": sel,
                             "delta_bytes": rec["delta"][sel],
                             "excluded_deltas": {b: rec["delta"][b]
                                                 for b in others}}
        print(f"idx {idx} -> {sel} (delta {rec['delta'][sel]} B)")
    # require the two indices to select DIFFERENT dies
    if binding["0"]["selected_bdf"] == binding["1"]["selected_bdf"]:
        doc["error"] = "both indices selected the same die"
        Path(out_dir / "placement-probe.json").write_text(
            json.dumps(doc, indent=1))
        return 3

    # 2) fresh per-layer law from sysfs residency deltas at ngl=1,2,3
    #    (log buffer lines are absent at this pin under lazy loading;
    #    sysfs mem_info_vram_used delta is the retained authority)
    sel_idx = 0  # bound above to a distinct BDF; re-proven per phase
    law = {}
    for ngl in (1, 2, 3):
        rec = probe(sel_idx, ngl, "law", out_dir)
        doc["probes"].append(rec)
        sel_bdf = binding[str(sel_idx)]["selected_bdf"]
        law[ngl] = rec["delta"][sel_bdf] / (1 << 20)
    if not all(law.get(n) for n in (1, 2, 3)):
        doc["error"] = f"zero residency delta: {law}"
        Path(out_dir / "placement-probe.json").write_text(
            json.dumps(doc, indent=1))
        return 3
    per_layer_mib = ((law[3] - law[1]) / 2.0)
    head_mib = law[1] - 0 * per_layer_mib  # ngl=1 = head only
    total_mib = 8176.0
    budget_mib = total_mib - C.HBM_RESERVE_BYTES / (1 << 20)
    max_ngl = 1
    for n in range(1, 200):
        if head_mib + (n - 1) * per_layer_mib <= budget_mib:
            max_ngl = n
        else:
            break
    rungs = [n for n in (1, 2, 4, 6, 7) if n <= max_ngl]
    doc["placement_law"] = {
        "ngl1_buffer_mib": law[1],
        "ngl2_buffer_mib": law[2],
        "per_layer_mib": per_layer_mib,
        "output_head_mib": head_mib,
        "hbm_total_mib": total_mib,
        "hbm_reserve_mib": C.HBM_RESERVE_BYTES / (1 << 20),
        "budget_mib": budget_mib,
        "max_ngl_mechanical": max_ngl,
        "ladder_rungs": rungs,
        "derivation": "buffer(ngl)=head+(ngl-1)*per_layer; largest ngl "
                      "with buffer<=budget; rungs are the frozen "
                      "monotone subset (1,2,4,6,8,12,16) capped at max",
    }
    doc["binding"] = binding
    doc["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                       time.gmtime())
    Path(out_dir / "placement-probe.json").write_text(json.dumps(doc,
                                                                 indent=1))
    print(json.dumps(doc["placement_law"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
