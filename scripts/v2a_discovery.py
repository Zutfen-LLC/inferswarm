#!/usr/bin/env python3
"""V2-A reusable NON-AUTHORIZING Vulkan device discovery (issue #163).

Narrow internal inventory layer: enumerate the Vulkan-capable physical
resources visible on THIS host, and bind each runtime selector
(``Vulkan<N>``) to a stable PCI BDF mechanically.

The runtime's own device listing does not print PCI addresses, so the
mechanical binding chain is: runtime listing row -> exact device-name
string -> loader's per-physical-device PCI bus info block -> BDF ->
lspci slot. The device-name join is exact-string and one-to-one: a
duplicated name across two loader devices makes the binding AMBIGUOUS
and fails closed (no ordering assumption, no first-match). Software
devices without PCI bus info (e.g. CPU rasterizers) are non-physical
and never bound.

Discovery makes no policy decision here: no vendor tier, no preferred
device, no ordering assumption, no promotion. The emitted document is
INVENTORY DATA ONLY — explicitly non-authorizing; it can never satisfy
the correctness-reference requirement of a campaign authority (see
``scripts/v2a_authority.py``).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

SCHEMA = "inferswarm.v2a.device-inventory/1"
NON_AUTHORIZING = ("inventory data only: no selection, promotion, authorization, "
                   "or correctness reference may be derived from this document")

_SELECTOR_ROW = re.compile(
    r"(?P<selector>Vulkan[0-9]+)\s*[:=]\s*(?P<name>.+?)\s*\((?P<total>[0-9]+)\s*MiB,\s*"
    r"(?P<free>[0-9]+)\s*MiB free\)\s*$")
_LOADER_INSTANCE = re.compile(r"Vulkan Instance Version:\s*(\S+)")


class DiscoveryError(RuntimeError):
    """Device inventory could not be established unambiguously."""


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _command(argv: list[str]) -> str:
    return subprocess.check_output(argv, text=True, stderr=subprocess.DEVNULL).strip()


def parse_device_rows(text: str) -> list[dict[str, Any]]:
    """Parse the runtime's ``--list-devices`` rows without ordering assumptions."""
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        match = _SELECTOR_ROW.search(line)
        if not match:
            continue
        rows.append({
            "selector": match.group("selector"),
            "device_name": match.group("name").strip(),
            "device_local_vram_bytes": int(match.group("total")) * 1024 * 1024,
            "device_local_vram_free_bytes": int(match.group("free")) * 1024 * 1024,
            "pci_bdf": None,
        })
    if not rows:
        raise DiscoveryError("runtime enumerated no Vulkan device rows")
    return rows


def parse_loader_pci_blocks(text: str) -> list[dict[str, Any]]:
    """Parse the loader's per-device blocks with PCI bus info.

    Blocks appear in loader enumeration order; each carries a device
    name and (for physical devices) a ``VkPhysicalDevicePCIBusInfo``
    section with domain/bus/device/function. Returns one entry per
    physical (PCI-bearing) device. Names are retained exactly; they are
    loader data, not policy.
    """
    devices: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in text.splitlines():
        header = re.match(r"^GPU(?P<index>[0-9]+):\s*$", line)
        if header:
            current = {"loader_index": int(header.group("index")), "device_name": None,
                       "pci_bdf": None, "vendor_id": None, "device_id": None,
                       "driver_name": None}
            devices.append(current)
            continue
        if current is None:
            continue
        name = re.match(r"^\s*deviceName\s*=\s*(.+?)\s*$", line)
        if name:
            current["device_name"] = name.group(1)
        vendor = re.match(r"^\s*vendorID\s*=\s*(0x[0-9a-fA-F]+)\s*$", line)
        if vendor:
            current["vendor_id"] = vendor.group(1).lower()
        device = re.match(r"^\s*deviceID\s*=\s*(0x[0-9a-fA-F]+)\s*$", line)
        if device:
            current["device_id"] = device.group(1).lower()
        driver = re.match(r"^\s*driverName\s*=\s*(.+?)\s*$", line)
        if driver:
            current["driver_name"] = driver.group(1)
        if "VkPhysicalDevicePCIBusInfoPropertiesEXT" in line:
            current["_in_pci_block"] = True
            continue
        if current.get("_in_pci_block"):
            bus = re.match(r"^\s*pciBus\s*=\s*([0-9]+)\s*$", line)
            dev = re.match(r"^\s*pciDevice\s*=\s*([0-9]+)\s*$", line)
            func = re.match(r"^\s*pciFunction\s*=\s*([0-9]+)\s*$", line)
            domain = re.match(r"^\s*pciDomain\s*=\s*([0-9]+)\s*$", line)
            if bus:
                current["_bus"] = int(bus.group(1))
            if dev:
                current["_dev"] = int(dev.group(1))
            if func:
                current["_func"] = int(func.group(1))
            if domain:
                current["_domain"] = int(domain.group(1))
            # The loader prints the four fields in a fixed block; the
            # BDF is composed once the function field (last in the
            # block's field order we consume) has been seen.
            if func:
                current["pci_bdf"] = (f"{current.get('_bus', 0):02x}:"
                                      f"{current.get('_dev', 0):02x}.{current['_func']}")
                current["pci_domain"] = current.get("_domain", 0)
                current["_in_pci_block"] = False
    physical = [d for d in devices if d.get("pci_bdf")]
    if not physical:
        raise DiscoveryError("loader reported no physical (PCI) Vulkan devices")
    return physical


