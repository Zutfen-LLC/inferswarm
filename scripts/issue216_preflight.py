#!/usr/bin/env python3
"""Issue #216 — V2-D Phase-1 preflight collector (inferswarm02).

Fresh physical re-measurement before any concurrency: host/OS/kernel/
amdgpu/ICD identity, complete root-port -> PM8533 -> both-Vega topology,
final BAR map, LnkCap/LnkSta, fresh two-die Vulkan discovery mapping
(with intended-identity corroboration), HBM/CU/ECC/SR-IOV facts,
peripheral health, and pre-existing fault scan. Plus one fresh
single-die accepted-sentinel per die.

All probes are read-only; every probe retains raw bytes + receipt.
Sentinels are the frozen bounded execution (8 tokens) per die through
the ACCEPTED runtime with the ACCEPTED comparator/accounting.
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
import issue216_host as host
import issue216_execution as ex
import issue216_physical_authority as pa
import issue216_receipt as rc

ROOT = Path(__file__).resolve().parents[1]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def collect_preflight(*, repo: Path, out: Path, attempt_id: str,
                      authority_path: Path) -> dict[str, Any]:
    rc.verify_closure(repo)
    authority = json.loads(authority_path.read_text(encoding="utf-8"))
    if not pa.verify_authority(authority, repo):
        raise pa.AuthorityError("authority invalid at preflight")

    raw = out / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    probes: list[dict[str, Any]] = []

    def art(name: str, argv: list[str], timeout: int = 120) -> dict:
        receipt = host.run_probe(argv, timeout=timeout)
        host.durable_write(raw / f"{name}.stdout",
                           receipt["stdout"].encode())
        host.durable_write(raw / f"{name}.stderr",
                           receipt["stderr"].encode())
        row = {"name": name, "argv": argv, "returncode": receipt[
            "returncode"], "stdout_rel": f"raw/{name}.stdout",
            "stdout_sha256": hashlib.sha256(
                receipt["stdout"].encode()).hexdigest()}
        probes.append(row)
        return receipt

    boot = host.boot_id()
    art("boot_id", ["cat", "/proc/sys/kernel/random/boot_id"])
    art("uname", ["uname", "-a"])
    art("kernel_cmdline", ["cat", "/proc/cmdline"])
    art("amdgpu_version", ["cat", "/sys/module/amdgpu/version"])
    art("vulkan_loader", ["dpkg-query", "-W",
                          "-f=${Version}\n", "libvulkan1"])
    art("icd_list", ["ls", "-la", "/usr/share/vulkan/icd.d/"])
    art("lspci_nn", ["lspci", "-nn"])
    art("lspci_tree", ["lspci", "-t"])
    art("vulkaninfo_summary", ["vulkaninfo", "--summary"], timeout=300)
    bdfs = host.vega_bdfs()
    for bdf in bdfs:
        art(f"lspci_vv_{bdf.replace(':', '-')}",
            ["lspci", "-PP", "-nn", "-vv", "-s", bdf], timeout=180)
    art("lspci_vv_full", ["lspci", "-PP", "-nn", "-vv"], timeout=600)
    art("render_nodes", ["ls", "-la", "/dev/dri/by-path/"])
    art("sriov", ["bash", "-c",
        "for d in /sys/bus/pci/devices/*; do t=$(cat $d/vendor):$(cat "
        "$d/device); if [ \"$t\" = \"0x1002/0x6864\" ] || [ \"$t\" = "
        "\"0x1022/0x1470\" ] || [ \"$t\" = \"0x1022/0x1471\" ]; then echo == "
        "$d; cat $d/sriov_totalvfs 2>/dev/null; cat $d/sriov_numvfs 2>/dev"
        "; fi; done"])
    art("vram_totals", ["bash", "-c",
        "for d in /sys/class/drm/card*/device; do echo == $d; cat $d/mem_"
        "info_vram_total 2>/dev/null; done"])
    art("ras", ["bash", "-c",
        "for d in /sys/class/drm/card*/device/ras; do echo == $d; cat $d/"
        "gpu_err_cnt 2>/dev/null; done"])
    art("nic_link", ["ip", "-d", "link", "show", "enp1s0"])
    art("gateway_ping", ["ping", "-c", "3", "-W", "2", "10.0.0.1"],
        timeout=60)
    art("lsusb", ["lsusb"])
    art("lsblk", ["lsblk", "-o", "NAME,SIZE,TYPE,MOUNTPOINT,MODEL"])
    art("storage_sentinel", ["bash", "-c",
        "set -e; f=$(mktemp /var/tmp/issue216-fs-sentinel.XXXXXX); "
        "printf issue216 > $f; sync; cat $f; rm -f $f; echo "
        "STORAGE_SENTINEL_OK"], timeout=120)
    journal = host.journal_scan()
    host.durable_write(raw / "journal_faults.stdout",
                       journal["text"].encode())
    probes.append({"name": "journal_faults", "argv": journal["argv"],
                   "returncode": 0,
                   "stdout_rel": "raw/journal_faults.stdout",
                   "stdout_sha256": hashlib.sha256(
                       journal["text"].encode()).hexdigest()})

    # Fresh mapping (intended-identity corroborating discovery)
    mapping = pa.fresh_map(authority_path, attempt_id, out / "mapping",
                           repo)

    aer = {bdf: host.aer_counters(bdf) for bdf in bdfs}

    record = {
        "schema": "inferswarm.v2d.preflight/2",
        "campaign_id": rc.CAMPAIGN_ID,
        "attempt_id": attempt_id,
        "authority_digest": authority["authority_digest"],
        "mapping_digest": mapping["mapping_digest"],
        "boot_id": boot,
        "captured_utc": _now(),
        "probes": probes,
        "bdfs": bdfs,
        "aer_counters": aer,
        "journal_fault_counts": journal["counts"],
        "mapping": mapping,
        "telemetry_idle": {bdf: host.telemetry_sample(bdf)
                           for bdf in bdfs},
    }
    return record


def run_sentinels(*, repo: Path, out: Path, attempt_id: str,
                  authority: dict[str, Any], mapping: dict[str, Any],
                  runtime: dict[str, Any]) -> dict[str, Any]:
    """One fresh single-die sentinel per die through the accepted argv."""
    results = {}
    for die in ("a", "b"):
        participant = mapping["participants"][die]
        argv = ex.execution_argv(runtime["executable"], runtime["model"],
                                 participant["fresh_selector"], n_tokens=8)
        run = ex.run_execution(
            argv=argv, out_dir=out / "sentinel" / die,
            label=f"sentinel-{attempt_id}-{die}",
            expected_selector_bdf=participant["fresh_pci_bdf"])
        run = ex.derive_execution_facts(repo, run,
                                        out / "sentinel" / die)
        results[die] = ex.reduce_run(run)
        results[die]["run"] = run
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--repo", required=True)
    c.add_argument("--out", required=True)
    c.add_argument("--attempt-id", required=True)
    c.add_argument("--authority", required=True)
    args = ap.parse_args()
    repo = Path(args.repo)
    out = Path(args.out)
    record = collect_preflight(repo=repo, out=out,
                               attempt_id=args.attempt_id,
                               authority_path=Path(args.authority))
    authority = json.loads(Path(args.authority).read_text())
    sentinels = run_sentinels(repo=repo, out=out,
                              attempt_id=args.attempt_id,
                              authority=authority,
                              mapping=record["mapping"],
                              runtime=authority["runtime"])
    record["sentinels"] = sentinels
    out.mkdir(parents=True, exist_ok=True)
    (out / "preflight.json").write_bytes(
        json.dumps(record, indent=1, sort_keys=True).encode() + b"\n")
    ok = all(s["correct"] for s in sentinels.values())
    print(json.dumps({"preflight_ok": ok,
                      "bdfs": record["bdfs"],
                      "sentinels": {d: results["correct"] for d, results
                                    in sentinels.items()}}))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
