#!/usr/bin/env python3
"""InferSwarm issue #86: v3 holdout-unseal preflight (CPU-only, fail-closed).

Refuses permission to proceed to the FUTURE v3 unseal step unless every
precondition holds. This module NEVER decrypts anything and never invokes
OpenSSL decrypt: it is a pure preflight/verifier. The future unseal itself
remains the maintainer's explicit act against the retained v3 ciphertext
(#83 §6 step 5; issue #86 section 10 — no OpenSSL decrypt is authorized by
issue #86).

Fail-closed contract (mirrors the accepted #79 hardening, v3-identified):

- the selected-eight artifact is bound to an INDEPENDENTLY supplied expected
  committed SHA (mandatory keyword), never merely to a field inside the
  threshold manifest;
- the threshold manifest is validated against the exact committed v3
  threshold JSON Schema (Draft 2020-12) before any further authorization;
- v3 holdout material (ciphertext/certificate/custody) must match the frozen
  committed identities; supplying the HISTORICAL #74 holdout ciphertext,
  certificate, or custody record is an explicit rejection;
- custody must be explicitly FOUND-equivalent via the committed non-secret
  custody record (2 custodians, public_key_match true);
- a supplied private-key path must ALWAYS be proven external to the
  repository root, which is derived deterministically from this file's
  location.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, NoReturn, Sequence

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

from issue86_v3_methodology import (
    argmax_tie_break_identity,
    decision_domain_construction_identity,
    is_sha256,
    sha256_bytes,
)
from issue74_methodology import MethodologyError, canonical_json_bytes, sha256_file
from issue86_v3_thresholds import (
    HISTORICAL_H74_CIPHERTEXT_SHA256,
    V3_HOLDOUT_CERTIFICATE_SHA256,
    V3_HOLDOUT_CIPHERTEXT_SHA256,
    V3_STRESS_COMMITMENT_SHA256,
    V3_STRESS_POOL_SHA256,
    V3_TOOLING_VERSION,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
THRESHOLD_SCHEMA_PATH = (
    REPO_ROOT / "docs/qualification/gemma4-12b-it-v3/schemas/threshold-manifest.schema.json"
)
CUSTODY_SCHEMA = "inferswarm.issue86.v3-holdout-custody-record/1"
V3_CUSTODY_CIPHERTEXT_SHA256 = V3_HOLDOUT_CIPHERTEXT_SHA256
V3_RECIPIENT_PUBLIC_KEY_DER_SHA256 = (
    "fc56175d275b24344354828957dfef84efc1ff3bfd02d996efe7a4d78f14cf9b"
)
HISTORICAL_H74_CERTIFICATE_SHA256 = (
    "9edb50e82a070bc666b43ac7d0fac158caa906a34510efda3241b1d160be2b46"
)
HISTORICAL_H74_CUSTODY_SCHEMA = "inferswarm.issue74.holdout-custody-record/1"

SELECTED_SHA_MISMATCH = "SELECTED_STRESS_SELECTION_SHA_MISMATCH"
THRESHOLD_SCHEMA_INVALID = "THRESHOLD_MANIFEST_SCHEMA_INVALID"
CUSTODY_NOT_VERIFIED = "HOLDOUT_CUSTODY_NOT_VERIFIED"
PRIVATE_KEY_NOT_EXTERNAL = "PRIVATE_KEY_PATH_NOT_EXTERNAL_TO_REPO"
WRONG_HISTORICAL_HOLDOUT = "HISTORICAL_H74_HOLDOUT_SUPPLIED_TO_V3_UNSEAL_PATH"
WRONG_V3_HOLDOUT_MATERIAL = "V3_HOLDOUT_MATERIAL_MISMATCH"
INCOMPLETE_THRESHOLD_FREEZE = "INCOMPLETE_THRESHOLD_FREEZE"


class UnsealPreflightError(ValueError):
    """A v3 unseal precondition failed; permission to proceed is refused."""


def _fail(message: str, code: str | None = None) -> NoReturn:
    raise UnsealPreflightError(f"{code}: {message}" if code else message)


def load_threshold_schema() -> dict[str, Any]:
    schema = json.loads(THRESHOLD_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return schema


def validate_unseal_preconditions(
    *,
    threshold_manifest: dict[str, Any],
    threshold_manifest_sha256: str,
    expected_committed_threshold_sha256: str,
    holdout_ciphertext_sha256: str,
    recipient_certificate_sha256: str,
    custody_record: dict[str, Any],
    expected_stress_selection_sha256: str,
    private_key_path: Path | None = None,
    threshold_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Authorize the FUTURE v3 unseal; never decrypt; never invoke OpenSSL."""
    # 1. threshold manifest committed SHA must match the independently
    #    supplied expectation — an external commitment, not self-reference.
    if not is_sha256(expected_committed_threshold_sha256):
        _fail("expected committed threshold SHA-256 is malformed")
    if threshold_manifest_sha256 != expected_committed_threshold_sha256:
        _fail(
            "threshold manifest SHA does not match the independently committed "
            f"expectation (expected {expected_committed_threshold_sha256}, "
            f"observed {threshold_manifest_sha256})",
            SELECTED_SHA_MISMATCH,
        )
    # observed sha must actually be the canonical hash of the manifest.
    if threshold_manifest_sha256 != sha256_bytes(canonical_json_bytes(threshold_manifest)):
        _fail("threshold manifest bytes do not hash to the supplied SHA", THRESHOLD_SCHEMA_INVALID)

    # 2. validate against the committed v3 threshold JSON Schema.
    schema = threshold_schema if threshold_schema is not None else load_threshold_schema()
    try:
        Draft202012Validator(schema).validate(threshold_manifest)
    except JsonSchemaValidationError as exc:
        _fail(f"threshold manifest failed schema validation: {exc.message}", THRESHOLD_SCHEMA_INVALID)

    # 3. frozen semantic provenance inside the manifest.
    if threshold_manifest.get("holdout_state") != "SEALED_NOT_CONSUMED":
        _fail("threshold manifest is not in the SEALED_NOT_CONSUMED state", INCOMPLETE_THRESHOLD_FREEZE)
    if threshold_manifest.get("decision_domain_construction") != decision_domain_construction_identity():
        _fail("threshold manifest decision-domain construction identity mismatch", INCOMPLETE_THRESHOLD_FREEZE)
    if threshold_manifest.get("argmax_tie_break") != argmax_tie_break_identity():
        _fail("threshold manifest argmax/tie-break identity mismatch", INCOMPLETE_THRESHOLD_FREEZE)
    if threshold_manifest.get("stress_pool_sha256") != V3_STRESS_POOL_SHA256:
        _fail("threshold manifest stress pool provenance mismatch", INCOMPLETE_THRESHOLD_FREEZE)
    if threshold_manifest.get("stress_selection_commitment_sha256") != V3_STRESS_COMMITMENT_SHA256:
        _fail("threshold manifest stress selection commitment provenance mismatch", INCOMPLETE_THRESHOLD_FREEZE)
    if threshold_manifest.get("tooling_version") != V3_TOOLING_VERSION:
        _fail("threshold manifest tooling version mismatch", INCOMPLETE_THRESHOLD_FREEZE)
    if not threshold_manifest.get("e_d_hex"):
        _fail("threshold manifest lacks E_D", INCOMPLETE_THRESHOLD_FREEZE)
    if not is_sha256(threshold_manifest.get("stress_selection_sha256", "")):
        _fail("threshold manifest lacks the selected-eight binding", INCOMPLETE_THRESHOLD_FREEZE)

    # 4. the selected-eight binding must match the INDEPENDENT expectation.
    if threshold_manifest.get("stress_selection_sha256") != expected_stress_selection_sha256:
        _fail(
            "threshold manifest selected-eight SHA does not match the independently "
            "committed expectation",
            SELECTED_SHA_MISMATCH,
        )

    # 5. v3 holdout material identity — and explicit historical rejection.
    if holdout_ciphertext_sha256 == HISTORICAL_H74_CIPHERTEXT_SHA256:
        _fail(
            "the historical #74 holdout ciphertext was supplied to the v3 unseal "
            "path; #74 holdout reuse is prohibited permanently",
            WRONG_HISTORICAL_HOLDOUT,
        )
    if recipient_certificate_sha256 == HISTORICAL_H74_CERTIFICATE_SHA256:
        _fail(
            "the historical #74 recipient certificate was supplied to the v3 "
            "unseal path",
            WRONG_HISTORICAL_HOLDOUT,
        )
    if custody_record.get("schema") == HISTORICAL_H74_CUSTODY_SCHEMA:
        _fail(
            "the historical #74 custody record was supplied to the v3 unseal path",
            WRONG_HISTORICAL_HOLDOUT,
        )
    if holdout_ciphertext_sha256 != V3_HOLDOUT_CIPHERTEXT_SHA256:
        _fail(
            f"v3 holdout ciphertext SHA mismatch (expected {V3_HOLDOUT_CIPHERTEXT_SHA256}, "
            f"observed {holdout_ciphertext_sha256})",
            WRONG_V3_HOLDOUT_MATERIAL,
        )
    if recipient_certificate_sha256 != V3_HOLDOUT_CERTIFICATE_SHA256:
        _fail(
            f"v3 recipient certificate SHA mismatch (expected {V3_HOLDOUT_CERTIFICATE_SHA256}, "
            f"observed {recipient_certificate_sha256})",
            WRONG_V3_HOLDOUT_MATERIAL,
        )

    # 6. custody must be explicitly proven via the committed v3 record.
    if custody_record.get("schema") != CUSTODY_SCHEMA:
        _fail("custody record is not the v3 schema", CUSTODY_NOT_VERIFIED)
    if custody_record.get("holdout_state") != "SEALED_NOT_CONSUMED":
        _fail("custody record holdout state is not SEALED_NOT_CONSUMED", CUSTODY_NOT_VERIFIED)
    if custody_record.get("holdout_ciphertext_sha256") != V3_HOLDOUT_CIPHERTEXT_SHA256:
        _fail("custody record does not bind the exact v3 ciphertext", CUSTODY_NOT_VERIFIED)
    if custody_record.get("recipient_certificate_sha256") != V3_HOLDOUT_CERTIFICATE_SHA256:
        _fail("custody record does not bind the exact v3 certificate", CUSTODY_NOT_VERIFIED)
    if custody_record.get("recipient_public_key_der_sha256") != V3_RECIPIENT_PUBLIC_KEY_DER_SHA256:
        _fail("custody record public-key DER SHA mismatch", CUSTODY_NOT_VERIFIED)
    custodians = custody_record.get("custodians")
    if not isinstance(custodians, list) or len(custodians) < 2:
        _fail("custody requires at least two verified custodians", CUSTODY_NOT_VERIFIED)
    key_shas = set()
    for custodian in custodians:
        if custodian.get("public_key_match") is not True:
            _fail(f"custodian {custodian.get('custodian_id')!r} public key not verified", CUSTODY_NOT_VERIFIED)
        key_sha = custodian.get("private_key_sha256")
        if not is_sha256(key_sha):
            _fail(f"custodian {custodian.get('custodian_id')!r} lacks a private-key SHA", CUSTODY_NOT_VERIFIED)
        key_shas.add(key_sha)
    if len(key_shas) != 1:
        _fail("custodians do not share one exact private-key identity", CUSTODY_NOT_VERIFIED)

    # 7. private key must be external to the repository, always.
    if private_key_path is not None:
        key = Path(private_key_path).resolve()
        try:
            key.relative_to(REPO_ROOT)
        except ValueError:
            pass
        else:
            _fail(
                f"private key {key} is inside the repository root {REPO_ROOT}; "
                "repo-local private keys are prohibited",
                PRIVATE_KEY_NOT_EXTERNAL,
            )

    return {
        "schema": "inferswarm.issue86.v3-unseal-preflight-record/1",
        "verdict": "UNSEAL_PRECONDITIONS_PASS_DECRYPT_NOT_PERFORMED",
        "decrypt_performed": False,
        "openssl_invoked": False,
        "threshold_manifest_sha256": threshold_manifest_sha256,
        "holdout_ciphertext_sha256": holdout_ciphertext_sha256,
        "recipient_certificate_sha256": recipient_certificate_sha256,
        "stress_selection_sha256": expected_stress_selection_sha256,
        "decision_domain_construction": decision_domain_construction_identity(),
        "argmax_tie_break": argmax_tie_break_identity(),
        "custodian_count": len(custodians),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threshold-manifest", required=True, type=Path)
    parser.add_argument("--expected-threshold-sha256", required=True)
    parser.add_argument("--expected-stress-selection-sha256", required=True)
    parser.add_argument("--custody-record", required=True, type=Path)
    parser.add_argument("--holdout-ciphertext", required=True, type=Path)
    parser.add_argument("--recipient-certificate", required=True, type=Path)
    parser.add_argument("--private-key-path", required=True, type=Path)
    args = parser.parse_args(argv)
    manifest = json.loads(args.threshold_manifest.read_text(encoding="utf-8"))
    custody = json.loads(args.custody_record.read_text(encoding="utf-8"))
    # Hash the ACTUAL bytes of the supplied holdout/certificate files —
    # never substitute the frozen hash constants. Missing files fail here
    # (unreadable path), corrupt/historical/wrong material fails the
    # identity checks inside the verifier.
    holdout_ciphertext_sha256 = sha256_file(args.holdout_ciphertext)
    recipient_certificate_sha256 = sha256_file(args.recipient_certificate)

    # Hash the ACTUAL threshold file bytes (accepted #79 behavior): the
    # committed/refetched artifact must remain byte-identical, so a file
    # that differs from the committed bytes by even whitespace/newlines
    # must fail here. The verifier separately enforces that the parsed
    # manifest's canonical representation hashes to the same SHA, so BOTH
    # the exact file bytes and the canonical representation are bound.
    record = validate_unseal_preconditions(
        threshold_manifest=manifest,
        threshold_manifest_sha256=sha256_file(args.threshold_manifest),
        expected_committed_threshold_sha256=args.expected_threshold_sha256,
        holdout_ciphertext_sha256=holdout_ciphertext_sha256,
        recipient_certificate_sha256=recipient_certificate_sha256,
        custody_record=custody,
        expected_stress_selection_sha256=args.expected_stress_selection_sha256,
        private_key_path=args.private_key_path,
    )
    print(json.dumps(record, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
