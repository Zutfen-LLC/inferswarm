#!/usr/bin/env python3
"""Generate the deterministic Qwen3.8 Vulkan v1 corpora (issue #237).

Fresh Qwen-specific IID mixture-population draws (per
``issue237_methodology.mixture_population_declaration``), tokenized with the
pinned Qwen tokenizer JSON reconstructed from the accepted GGUF header bytes.

CPU-only and tokenizer-pure: no execution runtime, no model weights, no
accelerator queries. Public mode emits the calibration corpus and the
non-predictive stress pool; holdout mode reads a secret seed from a file or
fd and NEVER writes plaintext inside the repository.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path
from typing import Any

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

from issue237_build_exclusion_inventory import (  # noqa: E402
    build_inventory,
    historical_identity_set,
)
from issue237_methodology import (  # noqa: E402
    CALIBRATION_CASES,
    CALIBRATION_SCHEMA,
    CALIBRATION_SEED,
    CONTENT_CLASSES,
    HOLDOUT_CASES,
    HOLDOUT_NAMESPACE,
    HOLDOUT_PLAINTEXT_SCHEMA,
    LENGTH_REGIMES,
    LEXEMES,
    MIXTURE_COMPONENTS,
    STRESS_POOL_CASES,
    STRESS_POOL_SCHEMA,
    STRESS_POOL_SEED,
    STRESS_SELECTED_CASES,
    TOKENIZER_ASSET_PATH,
    TOKENIZER_JSON_SHA256,
    component_stream,
    mixture_population_declaration,
    realized_component_counts,
    statistical_design,
    target_length,
)
from issue74_methodology import canonical_json_bytes, sha256_bytes  # noqa: E402

REPO = Path(__file__).resolve().parents[1]

HISTORICAL_REJECTION_RULE = (
    "for each draw index, select exactly one uniform 1/24 component and "
    "exactly one uniform target length in its regime; freeze both; on a "
    "historical identity collision, increment only a case-local prompt "
    "realization attempt nonce and retry prompt realization until accepted; "
    "never redraw the component or target length, and never balance quotas"
)
DISJOINTNESS_NOTE = (
    "Qwen v1 predictive draws are excluded from the fixed historical "
    "identity inventory only. Fresh predictive prompt/token collisions are "
    "audit-only and retained as IID draws; the non-predictive stress pool "
    "is deliberately distinct."
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class GenerationError(RuntimeError):
    pass


def _rng(seed: str, namespace: str, content_class: str, cell: str,
         index: int, attempt: int) -> random.Random:
    material = "\0".join(
        (seed, namespace, content_class, cell, str(index), str(attempt))
    ).encode()
    return random.Random(int.from_bytes(hashlib.sha256(material).digest(), "big"))


def _raw_candidate(seed: str, namespace: str, content_class: str, cell: str,
                   index: int, target: int, attempt: int) -> str:
    rng = _rng(seed, namespace, content_class, cell, index, attempt)
    lexemes = LEXEMES[content_class]
    count = target * 4 + 16
    words = [lexemes[rng.randrange(len(lexemes))] for _ in range(count)]
    return " ".join(words)


def generate_prompt(tokenizer: Any, *, seed: str, namespace: str,
                    content_class: str, cell: str, index: int,
                    target: int) -> tuple[str, list[int]]:
    """Generate one unique prompt with an exact rendered token count."""
    for attempt in range(512):
        raw = _raw_candidate(seed, namespace, content_class, cell, index, target, attempt)
        long_ids = tokenizer.encode(raw, add_special_tokens=False).ids
        if len(long_ids) < target:
            continue
        ids = long_ids[:target]
        text = tokenizer.decode(ids, skip_special_tokens=False)
        round_trip = tokenizer.encode(text, add_special_tokens=False).ids
        if round_trip == ids:
            return text, ids
    raise GenerationError(
        f"could not generate exact prompt for {content_class}/{cell}/{index}"
    )


def _case_identity(content_class: str, regime_index: int, text: str,
                   token_ids: list[int]) -> dict[str, Any]:
    return {
        "content_class": content_class,
        "length_regime_index": regime_index,
        "length_regime": list(LENGTH_REGIMES[regime_index]),
        "prompt_text": text,
        "token_ids": token_ids,
    }


def _case_row(case_id: str, identity: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": case_id,
        **identity,
        "token_count": len(identity["token_ids"]),
        "prompt_sha256": sha256_bytes(identity["prompt_text"].encode("utf-8")),
        "token_ids_sha256": sha256_bytes(
            canonical_json_bytes(identity["token_ids"])
        ),
        "case_sha256": sha256_bytes(canonical_json_bytes(identity)),
    }


def _tokenizer_block() -> dict[str, str]:
    return {
        "path": TOKENIZER_ASSET_PATH,
        "sha256": TOKENIZER_JSON_SHA256,
        "note": "reconstructed from accepted GGUF member-1 header bytes; fixture-validated",
    }


def _mixture_case(seed: str, namespace: str, prefix: str, tokenizer: Any,
                  content_class: str, regime_index: int, target: int,
                  index: int, ordinal: int) -> dict[str, Any]:
    low, high = LENGTH_REGIMES[regime_index]
    cell = f"{content_class}:{low}-{high}"
    text, token_ids = generate_prompt(
        tokenizer, seed=seed, namespace=namespace, content_class=content_class,
        cell=cell, index=index, target=target,
    )
    case_id = f"{prefix}{regime_index + 1:02d}-{CONTENT_CLASSES.index(content_class) + 1:02d}-{ordinal:03d}"
    return _case_row(case_id, _case_identity(content_class, regime_index, text, token_ids))


def generate_mixture_cases(tokenizer: Any, *, seed: str, namespace: str,
                           prefix: str, count: int,
                           exclusions: set[str]) -> list[dict[str, Any]]:
    """Draw ``count`` IID mixture-population cases with conditional rejection."""
    cell_ordinals: dict[tuple[str, int], int] = {}
    cases: list[dict[str, Any]] = []
    for index, (content_class, regime_index) in component_stream(seed, namespace, count):
        if (content_class, regime_index) not in [
            (c, r) for c, r in
            [(cc, ri) for cc in CONTENT_CLASSES for ri in range(len(LENGTH_REGIMES))]
        ]:
            raise GenerationError("component outside the frozen universe")
        target = target_length(seed, namespace, regime_index, index)
        attempt = 0
        while True:
            if attempt == 0:
                attempt_namespace = namespace
            else:
                attempt_namespace = f"{namespace}:case:{index}:attempt:{attempt}"
            key = (content_class, regime_index)
            next_ordinal = cell_ordinals.get(key, 0) + 1
            case = _mixture_case(
                seed, attempt_namespace, prefix, tokenizer, content_class,
                regime_index, target, index, next_ordinal,
            )
            if (case["prompt_sha256"] not in exclusions
                    and case["token_ids_sha256"] not in exclusions):
                cell_ordinals[key] = next_ordinal
                case["draw_index"] = index
                case["historical_rejection_attempt"] = attempt
                break
            attempt += 1
            if attempt > 1_000_000:
                raise GenerationError("historical rejection did not terminate")
        cases.append(case)
    case_ids = {case["case_id"] for case in cases}
    if len(case_ids) != count:
        raise GenerationError("mixture draw produced a duplicate case_id")
    return cases


def generate_stress_pool_cases(tokenizer: Any, exclusions: set[str]) -> list[dict[str, Any]]:
    """48 deterministic reference-input stress cases (2 per component).

    Non-predictive: selected WITHOUT candidate influence (margin-based
    selection happens later from matched reference execution only), and
    contributes zero predictive sample count.
    """
    cases: list[dict[str, Any]] = []
    for class_index, class_name in enumerate(CONTENT_CLASSES):
        for regime_index in range(len(LENGTH_REGIMES)):
            for index in range(2):
                low, high = LENGTH_REGIMES[regime_index]
                target = low + index % (high - low + 1)
                case = _mixture_case(
                    STRESS_POOL_SEED, "stress", "p237-", tokenizer, class_name,
                    regime_index, target, index, index + 1,
                )
                if (case["prompt_sha256"] in exclusions
                        or case["token_ids_sha256"] in exclusions):
                    raise GenerationError(
                        "stress-pool case collided with historical identities"
                    )
                cases.append(case)
    if len(cases) != STRESS_POOL_CASES:
        raise GenerationError("stress pool size mismatch")
    return cases


def load_tokenizer(tokenizer_path: Path) -> Any:
    if sha256_file(tokenizer_path) != TOKENIZER_JSON_SHA256:
        raise GenerationError("tokenizer.json SHA-256 mismatch")
    from tokenizers import Tokenizer  # noqa: PLC0415
    return Tokenizer.from_file(str(tokenizer_path))


def generate_calibration(tokenizer: Any, exclusions: set[str]) -> dict[str, Any]:
    cases = generate_mixture_cases(
        tokenizer, seed=CALIBRATION_SEED, namespace="calibration",
        prefix="c237-", count=CALIBRATION_CASES, exclusions=exclusions,
    )
    return {
        "schema": CALIBRATION_SCHEMA,
        "generator": "scripts/issue237_generate_corpora.py",
        "generator_sha256": sha256_file(Path(__file__)),
        "tokenizer": _tokenizer_block(),
        "seed": CALIBRATION_SEED,
        "mixture_population": mixture_population_declaration(),
        "statistical_design": statistical_design(),
        "cases": cases,
        "realized_component_counts": realized_component_counts(cases),
        "realized_component_counts_role": "OBSERVATIONAL_NOT_QUOTAS_OR_STRATA",
        "historical_rejection_rule": HISTORICAL_REJECTION_RULE,
        "disjointness": DISJOINTNESS_NOTE,
    }


def generate_stress_pool(tokenizer: Any, exclusions: set[str]) -> dict[str, Any]:
    cases = generate_stress_pool_cases(tokenizer, exclusions)
    return {
        "schema": STRESS_POOL_SCHEMA,
        "generator": "scripts/issue237_generate_corpora.py",
        "generator_sha256": sha256_file(Path(__file__)),
        "tokenizer": _tokenizer_block(),
        "seed": STRESS_POOL_SEED,
        "selection_input_only": "matched-reference-top1-margin (frozen pre-candidate)",
        "cases": cases,
        "stress_role": "NON_PREDICTIVE; zero predictive sample count",
        "disjointness": DISJOINTNESS_NOTE,
    }


def generate_holdout(tokenizer: Any, secret_seed: str,
                     exclusions: set[str]) -> dict[str, Any]:
    cases = generate_mixture_cases(
        tokenizer, seed=secret_seed, namespace=HOLDOUT_NAMESPACE,
        prefix="h237-", count=HOLDOUT_CASES, exclusions=exclusions,
    )
    return {
        "schema": HOLDOUT_PLAINTEXT_SCHEMA,
        "generator": "scripts/issue237_generate_corpora.py",
        "generator_sha256": sha256_file(Path(__file__)),
        "secret_seed_sha256": sha256_bytes(secret_seed.encode()),
        "tokenizer": _tokenizer_block(),
        "cases": cases,
        "realized_component_counts": realized_component_counts(cases),
        "realized_component_counts_role": "OBSERVATIONAL_NOT_QUOTAS_OR_STRATA",
        "historical_rejection_rule": HISTORICAL_REJECTION_RULE,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tokenizer-json", required=True, type=Path)
    parser.add_argument("--calibration-out", type=Path)
    parser.add_argument("--stress-pool-out", type=Path)
    parser.add_argument("--holdout-out", type=Path)
    parser.add_argument("--holdout-secret-seed-file", type=Path)
    parser.add_argument("--holdout-secret-seed-fd", type=int)
    args = parser.parse_args(argv)

    tokenizer = load_tokenizer(args.tokenizer_json)
    exclusions = historical_identity_set(build_inventory())

    if args.holdout_out:
        inputs = [
            bool(args.holdout_secret_seed_file),
            args.holdout_secret_seed_fd is not None,
        ]
        if sum(inputs) != 1 or args.calibration_out or args.stress_pool_out:
            parser.error(
                "holdout generation requires exactly one secret-seed input "
                "and no public outputs"
            )
        if args.holdout_secret_seed_file:
            secret_seed = args.holdout_secret_seed_file.read_text(
                encoding="utf-8"
            ).strip()
        else:
            secret_seed = (
                open(args.holdout_secret_seed_fd, "r", encoding="utf-8").read().strip()
            )
        args.holdout_out.write_bytes(
            canonical_json_bytes(generate_holdout(tokenizer, secret_seed, exclusions))
        )
    else:
        if not args.calibration_out or not args.stress_pool_out:
            parser.error("public generation requires --calibration-out and --stress-pool-out")
        args.calibration_out.write_bytes(
            canonical_json_bytes(generate_calibration(tokenizer, exclusions))
        )
        args.stress_pool_out.write_bytes(
            canonical_json_bytes(generate_stress_pool(tokenizer, exclusions))
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
