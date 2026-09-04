#!/usr/bin/env python3
"""Generate the deterministic v2 stress pool frozen by InferSwarm issue #76 v2.

Issue #74/v1 stress-pool machinery, unchanged (same lexemes, same RNG
construction, same exact-token-count loop, same tokenizer profile) — only the
seed, case-id prefix, schema version, and eligibility contract differ.

This script does not load an execution runtime or model weights. It is
CPU-only and tokenizer-pure. It must not be used to regenerate the v1 pool
or the v1/v2 holdouts.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Sequence

from generate_issue74_corpora import (
    CONTENT_CLASSES,
    CONTRACT_ID,
    LENGTH_REGIMES,
    TOKENIZER_SHA256,
    _case,
    sha256_bytes,
    sha256_file,
)
from issue74_methodology import canonical_json_bytes

V2_STRESS_POOL_SEED = "inferswarm-issue-76-stress-pool-v2"


def generate_v2_pool(tokenizer: Any) -> dict[str, Any]:
    cases = []
    for class_name in CONTENT_CLASSES:
        for regime_index in range(len(LENGTH_REGIMES)):
            for index in range(2):
                cases.append(_case(V2_STRESS_POOL_SEED, "stress", "p76-", tokenizer,
                                   class_name, regime_index, index))
    return {
        "schema": "inferswarm.issue76.margin-stress-pool/2",
        "contract_id": CONTRACT_ID,
        "generator": "scripts/generate_issue76_stress_pool_v2.py",
        "generator_sha256": sha256_file(Path(__file__)),
        "tokenizer": {
            "model": "google/gemma-4-12B-it",
            "revision": "707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7",
            "tokenizer_json_sha256": TOKENIZER_SHA256,
            "profile": "raw-text encode(add_special_tokens=False); no chat template",
        },
        "seed": V2_STRESS_POOL_SEED,
        "selection_input_only": "matched-reference-top1-margin",
        "cases_per_cell": 2,
        "cases": cases,
        "provenance": {
            "v1_pool_reuse_forbidden": True,
            "v1_observed_margins_forbidden_as_selection_input": True,
            "supersedes": "docs/qualification/gemma4-12b-it-v1/manifests/margin-stress-pool.json",
            "reason": (
                "v1 selector treated any nonpositive-margin pool case as fatal to "
                "the entire selection; v2 defines prospective positive eligibility"
            ),
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tokenizer-json", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    if sha256_file(args.tokenizer_json) != TOKENIZER_SHA256:
        raise ValueError("tokenizer.json SHA-256 mismatch")
    from tokenizers import Tokenizer
    tokenizer = Tokenizer.from_file(str(args.tokenizer_json))
    pool = generate_v2_pool(tokenizer)
    args.out.write_bytes(canonical_json_bytes(pool))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
