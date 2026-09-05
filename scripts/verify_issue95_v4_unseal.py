#!/usr/bin/env python3
"""Non-decrypting v4 unseal preflight. Never invokes a decrypt operation."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Any
from issue74_methodology import MethodologyError, sha256_file

ROOT = Path(__file__).resolve().parents[1]


def validate_unseal_preconditions(*, core_threshold_path: Path, expected_core_threshold_sha256: str, ciphertext: Path, certificate: Path, custody_record: dict[str, Any], private_key_path: Path) -> dict[str, str]:
    if sha256_file(core_threshold_path) != expected_core_threshold_sha256:
        raise MethodologyError('CORE_THRESHOLD_FILE_SHA_MISMATCH')
    threshold = json.loads(core_threshold_path.read_text())
    if threshold.get('schema') != 'inferswarm.issue95.v4-core-threshold-manifest/1' or threshold.get('holdout_state') != 'SEALED_NOT_CONSUMED':
        raise MethodologyError('INCOMPLETE_THRESHOLD_FREEZE')
    if custody_record.get('schema') != 'inferswarm.issue95.v4-holdout-custody-record/1' or custody_record.get('holdout_state') != 'SEALED_NOT_CONSUMED':
        raise MethodologyError('HOLDOUT_CUSTODY_NOT_VERIFIED')
    if custody_record.get('holdout_ciphertext_sha256') != sha256_file(ciphertext) or custody_record.get('recipient_certificate_sha256') != sha256_file(certificate):
        raise MethodologyError('HOLDOUT_MATERIAL_MISMATCH')
    if len(custody_record.get('custodians', [])) < 2 or not all(c.get('public_key_match') is True for c in custody_record['custodians']):
        raise MethodologyError('HOLDOUT_CUSTODY_NOT_VERIFIED')
    try:
        private_key_path.resolve().relative_to(ROOT)
    except ValueError:
        pass
    else:
        raise MethodologyError('PRIVATE_KEY_PATH_NOT_EXTERNAL_TO_REPO')
    return {'verdict':'PRECONDITIONS_PASS_STOP_BEFORE_DECRYPT', 'threshold_sha256':sha256_file(core_threshold_path), 'ciphertext_sha256':sha256_file(ciphertext), 'certificate_sha256':sha256_file(certificate)}

if __name__ == '__main__':
    raise SystemExit('This verifier is library-only and intentionally cannot decrypt holdout material.')
