#!/usr/bin/env python3
"""Create the public commitment + custody record for the sealed v5 holdout.

Reads the PLAINTEXT holdout once (on the sealing host, never committed),
binds every non-secret case hash required for the public disjointness proof,
and emits:

- sealed-holdout-commitment.json (public; ciphertext/certificate hashes);
- holdout-custody-record.json (non-secret custody metadata only).

Plaintext and secret seed are never written by this script. Unlike v1/v3/v4,
the v5 holdout is 24 IID mixture draws, not one case per each of 24 fixed
cells, so no per-cell balance is required or checked here — only that every
case's declared component is a member of the frozen 24-component mixture.

``custody_is_satisfied`` is a fail-closed helper: the historical v1-v4
pattern required at least two independently verified custodian copies before
declaring holdout_state == SEALED_NOT_CONSUMED. A commitment with fewer than
two verified custodians must use holdout_state == SEALED_CUSTODY_INCOMPLETE
and unseal_authorized == False; it is not eligible for the unseal preflight
(verify_issue109_v5_unseal.py) until a second copy is established and
verified.
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Any, Sequence

from issue109_v5_methodology import (
    CONTRACT_ID,
    V5_HOLDOUT_CASES,
    V5_HOLDOUT_COMMITMENT_SCHEMA,
    V5_HOLDOUT_CUSTODY_SCHEMA,
    V5_HOLDOUT_PLAINTEXT_SCHEMA,
    is_sha256,
    mixture_components,
)
from issue74_methodology import canonical_json_bytes, sha256_bytes, sha256_file
from generate_issue109_corpora import realized_component_counts

SEALED_NOT_CONSUMED = "SEALED_NOT_CONSUMED"
SEALED_CUSTODY_INCOMPLETE = "SEALED_CUSTODY_INCOMPLETE"


def build_commitment(
    plaintext_holdout: dict[str, Any], ciphertext: Path, certificate: Path
) -> dict[str, Any]:
    if plaintext_holdout.get("schema") != V5_HOLDOUT_PLAINTEXT_SCHEMA:
        raise ValueError("v5 holdout plaintext schema mismatch")
    cases = plaintext_holdout.get("cases")
    if not isinstance(cases, list) or len(cases) != V5_HOLDOUT_CASES:
        raise ValueError(f"v5 holdout must contain exactly {V5_HOLDOUT_CASES} cases")
    from issue74_methodology import LENGTH_REGIMES as _REGIMES

    valid_regimes = {tuple(regime) for regime in _REGIMES}
    valid_classes = {content_class for content_class, _ in mixture_components()}
    observed_ids = set()
    for row in cases:
        case_id = row["case_id"]
        if case_id in observed_ids or not case_id.startswith("h109-"):
            raise ValueError("v5 holdout contains a duplicate or malformed case ID")
        if (row["content_class"] not in valid_classes
                or tuple(row["length_regime"]) not in valid_regimes):
            raise ValueError("v5 holdout case is not a member of the frozen mixture population")
        observed_ids.add(case_id)
    if len(observed_ids) != V5_HOLDOUT_CASES:
        raise ValueError("v5 holdout case identities are not all distinct")
    ciphertext_sha = sha256_file(ciphertext)
    certificate_sha = sha256_file(certificate)
    return {
        "schema": V5_HOLDOUT_COMMITMENT_SCHEMA,
        "contract_id": CONTRACT_ID,
        "state": SEALED_NOT_CONSUMED,
        "case_count": V5_HOLDOUT_CASES,
        "draws": [
            {
                "case_id": row["case_id"],
                "content_class": row["content_class"],
                "length_regime": row["length_regime"],
                "token_count": row["token_count"],
                "prompt_sha256": row["prompt_sha256"],
                "token_ids_sha256": row["token_ids_sha256"],
                "case_sha256": row["case_sha256"],
                "draw_index": row["draw_index"],
                "historical_rejection_attempt": row["historical_rejection_attempt"],
            }
            for row in cases
        ],
        "realized_component_counts": realized_component_counts(cases),
        "realized_component_counts_role": "OBSERVATIONAL_NOT_QUOTAS_OR_STRATA",
        "historical_rejection_rule": plaintext_holdout["historical_rejection_rule"],
        "secret_seed_sha256": plaintext_holdout["secret_seed_sha256"],
        "historical_exclusion_inventory_sha256": plaintext_holdout[
            "historical_exclusion_inventory_sha256"
        ],
        "generator": plaintext_holdout["generator"],
        "generator_sha256": plaintext_holdout["generator_sha256"],
        "tokenizer_json_sha256": plaintext_holdout["tokenizer_json_sha256"],
        "cipher": "CMS EnvelopedData; AES-256-CBC; RSA-3072 recipient",
        "ciphertext_sha256": ciphertext_sha,
        "recipient_certificate_sha256": certificate_sha,
        "unseal_rule": (
            "only after the v5 threshold manifest is committed and the v5 "
            "unseal preflight passes; only by the maintainer's explicit act"
        ),
        "plaintext_retention": "PROHIBITED_IN_REPOSITORY",
    }


def custody_is_satisfied(record: dict[str, Any]) -> bool:
    """Return True only when >=2 independently verified custodians exist."""
    if record.get("holdout_state") != SEALED_NOT_CONSUMED:
        return False
    custodians = record.get("custodians", [])
    if len(custodians) < 2:
        return False
    ids = {c.get("custodian_id") for c in custodians}
    if len(ids) != len(custodians):
        return False
    # Copies of one key are expected. Independence concerns control of the
    # storage boundary, so copied entries on one host/location do not count.
    boundaries = {(c.get("host"), c.get("location")) for c in custodians}
    if len(boundaries) != len(custodians) or any(not host or not location for host, location in boundaries):
        return False
    return all(
        c.get("public_key_match") is True and c.get("verified_date") for c in custodians
    )


def recipient_public_key_der_sha256(certificate: Path) -> str:
    """Derive the recipient public-key DER identity from the public certificate."""
    try:
        public_pem = subprocess.run(
            ["openssl", "x509", "-in", str(certificate), "-pubkey", "-noout"],
            check=True, capture_output=True,
        ).stdout
        public_der = subprocess.run(
            ["openssl", "pkey", "-pubin", "-outform", "DER"], input=public_pem,
            check=True, capture_output=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("recipient certificate public key cannot be derived") from exc
    if not public_der:
        raise ValueError("recipient certificate public key cannot be derived")
    return sha256_bytes(public_der)


def build_custody_record(
    commitment: dict[str, Any], custodians: Sequence[dict[str, Any]], certificate: Path
) -> dict[str, Any]:
    if sha256_file(certificate) != commitment.get("recipient_certificate_sha256"):
        raise ValueError("recipient certificate does not match holdout commitment")
    for custodian in custodians:
        if not is_sha256(custodian.get("private_key_sha256")):
            raise ValueError("custodian entries must pin the private-key SHA-256")
        if custodian.get("public_key_match") is not True:
            raise ValueError("custodian public_key_match must be verified true")
        if custodian.get("verified_date") is None:
            raise ValueError("custodian entries must record a verification date")
    custodian_ids = {custodian.get("custodian_id") for custodian in custodians}
    provisional = {"holdout_state": SEALED_NOT_CONSUMED, "custodians": list(custodians)}
    state = SEALED_NOT_CONSUMED if custody_is_satisfied(provisional) else SEALED_CUSTODY_INCOMPLETE
    record = {
        "schema": V5_HOLDOUT_CUSTODY_SCHEMA,
        "contract_id": CONTRACT_ID,
        "custodians": list(custodians),
        "holdout_ciphertext_sha256": commitment["ciphertext_sha256"],
        "recipient_certificate_sha256": commitment["recipient_certificate_sha256"],
        "recipient_public_key_der_sha256": recipient_public_key_der_sha256(certificate),
        "holdout_state": state,
        "private_material_in_repository": "PROHIBITED",
        "fail_closed_rule": (
            "if fewer than two verified independent custodians exist, holdout_state "
            "must be SEALED_CUSTODY_INCOMPLETE and unseal_authorized must be False; "
            "never regenerate a key for the existing ciphertext"
        ),
        "unseal_authorized": False,
        "custody_history": (
            "Replacement holdout key and secret seed were generated fresh after "
            "the prior CMS round-trip attempt was classified tainted. One local "
            "custodian copy was verified by non-decrypting public-key DER match."
        ),
        "verification_method": (
            "openssl pkey -pubout -outform DER from the private key vs "
            "openssl x509 -pubkey from the committed certificate; "
            "non-decrypting; holdout NOT unsealed"
        ),
    }
    if state == SEALED_CUSTODY_INCOMPLETE:
        record["outstanding_action"] = (
            "Establish and independently verify a second custodian copy of the "
            "recipient private key and secret seed before any unseal preflight or "
            "physical v5 campaign may proceed."
        )
    return record


def main(argv: Sequence[str] | None = None) -> int:
    raise SystemExit("custody metadata is assembled in the sealing session; see TOOLING.md")


if __name__ == "__main__":
    raise SystemExit(main())
