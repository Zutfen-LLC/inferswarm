#!/usr/bin/env python3
"""Issue #232 — V2-G host-observation helpers (inferswarm02).

Adapted from the accepted #230 host module (same fail-closed receipt
discipline; unavailable telemetry fields are None, never estimated).
V2-G adds the PCIe-path observation machinery the remediation campaign
needs:

* AER EVENT counting from TWO independent sources (sysfs per-device
  counters + kernel-journal event census) — never conflated with
  multi-line journal context-block counts (issue Phase 1);
* link-width/speed observation that explicitly distinguishes idle
  SPEED downtraining from negotiated WIDTH (issue control 2);
* topology-chain derivation from FRESH lspci bytes by switch identity
  + bus chaining (never from historical BDF literals — issue control 1);
* the whole-boot journal AER census parser (same grammar as the
  accepted V2-F supplementary quantification).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

VEGA_ID = "1002:6864"
PM8533_ID = "11f8:8533"


class HostObservationError(RuntimeError):
    pass


def run_probe(argv: list[str], timeout: int = 120) -> dict[str, Any]:
    """Run one read-only probe; retain receipt; fail closed on error."""
    try:
        p = subprocess.run(argv, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise HostObservationError(
            f"probe timeout: {' '.join(argv[:4])}...") from exc
    receipt = {
        "argv": argv,
        "returncode": p.returncode,
        "stdout_bytes": len(p.stdout),
        "stderr_bytes": len(p.stderr),
        "stdout": p.stdout.decode("utf-8", "replace"),
        "stderr": p.stderr.decode("utf-8", "replace"),
    }
    if p.returncode != 0:
        raise HostObservationError(
            f"probe failed rc={p.returncode}: {' '.join(argv[:4])}... :: "
            f"{receipt['stderr'][:200]}")
    return receipt


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def sha256_text(text: bytes) -> str:
    import hashlib
    return hashlib.sha256(text).hexdigest()


def sysfs_bdf(bdf: str) -> str:
    bdf = bdf.strip()
    return bdf if bdf.startswith("0000:") else f"0000:{bdf}"


# ---------------------------------------------------------------------------
# AER event counting — two independent sources, never mixed.
# ---------------------------------------------------------------------------

def aer_counters(bdf: str) -> dict[str, Any]:
    """AER sysfs counters for one BDF (parsed name->int, unavailable=-1).

    Handles BOTH kernel formats: ``RxErr=93177`` (older) and
    ``RxErr 93177`` (kernel 7.1.x space-separated pairs). A file that
    exists but parses to zero counters is marked ``{"_unparseable": -1}``
    so downstream zero-checks fail closed — an empty dict never
    masquerades as "no events".

    NOTE (measured 2026-09-20, boot 201768fa): the kernel journal
    RATE-LIMITS AER prints while the flood runs — sysfs counters are
    the authoritative per-event count (measured ~8x the journal line
    count at flood rates: 93,217 cumulative sysfs RxErr vs ~11.2k
    journal severity lines in the same boot window). Zero-checks
    require BOTH sources at zero; journal line counts never scale to
    event counts under rate limiting.
    """
    base = Path("/sys/bus/pci/devices") / sysfs_bdf(bdf)
    out: dict[str, Any] = {}
    for name in ("aer_dev_correctable", "aer_dev_nonfatal",
                 "aer_dev_fatal"):
        val = _read(base / name)
        if val is None:
            out[name] = -1  # unavailable marker (never silently zero)
            continue
        fields: dict[str, int] = {}
        toks = val.split()
        if "=" in val:
            for token in toks:
                k, sep, v = token.partition("=")
                if not sep:
                    continue
                try:
                    fields[k] = int(v)
                except ValueError:
                    fields[k] = -1
        else:
            it = iter(toks)
            for k in it:
                v = next(it, None)
                if v is None:
                    break
                try:
                    fields[k] = int(v)
                except ValueError:
                    fields[k] = -1
        if not fields:
            out[name] = {"_unparseable": -1}  # fail closed
        else:
            out[name] = fields
    return out


def aer_event_census(journal_text: str) -> dict[str, Any]:
    """Parse KERNEL JOURNAL bytes into AER EVENT counts using the
    accepted V2-F supplementary quantification grammar: an EVENT is a
    severity-bearing ``pcieport BDF: PCIe Bus Error: severity=...``
    line (the accepted count 250,851 = exactly these lines in the
    fault boot). The source BDF is the pcieport prefix of THAT line.

    Everything else is counted SEPARATELY and never mixed into event
    counts (issue Phase 1 / control 3): the root-port relay
    announcements (``AER: Correctable error message received from``),
    per-error detail rows (``[ 0] RxErr``), device status/mask lines,
    and _OSC/ACS/AER-enabled context lines. Correctable is never
    conflated with Uncorrectable/DPC (control 4).
    """
    events = {"Correctable": 0, "Uncorrectable": 0, "DPC": 0}
    by_source: dict[str, dict[str, int]] = {}
    by_severity_prefix: dict[str, dict[str, int]] = {}
    by_type_class: dict[str, int] = {}
    announcement_lines = 0
    context_lines = 0
    detail_lines = 0
    for line in journal_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # EVENT: severity-bearing PCIe Bus Error line
        em = re.match(
            r".*pcieport\s+([0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]):"
            r"\s*PCIe Bus Error:\s*severity=(\w+)", stripped)
        if em:
            src = sysfs_bdf(em.group(1))
            sev_raw = em.group(2)
            if sev_raw.lower() == "correctable":
                sev = "Correctable"
            else:
                sev = "Uncorrectable"
            events[sev] += 1
            by_severity_prefix.setdefault(src, {"Correctable": 0,
                                                "Uncorrectable": 0,
                                                "DPC": 0})[sev] += 1
            tm = re.search(r"type=([^,]+)", stripped)
            if tm:
                tclass = tm.group(1).strip()
                by_type_class[tclass] = \
                    by_type_class.get(tclass, 0) + 1
            continue
        # root-port relay announcement — the accepted V2-F
        # quantification attributes SOURCE by this line's
        # ``received from <BDF>`` (the error-sending device; the
        # pcieport prefix here is only the relaying root port).
        # Announcements may coalesce ("Multiple"), so they are a
        # separate population from event counts, never summed into
        # them.
        am = re.search(
            r"pcieport\s+[0-9a-f:.]+:\s*AER:\s*(Multiple\s+)?"
            r"(Correctable|Uncorrected|Uncorrectable)[^\n]*?"
            r"received from\s+([0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}"
            r"\.[0-7])", stripped)
        if am:
            announcement_lines += 1
            src = sysfs_bdf(am.group(3))
            sev = "Correctable" if am.group(2) == "Correctable" \
                else "Uncorrectable"
            by_source.setdefault(src, {"Correctable": 0,
                                       "Uncorrectable": 0,
                                       "DPC": 0})[sev] += 1
            continue
        if re.search(r"DPC|containment|integrity", stripped, re.I):
            if "pcieport" in stripped or "pci" in stripped.lower():
                events["DPC"] += 1
                continue
        if re.search(r"pcieport.*AER: enabled with IRQ", stripped):
            context_lines += 1
            continue
        if re.search(r"_OSC|ACS:", stripped):
            context_lines += 1
            continue
        # per-error detail rows ([ 0] RxErr (First), status/mask, ...)
        detail_lines += 1
    return {
        "events": events,
        "events_by_source": by_source,
        "events_by_severity_prefix": by_severity_prefix,
        "events_by_type_class": by_type_class,
        "announcement_lines": announcement_lines,
        "context_lines": context_lines,
        "detail_lines": detail_lines,
        "total_lines": len(journal_text.splitlines()),
    }


def aer_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Per-BDF per-counter deltas (negative = counter reset, retained)."""
    out: dict[str, Any] = {}
    for bdf in before.get("aer", {}):
        row = {}
        for cls in ("aer_dev_correctable", "aer_dev_nonfatal",
                    "aer_dev_fatal"):
            b = before["aer"][bdf].get(cls)
            a = after["aer"][bdf].get(cls)
            if isinstance(b, dict) and isinstance(a, dict):
                row[cls] = {k: a.get(k, 0) - b.get(k, 0) for k in
                            sorted(set(b) | set(a))}
            else:
                row[cls] = None
        out[bdf] = row
    return out


