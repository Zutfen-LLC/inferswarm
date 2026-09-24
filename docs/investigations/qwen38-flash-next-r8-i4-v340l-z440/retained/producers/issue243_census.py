#!/usr/bin/env python3
"""Issue #243 (R8-I4) — Phase 0/1 census assembler (runs on inferswarm05).

Collects fresh host identity, PCIe/Vulkan/driver census, telemetry
baseline, and model-backing read capability into one JSON receipt.
Read-only: no GPU context created, no compute executed.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue243_constants as C


def run(cmd: list[str], timeout: int = 120) -> dict:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return {"rc": p.returncode, "out": p.stdout, "err": p.stderr}


def sha256(path: str) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    doc: dict = {
        "schema": "inferswarm.issue243.census/1",
        "campaign": C.CAMPAIGN_ID,
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                     time.gmtime()),
    }
    # Host identity
    doc["host"] = {
        "hostname": run(["hostname"])["out"].strip(),
        "machine_id": Path("/etc/machine-id").read_text().strip(),
        "uname": run(["uname", "-a"])["out"].strip(),
        "cmdline": Path("/proc/cmdline").read_text().strip(),
        "os_release": Path("/etc/os-release").read_text(),
        "baseboard": run(["sudo", "-n", "dmidecode", "-t", "baseboard"])["out"],
        "bios": run(["sudo", "-n", "dmidecode", "-t", "bios"])["out"],
        "processor": run(["sudo", "-n", "dmidecode", "-t",
                          "processor"])["out"],
        "memory_dimms": run(["sudo", "-n", "dmidecode", "-t",
                             "memory"])["out"],
        "meminfo": Path("/proc/meminfo").read_text(),
        "swaps": Path("/proc/swaps").read_text(),
        "slots": run(["sudo", "-n", "dmidecode", "-t", "slot"])["out"],
    }
    # PCIe + GPUs
    doc["pcie"] = {
        "lspci_PP_nn": run(["lspci", "-PP", "-nn"])["out"],
        "lspci_vv_full": run(["sudo", "-n", "lspci", "-PP", "-nn",
                              "-vv"])["out"],
    }
    dies = {}
    for card, bdf in (("card1", "0000:07:00.0"), ("card2", "0000:0b:00.0")):
        base = f"/sys/class/drm/{card}/device"
        entry: dict = {"bdf": bdf, "pci_slot_name": bdf}
        for k in ("vendor", "device", "subsystem_vendor",
                  "subsystem_device", "revision", "driver",
                  "mem_info_vram_total", "mem_info_vram_used",
                  "mem_info_gtt_total", "current_link_speed",
                  "current_link_width", "max_link_speed",
                  "max_link_width"):
            try:
                entry[k] = Path(base, k).read_text().strip()
            except OSError:
                pass
        # BARs from lspci
        entry["lspci_regions"] = [
            l for l in run(["sudo", "-n", "lspci", "-PP", "-nn", "-v",
                            "-s", bdf[5:]])["out"].splitlines()
            if "Region" in l or "Memory at" in l]
        # hwmon telemetry
        hw = {}
        for hdir in sorted(Path(base, "hwmon").glob("hwmon*")):
            for f in sorted(hdir.iterdir()):
                if f.name.startswith(("temp", "power", "freq",
                                      "in_", "curr")) \
                        and not f.name.endswith(("_label", "_crit",
                                                "_crit_hyst",
                                                "_emergency",
                                                "_highest",
                                                "_lowest")):
                    try:
                        hw[f.name] = f.read_text().strip()
                    except OSError:
                        pass
        entry["hwmon"] = hw
        # clocks via ppcurvclock-equivalent sysfs (vega10: no generic
        # gt_cur_freq; use amdgpu pm files if present)
        for ck in ("pp_dpm_sclk", "pp_dpm_mclk", "ppcurvclock"):
            try:
                entry[ck] = Path(base, ck).read_text().strip()[:800]
            except OSError:
                pass
        dies[card] = entry
    doc["dies"] = dies
    # GTX 1060 presence (not used)
    doc["other_gpus"] = {
        "02:00.0": run(["sudo", "-n", "lspci", "-PP", "-nn", "-vv",
                        "-s", "02:00.0"])["out"][:3000]}
    # Vulkan
    doc["vulkan"] = {
        "summary": run(["vulkaninfo", "--summary"],
                       timeout=180)["out"],
        "loader_version": run(["dpkg-query", "-W", "-f",
                               "${Version}", "libvulkan1"])["out"],
        "mesa_version": run(["dpkg-query", "-W", "-f", "${Version}",
                             "mesa-vulkan-drivers"])["out"],
        "icd_radeon": Path(C.ICD_FILE).read_text()
        if Path(C.ICD_FILE).is_file() else None,
    }
    # kernel driver state
    doc["kernel"] = {
        "dmesg_baseline": run(["sudo", "-n", "dmesg"])["out"],
        "amdgpu_version": run(["cat", "/sys/module/amdgpu/version"])
                             ["out"].strip(),
        "iommu_groups": str(len(list(Path("/sys/kernel/iommu_groups")
                                     .iterdir()))),
    }
    # Storage backing / model read capability
    doc["backing"] = {
        "findmnt_srv": run(["findmnt", "-T", C.MODEL_DIR])["out"],
        "lsblk": run(["lsblk", "-o",
                      "NAME,SIZE,ROTA,TYPE,MOUNTPOINT,FSTYPE"])["out"],
        "model_dir_listing": run(["ls", "-la", C.MODEL_DIR])["out"],
    }
    out_path = sys.argv[1] if len(sys.argv) > 1 else "phase1-census.json"
    Path(out_path).write_text(json.dumps(doc, indent=1))
    print(json.dumps({"written": out_path,
                      "dies": {k: v["bdf"] for k, v in dies.items()}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
