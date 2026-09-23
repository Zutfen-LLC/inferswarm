#!/usr/bin/env python3
"""Issue #243 (R8-I4) — Phase 3 ladder runner + Phase 4 regime runner.

Runs the frozen ngl ladder (Phase 3) and the historical fixture regimes
(Phase 4) against a single selected die. Per rung/case retains:

  prompt/decode/wall timing (from response timings_detailed + wall),
  selected/excluded die HBM, host RSS/RssFile/anon/swap from smaps_rollup,
  process read_bytes/write_bytes, major faults, GPU util/temps/clocks,
  iowait, kernel health window, tokens (identity only; never used for
  placement selection — negative control 12).

Usage:
  phase34.py rung <vk_idx> <ngl> <out_dir>          # one ladder rung
  phase34.py regime <vk_idx> <ngl> <out_dir>        # 4 fixtures x repeats
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

SERVER = Path(C.BIN_DIR) / "llama-server"
MODEL = Path(C.MODEL_DIR) / C.MODEL_MEMBERS[0]["member"]
DIES = {"0000:07:00.0": "card1", "0000:0b:00.0": "card2"}
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures.json"


def http_json(url: str, payload: dict, timeout: int = 14400) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def wait_healthy(port: int, deadline_s: int = 14400) -> float:
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


def vram() -> dict:
    out = {}
    for bdf, card in DIES.items():
        out[bdf] = int(
            Path(f"/sys/class/drm/{card}/device/mem_info_vram_used")
            .read_text().strip())
    return out


def proc_stat(pid: int) -> dict:
    out = {}
    p = Path(f"/proc/{pid}")
    for f in ("stat", "status"):
        try:
            txt = (p / f).read_text()
        except OSError:
            continue
        if f == "stat":
            fields = txt.rsplit(")", 1)[1].split()
            # field 12 majflt is index 9 after the split (state=3rd)
            out["majflt"] = int(fields[9])
            out["utime_ticks"] = int(fields[11])
            out["stime_ticks"] = int(fields[12])
            out["starttime_ticks"] = int(fields[19])
        else:
            for line in txt.splitlines():
                if line.startswith(("VmRSS", "VmSize", "VmSwap",
                                    "VmData")):
                    k, v = line.split(":", 1)
                    out[k] = v.strip()
    try:
        io = (p / "io").read_text()
        for line in io.splitlines():
            if line.startswith(("read_bytes", "write_bytes",
                                "rchar", "wchar")):
                k, v = line.split(":", 1)
                out[k] = v.strip()
    except OSError:
        pass
    try:
        roll = (p / "smaps_rollup").read_text()
        for line in roll.splitlines():
            if line.startswith(("Rss:", "RssFile:", "Anonymous:",
                                "Pss:")):
                k, v = line.split(":", 1)
                out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


def gpu_sample() -> dict:
    out = {}
    for bdf, card in DIES.items():
        base = Path(f"/sys/class/drm/{card}/device")
        e = {}
        for k in ("gpu_busy_percent", "mem_busy_percent",
                  "mem_info_vram_used", "current_link_speed",
                  "current_link_width"):
            try:
                e[k] = (base / k).read_text().strip()
            except OSError:
                pass
        for h in sorted((base / "hwmon").glob("hwmon*")):
            for tf in sorted(h.glob("temp*_input")):
                label = ""
                lf = Path(str(tf).replace("_input", "_label"))
                if lf.is_file():
                    label = lf.read_text().strip()
                try:
                    e[f"temp_{label or tf.name}"] = \
                        int(tf.read_text()) / 1000.0
                except (OSError, ValueError):
                    pass
            pf = h / "power1_input"
            if pf.is_file():
                try:
                    e["power_w"] = int(pf.read_text()) / 1e6
                except (OSError, ValueError):
                    pass
        try:
            sclk = (base / "pp_dpm_sclk").read_text()
            cur = [l for l in sclk.splitlines() if "*" in l]
            e["sclk_current"] = cur[0].split(":")[-1].replace("*",
                                                              "").strip()
        except OSError:
            pass
        out[bdf] = e
    return out


def host_sample(prev_cpu=None) -> dict:
    fields = list(map(int, Path("/proc/stat").read_text().splitlines()[0]
                      .split()[1:]))
    d = {"cpu": fields}
    if prev_cpu:
        dt = sum(b - a for a, b in zip(prev_cpu, fields))
        diow = fields[5] - prev_cpu[5]
        d["iowait_frac"] = (diow / dt) if dt else 0.0
    mem = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith(("MemAvailable", "MemFree", "Cached", "SwapFree",
                            "SwapTotal", "Dirty", "Writeback")):
            k, v = line.split(":", 1)
            mem[k] = v.strip()
    d["meminfo"] = mem
    return d


def kernel_window(t0_iso: str) -> dict:
    out = subprocess.run(["sudo", "-n", "dmesg", "-T"],
                         capture_output=True, text=True).stdout
    pat = re.compile(
        r"amdgpu.*(reset|fault|GPU hang|ring.*timeout)|AER|"
        r"pcieport .*error", re.I)
    lines = [l for l in out.splitlines() if pat.search(l)]
    return {"matching_lines": lines[-40:], "count": len(lines)}


def start_server(ngl: int, vk_idx: int, port: int, log_path: Path
                 ) -> subprocess.Popen:
    env = dict(os.environ)
    env["LD_LIBRARY_PATH"] = C.BIN_DIR + ":" + env.get("LD_LIBRARY_PATH",
                                                       "")
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


def do_request(port: int, prompt_ids: list) -> dict:
    body = dict(C.REQUEST_CONTRACT)
    body["prompt"] = prompt_ids
    t0 = time.time()
    resp = http_json(f"http://127.0.0.1:{port}/completion", body)
    wall = time.time() - t0
    return {"wall_s": round(wall, 3),
            "timings": resp.get("timings_detailed")
            or resp.get("timings"),
            "tokens": resp.get("tokens"),
            "stop_type": resp.get("stop_type")}


def main() -> int:
    mode = sys.argv[1]
    vk_idx = int(sys.argv[2])
    if mode == "rung":
        ngl = int(sys.argv[3])
        out_dir = Path(sys.argv[4])
    else:
        ngl = int(sys.argv[3])
        out_dir = Path(sys.argv[4])
    out_dir.mkdir(parents=True, exist_ok=True)
    fixtures = json.loads(FIXTURES.read_text())

    port = 18500 + vk_idx
    tag = f"idx{vk_idx}-ngl{ngl}"
    log_path = out_dir / f"server-{tag}.log"
    t0_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    pre_vram = vram()
    proc = start_server(ngl, vk_idx, port, log_path)
    doc = {
        "schema": f"inferswarm.issue243.{mode}/1",
        "campaign": C.CAMPAIGN_ID,
        "vk_idx": vk_idx, "ngl": ngl, "port": port,
        "geometry": {"ngl": ngl, "ctx": dict(C.CONTEXT_SETTINGS),
                     "request": dict(C.REQUEST_CONTRACT)},
        "server_pid": proc.pid, "t0": t0_iso,
        "vram_before": pre_vram,
        "runs": [],
    }
    rc = 0
    try:
        load_s = wait_healthy(port)
        doc["load_to_healthy_s"] = round(load_s, 1)
        time.sleep(10)  # settle
        doc["vram_loaded"] = vram()
        doc["proc_loaded"] = proc_stat(proc.pid)
        doc["gpu_loaded"] = gpu_sample()
        prev = host_sample()
        if mode == "rung":
            case = fixtures["cases"][0]  # case-256 as load exercise
            for rep in range(1, C.REQUIRED_REPEATS_WARM + 1):
                r = do_request(port, case["prompt_token_ids"])
                r["case"] = case["case_id"]
                r["rep"] = rep
                r["vram_post"] = vram()
                r["gpu_post"] = gpu_sample()
                h = host_sample(prev["cpu"])
                r["host"] = {"iowait_frac": h.get("iowait_frac"),
                             "meminfo": h["meminfo"]}
                prev = h
                r["proc_post"] = proc_stat(proc.pid)
                doc["runs"].append(r)
                print(json.dumps({"rep": rep,
                                  "wall": r["wall_s"],
                                  "prompt_s": (r.get("timings") or {})
                                  .get("prompt_n")}))
        else:  # regime
            for case in fixtures["cases"]:
                # 1 cold-ish first + REQUIRED_REPEATS_WARM warm
                for rep in range(0, C.REQUIRED_REPEATS_WARM + 1):
                    r = do_request(port, case["prompt_token_ids"])
                    r["case"] = case["case_id"]
                    r["rep"] = rep  # 0 = first-touch
                    r["vram_post"] = vram()
                    r["gpu_post"] = gpu_sample()
                    h = host_sample(prev["cpu"])
                    r["host"] = {"iowait_frac": h.get("iowait_frac"),
                                 "meminfo": h["meminfo"]}
                    prev = h
                    r["proc_post"] = proc_stat(proc.pid)
                    doc["runs"].append(r)
                    print(json.dumps({"case": case["case_id"],
                                      "rep": rep, "wall": r["wall_s"]}))
        doc["kernel_window"] = kernel_window(t0_iso)
        doc["vram_final"] = vram()
    except Exception as e:  # fail closed, retain partial
        doc["error"] = repr(e)
        doc["kernel_window"] = kernel_window(t0_iso)
        rc = 3
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
    (out_dir / f"{mode}-{tag}.json").write_text(json.dumps(doc, indent=1))
    print("wrote", out_dir / f"{mode}-{tag}.json")
    return rc


if __name__ == "__main__":
    sys.exit(main())
