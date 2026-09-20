#!/usr/bin/env python3
"""Issue #230 — V2-F host-observation helpers (inferswarm02).

Adapted from the accepted #228 host module (same fail-closed receipt
discipline; unavailable telemetry fields are None, never estimated).
Adds the host-facing x1 route counters V2-F needs: PM8533 upstream-port
sysfs traffic counters when the kernel exposes them (they do not exist
on this host per #228 — the absence itself is retained), and NIC/USB
sentinels per arm.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

VEGA_ID = "1002:6864"


class HostObservationError(RuntimeError):
    pass


def run_probe(argv: list[str], timeout: int = 120) -> dict[str, Any]:
    """Run one read-only probe; retain receipt; fail closed on error."""
    try:
        p = subprocess.run(argv, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise HostObservationError(
            f"probe timeout: {' '.join(argv[:4])}...") from exc
    receipt = {
        "argv": argv,
        "returncode": p.returncode,
        "stdout_bytes": len(p.stdout),
        "stderr_bytes": len(p.stderr),
        "stdout": p.stdout.decode("utf-8", "replace"),
        "stderr": p.stderr.decode("utf-8", "replace"),
    }
    if p.returncode != 0:
        raise HostObservationError(
            f"probe failed rc={p.returncode}: {' '.join(argv[:4])}... :: "
            f"{receipt['stderr'][:200]}")
    return receipt


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def sha256_text(text: bytes) -> str:
    import hashlib
    return hashlib.sha256(text).hexdigest()


def sysfs_bdf(bdf: str) -> str:
    bdf = bdf.strip()
    return bdf if bdf.startswith("0000:") else f"0000:{bdf}"


def vega_bdfs() -> list[str]:
    """Current Vega BDFs from lspci (sorted)."""
    receipt = run_probe(["lspci", "-nn"])
    rows = [line.split()[0] for line in receipt["stdout"].splitlines()
            if VEGA_ID in line]
    if len(rows) != 2:
        raise HostObservationError(
            f"expected exactly two Vega functions, saw {rows}")
    return sorted(sysfs_bdf(r) for r in rows)


def link_state(bdf: str) -> dict[str, Any]:
    """Sysfs link state for one BDF (raw labels + widths)."""
    base = Path("/sys/bus/pci/devices") / sysfs_bdf(bdf)
    out: dict[str, Any] = {}
    for field in ("current_link_speed", "current_link_width",
                  "max_link_speed", "max_link_width"):
        out[field] = _read(base / field)
    return out


def aer_counters(bdf: str) -> dict[str, Any]:
    """AER sysfs counters for one BDF (parsed name->int, unavailable=-1)."""
    base = Path("/sys/bus/pci/devices") / sysfs_bdf(bdf)
    out: dict[str, Any] = {}
    for name in ("aer_dev_correctable", "aer_dev_nonfatal",
                 "aer_dev_fatal"):
        val = _read(base / name)
        if val is None:
            out[name] = -1  # unavailable marker (never silently zero)
            continue
        fields: dict[str, int] = {}
        for token in val.split():
            if "=" in token:
                k, v = token.rsplit("=", 1)
                try:
                    fields[k] = int(v)
                except ValueError:
                    fields[k] = -1
        out[name] = fields
    return out


def health_snapshot(bdfs: tuple[str, ...] | list[str]) -> dict[str, Any]:
    """One health snapshot: monotonic time + per-BDF AER + link state."""
    return {
        "monotonic_ns": time.monotonic_ns(),
        "aer": {bdf: aer_counters(bdf) for bdf in bdfs},
        "link": {bdf: link_state(bdf) for bdf in bdfs},
    }


def aer_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Per-BDF per-counter deltas (negative = counter reset, retained)."""
    out: dict[str, Any] = {}
    for bdf in before.get("aer", {}):
        row = {}
        for cls in ("aer_dev_correctable", "aer_dev_nonfatal",
                    "aer_dev_fatal"):
            b = before["aer"][bdf].get(cls)
            a = after["aer"][bdf].get(cls)
            if isinstance(b, dict) and isinstance(a, dict):
                row[cls] = {k: a.get(k, 0) - b.get(k, 0) for k in
                            sorted(set(b) | set(a))}
            else:
                row[cls] = None
        out[bdf] = row
    return out


def telemetry_sample(bdf: str) -> dict[str, Any]:
    """One amdgpu telemetry sample for one Vega die (None = unavailable)."""
    dev = Path("/sys/bus/pci/devices") / sysfs_bdf(bdf)
    sample: dict[str, Any] = {
        "monotonic_ns": time.monotonic_ns(),
        "bdf": bdf,
    }
    hwmon: dict[str, Any] = {}
    for h in sorted(dev.glob("hwmon/hwmon*")):
        name = _read(h / "name")
        entries: dict[str, Any] = {"name": name}
        for f in sorted(h.iterdir()):
            if f.name in ("name", "uevent"):
                continue
            val = _read(f)
            if val is not None and re.fullmatch(r"-?\d+", val):
                entries[f.name] = int(val)
            elif val is not None and len(val) <= 64:
                entries[f.name] = val
        hwmon[h.name] = entries
    sample["hwmon"] = hwmon
    sample["gpu_busy_percent"] = _int_or_none(_read(dev / "gpu_busy_percent"))
    sample["mem_busy_percent"] = _int_or_none(_read(dev / "mem_busy_percent"))
    sample["vram_used_bytes"] = _int_or_none(_read(dev / "mem_info_vram_used"))
    sample["vram_total_bytes"] = _int_or_none(
        _read(dev / "mem_info_vram_total"))
    sample["current_link_speed"] = _read(dev / "current_link_speed")
    sample["current_link_width"] = _read(dev / "current_link_width")
    ras = dev / "ras"
    if ras.is_dir():
        sample["ras_gpu_err_cnt"] = _int_or_none(_read(ras / "gpu_err_cnt"))
    else:
        sample["ras_gpu_err_cnt"] = None
    return sample


