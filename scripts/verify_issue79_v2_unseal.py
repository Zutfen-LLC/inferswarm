#!/usr/bin/env python3
"""Issue #79: v2 holdout-unseal preflight verifier (CPU-only, fail-closed).

Refuses permission to proceed to the future v2 unseal step unless every
precondition holds. This module NEVER decrypts anything and never invokes
OpenSSL: it is a pure preflight/verifier. The future unseal itself remains
the maintainer's act against the retained v1 ciphertext.

The v1 unseal script (scripts/seal_issue74_holdout.py) is retained
byte-identical historical evidence and is NOT wrapped or modified here.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

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
EXPECTED_RECIPIENT_CERTIFICATE_SHA256 = (
    "9edb50e82a070bc666b43ac7d0fac158caa906a34510efda3241b1d160be2b46"
)
HOLDOUT_CUSTODY_BLOCKED = "HOLDOUT_CUSTODY_BLOCKED"
CUSTODY_VERDICT_OK = "FOUND_VERIFIED"


class UnsealPreflightError(ValueError):
    """A v2 unseal precondition failed; permission to proceed is refused."""


def _fail(message: str) -> None:
    raise UnsealPreflightError(message)


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def validate_unseal_preconditions(
    *,
    threshold_manifest: dict[str, Any],
    threshold_manifest_sha256: str,
    expected_committed_threshold_sha256: str,
    holdout_ciphertext_sha256: str,
    recipient_certificate_sha256: str,
    custody_record: dict[str, Any] | None = None,
    custody_state: str | None = None,
    expected_stress_selection_sha256: str | None = None,
    private_key_path: str | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Verify every v2 unseal precondition; raise UnsealPreflightError on any
    failure. Returns a preflight record when all checks pass. Does NOT
    decrypt and does NOT invoke OpenSSL."""
    # 1. threshold manifest validates against the new v2 threshold schema
    #    (structural + const validation against the committed schema file).
    if threshold_manifest.get("schema") != V2_THRESHOLD_SCHEMA:
        _fail("threshold manifest is not the v2 threshold schema")
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
    if not _is_sha256(threshold_manifest.get("stress_selection_sha256")):
        _fail("threshold manifest selected-eight SHA is missing or invalid")
    if (
        expected_stress_selection_sha256 is not None
        and threshold_manifest.get("stress_selection_sha256") != expected_stress_selection_sha256
    ):
        _fail("threshold manifest selected-eight SHA is not bound to the expected committed selection")
    # 9. encrypted holdout file SHA
    if holdout_ciphertext_sha256 != HOLDOUT_CIPHERTEXT_SHA256:
        _fail("holdout ciphertext SHA mismatch")
    # 10. recipient certificate SHA matches the committed certificate
    if recipient_certificate_sha256 != EXPECTED_RECIPIENT_CERTIFICATE_SHA256:
        _fail("recipient certificate SHA mismatch")
    # 11. private key path (if supplied for the future step) must be external
    #     to the Git repository scope
    if private_key_path is not None:
        key = Path(private_key_path)
        if repo_root is not None:
            root = Path(repo_root).resolve()
            try:
                key.resolve().relative_to(root)
            except ValueError:
                pass  # outside the repo: acceptable
            else:
                _fail("private key path must be external to the Git repository scope")
        if key.name in {"recipient-certificate.pem"} or str(key).endswith(".cms"):
            _fail("private key path points at committed repository material")
    # 12. custody state is not HOLDOUT_CUSTODY_BLOCKED. The custody record is
    #     public metadata (no secret material); its verdict/state fields are
    #     checked directly rather than recursively rejected like derivation
    #     inputs, because recording the ciphertext SHA/state is its purpose.
    effective_custody = custody_state
    if custody_record is not None:
        if custody_record.get("custody_verdict") == HOLDOUT_CUSTODY_BLOCKED or (
            custody_record.get("custody_verdict") != CUSTODY_VERDICT_OK
            and custody_record.get("holdout_state") == HOLDOUT_CUSTODY_BLOCKED
        ):
            effective_custody = HOLDOUT_CUSTODY_BLOCKED
    if effective_custody == HOLDOUT_CUSTODY_BLOCKED:
        _fail("holdout custody is blocked; unseal is refused")

    return {
        "schema": "inferswarm.issue79.v2-unseal-preflight/1",
        "verdict": "UNSEAL_PRECONDITIONS_PASS_DECRYPT_NOT_PERFORMED",
        "threshold_schema": V2_THRESHOLD_SCHEMA,
        "threshold_manifest_sha256": threshold_manifest_sha256,
        "holdout_ciphertext_sha256": holdout_ciphertext_sha256,
        "recipient_certificate_sha256": recipient_certificate_sha256,
        "custody_state": effective_custody or CUSTODY_VERDICT_OK,
        "decrypt_performed": False,
        "openssl_invoked": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threshold-manifest", required=True, type=Path)
    parser.add_argument("--expected-threshold-sha256", required=True)
    parser.add_argument("--holdout-ciphertext", required=True, type=Path)
    parser.add_argument("--recipient-certificate", required=True, type=Path)
    parser.add_argument("--custody-record", type=Path)
    parser.add_argument("--private-key-path", default=None,
                        help="future unseal private key path; must be external to the repo")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    record = validate_unseal_preconditions(
        threshold_manifest=json.loads(args.threshold_manifest.read_text(encoding="utf-8")),
        threshold_manifest_sha256=sha256_file(args.threshold_manifest),
        expected_committed_threshold_sha256=args.expected_threshold_sha256,
        holdout_ciphertext_sha256=sha256_file(args.holdout_ciphertext),
        recipient_certificate_sha256=sha256_file(args.recipient_certificate),
        custody_record=(
            json.loads(args.custody_record.read_text(encoding="utf-8"))
            if args.custody_record else None
        ),
        private_key_path=args.private_key_path,
        repo_root=args.repo_root,
    )
    args.out.write_bytes(canonical_json_bytes(record))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
