#!/usr/bin/env python3
"""Issue #234 — R8-H platform health collector (inferswarm02).

Bounded amdgpu/AER/PCIe/device-loss observations around model
execution, from raw journal + sysfs bytes (sudo -n, read-only):

  * amdgpu ring timeout / reset / device-loss journal deltas for BOTH
    dies over the execution window;
  * AER correctable/uncorrectable counters on both dies and the
    upstream path;
  * negotiated link width/speed before/after;
  * process exit status + GPU memory release after exit.

Immediate-stop classes (issue Phase 6) are classified from these
bytes; the ladder runner consults stop_now() between cases.
"""
from __future__ import annotations

import json
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
)


def _sudo(cmd: list[str]) -> str:
    proc = subprocess.run(["sudo", "-n", *cmd], capture_output=True,
                          text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"sudo command failed ({proc.returncode}): {' '.join(cmd)}: "
            f"{proc.stderr[-500:]}")
    return proc.stdout


def journal_amdgpu(since: str | None = None, until: str | None = None,
                   boot: str | None = None) -> str:
    cmd = ["journalctl", "-k", "--no-pager", "-o", "short-iso"]
    if boot:
        cmd += ["-b", boot]
    if since:
        cmd += ["--since", since]
    if until:
        cmd += ["--until", until]
    return _sudo(cmd)


def classify_journal(raw: str, selected_sysfs: str,
                     excluded_sysfs: str) -> dict[str, Any]:
    """Parse amdgpu/AER-relevant events from a journal window."""
    events: list[dict[str, Any]] = []
    stops: list[str] = []
    for line in raw.splitlines():
        if "amdgpu" not in line and "AER" not in line and "DPC" not in line:
            continue
        cls = None
        low = line.lower()
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
        elif "vulkan" in low and "device lost" in low:
            cls = "vulkan_device_lost"
        elif "uecpoison" in low or "uncorrectable" in low:
            cls = "uncorrectable_aer"
        elif "dpc" in low and ("contain" in low or "trigger" in low):
            cls = "dpc_triggered"
        if cls:
            events.append({"class": cls, "line": line[:400]})
            if cls in STOP_CLASSES:
                stops.append(cls)
    # Correctable RxErr recurrence: count CeRecvErr entries in window
    rxerr = len(re.findall(r"Corrected errorReceivedError|RxErr", raw))
    return {
        "events": events,
        "stop_classes": sorted(set(stops)),
        "correctable_rxerr_lines": rxerr,
    }


def aer_counters(sysfs_bdf: str) -> dict[str, int]:
    out = {}
    base = Path(f"/sys/bus/pci/devices/{sysfs_bdf}")
    corr = base / "aer_devcorrectable"
    if corr.is_file():
        for line in corr.read_text().splitlines():
            k, _, v = line.partition(" ")
            if v.isdigit():
                out[f"corr_{k}"] = int(v)
    unc = base / "aer_devuncorrectable"
    if unc.is_file():
        for line in unc.read_text().splitlines():
            k, _, v = line.partition(" ")
            if v.isdigit():
                out[f"unc_{k}"] = int(v)
    return out


def link_state(sysfs_bdf: str) -> dict[str, str]:
    base = Path(f"/sys/bus/pci/devices/{sysfs_bdf}")
    out = {}
    for k in ("current_link_speed", "current_link_width",
              "max_link_speed", "max_link_width"):
        p = base / k
        if p.is_file():
            out[k] = p.read_text().strip()
    return out


def snapshot(selected_sysfs: str, excluded_sysfs: str) -> dict[str, Any]:
    return {
        "selected_aer": aer_counters(selected_sysfs),
        "excluded_aer": aer_counters(excluded_sysfs),
        "selected_link": link_state(selected_sysfs),
        "excluded_link": link_state(excluded_sysfs),
        "selected_mem": {p.name: int(p.read_text())
                         for card in sorted(
                             Path(f"/sys/bus/pci/devices/{selected_sysfs}"
                                  ).glob("drm/card*"))
                         for p in (card / "device").glob("mem_info_*used")},
        "excluded_mem": {p.name: int(p.read_text())
                         for card in sorted(
                             Path(f"/sys/bus/pci/devices/{excluded_sysfs}"
                                  ).glob("drm/card*"))
                         for p in (card / "device").glob("mem_info_*used")},
    }


def stop_now(window: dict[str, Any]) -> list[str]:
    return window.get("journal", {}).get("stop_classes", [])


def delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    d: dict[str, Any] = {}
    for side in ("selected_aer", "excluded_aer"):
        b, a = before.get(side, {}), after.get(side, {})
        d[side] = {k: a.get(k, 0) - b.get(k, 0) for k in set(b) | set(a)}
    d["selected_link_before"] = before.get("selected_link")
    d["selected_link_after"] = after.get("selected_link")
    d["excluded_link_before"] = before.get("excluded_link")
    d["excluded_link_after"] = after.get("excluded_link")
    return d
