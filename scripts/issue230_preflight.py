#!/usr/bin/env python3
"""Issue #230 — V2-F preflight collector (Phase 0/1; read-only).

Collects, under the frozen closure:
  * host identity/boot/kernel/loader/ICD/driver probes (raw bytes);
  * the accepted #228 evidence byte-preservation proof (re-hashing its
    full manifest — the same proof the authority builder performs, so
    drift is caught at collection time too);
  * the fresh mapping (V2-A R3 identity probes + V2-F Vulkan identity
    probe UUID->BDF join, both corroborated against the authority);
  * the safety classification artifact;
  * the baseline health/journal snapshot.

No transfer is executed here (read-only preflight).
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
import issue230_host as host
import issue230_authority as pa
import issue230_receipt as rc
import issue230_safety as safety
import issue230_transfer as transfer

ROOT = Path(__file__).resolve().parents[1]

ATTEMPT_ID = "v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def collect_preflight(*, repo: Path, out: Path, attempt_id: str,
                      authority_path: Path, build_dir: Path
                      ) -> dict[str, Any]:
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
    for bdf in rc.ROUTE_BDFS.values():
        art(f"lspci_vv_{bdf.replace(':', '-')}",
            ["lspci", "-PP", "-nn", "-vv", "-s", bdf.removeprefix("0000:")],
            timeout=180)
    art("render_nodes", ["ls", "-la", "/dev/dri/by-path/"])
    art("iommu_groups", ["bash", "-c",
        "for g in /sys/kernel/iommu_groups/*; do echo \"== group "
        "$(basename $g)\"; for d in $g/devices/*; do echo $(basename $d) "
        "$(lspci -s $(basename $d | cut -d: -f2-) -nn 2>/dev/null | "
        "head -1); done; done; true"])
    art("acs_bits", ["bash", "-c",
        "for d in 00:1d.0 02:00.0 03:00.0 03:01.0 06:00.0 09:00.0 "
        "0a:00.0; do echo == $d; lspci -PP -vv -s $d 2>/dev/null "
        "| grep -A3 'Access Control'; done; true"])
    art("vram_totals", ["bash", "-c",
        "for d in /sys/class/drm/card*/device; do echo == $d; cat $d/mem_"
        "info_vram_total 2>/dev/null; done; true"])
    art("nic_link", ["ip", "-d", "link", "show"])
    art("gateway_ping", ["ping", "-c", "3", "-W", "2", "10.0.0.1"],
        timeout=60)
    art("lsusb", ["lsusb"])
    art("lsblk", ["lsblk", "-o", "NAME,SIZE,TYPE,MOUNTPOINT,MODEL"])
    art("storage_sentinel", ["bash", "-c",
        "set -e; f=$(mktemp /var/tmp/issue230-fs-sentinel.XXXXXX); "
        "printf issue230 > $f; sync; cat $f; rm -f $f; echo "
        "STORAGE_SENTINEL_OK"], timeout=120)
    journal = host.journal_scan()
    host.durable_write(raw / "journal_faults.stdout",
                       journal["text"].encode())
    probes.append({"name": "journal_faults", "argv": journal["argv"],
                   "returncode": 0,
                   "stdout_rel": "raw/journal_faults.stdout",
                   "stdout_sha256": hashlib.sha256(
                       journal["text"].encode()).hexdigest()})

    health0 = host.health_snapshot(rc.HEALTH_BDFS)
    tel_a = host.telemetry_sample("0000:06:00.0")
    tel_b = host.telemetry_sample("0000:09:00.0")

    # fresh mapping (R3 identity probes + V2-F Vulkan identity join)
    mapping = pa.fresh_map(authority_path, f"{attempt_id}-map",
                           out / "mapping", repo)

    # V2-F Vulkan identity probe (current-boot UUID->BDF corroboration)
    binary, _source = transfer.compile_transfer(build_dir)
    # R3 mapping carries short BDFs (06:00.0); the C probe derives the
    # 16-char domain-prefixed form from deviceUUIDs — normalize (the
    # documented BDF-form pitfall; a silent strcmp mismatch fails the
    # join).
    bdf_a = host.sysfs_bdf(mapping["participants"]["a"]["fresh_pci_bdf"])
    bdf_b = host.sysfs_bdf(mapping["participants"]["b"]["fresh_pci_bdf"])
    idy = transfer.run_probe(binary, ["identity", bdf_a, bdf_b],
                             raw, "identity-probe", timeout=120)
    if idy["returncode"] != 0:
        raise transfer.ProbeError(
            f"V2-F identity probe failed: {idy['stderr'][:300]}")
    devices = idy_parsed_identity_devices(idy["stdout"])
    uuid_bdfs = {d["bdf"] for d in devices if d["bdf"]}
    expected = {host.sysfs_bdf(bdf_a), host.sysfs_bdf(bdf_b)}
    if uuid_bdfs != expected:
        raise pa.AuthorityError(
            f"identity probe UUID-derived BDFs {sorted(uuid_bdfs)} do "
            f"not corroborate the fresh mapping {sorted(expected)}")
    probes.append({
        "name": "identity_probe",
        "argv": ["<embedded C probe>", "identity", bdf_a, bdf_b],
        "returncode": idy["returncode"],
        "stdout_rel": "raw/identity-probe.stdout",
        "stdout_sha256": idy["stdout_sha256"],
    })

    # safety classification artifact
    safety_path = safety.write_safety_record(out)

    # #228 byte-preservation proof (re-hash its full manifest)
    preserved = _verify_predecessor_manifests(repo)

    doc = {
        "schema": "inferswarm.v2f.preflight/1",
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
        "identity_probe_ok": True,
        "safety_classification_path": "safety-classification.json",
        "predecessor_preservation": preserved,
        "nonclaims": [
            "read-only preflight: no transfer executed in this phase",
            "the consumed #228 census is advertisement authority only",
        ],
    }
    (out / "preflight.json").write_bytes(
        json.dumps(doc, indent=1, sort_keys=True).encode() + b"\n")
    return doc


def idy_parsed_identity_devices(stdout: str) -> list[dict[str, Any]]:
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if obj.get("event") == "identity":
            return obj.get("devices") or []
    raise transfer.ProbeError("no identity event in probe output")


def _verify_predecessor_manifests(repo: Path) -> dict[str, Any]:
    """Re-hash every row of every predecessor manifest (V2-B/C/D/E)."""
    out: dict[str, Any] = {}
    for gen, rel in pa.MANIFEST_OF.items():
        rows = pa._load_manifest_rows(repo, rel)
        bad = []
        for path_rel, digest in sorted(rows.items()):
            p = repo / path_rel
            if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() \
                    != digest:
                bad.append(path_rel)
        out[gen] = {"manifest": rel, "rows": len(rows),
                    "drift": bad}
        if bad:
            raise pa.AuthorityError(
                f"predecessor {gen} evidence byte drift: {bad[:3]}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(ROOT))
    ap.add_argument("--out", required=True)
    ap.add_argument("--attempt-id", default=ATTEMPT_ID)
    ap.add_argument("--authority", required=True)
    ap.add_argument("--build-dir", default="/var/tmp/issue230-build")
    args = ap.parse_args()
    doc = collect_preflight(repo=Path(args.repo), out=Path(args.out),
                            attempt_id=args.attempt_id,
                            authority_path=Path(args.authority),
                            build_dir=Path(args.build_dir))
    print(json.dumps({"preflight": str(Path(args.out) / "preflight.json"),
                      "boot_id": doc["boot_id"],
                      "predecessor_preservation":
                          {k: v["rows"] for k, v in
                           doc["predecessor_preservation"].items()}},
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
