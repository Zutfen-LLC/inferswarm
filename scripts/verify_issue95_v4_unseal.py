#!/usr/bin/env python3
"""Non-decrypting issue #95 v4 unseal preflight.

OpenSSL is used only to derive public-key DER from supplied key/certificate; no
CMS decrypt operation is present or reachable.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from issue74_methodology import MethodologyError, sha256_bytes, sha256_file

ROOT = Path(__file__).resolve().parents[1]
V4 = ROOT / 'docs/qualification/gemma4-12b-it-v4'


def _external_regular_readable(path: Path) -> Path:
    if path.is_symlink() or not path.exists() or not path.is_file():
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


def _run(*args: str, input_bytes: bytes | None = None) -> bytes:
    try:
        result = subprocess.run(['openssl', *args], input=input_bytes, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise MethodologyError('PUBLIC_KEY_DER_DERIVATION_FAILED') from exc
    if not result.stdout:
        raise MethodologyError('PUBLIC_KEY_DER_DERIVATION_FAILED')
    return result.stdout


def _private_public_der(key: Path) -> bytes:
    return _run('pkey', '-in', str(key), '-pubout', '-outform', 'DER')


def _certificate_public_der(certificate: Path) -> bytes:
    return _run('pkey', '-pubin', '-outform', 'DER', input_bytes=_run('x509', '-in', str(certificate), '-pubkey', '-noout'))


def _load_json_exact(path: Path, expected_sha256: str, label: str) -> dict[str, Any]:
    if not path.is_file() or sha256_file(path) != expected_sha256:
        raise MethodologyError(f'{label}_SHA_MISMATCH')
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise MethodologyError(f'{label}_INVALID') from exc


def validate_unseal_preconditions(*, core_threshold_path: Path, expected_core_threshold_sha256: str,
                                  ciphertext: Path, certificate: Path, custody_record_path: Path,
                                  expected_custody_record_sha256: str, private_key_path: Path) -> dict[str, str]:
    threshold = _load_json_exact(core_threshold_path, expected_core_threshold_sha256, 'CORE_THRESHOLD_FILE')
    custody = _load_json_exact(custody_record_path, expected_custody_record_sha256, 'HOLDOUT_CUSTODY_RECORD')
    commitment = json.loads((V4 / 'manifests/sealed-holdout-commitment.json').read_text())
    if threshold.get('schema') != 'inferswarm.issue95.v4-core-threshold-manifest/1' or threshold.get('holdout_state') != 'SEALED_NOT_CONSUMED':
        raise MethodologyError('INCOMPLETE_THRESHOLD_FREEZE')
    provenance = threshold.get('provenance')
    if not isinstance(provenance, dict) or provenance.get('holdout_custody_record_sha256') != expected_custody_record_sha256:
        raise MethodologyError('THRESHOLD_CUSTODY_IDENTITY_MISMATCH')
    if custody.get('schema') != 'inferswarm.issue95.v4-holdout-custody-record/1' or custody.get('holdout_state') != 'SEALED_NOT_CONSUMED' or custody.get('unseal_authorized') is not False:
        raise MethodologyError('HOLDOUT_CUSTODY_NOT_VERIFIED')
    if sha256_file(ciphertext) != commitment.get('ciphertext_sha256') or sha256_file(certificate) != commitment.get('recipient_certificate_sha256'):
        raise MethodologyError('HOLDOUT_MATERIAL_MISMATCH')
    if custody.get('holdout_ciphertext_sha256') != commitment.get('ciphertext_sha256') or custody.get('recipient_certificate_sha256') != commitment.get('recipient_certificate_sha256'):
        raise MethodologyError('HOLDOUT_CUSTODY_NOT_VERIFIED')
    key = _external_regular_readable(private_key_path)
    key_sha = sha256_file(key)
    custodians = custody.get('custodians', [])
    if len(custodians) < 2 or len({c.get('custodian_id') for c in custodians}) != len(custodians) or not all(c.get('public_key_match') is True for c in custodians):
        raise MethodologyError('HOLDOUT_CUSTODY_NOT_VERIFIED')
    if not any(c.get('private_key_sha256') == key_sha for c in custodians):
        raise MethodologyError('PRIVATE_KEY_CUSTODY_HASH_MISMATCH')
    private_der, certificate_der = _private_public_der(key), _certificate_public_der(certificate)
    if private_der != certificate_der:
        raise MethodologyError('PRIVATE_KEY_CERTIFICATE_PUBLIC_KEY_MISMATCH')
    public_der_sha = sha256_bytes(private_der)
    if public_der_sha != custody.get('recipient_public_key_der_sha256'):
        raise MethodologyError('RECIPIENT_PUBLIC_KEY_DER_SHA_MISMATCH')
    return {'verdict': 'PRECONDITIONS_PASS_STOP_BEFORE_DECRYPT', 'threshold_sha256': sha256_file(core_threshold_path), 'custody_record_sha256': sha256_file(custody_record_path), 'ciphertext_sha256': sha256_file(ciphertext), 'certificate_sha256': sha256_file(certificate), 'recipient_public_key_der_sha256': public_der_sha}


if __name__ == '__main__':
    raise SystemExit('This verifier is library-only and intentionally cannot decrypt holdout material.')
