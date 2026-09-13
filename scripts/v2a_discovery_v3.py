#!/usr/bin/env python3
"""V2-A R3 reviewed-discovery successor (issue #163 correction round 3).

Supersedes ``scripts/v2a_discovery_v2.py`` (R2, retained byte-unchanged)
for new discovery artifacts. The R2 layer correctly bound selector ->
stable BDF through the bounded zero-token identity probe, but two
provenance seams remained, both identified by the maintainer NO-GO
review of PR #164 head ``1c724d3``:

1. **Freshness stopped at the review event.** The R2 bindings artifact
   carried ``inventory_measured_utc`` as prose-ish copied data that the
   R2 authority loader never validated, and the loader aged only
   ``bindings.reviewed_utc``. A fresh review of a months-old physical
   inventory could authorize a correctness-bearing campaign against a
   host that no longer matches the measurement. #163 requires stale
   INVENTORY to fail closed, independently of the review.

2. **Raw probe bytes were bound only by self-reported digests.** The
   R2 structured probe record hashed its own stdout/stderr, but nothing
   mechanically re-derived the structured fields (identity line, BDF,
   zero-generation proof) from the RETAINED RAW BYTES. An injected
   probe result could carry any identity_proof_line it liked, and the
   retained raw files could be swapped without detection.

This module produces schemas ``inferswarm.v2a.discovery-inventory/3``
and ``inferswarm.v2a.discovery-bindings/3``:

* the inventory is the R2 inventory plus a required timezone-aware
  ``measured_utc`` (malformed/naive/missing timestamps fail closed at
  build AND at every downstream verification);
* the bindings artifact binds each probed selector to its retained raw
  probe streams by explicit ``raw_stdout_path``/``raw_stderr_path``
  (repository-relative) plus digests over the RAW BYTES;
* ONE shared probe-validation path (``validate_probe``) derives the
  identity line, the BDF, and the zero-generation proof FROM raw
  stdout/stderr bytes and checks every structured field against that
  derivation. It is the same function for freshly executed probes,
  CPU-injected probes, and later re-verification of the retained
  artifacts — there is no second, weaker validation path.

The probe remains NON_AUTHORIZING and NON_CORRECTNESS_BEARING: it
generates zero model tokens and no correctness reference may ever be
derived from these artifacts.
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

import v2a_discovery_v2 as r2  # noqa: E402  (R2 layer, imported not forked)

SCHEMA_INVENTORY = "inferswarm.v2a.discovery-inventory/3"
SCHEMA_BINDINGS = "inferswarm.v2a.discovery-bindings/3"
NON_AUTHORIZING = r2.NON_AUTHORIZING
NON_CORRECTNESS_BEARING = r2.NON_CORRECTNESS_BEARING

INVENTORY_FILENAME = "DISCOVERY-INVENTORY-R3.json"
BINDINGS_FILENAME = "DISCOVERY-BINDINGS-R3.json"

_IDENTITY_LINE = r2._IDENTITY_LINE
_GENERATION_RATE = re.compile(r"Generation:\s*([0-9]*\.?[0-9]+)\s*t/s")


class DiscoveryError(RuntimeError):
    """Reviewed discovery could not be established or re-verified."""


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Timestamp contract: timezone-aware ISO-8601, fail-closed everywhere.
# ---------------------------------------------------------------------------

def parse_utc_timestamp(value: Any, *, label: str) -> datetime:
    """Parse a required timezone-aware ISO-8601 timestamp or fail closed.

    Rejects missing, non-string, malformed, and NAIVE (timezone-free)
    timestamps. Returns an aware datetime normalized to UTC.
    """
    if not isinstance(value, str) or not value.strip():
        raise DiscoveryError(f"{label} timestamp is missing or not a string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise DiscoveryError(f"{label} timestamp is malformed: {value!r}")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DiscoveryError(f"{label} timestamp must be timezone-aware: {value!r}")
    return parsed.astimezone(timezone.utc)


def require_chronology(first: datetime, second: datetime, *, what: str) -> None:
    """Require ``first <= second`` or fail closed (inverted chronology)."""
    if first > second:
        raise DiscoveryError(
            f"inverted chronology: {what} ({first.isoformat()} > {second.isoformat()})")


# ---------------------------------------------------------------------------
# Layer 1: raw NON_AUTHORIZING inventory with a validated measured_utc.
# ---------------------------------------------------------------------------

def build_inventory(*, runtime_executable: str, listing_probe: str | None = None,
                    loader_probe: str | None = None, lspci_text: str | None = None,
                    hostname: str | None = None,
                    measured_utc: str | None = None) -> dict[str, Any]:
    """Measure the raw host inventory with per-selector binding classifications.

    Identical fact surface to the R2 inventory (whose grammars import the
    accepted attempt-01 parser), plus a strictly validated timezone-aware
    ``measured_utc``. Physical inputs and the timestamp are injectable
    for CPU-only controls; a malformed/naive injected timestamp fails
    closed exactly like a malformed physical clock.
    """
    hostname = hostname if hostname is not None else os.uname().nodename
    listing = listing_probe if listing_probe is not None else r2._command(
        [runtime_executable, "--list-devices"])
    loader = loader_probe if loader_probe is not None else r2._command(["vulkaninfo"])
    lspci_text = lspci_text if lspci_text is not None else r2._command(["lspci"])
    rows = r2.attempt01.classify_bindings(
        r2.attempt01.parse_device_rows(listing), r2.attempt01.parse_loader_pci_blocks(loader), lspci_text)
    loader_match = r2.attempt01._LOADER_INSTANCE.search(loader)
    executable_sha = None
    if listing_probe is None:
        executable_sha = sha256_file(Path(runtime_executable))
    stamp = parse_utc_timestamp(
        measured_utc if measured_utc is not None else datetime.now(timezone.utc).isoformat(),
        label="inventory measured_utc")
    return {
        "schema": SCHEMA_INVENTORY,
        "measured_utc": stamp.isoformat(),
        "hostname": hostname,
        "node_identity_source": "os.uname().nodename on the proving node",
        "runtime_executable": runtime_executable,
        "runtime_executable_sha256": executable_sha,
        "vulkan_loader_identity": loader_match.group(1) if loader_match else None,
        "devices": rows,
        "authorization": "NON_AUTHORIZING",
        "nonclaims": [NON_AUTHORIZING, NON_CORRECTNESS_BEARING],
    }


# ---------------------------------------------------------------------------
# THE shared probe-validation path. Real executions, CPU-injected probe
# results, and later re-verification of retained artifacts all pass through
# validate_probe(); there is no separate weaker path for injected data.
# ---------------------------------------------------------------------------

def validate_probe(probe: dict[str, Any], *, raw_stdout: bytes, raw_stderr: bytes,
                   expected_selector: str | None = None) -> dict[str, Any]:
    """Mechanically validate a structured probe result against RAW bytes.

    Fails closed unless the structured record is exactly what the raw
    stdout/stderr bytes prove:

    * ``stdout_sha256``/``stderr_sha256`` equal the digests of the given
      raw bytes (the caller supplies the bytes — never the claim);
    * the raw stderr contains exactly ONE selected-device identity line,
      its selector equals the probe's selector (and the expected selector
      when given), and its BDF equals ``observed_pci_bdf``;
    * ``identity_proof_line`` equals that exact raw line;
    * the raw stdout proves ZERO generated tokens: at least one
      ``Generation: N t/s`` rate exists and every rate is exactly 0.0 —
      an injected ``zero_generation_proof`` list cannot substitute for
      the raw bytes' own generation rates;
    * ``generated_tokens`` is exactly 0 and ``exit_code`` is exactly 0;
    * argv is the bounded identity-probe argv with ``-n 0``.

    Returns the validated probe record (unchanged).
    """
    if not isinstance(probe, dict):
        raise DiscoveryError("probe result must be a mapping")
    if probe.get("probe_kind") != "NON_CORRECTNESS_BEARING_IDENTITY_PROBE":
        raise DiscoveryError("probe result is not a non-correctness-bearing identity probe")
    if probe.get("authorization") != "NON_AUTHORIZING":
        raise DiscoveryError("probe result must be explicitly NON_AUTHORIZING")
    if probe.get("exit_code") != 0:
        raise DiscoveryError("identity probe exit was not clean")
    if probe.get("generated_tokens") != 0:
        raise DiscoveryError("identity probe did not prove zero generated tokens")
    # Raw byte binding: the structured digests must match the raw bytes
    # the caller holds, and the structured proof fields must match what
    # those bytes mechanically contain.
    if probe.get("stdout_sha256") != digest_bytes(raw_stdout):
        raise DiscoveryError("probe stdout_sha256 does not match the retained raw stdout bytes")
    if probe.get("stderr_sha256") != digest_bytes(raw_stderr):
        raise DiscoveryError("probe stderr_sha256 does not match the retained raw stderr bytes")
    try:
        stderr_text = raw_stderr.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise DiscoveryError("retained raw probe stderr is not valid UTF-8")
    matches = list(_IDENTITY_LINE.finditer(stderr_text))
    if len(matches) != 1:
        raise DiscoveryError(
            f"raw probe stderr must contain exactly one selected-device line, saw {len(matches)}")
    match = matches[0]
    selector = probe.get("selector")
    if not isinstance(selector, str) or not selector:
        raise DiscoveryError("probe result is missing its selector")
    if match.group("selector") != selector:
        raise DiscoveryError(
            f"raw proof line selects {match.group('selector')} but the probe claims {selector}")
    if expected_selector is not None and selector != expected_selector:
        raise DiscoveryError(
            f"probe selector {selector} does not match the probed selector {expected_selector}")
    if probe.get("identity_proof_line") != match.group(0):
        raise DiscoveryError("probe identity_proof_line is not the raw proof line")
    if probe.get("observed_pci_bdf") != match.group("bdf").removeprefix("0000:"):
        raise DiscoveryError("probe observed_pci_bdf is not the raw proof line's BDF")
    rates = _GENERATION_RATE.findall(raw_stdout.decode("utf-8", "replace"))
    if not rates or any(rate != "0.0" for rate in rates):
        raise DiscoveryError("raw probe stdout does not prove zero generated tokens")
    declared = probe.get("zero_generation_proof")
    expected_proof = [f"Generation: {rate} t/s" for rate in rates]
    if declared != expected_proof:
        raise DiscoveryError("probe zero_generation_proof disagrees with the raw stdout rates")
    argv = probe.get("argv")
    if not isinstance(argv, list) or "--device" not in argv or "-n" not in argv:
        raise DiscoveryError("probe argv is not the bounded identity-probe argv")
    if argv[argv.index("-n") + 1] != "0":
        raise DiscoveryError("probe argv does not bound generation to zero tokens (-n 0)")
    return probe


# ---------------------------------------------------------------------------
# Layer 2: reviewed bindings with raw-byte-bound probe evidence.
# ---------------------------------------------------------------------------

def identity_probe_argv(runtime_executable: str, model: str, selector: str) -> list[str]:
    """The bounded identity-probe argv (inherited R2 semantics)."""
    return r2.identity_probe_argv(runtime_executable, model, selector)


def run_identity_probe(argv: list[str], *, timeout: int = 1800,
                       out_dir: Path | None = None, selector_label: str | None = None,
                       raw_root: Path | None = None,
                       raw_rel_dir: str | None = None) -> dict[str, Any]:
    """Execute one identity probe, retain raw bytes, and structure it.

    The structured record is built and validated against the JUST
    RETAINED raw bytes through the shared ``validate_probe`` path, and
    carries explicit repository-relative ``raw_stdout_path`` /
    ``raw_stderr_path`` so later verification re-reads and re-derives
    from the retained bytes (never from self-reported digests alone).
    """
    started = datetime.now(timezone.utc).isoformat()
    process = subprocess.run(argv, capture_output=True, text=False, timeout=timeout)
    stdout_bytes, stderr_bytes = process.stdout, process.stderr
    label = (selector_label or argv[argv.index("--device") + 1]).lower()
    rel_stdout = rel_stderr = None
    if raw_root is not None:
        raw_root.mkdir(parents=True, exist_ok=True)
        rel_stdout = f"{raw_rel_dir or '.'}/identity-probe-stdout-{label}.txt"
        rel_stderr = f"{raw_rel_dir or '.'}/identity-probe-stderr-{label}.txt"
        (raw_root / rel_stdout).write_bytes(stdout_bytes)
        (raw_root / rel_stderr).write_bytes(stderr_bytes)
    elif out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"identity-probe-stdout-{label}.txt").write_bytes(stdout_bytes)
        (out_dir / f"identity-probe-stderr-{label}.txt").write_bytes(stderr_bytes)
    probe = {
        "probe_kind": "NON_CORRECTNESS_BEARING_IDENTITY_PROBE",
        "authorization": "NON_AUTHORIZING",
        "nonclaims": [NON_AUTHORIZING, NON_CORRECTNESS_BEARING],
        "started_utc": started,
        "argv": list(argv),
        "exit_code": process.returncode,
        "selector": argv[argv.index("--device") + 1],
        "raw_stdout_path": rel_stdout,
        "raw_stderr_path": rel_stderr,
        "stdout_sha256": digest_bytes(stdout_bytes),
        "stderr_sha256": digest_bytes(stderr_bytes),
    }
    # Derive the identity/binding fields FROM the raw bytes via the one
    # shared validation path, then freeze them into the record.
    matches = list(_IDENTITY_LINE.finditer(stderr_bytes.decode("utf-8", "strict")))
    rates = _GENERATION_RATE.findall(stdout_bytes.decode("utf-8", "replace"))
    probe.update({
        "observed_pci_bdf": matches[0].group("bdf").removeprefix("0000:") if len(matches) == 1 else None,
        "identity_proof_line": matches[0].group(0) if len(matches) == 1 else None,
        "generated_tokens": 0,
        "zero_generation_proof": [f"Generation: {rate} t/s" for rate in rates],
    })
    validate_probe(probe, raw_stdout=stdout_bytes, raw_stderr=stderr_bytes)
    return probe


def validate_probe_record(probe: dict[str, Any], *, raw_root: Path,
                          expected_selector: str | None = None) -> dict[str, Any]:
    """Re-verify a RETAINED structured probe record against its retained raw bytes.

    The raw paths are repository-relative under ``raw_root``; the raw
    bytes are read from disk and pushed through the same shared
    ``validate_probe`` path used for fresh executions and CPU controls.
    Tampering with either raw file while leaving the structured record
    (or its digest fields) unchanged fails closed here.
    """
    for key in ("raw_stdout_path", "raw_stderr_path"):
        if not isinstance(probe.get(key), str) or not probe[key]:
            raise DiscoveryError(f"retained probe record is missing {key}")
    stdout_path, stderr_path = raw_root / probe["raw_stdout_path"], raw_root / probe["raw_stderr_path"]
    for path in (stdout_path, stderr_path):
        if not path.is_file():
            raise DiscoveryError(f"retained raw probe bytes are missing: {path}")
    return validate_probe(probe, raw_stdout=stdout_path.read_bytes(),
                          raw_stderr=stderr_path.read_bytes(), expected_selector=expected_selector)


def build_bindings(inventory: dict[str, Any], *, model: str,
                   probe_runner=None, resolve_only: list[str] | None = None,
                   force_probe: list[str] | None = None,
                   raw_root: Path | None = None, raw_rel_dir: str = "raw/discovery-r3",
                   reviewed_utc: str | None = None) -> dict[str, Any]:
    """Resolve every ambiguous/unbound selector mechanically, or fail closed.

    Same resolution doctrine as R2 (probe resolution only; ordering,
    first-match, and historical assumption never resolve anything), with
    every probe result validated through the shared raw-byte path. A
    CPU-injected ``probe_runner`` result carries its own synthetic raw
    bytes (``raw_stdout``/``raw_stderr`` keys, stripped after
    validation) so injected results exercise the SAME invariant as
    production probes. The bindings artifact records the physical
    inventory measurement timestamp (validated) alongside its review
    timestamp (validated), and enforces
    ``inventory measured <= reviewed``.
    """
    if inventory.get("schema") != SCHEMA_INVENTORY:
        raise DiscoveryError("bindings require a v3 discovery inventory document")
    if inventory.get("authorization") != "NON_AUTHORIZING":
        raise DiscoveryError("inventory artifact must be explicitly NON_AUTHORIZING")
    measured = parse_utc_timestamp(inventory.get("measured_utc"), label="inventory measured_utc")
    reviewed = parse_utc_timestamp(
        reviewed_utc if reviewed_utc is not None else datetime.now(timezone.utc).isoformat(),
        label="bindings reviewed_utc")
    require_chronology(measured, reviewed, what="inventory measured_utc after reviewed_utc")
    executable = inventory["runtime_executable"]
    bindings: list[dict[str, Any]] = []
    seen: dict[str, str] = {}

    def runner_probe(runner, exe: str, mdl: str, selector: str) -> dict[str, Any]:
        argv = identity_probe_argv(exe, mdl, selector)
        probe = runner(argv)
        if not isinstance(probe, dict):
            raise DiscoveryError(f"identity probe for {selector} did not return a mapping")
        if probe.get("authorization") != "NON_AUTHORIZING" or probe.get("exit_code") != 0:
            raise DiscoveryError(
                f"identity probe for {selector} is not a clean non-authorizing proof")
        if probe.get("selector") != selector:
            raise DiscoveryError(f"identity probe selector mismatch for {selector}")
        raw_stdout, raw_stderr = probe.get("raw_stdout"), probe.get("raw_stderr")
        if isinstance(raw_stdout, bytes) and isinstance(raw_stderr, bytes):
            # CPU-injected probe carrying its own synthetic raw bytes:
            # validate through the SAME shared path as real executions.
            stripped = {k: v for k, v in probe.items() if k not in ("raw_stdout", "raw_stderr")}
            return validate_probe(stripped, raw_stdout=raw_stdout, raw_stderr=raw_stderr,
                                  expected_selector=selector)
        # Real retained record: re-verify against the retained raw bytes.
        if raw_root is not None:
            return validate_probe_record(probe, raw_root=raw_root, expected_selector=selector)
        raise DiscoveryError(
            f"identity probe for {selector} carries no raw bytes to validate against")

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
        "reviewed_utc": reviewed.isoformat(),
        "bindings": bindings,
        "authorization": "NON_AUTHORIZING",
        "nonclaims": [NON_AUTHORIZING, NON_CORRECTNESS_BEARING],
    }


def verify_binding_document(bindings: dict[str, Any], inventory: dict[str, Any],
                            *, selector: str, bdf: str,
                            raw_root: Path | None = None) -> dict[str, Any]:
    """Verify a reviewed binding for one selector against its inventory.

    Fails closed on everything the R2 verifier rejected (schema,
    NON_AUTHORIZING status, hostname/executable drift, missing or
    duplicate rows, non-BOUND status, BDF disagreement, tampered proof
    digests) PLUS:

    * ``bindings.inventory_measured_utc`` must EQUAL the digest-verified
      inventory's ``measured_utc`` (the copied field cannot diverge from
      the artifact it claims to summarize);
    * both timestamps must parse timezone-aware and satisfy
      ``inventory measured <= reviewed``;
    * when raw probe bytes are retained, the probe record re-verifies
      against those bytes through the shared validation path (tampered
      raw stdout/stderr fails closed).
    """
    if bindings.get("schema") != SCHEMA_BINDINGS:
        raise DiscoveryError("reviewed binding document schema mismatch")
    if bindings.get("authorization") != "NON_AUTHORIZING" \
            or inventory.get("authorization") != "NON_AUTHORIZING":
        raise DiscoveryError("discovery artifacts must be NON_AUTHORIZING")
    if inventory.get("schema") != SCHEMA_INVENTORY:
        raise DiscoveryError("reviewed bindings require a v3 inventory document")
    if bindings.get("inventory_hostname") != inventory["hostname"]:
        raise DiscoveryError("binding artifact hostname disagrees with inventory")
    if bindings.get("inventory_runtime_executable") != inventory["runtime_executable"]:
        raise DiscoveryError("binding artifact runtime executable disagrees with inventory")
    if (bindings.get("inventory_runtime_executable_sha256") or "") != \
            (inventory.get("runtime_executable_sha256") or ""):
        raise DiscoveryError("binding artifact runtime executable hash disagrees with inventory")
    # The copied measurement timestamp must be EXACTLY the inventory's.
    if bindings.get("inventory_measured_utc") != inventory.get("measured_utc"):
        raise DiscoveryError(
            "bindings inventory_measured_utc disagrees with the digest-verified inventory")
    measured = parse_utc_timestamp(inventory.get("measured_utc"), label="inventory measured_utc")
    reviewed = parse_utc_timestamp(bindings.get("reviewed_utc"), label="bindings reviewed_utc")
    require_chronology(measured, reviewed, what="inventory measured_utc after reviewed_utc")
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
        if probe.get("observed_pci_bdf") != bdf or probe.get("selector") != selector:
            raise DiscoveryError(f"identity-probe proof disagrees with the declared binding")
        if probe.get("exit_code") != 0 or probe.get("generated_tokens") != 0:
            raise DiscoveryError(f"identity-probe evidence for {selector} is not a clean zero-token proof")
        # Raw-byte provenance: re-derive the structured proof fields from
        # the RETAINED raw bytes through the one shared validation path.
        if raw_root is not None:
            validate_probe_record(probe, raw_root=raw_root, expected_selector=selector)
    return entry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-executable", required=True)
    parser.add_argument("--model", required=True,
                        help="model path for the zero-token identity probes")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--repo-root", default=".",
                        help="repository root resolving retained raw-probe paths")
    parser.add_argument("--raw-dir", default="docs/investigations/vulkan-v2-a/raw/discovery-r3",
                        help="repository-relative directory retaining raw probe bytes")
    parser.add_argument("--resolve-only", action="append",
                        help="probe only these selectors (repeatable); default: all AMBIGUOUS")
    parser.add_argument("--force-probe", action="append",
                        help="also probe these name-join-bound selectors (repeatable)")
    args = parser.parse_args(argv)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    root = Path(args.repo_root)
    raw_root = root / args.raw_dir
    raw_root.mkdir(parents=True, exist_ok=True)
    inventory = build_inventory(runtime_executable=args.runtime_executable)
    (out / INVENTORY_FILENAME).write_bytes(canonical(inventory) + b"\n")
    bindings = build_bindings(inventory, model=args.model, resolve_only=args.resolve_only,
                              force_probe=args.force_probe, raw_root=root,
                              raw_rel_dir=args.raw_dir)
    (out / BINDINGS_FILENAME).write_bytes(canonical(bindings) + b"\n")
    statuses = {b["selector"]: b["binding_status"] for b in bindings["bindings"]}
    print(canonical({"result": "PASS", "inventory_sha256": digest_bytes(canonical(inventory)),
                     "bindings_sha256": digest_bytes(canonical(bindings)),
                     "inventory_measured_utc": inventory["measured_utc"],
                     "reviewed_utc": bindings["reviewed_utc"],
                     "binding_statuses": statuses, "non_authorizing": True}).decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
