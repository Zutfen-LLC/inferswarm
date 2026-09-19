#!/usr/bin/env python3
"""Issue #228 — V2-E fresh topology + capability census (Phases 1-2).

Read-only first: complete topology/capability census BEFORE any transfer
execution. Retains raw probe bytes + receipts for every observation:
host/kernel/cmdline identity, complete lspci -PP -nn -vv topology with
LnkCap/LnkSta, BAR map, ACS capability/control bits, IOMMU groups, AER
baselines, amdgpu health, peripheral sentinels, plus the Vulkan
device-group capability audit (enumeration, group membership,
subset-allocation, per-die memory heaps, and — via the #228 capability
probe binary — vkGetDeviceGroupPeerMemoryFeatures for every
(device, heap) candidate pair).

No transfer is executed here. The capability probe allocates NO memory
beyond device creation and queries capability entry points only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue228_host as host
import issue228_authority as pa
import issue228_receipt as rc
import issue228_probe as probe

ROOT = Path(__file__).resolve().parents[1]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def collect_preflight(*, repo: Path, out: Path, attempt_id: str,
                      authority_path: Path, build_dir: Path) -> dict[str, Any]:
    closure = rc.verify_closure(repo)
    authority = json.loads(authority_path.read_text(encoding="utf-8"))
    if not pa.verify_authority(authority, repo):
        raise pa.AuthorityError("authority invalid at preflight")

    raw = out / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    probes: list[dict[str, Any]] = []

    def art(name: str, argv: list[str], timeout: int = 120,
            optional: bool = False) -> dict:
        try:
            receipt = host.run_probe(argv, timeout=timeout)
        except host.HostObservationError as exc:
            if not optional:
                raise
            receipt = {"argv": argv, "returncode": 1,
                       "stdout": "", "stderr": str(exc),
                       "optional_unavailable": True}
        host.durable_write(raw / f"{name}.stdout",
                           receipt["stdout"].encode())
        host.durable_write(raw / f"{name}.stderr",
                           receipt["stderr"].encode())
        row = {"name": name, "argv": argv,
               "returncode": receipt["returncode"],
               "stdout_rel": f"raw/{name}.stdout",
               "stdout_sha256": hashlib.sha256(
                   receipt["stdout"].encode()).hexdigest()}
        probes.append(row)
        return receipt

    boot = host.boot_id()
    art("boot_id", ["cat", "/proc/sys/kernel/random/boot_id"])
    art("uname", ["uname", "-a"])
    art("kernel_cmdline", ["cat", "/proc/cmdline"])
    art("amdgpu_version", ["cat", "/sys/module/amdgpu/version"],
        optional=True)
    art("vulkan_loader", ["dpkg-query", "-W", "-f=${Version}\n",
                          "libvulkan1"])
    art("icd_list", ["ls", "-la", "/usr/share/vulkan/icd.d/"])
    art("lspci_nn", ["lspci", "-nn"])
    art("lspci_tree", ["lspci", "-tv"])
    art("vulkaninfo_summary", ["vulkaninfo", "--summary"], timeout=300)
    art("vulkaninfo_full", ["vulkaninfo"], timeout=600)
    # full verbose topology with -PP (full path) for every port on the
    # root->switch->die path plus both dies
    for bdf in rc.ROUTE_BDFS.values():
        art(f"lspci_vv_{bdf.replace(':', '-')}",
            ["lspci", "-PP", "-nn", "-vv", "-s", bdf.removeprefix("0000:")],
            timeout=180)
    art("lspci_vv_full", ["lspci", "-PP", "-nn", "-vv"], timeout=600)
    art("render_nodes", ["ls", "-la", "/dev/dri/by-path/"])
    art("iommu_groups", ["bash", "-c",
        "for g in /sys/kernel/iommu_groups/*; do echo \"== group "
        "$(basename $g)\"; for d in $g/devices/*; do echo $(basename $d) "
        "$(lspci -s $(basename $d | cut -d: -f2-) -nn 2>/dev/null | "
        "head -1); done; done; true"])
    art("acs_bits", ["bash", "-c",
        "for d in 00:1d.0 02:00.0 03:00.0 03:01.0 04:00.0 05:00.0 "
        "07:00.0 08:00.0; do echo == $d; lspci -PP -vv -s $d 2>/dev/null "
        "| grep -A3 'Access Control'; done; true"])
    art("vram_totals", ["bash", "-c",
        "for d in /sys/class/drm/card*/device; do echo == $d; cat $d/mem_"
        "info_vram_total 2>/dev/null; done; true"])
    art("ras", ["bash", "-c",
        "for d in /sys/class/drm/card*/device/ras; do echo == $d; cat $d/"
        "gpu_err_cnt 2>/dev/null; done; true"], optional=True)
    art("nic_link", ["ip", "-d", "link", "show", "enp1s0"])
    art("gateway_ping", ["ping", "-c", "3", "-W", "2", "10.0.0.1"],
        timeout=60)
    art("lsusb", ["lsusb"])
    art("lsblk", ["lsblk", "-o", "NAME,SIZE,TYPE,MOUNTPOINT,MODEL"])
    art("storage_sentinel", ["bash", "-c",
        "set -e; f=$(mktemp /var/tmp/issue228-fs-sentinel.XXXXXX); "
        "printf issue228 > $f; sync; cat $f; rm -f $f; echo "
        "STORAGE_SENTINEL_OK"], timeout=120)
    journal = host.journal_scan()
    host.durable_write(raw / "journal_faults.stdout",
                       journal["text"].encode())
    probes.append({"name": "journal_faults", "argv": journal["argv"],
                   "returncode": 0,
                   "stdout_rel": "raw/journal_faults.stdout",
                   "stdout_sha256": hashlib.sha256(
                       journal["text"].encode()).hexdigest()})

    # health baseline over the full route BDF set
    health0 = host.health_snapshot(rc.HEALTH_BDFS)
    tel_a = host.telemetry_sample("0000:06:00.0")
    tel_b = host.telemetry_sample("0000:09:00.0")

    # fresh mapping (R3 identity probes; no model tokens)
    mapping = pa.fresh_map(authority_path, f"{attempt_id}-map",
                           out / "mapping", repo)
    for die, row in mapping["participants"].items():
        if not row["fresh_pci_bdf"].startswith(("06:", "09:", "0000:06:",
                                                "0000:09:")):
            raise pa.AuthorityError(
                f"fresh mapping bound die {die} to unexpected BDF "
                f"{row['fresh_pci_bdf']}")

    # capability probes (device-group enumeration + peer-memory features;
    # external-memory handle matrix; no transfers)
    cap = probe.run_capability_probe(build_dir=build_dir,
                                     raw_dir=raw)
    probes.append({
        "name": "capability_probe",
        "argv": ["<embedded C probe>"],
        "returncode": 0,
        "stdout_rel": f"raw/{cap['stdout_rel']}",
        "stdout_sha256": cap["stdout_sha256"],
    })
    ext = probe.run_ext_matrix_probe(build_dir=build_dir, raw_dir=raw)
    probes.append({
        "name": "external_memory_matrix_probe",
        "argv": ["<embedded C probe>", "ext-matrix"],
        "returncode": 0,
        "stdout_rel": f"raw/{ext['stdout_rel']}",
        "stdout_sha256": ext["stdout_sha256"],
    })
    capability_doc = dict(cap["parsed"])
    capability_doc["external_memory_matrix"] = ext["parsed"]

    doc = {
        "schema": "inferswarm.v2e.preflight/1",
        "campaign_id": rc.CAMPAIGN_ID,
        "attempt_id": attempt_id,
        "captured_utc": _now(),
        "boot_id": boot,
        "authority_digest": authority["authority_digest"],
        "mapping_digest": mapping["mapping_digest"],
        "closure_digest": closure["closure_digest"],
        "producer_head": closure["producer_head"],
        "probes": probes,
        "health_baseline": health0,
        "telemetry_idle": {"a": tel_a, "b": tel_b},
        "journal_fault_counts": journal["counts"],
        "journal_next_cursor": journal["next_cursor"],
        "capability": capability_doc,
        "nonclaims": [
            "read-only census: no peer transfer executed in this phase",
        ],
    }
    (out / "preflight.json").write_bytes(
        json.dumps(doc, indent=1, sort_keys=True).encode() + b"\n")
    return doc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(ROOT))
    ap.add_argument("--out", required=True)
    ap.add_argument("--attempt-id", default="pf1")
    ap.add_argument("--authority", required=True)
    ap.add_argument("--build-dir", default="/var/tmp/issue228-build")
    args = ap.parse_args()
    doc = collect_preflight(repo=Path(args.repo), out=Path(args.out),
                            attempt_id=args.attempt_id,
                            authority_path=Path(args.authority),
                            build_dir=Path(args.build_dir))
    print(json.dumps({"preflight": str(Path(args.out) / "preflight.json"),
                      "capability_ok":
                          doc["capability"].get("capability_ok"),
                      "peer_features": doc["capability"].get(
                          "peer_memory_features")},
                         indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
