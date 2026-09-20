#!/usr/bin/env python3
"""Issue #232 — V2-G Phase 0/1 collectors: census + bounded observation.

`census` collects the full read-only post-boot census (identity,
topology, link state, AER counters, journal snapshot) — the Phase 0
record and the before/after state for every intervention.

`observe` runs ONE bounded idle observation interval (fixed minutes,
no GPU workload before the clean-link gate): AER sysfs counters +
journal event census at both ends, rates computed from the deltas.
This is the Phase 1 idle/background RxErr behavior record and the
Phase 3 gate input.

`intervention` records ONE physical configuration delta BEFORE the
boot that will exercise it (issue Phase 2: "record every change before
booting"). The declared delta must name exactly one component/variable
(control 6); a bundle must declare itself a bundle, and improvement is
never attributed to an individual member of a bundle.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import issue232_receipt as rc
import issue232_host as host
import issue232_authority as pa

ROOT = Path(__file__).resolve().parents[1]

HEALTH_BDFS = (
    "0000:06:00.0", "0000:09:00.0",      # the dies (historical; census
    "0000:02:00.0", "0000:03:00.0", "0000:03:01.0",  # re-derives)
    "0000:00:1d.0", "0000:0a:00.0",
)

INTERVENTION_COMPONENTS = (
    "pm8533_upstream_reseat",     # reseat the switch card / its slot
    "pm8533_upstream_slot_move",  # move to a different PCH x1 slot
    "pm8533_upstream_contact_clean",  # clean contacts / inspect for
                                      # bent pins / mechanical strain
    "die_reseat",                 # reseat V340L / its slot or cabling
    "aux_power_verify",           # auxiliary power/connector integrity
    "bundle_declared",            # unavoidable multiple changes — NO
                                  # individual attribution allowed
)


class BaselineError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def collect_census(*, repo: Path, out: Path, note: str | None = None
                   ) -> dict[str, Any]:
    """Phase 0 census: identity + topology + link + AER + journal
    snapshot, all retained as raw bytes with a bound receipt."""
    closure = rc.verify_closure(repo)
    authority = json.loads(
        (repo / rc.AREA_REL / "PHYSICAL-AUTHORITY.json")
        .read_text(encoding="utf-8"))
    if not pa.verify_authority(authority, repo):
        raise pa.AuthorityError("authority invalid at census")

    raw = out / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    probes: list[dict[str, Any]] = []

    def art(name: str, argv: list[str], timeout: int = 120,
            optional: bool = False) -> dict[str, Any]:
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

    art("boot_id", ["cat", "/proc/sys/kernel/random/boot_id"])
    boot = host.boot_id()
    art("uname", ["uname", "-a"])
    art("kernel_cmdline", ["cat", "/proc/cmdline"])
    art("uptime", ["cat", "/proc/uptime"])
    art("dmidecode_baseboard", ["sudo", "-n", "dmidecode", "-t",
                                "baseboard", "-t", "bios"], timeout=60)
    art("amdgpu_version", ["cat", "/sys/module/amdgpu/version"],
        optional=True)
    art("vulkan_loader", ["dpkg-query", "-W",
                          "-f=${Version}\\n", "libvulkan1"])
    art("icd_list", ["ls", "-la", "/usr/share/vulkan/icd.d/"])
    art("lspci_nn", ["lspci", "-nn"])
    art("lspci_tree", ["lspci", "-tv"])
    art("lspci_vv_full", ["lspci", "-PP", "-nn", "-vv", "-d",
                          "11f8:8533"], timeout=180)
    # per-BDF vv for EVERY bus-00 bridge + Vega row: root-port device
    # ids differ across slots (a294/a295/a29a on this PCH family) —
    # never collect by a single hardcoded id
    nn_rows0 = host.parse_lspci_nn(
        (raw / "lspci_nn.stdout").read_text(encoding="utf-8"))
    for _bdf in host.bus00_bridge_bdfs(nn_rows0):
        art(f"lspci_vv_s_{_bdf.replace(':', '-')}",
            ["lspci", "-PP", "-nn", "-vv", "-s",
             _bdf.removeprefix("0000:")], timeout=180)
    art("lspci_vv_vega", ["lspci", "-PP", "-nn", "-vv", "-d",
                          "1002:6864"], timeout=180)
    art("render_nodes", ["ls", "-la", "/dev/dri/by-path/"])
    # previous-boot termination evidence (cold-vs-warm proof input):
    # a real power cut ends the journal with NO reboot.target and
    # leaves a shutdown record in `last -x`
    art("prev_boot_journal_tail",
        ["sudo", "-n", "journalctl", "-b", "-1", "-k", "--no-pager",
         "-n", "200"], optional=True)
    art("prev_boot_last_reboot", ["last", "-x", "reboot", "shutdown",
                                  "-n", "12"], optional=True)
    art("lsusb", ["lsusb"])
    art("nic_state", ["ip", "-brief", "link"])
    art("storage", ["df", "-h", "/"])
    art("gateway_ping", ["ping", "-c", "3", "-W", "2", "10.0.0.1"])

    # derive the CURRENT chain from the fresh bytes (never historical
    # literals — control 1)
    nn_text = (raw / "lspci_nn.stdout").read_text(encoding="utf-8")
    tree_text = (raw / "lspci_tree.stdout").read_text(encoding="utf-8")
    vv_parts = [(raw / "lspci_vv_full.stdout").read_text(
        encoding="utf-8")]
    for _p in sorted(raw.glob("lspci_vv_s_*.stdout")):
        vv_parts.append(_p.read_text(encoding="utf-8"))
    vv_parts.append((raw / "lspci_vv_vega.stdout").read_text(
        encoding="utf-8"))
    vv_text = "\n".join(vv_parts)
    chain = host.derive_chain(nn_text, tree_text, vv_text)
    rows = host.parse_lspci_nn(nn_text)
    vega_rows = [r for r in rows if r["id"] == host.VEGA_ID]
    if len(vega_rows) != 2:
        raise BaselineError(
            f"expected exactly two Vega dies, found {len(vega_rows)}")

    aer = {bdf: host.aer_counters(bdf) for bdf in
           sorted({chain["root_port_bdf"],
                   chain["switch_upstream_bdf"]}
                  | {r["bdf"] for r in vega_rows}
                  | {"0000:0a:00.0", "0000:00:1c.0", "0000:00:1d.3"})}
    # 0000:02:00.0/03:00.0/03:01.0 may be stale post-move; census uses
    # the derived chain BDFs (recorded above under their CURRENT bdf)
    journal = host.journal_scan()
    host.durable_write(raw / "journal_faults.stdout",
                       journal["text"].encode())
    census_event_census = host.aer_event_census(journal["text"])
    host.durable_write(
        raw / "aer_event_census.json",
        json.dumps(census_event_census, indent=1,
                   sort_keys=True).encode())

    link_sysfs = {bdf: host.link_state(bdf) for bdf in aer}
    cold_cycle = None
    prev_tail_path = raw / "prev_boot_journal_tail.stdout"
    prev_last_path = raw / "prev_boot_last_reboot.stdout"
    if prev_tail_path.is_file() and prev_last_path.is_file():
        tail = prev_tail_path.read_text(encoding="utf-8")
        lastx = prev_last_path.read_text(encoding="utf-8")
        # a warm reboot records reboot.target before the journal ends
        ended_without_reboot_target = "reboot.target" not in tail
        shutdown_record_present = (
            re.search(r"^shutdown system down", lastx, re.M) is not None)
        cold_cycle = {
            "prev_boot_ended_without_reboot_target":
                ended_without_reboot_target,
            "shutdown_record_present": shutdown_record_present,
            "prev_tail_sha256": rc.sha256_bytes(tail.encode()),
            "last_x_sha256": rc.sha256_bytes(lastx.encode()),
        }
    doc = {
        "schema": "inferswarm.v2g.census/1",
        "campaign_id": rc.CAMPAIGN_ID,
        "census_id": f"v2g-census-{int(time.time())}",
        "collected_utc": _now(),
        "boot_id": boot,
        "note": note,
        "cold_cycle_evidence": cold_cycle,
        "authority_digest": authority["authority_digest"],
        "closure_digest": closure["closure_digest"],
        "producer_head": closure["producer_head"],
        "derived_chain": chain,
        "vega_bdfs": sorted(r["bdf"] for r in vega_rows),
        "aer_counters": aer,
        "link_sysfs": link_sysfs,
        "journal_fault_counts": journal["counts"],
        "journal_aer_event_census": census_event_census,
        "probes": probes,
        "host_health": host.host_health(),
        "nic": host.nic_sentinel(),
        "storage": host.storage_sentinel(),
    }
    host.durable_write(out / "census.json",
                       json.dumps(doc, indent=1, sort_keys=True).encode()
                       + b"\n")
    return doc


def run_observation(*, repo: Path, out: Path, minutes: int,
                    note: str | None = None) -> dict[str, Any]:
    """One bounded idle observation interval (Phase 1 / gate input).

    Samples AER sysfs counters + journal cursor at both ends of a fixed
    interval and computes event rates from the deltas. The GPUs get NO
    workload from this tool (nothing before the clean-link gate).
    """
    if minutes <= 0:
        raise BaselineError("observation interval must be positive")
    closure = rc.verify_closure(repo)
    boot = host.boot_id()

    nn0 = host.run_probe(["lspci", "-nn"])["stdout"]
    tree0 = host.run_probe(["lspci", "-tv"])["stdout"]
    vv0 = host.collect_vv_bytes()
    live_chain = host.derive_chain(nn0, tree0, vv0)
    chain_bdfs = _current_chain_bdfs(repo, live_chain)

    start_aer = {bdf: host.aer_counters(bdf) for bdf in chain_bdfs}
    start_monotonic = time.monotonic_ns()
    j0 = host.journal_scan()
    start_wall = _now()

    time.sleep(minutes * 60)

    end_aer = {bdf: host.aer_counters(bdf) for bdf in chain_bdfs}
    end_monotonic = time.monotonic_ns()
    j1 = host.journal_scan(cursor=j0["next_cursor"])
    end_wall = _now()

    census = host.aer_event_census(j1["text"])
    raw = out / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    host.durable_write(raw / "journal-delta.stdout",
                       j1["text"].encode())
    host.durable_write(raw / "journal-delta-census.json",
                       json.dumps(census, indent=1,
                                  sort_keys=True).encode())

    elapsed_min = (end_monotonic - start_monotonic) / 60e9
    deltas: dict[str, Any] = {}
    rates: dict[str, Any] = {}
    for bdf in chain_bdfs:
        row: dict[str, Any] = {}
        for cls in ("aer_dev_correctable", "aer_dev_nonfatal",
                    "aer_dev_fatal"):
            b = start_aer[bdf].get(cls)
            a = end_aer[bdf].get(cls)
            if isinstance(b, dict) and isinstance(a, dict):
                row[cls] = {k: a.get(k, 0) - b.get(k, 0)
                            for k in sorted(set(b) | set(a))}
            else:
                row[cls] = None
        deltas[bdf] = row
        corr = row.get("aer_dev_correctable") or {}
        total_corr = sum(v for v in corr.values()
                         if isinstance(v, int) and v > 0)
        rates[bdf] = {
            "correctable_events": total_corr,
            "rate_per_minute": (total_corr / elapsed_min
                                if elapsed_min > 0 else None),
        }
    nn = host.run_probe(["lspci", "-nn"])["stdout"]
    tree = host.run_probe(["lspci", "-tv"])["stdout"]
    vv = host.collect_vv_bytes()
    chain = host.derive_chain(nn, tree, vv)
    doc = {
        "schema": "inferswarm.v2g.observation/1",
        "campaign_id": rc.CAMPAIGN_ID,
        "observation_id": f"v2g-obs-{int(time.time())}",
        "note": note,
        "boot_id": boot,
        "started_utc": start_wall,
        "ended_utc": end_wall,
        "requested_minutes": minutes,
        "elapsed_minutes": elapsed_min,
        "chain_bdfs": chain_bdfs,
        "chain_roles": {
            "root_port": chain["root_port_bdf"],
            "switch_upstream": chain["switch_upstream_bdf"],
            "root_port_sta": chain["root_port_sta"],
            "switch_upstream_sta": chain["switch_upstream_sta"],
            "root_port_cap": chain["root_port_cap"],
            "switch_upstream_cap": chain["switch_upstream_cap"],
        },
        "aer_start": start_aer,
        "aer_end": end_aer,
        "aer_deltas": deltas,
        "rates": rates,
        "journal_census_delta": census,
        "journal_fault_counts": j1["counts"],
        "nic": host.nic_sentinel(),
        "storage": host.storage_sentinel(),
        "link_sysfs_end": {bdf: host.link_state(bdf)
                           for bdf in chain_bdfs},
        "host_health": host.host_health(),
        "closure_digest": closure["closure_digest"],
        "producer_head": closure["producer_head"],
    }
    host.durable_write(
        out / "observation.json",
        json.dumps(doc, indent=1, sort_keys=True).encode() + b"\n")
    return doc


def record_intervention(*, repo: Path, out: Path, component: str,
                        description: str, pre_census_rel: str,
                        declared_bundle: bool = False) -> dict[str, Any]:
    """Record ONE physical configuration delta BEFORE the boot that
    exercises it (control 6: one variable at a time, else a declared
    bundle with no individual attribution)."""
    if component not in INTERVENTION_COMPONENTS:
        raise BaselineError(
            f"unknown intervention component {component!r}; choose from "
            f"{INTERVENTION_COMPONENTS}")
    if declared_bundle and component != "bundle_declared":
        raise BaselineError(
            "a bundle must use component='bundle_declared'")
    if not declared_bundle and component == "bundle_declared":
        raise BaselineError(
            "bundle_declared requires declared_bundle=true")
    if not description or len(description) > 2000:
        raise BaselineError("intervention needs a 1..2000 char "
                            "description of the physical delta")
    # pre-census rel paths are EVIDENCE-ROOT-relative (census docs
    # record them that way); resolve against the evidence root that
    # holds the interventions dir
    pre = out.parent / pre_census_rel
    if not pre.is_file():
        raise BaselineError(f"pre-census not found: {pre_census_rel} "
                            f"(looked in {out.parent})")
    closure = rc.verify_closure(repo)
    doc = {
        "schema": "inferswarm.v2g.intervention/1",
        "campaign_id": rc.CAMPAIGN_ID,
        "intervention_id": f"v2g-iv-{int(time.time())}",
        "recorded_utc": _now(),
        "component": component,
        "declared_bundle": declared_bundle,
        "attribution_policy": (
            "NO individual component attribution for a declared bundle"
            if declared_bundle else
            f"single variable: {component}"),
        "description": description,
        "pre_census_rel": pre_census_rel,
        "pre_census_sha256": rc.sha256_bytes(pre.read_bytes()),
        "operator_declared": True,
        "closure_digest": closure["closure_digest"],
        "producer_head": closure["producer_head"],
    }
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"{doc['intervention_id']}.json"
    if target.exists():
        raise BaselineError("duplicate intervention id")
    host.durable_write(target,
                       json.dumps(doc, indent=1, sort_keys=True).encode()
                       + b"\n")
    return doc


def _current_chain_bdfs(repo: Path,
                        chain: dict[str, Any] | None = None
                        ) -> list[str]:
    """Fresh chain BDFs from live lspci (root port, switch upstream,
    both dies, sibling endpoints for regression watching)."""
    if chain is None:
        nn = host.run_probe(["lspci", "-nn"])["stdout"]
        tree = host.run_probe(["lspci", "-tv"])["stdout"]
        vv = host.collect_vv_bytes()
        chain = host.derive_chain(nn, tree, vv)
        rows = host.parse_lspci_nn(nn)
    else:
        rows = host.parse_lspci_nn(
            host.run_probe(["lspci", "-nn"])["stdout"])
    vegas = sorted(r["bdf"] for r in rows if r["id"] == host.VEGA_ID)
    if len(vegas) != 2:
        raise BaselineError(f"expected 2 Vega dies, saw {vegas}")
    others = sorted(r["bdf"] for r in rows
                    if r["id"] in ("10ec:8168", "8086:a2af",
                                   "10de:2489"))
    bdfs = sorted({chain["root_port_bdf"],
                   chain["switch_upstream_bdf"], *vegas, *others})
    return bdfs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(ROOT))
    ap.add_argument("--evidence-root", required=True)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("census")
    c.add_argument("--note")
    o = sub.add_parser("observe")
    o.add_argument("--minutes", type=int, required=True)
    o.add_argument("--note")
    i = sub.add_parser("intervention")
    i.add_argument("--component", required=True)
    i.add_argument("--description", required=True)
    i.add_argument("--pre-census-rel", required=True)
    i.add_argument("--declared-bundle", action="store_true")
    args = ap.parse_args()

    repo = Path(args.repo)
    ev = Path(args.evidence_root)

    if args.cmd == "census":
        out = ev / "censuses" / datetime.now(timezone.utc).strftime(
            "%Y%m%dT%H%M%SZ")
        doc = collect_census(repo=repo, out=out, note=args.note)
        print(json.dumps({"census": str(out / "census.json"),
                          "boot_id": doc["boot_id"],
                          "chain": [doc["derived_chain"]["root_port_bdf"],
                                    doc["derived_chain"]["switch_upstream_bdf"]],
                          "vega_bdfs": doc["vega_bdfs"]}, indent=1))
        return 0
    if args.cmd == "observe":
        out = ev / "observations" / datetime.now(
            timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        doc = run_observation(repo=repo, out=out, minutes=args.minutes,
                              note=args.note)
        print(json.dumps({"observation": str(out / "observation.json"),
                          "minutes": doc["elapsed_minutes"],
                          "rates": doc["rates"]}, indent=1))
        return 0
    if args.cmd == "intervention":
        doc = record_intervention(
            repo=repo, out=ev / "interventions",
            component=args.component, description=args.description,
            pre_census_rel=args.pre_census_rel,
            declared_bundle=args.declared_bundle)
        print(json.dumps({"intervention": doc["intervention_id"],
                          "component": doc["component"]}, indent=1))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
