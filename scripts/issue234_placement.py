#!/usr/bin/env python3
"""Issue #234 — R8-H prospectively frozen placement preflight.

Runs on inferswarm02. LOAD-ONLY preflight (no correctness output):
launches llama-server with each candidate --n-gpu-layers value under
the frozen single-die selector, waits for load completion, captures
the load log's buffer placement lines + amdgpu memory counters for
BOTH dies, then terminates the server. Every attempted geometry is
retained.

Selection rule (frozen in issue234_receipt.PLACEMENT_RULE): the
SMALLEST candidate ngl with measured >0 model-buffer bytes on the
selected die and 0 on the excluded die, subject to the frozen
headroom contract. Mechanical, output-blind: it never sees a token.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue234_receipt as rc


class PlacementError(RuntimeError):
    pass


def amdgpu_mem(bdf_sysfs: str) -> dict[str, int]:
    out = {}
    base = Path(f"/sys/bus/pci/devices/{bdf_sysfs}/drm")
    for card in sorted(base.glob("card*")):
        dev = card / "device"
        for f, k in (("mem_info_vram_used", "vram_used"),
                     ("mem_info_gtt_used", "gtt_used"),
                     ("mem_info_vis_vram_used", "vis_vram_used")):
            p = dev / f
            if p.is_file():
                try:
                    out[f"{card.name}.{k}"] = int(p.read_text().strip())
                except ValueError:
                    pass
    return out


def parse_load_placement(log: str) -> dict[str, Any]:
    """Parse the pinned llama.cpp load log's placement lines."""
    out: dict[str, Any] = {"vulkan_buffers_mib": {}, "cpu_buffers_mib": {},
                           "offloaded_layers": None, "total_layers": None}
    # lines like: llama_new_context_with_model: Vulkan0 buffer size = ...
    for m in re.finditer(
            r"(Vulkan\d+|CPU) buffer size\s*=\s*([\d.]+)\s*MiB", log):
        out["vulkan_buffers_mib"].setdefault(m.group(1), 0.0)
        out["vulkan_buffers_mib"][m.group(1)] += float(m.group(2))
    m = re.search(r"offloaded (\d+)/(\d+) layers", log)
    if m:
        out["offloaded_layers"] = int(m.group(1))
        out["total_layers"] = int(m.group(2))
    return out


def preflight_ngl(server: Path, model_dir: Path, ngl: int,
                  selected_sysfs: str, excluded_sysfs: str,
                  port: int = 18433, log_dir: Path = Path("/tmp/is234")) -> dict[str, Any]:
    """One load-only attempt. No completion request is ever sent."""
    env = {
        "GGML_VK_VISIBLE_DEVICES": "1",
        "PATH": "/usr/bin:/bin",
    }
    import os
    full_env = dict(os.environ)
    full_env.update(env)
    model = model_dir / rc.MODEL_MEMBERS[0]["member"]
    cmd = [str(server), "--model", str(model),
           "--n-gpu-layers", str(ngl), "--ctx-size", "8192", "--batch-size", "512",
           "--port", str(port), "--host", "127.0.0.1"]
    log_path = log_dir / f"preflight-ngl{ngl}.log"
    rec: dict[str, Any] = {}
    log = ""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True,
                            env=full_env, cwd=str(log_dir))
    baseline_sel = amdgpu_mem(selected_sysfs)
    baseline_exc = amdgpu_mem(excluded_sysfs)
    loaded = False
    deadline = time.time() + 3600
    log_lines: list[str] = []
    try:
        while time.time() < deadline:
            line = proc.stdout.readline() if proc.stdout else ""
            if line:
                log_lines.append(line)
                if "model loaded" in line or "listen address" in line.lower():
                    loaded = True
                    break
                if re.search(r"error|failed to load|CUDA|abort", line, re.I):
                    break
            if proc.poll() is not None:
                break
            time.sleep(0.2)
        log = "".join(log_lines)
        during_sel = amdgpu_mem(selected_sysfs)
        during_exc = amdgpu_mem(excluded_sysfs)
        delta_sel = {k: during_sel.get(k, 0) - baseline_sel.get(k, 0)
                     for k in during_sel}
        delta_exc = {k: during_exc.get(k, 0) - baseline_exc.get(k, 0)
                     for k in during_exc}
        rec = {
            "schema": "inferswarm.r8h.placement-preflight/1",
            "campaign": rc.CAMPAIGN_ID,
            "ngl": ngl,
            "cmd": cmd,
            "selector": env,
            "loaded": loaded,
            "exit_code": proc.poll(),
            "placement": parse_load_placement(log),
            "selected_die_mem_delta_bytes": delta_sel,
            "excluded_die_mem_delta_bytes": delta_exc,
            "log_excerpt": log[-8000:],
        }
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        # VRAM release check
        time.sleep(3)
        after_sel = amdgpu_mem(selected_sysfs)
        rec["selected_die_mem_after_exit_bytes"] = after_sel
        rec["selected_die_released"] = (
            after_sel.get("card0.vram_used", 0) <=
            baseline_sel.get("card0.vram_used", 0) + 8 * 1024 * 1024)
    log_path.write_text(log if 'log' in dir() else "".join(log_lines))
    return rec


