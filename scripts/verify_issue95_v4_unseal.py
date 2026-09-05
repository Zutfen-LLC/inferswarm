#!/usr/bin/env python3
"""Non-decrypting issue #95 v4 unseal preflight.

This module is explicitly permitted to invoke OpenSSL only to derive public-key
DER from the supplied private key and recipient certificate. It never invokes
CMS decrypt functionality.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from issue74_methodology import MethodologyError, sha256_bytes, sha256_file

ROOT = Path(__file__).resolve().parents[1]


def _external_regular_readable(path: Path) -> Path:
    if path.is_symlink() or not path.exists() or not path.is_file() or not path.stat().st_mode:
        raise MethodologyError('PRIVATE_KEY_PATH_NOT_EXTERNAL_REGULAR_READABLE_FILE')
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        pass
    else:
        raise MethodologyError('PRIVATE_KEY_PATH_NOT_EXTERNAL_TO_REPO')
    try:
        with resolved.open('rb') as handle:
            handle.read(1)
    except OSError as exc:
        raise MethodologyError('PRIVATE_KEY_PATH_NOT_EXTERNAL_REGULAR_READABLE_FILE') from exc
    return resolved


def _openssl_public_der(*args: str) -> bytes:
    try:
        result = subprocess.run(['openssl', *args], check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise MethodologyError('PUBLIC_KEY_DER_DERIVATION_FAILED') from exc
    if not result.stdout:
        raise MethodologyError('PUBLIC_KEY_DER_DERIVATION_FAILED')
    return result.stdout


def _private_public_der(key: Path) -> bytes:
    return _openssl_public_der('pkey', '-in', str(key), '-pubout', '-outform', 'DER')


def _certificate_public_der(certificate: Path) -> bytes:
    try:
        pubkey = subprocess.run(
            ['openssl', 'x509', '-in', str(certificate), '-pubkey', '-noout'],
            check=True, capture_output=True,
        ).stdout
        result = subprocess.run(
            ['openssl', 'pkey', '-pubin', '-outform', 'DER'], input=pubkey,
            check=True, capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise MethodologyError('PUBLIC_KEY_DER_DERIVATION_FAILED') from exc
    if not result.stdout:
        raise MethodologyError('PUBLIC_KEY_DER_DERIVATION_FAILED')
    return result.stdout


def validate_unseal_preconditions(*, core_threshold_path: Path, expected_core_threshold_sha256: str,
                                  ciphertext: Path, certificate: Path,
                                  custody_record: dict[str, Any], private_key_path: Path) -> dict[str, str]:
    if sha256_file(core_threshold_path) != expected_core_threshold_sha256:
        raise MethodologyError('CORE_THRESHOLD_FILE_SHA_MISMATCH')
    threshold = json.loads(core_threshold_path.read_text())
    if threshold.get('schema') != 'inferswarm.issue95.v4-core-threshold-manifest/1' or threshold.get('holdout_state') != 'SEALED_NOT_CONSUMED':
        raise MethodologyError('INCOMPLETE_THRESHOLD_FREEZE')
    if custody_record.get('schema') != 'inferswarm.issue95.v4-holdout-custody-record/1' or custody_record.get('holdout_state') != 'SEALED_NOT_CONSUMED':
        raise MethodologyError('HOLDOUT_CUSTODY_NOT_VERIFIED')
    if custody_record.get('holdout_ciphertext_sha256') != sha256_file(ciphertext) or custody_record.get('recipient_certificate_sha256') != sha256_file(certificate):
        raise MethodologyError('HOLDOUT_MATERIAL_MISMATCH')
    key = _external_regular_readable(private_key_path)
    key_sha = sha256_file(key)
    custodians = custody_record.get('custodians', [])
    if len(custodians) < 2 or not all(c.get('public_key_match') is True for c in custodians):
        raise MethodologyError('HOLDOUT_CUSTODY_NOT_VERIFIED')
    if not any(c.get('private_key_sha256') == key_sha for c in custodians):
        raise MethodologyError('PRIVATE_KEY_CUSTODY_HASH_MISMATCH')
    private_der = _private_public_der(key)
    certificate_der = _certificate_public_der(certificate)
    if private_der != certificate_der:
        raise MethodologyError('PRIVATE_KEY_CERTIFICATE_PUBLIC_KEY_MISMATCH')
    public_der_sha = sha256_bytes(private_der)
    if public_der_sha != custody_record.get('recipient_public_key_der_sha256'):
        raise MethodologyError('RECIPIENT_PUBLIC_KEY_DER_SHA_MISMATCH')
    return {'verdict': 'PRECONDITIONS_PASS_STOP_BEFORE_DECRYPT',
            'threshold_sha256': sha256_file(core_threshold_path),
            'ciphertext_sha256': sha256_file(ciphertext),
            'certificate_sha256': sha256_file(certificate),
            'recipient_public_key_der_sha256': public_der_sha}


if __name__ == '__main__':
    raise SystemExit('This verifier is library-only and intentionally cannot decrypt holdout material.')
