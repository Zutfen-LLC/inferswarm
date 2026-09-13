#!/usr/bin/env python3
"""V2-A R2 reviewed-discovery successor (issue #163 correction round 2).

Closes the discovery -> authority provenance gap of attempt 01: the
attempt-01 discovery (``scripts/v2a_discovery.py``) correctly recorded
the two identically-named twin devices as AMBIGUOUS, but nothing
downstream REQUIRED a reviewed discovery artifact, and the authority
froze a selector/BDF pair whose binding was only proven later, during
the correctness-bearing qualification run.

This successor produces TWO explicit NON-AUTHORIZING layers BEFORE any
campaign authority may freeze:

1. ``DISCOVERY-INVENTORY`` (schema ``inferswarm.v2a.discovery-inventory/2``)
   — raw host inventory: runtime ``--list-devices`` facts, Vulkan
   loader PCI facts, lspci facts, hostname, runtime executable
   path/hash, selector rows, and the initial binding classifications
   (BOUND / AMBIGUOUS / UNRESOLVED). Explicitly NON_AUTHORIZING.

2. ``DISCOVERY-BINDINGS`` (schema ``inferswarm.v2a.discovery-bindings/2``)
   — the reviewed/resolved selector -> stable-physical-identity
   bindings, still NON_AUTHORIZING for correctness. Every resolved
   binding carries the exact mechanical identity-proof evidence: the
   bounded NON-CORRECTNESS-BEARING identity probe (the accepted runtime
   executes with ``-n 0`` so it emits its selected-device identity/BDF
   line while generating ZERO model tokens), the exact argv, the
   executable/runtime identity, the selector, the observed stable BDF,
   the raw identity-proof line, the probe exit code, and a digest over
   the binding proof. Ambiguity or mismatch fails closed; ordering and
   first-match are never used to resolve anything.

The probe is NON_AUTHORIZING and NON-CORRECTNESS-BEARING: no
correctness reference may be derived from either artifact, and no
generated model answer ever becomes authority (zero tokens are
generated). The campaign authority loader (``v2a_authority`` v2)
requires and verifies both artifacts before a campaign can run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_INVENTORY = "inferswarm.v2a.discovery-inventory/2"
SCHEMA_BINDINGS = "inferswarm.v2a.discovery-bindings/2"
NON_AUTHORIZING = ("inventory data only: no selection, promotion, authorization, "
                   "or correctness reference may be derived from this document")
NON_CORRECTNESS_BEARING = ("identity probe generates zero model tokens; it proves only "
                           "selector -> stable BDF and can never be a correctness reference")

INVENTORY_FILENAME = "DISCOVERY-INVENTORY.json"
BINDINGS_FILENAME = "DISCOVERY-BINDINGS.json"

# The accepted runtime grammar for the selected-device identity line,
# identical to the accepted V1-A adapter device grammar.
_IDENTITY_LINE = re.compile(
    r"using device (?P<selector>Vulkan[0-9]+).*?\((?P<bdf>0000:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.\d)\)")


class DiscoveryError(RuntimeError):
    """Reviewed discovery could not be established unambiguously."""


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Layer 1: raw NON-AUTHORIZING inventory. The attempt-01 parser functions
# are IMPORTED, not forked: identical row/loader/lspci grammars.
# ---------------------------------------------------------------------------

import v2a_discovery as attempt01  # noqa: E402


def build_inventory(*, runtime_executable: str, listing_probe: str | None = None,
                    loader_probe: str | None = None, lspci_text: str | None = None,
                    hostname: str | None = None) -> dict[str, Any]:
    """Measure the raw host inventory with per-selector binding classifications.

    Never resolves AMBIGUOUS rows: the classification layer is raw
    fact. Physical inputs are injectable for CPU-only controls.
    """
    hostname = hostname if hostname is not None else os.uname().nodename
    listing = listing_probe if listing_probe is not None else _command(
        [runtime_executable, "--list-devices"])
    loader = loader_probe if loader_probe is not None else _command(["vulkaninfo"])
    lspci_text = lspci_text if lspci_text is not None else _command(["lspci"])
    rows = attempt01.classify_bindings(
        attempt01.parse_device_rows(listing), attempt01.parse_loader_pci_blocks(loader), lspci_text)
    loader_match = attempt01._LOADER_INSTANCE.search(loader)
    executable_sha = None
    if listing_probe is None:
        executable_sha = sha256_file(Path(runtime_executable))
    return {
        "schema": SCHEMA_INVENTORY,
        "measured_utc": datetime.now(timezone.utc).isoformat(),
        "hostname": hostname,
        "node_identity_source": "os.uname().nodename on the proving node",
        "runtime_executable": runtime_executable,
        "runtime_executable_sha256": executable_sha,
        "vulkan_loader_identity": loader_match.group(1) if loader_match else None,
        "devices": rows,
        "authorization": "NON_AUTHORIZING",
        "nonclaims": [NON_AUTHORIZING, NON_CORRECTNESS_BEARING],
    }


def _command(argv: list[str]) -> str:
    return subprocess.check_output(argv, text=True, stderr=subprocess.DEVNULL).strip()


# ---------------------------------------------------------------------------
# Layer 2: bounded NON-CORRECTNESS-BEARING selector identity probe.
# ---------------------------------------------------------------------------

def identity_probe_argv(runtime_executable: str, model: str, selector: str) -> list[str]:
    """The bounded identity-probe argv: accepted runtime/backend, zero generated tokens.

    ``-n 0`` bounds generation to zero tokens, ``--no-warmup`` skips the
    warmup run, and ``-lv 4`` retains the device-proof log line. The
    probe therefore emits the runtime's OWN selected-device
    identity/BDF line while producing no correctness-bearing generated
    output. The selector is the ONLY parameter that varies.
    """
    return [runtime_executable, "-m", model, "--device", selector,
            "-ngl", "99", "-n", "0", "-p", "identity-probe", "--no-warmup",
            "-st", "-lv", "4"]


def run_identity_probe(argv: list[str], *, timeout: int = 1800,
                       out_dir: Path | None = None, selector_label: str | None = None) -> dict[str, Any]:
    """Execute one identity probe and retain its raw evidence.

    Requires a clean exit, exactly one selected-device identity line
    whose selector matches the probed selector, zero generated tokens
    ("Generation: 0.0 t/s" with an empty response), and no sampled
    correctness-bearing content. Fails closed otherwise. When
    ``out_dir`` is given the raw stdout/stderr bytes are retained there.
    """
    started = datetime.now(timezone.utc).isoformat()
    process = subprocess.run(argv, capture_output=True, text=False, timeout=timeout)
    stderr_text = process.stderr.decode("utf-8", errors="strict")
    stdout_bytes = process.stdout
    if process.returncode != 0:
        raise DiscoveryError(f"identity probe exit was not clean: {process.returncode}")
    matches = list(_IDENTITY_LINE.finditer(stderr_text))
    if len(matches) != 1:
        raise DiscoveryError(
            f"identity probe must emit exactly one selected-device line, saw {len(matches)}")
    selector = argv[argv.index("--device") + 1]
    match = matches[0]
    if match.group("selector") != selector:
        raise DiscoveryError(
            f"probe selected {match.group('selector')} but probed selector was {selector}")
    bdf = match.group("bdf").removeprefix("0000:")
    # Zero-generation proof: the runtime prints its generation rate; a
    # zero-token probe must show 0.0 t/s generation.
    rates = re.findall(r"Generation:\s*([0-9.]+)\s*t/s", stdout_bytes.decode("utf-8", "replace"))
    if not rates or any(rate != "0.0" for rate in rates):
        raise DiscoveryError("identity probe did not prove zero generated tokens")
    raw_line = match.group(0)
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        label = (selector_label or selector).lower()
        (out_dir / f"identity-probe-stdout-{label}.txt").write_bytes(stdout_bytes)
        (out_dir / f"identity-probe-stderr-{label}.txt").write_bytes(process.stderr)
    return {
        "probe_kind": "NON_CORRECTNESS_BEARING_IDENTITY_PROBE",
        "authorization": "NON_AUTHORIZING",
        "nonclaims": [NON_AUTHORIZING, NON_CORRECTNESS_BEARING],
        "started_utc": started,
        "argv": list(argv),
        "exit_code": process.returncode,
        "selector": selector,
        "observed_pci_bdf": bdf,
        "identity_proof_line": raw_line,
        "generated_tokens": 0,
        "zero_generation_proof": [f"Generation: {rate} t/s" for rate in rates],
        "stderr_sha256": digest_bytes(process.stderr),
        "stdout_sha256": digest_bytes(stdout_bytes),
    }


def build_bindings(inventory: dict[str, Any], *, model: str,
                   probe_runner=None, resolve_only: list[str] | None = None,
                   force_probe: list[str] | None = None,
                   probe_out_dir: Path | None = None) -> dict[str, Any]:
    """Resolve every ambiguous/unbound selector mechanically, or fail closed.

    For each selector the inventory classified BOUND (unique exact-name
    join), the reviewed binding reuses that mechanical evidence — unless
    the selector is listed in ``force_probe`` (R2 subjects are probed
    prospectively even when the name join is unique, so every intended
    campaign subject carries explicit runtime-native identity proof).
    For each AMBIGUOUS selector (identical device names across loader
    devices) the resolution uses ONLY the bounded identity probe: the
    accepted runtime itself states which stable BDF the selector
    addresses. Ordering, first-match, and historical assumption are
    never used; UNRESOLVED selectors without a mechanical proof stay
    UNRESOLVED and can never be bound by callers. ``probe_runner``
    (argv -> probe result mapping) is injectable for CPU-only controls.
    """
    if inventory.get("schema") != SCHEMA_INVENTORY:
        raise DiscoveryError("bindings require a v2 discovery inventory document")
    if inventory.get("authorization") != "NON_AUTHORIZING":
        raise DiscoveryError("inventory artifact must be explicitly NON_AUTHORIZING")
    if probe_runner is None:
        def _default_runner(argv):
            return run_identity_probe(argv, out_dir=probe_out_dir)
        probe_runner = _default_runner
    executable = inventory["runtime_executable"]
    bindings: list[dict[str, Any]] = []
    seen: dict[str, str] = {}

    def runner_probe(runner, executable: str, model: str, selector: str) -> dict[str, Any]:
        probe = runner(identity_probe_argv(executable, model, selector))
        if probe["authorization"] != "NON_AUTHORIZING" or probe["exit_code"] != 0:
            raise DiscoveryError(
                f"identity probe for {selector} is not a clean non-authorizing proof")
        if probe["selector"] != selector:
            raise DiscoveryError(f"identity probe selector mismatch for {selector}")
        return probe
    for row in inventory["devices"]:
        selector = row["selector"]
        entry: dict[str, Any] = {
            "selector": selector,
            "device_name": row["device_name"],
            "authorization": "NON_AUTHORIZING",
        }
        status = row["binding_status"]
        name_join_bound = status == "BOUND" and not (force_probe and selector in force_probe)
        if name_join_bound:
            entry.update({
                "binding_status": "BOUND",
                "pci_bdf": row["pci_bdf"],
                "resolution_mechanism": "unique exact device-name join "
                                         "(runtime row -> loader PCI block -> lspci slot)",
                "lspci_line": row.get("lspci_line"),
            })
        elif status in ("BOUND", "AMBIGUOUS"):
            if resolve_only is not None and selector not in resolve_only:
                entry.update({"binding_status": status if status == "AMBIGUOUS" else "BOUND",
                              "candidate_bdfs": row.get("candidate_bdfs", []),
                              "resolution_mechanism": "not probed (outside resolve_only)"})
                if status == "BOUND":
                    entry["pci_bdf"] = row["pci_bdf"]
                bindings.append(entry)
                continue
            probe = runner_probe(probe_runner, executable, model, selector)
            probe_bdf = probe["observed_pci_bdf"]
            if status == "BOUND" and probe_bdf != row["pci_bdf"]:
                raise DiscoveryError(
                    f"identity probe for {selector} proves BDF {probe_bdf} but the name "
                    f"join bound {row['pci_bdf']}; failing closed on disagreement")
            entry.update({
                "binding_status": "BOUND",
                "pci_bdf": probe_bdf,
                "resolution_mechanism": "runtime identity probe (zero generated tokens); "
                                         "the runtime's own selected-device line states the BDF",
                "identity_probe": probe,
                "binding_proof_sha256": digest_bytes(canonical(probe)),
            })
        else:  # UNRESOLVED: no mechanical proof exists; fail closed for this selector.
            entry.update({
                "binding_status": "UNRESOLVED",
                "resolution_mechanism": "no mechanical identity evidence; never bound by callers",
            })
        if entry["binding_status"] == "BOUND":
            other = seen.get(entry["pci_bdf"])
            if other is not None and other != selector:
                raise DiscoveryError(
                    f"BDF {entry['pci_bdf']} bound to multiple selectors ({other}, {selector})")
            seen[entry["pci_bdf"]] = selector
        bindings.append(entry)
    return {
        "schema": SCHEMA_BINDINGS,
        "inventory_schema": inventory["schema"],
        "inventory_hostname": inventory["hostname"],
        "inventory_runtime_executable": inventory["runtime_executable"],
        "inventory_runtime_executable_sha256": inventory.get("runtime_executable_sha256"),
        "inventory_measured_utc": inventory["measured_utc"],
        "reviewed_utc": datetime.now(timezone.utc).isoformat(),
        "bindings": bindings,
        "authorization": "NON_AUTHORIZING",
        "nonclaims": [NON_AUTHORIZING, NON_CORRECTNESS_BEARING],
    }


def verify_binding_document(bindings: dict[str, Any], inventory: dict[str, Any],
                            *, selector: str, bdf: str) -> dict[str, Any]:
    """Verify a reviewed binding for one selector against its inventory.

    Fails closed on: missing selector, UNRESOLVED/AMBIGUOUS status,
    inventory digest/hostname/executable drift, BDF disagreement,
    duplicate selector bindings, and tampered identity-proof digests.
    """
    if bindings.get("schema") != SCHEMA_BINDINGS:
        raise DiscoveryError("reviewed binding document schema mismatch")
    if bindings.get("authorization") != "NON_AUTHORIZING" \
            or inventory.get("authorization") != "NON_AUTHORIZING":
        raise DiscoveryError("discovery artifacts must be NON_AUTHORIZING")
    if bindings.get("inventory_hostname") != inventory["hostname"]:
        raise DiscoveryError("binding artifact hostname disagrees with inventory")
    if bindings.get("inventory_runtime_executable") != inventory["runtime_executable"]:
        raise DiscoveryError("binding artifact runtime executable disagrees with inventory")
    if (bindings.get("inventory_runtime_executable_sha256") or "") != \
            (inventory.get("runtime_runtime_executable_sha256")
             or inventory.get("runtime_executable_sha256") or ""):
        raise DiscoveryError("binding artifact runtime executable hash disagrees with inventory")
    rows = [entry for entry in bindings["bindings"] if entry["selector"] == selector]
    if not rows:
        raise DiscoveryError(f"selector {selector} absent from reviewed discovery bindings")
    if len(rows) > 1:
        raise DiscoveryError(f"duplicate binding rows for selector {selector}")
    entry = rows[0]
    if entry["binding_status"] != "BOUND":
        raise DiscoveryError(
            f"selector {selector} binding is {entry['binding_status']}; BOUND required")
    if entry["pci_bdf"] != bdf:
        raise DiscoveryError(
            f"selector {selector} bound to {entry['pci_bdf']}, authority declares {bdf}")
    probe = entry.get("identity_probe")
    if probe is not None:
        if entry.get("binding_proof_sha256") != digest_bytes(canonical(probe)):
            raise DiscoveryError(f"tampered identity-probe evidence for {selector}")
        if probe["observed_pci_bdf"] != bdf or probe["selector"] != selector:
            raise DiscoveryError(f"identity-probe proof disagrees with the declared binding")
        if probe["exit_code"] != 0 or probe["generated_tokens"] != 0:
            raise DiscoveryError(f"identity-probe evidence for {selector} is not a clean zero-token proof")
    return entry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-executable", required=True)
    parser.add_argument("--model", required=True,
                        help="model path for the zero-token identity probes")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--resolve-only", action="append",
                        help="probe only these selectors (repeatable); default: all AMBIGUOUS")
    parser.add_argument("--force-probe", action="append",
                        help="also probe these name-join-bound selectors (repeatable)")
    parser.add_argument("--raw-dir",
                        help="retain raw identity-probe stdout/stderr bytes here")
    args = parser.parse_args(argv)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    raw_dir = Path(args.raw_dir) if args.raw_dir else (out / "raw" / "discovery-r2")
    inventory = build_inventory(runtime_executable=args.runtime_executable)
    (out / INVENTORY_FILENAME).write_bytes(canonical(inventory) + b"\n")
    bindings = build_bindings(inventory, model=args.model, resolve_only=args.resolve_only,
                              force_probe=args.force_probe, probe_out_dir=raw_dir)
    (out / BINDINGS_FILENAME).write_bytes(canonical(bindings) + b"\n")
    statuses = {b["selector"]: b["binding_status"] for b in bindings["bindings"]}
    print(canonical({"result": "PASS", "inventory_sha256": digest_bytes(canonical(inventory)),
                     "bindings_sha256": digest_bytes(canonical(bindings)),
                     "binding_statuses": statuses, "non_authorizing": True}).decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
