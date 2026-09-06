#!/usr/bin/env python3
"""Generate the deterministic v5 mixture-population corpora (issue #109).

Unlike the v1/v3/v4 generators (fixed cases-per-cell, a balanced design), this
generator draws each case's component IID from the frozen 24-component
mixture declared in ``mixture_population_declaration()`` before generating its
content, per the accepted issue #108 MIXTURE_POPULATION_EXCHANGEABILITY
profile. The underlying per-case prompt construction (lexeme sampling,
exact-token-count retry, round-trip check) is unchanged v1 machinery.

This script does not load an execution runtime or model weights. It is
CPU-only and tokenizer-pure. It must not be used to regenerate any v1/v2/v3/v4
corpus, pool, or holdout.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from generate_issue74_corpora import (
    CONTENT_CLASSES,
    TOKENIZER_SHA256,
    _case,
    generate_prompt,
    sha256_file,
)
from issue74_methodology import LENGTH_REGIMES, canonical_json_bytes, sha256_bytes
from issue109_v5_methodology import (
    CONTRACT_ID,
    V5_CALIBRATION_SCHEMA,
    V5_CALIBRATION_SEED,
    V5_CALIBRATION_CASES,
    V5_HOLDOUT_CASES,
    V5_HOLDOUT_PLAINTEXT_SCHEMA,
    V5_STRESS_POOL_CASES,
    V5_STRESS_POOL_SCHEMA,
    V5_STRESS_POOL_SEED,
    component_stream,
    mixture_population_declaration,
    target_length,
)

V5_DISJOINTNESS_NOTE = (
    "v5 predictive draws are excluded from fixed historical identities only. "
    "Predictive prompt/token collisions are audit-only and are retained as IID "
    "draws; the non-predictive stress pool is deliberately distinct."
)
HISTORICAL_EXCLUSION = Path(__file__).resolve().parents[1] / (
    "docs/qualification/gemma4-12b-it-v5/manifests/historical-exclusion-inventory.json"
)


def realized_component_counts(cases: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return sorted observational component counts from realized draw content.

    The returned values are audit data. They never specify generation quotas
    and must not be used to condition predictive sampling.
    """
    counts = {
        (content_class, tuple(LENGTH_REGIMES[regime_index])): 0
        for content_class, regime_index in mixture_population_declaration_components()
    }
    for case in cases:
        key = (case["content_class"], tuple(case["length_regime"]))
        counts[key] = counts.get(key, 0) + 1
    return [
        {"content_class": content_class, "length_regime": list(regime), "count": count}
        for (content_class, regime), count in sorted(counts.items())
    ]


def mixture_population_declaration_components() -> tuple[tuple[str, int], ...]:
    """Avoid a second public representation of the fixed component universe."""
    from issue109_v5_methodology import mixture_components
    return mixture_components()


def _historical_identities() -> tuple[set[str], str]:
    inventory = json.loads(HISTORICAL_EXCLUSION.read_text(encoding="utf-8"))
    identities = {
        identity["prompt_sha256"]
        for identity in inventory["identities"]
    } | {
        identity["token_ids_sha256"]
        for identity in inventory["identities"]
    }
    return identities, sha256_file(HISTORICAL_EXCLUSION)


def _tokenizer_block() -> dict[str, Any]:
    return {
        "model": "google/gemma-4-12B-it",
        "revision": "707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7",
        "tokenizer_json_sha256": TOKENIZER_SHA256,
        "profile": "raw-text encode(add_special_tokens=False); no chat template",
    }


def _mixture_case(
    seed: str, namespace: str, prefix: str, tokenizer: Any,
    content_class: str, regime_index: int, global_index: int, cell_ordinal: int,
) -> dict[str, Any]:
    low, high = LENGTH_REGIMES[regime_index]
    target = target_length(seed, namespace, regime_index, global_index)
    cell = f"{content_class}:{low}-{high}"
    text, token_ids = generate_prompt(
        tokenizer, seed=seed, namespace=namespace, content_class=content_class,
        cell=cell, index=global_index, target=target,
    )
    identity = {
        "content_class": content_class,
        "length_regime": [low, high],
        "prompt_text": text,
        "token_ids": token_ids,
    }
    return {
        "case_id": f"{prefix}{regime_index + 1:02d}-{CONTENT_CLASSES.index(content_class) + 1:02d}-{cell_ordinal:03d}",
        **identity,
        "token_count": len(token_ids),
        "prompt_sha256": sha256_bytes(text.encode("utf-8")),
        "token_ids_sha256": sha256_bytes(canonical_json_bytes(token_ids)),
        "case_sha256": sha256_bytes(canonical_json_bytes(identity)),
    }


