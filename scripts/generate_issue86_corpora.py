#!/usr/bin/env python3
"""Generate the deterministic v3 corpora frozen by InferSwarm issue #86.

v1 corpus-generation machinery, unchanged (same lexemes, same RNG
construction, same exact-token-count loop, same tokenizer profile) — only
the seeds, case-id prefixes (c86-/p86-/h86-), schema versions, and the v3
disjointness contract differ.

This script does not load an execution runtime or model weights. It is
CPU-only and tokenizer-pure. It must not be used to regenerate any v1/v2
corpus, pool, or holdout.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Sequence

from generate_issue74_corpora import (
    CALIBRATION_CASES_PER_CELL,
    CONTENT_CLASSES,
    CONTRACT_ID,
    LENGTH_REGIMES,
    TOKENIZER_SHA256,
    _case,
    sha256_file,
)
from issue74_methodology import canonical_json_bytes
from issue86_v3_methodology import (
    V3_CALIBRATION_SCHEMA,
    V3_CALIBRATION_SEED,
    V3_HOLDOUT_CASES,
    V3_HOLDOUT_PLAINTEXT_SCHEMA,
    V3_STRESS_POOL_CASES,
    V3_STRESS_POOL_SCHEMA,
    V3_STRESS_POOL_SEED,
)

V3_DISJOINTNESS_NOTE = (
    "v3 artifacts are mechanically disjoint by prompt_sha256 and "
    "token_ids_sha256 from: the c74-* calibration corpus, the v1 stress "
    "pool, the v2 stress pool, the historical #74 holdout public "
    "commitment, and the fresh v3 stress pool / v3 holdout commitment"
)


def generate_calibration(tokenizer: Any) -> dict[str, Any]:
    cases = []
    for class_name in CONTENT_CLASSES:
        for regime_index in range(len(LENGTH_REGIMES)):
            for index in range(CALIBRATION_CASES_PER_CELL):
                cases.append(_case(V3_CALIBRATION_SEED, "calibration", "c86-", tokenizer,
                                   class_name, regime_index, index))
    return {
        "schema": V3_CALIBRATION_SCHEMA,
        "contract_id": CONTRACT_ID,
        "generator": "scripts/generate_issue86_corpora.py",
        "generator_sha256": sha256_file(Path(__file__)),
        "tokenizer": {
            "model": "google/gemma-4-12B-it",
            "revision": "707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7",
            "tokenizer_json_sha256": TOKENIZER_SHA256,
            "profile": "raw-text encode(add_special_tokens=False); no chat template",
        },
        "seed": V3_CALIBRATION_SEED,
        "cases_per_cell": CALIBRATION_CASES_PER_CELL,
        "cases": cases,
        "disjointness": V3_DISJOINTNESS_NOTE,
    }


def generate_stress_pool(tokenizer: Any) -> dict[str, Any]:
    cases = []
    for class_name in CONTENT_CLASSES:
        for regime_index in range(len(LENGTH_REGIMES)):
            for index in range(2):
                cases.append(_case(V3_STRESS_POOL_SEED, "stress", "p86-", tokenizer,
                                   class_name, regime_index, index))
    assert len(cases) == V3_STRESS_POOL_CASES
    return {
        "schema": V3_STRESS_POOL_SCHEMA,
        "contract_id": CONTRACT_ID,
        "generator": "scripts/generate_issue86_corpora.py",
        "generator_sha256": sha256_file(Path(__file__)),
        "tokenizer": {
            "model": "google/gemma-4-12B-it",
            "revision": "707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7",
            "tokenizer_json_sha256": TOKENIZER_SHA256,
            "profile": "raw-text encode(add_special_tokens=False); no chat template",
        },
        "seed": V3_STRESS_POOL_SEED,
        "selection_input_only": "matched-reference-top1-margin",
        "cases_per_cell": 2,
        "cases": cases,
        "disjointness": V3_DISJOINTNESS_NOTE,
    }


def generate_holdout(tokenizer: Any, secret_seed: str) -> dict[str, Any]:
    cases = []
    for class_name in CONTENT_CLASSES:
        for regime_index in range(len(LENGTH_REGIMES)):
            cases.append(_case(secret_seed, "v3-sealed-holdout", "h86-", tokenizer,
                               class_name, regime_index, 0))
    assert len(cases) == V3_HOLDOUT_CASES
    from issue86_v3_methodology import sha256_bytes
    return {
        "schema": V3_HOLDOUT_PLAINTEXT_SCHEMA,
        "contract_id": CONTRACT_ID,
        "generator": "scripts/generate_issue86_corpora.py",
        "generator_sha256": sha256_file(Path(__file__)),
        "secret_seed_sha256": sha256_bytes(secret_seed.encode()),
        "tokenizer_json_sha256": TOKENIZER_SHA256,
        "cases": cases,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tokenizer-json", required=True, type=Path)
    parser.add_argument("--calibration-out", type=Path)
    parser.add_argument("--stress-pool-out", type=Path)
    parser.add_argument("--holdout-out", type=Path)
    parser.add_argument("--holdout-secret-seed")
    args = parser.parse_args(argv)
    if sha256_file(args.tokenizer_json) != TOKENIZER_SHA256:
        raise ValueError("tokenizer.json SHA-256 mismatch")
    from tokenizers import Tokenizer
    tokenizer = Tokenizer.from_file(str(args.tokenizer_json))
    if args.holdout_out:
        if not args.holdout_secret_seed or args.calibration_out or args.stress_pool_out:
            parser.error("holdout generation requires only --holdout-out and --holdout-secret-seed")
        args.holdout_out.write_bytes(canonical_json_bytes(generate_holdout(tokenizer, args.holdout_secret_seed)))
    else:
        if not args.calibration_out or not args.stress_pool_out or args.holdout_secret_seed:
            parser.error("public generation requires --calibration-out and --stress-pool-out")
        args.calibration_out.write_bytes(canonical_json_bytes(generate_calibration(tokenizer)))
        args.stress_pool_out.write_bytes(canonical_json_bytes(generate_stress_pool(tokenizer)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
