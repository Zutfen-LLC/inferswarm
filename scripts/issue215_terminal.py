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
PROMPT_SENTINEL = ("The quick brown fox jumps over the lazy dog. "
                   "Explain what happens next in one sentence:").encode()
REFERENCE_PATH_SENTINEL = "docs/investigations/vulkan-v1-a/reference-visible-output.txt"


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



_SIZE_RE = re.compile(r"^([0-9]+)([KMGT]?)$", re.M)


def _size_bytes(token: str) -> int:
    m = _SIZE_RE.match(token.strip())
    if not m:
        raise ReductionError(f"unparseable BAR size token: {token!r}")
    mult = {"": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3, "T": 1024 ** 4}[m.group(2)]
    return int(m.group(1)) * mult


def split_lspci_blocks(text: str) -> dict[str, str]:
    """Split an lspci -PP/-nn -vv dump into per-device blocks keyed by the
    FINAL BDF of each device path header line. Block boundaries are device
    header lines (a path of BDF segments at line start); everything until
    the next header belongs to that device."""
    header = re.compile(r"^((?:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}\.[0-9A-F])/)*([0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}\.[0-9A-F])\s", re.M)
    matches = list(header.finditer(text))
    blocks: dict[str, str] = {}
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        bdf = m.group(2)
        if bdf in blocks:
            raise ReductionError(
                f"duplicate device block for final BDF {bdf} in lspci dump — "
                "injected or malformed topology evidence fails closed")
        blocks[bdf] = text[m.start():end]
    return blocks


def _lnksta(block: str) -> dict | None:
    m = re.search(r"LnkSta:\s*Speed (\d+\.?\d*)GT/s, Width x?(\d+)", block)
    if not m:
        return None
    return {"speed": float(m.group(1)), "width": int(m.group(2))}


def _bus_span(block: str) -> tuple[int, int, int] | None:
    """(primary, secondary, subordinate) from a bridge's Bus line."""
    m = re.search(r"Bus: primary=([0-9A-Fa-f]+), secondary=([0-9A-Fa-f]+)(?:, subordinate=([0-9A-Fa-f]+))?",
                  block)
    if not m:
        return None
    sub = int(m.group(3), 16) if m.group(3) else int(m.group(2), 16)
    return int(m.group(1), 16), int(m.group(2), 16), sub


def _bus_primary_secondary(block: str) -> tuple[int, int] | None:
    span = _bus_span(block)
    return (span[0], span[1]) if span else None


def _endpoint_bars(block: str) -> list[tuple[int, int]]:
    """Parse assigned memory BARs [(start, size_bytes)] from one endpoint
    block. Disabled/unassigned BARs raise (caller fails closed)."""
    bars = []
    for m in re.finditer(
            r"Region \d+: Memory at ([0-9a-f]+) \([^)]*\)\s*\[size=([0-9]+[KMGT]?)\]", block):
        bars.append((int(m.group(1), 16), _size_bytes(m.group(2))))
    if re.search(r"Region \d+: Memory at [0-9a-f]+ \([^)]*\)\s*\[disabled\]", block):
        raise ReductionError("endpoint BAR is disabled")
    if re.search(r"Region \d+: Memory at 00000000", block):
        raise ReductionError("endpoint BAR is unassigned")
    return bars


