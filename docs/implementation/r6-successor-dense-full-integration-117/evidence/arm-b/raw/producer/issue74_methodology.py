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
CALIBRATION_CORPUS_SCHEMA = "inferswarm.issue74.calibration-corpus/1"
STRESS_POOL_SCHEMA = "inferswarm.issue74.margin-stress-pool/1"
STRESS_SELECTION_SCHEMA = "inferswarm.issue74.margin-stress-selection/1"
STRESS_SELECTION_STATE = "FROZEN_AFTER_MATCHED_REFERENCE_BEFORE_HETEROGENEOUS_CANDIDATE"


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


def balanced_mixture_all_below_bound(
    cell_coverages: Sequence[float], observations_per_cell: int
) -> tuple[float, float]:
    """Return the balanced-design probability and its equal-mixture bound."""
    if len(cell_coverages) != len(CONTENT_CLASSES) * len(LENGTH_REGIMES):
        raise MethodologyError("the balanced design must contain exactly 24 cells")
    if observations_per_cell <= 0:
        raise MethodologyError("observations per cell must be positive")
    coverages = [float(value) for value in cell_coverages]
    if not all(math.isfinite(value) and 0.0 <= value <= 1.0 for value in coverages):
        raise MethodologyError("cell coverage must be finite and between zero and one")
    all_below_probability = math.prod(value ** observations_per_cell for value in coverages)
    equal_mixture_coverage = math.fsum(coverages) / len(coverages)
    mixture_bound = equal_mixture_coverage ** (len(coverages) * observations_per_cell)
    return all_below_probability, mixture_bound


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


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _case_identity_rows(cases: Any, *, expected_count: int, prefix: str) -> list[dict[str, str]]:
    if not isinstance(cases, list) or len(cases) != expected_count:
        raise MethodologyError(f"{prefix} identity source must contain exactly {expected_count} cases")
    identities: list[dict[str, str]] = []
    seen: set[str] = set()
    for case in cases:
        if not isinstance(case, dict):
            raise MethodologyError(f"{prefix} identity source contains an invalid case")
        case_id = case.get("case_id")
        case_sha256 = case.get("case_sha256")
        if not isinstance(case_id, str) or not case_id.startswith(prefix) or case_id in seen:
            raise MethodologyError(f"invalid or duplicate {prefix} identity source case ID")
        if not _is_sha256(case_sha256):
            raise MethodologyError(f"{case_id} has an invalid frozen case hash")
        seen.add(case_id)
        identities.append({"case_id": case_id, "case_sha256": case_sha256})
    return sorted(identities, key=lambda row: row["case_id"])


def case_ids_sha256(cases: Any, *, expected_count: int, prefix: str) -> str:
    """Hash the order-independent set of frozen case IDs."""
    identities = _case_identity_rows(cases, expected_count=expected_count, prefix=prefix)
    return sha256_bytes(canonical_json_bytes([row["case_id"] for row in identities]))


def case_identities_sha256(cases: Any, *, expected_count: int, prefix: str) -> str:
    """Hash the order-independent case-ID-to-case-hash mapping."""
    identities = _case_identity_rows(cases, expected_count=expected_count, prefix=prefix)
    return sha256_bytes(canonical_json_bytes(identities))


