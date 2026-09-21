#!/usr/bin/env python3
"""Issue #234 — R8-H matched placement preflight (schema /2).

Load-only preflight per arm: boots the arm's frozen binary with the
frozen matched geometry (ngl=1, ctx 8192, batch 512) and the exact
model bytes, waits for load, samples device memory residency, then
terminates the process. Emits NO correctness output (no /completion
request is ever sent; the model is not evaluated).

Per-arm proof obligations (issue #11 execution-truth pre-component):
  * selected device carries nonzero model-scale residency;
  * sibling/excluded device stays under the frozen noise bound
    (< 1 MiB delta) and carries no compute process;
  * process exits cleanly and memory releases.

The token-bearing ladder (issue234_ladder.py) re-samples residency
DURING generation; this preflight only proves the geometry is legal
before canonical output exists.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue234_receipt as rc


class PlacementError(RuntimeError):
    pass


def gpu_mem_nvidia() -> dict[str, dict[str, int]]:
    out = subprocess.run(
        ["nvidia-smi", "--query-gpu=uuid,memory.used",
         "--format=csv,noheader"], capture_output=True, text=True)
    res: dict[str, dict[str, int]] = {}
    for line in (out.stdout or "").splitlines():
        f = [x.strip() for x in line.split(",")]
        if len(f) == 2:
            res[f[0]] = {"mem_used_mib": int(f[1].split()[0])}
    return res


def gpu_mem_amd() -> dict[str, dict[str, int]]:
    res = {}
    for bdf_dir in sorted(Path("/sys/class/drm").glob("card*")):
        pass
    # enumerated by BDF via sysfs
    import issue234_host as host
    for cand in Path("/sys/bus/pci/devices").iterdir():
        if not cand.name.startswith("0000:"):
            continue
        try:
            bdf = host.bdf16(cand.name)
        except Exception:
            continue
        drm = sorted(cand.glob("drm/card*"))
        if not drm:
            continue
        m = {}
        for key in ("mem_info_vram_used", "mem_info_vis_vram_used"):
            f = drm[0] / "device" / key
            if f.is_file():
                m[key] = int(f.read_text().strip())
        if m:
            res[bdf] = m
    return res


def wait_loaded(log_path: Path, deadline_s: int = 7200) -> bool:
    deadline = time.time() + deadline_s
    loaded = False
    while time.time() < deadline:
        try:
            text = log_path.read_text(errors="replace")
        except FileNotFoundError:
            text = ""
        if "model loaded" in text:
            loaded = True
            break
        if "error" in text.lower() and "loading" in text.lower():
            break
        time.sleep(5)
    return loaded


def preflight(arm: str, server: Path, model_dir: Path, out_dir: Path,
              cuda_selector: str | None = None,
              vk_selector: str | None = None,
              icd: Path | None = None,
              selected_key: str | None = None,
              excluded_keys: list[str] | None = None,
              port: int = 18490) -> dict[str, Any]:
    import os
    if arm not in ("A", "B", "C"):
        raise PlacementError(f"bad arm {arm!r}")
    if selected_key is None or excluded_keys is None:
        raise PlacementError("selected/excluded device keys required")
    model_files = sorted(model_dir.glob("*.gguf"))
    if len(model_files) != len(rc.MODEL_MEMBERS):
        raise PlacementError(f"model dir member count {len(model_files)}")
    model_arg = model_files[0]  # split GGUF: first member carries the set

    env = dict(os.environ)
    env["PATH"] = "/usr/bin:/bin:" + env.get("PATH", "")
    if arm in ("B", "C"):
        # deployed launcher needs its co-packaged libs (01-built bin dir)
        env["LD_LIBRARY_PATH"] = (str(server.parent) + ":" +
                                  env.get("LD_LIBRARY_PATH", ""))
    if arm == "A":
        env["CUDA_VISIBLE_DEVICES"] = cuda_selector or ""
        env.pop("GGML_VK_VISIBLE_DEVICES", None)
    else:
        env["GGML_VK_VISIBLE_DEVICES"] = vk_selector or ""
        env.pop("CUDA_VISIBLE_DEVICES", None)
        if icd is not None:
            env["VK_ICD_FILENAMES"] = str(icd)
    # never let a foreign CUDA runtime see devices in Vulkan arms
    if arm in ("B", "C"):
        env["CUDA_VISIBLE_DEVICES"] = "-1"

    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / f"preflight-{arm}-server.log"

    mem_before = (gpu_mem_nvidia() if arm in ("A", "B") else gpu_mem_amd())
    t0 = time.strftime("%Y-%m-%d %H:%M:%S")
    log = open(log_path, "w")
    proc = subprocess.Popen(
        [str(server), "--model", str(model_arg),
         "--n-gpu-layers", str(rc.MATCHED_NGL),
         "--ctx-size", str(rc.CONTEXT_SETTINGS["ctx-size"]),
         "--batch-size", str(rc.CONTEXT_SETTINGS["batch-size"]),
         "--port", str(port), "--host", "127.0.0.1"],
        stdout=log, stderr=subprocess.STDOUT, env=env)
    doc: dict[str, Any] = {
        "schema": "inferswarm.r8h.placement/2",
        "campaign": rc.CAMPAIGN_ID,
        "arm": arm,
        "geometry": {"ngl": rc.MATCHED_NGL,
                     "ctx": dict(rc.CONTEXT_SETTINGS)},
        "selector": {"cuda": cuda_selector, "vk": vk_selector,
                     "icd": str(icd) if icd else None},
        "model_members": [m.name for m in model_files],
        "t_start": t0,
        "pid": proc.pid,
    }
    loaded = False
    residency = None
    exit_code = None
    try:
        loaded = wait_loaded(log_path)
        time.sleep(20)  # settle allocations
        mem_during = (gpu_mem_nvidia() if arm in ("A", "B") else gpu_mem_amd())
        sel_before = mem_before.get(selected_key, {})
        sel_during = mem_during.get(selected_key, {})
        sel_delta = {k: sel_during.get(k, 0) - sel_before.get(k, 0)
                     for k in set(sel_before) | set(sel_during)}
        excluded = {}
        for ex in excluded_keys:
            b = mem_before.get(ex, {})
            d = mem_during.get(ex, {})
            excluded[ex] = {k: d.get(k, 0) - b.get(k, 0)
                            for k in set(b) | set(d)}
        residency = {
            "selected": {"key": selected_key, "before": sel_before,
                         "during": sel_during, "delta": sel_delta},
            "excluded": excluded,
        }
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        time.sleep(10)
        mem_after = (gpu_mem_nvidia() if arm in ("A", "B") else gpu_mem_amd())
        exit_code = proc.returncode
        doc["post_exit"] = {
            "memory_after": mem_after,
            "exit_code": exit_code,
            "released": all(
                v.get("mem_used_mib", 0) <= 8 for v in mem_after.values())
            if arm in ("A", "B") else None,
        }
    doc.update({
        "loaded": loaded,
        "residency": residency,
        "server_log_tail": log_path.read_text(errors="replace")[-8000:],
    })
    out = out_dir / f"preflight-{arm}.json"
    out.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(json.dumps({"arm": arm, "loaded": loaded,
                      "selected_delta": (residency or {}).get(
                          "selected", {}).get("delta"),
                      "exit_code": exit_code}))
    return doc


def judge(doc: dict[str, Any], excluded_max_bytes: int
          = rc.EXCLUDED_DEVICE_MAX_BYTES) -> dict[str, Any]:
    """Mechanical legality judgment of one preflight (fail closed)."""
    problems = []
    if not doc.get("loaded"):
        problems.append("model_did_not_load")
    res = doc.get("residency") or {}
    sel_delta = res.get("selected", {}).get("delta", {})
    sel_bytes = _model_residency_bytes(sel_delta)
    if sel_bytes <= 0:
        problems.append("zero_selected_device_residency")
    for ex_key, deltas in (res.get("excluded") or {}).items():
        ex_bytes = _model_residency_bytes(deltas)
        if ex_bytes >= excluded_max_bytes:
            problems.append(f"excluded_device_active:{ex_key}")
    post = doc.get("post_exit") or {}
    if post.get("exit_code") not in (0,):
        problems.append(f"exit_code:{post.get('exit_code')}")
    if problems:
        return {"status": "ILLEGAL", "problems": problems}
    return {"status": "LEGAL",
            "selected_delta_bytes": sel_bytes,
            "excluded_max_delta_bytes": max(
                ([_to_bytes(k, v)
                  for d in (res.get("excluded") or {}).values()
                  for k, v in d.items()] or [0]))}


def _to_bytes(key: str, value: int) -> int:
    if key.endswith("_mib"):
        return value * 1024 * 1024
    return value


def _model_residency_bytes(deltas: dict[str, int]) -> int:
    """Model-scale residency for one device from its mem deltas.

    AMD: mem_info_vis_vram_used / mem_info_vram_used are the
    model-residency counters (the superseded campaign measured
    1,050,275,840 B vis-vram at ngl=1); gtt is host-backed noise.
    NVIDIA: nvidia-smi memory.used (MiB).
    """
    keys = [k for k in deltas
            if "vis_vram_used" in k or k == "mem_used_mib"
            or k.endswith(".mem_info_vram_used")]
    vals = [_to_bytes(k, deltas[k]) for k in keys]
    return max(vals) if vals else max(
        (_to_bytes(k, v) for k, v in deltas.items()), default=0)


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--arm", choices=("A", "B", "C"), required=True)
    ap.add_argument("--server", type=Path, required=True)
    ap.add_argument("--model-dir", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--cuda-selector")
    ap.add_argument("--vk-selector")
    ap.add_argument("--icd", type=Path)
    ap.add_argument("--selected-key", required=True)
    ap.add_argument("--excluded-keys", nargs="+", required=True)
    ap.add_argument("--port", type=int, default=18490)
    args = ap.parse_args()
    doc = preflight(
        args.arm, args.server, args.model_dir, args.out_dir,
        args.cuda_selector, args.vk_selector, args.icd,
        args.selected_key, args.excluded_keys, args.port)
    print(json.dumps(judge(doc)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
