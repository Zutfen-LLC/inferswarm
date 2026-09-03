#!/usr/bin/env python3
"""CPU-only reducers and derivations for InferSwarm issue #74.

This module does not import a model runtime. It does not inspect holdout
content. It fails closed when an input contains holdout data or incomplete
calibration evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Sequence

CONTRACT_ID = "inferswarm.gemma4-heterogeneous-numerical-equivalence/1"
METHODOLOGY_SCHEMA = "inferswarm.issue74.methodology/1"
CALIBRATION_SCHEMA = "inferswarm.issue74.calibration-summary/1"
THRESHOLD_SCHEMA = "inferswarm.issue74.threshold-manifest/1"

CONTENT_CLASSES = (
    "ordinary-prose",
    "source-code-structured-syntax",
    "mathematics-numerals",
    "multilingual-text",
    "repetitive-low-entropy",
    "punctuation-whitespace-rare-high-entropy",
)
LENGTH_REGIMES = ((4, 8), (24, 28), (36, 40), (52, 56))
FAMILIES = (
    "local-bf16-backend-operation-output",
    "hidden-residual-stream",
    "final-normalized-hidden-state",
    "bf16-logits",
    "fp32-consumer-logits",
)
METRICS = ("max-absolute-difference", "rms-difference", "p99-absolute-error")
ENVELOPES = tuple(f"{family}:{metric}" for family in FAMILIES for metric in METRICS)

POPULATION_CONTENT = 0.99
FAMILYWISE_CONFIDENCE = 0.95
BONFERRONI_ENVELOPES = len(ENVELOPES)
SELECTED_CALIBRATION_CASES = 576
CALIBRATION_CASES_PER_CELL = 24
STRESS_CASES = 8


class MethodologyError(ValueError):
    """An input violates the frozen issue #74 method."""


def canonical_json_bytes(value: Any) -> bytes:
    """Return the only JSON serialization used by this methodology."""
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def minimum_sample_size(
    population_content: float = POPULATION_CONTENT,
    familywise_confidence: float = FAMILYWISE_CONFIDENCE,
    envelope_count: int = BONFERRONI_ENVELOPES,
) -> int:
    """Derive n for a maximum-order-statistic tolerance limit."""
    if not 0.0 < population_content < 1.0:
        raise MethodologyError("population content must be between zero and one")
    if not 0.0 < familywise_confidence < 1.0:
        raise MethodologyError("familywise confidence must be between zero and one")
    if envelope_count <= 0:
        raise MethodologyError("envelope count must be positive")
    alpha_i = (1.0 - familywise_confidence) / envelope_count
    return math.ceil(math.log(alpha_i) / math.log(population_content))


def nearest_rank_higher(values: Sequence[float], percentile: float) -> float:
    """Return the conservative nearest-rank/higher percentile."""
    if not values:
        raise MethodologyError("the percentile domain must not be empty")
    if not 0.0 < percentile <= 1.0:
        raise MethodologyError("percentile must be greater than zero and at most one")
    finite = [float(value) for value in values]
    if not all(math.isfinite(value) and value >= 0.0 for value in finite):
        raise MethodologyError("absolute-error inputs must be finite and nonnegative")
    ordered = sorted(finite)
    return ordered[math.ceil(percentile * len(ordered)) - 1]


def tensor_metrics(reference: Sequence[float], candidate: Sequence[float]) -> dict[str, float]:
    """Reduce one complete checkpoint domain with host float64 arithmetic."""
    if len(reference) != len(candidate) or not reference:
        raise MethodologyError("reference and candidate domains must have the same nonzero size")
    errors: list[float] = []
    squares: list[float] = []
    for reference_value, candidate_value in zip(reference, candidate, strict=True):
        left = float(reference_value)
        right = float(candidate_value)
        if not math.isfinite(left) or not math.isfinite(right):
            raise MethodologyError("NaN or Inf is an unconditional failure")
        error = abs(left - right)
        if not math.isfinite(error):
            raise MethodologyError("non-finite absolute error is an unconditional failure")
        errors.append(error)
        squares.append(error * error)
    return {
        "max-absolute-difference": max(errors),
        "rms-difference": math.sqrt(math.fsum(squares) / len(squares)),
        "p99-absolute-error": nearest_rank_higher(errors, 0.99),
    }


