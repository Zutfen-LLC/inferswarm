#!/usr/bin/env python3
"""Issue #110 v5 custody handoff tooling (CPU/static, non-decrypting).

Deterministically constructs the effective completed holdout custody record
from (a) the accepted #109 baseline custody record (hash-checked, never
modified) and (b) the additive #110 custody completion record that documents
the verified second independent custodian. The effective record reuses the
frozen inferswarm.issue109.v5-holdout-custody-record/1 schema so the accepted
threshold deriver and unseal preflight can bind the completed custody state
without touching any accepted #109 byte.

This module never reads private key or secret seed files; it validates
metadata identities only. No CMS decrypt operation is present or reachable.
Scope prohibition: no SSH to GPU nodes, no torch/CUDA/triton, no calibration,
no stress or candidate execution, no holdout decrypt.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from issue74_methodology import MethodologyError, canonical_json_bytes, sha256_bytes, sha256_file
from commit_issue109_holdout import custody_is_satisfied

ROOT = Path(__file__).resolve().parents[1]
V5 = ROOT / "docs/qualification/gemma4-12b-it-v5"
CAMPAIGN = ROOT / "docs/qualification/gemma4-12b-it-v5-campaign-110/preflight"

ACCEPTED_ISSUE109_MERGE = "bc6f0ec657d025702d5928771bf8f51aa563a8be"
ACCEPTED_BASELINE_CUSTODY_RECORD_SHA256 = "6adaa4e5743cdee65f659806d81039dca499c7997cf0240ce92d48cfc2a23b46"
ACCEPTED_HOLDOUT_COMMITMENT_SHA256 = "b0dcff2a241b20cbd24f1b54f30e77a33512d8ceb12f79afc6c1761b2c994fd2"
ACCEPTED_THRESHOLDS_TOOL_SHA256 = "41904b3297e06656bad8b0776f75ca42f7a05635b48fe3afe0b7330071bb0e25"

CIPHERTEXT_SHA256 = "93f75078875af163334fdfc7b74b3347f86b6948416b7dd8e603bd52863221b9"
CERTIFICATE_SHA256 = "072a211370b7ddbd352b8d8f9fccb60bc01b6835567b34d08cbbbac147e284eb"
PUBLIC_KEY_DER_SHA256 = "62ded0e04b2e800c85bae9b5c499faa29f8fb21956c3f40dee23efdcf5d5f9e6"
PRIVATE_KEY_SHA256 = "6e472dc13c550bbb59542179a04eab5988a60bb4a8746210049215c23a4a87e8"
NORMALIZED_SEED_SHA256 = "c4c3d3821f6830933ff748f999a8b47bb113b820c8f31ad172c99f5d53eb1854"

CUSTODY_SCHEMA = "inferswarm.issue109.v5-holdout-custody-record/1"
COMPLETION_SCHEMA = "inferswarm.issue110.v5-custody-completion-record/1"
TOOLING_VERSION = "inferswarm.issue110.v5-custody-handoff-tooling/1"

# Network-backed or otherwise non-local storage boundaries are rejectable.
_NON_LOCAL_KINDS = {"nfs", "cifs", "smb", "sshfs", "network", "nexus", "remote", "cloud"}
# Placeholder-ish host tokens that must never appear as custodian hosts.
_PLACEHOLDER_HOSTS = {"orchestrator", "localhost", "host", "host-a", "host-b", "example.com", "placeholder"}


def _load_json(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise MethodologyError(f"110 cannot load {path.name}: {exc}") from exc
    if not isinstance(document, dict):
        raise MethodologyError(f"110 {path.name} must be a JSON object")
    return document


def load_accepted_baseline(path: Path | None = None) -> dict[str, Any]:
    """Load and hash-check the accepted #109 baseline custody record."""
    path = path or (V5 / "manifests/holdout-custody-record.json")
    if sha256_file(path) != ACCEPTED_BASELINE_CUSTODY_RECORD_SHA256:
        raise MethodologyError("110 accepted baseline custody record hash mismatch")
    document = _load_json(path)
    if document.get("schema") != CUSTODY_SCHEMA:
        raise MethodologyError("110 baseline custody record schema mismatch")
    return document


