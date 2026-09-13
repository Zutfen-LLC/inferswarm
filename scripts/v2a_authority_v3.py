#!/usr/bin/env python3
"""V2-A R3 campaign authority contract successor (issue #163 correction round 3).

Supersedes ``scripts/v2a_authority_v2.py`` (R2, retained byte-unchanged)
as the loader required for correctness-bearing campaigns. The R2 loader
correctly required a digest-verified reviewed-discovery binding, but it
aged ONLY the review event: ``bindings.reviewed_utc`` had to be within
``max_discovery_age_hours`` of the authority freeze, while the physical
inventory measurement timestamp (``DISCOVERY-INVENTORY.measured_utc``)
was never required, never cross-checked, and never aged. Issue #163
requires stale INVENTORY to fail closed; a fresh review of a stale
physical measurement must not authorize a campaign. That gap is why the
R2 terminal is superseded (R2-SUPERSESSION.json).

Schema ``inferswarm.v2a.campaign-authority/3`` keeps every R2 field and
adds one required binding field::

    "inventory_measured_utc": <ISO-8601, timezone-aware>

At load time the loader verifies, mechanically and fail-closed, in
addition to every accepted v1 and R2 check:

* the inventory artifact carries a well-formed timezone-aware
  ``measured_utc`` (malformed, naive, or missing rejected);
* ``discovery_binding.inventory_measured_utc`` EQUALS the digest-verified
  inventory's ``measured_utc`` (the copied field cannot diverge from the
  artifact it summarizes);
* ``discovery_binding.reviewed_utc`` equals the bindings artifact's
  ``reviewed_utc`` (as in R2) and the bindings artifact's
  ``inventory_measured_utc`` equals the inventory's (as in R3 discovery);
* chronology is enforced at the LOADER, not just at build time:
  ``inventory measured <= reviewed <= anchor``, where the anchor is the
  authority freeze time (``frozen_at``) or the current time; a future or
  inverted timestamp is rejected;
* the configured ``max_discovery_age_hours`` bounds the PHYSICAL
  INVENTORY MEASUREMENT against the anchor — not merely the review
  event — so a fresh review of a >72h-stale inventory fails closed;
* the retained raw identity-probe bytes re-verify against the structured
  proof through the shared R3 validation path: raw byte digest ->
  structured digest field -> identity/BDF -> zero-generation proof.

No caller-supplied enrichment can bypass this: the timestamps live
inside the digest-verified artifacts, and the ages are computed from
those artifacts only. Correctness-reference provenance remains
independently required and unchanged (accepted v1 semantics, imported).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

import v2a_authority as v1  # noqa: E402  (accepted attempt-01 contract, imported)
import v2a_discovery_v3 as discovery_v3  # noqa: E402

SCHEMA = "inferswarm.v2a.campaign-authority/3"
DEFAULT_MAX_DISCOVERY_AGE_HOURS = 72
BOUND_FIELDS = ("inventory_path", "inventory_sha256", "bindings_path", "bindings_sha256",
                "reviewed_utc", "inventory_measured_utc", "discovery_hostname",
                "discovery_runtime_executable_sha256", "selector", "pci_bdf",
                "binding_status", "binding_proof_sha256")


class AuthorityError(v1.AuthorityError):
    """The v3 authority's reviewed-discovery binding is stale, unverified, or inconsistent."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_authority(document: Mapping[str, Any], *, reference_root: Path | None = None,
                   discovery_root: Path | None = None,
                   raw_root: Path | None = None,
                   max_discovery_age_hours: int = DEFAULT_MAX_DISCOVERY_AGE_HOURS,
                   frozen_at: str | None = None) -> dict[str, Any]:
    """Validate a v3 authority: accepted v1 + R2 semantics PLUS inventory aging.

    ``discovery_root`` resolves repository-relative discovery artifact
    paths; ``raw_root`` resolves retained raw probe paths (both default
    to the repository root). ``frozen_at`` (ISO-8601) anchors the
    freshness/chronology checks; when omitted the current time is used.
    """
    if not isinstance(document, Mapping) or document.get("schema") != SCHEMA:
        raise AuthorityError(f"authority schema must be {SCHEMA}")
    # Full accepted v1 field/correctness validation first (frozen block,
    # correctness reference bytes + provenance, evidence IDs, nonclaims).
    view = dict(document)
    view["schema"] = v1.SCHEMA
    loaded = v1.load_authority(view, reference_root=reference_root)
    loaded["schema"] = SCHEMA
    frozen = loaded["frozen"]

    binding = document.get("discovery_binding")
    if not isinstance(binding, Mapping):
        raise AuthorityError("discovery_binding block is required (reviewed-discovery contract)")
    missing = [field for field in BOUND_FIELDS if field not in binding]
    if missing:
        raise AuthorityError(f"discovery_binding missing fields: {missing}")

    root = discovery_root if discovery_root is not None else (
        reference_root if reference_root is not None else Path.cwd())
    raws = raw_root if raw_root is not None else root
    inventory_path, bindings_path = root / binding["inventory_path"], root / binding["bindings_path"]
    for label, path, expected in (("inventory", inventory_path, binding["inventory_sha256"]),
                                  ("bindings", bindings_path, binding["bindings_sha256"])):
        if not path.is_file():
            raise AuthorityError(f"reviewed discovery {label} artifact is missing: {path}")
        actual = _sha256(path.read_bytes())
        if actual != expected:
            raise AuthorityError(f"reviewed discovery {label} digest mismatch "
                                 f"(declared {expected}, measured {actual})")
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    bindings = json.loads(bindings_path.read_text(encoding="utf-8"))
    for label, artifact in (("inventory", inventory), ("bindings", bindings)):
        if artifact.get("authorization") != "NON_AUTHORIZING":
            raise AuthorityError(f"discovery {label} artifact must be NON_AUTHORIZING")
        if "correctness" in artifact or "reference" in artifact:
            raise AuthorityError(f"discovery {label} artifact must not contain correctness data")

    # --- Mechanical binding verification (every R2 axis, fail-closed). ---
    if binding["discovery_hostname"] != inventory["hostname"]:
        raise AuthorityError("declared discovery hostname disagrees with the inventory artifact")
    if inventory["hostname"] != frozen["hostname"]:
        raise AuthorityError("discovery hostname disagrees with the frozen authority hostname")
    if binding["discovery_runtime_executable_sha256"] != \
            inventory.get("runtime_executable_sha256"):
        raise AuthorityError("declared discovery runtime hash disagrees with the inventory artifact")
    if inventory.get("runtime_executable_sha256") != frozen["executable_sha256"]:
        raise AuthorityError("discovery runtime executable hash disagrees with the frozen authority")
    if binding["binding_status"] != "BOUND":
        raise AuthorityError(f"declared binding status is {binding['binding_status']}; BOUND required")
    if binding["selector"] != frozen["selector"]:
        raise AuthorityError("discovery binding selector disagrees with the frozen selector")
    if binding["pci_bdf"] != frozen["physical_device_bdf"]:
        raise AuthorityError("discovery binding BDF disagrees with the frozen BDF")
    if binding["reviewed_utc"] != bindings.get("reviewed_utc"):
        raise AuthorityError("declared reviewed_utc disagrees with the bindings artifact")
    if binding["inventory_measured_utc"] != inventory.get("measured_utc"):
        raise AuthorityError(
            "declared inventory_measured_utc disagrees with the digest-verified inventory")

    # --- THE corrected freshness contract: age the PHYSICAL INVENTORY. ---
    # All three timestamps parse fail-closed (malformed/naive/missing
    # rejected) and must satisfy measured <= reviewed <= anchor.
    try:
        measured = discovery_v3.parse_utc_timestamp(
            inventory.get("measured_utc"), label="inventory measured_utc")
        reviewed = discovery_v3.parse_utc_timestamp(
            bindings.get("reviewed_utc"), label="bindings reviewed_utc")
        discovery_v3.require_chronology(
            measured, reviewed, what="inventory measured after review (inverted chronology)")
    except discovery_v3.DiscoveryError as error:
        raise AuthorityError(f"discovery timestamp contract violated: {error}")
    if bindings.get("inventory_measured_utc") != inventory.get("measured_utc"):
        raise AuthorityError(
            "bindings artifact inventory_measured_utc disagrees with the inventory artifact")
    anchor_raw = frozen_at if frozen_at is not None else datetime.now(timezone.utc).isoformat()
    try:
        anchor = discovery_v3.parse_utc_timestamp(anchor_raw, label="authority freeze anchor")
        discovery_v3.require_chronology(
            reviewed, anchor, what="reviewed_utc after the authority freeze anchor (future review)")
    except discovery_v3.DiscoveryError as error:
        raise AuthorityError(f"discovery timestamp contract violated: {error}")
    if anchor - measured > timedelta(hours=max_discovery_age_hours):
        raise AuthorityError(
            "discovery INVENTORY is stale (measured "
            f"{(anchor - measured).total_seconds() / 3600:.2f}h before the anchor; limit "
            f"{max_discovery_age_hours}h) — a fresh review of a stale physical measurement "
            "cannot authorize a campaign")

    # --- Reviewed binding verification incl. retained raw probe bytes. ---
    try:
        verified = discovery_v3.verify_binding_document(
            bindings, inventory, selector=binding["selector"], bdf=binding["pci_bdf"],
            raw_root=raws)
    except discovery_v3.DiscoveryError as error:
        raise AuthorityError(f"reviewed discovery binding rejected: {error}")
    if verified.get("identity_probe") is not None:
        if verified.get("binding_proof_sha256") != binding["binding_proof_sha256"]:
            raise AuthorityError("authority binding_proof_sha256 disagrees with the reviewed artifact")
    elif binding["binding_proof_sha256"]:
        raise AuthorityError("binding_proof_sha256 declared but the reviewed binding carries no proof")
    loaded["discovery_binding"] = dict(binding)
    loaded["verified_binding"] = {k: verified[k] for k in ("selector", "pci_bdf", "binding_status")
                                  if k in verified}
    return loaded


def load_authority_file(path: Path, *, reference_root: Path | None = None,
                        discovery_root: Path | None = None,
                        raw_root: Path | None = None,
                        max_discovery_age_hours: int = DEFAULT_MAX_DISCOVERY_AGE_HOURS,
                        frozen_at: str | None = None) -> dict[str, Any]:
    return load_authority(json.loads(path.read_text(encoding="utf-8")),
                          reference_root=reference_root, discovery_root=discovery_root,
                          raw_root=raw_root,
                          max_discovery_age_hours=max_discovery_age_hours, frozen_at=frozen_at)