def select_geometry(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply the frozen selection rule over retained attempts."""
    for rec in sorted(attempts, key=lambda r: r["ngl"]):
        if not rec.get("loaded"):
            continue
        sel = rec["selected_die_mem_delta_bytes"]
        exc = rec["excluded_die_mem_delta_bytes"]
        sel_vram = max((v for k, v in sel.items() if "vram_used" in k),
                       default=0)
        exc_vram = max((v for k, v in exc.items() if "vram_used" in k),
                       default=0)
        if sel_vram > 0 and exc_vram < rc.EXCLUDED_DIE_MAX_BYTES:
            vulkan_mib = rec["placement"]["vulkan_buffers_mib"]
            on_die_mib = sum(v for k, v in vulkan_mib.items()
                             if k.startswith("Vulkan"))
            if on_die_mib * 1024 * 1024 <= rc.DIE_HEAP_BYTES - rc.SAFETY_HEADROOM_BYTES:
                return {
                    "selected_ngl": rec["ngl"],
                    "rule": rc.PLACEMENT_RULE,
                    "selected_die_model_bytes": sel_vram,
                    "excluded_die_model_bytes": exc_vram,
                    "headroom_bytes": rc.DIE_HEAP_BYTES -
                    int(on_die_mib * 1024 * 1024),
                    "basis_attempt": rec,
                }
    raise PlacementError(
        "no legal nonzero single-die Vulkan placement among attempts: " +
        str([(a["ngl"], a["loaded"],
              max((v for k, v in a["selected_die_mem_delta_bytes"].items()
                   if "vram_used" in k), default=0)) for a in attempts]))


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--server", type=Path, required=True)
    ap.add_argument("--model-dir", type=Path, required=True)
    ap.add_argument("--selected-sysfs", default="0000:06:00.0")
    ap.add_argument("--excluded-sysfs", default="0000:09:00.0")
    ap.add_argument("--attempts", type=int, nargs="*", default=None)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    ngls = args.attempts or list(rc.NGL_CANDIDATE_LADDER)
    attempts = []
    for ngl in ngls:
        rec = preflight_ngl(args.server, args.model_dir, ngl,
                            args.selected_sysfs, args.excluded_sysfs)
        attempts.append(rec)
        print(f"ngl={ngl} loaded={rec['loaded']} "
              f"sel_delta={rec['selected_die_mem_delta_bytes']} "
              f"exc_delta={rec['excluded_die_mem_delta_bytes']}")
        if rec["loaded"]:
            sel = max((v for k, v in rec["selected_die_mem_delta_bytes"].items()
                       if "vram_used" in k), default=0)
            if sel > 0:
                break  # smallest found — stop the ladder
    doc = {
        "schema": "inferswarm.r8h.placement/1",
        "campaign": rc.CAMPAIGN_ID,
        "attempts": attempts,
        "selection": select_geometry(attempts),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                        encoding="utf-8")
    print(json.dumps({"selected_ngl": doc["selection"]["selected_ngl"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
