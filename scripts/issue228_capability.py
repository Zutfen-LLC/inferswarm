#!/usr/bin/env python3
"""Issue #228 — V2-E fresh topology + capability census (Phases 1-2).

Correction round (maintainer NO-GO on c9822fe):

* the capability census is VALIDATED (issue228_probe
  .validate_capability_census) before any conclusion is drawn from it;
  an invalid census is an evidence failure, never capability absence;
* the census is physically joined to the accepted fresh A/B mapping by
  deviceUUID->BDF corroboration (name substrings and enumeration order
  are never physical authority), and the census's own UUID-derived BDFs
  must agree with the mapping's participants;
* the census artifacts carry an explicit ``attempt`` identity
  (``pf1`` = superseded attempt-1 bytes retained verbatim; ``pf2`` =
  this corrected attempt) so corrected observations are never mistaken
  for attempt-1 output and vice versa;
* no transfer execution exists in this collector (the ladder/baseline
  runners are hard-disabled; see issue228_ladder).

Read-only first: complete topology/capability census with raw probe
bytes + receipts for every observation. No transfer is executed here.
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

#: attempt identity for this collector. attempt-1 (``pf1``) observations
#: are retained verbatim under evidence/preflight/ and are SUPERSEDED;
#: corrected observations use ``pf2``.
ATTEMPT_ID = "pf2"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def census_join_mapping(cap: dict[str, Any], mapping: dict[str, Any],
                        ) -> dict[str, str]:
    """Fail-closed UUID/BDF corroboration between the fresh census and
    the accepted fresh mapping. Returns participant->BDF on success;
    raises pa.AuthorityError when the two disagree."""
    expected: dict[str, str] = {}
    for die, row in mapping["participants"].items():
        bdf = probe.normalize_bdf(row["fresh_pci_bdf"])
        expected[die] = bdf
    vega_uuids = set()
    for g in cap.get("groups", []):
        for d in g.get("devices", []):
            if d.get("is_v340") and d.get("device_uuid"):
                vega_uuids.add(d["device_uuid"])
    derived: dict[str, str] = {}
    for uuid in sorted(vega_uuids):
        bdf = probe.bdf_from_device_uuid(uuid)
        if bdf is None:
            raise pa.AuthorityError(
                f"census deviceUUID {uuid} does not parse to a BDF")
        derived[uuid] = bdf
    derived_bdfs = set(derived.values())
    expected_bdfs = set(expected.values())
    if derived_bdfs != expected_bdfs:
        raise pa.AuthorityError(
            f"census UUID-derived BDFs {sorted(derived_bdfs)} disagree "
            f"with the accepted fresh mapping {sorted(expected_bdfs)}")
    return expected


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
        "returncode": cap["exit_code"],
        "stdout_rel": f"raw/{cap['stdout_rel']}",
        "stdout_sha256": cap["stdout_sha256"],
    })
    ext = probe.run_ext_matrix_probe(build_dir=build_dir, raw_dir=raw)
    probes.append({
        "name": "external_memory_matrix_probe",
        "argv": ["<embedded C probe>", "ext-matrix"],
        "returncode": ext["exit_code"],
        "stdout_sha256": ext["stdout_sha256"],
        "stdout_rel": f"raw/{ext['stdout_rel']}",
    })
    capability_doc = dict(cap["parsed"])
    capability_doc["external_memory_matrix"] = ext["parsed"]

    # fail-closed physical identity join (census <-> accepted mapping)
    joined = census_join_mapping(cap["parsed"], mapping)

    # validate the census BEFORE any conclusion is drawn from it
    verdict = probe.validate_capability_census(
        cap["parsed"], ext["parsed"], joined)
    if not verdict["census_valid"]:
        raise probe.CensusInvalid(
            "capability census invalid; no capability conclusion may be "
            "drawn: " + "; ".join(verdict["failure_reasons"]))

    doc = {
        "schema": "inferswarm.v2e.preflight/2",
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
        "capability_verdict": verdict,
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
    ap.add_argument("--attempt-id", default=ATTEMPT_ID)
    ap.add_argument("--authority", required=True)
    ap.add_argument("--build-dir", default="/var/tmp/issue228-build")
    args = ap.parse_args()
    doc = collect_preflight(repo=Path(args.repo), out=Path(args.out),
                            attempt_id=args.attempt_id,
                            authority_path=Path(args.authority),
                            build_dir=Path(args.build_dir))
    print(json.dumps({"preflight": str(Path(args.out) / "preflight.json"),
                      "census_valid":
                          doc["capability_verdict"]["census_valid"],
                      "capable_mechanisms":
                          doc["capability_verdict"]["capable_mechanisms"],
                      "group": doc["capability_verdict"]["group"],
                      "peer_directions":
                          doc["capability_verdict"]["peer_features"][
                              "directions"],
                      "external_memory":
                          doc["capability_verdict"]["external_memory"][
                              "usable_handle_types"]},
                         indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
