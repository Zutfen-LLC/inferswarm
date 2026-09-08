#!/usr/bin/env python3
"""Issue #117 deterministic checkpoint-authority validator (CPU-only).

Companion to ``evidence/checkpoint-authority-provenance.json``. The recovered
historical rule is:

    checkpoint authority sha256 == sha256(model.safetensors bytes)

i.e. the SHA-256 of the single ``model.safetensors`` file at the root of the
checkpoint repository — the same value the Hugging Face hub pins as the LFS
oid of that file at revision ``707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7``.
It is not a directory-tree digest, not a manifest construction, and not a
config SHA.

This module never hardcodes the accepted digest as the source of truth for a
candidate repository: the expected value is loaded from the retained
authority evidence (byte-pinned files, verified against their recorded
SHA-256), then mechanically compared against a full-file SHA-256 computed
over the candidate's actual bytes. Altered bytes cannot pass. A sidecar that
merely repeats the accepted string proves nothing and is ignored.

Pure stdlib. No model parsing, no CUDA, no network.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]

PROVENANCE_RELATIVE = Path(
    "docs/implementation/r6-successor-dense-full-integration-117/evidence/"
    "checkpoint-authority-provenance.json")

#: the single authority-bearing object named by the recovered rule
CHECKPOINT_WEIGHTS_FILE = "model.safetensors"
#: accepted byte length of the authority-bearing object (secondary check)
ACCEPTED_WEIGHTS_SIZE = 23919549408


class CheckpointAuthorityError(RuntimeError):
    """The candidate repository cannot prove the accepted checkpoint identity."""


def _chunked_sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(8 * 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            total += len(chunk)
    return digest.hexdigest(), total


def load_provenance_record(root: Path | None = None) -> dict[str, Any]:
    """Load and structurally validate the retained provenance evidence."""
    root = Path(root or ROOT)
    path = root / PROVENANCE_RELATIVE
    if not path.is_file():
        raise CheckpointAuthorityError(f"provenance record missing: {path}")
    document = json.loads(path.read_text())
    if document.get("schema") != "inferswarm.issue117.checkpoint-authority-provenance/1":
        raise CheckpointAuthorityError("provenance record schema mismatch")
    if document.get("classification") != "V5_CHECKPOINT_AUTHORITY_PROVENANCE_RECOVERED":
        raise CheckpointAuthorityError(
            "provenance record is not the recovered-authority record")
    rule = document.get("derivation_rule", {})
    if rule.get("algorithm") != "sha256" or CHECKPOINT_WEIGHTS_FILE not in str(
            rule.get("input", "")):
        raise CheckpointAuthorityError(
            "provenance record does not state the recovered derivation rule")
    return document


def accepted_checkpoint_authority(root: Path | None = None) -> str:
    """The accepted authority, loaded from the retained provenance record.

    Falls back to the retained V5 authority evidence files (the same loader
    the applicability audit uses) so the expected value always comes from
    accepted retained evidence, never from caller input.
    """
    document = load_provenance_record(root)
    return document["subject"]["checkpoint_authority_sha256"]


def validate_checkpoint_repository(
        checkpoint_root: Path, *, expected_sha256: str | None = None,
        root: Path | None = None,
        expected_size: int = ACCEPTED_WEIGHTS_SIZE) -> dict[str, Any]:
    """Fail-closed validation of a checkpoint repository against the rule.

    Hashes the candidate's actual ``model.safetensors`` bytes in full and
    requires: exact accepted digest, exact accepted byte length, and a plain
    regular file (no symlink indirection of the authority-bearing object).
    Returns the mechanical record; raises on any failure.
    """
    checkpoint_root = Path(checkpoint_root)
    if expected_sha256 is None:
        expected_sha256 = accepted_checkpoint_authority(root)
    weights = checkpoint_root / CHECKPOINT_WEIGHTS_FILE
    if not checkpoint_root.is_dir():
        raise CheckpointAuthorityError(
            f"checkpoint repository inaccessible: {checkpoint_root}")
    if not weights.exists():
        raise CheckpointAuthorityError(
            f"checkpoint repository has no {CHECKPOINT_WEIGHTS_FILE}")
    if weights.is_symlink():
        raise CheckpointAuthorityError(
            f"{CHECKPOINT_WEIGHTS_FILE} is a symlink; the authority-bearing "
            "object must be a plain regular file at the repository root")
    observed_sha256, observed_size = _chunked_sha256(weights)
    if observed_size != expected_size:
        raise CheckpointAuthorityError(
            f"{CHECKPOINT_WEIGHTS_FILE} byte length {observed_size} != accepted "
            f"{expected_size}")
    if observed_sha256 != expected_sha256:
        raise CheckpointAuthorityError(
            f"{CHECKPOINT_WEIGHTS_FILE} sha256 {observed_sha256} does not derive "
            f"the accepted checkpoint authority {expected_sha256}")
    return {
        "schema": "inferswarm.issue117.checkpoint-authority-validation/1",
        "rule": "sha256(model.safetensors bytes)",
        "checkpoint_root": str(checkpoint_root),
        "weights_file": CHECKPOINT_WEIGHTS_FILE,
        "weights_size_bytes": observed_size,
        "weights_sha256": observed_sha256,
        "expected_authority_sha256": expected_sha256,
        "derivation": "MATCH" if observed_sha256 == expected_sha256 else "MISMATCH",
        "status": "CHECKPOINT_AUTHORITY_DERIVED",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint_root", type=Path,
                        help="checkpoint repository to validate "
                             "(e.g. /srv/models/gemma-r6)")
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--json", action="store_true",
                        help="print the mechanical validation record")
    args = parser.parse_args(argv)
    try:
        record = validate_checkpoint_repository(
            args.checkpoint_root, root=args.repo_root)
    except CheckpointAuthorityError as error:
        print(f"CHECKPOINT_AUTHORITY_INVALID: {error}")
        return 1
    if args.json:
        print(json.dumps(record, indent=2, sort_keys=True))
    else:
        print("CHECKPOINT_AUTHORITY_DERIVED")
        print(f"  rule: sha256(model.safetensors bytes)")
        print(f"  root: {record['checkpoint_root']}")
        print(f"  size: {record['weights_size_bytes']}")
        print(f"  sha256: {record['weights_sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
