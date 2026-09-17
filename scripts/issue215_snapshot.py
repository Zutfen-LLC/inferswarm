#!/usr/bin/env python3
"""Issue #215 — V2-C post-boot canonical snapshot collector.

Runs DIRECTLY on inferswarm02 (as hermes, via sudo for read-only host
queries). Captures the frozen per-cycle snapshot schema into a node-local
evidence root. Executes NO reboot and NO model execution (the sentinel is a
separate prospectively frozen step). All probes are read-only.

Usage (on inferswarm02):
  sudo python3 issue215_snapshot.py capture --cycle <n> --type <warm|cold|baseline> \
      --prev-boot-id <id> --out-root /srv/inferswarm/state/issue215/<campaign-id>

Every artifact is written with sha256 sidecars and a receipt manifest. The
collector never repairs anything; failures are recorded, not fixed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "inferswarm.v2c.post-boot-snapshot/1"

RUNTIME_EXECUTABLE = "/home/zutfen/.cache/v0c-llama.cpp/build-v0c-vulkan/bin/llama-cli"
MODEL = "/home/zutfen/.cache/v0c-models/Qwen2.5-3B-Instruct-Q4_K_M.gguf"
GATEWAY = "10.0.0.1"

VEGA_ID = "1002:6864"
BRIDGE_IDS = ("1022:1470", "1022:1471")
PM8533_ID = "11f8:8533"
NIC_ID = "10ec:8168"
USB_ID = "8086:a2af"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(cmd: list[str], timeout: int = 120) -> dict:
    try:
        p = subprocess.run(cmd, capture_output=True, text=False, timeout=timeout)
        return {"argv": cmd, "rc": p.returncode, "stdout": p.stdout.decode("utf-8", "replace"),
                "stderr": p.stderr.decode("utf-8", "replace")}
    except subprocess.TimeoutExpired as exc:
        return {"argv": cmd, "rc": 124, "stdout": (exc.stdout or b"").decode("utf-8", "replace"),
                "stderr": f"TIMEOUT after {timeout}s", "exc": "TimeoutExpired"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_artifact(out: Path, name: str, data: bytes) -> dict:
    path = out / name
    path.write_bytes(data)
    (out / (name + ".sha256")).write_text(sha256_bytes(data) + "\n", encoding="utf-8")
    # Durability (v2 lesson, cycle-04 v1 loss): every artifact is fsynced,
    # and its parent directory entry too, so retained bytes survive an
    # abrupt power cut at any moment.
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    dfd = os.open(out, os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)
    return {"name": name, "bytes": len(data), "sha256": sha256_bytes(data)}


def capture(cycle: int, kind: str, prev_boot_id: str | None, out_root: Path,
            requested_transition: str | None) -> dict:
    out = out_root / f"cycle-{cycle:02d}-{kind}"
    if out.exists():
        raise SystemExit(f"refusing to overwrite existing cycle dir {out}")
    out.mkdir(parents=True)
    raw = out / "raw"
    raw.mkdir()
    artifacts: list[dict] = []

    def art(name: str, cmd: list[str], timeout: int = 120) -> dict:
        r = _run(cmd, timeout=timeout)
        rec = write_artifact(raw, name, json.dumps(r, indent=1).encode())
        return {"probe": name, **rec, "rc": r["rc"]}

    # --- host identity ---
    boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    records: dict = {
        "schema": SCHEMA,
        "campaign_id": "issue215-v2c-v340l-platform-stability-v1",
        "cycle_index": cycle,
        "cycle_type": kind,
        "requested_transition": requested_transition,
        "prev_boot_id": prev_boot_id,
        "boot_id": boot_id,
        "boot_id_changed": (prev_boot_id is not None and boot_id != prev_boot_id) if kind != "baseline" else None,
        "captured_utc": _now(),
    }
    artifacts.append(art("boot_id.txt", ["cat", "/proc/sys/kernel/random/boot_id"]))
    artifacts.append(art("uptime.txt", ["cat", "/proc/uptime"]))
    artifacts.append(art("uname.txt", ["uname", "-a"]))
    artifacts.append(art("cmdline.txt", ["cat", "/proc/cmdline"]))
    artifacts.append(art("dmi-board.txt", ["dmidecode", "-s", "baseboard-manufacturer"]))
    artifacts.append(art("dmi-board-product.txt", ["dmidecode", "-s", "baseboard-product-name"]))
    artifacts.append(art("dmi-bios-version.txt", ["dmidecode", "-s", "bios-version"]))
    artifacts.append(art("os-release.txt", ["cat", "/etc/os-release"]))
    artifacts.append(art("amdgpu-version.txt", ["cat", "/sys/module/amdgpu/version"]))
    artifacts.append(art("modinfo-amdgpu.txt", ["modinfo", "amdgpu"], timeout=60))
    artifacts.append(art("vulkan-loader-version.txt", ["dpkg-query", "-W", "-f=${Version}\\n", "libvulkan1"]))
    artifacts.append(art("icd-list.txt", ["ls", "-la", "/usr/share/vulkan/icd.d/"]))
    artifacts.append(art("vulkaninfo-summary.txt", ["vulkaninfo", "--summary"], timeout=180))

    # --- PCI / V340L ---
    artifacts.append(art("lspci-nn.txt", ["lspci", "-nn"]))
    artifacts.append(art("lspci-tree.txt", ["lspci", "-t"]))
    for bdf in _vega_bdfs():
        artifacts.append(art(f"lspci-vv-{bdf.replace(':', '-')}.txt",
                             ["lspci", "-PP", "-nn", "-vv", "-s", bdf], timeout=180))
    artifacts.append(art("lspci-vv-full.txt", ["lspci", "-PP", "-nn", "-vv"], timeout=600))
    artifacts.append(art("iommu-groups.txt", ["findmnt", "-n", "-o", "SOURCE", "/"]))
    artifacts.append(art("render-nodes.txt", ["ls", "-la", "/dev/dri/by-path/"]))
    artifacts.append(art("drm-cards.txt", ["ls", "-la", "/sys/class/drm/"]))
    artifacts.append(art("gpu-sysfs-mem.txt", ["bash", "-c",
        "for d in /sys/class/drm/card*/device; do echo == $d; cat $d/mem_info_vram_total 2>/dev/null; done"]))
    artifacts.append(art("ras-ecc.txt", ["bash", "-c",
        "for d in /sys/class/drm/card*/device/ras; do echo == $d; cat $d/gpu_err_cnt 2>/dev/null; done"]))
    artifacts.append(art("sriov.txt", ["bash", "-c",
        "for d in /sys/bus/pci/devices/*; do t=$(cat $d/vendor):$(cat $d/device); "
        "if [ \"$t\" = \"0x1002/0x6864\" ] || [ \"$t\" = \"0x1022/0x1470\" ] || [ \"$t\" = \"0x1022/0x1471\" ]; then "
        "echo == $d; cat $d/sriov_totalvfs 2>/dev/null; cat $d/sriov_numvfs 2>/dev/null; fi; done"]))

    # --- Vulkan enumeration (fresh) ---
    artifacts.append(art("vulkan-list-devices.txt", [RUNTIME_EXECUTABLE, "--list-devices"], timeout=300))

    # --- peripherals ---
    artifacts.append(art("nic-link.txt", ["ip", "-d", "link", "show", "enp1s0"]))
    artifacts.append(art("nic-addr.txt", ["ip", "-br", "addr", "show", "enp1s0"]))
    artifacts.append(art("nic-route.txt", ["ip", "route"]))
    artifacts.append(art("nic-driver.txt", ["bash", "-c", "lspci -nnk -s 01:00.0 | tail -3"]))
    artifacts.append(art("gateway-ping.txt", ["ping", "-c", "3", "-W", "2", GATEWAY], timeout=60))
    artifacts.append(art("lsusb.txt", ["lsusb"]))
    artifacts.append(art("usb-controllers.txt", ["lsusb", "-t"]))
    artifacts.append(art("usb-devices-sysfs.txt", ["bash", "-c",
        "for d in /sys/bus/usb/devices/*; do [ -f $d/idVendor ] || continue; "
        "echo \"$d $(cat $d/idVendor):$(cat $d/idProduct) $(cat $d/product 2>/dev/null)\"; done"]))
    artifacts.append(art("lsblk.txt", ["lsblk", "-o", "NAME,SIZE,TYPE,MOUNTPOINT,MODEL"]))
    artifacts.append(art("findmnt-root.txt", ["findmnt", "/"]))
    artifacts.append(art("storage-sentinel.txt", ["bash", "-c",
        "set -e; f=$(mktemp /var/tmp/issue215-fs-sentinel.XXXXXX); printf issue215 > $f; sync; "
        "cat $f; rm -f $f; echo STORAGE_SENTINEL_OK"], timeout=120))
    artifacts.append(art("mdadm-detail.txt", ["bash", "-c", "cat /proc/mdstat 2>/dev/null || true"]))

    # --- error baseline (current boot journal, kernel) ---
    artifacts.append(art("journal-errors.txt", ["journalctl", "-b", "-p", "err", "--no-pager"], timeout=300))
    artifacts.append(art("journal-warnings.txt", ["journalctl", "-b", "-p", "warning", "--no-pager"], timeout=300))
    artifacts.append(art("dmesg.txt", ["dmesg"], timeout=120))
    artifacts.append(art("journal-aer.txt", ["journalctl", "-b", "-k", "--no-pager",
        "-g", "AER|pcieport|BAR |amdgpu|DMAR|dmar|IOMMU|iommu"], timeout=300))

    # --- prior boot termination evidence (warm cycles) ---
    if kind != "baseline":
        artifacts.append(art("prev-boot-shutdown.txt", ["journalctl", "-b", "-1", "--no-pager",
            "-g", "Stopping|Started|Reached target|Shutdown", "-n", "200"], timeout=300))
        artifacts.append(art("prev-boot-last-lines.txt", ["journalctl", "-b", "-1", "--no-pager", "-n", "60"],
                             timeout=300))

    receipt = {"records": records, "artifacts": artifacts}
    (out / "receipt.json").write_bytes(json.dumps(receipt, indent=1).encode() + b"\n")
    print(json.dumps({"cycle": cycle, "type": kind, "boot_id": boot_id, "out": str(out),
                      "artifact_count": len(artifacts)}, indent=1))
    return receipt


def _vega_bdfs() -> list[str]:
    try:
        lspci = subprocess.run(["lspci", "-nn"], capture_output=True, text=True, timeout=60)
        return [line.split()[0] for line in lspci.stdout.splitlines() if VEGA_ID in line]
    except Exception:
        return []


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("capture")
    c.add_argument("--cycle", type=int, required=True)
    c.add_argument("--type", choices=("baseline", "warm", "cold"), required=True)
    c.add_argument("--prev-boot-id")
    c.add_argument("--requested-transition")
    c.add_argument("--out-root", required=True)
    args = parser.parse_args()
    capture(args.cycle, args.type, args.prev_boot_id, Path(args.out_root), args.requested_transition)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