def generate_mixture_cases(
    tokenizer: Any, *, seed: str, namespace: str, prefix: str, count: int,
) -> list[dict[str, Any]]:
    """Draw ``count`` IID mixture-population cases; see mixture_population_declaration()."""
    exclusions, _inventory_sha = _historical_identities()
    cell_ordinals: dict[tuple[str, int], int] = {}
    cases: list[dict[str, Any]] = []
    for index, (initial_class, initial_regime) in component_stream(seed, namespace, count):
        # This is case-local rejection sampling from the frozen target law.
        # A rejection does not change another draw, a corpus seed, or a quota.
        # Each retry redraws the complete component/content realization from the
        # same IID mixture. The accepted attempt remains draw position ``index``.
        attempt = 0
        while True:
            if attempt == 0:
                attempt_namespace = namespace
                content_class, regime_index = initial_class, initial_regime
            else:
                attempt_namespace = f"{namespace}:case:{index}:attempt:{attempt}"
                _unused, (content_class, regime_index) = next(component_stream(
                    seed, attempt_namespace, 1
                ))
            key = (content_class, regime_index)
            next_ordinal = cell_ordinals.get(key, 0) + 1
            case = _mixture_case(
                seed, attempt_namespace, prefix, tokenizer, content_class,
                regime_index, index, next_ordinal,
            )
            if (case["prompt_sha256"] not in exclusions
                    and case["token_ids_sha256"] not in exclusions):
                cell_ordinals[key] = next_ordinal
                case["draw_index"] = index
                case["historical_rejection_attempt"] = attempt
                break
            attempt += 1
            if attempt > 1_000_000:
                raise RuntimeError("historical case-local rejection did not terminate")
        cases.append(case)
    case_ids = {case["case_id"] for case in cases}
    if len(case_ids) != count:
        raise RuntimeError("mixture draw produced a duplicate case_id")
    return cases


def generate_calibration(tokenizer: Any) -> dict[str, Any]:
    cases = generate_mixture_cases(
        tokenizer, seed=V5_CALIBRATION_SEED, namespace="calibration",
        prefix="c109-", count=V5_CALIBRATION_CASES,
    )
    return {
        "schema": V5_CALIBRATION_SCHEMA,
        "contract_id": CONTRACT_ID,
        "generator": "scripts/generate_issue109_corpora.py",
        "generator_sha256": sha256_file(Path(__file__)),
        "tokenizer": _tokenizer_block(),
        "seed": V5_CALIBRATION_SEED,
        "historical_exclusion_inventory_sha256": _historical_identities()[1],
        "mixture_population": mixture_population_declaration(),
        "cases": cases,
        "realized_component_counts": realized_component_counts(cases),
        "realized_component_counts_role": "OBSERVATIONAL_NOT_QUOTAS_OR_STRATA",
        "historical_rejection_rule": (
            "case-local rejection sampling: redraw only the rejected draw from "
            "the frozen IID target generator; no global seed, quota, or component "
            "count is changed"
        ),
        "disjointness": V5_DISJOINTNESS_NOTE,
    }


def generate_stress_pool(tokenizer: Any) -> dict[str, Any]:
    cases = []
    for class_name in CONTENT_CLASSES:
        for regime_index in range(len(LENGTH_REGIMES)):
            for index in range(2):
                cases.append(_case(V5_STRESS_POOL_SEED, "stress", "p109-", tokenizer,
                                   class_name, regime_index, index))
    assert len(cases) == V5_STRESS_POOL_CASES
    return {
        "schema": V5_STRESS_POOL_SCHEMA,
        "contract_id": CONTRACT_ID,
        "generator": "scripts/generate_issue109_corpora.py",
        "generator_sha256": sha256_file(Path(__file__)),
        "tokenizer": _tokenizer_block(),
        "seed": V5_STRESS_POOL_SEED,
        "selection_input_only": "matched-reference-top1-margin",
        "cases_per_cell": 2,
        "cases": cases,
        "disjointness": V5_DISJOINTNESS_NOTE,
    }


def generate_holdout(tokenizer: Any, secret_seed: str) -> dict[str, Any]:
    cases = generate_mixture_cases(
        tokenizer, seed=secret_seed, namespace="v5-sealed-holdout",
        prefix="h109-", count=V5_HOLDOUT_CASES,
    )
    return {
        "schema": V5_HOLDOUT_PLAINTEXT_SCHEMA,
        "contract_id": CONTRACT_ID,
        "generator": "scripts/generate_issue109_corpora.py",
        "generator_sha256": sha256_file(Path(__file__)),
        "secret_seed_sha256": sha256_bytes(secret_seed.encode()),
        "historical_exclusion_inventory_sha256": _historical_identities()[1],
        "tokenizer_json_sha256": TOKENIZER_SHA256,
        "cases": cases,
        "realized_component_counts": realized_component_counts(cases),
        "realized_component_counts_role": "OBSERVATIONAL_NOT_QUOTAS_OR_STRATA",
        "historical_rejection_rule": (
            "case-local rejection sampling: redraw only the rejected draw from "
            "the frozen IID target generator; no global seed, quota, or component "
            "count is changed"
        ),
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