def validate_completion_record(record: dict[str, Any]) -> None:
    """Fail-closed validation of the additive #110 completion record metadata."""
    if record.get("schema") != COMPLETION_SCHEMA:
        raise MethodologyError("110 completion record schema mismatch")
    if record.get("record_type") != "PRE_EXECUTION_CUSTODY_HANDOFF_TOOLING_REPAIR":
        raise MethodologyError("110 completion record type mismatch")
    if record.get("accepted_issue109_merge") != ACCEPTED_ISSUE109_MERGE:
        raise MethodologyError("110 completion record merge mismatch")
    if record.get("accepted_baseline_custody_record_sha256") != ACCEPTED_BASELINE_CUSTODY_RECORD_SHA256:
        raise MethodologyError("110 completion record baseline custody hash mismatch")
    if record.get("accepted_holdout_commitment_sha256") != ACCEPTED_HOLDOUT_COMMITMENT_SHA256:
        raise MethodologyError("110 completion record holdout commitment mismatch")
    identities = record.get("accepted_identities")
    if not isinstance(identities, dict) or identities.get("holdout_ciphertext_sha256") != CIPHERTEXT_SHA256 \
            or identities.get("recipient_certificate_sha256") != CERTIFICATE_SHA256 \
            or identities.get("recipient_public_key_der_sha256") != PUBLIC_KEY_DER_SHA256:
        raise MethodologyError("110 completion record accepted identity mismatch")
    custodians = record.get("custodians")
    if not isinstance(custodians, list) or len(custodians) != 2:
        raise MethodologyError("110 completion record must carry exactly two custodians")
    boundaries: set[tuple[str, str]] = set()
    hosts: set[str] = set()
    locations: set[str] = set()
    for custodian in custodians:
        if not isinstance(custodian, dict):
            raise MethodologyError("110 custodian entry must be an object")
        host, location = custodian.get("host"), custodian.get("location")
        if not isinstance(host, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*[a-z0-9]|[a-z0-9]", host) or host in _PLACEHOLDER_HOSTS:
            raise MethodologyError("110 custodian host must be a canonical hostname, not an alias or placeholder")
        if not isinstance(location, str) or not location.startswith("/") or ".." in location:
            raise MethodologyError("110 custodian location must be an absolute path")
        if host in hosts:
            raise MethodologyError("110 custodian host duplicated")
        if location in locations:
            raise MethodologyError("110 custodian storage location duplicated")
        if (host, location) in boundaries:
            raise MethodologyError("110 custodian storage boundary duplicated")
        hosts.add(host)
        locations.add(location)
        boundaries.add((host, location))
        storage = custodian.get("backing_storage")
        if not isinstance(storage, dict) or storage.get("kind") != "local":
            raise MethodologyError("110 custodian backing storage must be local")
        if str(storage.get("filesystem", "")).lower() in _NON_LOCAL_KINDS or str(storage.get("device", "")).lower() in _NON_LOCAL_KINDS:
            raise MethodologyError("110 custodian storage is network-backed")
        if not re.match(r"^/dev/[a-zA-Z0-9]+$", str(storage.get("device", ""))):
            raise MethodologyError("110 custodian backing device must be a local block device")
        if custodian.get("private_key_sha256") != PRIVATE_KEY_SHA256:
            raise MethodologyError("110 custodian private key identity mismatch")
        if custodian.get("normalized_secret_seed_sha256") != NORMALIZED_SEED_SHA256:
            raise MethodologyError("110 custodian normalized seed identity mismatch")
        if custodian.get("public_key_der_sha256") != PUBLIC_KEY_DER_SHA256:
            raise MethodologyError("110 custodian public key DER identity mismatch")
        if custodian.get("ownership") != "zutfen" or custodian.get("directory_mode") != "0700" or custodian.get("file_mode") != "0600":
            raise MethodologyError("110 custodian permission metadata mismatch")
        if not custodian.get("verified_date"):
            raise MethodologyError("110 custodian verified_date missing")
    if record.get("decrypt_performed") is not False:
        raise MethodologyError("110 completion record must assert no decrypt")
    if record.get("private_material_in_repository") is not False:
        raise MethodologyError("110 completion record must assert no private material in repository")
    extra = record.get("additional_observed_copy")
    if not isinstance(extra, dict) or extra.get("relied_upon_for_proof") is not False:
        raise MethodologyError("110 additional observed copy must not be relied upon for the proof")
    if extra.get("host") in hosts:
        raise MethodologyError("110 additional copy host must not duplicate a custodian host")


def build_effective_custody_record(completion: dict[str, Any]) -> dict[str, Any]:
    """Deterministically construct the effective custody record.

    Reuses the frozen inferswarm.issue109.v5-holdout-custody-record/1 schema
    with exactly the two correctness-bearing custodians, holdout_state
    SEALED_NOT_CONSUMED, and unseal_authorized False.
    """
    validate_completion_record(completion)
    custodians = [
        {
            "custodian_id": row["custodian_id"],
            "files": "recipient-key.pem, secret-seed.txt",
            "host": row["host"],
            "location": row["location"],
            "ownership": row["ownership"],
            "permissions": "0700 directory; 0600 files",
            "private_key_sha256": row["private_key_sha256"],
            "public_key_match": True,
            "verified_date": row["verified_date"],
        }
        for row in completion["custodians"]
    ]
    return {
        "schema": CUSTODY_SCHEMA,
        "contract_id": completion["contract_id"],
        "custodians": custodians,
        "custody_history": (
            "Accepted #109 baseline custody record (hash "
            f"{ACCEPTED_BASELINE_CUSTODY_RECORD_SHA256}) intentionally carried one "
            "custodian and SEALED_CUSTODY_INCOMPLETE. Issue #110 verified a second "
            "independent custodian and records the completed custody state in this "
            "effective record; the historical record is retained unmodified."
        ),
        "fail_closed_rule": (
            "if fewer than two verified independent custodians exist, holdout_state "
            "must be SEALED_CUSTODY_INCOMPLETE and unseal_authorized must be False; "
            "never regenerate a key for the existing ciphertext"
        ),
        "holdout_ciphertext_sha256": CIPHERTEXT_SHA256,
        "holdout_state": "SEALED_NOT_CONSUMED",
        "private_material_in_repository": "PROHIBITED",
        "recipient_certificate_sha256": CERTIFICATE_SHA256,
        "recipient_public_key_der_sha256": PUBLIC_KEY_DER_SHA256,
        "unseal_authorized": False,
        "verification_method": (
            "non-decrypting identity verification of two independent custodian "
            "copies (file SHA-256, normalized seed SHA-256, public-key DER SHA-256); "
            "see docs/qualification/gemma4-12b-it-v5-campaign-110/preflight/"
            "holdout-custody-completion.json"
        ),
    }


def effective_custody_record_sha256(record: dict[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes(record))


def write_effective_record(path: Path | None = None) -> str:
    """Validate inputs, write canonical-JSON bytes of the effective record, return its SHA-256."""
    baseline = load_accepted_baseline()
    completion = _load_json(CAMPAIGN / "holdout-custody-completion.json")
    effective = build_effective_custody_record(completion)
    if baseline.get("contract_id") != effective["contract_id"]:
        raise MethodologyError("110 contract identity drift between baseline and completion")
    if not custody_is_satisfied(effective):
        raise MethodologyError("110 effective custody record does not satisfy frozen custody semantics")
    out = path or (CAMPAIGN / "effective-holdout-custody-record.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(canonical_json_bytes(effective))
    return sha256_file(out)


def main() -> None:
    sha = write_effective_record()
    print(f"effective custody record sha256: {sha}")
    print(f"written: {CAMPAIGN / 'effective-holdout-custody-record.json'}")


if __name__ == "__main__":
    main()