def _validate_arm(
    rows: Any, expected_identities: dict[str, str], expected_count: int, prefix: str
) -> list[dict[str, Any]]:
    if not isinstance(rows, list) or len(rows) != expected_count:
        raise MethodologyError(f"{prefix} must contain exactly {expected_count} cases")
    case_ids: set[str] = set()
    expected_row_fields = {
        "case_id", "case_sha256", "exact_integrity", "semantic_output",
        "finite", "evidence_complete", "envelopes",
    }
    for row in rows:
        if not isinstance(row, dict):
            raise MethodologyError(f"{prefix} contains an invalid case summary")
        if set(row) != expected_row_fields:
            raise MethodologyError(f"{prefix} case summary fields do not match the schema")
        case_id = row.get("case_id")
        if not isinstance(case_id, str) or not case_id.startswith(prefix) or case_id in case_ids:
            raise MethodologyError(f"invalid or duplicate {prefix} case ID")
        case_ids.add(case_id)
        if row.get("case_sha256") != expected_identities.get(case_id):
            raise MethodologyError(f"{case_id} does not match the frozen case identity")
        if row.get("exact_integrity") != "PASS" or row.get("semantic_output") != "PASS":
            raise MethodologyError(f"{case_id} does not pass exact and semantic gates")
        if row.get("finite") is not True or row.get("evidence_complete") is not True:
            raise MethodologyError(f"{case_id} has incomplete or non-finite evidence")
        summaries = row.get("envelopes")
        if not isinstance(summaries, dict) or set(summaries) != set(ENVELOPES):
            raise MethodologyError(f"{case_id} must contain all 15 envelopes")
        for value in summaries.values():
            _parse_metric(value)
    if case_ids != set(expected_identities):
        raise MethodologyError(f"{prefix} case IDs do not match the exact frozen case set")
    return rows


def _validate_frozen_corpus(
    methodology: dict[str, Any], calibration_corpus: dict[str, Any]
) -> dict[str, str]:
    if calibration_corpus.get("schema") != CALIBRATION_CORPUS_SCHEMA:
        raise MethodologyError("calibration corpus schema mismatch")
    if calibration_corpus.get("contract_id") != CONTRACT_ID:
        raise MethodologyError("calibration corpus contract mismatch")
    corpus_hash = sha256_bytes(canonical_json_bytes(calibration_corpus))
    if corpus_hash != methodology["corpora"]["calibration_manifest_sha256"]:
        raise MethodologyError("calibration corpus hash mismatch")
    identities = _case_identity_rows(
        calibration_corpus.get("cases"),
        expected_count=SELECTED_CALIBRATION_CASES,
        prefix="c74-",
    )
    ids_hash = sha256_bytes(canonical_json_bytes([row["case_id"] for row in identities]))
    identities_hash = sha256_bytes(canonical_json_bytes(identities))
    if ids_hash != methodology["corpora"].get("calibration_case_ids_sha256"):
        raise MethodologyError("calibration case ID commitment mismatch")
    if identities_hash != methodology["corpora"].get("calibration_case_identities_sha256"):
        raise MethodologyError("calibration case identity commitment mismatch")
    return {row["case_id"]: row["case_sha256"] for row in identities}


def _validate_methodology_contract(methodology: dict[str, Any]) -> None:
    design = methodology.get("statistical_design")
    expected_design = {
        "population_content": POPULATION_CONTENT,
        "familywise_confidence": FAMILYWISE_CONFIDENCE,
        "bonferroni_envelopes": BONFERRONI_ENVELOPES,
        "minimum_n": minimum_sample_size(),
        "selected_n": SELECTED_CALIBRATION_CASES,
        "cell_count": len(CONTENT_CLASSES) * len(LENGTH_REGIMES),
        "cases_per_cell": CALIBRATION_CASES_PER_CELL,
        "independent_unit": "one deterministic prompt case",
        "target_population": "equal-weighted mixture of the 24 frozen content-by-length cells",
        "balanced_mixture_proof": "product(q_h^24)<=q_bar^576 by AM-GM",
    }
    if design != expected_design:
        raise MethodologyError("statistical design contract mismatch")
    corpora = methodology.get("corpora")
    if not isinstance(corpora, dict):
        raise MethodologyError("corpus contract is missing")
    expected_counts = {
        "calibration_case_count": SELECTED_CALIBRATION_CASES,
        "stress_pool_case_count": 48,
        "stress_selected_case_count": STRESS_CASES,
        "holdout_case_count": 24,
    }
    if any(corpora.get(key) != value for key, value in expected_counts.items()):
        raise MethodologyError("corpus count contract mismatch")
    if methodology.get("threshold_rule") != (
        "max(576-case statistical maximum,8-case stress maximum) for each envelope"
    ):
        raise MethodologyError("threshold rule mismatch")
    reducer = methodology.get("reducer")
    if not isinstance(reducer, dict) or reducer.get("comparison") != "inclusive observed<=frozen_limit":
        raise MethodologyError("inclusive comparison contract mismatch")


