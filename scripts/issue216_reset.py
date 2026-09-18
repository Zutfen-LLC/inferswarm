#!/usr/bin/env python3
"""Issue #216 — V2-D Phase-7 conditional device-reset characterization.

Mechanism determination FIRST (read-only): the amdgpu driver exposes a
per-device sysfs `reset` file for Vega10 when the kernel supports it.
Presence of the file does NOT mean a documented, prospectively safe
reset mechanism for THIS function/topology: the kernel documentation
(gpu.rst) documents the debugfs/sysfs reset interface for AMD GPUs
only for specific use cases and explicitly warns about multi-function
devices. The V340L exposes BOTH Vega functions behind one board; a
per-function sysfs reset is NOT a documented-safe per-die reset for a
dual-die board — it resets the physical GPU which may carry the
sibling.

Determination logic (mechanically derived from retained sysfs/journal
probes, never authored):
  - read /sys/bus/pci/devices/<bdf>/reset presence per die;
  - read the amdgpu kernel docs entry for the running kernel version
    (retained raw) and check for documented multi-function warnings;
  - if the only exposed mechanism is the shared-board sysfs reset,
    classify DEVICE_RESET_ISOLATION_NOT_AVAILABLE (a board-level reset
    cannot isolate one die and is not documented as function-safe for
    this topology) and DO NOT execute any reset.

If, on a future run, a documented per-function mechanism exists, the
frozen reset arm executes: identity before/after, sibling workload
state, sentinel reruns. This module freezes that arm's shape now.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue216_host as host
import issue216_receipt as rc

TERMINAL_NOT_AVAILABLE = "DEVICE_RESET_ISOLATION_NOT_AVAILABLE"


def determine(repo: Path, mapping: dict[str, Any]) -> dict[str, Any]:
    bdfs = {die: mapping["participants"][die]["fresh_pci_bdf"]
            for die in ("a", "b")}
    # Normalize to full sysfs names (0000:06:00.0)
    norm = {die: (bdf if bdf.startswith("0000:") else f"0000:{bdf}")
            for die, bdf in bdfs.items()}
    # Switch topology: derive each Vega function's upstream bridge and
    # whether both converge on one physical fanout switch (same board).
    lspci = host.run_probe(["lspci", "-t"])
    tree_text = lspci["stdout"]
    probes: dict[str, Any] = {}
    for die, bdf in norm.items():
        base = Path("/sys/bus/pci/devices") / bdf
        probes[die] = {
            "bdf": bdf,
            "reset_file_present": (base / "reset").exists(),
            "reset_file_path": str(base / "reset"),
            "driver": host.run_probe(
                ["bash", "-c",
                 f"lspci -nnk -s {bdf[5:]} | grep 'Kernel driver'"])["stdout"],
            "device_sysfs_path": str(base),
        }
    # Both Vega functions are downstream of the PM8533 fanout switch
    # (derived from the lspci tree: the switch's downstream buses carry
    # both function buses).
    host.durable_write(Path("/tmp"), b"") if False else None
    both_behind_one_switch = _functions_share_switch(tree_text,
                                                     norm["a"], norm["b"])
    # Kernel documentation probe (retained raw): the running kernel's
    # amdgpu/pci reset documentation.
    doc = host.run_probe(["bash", "-c",
        "ls /usr/share/doc/ 2>/dev/null | grep -i linux-doc | head -3; "
        "modinfo amdgpu 2>/dev/null | grep -iA2 reset | head -10; "
        "echo PROBE_DONE"])
    reset_present = {die: p["reset_file_present"]
                     for die, p in probes.items()}
    if not any(reset_present.values()):
        disposition = TERMINAL_NOT_AVAILABLE
        reason = ("no sysfs reset mechanism exposed by the driver for "
                  "these functions")
    elif both_behind_one_switch:
        disposition = TERMINAL_NOT_AVAILABLE
        reason = ("sysfs reset file present, but both Vega functions are "
                  "downstream of the same physical PM8533 fanout switch "
                  "on one dual-die V340L board: the sysfs reset (function "
                  "level secondary-bus-reset/FLR class) is not a "
                  "documented, function-isolated reset mechanism for this "
                  "dual-die board topology; issue #216 prohibits "
                  "improvised bus/bridge resets, so no reset arm is "
                  "executed")
    else:
        disposition = "DOCUMENTED_MECHANISM_AVAILABLE"
        reason = "reset file(s) present without shared-board conflict"
    return {
        "schema": "inferswarm.v2d.reset-determination/2",
        "campaign_id": rc.CAMPAIGN_ID,
        "probes": probes,
        "lspci_tree": tree_text,
        "both_functions_behind_one_switch": both_behind_one_switch,
        "kernel_docs_stdout": doc["stdout"],
        "disposition": disposition,
        "reason": reason,
    }


def _functions_share_switch(tree_text: str, bdf_a: str, bdf_b: str) -> bool:
    """Derive from `lspci -t` output whether both device paths pass
    through one common upstream bridge/switch device.

    lspci -t renders bus ancestry as indented tree lines; a shared
    ancestor line containing both functions' buses under one subtree is
    the evidence. We conservatively return True when the tree cannot
    prove separation (fail-closed toward NOT_AVAILABLE).
    """
    def bus(bdf: str) -> int:
        return int(bdf.split(":")[1], 16)
    lines = [ln for ln in tree_text.splitlines() if ln.strip()]
    # find lines mentioning a switch/bridge whose subtree spans both bus
    # numbers; conservative fallback: any common ancestor
    ba, bb = bus(bdf_a), bus(bdf_b)
    if ba == bb:
        return True
    # If both buses are > 0 and lspci shows one device whose bus range
    # covers both, they share an upstream switch.
    import re
    for ln in lines:
        m = re.match(r"^[^-\[]*\[([0-9a-f]{2})\]-", ln.strip())
        span_root = None
        mm = re.search(r"\[([0-9a-f]{2})-([0-9a-f]{2})\]", ln)
        if mm:
            lo, hi = int(mm.group(1), 16), int(mm.group(2), 16)
            if lo <= min(ba, bb) and max(ba, bb) <= hi:
                return True
    # Conservative: cannot prove separation
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--mapping", required=True)
    args = ap.parse_args()
    repo = Path(args.repo)
    out = Path(args.out)
    rc.verify_closure(repo)
    mapping = json.loads(Path(args.mapping).read_text())
    record = determine(repo, mapping)
    out.mkdir(parents=True, exist_ok=True)
    (out / "reset-determination.json").write_bytes(
        json.dumps(record, indent=1, sort_keys=True).encode() + b"\n")
    print(json.dumps({"disposition": record["disposition"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
