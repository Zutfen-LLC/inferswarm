#!/usr/bin/env python3
"""Issue #234 — R8-H fresh host/device census collector (schema /2).

Runs on inferswarm01 (RTX 3060 pair) and inferswarm02 (V340L pair) as
hermes with sudo -n for read-only privileged reads. Derives CURRENT-boot
identity from raw bytes only: lspci, sysfs, vulkaninfo, nvidia-smi.

Bindings (never ordinal assumptions):
  * AMD/RADV Vulkan deviceUUID encodes the PCI BDF (V2-E #228 join);
  * NVIDIA Vulkan deviceUUID == nvidia-smi GPU UUID (driver contract);
    both sides normalized to 16-char domain-prefixed BDFs;
  * CUDA_VISIBLE_DEVICES maps by nvidia-smi index/UUID, never by
    enumeration order alone.
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


class CensusError(RuntimeError):
    """A census read failed; no identity may be assumed."""


def _run(cmd: list[str], sudo: bool = False, env: dict | None = None) -> str:
    import os
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    full = (["sudo", "-n"] if sudo else []) + cmd
    proc = subprocess.run(full, capture_output=True, text=True,
                          env=full_env)
    if proc.returncode != 0:
        raise CensusError(
            f"command failed ({proc.returncode}): {' '.join(full)}\n"
            f"stderr: {proc.stderr[-2000:]}")
    return proc.stdout


def bdf16(short: str) -> str:
    """Normalize any BDF spelling to 16-char domain-prefixed form."""
    s = short.strip().lower()
    parts = s.split(":")
    if len(parts) == 3:
        domain, bus, devfn = parts
        if len(domain) == 8:
            return s
        if len(domain) == 4:
            return f"{int(domain, 16):08x}:{bus}:{devfn}"
    if len(parts) == 2:
        return f"00000000:{parts[0]}:{parts[1]}"
    raise CensusError(f"unparseable BDF: {short!r}")


def sysfs_name(bdf16_form: str) -> str:
    """16-char 00000000:06:00.0 -> sysfs 0000:06:00.0 (4-hex domain)."""
    domain, bus, devfn = bdf16_form.split(":")
    return f"{domain[-4:]}:{bus}:{devfn}"


def uuid_bdf(device_uuid: str) -> str:
    """RADV deviceUUID -> BDF (first 8 bytes encode domain/bus/dev/fn)."""
    m = re.fullmatch(
        r"([0-9a-f]{8})-([0-9a-f]{4})-([0-9a-f]{4})-([0-9a-f]{4})-([0-9a-f]{12})",
        device_uuid.strip().lower())
    if not m:
        raise CensusError(f"unparseable deviceUUID: {device_uuid!r}")
    blob = (m.group(1) + m.group(2) + m.group(3) + m.group(4) + m.group(5))
    domain = blob[0:8]
    bus = blob[8:10]
    dev = blob[10:12]
    fn = blob[12:14]
    return f"{domain}:{bus}:{dev}.{int(fn, 16) & 7}"


# -----------------------------------------------------------------------
# NVIDIA
# -----------------------------------------------------------------------

def collect_nvidia() -> dict[str, Any]:
    """nvidia-smi CSV census (identity, topology, foreign processes)."""
    q = ("index,uuid,name,pci.bus_id,memory.total,memory.used,"
         "driver_version,compute_mode")
    out = _run(["nvidia-smi", f"--query-gpu={q}", "--format=csv,noheader"])
    gpus = []
    for line in out.splitlines():
        f = [x.strip() for x in line.split(",")]
        if len(f) < 8:
            continue
        gpus.append({
            "smi_index": int(f[0]),
            "uuid": f[1],
            "name": f[2],
            "bdf": bdf16(f[3]),
            "memory_total_mib": int(f[4].split()[0]),
            "memory_used_mib": int(f[5].split()[0]),
            "driver_version": f[6],
            "compute_mode": f[7],
        })
    topo = _run(["nvidia-smi", "topo", "-m"])
    apps = _run(["nvidia-smi", "--query-compute-apps=gpu_uuid,pid,"
                 "process_name,used_memory",
                 "--format=csv,noheader"])
    return {"gpus": gpus, "topo_matrix": topo, "compute_apps_raw": apps,
            "kernel_module": _nvidia_kernel_module()}


def _nvidia_kernel_module() -> str | None:
    p = Path("/proc/driver/nvidia/version")
    if not p.is_file():
        return None
    return p.read_text().splitlines()[0]


# -----------------------------------------------------------------------
# Vulkan
# -----------------------------------------------------------------------

def collect_vulkan(icd_filter: str | None = None) -> dict[str, Any]:
    """vulkaninfo census restricted to one ICD when asked."""
    env = {"VK_ICD_FILENAMES": icd_filter} if icd_filter else None
    raw = _run(["vulkaninfo"], env=env)
    gpus: dict[str, dict[str, Any]] = {}
    blocks = re.split(r"^GPU(\d+):\s*$", raw, flags=re.M)
    it = iter(blocks[1:])
    for gpu_id, body in zip(it, it):
        info: dict[str, Any] = {"gpu_index": int(gpu_id)}

        def g(pat: str) -> Any:
            m = re.search(pat, body, flags=re.M)
            return m.group(1).strip() if m else None

        info["name"] = g(r"deviceName\s+=\s+(.*)")
        info["deviceUUID"] = g(r"deviceUUID\s+=\s+([0-9a-f-]+)")
        info["driverUUID"] = g(r"driverUUID\s+=\s+([0-9a-f-]+)")
        info["apiVersion"] = g(r"apiVersion\s+=\s+([0-9.]+)")
        info["driverVersion"] = g(r"driverVersion\s+=\s+([0-9.]+)")
        info["vendorID"] = g(r"vendorID\s+=\s+(0x[0-9a-f]+)")
        info["deviceID"] = g(r"deviceID\s+=\s+(0x[0-9a-f]+)")
        info["deviceType"] = g(r"deviceType\s+=\s+(\w+)")
        heaps = []
        # vulkaninfo layout: memoryHeaps[N]: size = <bytes> ... flags:
        # ... MEMORY_HEAP_DEVICE_LOCAL_BIT (possibly multiline)
        heap_blocks = re.split(r"memoryHeaps\[\d+\]:", body)
        for hb in heap_blocks[1:]:
            ms = re.search(r"size\s+=\s+(\d+)", hb)
            if not ms:
                continue
            device_local = "MEMORY_HEAP_DEVICE_LOCAL_BIT" in hb
            heaps.append({"size": int(ms.group(1)),
                          "device_local": device_local})
        info["device_local_heaps"] = [h for h in heaps if h["device_local"]]
        info["all_heaps"] = heaps
        gpus[f"gpu{gpu_id}"] = info
    return {"raw_length": len(raw), "gpus": gpus, "raw": raw,
            "icd_filter": icd_filter}


# -----------------------------------------------------------------------
# sysfs per-device detail
# -----------------------------------------------------------------------

def collect_sysfs(bdf: str) -> dict[str, Any]:
    p = None
    for cand in (bdf, sysfs_name(bdf)):
        q = Path(f"/sys/bus/pci/devices/{cand}")
        if q.is_dir():
            p = q
            break
    if p is None:
        raise CensusError(f"sysfs device missing: {bdf}")
    out: dict[str, Any] = {"bdf": bdf}
    for attr in ("vendor", "device", "subsystem_vendor", "subsystem_device",
                 "revision", "class", "numa_node", "dma_mask_bits"):
        f = p / attr
        if f.is_file():
            out[attr] = f.read_text().strip()
    drv = p / "driver"
    out["driver"] = drv.resolve().name if drv.exists() else None
    drm: dict[str, Any] = {}
    for card in sorted(p.glob("drm/card*")):
        info: dict[str, Any] = {"card": card.name}
        for key in ("mem_info_vram_total", "mem_info_vram_used",
                    "mem_info_gtt_used", "mem_info_vis_vram_used"):
            f = card / "device" / key
            if f.is_file():
                info[key] = int(f.read_text().strip())
        drm[card.name] = info
    out["drm"] = drm
    out["current_link_speed"] = (p / "current_link_speed").read_text().strip() \
        if (p / "current_link_speed").is_file() else None
    out["current_link_width"] = (p / "current_link_width").read_text().strip() \
        if (p / "current_link_width").is_file() else None
    out["max_link_width"] = (p / "max_link_width").read_text().strip() \
        if (p / "max_link_width").is_file() else None
    for aer, key in (("aer_devcorrectable", "aer_correctable_raw"),
                     ("aer_devuncorrectable", "aer_uncorrectable_raw")):
        f = p / aer
        if f.is_file():
            out[key] = f.read_text().strip()
    return out


def collect_host() -> dict[str, Any]:
    boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    return {
        "hostname": _run(["hostname"]).strip(),
        "boot_id": boot_id,
        "uname": _run(["uname", "-a"]).strip(),
        "kernel_cmdline": Path("/proc/cmdline").read_text().strip(),
        "vulkan_loader": _run(["dpkg-query", "-W", "-f=${Version}",
                               "libvulkan1"]),
        "vulkan_icds": sorted(
            p.name for p in Path("/usr/share/vulkan/icd.d").iterdir()),
    }


# -----------------------------------------------------------------------
# Composite censuses
# -----------------------------------------------------------------------

def census_nvidia_host() -> dict[str, Any]:
    """inferswarm01: join nvidia-smi UUID/BDF <-> NVIDIA Vulkan UUID."""
    host = collect_host()
    nv = collect_nvidia()
    vk_all = collect_vulkan()  # unrestricted: both ICDs may enumerate
    nvidia_vk = {}
    for key, info in vk_all["gpus"].items():
        if info.get("vendorID") == "0x10de":
            nvidia_vk[key] = info
    # UUID join: nvidia-smi GPU-<uuid> vs Vulkan deviceUUID (no dashes)
    joins = []
    for g in nv["gpus"]:
        smi_u = g["uuid"].removeprefix("GPU-").replace("-", "").lower()
        match = None
        for key, info in nvidia_vk.items():
            vk_u = (info.get("deviceUUID") or "").replace("-", "").lower()
            if vk_u == smi_u:
                match = key
                break
        joins.append({
            "smi_index": g["smi_index"],
            "nvidia_uuid": g["uuid"],
            "bdf_smi": g["bdf"],
            "name": g["name"],
            "vulkan_key": match,
            "vulkan_deviceUUID": nvidia_vk[match]["deviceUUID"] if match else None,
            "heap_mib": (max((h["size"] for h in
                              nvidia_vk[match]["device_local_heaps"]),
                             default=0) // (1024 * 1024)) if match else None,
        })
    r3060 = [j for j in joins if "3060" in j["name"]]
    if len(r3060) != 2:
        raise CensusError(f"expected exactly 2 RTX 3060, found {len(r3060)}")
    for j in r3060:
        if j["vulkan_key"] is None:
            raise CensusError(
                f"3060 {j['nvidia_uuid']} has no NVIDIA Vulkan device join")
        j["sysfs"] = collect_sysfs(j["bdf_smi"])
    return {
        "schema": "inferswarm.r8h.census-nvidia/2",
        "campaign": rc.CAMPAIGN_ID,
        "host": host,
        "nvidia": nv,
        "rtx3060": r3060,
        "raw": {"vulkaninfo_all": vk_all["raw"]},
    }


def census_amd_host() -> dict[str, Any]:
    """inferswarm02: join RADV deviceUUID <-> BDF for both V340L dies."""
    host = collect_host()
    vk = collect_vulkan()
    bindings = []
    for key, info in vk["gpus"].items():
        entry = dict(info)
        entry["vulkan_key"] = key
        if info.get("vendorID") == "0x1002" and "RADV" in (info.get("name") or ""):
            entry["bdf"] = uuid_bdf(info["deviceUUID"])
        bindings.append(entry)
    v340l = [b for b in bindings if b.get("vendorID") == "0x1002"
             and "V340" in (b.get("name") or "")]
    if len(v340l) != 2:
        raise CensusError(
            f"expected exactly 2 V340L Vulkan devices, found {len(v340l)}: "
            f"{[b.get('name') for b in bindings]}")
    dies = {}
    for b in v340l:
        b["sysfs"] = collect_sysfs(b["bdf"])
        dies[b["bdf"]] = b
    return {
        "schema": "inferswarm.r8h.census-amd/2",
        "campaign": rc.CAMPAIGN_ID,
        "host": host,
        "vulkan_devices": bindings,
        "v340l_dies": dies,
        "raw": {"vulkaninfo": vk["raw"]},
    }


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--kind", choices=("nvidia", "amd"), required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    doc = census_nvidia_host() if args.kind == "nvidia" else census_amd_host()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                        encoding="utf-8")
    print(json.dumps({
        "boot_id": doc["host"]["boot_id"],
        "kind": args.kind,
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