def parse_journal_errors(journal_text: str) -> dict:
    """Classify boot-journal errors into transient (retained observation) vs
    correctness-bearing (fails the cycle). Fatal/uncorrected AER phrasings
    cover the kernel-standard spellings (case-insensitive)."""
    def count(pattern: str) -> int:
        return len(re.findall(pattern, journal_text, re.I))
    return {
        "fatal_aer_count": count(r"severity\s*=\s*(fatal|uncorrectable|uncorrected)")
                            + count(r"AER:\s*(?:Multiple\s+)?Uncorrected"),
        "amdgpu_failure_count": count(r"amdgpu.*(fail|timeout|reset|hang)"),
        "dmar_fault_count": count(r"DMAR:[^\n]*(fault|error)"),
        "unresolved_bar_count": count(r"BAR \d+: no space|can't claim BAR|not claimed"),
        "controller_failure_count": count(r"(r8169|usb \d+-\d|ata\d+|sd[a-z]): .*(fail|error|reset)"),
        "correctable_aer_count": count(r"severity=Correctable"),
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

    def required_stdout(name: str) -> str:
        path = raw / name
        if not path.is_file():
            raise ReductionError(f"missing required raw artifact: {path}")
        text = _stdout_of(path)
        # a retained-but-empty capture for a required probe is a capture
        # fault, not evidence of a clean platform
        if not text.strip():
            raise ReductionError(f"empty required raw artifact: {path}")
        return text

    # boot transition proof: receipt boot_id must equal the retained
    # raw boot_id.txt bytes (measured by the collector, retained raw).
    boot_id_raw = required_stdout("boot_id.txt").strip()
    checks["boot_id_bound_to_raw"] = rec["boot_id"] == boot_id_raw
    detail["boot_id"] = rec["boot_id"]
    if kind != "baseline":
        checks["boot_id_changed"] = rec.get("boot_id_changed") is True
        checks["prev_boot_id_bound"] = rec.get("prev_boot_id") is not None
        detail["prev_boot_id"] = rec.get("prev_boot_id")

    # warm/cold transition-type corroboration from the PREVIOUS boot's
    # retained journal bytes: an ordinary OS reboot records
    # reboot.target; a cold power cut does not (the journal simply ends).
    if kind in ("warm", "cold"):
        prev_shutdown = required_stdout("prev-boot-shutdown.txt")
        prev_last = required_stdout("prev-boot-last-lines.txt")
        saw_reboot_target = ("reboot.target" in prev_shutdown
                             or "reboot.target" in prev_last)
        if kind == "warm":
            checks["warm_reboot_evidence"] = saw_reboot_target
        else:
            # cold cycle: the previous boot must show a NON-reboot
            # termination (power cut) — reboot.target evidence would mean
            # this was actually a warm reboot mislabeled cold.
            checks["cold_powercut_evidence"] = not saw_reboot_target
        detail["prev_boot_saw_reboot_target"] = saw_reboot_target

    # PCI topology
    lspci_text = required_stdout("lspci-nn.txt")
    lspci = parse_lspci_nn(lspci_text)
    vegas = vega_functions(lspci)
    switches = pm8533_upstream(lspci)
    bridges = vega_bridges(lspci)
    checks["exactly_two_vega_functions"] = len(vegas) == 2
    checks["pm8533_fanout_present"] = len(switches) >= 1 and len(bridges) >= 2
    detail["vega_bdfs"] = [v["bdf"] for v in vegas]
    detail["switch_bdfs"] = [s["bdf"] for s in switches]

    # per-Vega -vv dumps (block-scoped)
    full_vv = required_stdout("lspci-vv-full.txt")
    blocks = split_lspci_blocks(full_vv)
    vega_states = {}
    bar_fail: list[str] = []
    for v in vegas:
        b = blocks.get(v["bdf"])
        if b is None:
            bar_fail.append(f"{v['bdf']}:no-block")
            continue
        vega_states[v["bdf"]] = b
    checks["both_vega_amdgpu_bound"] = bool(vega_states) and all(
        "Kernel driver in use: amdgpu" in b for b in vega_states.values())
    ranges: list[tuple[int, int]] = []
    try:
        for bdf, b in vega_states.items():
            for start, size in _endpoint_bars(b):
                ranges.append((start, size))
        checks["bars_assigned_not_disabled"] = len(ranges) > 0 and not bar_fail
    except ReductionError as exc:
        bar_fail.append(str(exc))
        checks["bars_assigned_not_disabled"] = False
    # size-aware non-overlap across ALL Vega BARs
    ranges_sorted = sorted(ranges)
    overlaps = [(a, b) for (a, a_sz), (b, b_sz) in zip(ranges_sorted, ranges_sorted[1:])
                if a + a_sz > b]
    checks["bars_nonoverlapping"] = not overlaps and not bar_fail and len(ranges) >= 2
    detail["bar_overlaps"] = overlaps
    detail["bar_fail"] = bar_fail

    # memory capacity via sysfs
    mem_text = required_stdout("gpu-sysfs-mem.txt")
    hbm = [int(x) for x in re.findall(r"^([0-9]{9,})$", mem_text, re.M)]
    checks["hbm_capacity_expected"] = len(hbm) >= 2 and sorted(hbm)[-2:] == [EXPECTED_HBM_BYTES] * 2

    nn_bridge_bdfs = {r["bdf"] for r in lspci
                      if r["desc"].lower().startswith("pci bridge")
                      and r["id"].split(":")[0] == "8086"}
    nn_switch_bdfs = {s["bdf"] for s in switches}
    # Link state. The chain is determined UNIQUELY from the retained
    # lspci TREE topology (independent capture): the root port is the unique
    # tree bridge whose secondary bus == the switch upstream's primary bus.
    # The vv blocks then corroborate nn membership + Bus lines + LnkSta.
    # Ambiguity (multiple candidate root ports or switch rows) fails CLOSED:
    # an in-place rewrite of another real root port cannot smuggle a second
    # chain, because BOTH chains would need to satisfy every predicate AND
    # the tree must corroborate each; a degraded true root port then fails.
    gen3 = {"root_port": False, "switch_upstream": False}
    detail["link_chain"] = None
    detail["link_candidates"] = []
    tree_text = required_stdout("lspci-tree.txt")
    candidates = []
    for s in switches:
        sb = blocks.get(s["bdf"])
        if sb is None or s["bdf"] not in nn_switch_bdfs:
            continue
        s_buses = _bus_primary_secondary(sb)
        if not s_buses:
            continue
        for rp_bdf, rp_block in blocks.items():
            if rp_bdf not in nn_bridge_bdfs:
                continue
            rp_buses = _bus_primary_secondary(rp_block)
            if not rp_buses or rp_buses[0] != 0 or rp_buses[1] != s_buses[0]:
                continue
            # tree corroboration, both sides: the root port opens the
            # switch's primary bus AND the switch's own (secondary,
            # subordinate) span appears INSIDE that root port's tree branch.
            rp_short = rp_bdf.split(":")[1]
            s_span = _bus_span(sb)
            if not s_span or not tree_chain_corroborated(
                    tree_text, rp_short, rp_buses[1], s_span[1], s_span[2]):
                continue
            rst = _lnksta(rp_block)
            sst = _lnksta(sb)
            rp_ok = bool(rst and rst["speed"] == 8.0 and rst["width"] == 1)
            sw_ok = bool(sst and sst["speed"] == 8.0 and sst["width"] == 1)
            candidates.append({"root_port_bdf": rp_bdf, "switch_upstream_bdf": s["bdf"],
                               "root_port_sta": rst, "switch_upstream_sta": sst,
                               "rp_ok": rp_ok, "sw_ok": sw_ok})
    detail["link_candidates"] = candidates
    if len(candidates) == 1:
        c = candidates[0]
        gen3["root_port"] = c["rp_ok"]
        gen3["switch_upstream"] = c["sw_ok"]
        detail["link_chain"] = c
    elif len(candidates) > 1:
        # ambiguity among corroborated chains: ALL must be Gen3 x1 (a forged
        # second chain cannot rescue a degraded true chain)
        gen3["root_port"] = all(c["rp_ok"] for c in candidates)
        gen3["switch_upstream"] = all(c["sw_ok"] for c in candidates)
        detail["link_chain"] = candidates[0]
        detail["link_ambiguous"] = True
    # zero candidates -> both predicates False (fail closed)
    checks["upstream_gen3_x1"] = gen3["root_port"] and gen3["switch_upstream"]
    detail["link"] = {"ok": checks["upstream_gen3_x1"], "parts": gen3}

    # Vulkan fresh enumeration
    vulkan_enum = required_stdout("vulkan-list-devices.txt")
    v_sel = re.findall(r"^\s*(Vulkan[0-9]+):\s+(.*)$", vulkan_enum, re.M)
    checks["two_vega_vulkan_devices"] = sum(1 for _, n in v_sel if "V340" in n or "Vega" in n) == 2

    # NIC
    nic_link = required_stdout("nic-link.txt")
    nic_addr = required_stdout("nic-addr.txt")
    ping = required_stdout("gateway-ping.txt")
    checks["nic_present_bound"] = NIC_ID.lower() in lspci_text.lower() and "r8169" in _stdout_of(raw / "nic-driver.txt")
    link_state = re.search(r"state (UP|DOWN)", nic_link)
    checks["nic_link_up"] = link_state is not None and link_state.group(1) == "UP"
    checks["nic_addressed"] = "10.0.0.137/24" in nic_addr
    checks["gateway_reachable"] = ping.count("time=") >= 3

    # USB
    lsusb = required_stdout("lsusb.txt")
    usb_now = set(re.findall(r"ID [0-9a-f]{4}:[0-9a-f]{4}", lsusb))
    if kind == "baseline":
        checks["usb_controllers_enumerated"] = "Linux Foundation root hub" in lsusb or len(usb_now) > 0
        detail["usb_baseline_set"] = sorted(usb_now)
    else:
        missing = (baseline_usb or set()) - usb_now
        checks["usb_controllers_enumerated"] = not missing
        detail["usb_missing_from_baseline"] = sorted(missing)

    # Storage
    findmnt = required_stdout("findmnt-root.txt")
    sentinel = required_stdout("storage-sentinel.txt")
    checks["root_fs_mounted_expected"] = "/dev/sda3" in findmnt or "UUID=f3a7ad1c" in findmnt
    checks["storage_sentinel_ok"] = "STORAGE_SENTINEL_OK" in sentinel

    # Kernel/platform errors
    journal = required_stdout("journal-errors.txt") + "\n" + required_stdout("journal-aer.txt")
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



def parse_lspci_tree(text: str) -> dict[str, tuple[int, int]]:
    """Parse an lspci -t tree into {final_bdf: (secondary, subordinate)} for
    bridge entries, from the retained tree bytes (independent of -vv)."""
    spans: dict[str, tuple[int, int]] = {}
    for m in re.finditer(r"([0-9a-f]{2})\.([0-9a-f]{2})\.([0-9a-f])\[(\w+)-?(\w+)?\]", text):
        seg = m.group(0)
        # lspci -t abbreviates BDFs as bus-relative (e.g. '1d.0-[02-09]'); the
        # full form appears as 'XX-YY' bus ranges after the device. We record
        # device -> (sec, sub) when a bracket range follows the device token.
        dev = m.group(0).split("-[")[0]
        rng = re.search(r"\[([0-9a-f]{2})-([0-9a-f]{2})\]", seg)
        if rng:
            spans[dev] = (int(rng.group(1), 16), int(rng.group(2), 16))
    return spans


def tree_span_for_device(tree_text: str, short_dev: str) -> tuple[int, int] | None:
    """The tree-claimed (secondary, subordinate) bus span a bridge device
    opens, e.g. tree '00.0-[03-09]' under the 1d.0 line -> (0x03, 0x09).
    Used to corroborate the SWITCH UPSTREAM's own Bus line from the tree,
    so an attacker cannot relocate the chain by editing only the vv file."""
    best: tuple[int, int] | None = None
    for m in re.finditer(r"([0-9a-f]{1,2}\\.[0-9a-f])\\s*-\\[([0-9a-f]{2})(?:-([0-9a-f]{2}))?\\]",
                         tree_text):
        if m.group(1) != short_dev:
            continue
        sec = int(m.group(2), 16)
        sub = int(m.group(3), 16) if m.group(3) else sec
        best = (sec, sub)
    return best


def tree_root_port_for_switch(tree_text: str, switch_secondary: int) -> set[str]:
    """Bridge devices in the TREE whose secondary == the switch's primary bus.
    lspci -t abbreviates devices as '<bus><zero-padded?>.0' (e.g. '1d.0-[02-09]');
    a single-bus span prints as '[NN]'. The tree is a separate retained capture;
    forging a -vv chain without also forging the tree leaves it uncorroborated."""
    found: set[str] = set()
    for m in re.finditer(r"([0-9a-f]{1,2}\.[0-9a-f])\s*-\[([0-9a-f]{2})(?:-([0-9a-f]{2}))?\]",
                         tree_text):
        dev = m.group(1)
        sec = int(m.group(2), 16)
        if sec == switch_secondary:
            found.add(dev)
    return found

def tree_chain_corroborated(tree_text: str, rp_short: str, rp_secondary: int,
                            switch_sec: int, switch_sub: int) -> bool:
    """The tree must show the root port rp_short opening rp_secondary AND the
    switch upstream span (switch_sec, switch_sub) nested within that root
    port branch. Root-bus ports are the "+-xx.N-[..]"/"\\-xx.N-[..]" tokens at
    line starts; a port branch runs until the next root-bus port token. lspci
    nests the switch directly on the root-port line
    ("+-1d.0-[02-09]----00.0-[03-09]"), so the branch includes that line."""
    root_pat = r"(?m)^\s*[+\\]-([0-9a-f]{2}\.[0-9a-f])\s*-\[([0-9a-f]{2})(?:-([0-9a-f]{2}))?\]"
    inner_pat = r"[0-9a-f]{1,2}\.[0-9a-f]\s*-\[([0-9a-f]{2})(?:-([0-9a-f]{2}))?\]"
    root_ports = list(re.finditer(root_pat, tree_text))
    for i, m in enumerate(root_ports):
        if m.group(1) != rp_short or int(m.group(2), 16) != rp_secondary:
            continue
        branch_end = root_ports[i + 1].start() if i + 1 < len(root_ports) else len(tree_text)
        branch = tree_text[m.end():branch_end]
        for d in re.finditer(inner_pat, branch):
            d_sec = int(d.group(1), 16)
            d_sub = int(d.group(2), 16) if d.group(2) else d_sec
            if (d_sec, d_sub) == (switch_sec, switch_sub):
                return True
    return False


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
    """Re-derive every sentinel predicate from the RETAINED RAW BYTES of the
    die executions (probe, stdout/stderr/exit-code, visible-output), plus the
    accepted comparator/accounting modules when importable. The structured
    sentinel-record.json is used ONLY for attribution fields that the raw
    bytes cannot carry (selector resolution provenance); every correctness
    predicate is recomputed, never trusted."""
    rec = load_json(sent_dir / "sentinel-record.json")
    import importlib.util
    from pathlib import Path as _P

    dies = {}
    for die in ("a", "b"):
        d_dir = sent_dir / f"die-{die}"
        if not d_dir.is_dir():
            dies[die] = {"result": "FAIL", "reason": "die raw dir absent"}
            continue
        try:
            exit_code = int((d_dir / "exit-code.txt").read_text().strip())
            stdout = (d_dir / "stdout.txt").read_bytes()
            stderr = (d_dir / "stderr.txt").read_bytes()
            visible = (d_dir / "visible-output.txt").read_bytes()
            probe = json.loads((d_dir / "probe.json").read_text())
        except (OSError, ValueError) as exc:
            dies[die] = {"result": "FAIL", "reason": f"raw artifact unreadable: {exc}"}
            continue
        stderr_text = stderr.decode("utf-8", "replace")
        # probe binding re-derived from raw probe stderr
        proof = probe.get("identity_proof_line")
        bdf = probe.get("bdf")
        # offload from raw stderr
        m = re.search(r"offloaded (\d+)/(\d+) layers", stderr_text)
        offloaded = [int(m.group(1)), int(m.group(2))] if m else None
        offload_full = offloaded is not None and offloaded[0] == offloaded[1]
        # byte-exactness: retained visible output must equal the recorded
        # stdout-derived response AND the structured digest must match
        vis_sha = sha256_bytes(visible)
        stdout_sha = sha256_bytes(stdout)
        stderr_sha = sha256_bytes(stderr)
        struct = (rec.get("dies") or {}).get(die) or {}
        digests_match = (struct.get("visible_output_sha256") == vis_sha
                         and struct.get("stdout_sha256") == stdout_sha
                         and struct.get("stderr_sha256") == stderr_sha)
        byte_exact_recorded = struct.get("byte_exact_visible_output") is True
        # comparator re-derivation: accepted extract_visible_response when the
        # module is importable next to this script; else grammar fallback
        try:
            spec = importlib.util.spec_from_file_location(
                "v0c_correctness_recheck", _P(__file__).resolve().parent / "v0c_correctness.py")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            derived_visible = mod.extract_visible_response(stdout, PROMPT_SENTINEL)
            comparator_ok = derived_visible == visible
            reference = (_P(__file__).resolve().parents[1]
                         / REFERENCE_PATH_SENTINEL).read_bytes()
            byte_exact = reference.startswith(derived_visible) and len(derived_visible) > 0
        except Exception:
            comparator_ok = False
            byte_exact = False
        # accounting re-derivation via accepted v1c reducer
        try:
            spec2 = importlib.util.spec_from_file_location(
                "v1c_accounting_recheck", _P(__file__).resolve().parent / "v1c_accounting.py")
            mod2 = importlib.util.module_from_spec(spec2)
            spec2.loader.exec_module(mod2)
            acct = mod2.parse_accounting(stderr_text, selector=struct.get("selector", "Vulkan1"))
            accounting = {k: acct[k] for k in (
                "unexplained_persistent_host_mirror_bytes", "source_fetches_after_ready",
                "unplanned_state_movements")}
        except Exception as exc:
            accounting = {"error": f"{type(exc).__name__}: {exc}"}
        accounting_clean = all(v == 0 for v in accounting.values())
        ok = (exit_code == 0 and proof and bdf and offload_full
              and digests_match and byte_exact_recorded and byte_exact
              and comparator_ok and accounting_clean)
        dies[die] = {
            "selector": struct.get("selector"), "probe_bdf": bdf,
            "identity_proof_line": proof,
            "exit_code": exit_code,
            "offloaded_layers": offloaded, "offload_full": offload_full,
            "visible_output_sha256": vis_sha, "stdout_sha256": stdout_sha,
            "stderr_sha256": stderr_sha,
            "digests_match_record": digests_match,
            "byte_exact_visible_output": byte_exact,
            "byte_exact_rederived_from_reference": byte_exact,
            "comparator_grammar_ok": comparator_ok,
            "accounting_three_tuple": accounting,
            "accounting_clean": accounting_clean,
            "result": "PASS" if ok else "FAIL",
        }
    distinct_bdfs = {d.get("probe_bdf") for d in dies.values() if d.get("probe_bdf")}
    distinct_selectors = {d.get("selector") for d in dies.values() if d.get("selector")}
    ok = (len(dies) == 2
          and all(d["result"] == "PASS" for d in dies.values())
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


def derive_final_canonical(area: Path, plan: dict) -> dict | None:
    """Derive the final-boot full-canonical predicates from retained bytes
    (qualification/canonical records + raw digests + discovery bindings)."""
    fc = area / "cycles-v2" / "final-canonical"
    rec_path = fc / "final-canonical.json"
    if not rec_path.is_file():
        return None
    rec = json.loads(rec_path.read_text(encoding="utf-8"))
    dies = {}
    for die in ("a", "b"):
        try:
            c = json.loads((fc / f"die-{die}/canonical/canonical-execution.json").read_text())
            q = json.loads((fc / f"die-{die}/qualification/qualification.json").read_text())
            stdout_sha = sha256_bytes((fc / f"die-{die}/canonical/stdout.txt").read_bytes())
            stderr_sha = sha256_bytes((fc / f"die-{die}/canonical/stderr.txt").read_bytes())
            raw_match = (stdout_sha == c["attempt"]["stdout_sha256"]
                         and stderr_sha == c["attempt"]["stderr_sha256"])
            acct = {k: c["accounting"][k] for k in (
                "unexplained_persistent_host_mirror_bytes", "source_fetches_after_ready",
                "unplanned_state_movements")}
            dies[die] = {
                "qualification_result": q["result"],
                "offloaded_layers": q["offloaded_layers"],
                "canonical_result": c["result"],
                "byte_exact_visible_output": c["correctness"]["byte_exact_visible_output"],
                "accounting_three_tuple": acct,
                "raw_bytes_match_record": raw_match,
            }
        except (OSError, KeyError, json.JSONDecodeError) as exc:
            dies[die] = {"result": "FAIL", "error": f"{type(exc).__name__}: {exc}"}
    ok = all(
        d.get("qualification_result") == "PASS" and d.get("canonical_result") == "PASS"
        and d.get("byte_exact_visible_output") is True
        and all(v == 0 for v in d.get("accounting_three_tuple", {"x": 1}).values())
        and d.get("raw_bytes_match_record") for d in dies.values()) and len(dies) == 2
    return {"boot_id": rec.get("boot_id"),
            "discovery": rec.get("discovery"),
            "dies": dies,
            "result": "PASS" if ok else "FAIL"}


def main() -> int:
    root = repo_root()
    area = area_root(root)
    plan = load_json(area / "CAMPAIGN-PLAN-V2.json")
    reduction = derive(area / "cycles-v2", plan)
    fc = derive_final_canonical(area, plan)
    if fc is not None:
        reduction["final_canonical"] = fc
        if fc["result"] != "PASS":
            reduction["terminal"] = "V2C_V340L_PLATFORM_STABILITY_FAIL"
    out = area / "TERMINAL.json"
    payload = json.dumps(reduction, indent=1, sort_keys=True, allow_nan=False)
    out.write_bytes(payload.encode() + b"\n")
    print(json.dumps({"terminal": reduction["terminal"],
                      "warm": reduction["warm_cycles"], "cold": reduction["cold_cycles"],
                      "cycles": len(reduction["cycle_table"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
