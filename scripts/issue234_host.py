#!/usr/bin/env python3
"""Issue #234 — R8-H fresh host/device census collector (runs on
inferswarm02 as hermes with sudo -n for read-only privileged reads).

Derives the CURRENT-boot identity of both V340L dies from raw bytes
only: lspci, sysfs, vulkaninfo. Binds each Vulkan physical device to a
PCI BDF through the RADV deviceUUID encoding (V2-E #228 established the
UUID->BDF join; both sides use the 16-char domain-prefixed BDF form).

The census never assumes historical BDFs: after V2-G's physical
intervention the current chain is re-derived from live lspci bytes and
bound by bus chaining from the CPU root port.
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


def _run(cmd: list[str], sudo: bool = False) -> str:
    full = (["sudo", "-n"] if sudo else []) + cmd
    proc = subprocess.run(full, capture_output=True, text=True)
    if proc.returncode != 0:
        raise CensusError(
            f"command failed ({proc.returncode}): {' '.join(full)}\n"
            f"stderr: {proc.stderr[-2000:]}")
    return proc.stdout


def bdf16(short: str) -> str:
    """Normalize any BDF spelling to the 16-char domain-prefixed form
    (00000000:06:00.0). nvidia/amdgpu tooling and the RADV UUID both
    use this form; a 12-char fixture silently fails equality."""
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


def uuid_bdf(device_uuid: str) -> str:
    """RADV encodes the BDF in the first 8 bytes of deviceUUID:
    00000000-0600-0000-... => domain 00000000, bus 06, dev 00, fn 0."""
    m = re.fullmatch(
        r"([0-9a-f]{8})-([0-9a-f]{4})-([0-9a-f]{4})-([0-9a-f]{4})-([0-9a-f]{12})",
        device_uuid.strip().lower())
    if not m:
        raise CensusError(f"unparseable deviceUUID: {device_uuid!r}")
    blob = (m.group(1) + m.group(2) + m.group(3) + m.group(4) + m.group(5))
    # RADV layout: bytes = domain(4) bus(1) dev(1) fn(1) padded
    domain = blob[0:8]
    bus = blob[8:10]
    dev = blob[10:12]
    fn = blob[12:14]
    return f"{domain}:{bus}:{dev}.{int(fn, 16) & 7}"


def collect_lspci() -> dict[str, Any]:
    raw = _run(["lspci", "-D", "-nn", "-vv", "-d", "1002::0300"])
    display_raw = _run(["lspci", "-D", "-nn"])
    bridges = {}
    dies = {}
    for line in display_raw.splitlines():
        mm = re.match(r"^([0-9a-f:.]+) (.*)$", line)
        if not mm:
            continue
        bdf, desc = mm.group(1), mm.group(2)
        if "Vega 10" in desc:
            dies[bdf16(bdf)] = desc
        if "PCI bridge" in desc and "AMD" in desc:
            bridges[bdf16(bdf)] = desc
    # Root-port ancestry from verbose tree output
    tree = _run(["lspci", "-D", "-t"])
    return {
        "dies": dies,
        "amd_bridges": bridges,
        "tree": tree,
        "display_controllers_verbose": raw,
    }


def collect_sysfs(die_bdf: str) -> dict[str, Any]:
    # sysfs names are the 12-char 4-hex-domain form (0000:06:00.0);
    # canonicalize to the 16-char form (00000000:06:00.0) for receipts
    # and try both spellings for the lookup.
    # BDF = domain:bus:dev.fn (2 colons, e.g. 00000000:06:00.0) in the
    # 16-char form, or bus:dev.fn (1 colon, e.g. 06:00.0) in the short
    # form; sysfs uses the 4-hex-domain 13-char form (0000:06:00.0).
    # Canonical 16-char form: 00000000:06:00.0 (8-hex domain). sysfs
    # names use a 4-hex domain: 0000:06:00.0. Map between them.
    candidates = [die_bdf]
    parts = die_bdf.split(":")
    if len(parts) == 3:
        domain, bus, devfn = parts
        candidates.append(f"{domain[-4:]}:{bus}:{devfn}")   # 4-hex domain
        candidates.append(f"{bus}:{devfn}")                  # no domain
    elif len(parts) == 2:
        candidates.append(f"0000:{die_bdf}")                 # 4-hex domain
        candidates.append(f"00000000:{die_bdf}")             # 8-hex domain
    p = None
    for c in candidates:
        q = Path(f"/sys/bus/pci/devices/{c}")
        if q.is_dir():
            p = q
            break
    if p is None:
        raise CensusError(f"sysfs device missing: {die_bdf}")
    out: dict[str, Any] = {"bdf": die_bdf}
    for attr in ("vendor", "device", "subsystem_vendor", "subsystem_device",
                 "revision", "class", "modalias", "numa_node", "dma_mask_bits"):
        f = p / attr
        if f.is_file():
            out[attr] = f.read_text().strip()
    # driver identity
    drv = p / "driver"
    out["driver"] = drv.resolve().name if drv.exists() else None
    # DRM identity: card*/device minor + GPU device UUID if exposed
    drm: dict[str, Any] = {}
    for card in sorted(p.glob("drm/card*")):
        info: dict[str, Any] = {"card": card.name}
        dev = card / "device"
        if dev.exists():
            info["device"] = dev.resolve().name if dev.is_symlink() else dev.read_text().strip()
        gpu_id = card / "gpu_id"
        if gpu_id.is_file():
            info["gpu_id"] = gpu_id.read_text().strip()
        unique = card / "device" / "unique"
        if unique.is_file():
            info["unique"] = unique.read_text().strip()
        # amdgpu memory info
        mem = card / "device" / "mem_info_vram_total"
        if mem.is_file():
            info["mem_info_vram_total"] = int(mem.read_text().strip())
        drm[card.name] = info
    out["drm"] = drm
    # resource sizes (BARs)
    out["resource_sizes"] = {}
    for i in range(0, 16):
        f = p / f"resource{int(i*1):d}" if False else p / f"resource"
        break
    res = (p / "resource").read_text().splitlines()
    for idx, line in enumerate(res):
        parts = line.split()
        if len(parts) == 3:
            start, end, flags = parts
            try:
                size = int(end, 16) - int(start, 16) + 1
            except ValueError:
                continue
            if size > 0:
                out["resource_sizes"][f"resource{idx}"] = size
    # current link state
    try:
        out["current_link_speed"] = (p / "current_link_speed").read_text().strip()
        out["current_link_width"] = (p / "current_link_width").read_text().strip()
        out["max_link_speed"] = (p / "max_link_speed").read_text().strip()
        out["max_link_width"] = (p / "max_link_width").read_text().strip()
    except FileNotFoundError:
        pass
    # AER counters
    aer = p / "aer_devcorrectable"
    if aer.is_file():
        out["aer_correctable_raw"] = aer.read_text().strip()
    aer_unc = p / "aer_devuncorrectable"
    if aer_unc.is_file():
        out["aer_uncorrectable_raw"] = aer_unc.read_text().strip()
    return out


def collect_vulkan() -> dict[str, Any]:
    """Full vulkaninfo; parse per-GPU identity from GPU<N>: blocks."""
    raw = _run(["vulkaninfo"])
    gpus: dict[str, dict[str, Any]] = {}
    # Per-device sections start at "GPU<N>:" and each field is taken
    # only from within its own block (split before the next GPU header
    # or EOF).
    blocks = re.split(r"^GPU(\d+):\s*$", raw, flags=re.M)
    # blocks: [pre, id1, body1, id2, body2, ...]
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
        # heap census: VkPhysicalDeviceMemoryProperties heaps
        heaps = []
        for hm in re.finditer(
            r"heap index\s+=\s+(\d+).*?device local.*?size\s+=\s+(\d+)",
                body, flags=re.S):
            heaps.append({"index": int(hm.group(1)),
                          "device_local": True,
                          "size": int(hm.group(2))})
        info["device_local_heaps"] = heaps
        gpus[f"gpu{gpu_id}"] = info
    return {"raw_length": len(raw), "gpus": gpus, "raw": raw}


def collect_host() -> dict[str, Any]:
    boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    return {
        "hostname": _run(["hostname"]).strip(),
        "boot_id": boot_id,
        "uname": _run(["uname", "-a"]).strip(),
        "kernel_cmdline": Path("/proc/cmdline").read_text().strip(),
        "uptime": Path("/proc/uptime").read_text().split()[0],
        "memory": _run(["free", "-b"]).splitlines()[1].split(),
        "cpu": _run(["lscpu"]),
        "dmidecode_bios": _run(["dmidecode", "-t", "bios", "-q"], sudo=True),
        "dmidecode_board": _run(["dmidecode", "-t", "baseboard", "-q"], sudo=True),
        "vulkan_loader": _run(["dpkg-query", "-W", "-f=${Version}",
                               "libvulkan1"]),
        "vulkan_icds": sorted(
            p.name for p in Path("/usr/share/vulkan/icd.d").iterdir()),
        "mesa": _run(["dpkg-query", "-W", "-f=${Version}",
                      "mesa-vulkan-drivers"]),
        "gpu_pci_bdfs": [l for l in _run(["lspci", "-D"]).splitlines()
                         if "Vega 10" in l or "Display controller" in l
                         or "VGA compatible" in l],
    }


def census() -> dict[str, Any]:
    host = collect_host()
    lspci = collect_lspci()
    vulkan = collect_vulkan()
    # Bind Vulkan devices to BDFs via UUID
    bindings = []
    for key, info in vulkan["gpus"].items():
        entry = {"vulkan_key": key, "vulkan_name": info.get("name"),
                 **{k: v for k, v in info.items() if k != "gpu_index"}}
        uuid = info.get("deviceUUID")
        if uuid and "RADV" in (info.get("name") or ""):
            entry["bdf"] = uuid_bdf(uuid)
        bindings.append(entry)
    v340l = [b for b in bindings
             if b.get("vendorID") == "0x1002" and "V340" in (b.get("vulkan_name") or "")]
    if len(v340l) != 2:
        raise CensusError(
            f"expected exactly 2 V340L Vulkan devices, found {len(v340l)}: "
            f"{[b.get('vulkan_name') for b in bindings]}")
    dies = {}
    for b in v340l:
        bdf = b["bdf"]
        dies[bdf] = {**b, "sysfs": collect_sysfs(bdf)}
        # cross-check: lspci display controller at same BDF
        if bdf not in lspci["dies"]:
            raise CensusError(
                f"Vulkan die {bdf} not present in lspci display set: "
                f"{sorted(lspci['dies'])}")
    doc = {
        "schema": "inferswarm.r8h.census/1",
        "campaign": rc.CAMPAIGN_ID,
        "host": host,
        "lspci_summary": {
            "dies": lspci["dies"],
            "amd_bridges": lspci["amd_bridges"],
            "tree": lspci["tree"],
        },
        "vulkan_devices": bindings,
        "v340l_dies": dies,
        "raw": {
            "vulkaninfo": vulkan["raw"],
        },
    }
    return doc


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    doc = census()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                        encoding="utf-8")
    print(json.dumps({
        "boot_id": doc["host"]["boot_id"],
        "dies": {b: {"uuid": d["deviceUUID"],
                     "vram_bytes": next(iter(d["sysfs"]["drm"].values()), {})
                     .get("mem_info_vram_total")}
                 for b, d in doc["v340l_dies"].items()},
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
