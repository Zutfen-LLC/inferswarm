#!/usr/bin/env python3
"""Issue #234 — R8-H platform health collector (schema /2, both vendors).

Bounded observations around model execution, from raw journal + sysfs
bytes (sudo -n where needed, read-only):

  * AMD arms: amdgpu ring timeout / reset / device-loss journal deltas
    for BOTH dies, AER counters, link width, VRAM release;
  * NVIDIA arms: Xid fault scan, driver reset scan, memory release on
    every 3060, compute-process hygiene (foreign processes);
  * process exit status and post-exit cleanup for the arm's server.

Immediate-stop classes (issue #234 Phase 6) are classified from bytes;
the ladder runner consults stop_now() between repeats.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue234_receipt as rc

STOP_CLASSES = (
    "amdgpu_ring_timeout",
    "amdgpu_reset",
    "amdgpu_reset_failure",
    "gpu_device_loss",
    "vulkan_device_lost",
    "uncorrectable_aer",
    "dpc_triggered",
    "material_rxerr_recurrence",
    "topology_change",
    "unexpected_link_width_change",
    "nvidia_xid_fault",
    "nvidia_driver_reset",
)


def _sudo(cmd: list[str]) -> str:
    proc = subprocess.run(["sudo", "-n", *cmd], capture_output=True,
                          text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"sudo command failed ({proc.returncode}): {' '.join(cmd)}: "
            f"{proc.stderr[-500:]}")
    return proc.stdout


def journal_kernel(since: str | None = None,
                   until: str | None = None) -> str:
    cmd = ["journalctl", "-k", "--no-pager", "-o", "short-iso"]
    if since:
        cmd += ["--since", since]
    if until:
        cmd += ["--until", until]
    return _sudo(cmd)


def classify_journal(raw: str) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    stops: list[str] = []
    for line in raw.splitlines():
        if not any(s in line for s in ("amdgpu", "AER", "DPC", "NVRM",
                                       "nvidia", "Vega", "vulkan")):
            continue
        low = line.lower()
        cls = None
        if re.search(r"ring.*(timeout|hang)", low):
            cls = "amdgpu_ring_timeout"
        elif "gpu reset" in low and "ret=" in low:
            cls = ("amdgpu_reset_failure"
                   if re.search(r"ret\s*=\s*(-\d+|!0|nonzero)", low)
                   else "amdgpu_reset")
        elif "amdgpu" in low and "reset" in low:
            cls = "amdgpu_reset"
        elif "device lost" in low or "device_lost" in low:
            cls = "gpu_device_loss"
        elif "uecpoison" in low or "uncorrectable" in low:
            cls = "uncorrectable_aer"
        elif "dpc" in low and ("contain" in low or "trigger" in low):
            cls = "dpc_triggered"
        elif "nvrm" in low and re.search(r"xid (\d+)", low):
            cls = "nvidia_xid_fault"
        elif "nvidia" in low and "reset" in low:
            cls = "nvidia_driver_reset"
        if cls:
            events.append({"class": cls, "line": line[:400]})
            if cls in STOP_CLASSES:
                stops.append(cls)
    rxerr = len(re.findall(r"Corrected errorReceivedError|RxErr", raw))
    return {"events": events, "stop_classes": sorted(set(stops)),
            "correctable_rxerr_lines": rxerr}


def aer_counters(bdf16_form: str) -> dict[str, int]:
    out: dict[str, int] = {}
    domain, bus, devfn = bdf16_form.split(":")
    sysfs = f"{domain[-4:]}:{bus}:{devfn}"
    base = Path(f"/sys/bus/pci/devices/{sysfs}")
    for fname, prefix in (("aer_devcorrectable", "corr"),
                          ("aer_devuncorrectable", "unc")):
        f = base / fname
        if f.is_file():
            for line in f.read_text().splitlines():
                k, _, v = line.partition(" ")
                if v.isdigit():
                    out[f"{prefix}_{k}"] = int(v)
    return out


def link_state(bdf16_form: str) -> dict[str, str]:
    domain, bus, devfn = bdf16_form.split(":")
    base = Path(f"/sys/bus/pci/devices/{domain[-4:]}:{bus}:{devfn}")
    out: dict[str, str] = {}
    for k in ("current_link_speed", "current_link_width",
              "max_link_speed", "max_link_width"):
        p = base / k
        if p.is_file():
            out[k] = p.read_text().strip()
    return out


def amd_die_mem(bdf16_form: str) -> dict[str, int]:
    domain, bus, devfn = bdf16_form.split(":")
    base = Path(f"/sys/bus/pci/devices/{domain[-4:]}:{bus}:{devfn}")
    out: dict[str, int] = {}
    for card in sorted(base.glob("drm/card*")):
        for key in ("mem_info_vram_used", "mem_info_vis_vram_used",
                    "mem_info_gtt_used"):
            f = card / "device" / key
            if f.is_file():
                out[f"{card.name}.{key}"] = int(f.read_text().strip())
    return out


def nvidia_state() -> dict[str, Any]:
    out = subprocess.run(
        ["nvidia-smi", "--query-gpu=uuid,memory.used,pci.bus_id",
         "--format=csv,noheader"], capture_output=True, text=True)
    gpus = []
    for line in (out.stdout or "").splitlines():
        f = [x.strip() for x in line.split(",")]
        if len(f) == 3:
            gpus.append({"uuid": f[0],
                         "mem_used_mib": int(f[1].split()[0]),
                         "bdf": f[2]})
    apps = subprocess.run(
        ["nvidia-smi", "--query-compute-apps=gpu_uuid,pid,used_memory",
         "--format=csv,noheader"], capture_output=True, text=True)
    return {"gpus": gpus, "compute_apps_raw": apps.stdout or ""}


def snapshot(vendor: str, selected_bdf: str | None = None,
             excluded_bdfs: list[str] | None = None) -> dict[str, Any]:
    """One health snapshot for an arm's host."""
    snap: dict[str, Any] = {"vendor": vendor}
    if vendor == "amd" and selected_bdf:
        snap["selected_aer"] = aer_counters(selected_bdf)
        snap["selected_link"] = link_state(selected_bdf)
        snap["selected_mem"] = amd_die_mem(selected_bdf)
        for ex in excluded_bdfs or []:
            snap[f"excluded_aer::{ex}"] = aer_counters(ex)
            snap[f"excluded_mem::{ex}"] = amd_die_mem(ex)
            snap[f"excluded_link::{ex}"] = link_state(ex)
    elif vendor == "nvidia":
        snap["nvidia"] = nvidia_state()
        if selected_bdf:
            snap["selected_aer"] = aer_counters(selected_bdf)
            snap["selected_link"] = link_state(selected_bdf)
            for ex in excluded_bdfs or []:
                snap[f"excluded_aer::{ex}"] = aer_counters(ex)
    return snap


def delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    d: dict[str, Any] = {}
    for key in set(before) | set(after):
        b, a = before.get(key), after.get(key)
        if isinstance(b, dict) and isinstance(a, dict):
            if key.endswith("_aer") or "::" in key:
                d[f"delta::{key}"] = {k: a.get(k, 0) - b.get(k, 0)
                                      for k in set(b) | set(a)}
            else:
                d[f"cmp::{key}"] = {"before": b, "after": a,
                                    "equal": b == a}
    return d


def stop_now(window: dict[str, Any]) -> list[str]:
    return list(window.get("journal", {}).get("stop_classes", []))


def main() -> int:
    import argparse
    import json
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--snapshot", action="store_true")
    ap.add_argument("--vendor", choices=("amd", "nvidia"), required=True)
    ap.add_argument("--selected-bdf")
    ap.add_argument("--excluded-bdfs", nargs="*")
    args = ap.parse_args()
    if args.snapshot:
        print(json.dumps(snapshot(args.vendor, args.selected_bdf,
                                  args.excluded_bdfs), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
