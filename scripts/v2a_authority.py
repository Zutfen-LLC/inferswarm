#!/usr/bin/env python3
"""V2-A machine-readable campaign authority contract and loader (issue #163).

A campaign authority is DATA, fully parameterized: subject/resource
identity, runtime/state, correctness, and evidence identifiers. The
same harness bytes must be able to drive any subject given a different
authority document; conversely the loader rejects any authority that is
incomplete, internally inconsistent, or self-authorizing.

Critical authority rule (mechanical, not prose): the correctness block
must carry prospectively authorized reference BYTES/HASH plus a
provenance that points at ACCEPTED PRE-EXISTING evidence — never at
output the harness itself just observed. A reference whose provenance
names discovery/qualification/canonical output of THIS campaign, or a
missing/placeholder provenance, is rejected before any campaign stage
runs. There is no recalibration field to loosen: the comparator policy
must equal the accepted byte-exact policy string.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "inferswarm.v2a.campaign-authority/1"
ACCEPTED_COMPARATOR_POLICY = "v0c-byte-exact-visible-output-v2"
NO_RECALIBRATION = "reference bytes are prospectively frozen; comparator policy may not be loosened or replaced after observation"
_FORBIDDEN_PROVENANCE = re.compile(
    r"(this[_ -]?(campaign|harness)|just[_ -]?observed|discovery[_ -]?output|"
    r"qualification[_ -]?output|canonical[_ -]?(output|stdout)|self[_ -]?authorized)", re.I)
_SELECTOR = re.compile(r"^Vulkan[0-9]+$")
_BDF = re.compile(r"^[0-9a-f]{2}:[0-9a-f]{2}\.[0-9]$")

# Required frozen runtime/state fields (accepted V1-A/V1-C semantics).
FROZEN_FIELDS = (
    "hostname", "node_id", "compute_unit_id", "memory_resource_id", "memory_bytes",
    "physical_device_bdf", "selector", "execution_unit_id", "execution_contract_id",
    "implementation_id", "logical_state_id", "required_representation", "required_features",
    "required_memory_bytes", "required_headroom_bytes", "required_integrity_status",
    "correctness_policy", "objective", "prompt", "runtime_source", "runtime_source_commit",
    "executable", "executable_sha256", "model", "model_sha256", "model_bytes",
    "qualification_evidence_id", "canonical_execution_evidence_id",
)
# Reference bytes may be carried inline (sha-pinned) or by repository path.
_REFERENCE_PATH_KEYS = ("reference_output",)


class AuthorityError(RuntimeError):
    """The campaign authority is incomplete, inconsistent, or self-authorizing."""


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def load_authority(document: Mapping[str, Any], *, reference_root: Path | None = None) -> dict[str, Any]:
    """Validate and return a complete, prospectively authorized authority.

    ``reference_root`` resolves repository-relative reference paths
    (the repository root for accepted predecessor references).
    """
    if not isinstance(document, Mapping) or document.get("schema") != SCHEMA:
        raise AuthorityError(f"authority schema must be {SCHEMA}")
    frozen = document.get("frozen")
    if not isinstance(frozen, Mapping):
        raise AuthorityError("frozen subject/runtime/state block is required")
    missing = [field for field in FROZEN_FIELDS if field not in frozen]
    if missing:
        raise AuthorityError(f"authority is missing frozen fields: {missing}")
    for field in ("hostname", "node_id", "compute_unit_id", "memory_resource_id",
                  "execution_unit_id", "execution_contract_id", "implementation_id",
                  "logical_state_id", "required_representation", "correctness_policy",
                  "objective", "prompt", "runtime_source", "runtime_source_commit",
                  "executable", "model", "qualification_evidence_id",
                  "canonical_execution_evidence_id"):
        if not _text(frozen[field]):
            raise AuthorityError(f"frozen field {field} must be a non-empty string")
    for field in ("memory_bytes", "required_memory_bytes", "required_headroom_bytes",
                  "model_bytes"):
        value = frozen[field]
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise AuthorityError(f"frozen field {field} must be a positive integer")
    for field, sha in (("executable_sha256", frozen["executable_sha256"]),
                       ("model_sha256", frozen["model_sha256"])):
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise AuthorityError(f"frozen field {field} must be a sha256 hex digest")
    if not _SELECTOR.match(frozen["selector"]):
        raise AuthorityError("frozen selector must match the runtime Vulkan<N> grammar")
    if not _BDF.match(frozen["physical_device_bdf"]):
        raise AuthorityError("frozen physical_device_bdf must be a PCI BDF")
    if not isinstance(frozen["required_features"], list) or not frozen["required_features"]:
        raise AuthorityError("frozen required_features must be a non-empty list")
    if not isinstance(frozen.get("runtime_identity"), Mapping) or not frozen["runtime_identity"]:
        raise AuthorityError("frozen runtime_identity mapping is required")
    # Correctness block: prospectively authorized reference + provenance.
    root = reference_root if reference_root is not None else Path.cwd()
    correctness = document.get("correctness")
    if not isinstance(correctness, Mapping):
        raise AuthorityError("correctness block is required")
    if correctness.get("comparator_policy") != ACCEPTED_COMPARATOR_POLICY:
        raise AuthorityError("comparator policy must be the accepted byte-exact policy")
    if correctness.get("no_recalibration") != NO_RECALIBRATION:
        raise AuthorityError("explicit no-recalibration rule is required verbatim")
    provenance = correctness.get("reference_provenance")
    if not _text(provenance) or _FORBIDDEN_PROVENANCE.search(provenance):
        raise AuthorityError("reference provenance must name accepted pre-existing evidence")
    reference_sha = correctness.get("reference_sha256")
    reference_path = correctness.get("reference_path")
    if not isinstance(reference_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", reference_sha):
        raise AuthorityError("reference_sha256 is required (prospectively authorized bytes)")
    if not isinstance(reference_path, str) or not _text(reference_path):
        raise AuthorityError("reference_path is required")
    reference_file = root / reference_path
    if not reference_file.is_file():
        raise AuthorityError(f"reference bytes not found: {reference_path}")
    actual = hashlib.sha256(reference_file.read_bytes()).hexdigest()
    if actual != reference_sha:
        raise AuthorityError("reference bytes do not match the authorized reference hash")
    # Evidence identity block.
    evidence = document.get("evidence")
    if not isinstance(evidence, Mapping):
        raise AuthorityError("evidence identity block is required")
    for field in ("evidence_namespace", "plan_evidence_id", "capability_evidence_id"):
        if not _text(evidence.get(field)):
            raise AuthorityError(f"evidence field {field} is required")
    if not isinstance(document.get("nonclaims"), list) or not document["nonclaims"]:
        raise AuthorityError("explicit nonclaims are required")
    return dict(document)


def load_authority_file(path: Path, *, reference_root: Path | None = None) -> dict[str, Any]:
    return load_authority(json.loads(path.read_text(encoding="utf-8")), reference_root=reference_root)


def reference_bytes(authority: Mapping[str, Any], *, reference_root: Path) -> bytes:
    """Return the prospectively authorized reference bytes."""
    return (reference_root / authority["correctness"]["reference_path"]).read_bytes()