def link_state(bdf: str) -> dict[str, Any]:
    """Sysfs link state for one BDF (raw labels + widths)."""
    base = Path("/sys/bus/pci/devices") / sysfs_bdf(bdf)
    out: dict[str, Any] = {}
    for field in ("current_link_speed", "current_link_width",
                  "max_link_speed", "max_link_width"):
        out[field] = _read(base / field)
    return out


# ---------------------------------------------------------------------------
# Topology-chain derivation from FRESH lspci bytes (control 1: stale
# BDF identity after power-cycle / slot move is REJECTED, never assumed).
# Chain rules follow the accepted V2-C reducer (#215): block-scoped -vv
# parsing with duplicate rejection, root-port discovery by bus chaining
# anchored at the root bus (primary==00), cross-bound to -nn rows, and
# corroborated by the independent `lspci -t` tree on BOTH sides
# (root port opens the switch primary bus; the switch's own span is
# nested inside that root port's tree branch). Ambiguity fails closed.
# ---------------------------------------------------------------------------

HEADER_RE = re.compile(
    r"^((?:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}\.[0-9A-F])/)*"
    r"([0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}\.[0-9A-F])\s", re.M)


def parse_lspci_nn(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        m = re.match(r"^(?:0000:)?([0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f])\s+"
                     r"(.*?)\s+\[([0-9a-f]{4}:[0-9a-f]{4})\]", line)
        if m:
            rows.append({"bdf": sysfs_bdf(m.group(1)),
                         "desc": m.group(2), "id": m.group(3)})
    return rows


def split_lspci_blocks(text: str) -> dict[str, str]:
    """Split an lspci -PP -nn -vv dump into per-device blocks keyed by
    the FINAL BDF of each path-header line; duplicate final BDFs raise
    (forgeable-concatenation guard from the accepted V2-C rules)."""
    matches = list(HEADER_RE.finditer(text))
    blocks: dict[str, str] = {}
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        bdf = sysfs_bdf(m.group(2))
        if bdf in blocks:
            raise HostObservationError(
                f"duplicate device block for final BDF {bdf} — "
                "injected or malformed topology evidence fails closed")
        blocks[bdf] = text[m.start():end]
    return blocks


def _bus_span(block: str) -> tuple[int, int, int] | None:
    """(primary, secondary, subordinate) from a bridge's Bus line."""
    m = re.search(
        r"Bus: primary=([0-9A-Fa-f]+), secondary=([0-9A-Fa-f]+)"
        r"(?:, subordinate=([0-9A-Fa-f]+))?", block)
    if not m:
        return None
    sub = int(m.group(3), 16) if m.group(3) else int(m.group(2), 16)
    return int(m.group(1), 16), int(m.group(2), 16), sub


def _lnksta(block: str) -> dict[str, Any] | None:
    m = re.search(r"LnkSta:\s*Speed (\d+\.?\d*)GT/s,\s*Width x(\d+)"
                  r"( \(downgraded\))?", block)
    if not m:
        return None
    return {"speed": float(m.group(1)), "width": int(m.group(2)),
            "width_downgraded": bool(m.group(3))}


def _lnkcap(block: str) -> dict[str, Any] | None:
    m = re.search(
        r"LnkCap:\s*Port #\d+,\s*Speed (\d+\.?\d*)GT/s,\s*Width x(\d+)",
        block)
    if not m:
        return None
    return {"speed": float(m.group(1)), "width": int(m.group(2))}


def tree_root_port_for_switch(tree_text: str,
                              switch_secondary: int) -> set[str]:
    """Tree bridge devices whose secondary == the switch's primary bus
    (V2-C grammar; single-bus spans print as '[NN]')."""
    found: set[str] = set()
    for m in re.finditer(
            r"([0-9a-f]{1,2}\.[0-9a-f])\s*-\[([0-9a-f]{2})"
            r"(?:-([0-9a-f]{2}))?\]", tree_text):
        if int(m.group(2), 16) == switch_secondary:
            found.add(m.group(1))
    return found


def tree_chain_corroborated(tree_text: str, rp_short: str,
                            rp_secondary: int, switch_sec: int,
                            switch_sub: int) -> bool:
    """Tree must show the root port opening rp_secondary AND the switch
    upstream span nested within that root port branch (V2-C rules)."""
    root_pat = (r"(?m)^\s*[+\\]-([0-9a-f]{2}\.[0-9a-f])\s*"
                r"-\[([0-9a-f]{2})(?:-([0-9a-f]{2}))?\]")
    inner_pat = (r"[0-9a-f]{1,2}\.[0-9a-f]\s*"
                 r"-\[([0-9a-f]{2})(?:-([0-9a-f]{2}))?\]")
    root_ports = list(re.finditer(root_pat, tree_text))
    for i, m in enumerate(root_ports):
        if m.group(1) != rp_short or int(m.group(2), 16) != rp_secondary:
            continue
        branch_end = (root_ports[i + 1].start()
                      if i + 1 < len(root_ports) else len(tree_text))
        branch = tree_text[m.end():branch_end]
        for d in re.finditer(inner_pat, branch):
            d_sec = int(d.group(1), 16)
            d_sub = int(d.group(2), 16) if d.group(2) else d_sec
            if (d_sec, d_sub) == (switch_sec, switch_sub):
                return True
    return False


def bus00_bridge_bdfs(rows: list[dict[str, Any]]) -> list[str]:
    """All bus-00 PCI bridges from nn rows (identity-free: root ports
    are bus-00 bridges regardless of their 8086:xxxx device id — the
    slot move landed on a295 where the historical port was a29a)."""
    return sorted(r["bdf"] for r in rows
                  if "bridge" in r["desc"].lower()
                  and r["bdf"].startswith("0000:00:"))


def collect_vv_bytes(timeout: int = 180) -> str:
    """Combined `lspci -PP -nn -vv` text for every bus-00 bridge, every
    PM8533 row, and every Vega row (live). Chain derivation needs the
    Bus:/LnkSta lines of ALL candidate root ports, not a hardcoded
    device id."""
    nn = run_probe(["lspci", "-nn"])["stdout"]
    rows = parse_lspci_nn(nn)
    bdfs = sorted(set(bus00_bridge_bdfs(rows))
                  | {r["bdf"] for r in rows if r["id"] == PM8533_ID}
                  | {r["bdf"] for r in rows if r["id"] == VEGA_ID})
    parts = []
    for bdf in bdfs:
        parts.append(run_probe(
            ["lspci", "-PP", "-nn", "-vv", "-s",
             bdf.removeprefix("0000:")], timeout=timeout)["stdout"])
    return "\n".join(parts)


def derive_chain(lspci_nn_text: str, lspci_tree_text: str,
                 lspci_vv_text: str) -> dict[str, Any]:
    """Derive the CURRENT root-port -> switch-upstream chain from fresh
    lspci bytes, identified by PM8533_ID / bus-chaining / tree
    corroboration (V2-C rules) — never from historical BDF literals.

    Returns the unique corroborated candidate (root_port, switch
    upstream, both LnkSta/LnkCap) or raises. Exactly zero or multiple
    corroborated candidates is a derivation failure (fail closed).
    """
    rows = parse_lspci_nn(lspci_nn_text)
    nn_bridge_bdfs = {r["bdf"] for r in rows
                      if "bridge" in r["desc"].lower()
                      and r["id"].split(":")[0] == "8086"}
    nn_switch_bdfs = {r["bdf"] for r in rows if r["id"] == PM8533_ID}
    blocks = split_lspci_blocks(lspci_vv_text)
    candidates: list[dict[str, Any]] = []
    for s_bdf in sorted(nn_switch_bdfs):
        sb = blocks.get(s_bdf)
        if sb is None:
            continue
        s_buses = _bus_span(sb)
        if not s_buses:
            continue
        for rp_bdf in sorted(nn_bridge_bdfs):
            rp_block = blocks.get(rp_bdf)
            if rp_block is None:
                continue
            rp_buses = _bus_span(rp_block)
            if not rp_buses or rp_buses[0] != 0 \
                    or rp_buses[1] != s_buses[0]:
                continue
            # tree tokens are dev.fn (lspci -t drops bus+domain): the
            # root port 00:1d.0 prints as '1d.0'
            rp_short = rp_bdf.split(":")[-1]
            if not tree_chain_corroborated(
                    lspci_tree_text, rp_short, rp_buses[1],
                    s_buses[1], s_buses[2]):
                continue
            if rp_short not in tree_root_port_for_switch(
                    lspci_tree_text, s_buses[0]):
                continue
            candidates.append({
                "root_port_bdf": rp_bdf,
                "switch_upstream_bdf": s_bdf,
                "root_port_sta": _lnksta(rp_block),
                "root_port_cap": _lnkcap(rp_block),
                "switch_upstream_sta": _lnksta(sb),
                "switch_upstream_cap": _lnkcap(sb),
            })
    if len(candidates) != 1:
        raise HostObservationError(
            f"expected exactly one corroborated root-port->switch chain, "
            f"found {len(candidates)}: "
            f"{[c['root_port_bdf'] + '->' + c['switch_upstream_bdf'] for c in candidates]}")
    return candidates[0]



# ---------------------------------------------------------------------------
# Journal / host sentinels (adapted from the accepted #230 host module).
# ---------------------------------------------------------------------------

def journal_scan(cursor: str | None = None) -> dict[str, Any]:
    """Scan the current-boot kernel journal for GPU/PCIe fault classes."""
    # sudo -n: hermes is not in adm/systemd-journal (the #230
    # campaign pitfall — a bare journalctl silently returns only
    # session-owned lines); passwordless sudo is verified available.
    argv = ["sudo", "-n", "journalctl", "-b", "-k", "--no-pager",
            "-g", "amdgpu|AER|pcieport|DMAR|dmar|[Rr]eset|[Hh]ang|ECC"]
    if cursor:
        argv += ["--after-cursor", cursor]
    # journalctl -g exits 1 when NO entries match the pattern — that
    # is the CLEAN result (a fault-free window), not a probe failure.
    # Only other nonzero codes (or a stderr error) fail closed.
    try:
        receipt = run_probe(argv, timeout=300)
        text = receipt["stdout"]
    except HostObservationError as exc:
        import subprocess as _sp
        p2 = _sp.run(argv, capture_output=True, timeout=300)
        no_entries = (p2.returncode == 1
                      and b"No entries" in p2.stdout
                      and not p2.stderr.strip())
        if not no_entries:
            raise
        text = ""
    cursor_argv = ["sudo", "-n", "journalctl", "-b", "-k",
                   "--no-pager", "-n", "1", "-o", "json"]
    creceipt = run_probe(cursor_argv, timeout=60)
    next_cursor = None
    try:
        next_cursor = json.loads(creceipt["stdout"]).get("__CURSOR")
    except (json.JSONDecodeError, AttributeError):
        next_cursor = None

    def count(pattern: str) -> int:
        return len(re.findall(pattern, text, re.I))

    return {
        "argv": argv,
        "text": text,
        "next_cursor": next_cursor,
        "counts": {
            "fatal_aer": count(r"severity\s*=\s*(fatal|uncorrectable|uncorrected)")
                       + count(r"AER:\s*(?:Multiple\s+)?Uncorrected"),
            "amdgpu_reset": count(r"amdgpu.*reset|resetting amdgpu|GPU reset"),
            "amdgpu_timeout": count(r"amdgpu.*timeout|GPU hang|ring timeout"),
            "amdgpu_failure": count(r"amdgpu.*(fail|error)"),
            "dmar_fault": count(r"DMAR:[^\n]*(fault|error)"),
            "thermal": count(r"thermal.*(shutdown|trip|critical)|overtemperature"),
        },
    }


def boot_id() -> str:
    val = _read(Path("/proc/sys/kernel/random/boot_id"))
    if not val:
        raise HostObservationError("no boot_id")
    return val


def host_health() -> dict[str, Any]:
    load = _read(Path("/proc/loadavg"))
    mem: dict[str, int] = {}
    for line in (_read(Path("/proc/meminfo")) or "").splitlines():
        if line.startswith(("MemAvailable", "MemFree", "SwapFree")):
            k, v = line.split(":", 1)
            mem[k] = int(v.strip().split()[0]) * 1024
    up = _read(Path("/proc/uptime"))
    return {"monotonic_ns": time.monotonic_ns(), "loadavg": load,
            "meminfo_bytes": mem, "uptime": up}


def nic_sentinel() -> dict[str, Any]:
    """Host-facing NIC byte counters (peripheral-regression sentinel)."""
    out: dict[str, Any] = {"monotonic_ns": time.monotonic_ns()}
    for iface in sorted(Path("/sys/class/net").glob("*")):
        base = iface / "statistics"
        if base.is_dir():
            out[iface.name] = {
                "rx_bytes": _int_or_none(_read(base / "rx_bytes")),
                "tx_bytes": _int_or_none(_read(base / "tx_bytes")),
            }
    return out


def storage_sentinel() -> dict[str, Any]:
    """Root-filesystem free space + a durable write/readback check."""
    st = os.statvfs("/")
    probe = Path("/var/tmp/issue232-storage-sentinel")
    try:
        probe.write_bytes(b"sentinel")
        fd = os.open(probe, os.O_RDONLY)
        os.fsync(fd)
        os.close(fd)
        ok = probe.read_bytes() == b"sentinel"
    finally:
        probe.unlink(missing_ok=True)
    return {"free_bytes": st.f_bavail * st.f_frsize, "write_ok": ok}


def _int_or_none(val: str | None) -> int | None:
    if val is None:
        return None
    try:
        return int(val)
    except ValueError:
        return None


def durable_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    dfd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)