def classify_bindings(rows: list[dict[str, Any]], loader_devices: list[dict[str, Any]],
                      lspci_text: str) -> list[dict[str, Any]]:
    """Attach a binding classification to every runtime selector row.

    Join: selector row -> loader device by EXACT device-name string ->
    loader PCI block -> lspci slot. Every row leaves with
    ``binding_status`` BOUND (pci_bdf set) or AMBIGUOUS/UNRESOLVED
    (candidate_bdfs recorded, pci_bdf None). Selector ordering is never
    used; a duplicated device name across loader devices is recorded as
    AMBIGUOUS, never resolved by first match.
    """
    names: dict[str, list[dict[str, Any]]] = {}
    for device in loader_devices:
        if device["device_name"]:
            names.setdefault(device["device_name"], []).append(device)

    def _slot(token: str) -> str:
        # lspci slot tokens may carry a 0000: domain prefix; the stable
        # identity is bus:device.function.
        parts = token.lower().split(":")
        return ":".join(parts[-2:]) if len(parts) >= 2 else token.lower()

    slots = {_slot(line.split()[0]): line.strip()
             for line in lspci_text.splitlines() if line.split()}
    seen_bdfs: dict[str, str] = {}
    for row in rows:
        matches = names.get(row["device_name"], [])
        if len(matches) == 1 and matches[0]["pci_bdf"] in slots:
            bdf = matches[0]["pci_bdf"]
            row["pci_bdf"] = bdf
            row["lspci_line"] = slots[bdf]
            row["vendor_device_ids"] = (
                f"{(matches[0]['vendor_id'] or '0000')[2:]}:{(matches[0]['device_id'] or '0000')[2:]}"
                if matches[0]["vendor_id"] and matches[0]["device_id"] else None)
            row["loader_driver_name"] = matches[0]["driver_name"]
            row["binding_status"] = "BOUND"
        else:
            row["pci_bdf"] = None
            row["candidate_bdfs"] = sorted({m["pci_bdf"] for m in matches if m["pci_bdf"]})
            row["binding_status"] = "AMBIGUOUS" if matches else "UNRESOLVED"
    for row in rows:
        bdf, selector = row.get("pci_bdf"), row["selector"]
        if bdf is not None:
            other = seen_bdfs.get(bdf)
            if other is not None and other != selector:
                raise DiscoveryError(f"BDF {bdf} bound to multiple selectors")
            seen_bdfs[bdf] = selector
    return rows


def bind_selectors(rows: list[dict[str, Any]], loader_devices: list[dict[str, Any]],
                   lspci_text: str) -> list[dict[str, Any]]:
    """STRICT mechanical binder: every selector must bind to exactly one
    stable BDF or the whole inventory fails closed. This is the only
    binding an automated consumer may trust; ambiguous or missing
    bindings are never silently resolved.
    """
    classified = classify_bindings(rows, loader_devices, lspci_text)
    selectors = [row["selector"] for row in classified]
    if len(selectors) != len(set(selectors)):
        raise DiscoveryError("duplicate selector enumeration")
    for row in classified:
        if row["binding_status"] != "BOUND":
            raise DiscoveryError(
                f"selector {row['selector']} binding is {row['binding_status']} "
                f"(candidates: {row.get('candidate_bdfs', [])})")
    return classified


def build_inventory(*, runtime_executable: str, loader_probe: str | None = None,
                    listing_probe: str | None = None, lspci_text: str | None = None,
                    hostname: str | None = None, strict: bool = False) -> dict[str, Any]:
    """Measure the current Vulkan device inventory on this host.

    Physical inputs are injectable for CPU-only negative controls; when
    omitted they are measured from the host. Measurement happens on the
    PROVING NODE only — this module never reaches over the network.

    ``strict=True`` fails closed unless EVERY enumerated selector binds
    to exactly one stable BDF; the default records per-device binding
    status so ambiguous hardware (e.g. two identically-named GPUs) is
    visible inventory fact, never a silently-resolved binding.
    """
    import os

    hostname = hostname if hostname is not None else os.uname().nodename
    listing = listing_probe if listing_probe is not None else _command(
        [runtime_executable, "--list-devices"])
    loader = loader_probe if loader_probe is not None else _command(["vulkaninfo"])
    lspci_text = lspci_text if lspci_text is not None else _command(["lspci"])
    rows = classify_bindings(parse_device_rows(listing), parse_loader_pci_blocks(loader), lspci_text)
    if strict:
        # Re-derive under the strict binder to prove total resolvability.
        rows = bind_selectors(parse_device_rows(listing), parse_loader_pci_blocks(loader), lspci_text)
    loader_match = _LOADER_INSTANCE.search(loader)
    executable_sha = None
    if listing_probe is None:
        executable_sha = hashlib.sha256(Path(runtime_executable).read_bytes()).hexdigest()
    return {
        "schema": SCHEMA,
        "hostname": hostname,
        "node_identity_source": "os.uname().nodename on the proving node",
        "runtime_executable": runtime_executable,
        "runtime_executable_sha256": executable_sha,
        "vulkan_loader_identity": loader_match.group(1) if loader_match else None,
        "devices": [{**row, "descriptive_only": True} for row in rows],
        "authorization": "NON_AUTHORIZING",
        "nonclaims": [NON_AUTHORIZING],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-executable", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--strict", action="store_true",
                        help="fail closed unless every selector binds to exactly one BDF")
    args = parser.parse_args(argv)
    inventory = build_inventory(runtime_executable=args.runtime_executable, strict=args.strict)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(canonical(inventory) + b"\n")
    statuses = {d["selector"]: d["binding_status"] for d in inventory["devices"]}
    print(canonical({"result": "PASS", "devices": len(inventory["devices"]),
                     "binding_statuses": statuses, "non_authorizing": True}).decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