def conservative_case_family(checkpoints: Iterable[dict[str, float]]) -> dict[str, float]:
    """Take the largest checkpoint value for each family metric."""
    rows = list(checkpoints)
    if not rows:
        raise MethodologyError("each family needs at least one checkpoint")
    result: dict[str, float] = {}
    for metric in METRICS:
        try:
            values = [float(row[metric]) for row in rows]
        except (KeyError, TypeError, ValueError) as exc:
            raise MethodologyError(f"missing or invalid family metric: {metric}") from exc
        if not all(math.isfinite(value) and value >= 0.0 for value in values):
            raise MethodologyError(f"family metric must be finite and nonnegative: {metric}")
        result[metric] = max(values)
    return result


def _walk_forbidden_holdout(value: Any, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = str(key).lower()
            child_path = f"{path}.{key}"
            if "holdout" in lowered or "unseal" in lowered:
                findings.append(child_path)
            findings.extend(_walk_forbidden_holdout(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_walk_forbidden_holdout(child, f"{path}[{index}]"))
    elif isinstance(value, str) and (value.startswith("h74-") or "sealed-holdout" in value.lower()):
        findings.append(path)
    return findings


def _parse_metric(value: Any) -> float:
    if isinstance(value, str):
        try:
            parsed = float.fromhex(value)
        except ValueError as exc:
            raise MethodologyError("metric strings must use Python hexadecimal float syntax") from exc
    else:
        parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0.0:
        raise MethodologyError("metrics must be finite and nonnegative")
    return parsed


def _validate_arm(rows: Any, expected_count: int, prefix: str) -> list[dict[str, Any]]:
    if not isinstance(rows, list) or len(rows) != expected_count:
        raise MethodologyError(f"{prefix} must contain exactly {expected_count} cases")
    case_ids: set[str] = set()
    for row in rows:
        case_id = row.get("case_id")
        if not isinstance(case_id, str) or not case_id.startswith(prefix) or case_id in case_ids:
            raise MethodologyError(f"invalid or duplicate {prefix} case ID")
        case_ids.add(case_id)
        if row.get("exact_integrity") != "PASS" or row.get("semantic_output") != "PASS":
            raise MethodologyError(f"{case_id} does not pass exact and semantic gates")
        if row.get("finite") is not True or row.get("evidence_complete") is not True:
            raise MethodologyError(f"{case_id} has incomplete or non-finite evidence")
        summaries = row.get("envelopes")
        if not isinstance(summaries, dict) or set(summaries) != set(ENVELOPES):
            raise MethodologyError(f"{case_id} must contain all 15 envelopes")
        for value in summaries.values():
            _parse_metric(value)
    return rows


def derive_threshold_manifest(
    methodology: dict[str, Any], calibration: dict[str, Any], *, program_sha256: str
) -> dict[str, Any]:
    """Derive 15 limits from calibration-only summaries."""
    forbidden = _walk_forbidden_holdout(calibration)
    if forbidden:
        raise MethodologyError("holdout inputs are forbidden: " + ", ".join(forbidden[:4]))
    if methodology.get("schema") != METHODOLOGY_SCHEMA:
        raise MethodologyError("methodology schema mismatch")
    if methodology.get("contract_id") != CONTRACT_ID:
        raise MethodologyError("contract ID mismatch")
    if methodology.get("status") != "FROZEN_METHODOLOGY_PHYSICAL_EXECUTION_NOT_AUTHORIZED":
        raise MethodologyError("methodology is not in the frozen pre-execution state")
    if methodology.get("mandatory_envelopes") != list(ENVELOPES):
        raise MethodologyError("mandatory envelope set or ordering mismatch")
    if calibration.get("schema") != CALIBRATION_SCHEMA:
        raise MethodologyError("calibration summary schema mismatch")
    if calibration.get("contract_id") != CONTRACT_ID:
        raise MethodologyError("calibration contract ID mismatch")
    if calibration.get("calibration_corpus_sha256") != methodology["corpora"]["calibration_manifest_sha256"]:
        raise MethodologyError("calibration corpus hash mismatch")
    stress_selection_sha256 = calibration.get("stress_selection_sha256")
    if not isinstance(stress_selection_sha256, str) or len(stress_selection_sha256) != 64:
        raise MethodologyError("the frozen stress selection hash is required")
    statistical = _validate_arm(calibration.get("statistical_cases"), SELECTED_CALIBRATION_CASES, "c74-")
    stress = _validate_arm(calibration.get("stress_cases"), STRESS_CASES, "p74-")
    evidence_hashes = calibration.get("evidence_sha256")
    if not isinstance(evidence_hashes, list) or not evidence_hashes:
        raise MethodologyError("at least one retained calibration evidence hash is required")
    if len(set(evidence_hashes)) != len(evidence_hashes):
        raise MethodologyError("calibration evidence hashes must be unique")
    if any(not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value)
           for value in evidence_hashes + [stress_selection_sha256]):
        raise MethodologyError("calibration evidence hashes must be SHA-256 hex digests")

    limits: dict[str, Any] = {}
    for envelope in ENVELOPES:
        statistical_max = max(_parse_metric(row["envelopes"][envelope]) for row in statistical)
        stress_max = max(_parse_metric(row["envelopes"][envelope]) for row in stress)
        limit = max(statistical_max, stress_max)
        limits[envelope] = {
            "statistical_max_hex": statistical_max.hex(),
            "stress_max_hex": stress_max.hex(),
            "limit_hex": limit.hex(),
            "rule": "max(statistical_max,stress_max)",
            "comparison": "observed<=limit",
        }

    return {
        "schema": THRESHOLD_SCHEMA,
        "contract_id": CONTRACT_ID,
        "methodology_manifest_sha256": sha256_bytes(canonical_json_bytes(methodology)),
        "calibration_summary_sha256": sha256_bytes(canonical_json_bytes(calibration)),
        "calibration_evidence_sha256": sorted(evidence_hashes),
        "stress_selection_sha256": stress_selection_sha256,
        "derivation_program_sha256": program_sha256,
        "metric_reducer": "host-float64/full-domain/nearest-rank-higher-p99/per-case-family-max/1",
        "corpus_sha256": methodology["corpora"]["calibration_manifest_sha256"],
        "limits": limits,
        "holdout_state": "SEALED_NOT_CONSUMED",
        "manual_editing_or_rounding": "PROHIBITED",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    sample = subparsers.add_parser("sample-size")
    sample.add_argument("--json", action="store_true")
    threshold = subparsers.add_parser("derive-thresholds")
    threshold.add_argument("--methodology", required=True, type=Path)
    threshold.add_argument("--calibration", required=True, type=Path)
    threshold.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    if args.command == "sample-size":
        minimum = minimum_sample_size()
        result = {
            "population_content": POPULATION_CONTENT,
            "familywise_confidence": FAMILYWISE_CONFIDENCE,
            "bonferroni_envelopes": BONFERRONI_ENVELOPES,
            "per_envelope_alpha": (1.0 - FAMILYWISE_CONFIDENCE) / BONFERRONI_ENVELOPES,
            "minimum_n": minimum,
            "selected_n": SELECTED_CALIBRATION_CASES,
        }
        print(json.dumps(result, sort_keys=True) if args.json else minimum)
        return 0

    methodology = json.loads(args.methodology.read_text(encoding="utf-8"))
    calibration = json.loads(args.calibration.read_text(encoding="utf-8"))
    manifest = derive_threshold_manifest(
        methodology, calibration, program_sha256=sha256_file(Path(__file__))
    )
    args.out.write_bytes(canonical_json_bytes(manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