def _validate_stress_selection(
    methodology: dict[str, Any], stress_pool: dict[str, Any], stress_selection: dict[str, Any]
) -> dict[str, str]:
    if stress_pool.get("schema") != STRESS_POOL_SCHEMA:
        raise MethodologyError("stress pool schema mismatch")
    if stress_pool.get("contract_id") != CONTRACT_ID:
        raise MethodologyError("stress pool contract mismatch")
    pool_hash = sha256_bytes(canonical_json_bytes(stress_pool))
    if pool_hash != methodology["corpora"]["stress_pool_manifest_sha256"]:
        raise MethodologyError("stress pool hash mismatch")
    pool_identities = _case_identity_rows(stress_pool.get("cases"), expected_count=48, prefix="p74-")
    pool_cases = {row["case_id"]: case for row, case in zip(
        pool_identities,
        sorted(stress_pool["cases"], key=lambda case: case["case_id"]),
        strict=True,
    )}

    if stress_selection.get("schema") != STRESS_SELECTION_SCHEMA:
        raise MethodologyError("stress selection schema mismatch")
    expected_selection_fields = {
        "schema", "contract_id", "stress_pool_sha256", "selection_commitment_sha256",
        "reference_margin_summary_sha256", "selection_inputs", "selection_rule",
        "selected_count", "selected", "state",
    }
    if set(stress_selection) != expected_selection_fields:
        raise MethodologyError("stress selection fields do not match the frozen artifact")
    if stress_selection.get("contract_id") != CONTRACT_ID:
        raise MethodologyError("stress selection contract mismatch")
    if stress_selection.get("state") != STRESS_SELECTION_STATE:
        raise MethodologyError("stress selection is not frozen at the post-reference barrier")
    if stress_selection.get("stress_pool_sha256") != pool_hash:
        raise MethodologyError("stress selection does not belong to the exact frozen pool")
    if stress_selection.get("selection_commitment_sha256") != methodology["corpora"].get(
        "stress_selection_commitment_sha256"
    ):
        raise MethodologyError("stress selection commitment mismatch")
    if stress_selection.get("selection_inputs") != "MATCHED_REFERENCE_MARGINS_ONLY":
        raise MethodologyError("stress selection is not reference-only")
    if stress_selection.get("selection_rule") != (
        "sort finite positive margins by (margin,case_id); take first four and last four"
    ):
        raise MethodologyError("stress selection rule mismatch")
    if not _is_sha256(stress_selection.get("reference_margin_summary_sha256")):
        raise MethodologyError("stress selection reference-margin hash is invalid")
    if stress_selection.get("selected_count") != STRESS_CASES:
        raise MethodologyError("stress selection must declare exactly eight cases")
    selected = stress_selection.get("selected")
    if not isinstance(selected, list) or len(selected) != STRESS_CASES:
        raise MethodologyError("stress selection must contain exactly eight cases")
    group_counts = {"four-smallest-positive": 0, "four-largest": 0}
    selected_cases: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    for row in selected:
        if not isinstance(row, dict) or row.get("selection_group") not in group_counts:
            raise MethodologyError("stress selection contains an invalid selection group")
        if set(row) != {"selection_group", "case", "reference_top1_margin_hex"}:
            raise MethodologyError("stress selection row fields do not match the frozen artifact")
        group_counts[row["selection_group"]] += 1
        case = row.get("case")
        case_id = case.get("case_id") if isinstance(case, dict) else None
        if case_id in selected_ids or case_id not in pool_cases or case != pool_cases.get(case_id):
            raise MethodologyError("stress selection contains a duplicate or non-pool case")
        try:
            margin = float.fromhex(row["reference_top1_margin_hex"])
        except (KeyError, TypeError, ValueError) as exc:
            raise MethodologyError("stress selection contains an invalid reference margin") from exc
        if not math.isfinite(margin) or margin <= 0.0:
            raise MethodologyError("stress selection requires finite positive reference margins")
        selected_ids.add(case_id)
        selected_cases.append(case)
    if set(group_counts.values()) != {4}:
        raise MethodologyError("stress selection must contain four cases in each selection group")
    identities = _case_identity_rows(selected_cases, expected_count=STRESS_CASES, prefix="p74-")
    return {row["case_id"]: row["case_sha256"] for row in identities}


