#!/usr/bin/env python3
"""Issue #79: v2 holdout-unseal preflight verifier (CPU-only, fail-closed).

Refuses permission to proceed to the future v2 unseal step unless every
precondition holds. This module NEVER decrypts anything and never invokes
OpenSSL: it is a pure preflight/verifier. The future unseal itself remains
the maintainer's act against the retained v1 ciphertext.

The v1 unseal script (scripts/seal_issue74_holdout.py) is retained
byte-identical historical evidence and is NOT wrapped or modified here.

Fail-closed contract (reviewed head a3bd03c hardening):

- the selected-eight artifact is bound to an INDEPENDENTLY supplied expected
  committed SHA (``expected_stress_selection_sha256``, mandatory) — never
  merely to a field inside the threshold manifest;
- the threshold manifest is validated against the exact committed v2
  threshold JSON Schema (Draft 2020-12) before any further authorization
  result;
- custody must be explicitly proven ``FOUND_VERIFIED`` via the committed
  non-secret custody record (absence of proof is not proof of custody);
- a supplied private-key path must ALWAYS be proven external to the
  repository root, which is derived deterministically from this file's
  location — never an optional operator responsibility.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, NoReturn, Sequence

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

from issue79_v2_thresholds import (
    CALIBRATION_CORPUS_SHA256,
    HOLDOUT_CIPHERTEXT_SHA256,
    V2_COMMITMENT_SHA256,
    V2_POOL_SHA256,
    V2_TOOLING_SCHEMA_FIELD,
    MethodologyError,
    canonical_json_bytes,
    reject_holdout_material,
    sha256_bytes,
    sha256_file,
)

V2_THRESHOLD_SCHEMA = "inferswarm.issue79.v2-threshold-manifest/1"
V2_THRESHOLD_SCHEMA_ID = (
    "https://inferswarm.dev/schema/issue79/v2-threshold-manifest-1.json"
)
EXPECTED_RECIPIENT_CERTIFICATE_SHA256 = (
    "9edb50e82a070bc666b43ac7d0fac158caa906a34510efda3241b1d160be2b46"
)
# Frozen recipient public-key DER SHA (sealed-holdout commitment provenance,
# re-verified non-decrypting during #74 custody recovery).
EXPECTED_RECIPIENT_PUBLIC_KEY_DER_SHA256 = (
    "f0a89feaa68ddd7c833e85d20d2d8eeac74208a2eb7da4354e97b35fd9ef8693"
)
HOLDOUT_CUSTODY_BLOCKED = "HOLDOUT_CUSTODY_BLOCKED"
CUSTODY_VERDICT_OK = "FOUND_VERIFIED"
CUSTODY_RECORD_SCHEMA = "inferswarm.issue74.holdout-custody-record/1"
CUSTODY_HOLDOUT_STATE_OK = "SEALED_NOT_CONSUMED; never unsealed during custody recovery"
CUSTODY_MIN_CUSTODIANS = 2

# The repository root is derived deterministically from this file's location;
# it is never an optional operator responsibility.
REPO_ROOT = Path(__file__).resolve().parents[1]
# Canonical committed v2 threshold schema — deterministically resolved, not
# operator-supplied.
THRESHOLD_SCHEMA_PATH = (
    REPO_ROOT / "docs/qualification/gemma4-12b-it-v2/schemas/threshold-manifest.schema.json"
)

SELECTED_SHA_MISMATCH = "SELECTED_STRESS_SELECTION_SHA_MISMATCH"
THRESHOLD_SCHEMA_INVALID = "THRESHOLD_MANIFEST_SCHEMA_INVALID"
CUSTODY_NOT_VERIFIED = "HOLDOUT_CUSTODY_NOT_VERIFIED"
PRIVATE_KEY_NOT_EXTERNAL = "PRIVATE_KEY_PATH_NOT_EXTERNAL_TO_REPO"


class UnsealPreflightError(ValueError):
    """A v2 unseal precondition failed; permission to proceed is refused."""


def _fail(message: str) -> NoReturn:
    raise UnsealPreflightError(message)


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def load_threshold_schema() -> dict[str, Any]:
    """Load the exact committed v2 threshold schema from its canonical
    repository path. Fails closed if it is missing, unparseable, or not the
    expected v2 schema identity."""
    try:
        schema = json.loads(THRESHOLD_SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _fail(f"{THRESHOLD_SCHEMA_INVALID}: cannot load committed v2 threshold schema: {exc}")
    if schema.get("$id") != V2_THRESHOLD_SCHEMA_ID:
        _fail(f"{THRESHOLD_SCHEMA_INVALID}: schema $id is not the exact v2 threshold schema")
    if schema.get("properties", {}).get("schema", {}).get("const") != V2_THRESHOLD_SCHEMA:
        _fail(f"{THRESHOLD_SCHEMA_INVALID}: schema does not pin the v2 threshold schema id")
    return schema


def _validate_threshold_manifest_schema(
    threshold_manifest: dict[str, Any], threshold_schema: dict[str, Any]
) -> None:
    """Real Draft 2020-12 validation of the complete threshold manifest
    against the exact committed v2 schema, before any further authorization
    result. Fail closed on any structural violation."""
    if threshold_manifest.get("schema") != V2_THRESHOLD_SCHEMA:
        _fail(f"{THRESHOLD_SCHEMA_INVALID}: threshold manifest is not the v2 threshold schema")
    try:
        Draft202012Validator(threshold_schema).validate(threshold_manifest)
    except JsonSchemaValidationError as exc:
        _fail(
            f"{THRESHOLD_SCHEMA_INVALID}: threshold manifest fails the committed "
            f"v2 JSON Schema at {exc.json_path}: {exc.message}"
        )


def _validate_custody_record(
    custody_record: Any, custody_state: str | None
) -> None:
    """Custody must be explicitly proven FOUND_VERIFIED against the accepted
    non-secret custody record and the frozen holdout/certificate provenance.
    Absence of proof is not proof of custody: fail closed."""
    if custody_state == HOLDOUT_CUSTODY_BLOCKED:
        _fail(f"{CUSTODY_NOT_VERIFIED}: holdout custody is blocked; unseal is refused")
    if not isinstance(custody_record, dict) or not custody_record:
        _fail(f"{CUSTODY_NOT_VERIFIED}: no explicit custody record was supplied")
    record: dict[str, Any] = custody_record
    if record.get("schema") != CUSTODY_RECORD_SCHEMA:
        _fail(f"{CUSTODY_NOT_VERIFIED}: custody record is not the accepted custody-record schema")
    verdict = record.get("custody_verdict")
    if verdict != CUSTODY_VERDICT_OK:
        if verdict == HOLDOUT_CUSTODY_BLOCKED:
            _fail(f"{CUSTODY_NOT_VERIFIED}: custody verdict is HOLDOUT_CUSTODY_BLOCKED")
        _fail(f"{CUSTODY_NOT_VERIFIED}: custody verdict is not explicitly FOUND_VERIFIED (got {verdict!r})")
    if record.get("holdout_state") != CUSTODY_HOLDOUT_STATE_OK:
        _fail(f"{CUSTODY_NOT_VERIFIED}: custody record holdout state mismatch")
    if record.get("holdout_ciphertext_sha256") != HOLDOUT_CIPHERTEXT_SHA256:
        _fail(f"{CUSTODY_NOT_VERIFIED}: custody record ciphertext SHA does not match the frozen holdout")
    if record.get("recipient_certificate_sha256") != EXPECTED_RECIPIENT_CERTIFICATE_SHA256:
        _fail(f"{CUSTODY_NOT_VERIFIED}: custody record certificate SHA does not match the committed certificate")
    if record.get("recipient_public_key_der_sha256") != EXPECTED_RECIPIENT_PUBLIC_KEY_DER_SHA256:
        _fail(f"{CUSTODY_NOT_VERIFIED}: custody record public-key DER SHA mismatch")
    custodians = record.get("custodians")
    if not isinstance(custodians, list) or len(custodians) < CUSTODY_MIN_CUSTODIANS:
        _fail(f"{CUSTODY_NOT_VERIFIED}: at least {CUSTODY_MIN_CUSTODIANS} custodians are required")
    for custodian in custodians:
        if not isinstance(custodian, dict) or custodian.get("public_key_match") is not True:
            _fail(f"{CUSTODY_NOT_VERIFIED}: every custodian must have public_key_match == true")


def _validate_private_key_externality(
    private_key_path: str, repo_root: Path | None
) -> None:
    """A supplied private-key path must always be proven external to the
    repository. The repository root defaults to the deterministic REPO_ROOT
    derived from this file — externality is never unproven because an
    operator omitted it."""
    key = Path(private_key_path)
    root = Path(repo_root).resolve() if repo_root is not None else REPO_ROOT
    try:
        key.resolve().relative_to(root)
    except ValueError:
        pass  # outside the repository: the only acceptable case
    else:
        _fail(
            f"{PRIVATE_KEY_NOT_EXTERNAL}: private key path must be external to "
            f"the Git repository scope (resolved inside {root})"
        )
    if key.name in {"recipient-certificate.pem"} or str(key).endswith(".cms"):
        _fail(f"{PRIVATE_KEY_NOT_EXTERNAL}: private key path points at committed repository material")


def validate_unseal_preconditions(
    *,
    threshold_manifest: dict[str, Any],
    threshold_manifest_sha256: str,
    expected_committed_threshold_sha256: str,
    expected_stress_selection_sha256: str,
    holdout_ciphertext_sha256: str,
    recipient_certificate_sha256: str,
    custody_record: dict[str, Any] | None = None,
    custody_state: str | None = None,
    threshold_schema: dict[str, Any] | None = None,
    private_key_path: str | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Verify every v2 unseal precondition; raise UnsealPreflightError on any
    failure. Returns a preflight record when all checks pass. Does NOT
    decrypt and does NOT invoke OpenSSL.

    ``expected_stress_selection_sha256`` is MANDATORY: the selected-eight
    artifact is bound to this independently supplied expected committed SHA,
    never merely to the manifest's own field. ``private_key_path`` may be
    omitted only in library/test mode; the operator CLI requires it."""
    # 1. threshold manifest validates against the exact committed v2
    #    threshold JSON Schema (real Draft 2020-12 validation) BEFORE any
    #    further authorization result.
    schema = threshold_schema if threshold_schema is not None else load_threshold_schema()
    _validate_threshold_manifest_schema(threshold_manifest, schema)
    # 2. threshold file SHA equals the externally supplied committed SHA
    if not _is_sha256(threshold_manifest_sha256) or not _is_sha256(expected_committed_threshold_sha256):
        _fail("threshold SHA-256 values must be 64-char hex digests")
    if threshold_manifest_sha256 != expected_committed_threshold_sha256:
        _fail("threshold file SHA does not equal the externally committed SHA")
    # 3. threshold manifest says SEALED_NOT_CONSUMED
    if threshold_manifest.get("holdout_state") != "SEALED_NOT_CONSUMED":
        _fail("threshold manifest holdout state is not SEALED_NOT_CONSUMED")
    # 4. bound to the accepted v2 tooling/methodology version
    if threshold_manifest.get("tooling_or_methodology_version") != V2_TOOLING_SCHEMA_FIELD:
        _fail("threshold manifest is not bound to the accepted v2 tooling version")
    # 5-8. exact artifact provenance
    if threshold_manifest.get("calibration_corpus_sha256") != CALIBRATION_CORPUS_SHA256:
        _fail("threshold manifest calibration corpus SHA mismatch")
    if threshold_manifest.get("stress_pool_sha256") != V2_POOL_SHA256:
        _fail("threshold manifest v2 stress pool SHA mismatch")
    if threshold_manifest.get("stress_selection_commitment_sha256") != V2_COMMITMENT_SHA256:
        _fail("threshold manifest v2 selection commitment SHA mismatch")
    # 9. selected-eight SHA is bound to the EXTERNALLY supplied expected
    #    committed SHA (never merely self-consistent inside the manifest).
    if not _is_sha256(expected_stress_selection_sha256):
        _fail(
            f"{SELECTED_SHA_MISMATCH}: expected selected-eight SHA must be "
            "supplied as a 64-char hex digest"
        )
    if not _is_sha256(threshold_manifest.get("stress_selection_sha256")):
        _fail(f"{SELECTED_SHA_MISMATCH}: threshold manifest selected-eight SHA is missing or invalid")
    if threshold_manifest.get("stress_selection_sha256") != expected_stress_selection_sha256:
        _fail(
            f"{SELECTED_SHA_MISMATCH}: threshold manifest selected-eight SHA is "
            "not bound to the externally expected committed selection"
        )
    # 10. encrypted holdout file SHA
    if holdout_ciphertext_sha256 != HOLDOUT_CIPHERTEXT_SHA256:
        _fail("holdout ciphertext SHA mismatch")
    # 11. recipient certificate SHA matches the committed certificate
    if recipient_certificate_sha256 != EXPECTED_RECIPIENT_CERTIFICATE_SHA256:
        _fail("recipient certificate SHA mismatch")
    # 12. custody must be explicitly proven FOUND_VERIFIED (fail closed).
    _validate_custody_record(custody_record, custody_state)
    # 13. private key path (if supplied for the future step) must ALWAYS be
    #     proven external to the repository scope.
    if private_key_path is not None:
        _validate_private_key_externality(private_key_path, repo_root)

    return {
        "schema": "inferswarm.issue79.v2-unseal-preflight/1",
        "verdict": "UNSEAL_PRECONDITIONS_PASS_DECRYPT_NOT_PERFORMED",
        "threshold_schema": V2_THRESHOLD_SCHEMA,
        "threshold_manifest_sha256": threshold_manifest_sha256,
        "stress_selection_sha256": expected_stress_selection_sha256,
        "holdout_ciphertext_sha256": holdout_ciphertext_sha256,
        "recipient_certificate_sha256": recipient_certificate_sha256,
        "custody_state": CUSTODY_VERDICT_OK,
        "decrypt_performed": False,
        "openssl_invoked": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Operator CLI: the real fail-closed pre-decrypt barrier. Every piece of
    external material is REQUIRED. Never decrypts, never invokes OpenSSL."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threshold-manifest", required=True, type=Path)
    parser.add_argument("--expected-threshold-sha256", required=True)
    parser.add_argument(
        "--expected-stress-selection-sha256", required=True,
        help="externally committed selected-eight SHA; the manifest alone is never sufficient",
    )
    parser.add_argument("--holdout-ciphertext", required=True, type=Path)
    parser.add_argument("--recipient-certificate", required=True, type=Path)
    parser.add_argument("--custody-record", required=True, type=Path)
    parser.add_argument(
        "--private-key-path", required=True,
        help="future unseal private key path; must be external to the repository",
    )
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    try:
        record = validate_unseal_preconditions(
            threshold_manifest=json.loads(args.threshold_manifest.read_text(encoding="utf-8")),
            threshold_manifest_sha256=sha256_file(args.threshold_manifest),
            expected_committed_threshold_sha256=args.expected_threshold_sha256,
            expected_stress_selection_sha256=args.expected_stress_selection_sha256,
            holdout_ciphertext_sha256=sha256_file(args.holdout_ciphertext),
            recipient_certificate_sha256=sha256_file(args.recipient_certificate),
            custody_record=json.loads(args.custody_record.read_text(encoding="utf-8")),
            private_key_path=args.private_key_path,
        )
    except UnsealPreflightError as exc:
        raise SystemExit(f"UNSEAL_PRECONDITIONS_FAIL: {exc}") from exc
    args.out.write_bytes(canonical_json_bytes(record))
    print(record["verdict"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
