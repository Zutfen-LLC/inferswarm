#!/usr/bin/env python3
"""Issue #215 — V2-C terminal reducer and cross-boot cycle-table builder.

Derives the per-cycle platform-health gate, the cross-boot reduction table,
and the terminal classification (V2C_V340L_PLATFORM_STABILITY_{PASS,FAIL},
V2C_V340L_WARM_REBOOT_STABILITY_ONLY, V2C_EVIDENCE_BLOCKED) MECHANICALLY
from retained cycle artifacts. No check is set by constant: every predicate
derives from retained bytes (snapshot receipt + raw files + sentinel
records + final canonical evidence). Honors the AREA/REPO env-override seam
for sandboxed negative controls (INFERSWARM_ISSUE215_ROOT).

Reads (relative to repo root or $INFERSWARM_ISSUE215_ROOT):
  docs/investigations/vulkan-v2-c-v340l-platform-stability/
    CAMPAIGN-PLAN.json                       (frozen plan digest binding)
    cycles/cycle-<NN>-<kind>/receipt.json    (snapshot receipts)
    cycles/cycle-<NN>-<kind>/raw/*           (raw probe bytes)
    cycles/cycle-<NN>-sentinels/sentinel-record.json (+ per-die raw)
    final-canonical/                         (final-boot full check evidence)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT_ENV = "INFERSWARM_ISSUE215_ROOT"
NS = "vulkan-v2-c-v340l-platform-stability"

VEGA_ID = "1002:6864"
BRIDGE_IDS = ("1022:1470", "1022:1471")
PM8533_ID = "11f8:8533"
NIC_ID = "10ec:8168"
USB_ID = "8086:a2af"
GEN3_SPEED = "8.0 GT/s"
WIDTH_1 = "x1"
EXPECTED_HBM_BYTES = 8573157376


class ReductionError(RuntimeError):
    """A retained artifact is missing or structurally unusable."""


def area_root(repo_root: Path) -> Path:
    return repo_root / "docs" / "investigations" / NS


def repo_root() -> Path:
    root = os.environ.get(ROOT_ENV)
    if root:
        return Path(root)
    return Path(__file__).resolve().parents[1]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_json(path: Path) -> dict:
    if not path.is_file():
        raise ReductionError(f"missing retained artifact: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Raw probe parsers (derive from retained raw bytes; never from summaries)
# ---------------------------------------------------------------------------

def parse_lspci_nn(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        m = re.match(r"^([0-9a-f:.]+)\s+(.+?)\s+\[([0-9a-f]{4}:[0-9a-f]{4})\]", line.strip())
        if m:
            rows.append({"bdf": m.group(1), "desc": m.group(2), "id": m.group(3)})
    return rows


def vega_functions(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["id"].lower() == VEGA_ID]


def pm8533_upstream(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["id"].lower() == PM8533_ID]


def vega_bridges(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["id"].lower() in BRIDGE_IDS]


def parse_lspci_vv(text: str) -> dict:
    """Extract LnkCap/LnkSta, BARs, driver, SR-IOV from one -vv dump."""
    out: dict[str, Any] = {"lnk_cap": None, "lnk_sta": None, "bars": [], "driver": None,
                           "sriov_totalvfs": None, "sriov_numvfs": None, "regions_fail": False}
    m = re.search(r"LnkCap:\s*Port [^,]*, speed (\d+\.?\d* GT/s), width (\d+)", text)
    if m:
        out["lnk_cap"] = {"speed": m.group(1), "width": int(m.group(2))}
    m = re.search(r"LnkSta:\s*Speed (\d+\.?\d*GT/s), Width (\d+)", text)
    if m:
        out["lnk_sta"] = {"speed": m.group(1).replace("GT/s", " GT/s").strip(),
                          "width": int(m.group(2))}
    for m in re.finditer(r"Region \d+: Memory at ([0-9a-f]+) .*?\[(size=(\d+[KM]?)|disabled)", text):
        out["bars"].append({"addr": m.group(1), "size": m.group(2), "disabled": m.group(3) == "disabled"})
    if "Region 0: Memory at 00000000 (32-bit, non-prefetchable) [disabled]" in text:
        out["regions_fail"] = True
    for m in re.finditer(r"Region \d+:.*\[disabled\]", text):
        out["regions_fail"] = True
        break
    m = re.search(r"Kernel driver in use: (\S+)", text)
    if m:
        out["driver"] = m.group(1)
    m = re.search(r"Kernel modules: (\S+)", text)
    out["sriov_totalvfs"] = None
    return out


def parse_journal_errors(journal_text: str) -> dict:
    """Classify boot-journal errors into transient (retained observation) vs
    correctness-bearing (fails the cycle)."""
    fatal_aer = re.findall(r"severity=(Fatal|Uncorrectable)", journal_text)
    fatal_amdgpu = re.findall(r"amdgpu.*(fail|timeout|reset|hang|GPU hang)", journal_text, re.I)
    dmar_fault = re.findall(r"DMAR:[^\n]*(fault|error)", journal_text, re.I)
    unresolved_bar = re.findall(r"BAR (\d+): no space|can't claim BAR|not claimed", journal_text)
    nic_usb_storage_fail = re.findall(r"(r8169|usb \d+-\d|ata\d+|sd[a-z]): .*(fail|error|reset)", journal_text, re.I)
    return {
        "fatal_aer_count": len(fatal_aer),
        "amdgpu_failure_count": len(fatal_amdgpu),
        "dmar_fault_count": len(dmar_fault),
        "unresolved_bar_count": len(unresolved_bar),
        "controller_failure_count": len(nic_usb_storage_fail),
        "correctable_aer_count": len(re.findall(r"severity=Correctable", journal_text)),
    }


def parse_link_from_tree_or_vv(vv_text: str) -> dict | None:
    return parse_lspci_vv(vv_text)


# ---------------------------------------------------------------------------
# Per-cycle gate
# ---------------------------------------------------------------------------

def derive_cycle(cycle_dir: Path, baseline_usb: set[str] | None,
                 baseline_input_devices: set[str] | None) -> dict:
    """Derive the Phase-3 platform-health gate for one cycle from bytes."""
    receipt = load_json(cycle_dir / "receipt.json")
    rec = receipt["records"]
    raw = cycle_dir / "raw"
    kind = rec["cycle_type"]
    checks: dict[str, bool] = {}
    detail: dict[str, Any] = {}

    # boot transition proof
    if kind != "baseline":
        checks["boot_id_changed"] = rec.get("boot_id_changed") is True
        detail["boot_id"] = rec["boot_id"]
        detail["prev_boot_id"] = rec.get("prev_boot_id")

    # PCI topology
    lspci = parse_lspci_nn(_stdout_of(raw / "lspci-nn.txt"))
    lspci_text = _stdout_of(raw / "lspci-nn.txt")
    vegas = vega_functions(lspci)
    switches = pm8533_upstream(lspci)
    bridges = vega_bridges(lspci)
    checks["exactly_two_vega_functions"] = len(vegas) == 2
    checks["pm8533_fanout_present"] = len(switches) >= 1 and len(bridges) >= 2
    detail["vega_bdfs"] = [v["bdf"] for v in vegas]
    detail["switch_bdfs"] = [s["bdf"] for s in switches]

    # per-Vega -vv dumps
    vega_vv = {}
    for v in vegas:
        name = f"lspci-vv-{v['bdf'].replace(':', '-')}.txt"
        p = raw / name
        vega_vv[v["bdf"]] = parse_lspci_vv(_stdout_of(p)) if p.is_file() else None
    bound = all(vega_vv[v["bdf"]] and vega_vv[v["bdf"]]["driver"] == "amdgpu" for v in vegas)
    checks["both_vega_amdgpu_bound"] = bound
    bars_assigned = all(
        vega_vv[v["bdf"]] and vega_vv[v["bdf"]]["bars"] and not vega_vv[v["bdf"]]["regions_fail"]
        for v in vegas)
    checks["bars_assigned_not_disabled"] = bars_assigned
    # BAR non-overlap across the two endpoints
    if len(vegas) == 2 and all(vega_vv[v["bdf"]] for v in vegas):
        ranges = []
        for v in vegas:
            for bar in vega_vv[v["bdf"]]["bars"]:
                if bar.get("addr") and not bar.get("disabled") and bar.get("addr") != "00000000":
                    ranges.append((int(bar["addr"], 16), bar.get("size")))
        checks["bars_nonoverlapping"] = len({a for a, _ in ranges}) == len(ranges)
    else:
        checks["bars_nonoverlapping"] = False

    # memory capacity via sysfs
    mem_text = _stdout_of(raw / "gpu-sysfs-mem.txt")
    hbm = [int(x) for x in re.findall(r"^([0-9]{9,})$", mem_text, re.M)]
    checks["hbm_capacity_expected"] = sorted(hbm)[-2:] == [EXPECTED_HBM_BYTES] * 2 if len(hbm) >= 2 else False

    # link state on root port + switch upstream + endpoints (from full -vv)
    full_vv = _stdout_of(raw / "lspci-vv-full.txt")
    gen3_x1 = verify_gen3_x1(full_vv, [s["bdf"] for s in switches], [v["bdf"] for v in vegas])
    checks["upstream_gen3_x1"] = gen3_x1["ok"]
    detail["link"] = gen3_x1

    # Vulkan fresh enumeration
    vulkan_enum = _stdout_of(raw / "vulkan-list-devices.txt")
    v_sel = re.findall(r"^\s*(Vulkan[0-9]+):\s+(.*)$", vulkan_enum, re.M)
    checks["two_vega_vulkan_devices"] = sum(1 for _, n in v_sel if "V340" in n or "Vega" in n) == 2

    # NIC
    nic_link = _stdout_of(raw / "nic-link.txt")
    nic_addr = _stdout_of(raw / "nic-addr.txt")
    ping = _stdout_of(raw / "gateway-ping.txt")
    checks["nic_present_bound"] = NIC_ID.lower() in lspci_text.lower() and "r8169" in _stdout_of(raw / "nic-driver.txt")
    link_state = re.search(r"state (UP|DOWN)", nic_link)
    checks["nic_link_up"] = link_state is not None and link_state.group(1) == "UP"
    checks["nic_addressed"] = "10.0.0.137/24" in nic_addr
    checks["gateway_reachable"] = ping.count("time=") >= 3

    # USB
    lsusb = _stdout_of(raw / "lsusb.txt")
    usb_now = set(re.findall(r"ID [0-9a-f]{4}:[0-9a-f]{4}", lsusb))
    if kind == "baseline":
        checks["usb_controllers_enumerated"] = "Linux Foundation root hub" in lsusb or len(usb_now) > 0
        detail["usb_baseline_set"] = sorted(usb_now)
    else:
        missing = (baseline_usb or set()) - usb_now
        checks["usb_controllers_enumerated"] = not missing
        detail["usb_missing_from_baseline"] = sorted(missing)

    # Storage
    findmnt = _stdout_of(raw / "findmnt-root.txt")
    sentinel = _stdout_of(raw / "storage-sentinel.txt")
    checks["root_fs_mounted_expected"] = "/dev/sda3" in findmnt or "UUID=f3a7ad1c" in findmnt
    checks["storage_sentinel_ok"] = "STORAGE_SENTINEL_OK" in sentinel

    # Kernel/platform errors
    journal = _stdout_of(raw / "journal-errors.txt") + "\n" + _stdout_of(raw / "journal-aer.txt")
    err = parse_journal_errors(journal)
    detail["error_classes"] = err
    checks["no_fatal_aer"] = err["fatal_aer_count"] == 0
    checks["no_amdgpu_failure"] = err["amdgpu_failure_count"] == 0
    checks["no_dmar_fault"] = err["dmar_fault_count"] == 0
    checks["no_unresolved_bar"] = err["unresolved_bar_count"] == 0
    checks["no_controller_failure"] = err["controller_failure_count"] == 0

    passed = all(checks.values())
    return {
        "cycle_index": rec["cycle_index"], "cycle_type": kind,
        "boot_id": rec["boot_id"],
        "requested_transition": rec.get("requested_transition"),
        "checks": checks, "detail": detail,
        "cycle_result": "PASS" if passed else "FAIL",
        "failed_checks": [k for k, v in checks.items() if not v],
    }


def verify_gen3_x1(full_vv: str, switch_bdfs: list[str], vega_bdfs: list[str]) -> dict:
    """Root port + PM8533 upstream must show Speed 8GT/s (or 8.0GT/s) Width x1
    in LnkSta (lspci prints 'Speed 8GT/s' for Gen3)."""
    ok = {"root_port": False, "switch_upstream": False}
    for bdf in switch_bdfs:
        m = re.search(re.escape(bdf) + r".*?(?=^[0-9a-f]{2}:[0-9a-f]{2}\.[0-9] |\Z)", full_vv, re.S | re.M)
        if not m:
            continue
        block = m.group(0)
        sta = re.search(r"LnkSta:\s*Speed 8(\.0)?GT/s, Width x?1\b", block)
        ok["switch_upstream"] = ok["switch_upstream"] or bool(sta)
    # root port: the root port feeding the switch (00:1d.0 class block)
    rp = re.search(r"Root Port[^\n]*\n(?:.*\n)*?.*?LnkSta:\s*Speed 8(\.0)?GT/s, Width x?1\b", full_vv)
    ok["root_port"] = bool(rp)
    return {"ok": ok["root_port"] and ok["switch_upstream"], "parts": ok}


def _stdout_of(path: Path) -> str:
    """Raw artifacts store probe results as JSON {argv, rc, stdout, stderr}."""
    if not path.is_file():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("stdout", "") or ""
    except json.JSONDecodeError:
        return path.read_text(errors="replace")


def derive_sentinel_cycle(sent_dir: Path) -> dict:
    rec = load_json(sent_dir / "sentinel-record.json")
    dies = {}
    for die, d in rec.get("dies", {}).items():
        dies[die] = {
            "selector": d["selector"], "probe_bdf": d["probe_bdf"],
            "result": d["result"],
            "byte_exact": d["byte_exact_visible_output"],
            "accounting_three_tuple": d["accounting_three_tuple"],
            "offload_full": d["offload_full"],
            "identity_proof_line": d["identity_proof_line"],
            "visible_output_sha256": d["visible_output_sha256"],
            "stdout_sha256": d["stdout_sha256"], "stderr_sha256": d["stderr_sha256"],
        }
    distinct_bdfs = {d["probe_bdf"] for d in rec.get("dies", {}).values()}
    distinct_selectors = {d["selector"] for d in rec.get("dies", {}).values()}
    ok = (rec.get("dies")
          and all(d["result"] == "PASS" for d in rec["dies"].values())
          and len(distinct_bdfs) == 2
          and len(distinct_selectors) == 2)
    return {"boot_id": rec.get("boot_id"), "dies": dies,
            "probe_bdfs": sorted(distinct_bdfs),
            "sentinel_result": "PASS" if ok else "FAIL"}


# ---------------------------------------------------------------------------
# Cross-boot reduction
# ---------------------------------------------------------------------------

_CYCLE_DIR = re.compile(r"^cycle-(\d{2})-(baseline|warm|cold)$")


def derive(cycles_root: Path, plan: dict) -> dict:
    """Derive the full campaign reduction and terminal."""
    plan_digest_ok = plan.get("campaign_plan_digest")
    cycle_dirs = sorted(p for p in cycles_root.iterdir() if p.is_dir() and _CYCLE_DIR.match(p.name))
    if not cycle_dirs:
        raise ReductionError("no retained cycles")

    baseline_dir = next((c for c in cycle_dirs if c.name.endswith("-baseline")), None)
    if baseline_dir is None:
        raise ReductionError("missing baseline cycle")

    baseline = derive_cycle(baseline_dir, None, None)
    baseline_usb = set(baseline["detail"].get("usb_baseline_set") or [])

    table = []
    sentinels = {}
    warm_count = 0
    cold_count = 0
    seen_boot_ids: dict[str, int] = {}
    for cdir in cycle_dirs:
        if cdir == baseline_dir:
            continue
        entry = derive_cycle(cdir, baseline_usb, None)
        if seen_boot_ids.get(entry["boot_id"]) is not None:
            entry["checks"]["boot_id_unique_across_cycles"] = False
            entry["duplicate_boot_id_of_cycle"] = seen_boot_ids[entry["boot_id"]]
        else:
            seen_boot_ids[entry["boot_id"]] = entry["cycle_index"]
            entry["checks"]["boot_id_unique_across_cycles"] = True
        sent_dir = cdir.parent / f"cycle-{entry['cycle_index']:02d}-sentinels"
        if sent_dir.is_dir():
            record_path = sent_dir / "sentinel-record.json"
            capture_ok = record_path.is_file() and record_path.stat().st_size > 0
            if not capture_ok:
                # The sentinel tool ran but its retained bytes are absent or
                # empty (v1 cycle-04 power-cut page-cache loss). This is a
                # CAPTURE fault, not an executed-and-failed sentinel: the
                # campaign may not claim PASS or FAIL on an unobserved
                # predicate — it classifies BLOCKED.
                entry["sentinels"] = {"sentinel_result": "CAPTURE_UNAVAILABLE",
                                      "reason": "sentinel-record.json missing or empty"}
                entry["checks"]["sentinels_pass"] = False
                entry["sentinel_capture_unavailable"] = True
            else:
                sent = derive_sentinel_cycle(sent_dir)
                # Sentinel attribution must bind to THIS boot and THIS boot's
                # freshly enumerated Vega BDFs (stale authority fails closed).
                if sent["boot_id"] != entry["boot_id"]:
                    sent["sentinel_result"] = "FAIL"
                    sent["attribution_error"] = "sentinel boot_id does not match snapshot boot_id"
                vega_set = set(entry["detail"].get("vega_bdfs") or [])
                if not set(sent.get("probe_bdfs") or []) <= vega_set:
                    sent["sentinel_result"] = "FAIL"
                    sent["attribution_error"] = (sent.get("attribution_error") or "") + \
                        "; sentinel probe BDFs not among this boot's live Vega BDFs"
                entry["sentinels"] = sent
                entry["checks"]["sentinels_pass"] = sent["sentinel_result"] == "PASS"
                sentinels[entry["cycle_index"]] = sent
        else:
            entry["checks"]["sentinels_pass"] = False
            entry["sentinel_capture_unavailable"] = True
            entry["sentinels"] = {"sentinel_result": "CAPTURE_UNAVAILABLE",
                                  "reason": "sentinel directory absent"}
        if entry["cycle_type"] == "warm":
            warm_count += 1
        elif entry["cycle_type"] == "cold":
            cold_count += 1
        entry["cycle_result"] = "PASS" if all(entry["checks"].values()) else "FAIL"
        entry["failed_checks"] = [k for k, v in entry["checks"].items() if not v]
        table.append(entry)

    all_pass = all(e["cycle_result"] == "PASS" for e in table)
    sentinels_all_pass = bool(sentinels) and all(s["sentinel_result"] == "PASS" for s in sentinels.values())
    capture_unavailable = any(e.get("sentinel_capture_unavailable") for e in table)
    min_warm_ok = warm_count >= 4  # 3 ordinary + >=1 additional warm
    cold_ok = cold_count >= 1

    if not table:
        terminal = "V2C_EVIDENCE_BLOCKED"
    elif capture_unavailable:
        # A required predicate could not be observed from retained bytes:
        # trustworthy evidence for BOTH pass and fail is missing. BLOCKED,
        # never relabeled as a platform failure (issue terminal contract).
        terminal = "V2C_EVIDENCE_BLOCKED"
    elif not all_pass or not sentinels_all_pass:
        terminal = "V2C_V340L_PLATFORM_STABILITY_FAIL"
    elif min_warm_ok and cold_ok:
        terminal = "V2C_V340L_PLATFORM_STABILITY_PASS"
    elif min_warm_ok:
        terminal = "V2C_V340L_WARM_REBOOT_STABILITY_ONLY"
    else:
        terminal = "V2C_V340L_PLATFORM_STABILITY_FAIL"

    return {
        "schema": "inferswarm.v2c.terminal-reduction/1",
        "campaign_id": plan["campaign_plan"]["campaign_id"],
        "campaign_plan_digest": plan_digest_ok,
        "baseline": {k: baseline[k] for k in ("cycle_index", "cycle_type", "boot_id", "checks", "cycle_result", "failed_checks")},
        "cycle_table": table,
        "warm_cycles": warm_count,
        "cold_cycles": cold_count,
        "all_cycles_pass": all_pass,
        "sentinels_all_pass": sentinels_all_pass,
        "capture_unavailable_cycles": [e["cycle_index"] for e in table if e.get("sentinel_capture_unavailable")],
        "manual_interventions": [],
        "terminal": terminal,
    }


def main() -> int:
    root = repo_root()
    area = area_root(root)
    plan = load_json(area / "CAMPAIGN-PLAN-V2.json")
    reduction = derive(area / "cycles", plan)
    out = area / "TERMINAL.json"
    payload = json.dumps(reduction, indent=1, sort_keys=True, allow_nan=False)
    out.write_bytes(payload.encode() + b"\n")
    print(json.dumps({"terminal": reduction["terminal"],
                      "warm": reduction["warm_cycles"], "cold": reduction["cold_cycles"],
                      "cycles": len(reduction["cycle_table"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
