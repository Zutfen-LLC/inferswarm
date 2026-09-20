#!/usr/bin/env python3
"""Issue #232 — replay boot/topology continuity proof (reduction-only).

2026-09-20 correction (PR #233 review): the retained replay arm records
bind the live-derived root port (00:1d.0) and upstream (02:00.0) but
carry no boot id, and the retained gate evaluation was fed a stale
motherboard-slot census (root 00:1c.5). This producer MECHANICALLY
binds which boot executed the replay from retained bytes plus ONE
read-only live probe — it executes no campaign phase and collects no
new physical evidence:

  1. the cold-confirmation census (20260920T150632Z) records boot
     433128ac… with its monotonic clock and collection time;
  2. the qualification record (same boot) pins boot_id + live-derived
     chain (root 00:1d.0, upstream 02:00.0, negotiated width);
  3. a POST-CAMPAIGN read-only probe (retained raw bytes, clearly
     labeled as such) shows the host STILL on boot 433128ac… with an
     uptime whose arithmetic anchors to the census monotonic clock —
     proving NO reboot occurred anywhere between the census and the
     probe, an interval that contains the entire replay window (order
     state recorded_utc values);
  4. therefore every arm executed on boot 433128ac… = the
     cold-confirmation/qualification boot, on the daughterboard-return
     topology (root 00:1d.0) — the same topology the corrected gate
     binds.

Fails closed on ANY mismatch. The uptime tolerance is generous
(seconds) yet decisive: a reboot resets uptime to ~0 and changes the
boot id, breaking both equality axes by orders of magnitude.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue232_receipt as rc
import issue232_host as host

SCHEMA = "inferswarm.v2g.boot-proof/1"

#: uptime |drift| tolerance in seconds: covers clock read skew between
#: the remote probe's date/uptime pair (two separate reads) and the
#: census's monotonic/utc pair. A reboot breaks equality by the whole
#: observed uptime (~thousands of seconds), never by single digits.
UPTIME_TOLERANCE_S = 5.0


class BootProofError(RuntimeError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not doc:
        raise BootProofError(f"empty artifact: {path}")
    return doc


def _parse_utc(text: str) -> datetime:
    return datetime.fromisoformat(text)


def parse_probe(raw: str) -> dict[str, Any]:
    """Parse the retained live probe stdout (labeled sections)."""
    sections: dict[str, str] = {}
    current = None
    for line in raw.splitlines():
        m = re.match(r"^=== (\S+)$", line.strip())
        if m:
            current = m.group(1)
            sections[current] = ""
        elif current:
            sections[current] += line + "\n"
    if "boot_id" not in sections or "uptime_seconds" not in sections \
            or "probed_utc" not in sections:
        raise BootProofError(
            "probe raw lacks required sections (boot_id/uptime_seconds/"
            "probed_utc)")
    boot_id = sections["boot_id"].strip()
    uptime = float(sections["uptime_seconds"].strip())
    probed_utc = sections["probed_utc"].strip()
    if not boot_id or uptime <= 0:
        raise BootProofError("malformed probe boot_id/uptime")
    tree = sections.get("lspci_tree", "")
    vegas = re.findall(
        r"\[(\d+)\]----00\.0\s+Advanced.*?Vega", tree)
    pm = re.findall(r"^\s*(\S+)\s*-?\[?(\d+)", sections.get("lspci_nn", ""),
                    re.M)
    return {
        "boot_id": boot_id,
        "uptime_seconds": uptime,
        "probed_utc": probed_utc,
        "kernel": sections.get("kernel", "").strip(),
        "vega_bdfs_from_tree": [f"0000:{b}:00.0" for b in vegas],
        "lspci_nn": sections.get("lspci_nn", ""),
        "lspci_tree": tree,
    }


def build_boot_proof(*, evidence_root: Path,
                     probe_raw_rel: str,
                     anchor_census_rel: str) -> dict[str, Any]:
    ev = evidence_root
    census = _load_json(ev / anchor_census_rel / "census.json")
    if census.get("schema") != "inferswarm.v2g.census/1":
        raise BootProofError("anchor census is not a V2-G census")
    qual = _load_json(ev / "qualification" / "qualification.json")
    if qual.get("schema") != "inferswarm.v2g.qualification/1":
        raise BootProofError("bad qualification schema")
    order = _load_json(ev / "replay-order-state.json")
    if order.get("schema") != "inferswarm.v2g.replay-order/1":
        raise BootProofError("bad order-state schema")
    # digest-chain verify the order state (the arm windows we bind)
    import issue232_replay as replay_mod
    replay_mod._verify_chain(order)

    probe_raw = (ev / probe_raw_rel).read_text(encoding="utf-8")
    if not probe_raw.strip():
        raise BootProofError("empty probe raw (capture fault)")
    probe = parse_probe(probe_raw)

    census_boot = census["boot_id"]
    mono_s = census["host_health"]["monotonic_ns"] / 1e9
    census_utc = _parse_utc(census["collected_utc"])
    probe_utc = _parse_utc(probe["probed_utc"])

    # --- boot continuity: same boot id + uptime arithmetic ----------
    if probe["boot_id"] != census_boot:
        raise BootProofError(
            f"host has rebooted since the anchor census "
            f"(census {census_boot[:8]}…, probe {probe['boot_id'][:8]}…) "
            "— replay boot binding is NOT mechanically recoverable; "
            "renewed physical authorization would be required")
    elapsed = (probe_utc - census_utc).total_seconds()
    expected = mono_s + elapsed
    drift = abs(expected - probe["uptime_seconds"])
    if drift > UPTIME_TOLERANCE_S:
        raise BootProofError(
            f"uptime arithmetic diverges (expected ~{expected:.1f}s, "
            f"observed {probe['uptime_seconds']:.1f}s, drift "
            f"{drift:.1f}s > {UPTIME_TOLERANCE_S}s) — a reboot or "
            "suspend broke continuity; fail closed")

    # the boot began before the census was collected on it
    boot_start = probe_utc.timestamp() - probe["uptime_seconds"]
    if boot_start > census_utc.timestamp():
        raise BootProofError(
            "boot start arithmetic places the current boot AFTER the "
            "anchor census collection — impossible for the same boot")

    # --- qualification agreement (same boot, live-derived chain) ----
    qchain = qual.get("chain") or {}
    qual_boot = qual.get("boot_id")
    if qual_boot != census_boot:
        raise BootProofError(
            f"qualification boot {qual_boot!r} != anchor census boot "
            f"{census_boot!r}")
    if qchain.get("root_port_bdf") \
            != (census.get("derived_chain") or {}).get("root_port_bdf"):
        raise BootProofError(
            "qualification chain root != anchor census derived root")
    if qchain.get("switch_upstream_bdf") \
            != (census.get("derived_chain") or {}
                ).get("switch_upstream_bdf"):
        raise BootProofError(
            "qualification chain upstream != anchor census upstream")

    # --- arm window inside the continuous interval ------------------
    recorded = [e["recorded_utc"] for e in order.get("entries", [])]
    if not recorded:
        raise BootProofError("order state has no arm entries")
    first_arm = _parse_utc(min(recorded))
    last_arm = _parse_utc(max(recorded))
    if not (census_utc <= first_arm and last_arm <= probe_utc):
        raise BootProofError(
            "arm window not contained in the continuous-boot interval "
            f"({census_utc.isoformat()} .. {probe_utc.isoformat()}); "
            f"arms {first_arm.isoformat()}..{last_arm.isoformat()}")

    # --- topology: census-derived + arm live-derived + probe corrob --
    chain = census["derived_chain"]
    topology = {
        "root_port": chain["root_port_bdf"],
        "switch_upstream": chain["switch_upstream_bdf"],
        "vega_bdfs": sorted(census.get("vega_bdfs") or []),
        "negotiated_width":
            (chain.get("switch_upstream_sta") or {}).get("width"),
        "root_port_width":
            (chain.get("root_port_sta") or {}).get("width"),
    }
    # corroborate with the live probe tree: the Vega chain must sit
    # under the SAME root port today (read-only, present-day)
    vegalines = [l for l in probe["lspci_tree"].splitlines()
                 if "Vega" in l]
    if not vegalines:
        raise BootProofError(
            "probe tree shows no Vega chain — cannot corroborate "
            "present-day topology")
    m_rp = re.search(r"([0-9a-f]{2}\.[0-9a-f])-\[\d+-\d+\]----00\.0",
                     vegalines[0])
    # tree tokens are dev.fn under the 00 root bus: 1d.0 -> 0000:00:1d.0
    probe_root = (f"0000:00:{m_rp.group(1)}"
                  if m_rp else None)
    if probe_root != topology["root_port"]:
        raise BootProofError(
            "present-day probe tree root differs from the anchor "
            f"topology ({probe_root} vs "
            f"{topology['root_port']}) — hardware moved after the "
            "campaign; continuity cannot be corroborated")

    # --- V340 identities from the retained arm identity probes ------
    vega_uuids: dict[str, str] = {}
    for arm_path in sorted((ev / "arms").glob("replay-*.json")):
        arm = _load_json(arm_path)
        idy_rel = f"raw/{arm['arm']}-identity.stdout"
        idy = _load_json(ev / idy_rel)
        for dev in idy.get("devices", []):
            bdf = dev.get("bdf")
            if bdf:
                if bdf in vega_uuids and vega_uuids[bdf] != dev["uuid"]:
                    raise BootProofError(
                        f"conflicting UUID for {bdf} across arms")
                vega_uuids[bdf] = dev["uuid"]
    if sorted(vega_uuids) != topology["vega_bdfs"]:
        raise BootProofError(
            f"arm identity joins {sorted(vega_uuids)} != census vega "
            f"set {topology['vega_bdfs']}")

    doc = {
        "schema": SCHEMA,
        "campaign_id": rc.CAMPAIGN_ID,
        "kind": ("reduction-only post-campaign continuity proof; no "
                 "campaign phase executed; the live probe is a "
                 "read-only present-day observation, labeled as such"),
        "probe": {
            "raw_rel": probe_raw_rel,
            "raw_sha256": rc.sha256_bytes(probe_raw.encode()),
            "probed_utc": probe["probed_utc"],
            "boot_id": probe["boot_id"],
            "uptime_seconds": probe["uptime_seconds"],
            "kernel": probe["kernel"],
        },
        "continuity": {
            "anchor_census_rel": anchor_census_rel,
            "anchor_census_boot_id": census_boot,
            "anchor_census_collected_utc": census["collected_utc"],
            "anchor_census_monotonic_s": mono_s,
            "expected_probe_uptime_s": expected,
            "observed_probe_uptime_s": probe["uptime_seconds"],
            "drift_s": drift,
            "tolerance_s": UPTIME_TOLERANCE_S,
            "boot_start_utc": datetime.fromtimestamp(
                boot_start, timezone.utc).isoformat(),
            "arm_window_utc": [min(recorded), max(recorded)],
            "arm_window_inside_interval": True,
            "order_state_chain_digest": order.get("chain_digest"),
        },
        "qualification_binding": {
            "boot_id": qual_boot,
            "collected_utc": qual.get("collected_utc"),
            "root_port": qchain.get("root_port_bdf"),
            "switch_upstream": qchain.get("switch_upstream_bdf"),
        },
        "replay_boot_id": census_boot,
        "topology": topology,
        "v340_uuids": vega_uuids,
    }
    return doc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence-root", required=True)
    ap.add_argument("--probe-raw-rel", required=True)
    ap.add_argument("--anchor-census-rel", required=True)
    ap.add_argument("--out-rel", default="boot-proof.json")
    args = ap.parse_args()
    doc = build_boot_proof(
        evidence_root=Path(args.evidence_root),
        probe_raw_rel=args.probe_raw_rel,
        anchor_census_rel=args.anchor_census_rel)
    out = Path(args.evidence_root) / args.out_rel
    host.durable_write(out, json.dumps(doc, indent=1,
                                       sort_keys=True).encode() + b"\n")
    print(json.dumps({
        "replay_boot_id": doc["replay_boot_id"],
        "root_port": doc["topology"]["root_port"],
        "drift_s": doc["continuity"]["drift_s"],
        "out": str(out)}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
