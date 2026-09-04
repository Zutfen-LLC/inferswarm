#!/usr/bin/env python3
"""Seal or unseal the issue #74 holdout with OpenSSL CMS.

Use ``seal`` before calibration. Do not use ``unseal`` until a threshold
manifest is committed and independently verified.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Sequence

from issue74_methodology import THRESHOLD_SCHEMA, sha256_file


def seal(plaintext: Path, certificate: Path, ciphertext: Path) -> None:
    subprocess.run([
        "openssl", "cms", "-encrypt", "-binary", "-aes-256-cbc", "-outform", "DER",
        "-in", str(plaintext), "-out", str(ciphertext), str(certificate),
    ], check=True)


def unseal(ciphertext: Path, certificate: Path, private_key: Path, plaintext: Path,
           threshold_manifest: Path, expected_threshold_sha256: str) -> None:
    if sha256_file(threshold_manifest) != expected_threshold_sha256:
        raise ValueError("committed threshold manifest SHA-256 mismatch")
    threshold = json.loads(threshold_manifest.read_text())
    if threshold.get("schema") != THRESHOLD_SCHEMA:
        raise ValueError("threshold manifest schema mismatch")
    if threshold.get("holdout_state") != "SEALED_NOT_CONSUMED":
        raise ValueError("threshold manifest is not the pre-holdout artifact")
    subprocess.run([
        "openssl", "cms", "-decrypt", "-binary", "-inform", "DER", "-in", str(ciphertext),
        "-recip", str(certificate), "-inkey", str(private_key), "-out", str(plaintext),
    ], check=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    seal_parser = subparsers.add_parser("seal")
    seal_parser.add_argument("--plaintext", required=True, type=Path)
    seal_parser.add_argument("--certificate", required=True, type=Path)
    seal_parser.add_argument("--ciphertext", required=True, type=Path)
    unseal_parser = subparsers.add_parser("unseal")
    unseal_parser.add_argument("--ciphertext", required=True, type=Path)
    unseal_parser.add_argument("--certificate", required=True, type=Path)
    unseal_parser.add_argument("--private-key", required=True, type=Path)
    unseal_parser.add_argument("--plaintext", required=True, type=Path)
    unseal_parser.add_argument("--threshold-manifest", required=True, type=Path)
    unseal_parser.add_argument("--expected-threshold-sha256", required=True)
    args = parser.parse_args(argv)
    if args.command == "seal":
        seal(args.plaintext, args.certificate, args.ciphertext)
    else:
        unseal(args.ciphertext, args.certificate, args.private_key, args.plaintext,
               args.threshold_manifest, args.expected_threshold_sha256)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
