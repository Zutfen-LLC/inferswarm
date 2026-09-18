#!/usr/bin/env python3
"""Issue #216 — V2-D shared host-observation helpers (inferswarm02).

Fail-closed read-only probes: every probe retains a structured receipt
(exact argv, return code, stdout bytes) and a missing receipt or nonzero
exit is an ERROR at collection time — an empty observation is admissible
only against a proven-successful receipt (lesson: read-only observation
collectors are acceptance-bearing producers).

Telemetry fields that the hardware does not expose are reported as
None ("unavailable"), never estimated.
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


def vega_bdfs() -> list[str]:
    """Current Vega BDFs from lspci (sorted)."""
    receipt = run_probe(["lspci", "-nn"])
    rows = [line.split()[0] for line in receipt["stdout"].splitlines()
            if VEGA_ID in line]
    if len(rows) != 2:
        raise HostObservationError(
            f"expected exactly two Vega functions, saw {rows}")
    return sorted(rows)


def bdf_to_drm_card(bdf: str) -> Path:
    """Map a PCI BDF to its drm card sysfs dir (0000:06:00.0 -> cardN)."""
    base = Path("/sys/bus/pci/devices") / bdf
    try:
        links = list((base / "drm").iterdir())
    except OSError as exc:
        raise HostObservationError(f"no drm dir for {bdf}") from exc
    cards = [d for d in links if d.name.startswith("card")
             and d.name[4:].isdigit()]
    if len(cards) != 1:
        raise HostObservationError(
            f"ambiguous drm card for {bdf}: {[c.name for c in cards]}")
    return cards[0]


def aer_counters(bdf: str) -> dict[str, Any]:
    """AER sysfs counters for one endpoint (raw names -> int)."""
    base = Path("/sys/bus/pci/devices") / sysfs_bdf(bdf)
    out: dict[str, Any] = {}
    for name in ("aer_dev_correctable", "aer_dev_nonfatal",
                 "aer_dev_fatal"):
        val = _read(base / name)
        if val is None:
            out[name] = -1  # unavailable marker (never silently zero)
            continue
        fields = {}
        for token in val.split():
            if "=" in token:
                k, v = token.rsplit("=", 1)
                try:
                    fields[k] = int(v)
                except ValueError:
                    fields[k] = -1
        out[name] = fields
    return out


def sysfs_bdf(bdf: str) -> str:
    """Normalize a BDF to the sysfs name (always 0000-domain-prefixed)."""
    bdf = bdf.strip()
    return bdf if bdf.startswith(("0000:", "^[0-9a-f]{4}:")) else f"0000:{bdf}"


def telemetry_sample(bdf: str) -> dict[str, Any]:
    """One hwmon/sysfs telemetry sample for one Vega die.

    Unavailable fields are None (reported as unavailable, never guessed).
    gpu_busy_percent and memory clocks come from amdgpu sysfs; ECC/RAS
    from the ras dir when present.
    """
    dev = Path("/sys/bus/pci/devices") / sysfs_bdf(bdf)
    sample: dict[str, Any] = {
        "monotonic_ns": time.monotonic_ns(),
        "bdf": bdf,
    }
    hwmon: dict[str, Any] = {}
    hwm_dirs = sorted(dev.glob("hwmon/hwmon*"))
    for h in hwm_dirs:
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
        sample["ras_gpu_err_cnt"] = _int_or_none(
            _read(ras / "gpu_err_cnt"))
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


def journal_scan(since_monotonic: float | None = None,
                 cursor: str | None = None) -> dict[str, Any]:
    """Scan the current-boot kernel journal for GPU/PCIe fault classes.

    Returns classified counts + the raw journal text (retained by the
    caller) + the next cursor for incremental scans.
    """
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
    """Host-level liveness/load markers for soak instability detection."""
    load = _read(Path("/proc/loadavg"))
    mem = {}
    for line in (_read(Path("/proc/meminfo")) or "").splitlines():
        if line.startswith(("MemAvailable", "MemFree", "SwapFree")):
            k, v = line.split(":", 1)
            mem[k] = int(v.strip().split()[0]) * 1024
    up = _read(Path("/proc/uptime"))
    return {"monotonic_ns": time.monotonic_ns(), "loadavg": load,
            "meminfo_bytes": mem, "uptime": up}


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
