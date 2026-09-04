#!/usr/bin/env python3
"""Generate the deterministic prompt corpora frozen by InferSwarm issue #74.

The script uses only the pinned tokenizer JSON. It does not load an execution
runtime or model weights.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path
from typing import Any, Sequence

from issue74_methodology import (
    CALIBRATION_CASES_PER_CELL,
    CONTENT_CLASSES,
    CONTRACT_ID,
    LENGTH_REGIMES,
    canonical_json_bytes,
    sha256_bytes,
    sha256_file,
)

TOKENIZER_SHA256 = "cc8d3a0ce36466ccc1278bf987df5f71db1719b9ca6b4118264f45cb627bfe0f"
PUBLIC_CALIBRATION_SEED = "inferswarm-issue-74-calibration-v1"
PUBLIC_STRESS_POOL_SEED = "inferswarm-issue-74-stress-pool-v1"
HISTORICAL_R6_TOKEN_IDS = (
    2, 105, 2364, 107, 46762, 786, 496, 886, 236772, 54554, 12323, 529,
    506, 6073, 529, 74413, 236761, 106, 107, 105, 4368, 107, 100, 45518,
    107, 101,
)

LEXEMES = {
    "ordinary-prose": (
        "amber", "bird", "calm", "drifts", "east", "field", "gentle", "hill",
        "island", "joins", "kind", "light", "morning", "near", "open", "path",
        "quiet", "river", "stone", "travels", "under", "valley", "wind", "young",
    ),
    "source-code-structured-syntax": (
        "def", "if", "else", "return", "while", "for", "in", "value", "item",
        "list", "map", "true", "false", "null", "(", ")", "[", "]", "{", "}",
        ":", ",", "=", "+", "-", "_tmp", "yield", "break", "class", "lambda",
    ),
    "mathematics-numerals": (
        "0", "1", "2", "3", "5", "8", "13", "21", "34", "55", "x", "y", "z",
        "+", "-", "=", "<", ">", "(", ")", "sum", "mean", "ratio", "squared",
        "half", "third", "prime", "vector", "matrix", "delta",
    ),
    "multilingual-text": (
        "bonjour", "monde", "merci", "hola", "mundo", "gracias", "hallo", "welt",
        "danke", "ciao", "mondo", "grazie", "olá", "mundo", "obrigado", "hej",
        "värld", "tack", "namaste", "duniya", "shukriya", "こんにちは", "世界", "ありがとう",
        "안녕", "세계", "감사", "مرحبا", "العالم", "شكرا", "привет", "мир", "спасибо",
    ),
    "repetitive-low-entropy": (
        "ha", "ha", "ha", "la", "la", "na", "na", "echo", "echo", "again",
        "again", "tick", "tock", "zero", "zero", "same", "same", "loop", "loop",
    ),
    "punctuation-whitespace-rare-high-entropy": (
        "!", "?", "#", "$", "%", "&", "*", "+", "-", "/", ":", ";", "<", "=",
        ">", "@", "[", "]", "^", "_", "{", "|", "}", "~", "§", "¶", "※", "◇",
        "Ж", "λ", "猫", "Ω", "7f", "a9", "0x", "::", "//", "\\t",
    ),
}


def _rng(seed: str, namespace: str, content_class: str, cell: str, index: int, attempt: int) -> random.Random:
    material = "\0".join((seed, namespace, content_class, cell, str(index), str(attempt))).encode()
    return random.Random(int.from_bytes(hashlib.sha256(material).digest(), "big"))


def _raw_candidate(
    seed: str, namespace: str, content_class: str, cell: str, index: int, target: int, attempt: int
) -> str:
    rng = _rng(seed, namespace, content_class, cell, index, attempt)
    lexemes = LEXEMES[content_class]
    count = target * 4 + 16
    words = [lexemes[rng.randrange(len(lexemes))] for _ in range(count)]
    return " ".join(words)


def generate_prompt(tokenizer: Any, *, seed: str, namespace: str, content_class: str,
                    cell: str, index: int, target: int) -> tuple[str, list[int]]:
    """Generate one unique prompt with an exact token count."""
    for attempt in range(512):
        raw = _raw_candidate(seed, namespace, content_class, cell, index, target, attempt)
        long_ids = tokenizer.encode(raw, add_special_tokens=False).ids
        if len(long_ids) < target:
            continue
        ids = long_ids[:target]
        text = tokenizer.decode(ids, skip_special_tokens=False)
        round_trip = tokenizer.encode(text, add_special_tokens=False).ids
        if round_trip == ids and tuple(ids) != HISTORICAL_R6_TOKEN_IDS:
            return text, ids
    raise RuntimeError(f"could not generate exact prompt for {content_class}/{cell}/{index}")


def _case(seed: str, namespace: str, prefix: str, tokenizer: Any, content_class: str,
          regime_index: int, index: int) -> dict[str, Any]:
    low, high = LENGTH_REGIMES[regime_index]
    target = low + index % (high - low + 1)
    cell = f"{content_class}:{low}-{high}"
    text, token_ids = generate_prompt(
        tokenizer, seed=seed, namespace=namespace, content_class=content_class,
        cell=cell, index=index, target=target,
    )
    identity = {
        "content_class": content_class,
        "length_regime": [low, high],
        "prompt_text": text,
        "token_ids": token_ids,
    }
    return {
        "case_id": f"{prefix}{regime_index + 1:02d}-{CONTENT_CLASSES.index(content_class) + 1:02d}-{index + 1:02d}",
        **identity,
        "token_count": len(token_ids),
        "prompt_sha256": sha256_bytes(text.encode("utf-8")),
        "token_ids_sha256": sha256_bytes(canonical_json_bytes(token_ids)),
        "case_sha256": sha256_bytes(canonical_json_bytes(identity)),
    }


def generate_public(tokenizer: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    calibration = []
    stress_pool = []
    for class_name in CONTENT_CLASSES:
        for regime_index in range(len(LENGTH_REGIMES)):
            for index in range(CALIBRATION_CASES_PER_CELL):
                calibration.append(_case(PUBLIC_CALIBRATION_SEED, "calibration", "c74-", tokenizer,
                                         class_name, regime_index, index))
            for index in range(2):
                stress_pool.append(_case(PUBLIC_STRESS_POOL_SEED, "stress", "p74-", tokenizer,
                                         class_name, regime_index, index))
    common = {
        "contract_id": CONTRACT_ID,
        "generator": "scripts/generate_issue74_corpora.py",
        "generator_sha256": sha256_file(Path(__file__)),
        "tokenizer": {
            "model": "google/gemma-4-12B-it",
            "revision": "707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7",
            "tokenizer_json_sha256": TOKENIZER_SHA256,
            "profile": "raw-text encode(add_special_tokens=False); no chat template",
        },
    }
    return (
        {"schema": "inferswarm.issue74.calibration-corpus/1", **common,
         "seed": PUBLIC_CALIBRATION_SEED, "cases_per_cell": 24, "cases": calibration},
        {"schema": "inferswarm.issue74.margin-stress-pool/1", **common,
         "seed": PUBLIC_STRESS_POOL_SEED, "selection_input_only": "matched-reference-top1-margin",
         "cases_per_cell": 2, "cases": stress_pool},
    )


def generate_holdout(tokenizer: Any, secret_seed: str) -> dict[str, Any]:
    cases = []
    for class_name in CONTENT_CLASSES:
        for regime_index in range(len(LENGTH_REGIMES)):
            cases.append(_case(secret_seed, "sealed-holdout", "h74-", tokenizer,
                               class_name, regime_index, 0))
    return {
        "schema": "inferswarm.issue74.sealed-holdout/1",
        "contract_id": CONTRACT_ID,
        "generator": "scripts/generate_issue74_corpora.py",
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
        calibration, stress = generate_public(tokenizer)
        args.calibration_out.write_bytes(canonical_json_bytes(calibration))
        args.stress_pool_out.write_bytes(canonical_json_bytes(stress))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
