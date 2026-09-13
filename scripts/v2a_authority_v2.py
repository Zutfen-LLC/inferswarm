#!/usr/bin/env python3
"""V2-A R2 campaign authority contract successor (issue #163 correction round 2).

Extends the accepted ``inferswarm.v2a.campaign-authority/1`` loader
(``scripts/v2a_authority.py``, imported unchanged) with the reviewed-
discovery binding the maintainer NO-GO review requires: a V2-A
authority can no longer carry an arbitrary syntactically valid
selector/BDF pair. Schema ``inferswarm.v2a.campaign-authority/2`` adds
one required block::

    "discovery_binding": {
        "inventory_path": ..., "inventory_sha256": ...,
        "bindings_path": ..., "bindings_sha256": ...,
        "reviewed_utc": ...,
        "discovery_hostname": ..., "discovery_runtime_executable_sha256": ...,
        "selector": ..., "pci_bdf": ..., "binding_status": "BOUND",
        "binding_proof_sha256": ...
    }

At load time the loader verifies, mechanically and fail-closed:

* both discovery artifacts exist and their sha256 digests match;
* both artifacts are explicitly NON_AUTHORIZING;
* the selected selector exists in the reviewed bindings;
* its binding status is exactly BOUND (AMBIGUOUS/UNRESOLVED rejected);
* the bound BDF exactly equals the authority's frozen BDF;
* the discovery hostname agrees with the frozen hostname;
* the discovery runtime executable hash agrees with the frozen
  executable_sha256;
* the reviewed timestamp is not stale relative to the authority freeze
  (``max_discovery_age_hours``, default 72h);
* the identity-proof digest re-verifies against the retained probe
  evidence (tamper control).

A caller cannot enrich an ambiguous discovery row into a BOUND
authority merely by supplying a BDF: the BOUND status and its proof
must already exist inside the digest-verified reviewed artifact.
Correctness-reference provenance remains independently required and
unchanged (v2a_authority semantics, imported not forked).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

import v2a_authority as v1  # noqa: E402  (accepted attempt-01 contract, imported)
import v2a_discovery_v2 as discovery_v2  # noqa: E402

SCHEMA = "inferswarm.v2a.campaign-authority/2"
DEFAULT_MAX_DISCOVERY_AGE_HOURS = 72
BOUND_FIELDS = ("inventory_path", "inventory_sha256", "bindings_path", "bindings_sha256",
                "reviewed_utc", "discovery_hostname", "discovery_runtime_executable_sha256",
                "selector", "pci_bdf", "binding_status", "binding_proof_sha256")


class AuthorityError(v1.AuthorityError):
    """The v2 authority's reviewed-discovery binding is missing or unverified."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_authority(document: Mapping[str, Any], *, reference_root: Path | None = None,
                   discovery_root: Path | None = None,
                   max_discovery_age_hours: int = DEFAULT_MAX_DISCOVERY_AGE_HOURS,
                   frozen_at: str | None = None) -> dict[str, Any]:
    """Validate a v2 authority: accepted v1 semantics PLUS the binding block.

    ``discovery_root`` resolves repository-relative discovery artifact
    paths (the repository root). ``frozen_at`` (ISO-8601) anchors the
    staleness check; when omitted the current time is used.
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

    # Mechanical binding verification (fail-closed on every axis).
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
    try:
        reviewed = datetime.fromisoformat(bindings["reviewed_utc"])
    except (KeyError, ValueError):
        raise AuthorityError("bindings artifact reviewed_utc is missing or malformed")
    anchor = frozen_at if frozen_at is not None else datetime.now(timezone.utc).isoformat()
    try:
        anchor_dt = datetime.fromisoformat(anchor)
    except ValueError:
        raise AuthorityError("frozen_at anchor is malformed")
    if anchor_dt - reviewed > timedelta(hours=max_discovery_age_hours):
        raise AuthorityError(
            f"reviewed discovery is stale (> {max_discovery_age_hours}h before authority freeze)")
    try:
        verified = discovery_v2.verify_binding_document(
            bindings, inventory, selector=binding["selector"], bdf=binding["pci_bdf"])
    except discovery_v2.DiscoveryError as error:
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
                        max_discovery_age_hours: int = DEFAULT_MAX_DISCOVERY_AGE_HOURS,
                        frozen_at: str | None = None) -> dict[str, Any]:
    return load_authority(json.loads(path.read_text(encoding="utf-8")),
                          reference_root=reference_root, discovery_root=discovery_root,
                          max_discovery_age_hours=max_discovery_age_hours, frozen_at=frozen_at)