def _int_or_none(val: str | None) -> int | None:
    if val is None:
        return None
    try:
        return int(val)
    except ValueError:
        return None


def upstream_traffic_snapshot() -> dict[str, Any]:
    """Route-instrumentation snapshot for the PM8533 upstream path.

    The kernel exposes no PM8533 per-port transaction/byte counters on
    this host (#228 established; re-verified at collection). What IS
    exposed and retained per arm: per-BDF PCIe link state (speed/width
    at every hop of root->switch->die), and the amdgpu VRAM/busy
    counters of both dies. The route proof therefore rests on the
    measured-behavior combination the issue authorizes — never on these
    sysfs counters alone, and never on nominal Gen3 arithmetic.
    """
    return {
        "monotonic_ns": time.monotonic_ns(),
        "link": {bdf: link_state(bdf) for bdf in (
            "0000:00:1d.0", "0000:02:00.0", "0000:03:00.0",
            "0000:03:01.0", "0000:06:00.0", "0000:09:00.0")},
        "vram_used": {
            "0000:06:00.0": _int_or_none(_read(Path(
                "/sys/bus/pci/devices/0000:06:00.0/mem_info_vram_used"))),
            "0000:09:00.0": _int_or_none(_read(Path(
                "/sys/bus/pci/devices/0000:09:00.0/mem_info_vram_used"))),
        },
    }


def journal_scan(cursor: str | None = None) -> dict[str, Any]:
    """Scan the current-boot kernel journal for GPU/PCIe fault classes."""
    argv = ["journalctl", "-b", "-k", "--no-pager",
            "-g", "amdgpu|AER|pcieport|DMAR|dmar|[Rr]eset|[Hh]ang|ECC"]
    if cursor:
        argv += ["--after-cursor", cursor]
    receipt = run_probe(argv, timeout=300)
    text = receipt["stdout"]
    cursor_argv = ["journalctl", "-b", "-k", "--no-pager", "-n", "1",
                   "-o", "json"]
    creceipt = run_probe(cursor_argv, timeout=60)
    next_cursor = None
    try:
        next_cursor = json.loads(creceipt["stdout"]).get("__CURSOR")
    except (json.JSONDecodeError, AttributeError):
        next_cursor = None

    def count(pattern: str) -> int:
        return len(re.findall(pattern, text, re.I))

    return {
        "argv": argv,
        "text": text,
        "next_cursor": next_cursor,
        "counts": {
            "fatal_aer": count(r"severity\s*=\s*(fatal|uncorrectable|uncorrected)")
                       + count(r"AER:\s*(?:Multiple\s+)?Uncorrected"),
            "amdgpu_reset": count(r"amdgpu.*reset|resetting amdgpu|GPU reset"),
            "amdgpu_timeout": count(r"amdgpu.*timeout|GPU hang|ring timeout"),
            "amdgpu_failure": count(r"amdgpu.*(fail|error)"),
            "dmar_fault": count(r"DMAR:[^\n]*(fault|error)"),
            "thermal": count(r"thermal.*(shutdown|trip|critical)|overtemperature"),
        },
    }


def boot_id() -> str:
    val = _read(Path("/proc/sys/kernel/random/boot_id"))
    if not val:
        raise HostObservationError("no boot_id")
    return val


def host_health() -> dict[str, Any]:
    load = _read(Path("/proc/loadavg"))
    mem: dict[str, int] = {}
    for line in (_read(Path("/proc/meminfo")) or "").splitlines():
        if line.startswith(("MemAvailable", "MemFree", "SwapFree")):
            k, v = line.split(":", 1)
            mem[k] = int(v.strip().split()[0]) * 1024
    up = _read(Path("/proc/uptime"))
    return {"monotonic_ns": time.monotonic_ns(), "loadavg": load,
            "meminfo_bytes": mem, "uptime": up}


def nic_sentinel() -> dict[str, Any]:
    """Host-facing NIC byte counters (sentinel for unexpected host
    traffic during a peer arm; deltas near zero corroborate locality)."""
    out: dict[str, Any] = {"monotonic_ns": time.monotonic_ns()}
    for iface in ("enp1s0", "enp2s0", "eth0"):
        base = Path(f"/sys/class/net/{iface}/statistics")
        if base.is_dir():
            out[iface] = {
                "rx_bytes": _int_or_none(_read(base / "rx_bytes")),
                "tx_bytes": _int_or_none(_read(base / "tx_bytes")),
            }
    return out


def durable_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    dfd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)
