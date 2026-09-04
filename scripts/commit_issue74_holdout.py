#!/usr/bin/env python3
"""Create the public commitment for a newly sealed issue #74 holdout."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from issue74_methodology import CONTRACT_ID, CONTENT_CLASSES, LENGTH_REGIMES, canonical_json_bytes, sha256_file


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plaintext", required=True, type=Path)
    parser.add_argument("--ciphertext", required=True, type=Path)
    parser.add_argument("--certificate", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    sealed = json.loads(args.plaintext.read_text())
    if sealed.get("schema") != "inferswarm.issue74.sealed-holdout/1":
        raise ValueError("holdout schema mismatch")
    cases = sealed.get("cases")
    expected_cells = {(name, bounds) for name in CONTENT_CLASSES for bounds in LENGTH_REGIMES}
    observed_cells = {(row["content_class"], tuple(row["length_regime"])) for row in cases}
    if len(cases) != 24 or observed_cells != expected_cells:
        raise ValueError("holdout must contain exactly one case in each of 24 cells")
    commitment = {
        "schema": "inferswarm.issue74.sealed-holdout-commitment/1",
        "contract_id": CONTRACT_ID,
        "state": "SEALED_BEFORE_CALIBRATION",
        "case_count": 24,
        "cells": [{
            "case_id": row["case_id"],
            "content_class": row["content_class"],
            "length_regime": row["length_regime"],
            "token_count": row["token_count"],
            "prompt_sha256": row["prompt_sha256"],
            "token_ids_sha256": row["token_ids_sha256"],
            "case_sha256": row["case_sha256"],
        } for row in cases],
        "secret_seed_sha256": sealed["secret_seed_sha256"],
        "generator": sealed["generator"],
        "generator_sha256": sealed["generator_sha256"],
        "tokenizer_json_sha256": sealed["tokenizer_json_sha256"],
        "cipher": "CMS EnvelopedData; AES-256-CBC; RSA-3072 recipient",
        "ciphertext_sha256": sha256_file(args.ciphertext),
        "recipient_certificate_sha256": sha256_file(args.certificate),
        "unseal_rule": "only after the threshold manifest is committed and independently verified",
        "plaintext_retention": "PROHIBITED_IN_REPOSITORY",
    }
    args.out.write_bytes(canonical_json_bytes(commitment))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