def derive_threshold_manifest(
    methodology: dict[str, Any],
    calibration: dict[str, Any],
    calibration_corpus: dict[str, Any],
    stress_pool: dict[str, Any],
    stress_selection: dict[str, Any],
    *,
    program_sha256: str,
) -> dict[str, Any]:
    """Derive 15 limits from calibration-only summaries."""
    forbidden = _walk_forbidden_holdout({
        "calibration": calibration,
        "stress_selection": stress_selection,
    })
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
    _validate_methodology_contract(methodology)
    statistical_identities = _validate_frozen_corpus(methodology, calibration_corpus)
    stress_identities = _validate_stress_selection(methodology, stress_pool, stress_selection)
    if calibration.get("schema") != CALIBRATION_SCHEMA:
        raise MethodologyError("calibration summary schema mismatch")
    expected_calibration_fields = {
        "schema", "contract_id", "calibration_corpus_sha256",
        "stress_selection_sha256", "evidence_sha256", "statistical_cases", "stress_cases",
    }
    if set(calibration) != expected_calibration_fields:
        raise MethodologyError("calibration summary fields do not match the schema")
    if calibration.get("contract_id") != CONTRACT_ID:
        raise MethodologyError("calibration contract ID mismatch")
    calibration_corpus_sha256 = sha256_bytes(canonical_json_bytes(calibration_corpus))
    if calibration.get("calibration_corpus_sha256") != calibration_corpus_sha256:
        raise MethodologyError("calibration corpus hash mismatch")
    stress_selection_sha256 = calibration.get("stress_selection_sha256")
    actual_stress_selection_sha256 = sha256_bytes(canonical_json_bytes(stress_selection))
    if stress_selection_sha256 != actual_stress_selection_sha256:
        raise MethodologyError("calibration summary does not bind the exact stress selection")
    statistical = _validate_arm(
        calibration.get("statistical_cases"), statistical_identities, SELECTED_CALIBRATION_CASES, "c74-"
    )
    stress = _validate_arm(calibration.get("stress_cases"), stress_identities, STRESS_CASES, "p74-")
    evidence_hashes = calibration.get("evidence_sha256")
    if not isinstance(evidence_hashes, list) or not evidence_hashes:
        raise MethodologyError("at least one retained calibration evidence hash is required")
    if len(set(evidence_hashes)) != len(evidence_hashes):
        raise MethodologyError("calibration evidence hashes must be unique")
    if any(not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value)
           for value in evidence_hashes + [stress_selection_sha256, program_sha256]):
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
        "corpus_sha256": calibration_corpus_sha256,
        "calibration_case_ids_sha256": methodology["corpora"]["calibration_case_ids_sha256"],
        "calibration_case_identities_sha256": methodology["corpora"][
            "calibration_case_identities_sha256"
        ],
        "stress_pool_sha256": methodology["corpora"]["stress_pool_manifest_sha256"],
        "stress_selection_commitment_sha256": methodology["corpora"]["stress_selection_commitment_sha256"],
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
    threshold.add_argument("--calibration-corpus", required=True, type=Path)
    threshold.add_argument("--stress-pool", required=True, type=Path)
    threshold.add_argument("--stress-selection", required=True, type=Path)
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
    calibration_corpus = json.loads(args.calibration_corpus.read_text(encoding="utf-8"))
    stress_pool = json.loads(args.stress_pool.read_text(encoding="utf-8"))
    stress_selection = json.loads(args.stress_selection.read_text(encoding="utf-8"))
    manifest = derive_threshold_manifest(
        methodology,
        calibration,
        calibration_corpus,
        stress_pool,
        stress_selection,
        program_sha256=sha256_file(Path(__file__)),
    )
    args.out.write_bytes(canonical_json_bytes(manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
