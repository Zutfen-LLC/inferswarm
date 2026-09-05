#!/usr/bin/env python3
"""Create the public commitment + custody record for the sealed v4 holdout.

Reads the PLAINTEXT holdout once (on the sealing host, never committed),
binds every non-secret case hash required for the public disjointness proof,
and emits:

- sealed-holdout-commitment.json (public; ciphertext/certificate hashes);
- holdout-custody-record.json (non-secret custody metadata only).

Plaintext and secret seed are never written by this script. Historical v1
holdout ciphertext/certificate are pinned as NEVER-REUSE identities.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Sequence

from issue95_v4_methodology import CONTRACT_ID
from issue74_methodology import canonical_json_bytes, sha256_file
from issue95_v4_methodology import (
    V4_HOLDOUT_COMMITMENT_SCHEMA,
    V4_HOLDOUT_CUSTODY_SCHEMA,
    V4_HOLDOUT_PLAINTEXT_SCHEMA,
    is_sha256,
)

HISTORICAL_H74_CIPHERTEXT_SHA256 = (
    "23311c5514b2561c66a2ecd0c9cfa25c3f4f91b83b67353aada8355f48e25c59"
)
HISTORICAL_H74_CERTIFICATE_SHA256 = (
    "9edb50e82a070bc666b43ac7d0fac158caa906a34510efda3241b1d160be2b46"
)


def build_commitment(
    plaintext_holdout: dict[str, Any], ciphertext: Path, certificate: Path
) -> dict[str, Any]:
    if plaintext_holdout.get("schema") != V4_HOLDOUT_PLAINTEXT_SCHEMA:
        raise ValueError("holdout plaintext schema mismatch")
    cases = plaintext_holdout.get("cases")
    if not isinstance(cases, list) or len(cases) != 24:
        raise ValueError("v4 holdout must contain exactly 24 cases")
    observed_cells = {
        (row["content_class"], tuple(row["length_regime"])) for row in cases  # type: ignore[union-attr]
    }
    from issue74_methodology import CONTENT_CLASSES, LENGTH_REGIMES

    expected_cells = {(name, bounds) for name in CONTENT_CLASSES for bounds in LENGTH_REGIMES}
    if observed_cells != expected_cells:
        raise ValueError("v4 holdout must contain exactly one case in each of 24 cells")
    ciphertext_sha = sha256_file(ciphertext)
    if ciphertext_sha == HISTORICAL_H74_CIPHERTEXT_SHA256:
        raise ValueError("historical #74 holdout ciphertext reuse is prohibited")
    certificate_sha = sha256_file(certificate)
    if certificate_sha == HISTORICAL_H74_CERTIFICATE_SHA256:
        raise ValueError("historical #74 recipient certificate reuse is prohibited")
    return {
        "schema": V4_HOLDOUT_COMMITMENT_SCHEMA,
        "contract_id": CONTRACT_ID,
        "state": "SEALED_NOT_CONSUMED",
        "case_count": 24,
        "cells": [
            {
                "case_id": row["case_id"],
                "content_class": row["content_class"],
                "length_regime": row["length_regime"],
                "token_count": row["token_count"],
                "prompt_sha256": row["prompt_sha256"],
                "token_ids_sha256": row["token_ids_sha256"],
                "case_sha256": row["case_sha256"],
            }
            for row in cases
        ],
        "secret_seed_sha256": plaintext_holdout["secret_seed_sha256"],
        "generator": plaintext_holdout["generator"],
        "generator_sha256": plaintext_holdout["generator_sha256"],
        "tokenizer_json_sha256": plaintext_holdout["tokenizer_json_sha256"],  # type: ignore[index]
        "cipher": "CMS EnvelopedData; AES-256-CBC; RSA-3072 recipient",
        "ciphertext_sha256": ciphertext_sha,
        "recipient_certificate_sha256": certificate_sha,
        "unseal_rule": (
            "only after the v4 threshold manifest is committed and the v4 "
            "unseal preflight passes; only by the maintainer's explicit act"
        ),
        "plaintext_retention": "PROHIBITED_IN_REPOSITORY",
        "historical_h74_holdout_reuse": "PROHIBITED_PERMANENTLY",
        "historical_h74_ciphertext_sha256": HISTORICAL_H74_CIPHERTEXT_SHA256,
    }


def build_custody_record(
    commitment: dict[str, Any], custodians: Sequence[dict[str, Any]]
) -> dict[str, Any]:
    if len(custodians) < 2:
        raise ValueError("at least two verified external custodian copies are required")
    for custodian in custodians:
        if not is_sha256(custodian.get("private_key_sha256")):
            raise ValueError("custodian entries must pin the private-key SHA-256")
        if custodian.get("public_key_match") is not True:
            raise ValueError("custodian public_key_match must be verified true")
        if custodian.get("verified_date") is None:
            raise ValueError("custodian entries must record a verification date")
    return {
        "schema": V4_HOLDOUT_CUSTODY_SCHEMA,
        "contract_id": CONTRACT_ID,
        "custodians": list(custodians),
        "holdout_ciphertext_sha256": commitment["ciphertext_sha256"],
        "recipient_certificate_sha256": commitment["recipient_certificate_sha256"],
        "holdout_state": "SEALED_NOT_CONSUMED",
        "private_material_in_repository": "PROHIBITED",
        "fail_closed_rule": (
            "if both custodians become unavailable the v4 methodology terminates "
            "at HOLDOUT_CUSTODY_BLOCKED; never regenerate a key for the existing "
            "ciphertext"
        ),
        "unseal_authorized": False,
        "verification_method": (
            "openssl pkey -pubout -outform DER from the private key vs "
            "openssl x509 -pubkey from the committed certificate; "
            "non-decrypting; holdout NOT unsealed"
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    raise SystemExit("custody metadata is assembled in the sealing session; see TOOLING.md")


if __name__ == "__main__":
    raise SystemExit(main())
