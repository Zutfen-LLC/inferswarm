#!/usr/bin/env python3
"""Issue #79: versioned v2 threshold derivation tool (CPU-only, fail-closed).

Binds methodology-v2 stress artifacts (p76-* pool, v2 selection commitment,
future v2 selected-eight manifest) to the UNCHANGED v1 threshold math over
the frozen c74-* 576-case statistical calibration corpus.

Differences from the v1 path (scripts/issue74_methodology.py, retained
byte-identical as historical evidence) are provenance-only:

- statistical arm: the SAME frozen 576-case c74-* calibration corpus
  (sha256 e147ce0a672fe7f8616f9e000fea770bfeab6e0a1aca637ffe6bc07cd64c3175);
- stress arm: the frozen v2 stress pool (p76-*, schema
  inferswarm.issue76.margin-stress-pool/2), the accepted v2 selection
  commitment, and the FUTURE v2 selected-eight manifest produced by the
  accepted v2 selector after the future matched-reference run;
- threshold semantics are byte-for-byte identical to v1: for each of
  exactly 15 envelopes,
      statistical_max = max across exact 576 statistical summaries
      stress_max      = max across exact 8 selected v2 stress summaries
      limit           = max(statistical_max, stress_max)
      comparison      = observed <= limit
  under the exact v1 reducer identity
  host-float64/full-domain/nearest-rank-higher-p99/per-case-family-max/1,
  serialized as exact hexadecimal binary64 strings. No interpolation, no
  manual rounding, no universal epsilon.

This tool never imports a model runtime, never queries hardware, and never
needs (or accepts) holdout material to derive
thresholds. It does NOT recompute the stress ranking: it only proves the
supplied selected-eight manifest is a valid frozen v2 selection artifact
with exact provenance (schema, state, pool/commitment binding, 4+4 shape,
pool-identity of every selected case).
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Sequence

# Shared pure helpers imported from the frozen v1 tool: identical semantics.
from issue74_methodology import (  # noqa: F401 (re-exported identity)
    CONTRACT_ID,
    ENVELOPES,
    SELECTED_CALIBRATION_CASES,
    STRESS_CASES,
    MethodologyError,
    _parse_metric,
    _walk_forbidden_holdout,
    canonical_json_bytes,
    case_identities_sha256,
    case_ids_sha256,
    sha256_bytes,
    sha256_file,
)

# --- frozen v2 identities (methodology v2 accepted at 8905566) -------------

V2_TOOLING_IDENTITY = (
    "inferswarm.issue79.v2-threshold-tooling/1 "
    "(methodology v2 accepted at inferswarm@8905566031e0296694b3f1288d0f9d1ae15f8134)"
)
V2_TOOLING_SCHEMA_FIELD = V2_TOOLING_IDENTITY

CALIBRATION_CORPUS_SCHEMA = "inferswarm.issue74.calibration-corpus/1"
CALIBRATION_CORPUS_SHA256 = (
    "e147ce0a672fe7f8616f9e000fea770bfeab6e0a1aca637ffe6bc07cd64c3175"
)
CALIBRATION_CASE_IDS_SHA256 = (
    "283b5fa3b637a1b7bd39abc65e5187804018dec1a85893ea258aad4fe794825b"
)
CALIBRATION_CASE_IDENTITIES_SHA256 = (
    "afd8680cb64b71f8d69043edc2287439e61fe68ac5c7f3b9fafaeff97bba3398"
)

V2_POOL_SCHEMA = "inferswarm.issue76.margin-stress-pool/2"
V2_POOL_SHA256 = (
    "533b32857721b3f99243e5695bc18b24960cbd3c80692d626154907d6ecbd7c9"
)
V2_POOL_CASE_COUNT = 48

V2_COMMITMENT_SHA256 = (
    "04421a6f19f6338a340dfea296214509eae3adc5ca32067dfd76880ab1cacba0"
)
V2_COMMITMENT_STATE = "COMMITTED_BEFORE_MATCHED_REFERENCE_EXECUTION"
V2_SELECTOR_PATH = "scripts/select_issue76_margin_stress_v2.py"
V2_SELECTOR_SHA256 = (
    "e32e8672671c3b3ec6b47e3b119c66fd54e2c5a62ba72fb2ec2288764508beab"
)
V2_MARGIN_DEFINITION = "min over all 8 greedy steps of fp32(top1_logit - top2_logit)"
V2_ELIGIBILITY_RULE = "margin is finite AND margin > 0"

V2_SELECTION_SCHEMA = "inferswarm.issue76.margin-stress-selection/2"
V2_SELECTION_STATE = "FROZEN_AFTER_MATCHED_REFERENCE_BEFORE_HETEROGENEOUS_CANDIDATE"
V2_SELECTION_INPUTS = "MATCHED_REFERENCE_MARGINS_ONLY"

V2_CALIBRATION_SUMMARY_SCHEMA = "inferswarm.issue79.v2-calibration-summary/1"
V2_THRESHOLD_SCHEMA = "inferswarm.issue79.v2-threshold-manifest/1"
METRIC_REDUCER = "host-float64/full-domain/nearest-rank-higher-p99/per-case-family-max/1"
HOLDOUT_CIPHERTEXT_SHA256 = (
    "23311c5514b2561c66a2ecd0c9cfa25c3f4f91b83b67353aada8355f48e25c59"
)

_V2_SELECTION_EXPECTED_FIELDS = {
    "schema", "contract_id", "margin_definition",
    "margin_definition_unchanged_from", "stress_pool_sha256",
    "selection_commitment_sha256", "reference_margin_summary_sha256",
    "selection_inputs", "eligibility_rule", "selection_rule",
    "minimum_eligible_cases", "eligible_case_count", "ineligible_case_count",
    "ineligible_cases", "selected_count", "selected", "state",
}


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


# --- holdout exclusion ------------------------------------------------------

def reject_holdout_material(label: str, *values: Any) -> None:
    """Recursively reject any input containing holdout/unseal material."""
    for value in values:
        findings = _walk_forbidden_holdout(value)
        if findings:
            raise MethodologyError(
                f"{label}: holdout inputs are forbidden: " + ", ".join(findings[:4])
            )


# --- validation stages (fail closed, in order) ------------------------------

def validate_contract_tooling(summary: dict[str, Any]) -> None:
    if summary.get("schema") != V2_CALIBRATION_SUMMARY_SCHEMA:
        raise MethodologyError("v2 calibration summary schema mismatch")
    if summary.get("contract_id") != CONTRACT_ID:
        raise MethodologyError("v2 calibration summary contract mismatch")
    if summary.get("tooling_or_methodology_version") != V2_TOOLING_SCHEMA_FIELD:
        raise MethodologyError("v2 tooling/methodology identity mismatch")


def validate_statistical_corpus(calibration_corpus: dict[str, Any]) -> dict[str, str]:
    """Exact frozen c74-* corpus: SHA, 576 IDs, exact mapping, no dup/sub."""
    if calibration_corpus.get("schema") != CALIBRATION_CORPUS_SCHEMA:
        raise MethodologyError("calibration corpus schema mismatch")
    if calibration_corpus.get("contract_id") != CONTRACT_ID:
        raise MethodologyError("calibration corpus contract mismatch")
    corpus_hash = sha256_bytes(canonical_json_bytes(calibration_corpus))
    if corpus_hash != CALIBRATION_CORPUS_SHA256:
        raise MethodologyError(
            "calibration corpus hash mismatch: the exact frozen v1 corpus is required"
        )
    cases = calibration_corpus.get("cases")
    if not isinstance(cases, list) or len(cases) != SELECTED_CALIBRATION_CASES:
        raise MethodologyError(
            f"calibration corpus must contain exactly {SELECTED_CALIBRATION_CASES} cases"
        )
    identities: dict[str, str] = {}
    for case in cases:
        if not isinstance(case, dict):
            raise MethodologyError("calibration corpus contains an invalid case")
        case_id = case.get("case_id")
        case_sha256 = case.get("case_sha256")
        if not isinstance(case_id, str) or not case_id.startswith("c74-"):
            raise MethodologyError("calibration corpus case ID must start with c74-")
        if case_id in identities:
            raise MethodologyError(f"duplicate calibration case: {case_id}")
        if not _is_sha256(case_sha256):
            raise MethodologyError(f"{case_id} has an invalid frozen case hash")
        identities[case_id] = case_sha256
    if case_ids_sha256(cases, expected_count=SELECTED_CALIBRATION_CASES, prefix="c74-") != CALIBRATION_CASE_IDS_SHA256:
        raise MethodologyError("calibration case-ID commitment mismatch")
    if case_identities_sha256(cases, expected_count=SELECTED_CALIBRATION_CASES, prefix="c74-") != CALIBRATION_CASE_IDENTITIES_SHA256:
        raise MethodologyError("calibration case identity commitment mismatch")
    return identities


def validate_stress_pool(stress_pool: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Exact frozen v2 pool: SHA, schema, exact 48-case p76-* identity source."""
    if stress_pool.get("schema") != V2_POOL_SCHEMA:
        raise MethodologyError("v2 stress pool schema mismatch")
    if stress_pool.get("contract_id") != CONTRACT_ID:
        raise MethodologyError("v2 stress pool contract mismatch")
    pool_hash = sha256_bytes(canonical_json_bytes(stress_pool))
    if pool_hash != V2_POOL_SHA256:
        raise MethodologyError("v2 stress pool hash mismatch")
    cases = stress_pool.get("cases")
    if not isinstance(cases, list) or len(cases) != V2_POOL_CASE_COUNT:
        raise MethodologyError(
            f"v2 stress pool must contain exactly {V2_POOL_CASE_COUNT} cases"
        )
    pool_cases: dict[str, dict[str, Any]] = {}
    for case in cases:
        if not isinstance(case, dict):
            raise MethodologyError("v2 stress pool contains an invalid case")
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id.startswith("p76-"):
            raise MethodologyError("v2 stress pool case ID must start with p76-")
        if case_id in pool_cases:
            raise MethodologyError(f"duplicate v2 stress pool case: {case_id}")
        if not _is_sha256(case.get("case_sha256")):
            raise MethodologyError(f"{case_id} has an invalid frozen case hash")
        pool_cases[case_id] = case
    return pool_cases


def validate_selection_commitment(commitment: dict[str, Any]) -> None:
    """Exact accepted v2 commitment: SHA, pre-reference state, selector binding,
    unchanged margin definition, finite-positive eligibility, no candidate
    observations."""
    commitment_hash = sha256_bytes(canonical_json_bytes(commitment))
    if commitment_hash != V2_COMMITMENT_SHA256:
        raise MethodologyError("v2 stress selection commitment hash mismatch")
    if commitment.get("state") != V2_COMMITMENT_STATE:
        raise MethodologyError(
            "v2 stress selection rule was not committed before reference execution"
        )
    if commitment.get("candidate_pool_sha256") != V2_POOL_SHA256:
        raise MethodologyError("v2 commitment does not bind the exact frozen pool")
    if commitment.get("selection_program") != V2_SELECTOR_PATH:
        raise MethodologyError("v2 commitment selector path mismatch")
    if commitment.get("selection_program_sha256") != V2_SELECTOR_SHA256:
        raise MethodologyError("v2 commitment selector hash mismatch")
    if commitment.get("margin_definition") != V2_MARGIN_DEFINITION:
        raise MethodologyError("v2 commitment margin definition drift")
    if commitment.get("eligibility_rule") != V2_ELIGIBILITY_RULE:
        raise MethodologyError("v2 commitment eligibility rule mismatch")
    if commitment.get("selected_case_count") != STRESS_CASES:
        raise MethodologyError("v2 commitment must require eight selected cases")
    if commitment.get("candidate_observations_forbidden") is not True:
        raise MethodologyError("v2 commitment does not forbid candidate observations")


def validate_selected_manifest(
    stress_selection: dict[str, Any], pool_cases: dict[str, dict[str, Any]]
) -> dict[str, str]:
    """Prove the selected-eight manifest is a valid frozen v2 selection
    artifact with exact provenance. Does NOT recompute the ranking."""
    if stress_selection.get("schema") != V2_SELECTION_SCHEMA:
        raise MethodologyError("v2 selected manifest schema mismatch")
    if stress_selection.get("schema") == "inferswarm.issue74.margin-stress-selection/1":
        raise MethodologyError("v1 selected manifest schema is forbidden in the v2 path")
    if set(stress_selection) != _V2_SELECTION_EXPECTED_FIELDS:
        raise MethodologyError("v2 selected manifest fields do not match the frozen artifact")
    if stress_selection.get("contract_id") != CONTRACT_ID:
        raise MethodologyError("v2 selected manifest contract mismatch")
    if stress_selection.get("state") != V2_SELECTION_STATE:
        raise MethodologyError("v2 selected manifest is not frozen at the post-reference barrier")
    if stress_selection.get("stress_pool_sha256") != V2_POOL_SHA256:
        raise MethodologyError("v2 selected manifest does not bind the exact frozen pool")
    if stress_selection.get("selection_commitment_sha256") != V2_COMMITMENT_SHA256:
        raise MethodologyError("v2 selected manifest commitment mismatch")
    if not _is_sha256(stress_selection.get("reference_margin_summary_sha256")):
        raise MethodologyError("v2 selected manifest reference-margin hash is invalid")
    if stress_selection.get("selection_inputs") != V2_SELECTION_INPUTS:
        raise MethodologyError("v2 selected manifest is not reference-only")
    if stress_selection.get("margin_definition") != V2_MARGIN_DEFINITION:
        raise MethodologyError("v2 selected manifest margin definition drift")
    if stress_selection.get("selected_count") != STRESS_CASES:
        raise MethodologyError("v2 selected manifest must declare exactly eight cases")
    selected = stress_selection.get("selected")
    if not isinstance(selected, list) or len(selected) != STRESS_CASES:
        raise MethodologyError("v2 selected manifest must contain exactly eight cases")
    group_counts = {"four-smallest-positive": 0, "four-largest-positive": 0}
    selected_ids: set[str] = set()
    identities: dict[str, str] = {}
    for row in selected:
        if not isinstance(row, dict) or row.get("selection_group") not in group_counts:
            raise MethodologyError("v2 selected manifest contains an invalid selection group")
        if set(row) != {"selection_group", "case", "reference_top1_margin_hex"}:
            raise MethodologyError("v2 selected manifest row fields do not match the frozen artifact")
        group_counts[row["selection_group"]] += 1
        case = row.get("case")
        case_id = case.get("case_id") if isinstance(case, dict) else None
        if not isinstance(case_id, str) or not case_id.startswith("p76-"):
            raise MethodologyError("v2 selected manifest contains a non-p76 case ID")
        if case_id.startswith("p74-"):
            raise MethodologyError("v1 p74 case IDs are forbidden in the v2 path")
        if case_id in selected_ids:
            raise MethodologyError("v2 selected manifest contains a duplicate case")
        if case_id not in pool_cases or case != pool_cases.get(case_id):
            raise MethodologyError(
                "v2 selected manifest case is not byte/object-identical to a frozen v2 pool case"
            )
        try:
            margin = float.fromhex(row["reference_top1_margin_hex"])
        except (KeyError, TypeError, ValueError) as exc:
            raise MethodologyError("v2 selected manifest contains an invalid reference margin") from exc
        if not math.isfinite(margin) or margin <= 0.0:
            raise MethodologyError("v2 selected manifest requires finite positive reference margins")
        selected_ids.add(case_id)
        identities[case_id] = case["case_sha256"]
    if set(group_counts.values()) != {4}:
        raise MethodologyError(
            "v2 selected manifest must contain four cases in each selection group"
        )
    return identities


def validate_calibration_summary(
    summary: dict[str, Any],
    *,
    corpus_identities: dict[str, str],
    selected_identities: dict[str, str],
    stress_selection_sha256: str,
) -> list[dict[str, Any]]:
    """Full v2 calibration-summary validation: provenance, exact case sets,
    all correctness gates, evidence SHA set."""
    validate_contract_tooling(summary)
    expected_fields = {
        "schema", "contract_id", "tooling_or_methodology_version",
        "calibration_corpus_sha256", "stress_pool_sha256",
        "stress_selection_commitment_sha256", "stress_selection_sha256",
        "evidence_sha256", "statistical_cases", "stress_cases",
    }
    if set(summary) != expected_fields:
        raise MethodologyError("v2 calibration summary fields do not match the schema")
    if summary.get("calibration_corpus_sha256") != CALIBRATION_CORPUS_SHA256:
        raise MethodologyError("v2 calibration summary corpus hash mismatch")
    if summary.get("stress_pool_sha256") != V2_POOL_SHA256:
        raise MethodologyError("v2 calibration summary stress pool hash mismatch")
    if summary.get("stress_selection_commitment_sha256") != V2_COMMITMENT_SHA256:
        raise MethodologyError("v2 calibration summary commitment hash mismatch")
    if summary.get("stress_selection_sha256") != stress_selection_sha256:
        raise MethodologyError("v2 calibration summary does not bind the exact selected manifest")

    evidence_hashes = summary.get("evidence_sha256")
    if not isinstance(evidence_hashes, list) or not evidence_hashes:
        raise MethodologyError("at least one retained calibration evidence hash is required")
    if len(set(evidence_hashes)) != len(evidence_hashes):
        raise MethodologyError("calibration evidence hashes must be unique")
    if any(not _is_sha256(value) for value in evidence_hashes):
        raise MethodologyError("calibration evidence hashes must be SHA-256 hex digests")

    statistical = _validate_arm(
        summary.get("statistical_cases"), corpus_identities,
        SELECTED_CALIBRATION_CASES, "c74-",
    )
    stress = _validate_arm(
        summary.get("stress_cases"), selected_identities, STRESS_CASES, "p76-",
    )
    return statistical + stress


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
        if case_id.startswith("p74-") or case_id.startswith("h74-"):
            raise MethodologyError(f"forbidden case ID namespace in {prefix} arm: {case_id}")
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


# --- derivation (math unchanged from v1) ------------------------------------

def derive_v2_threshold_manifest(
    *,
    calibration_corpus: dict[str, Any],
    stress_pool: dict[str, Any],
    selection_commitment: dict[str, Any],
    stress_selection: dict[str, Any],
    calibration_summary: dict[str, Any],
    program_sha256: str,
) -> dict[str, Any]:
    """Derive the 15 unchanged limits from exact c74-* statistical evidence
    plus exact selected p76-* stress evidence. Fails closed unless every
    prerequisite is exact."""
    reject_holdout_material(
        "derivation inputs",
        calibration_corpus, stress_pool, selection_commitment,
        stress_selection, calibration_summary,
    )
    if not _is_sha256(program_sha256):
        raise MethodologyError("derivation program SHA must be a SHA-256 hex digest")

    # Order matters: contract/tooling, corpus, pool, commitment, selection,
    # then the calibration summary.
    validate_contract_tooling(calibration_summary)
    corpus_identities = validate_statistical_corpus(calibration_corpus)
    pool_cases = validate_stress_pool(stress_pool)
    validate_selection_commitment(selection_commitment)
    selected_identities = validate_selected_manifest(stress_selection, pool_cases)
    stress_selection_sha256 = sha256_bytes(canonical_json_bytes(stress_selection))
    rows = validate_calibration_summary(
        calibration_summary,
        corpus_identities=corpus_identities,
        selected_identities=selected_identities,
        stress_selection_sha256=stress_selection_sha256,
    )
    statistical = rows[:SELECTED_CALIBRATION_CASES]
    stress = rows[SELECTED_CALIBRATION_CASES:]

    # UNCHANGED v1 threshold math: max(statistical_max, stress_max) per
    # envelope, exact hexadecimal binary64 serialization.
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
        "schema": V2_THRESHOLD_SCHEMA,
        "contract_id": CONTRACT_ID,
        "tooling_or_methodology_version": V2_TOOLING_SCHEMA_FIELD,
        "calibration_corpus_sha256": CALIBRATION_CORPUS_SHA256,
        "calibration_case_ids_sha256": CALIBRATION_CASE_IDS_SHA256,
        "calibration_case_identities_sha256": CALIBRATION_CASE_IDENTITIES_SHA256,
        "calibration_summary_sha256": sha256_bytes(canonical_json_bytes(calibration_summary)),
        "calibration_evidence_sha256": sorted(calibration_summary["evidence_sha256"]),
        "stress_pool_sha256": V2_POOL_SHA256,
        "stress_selection_commitment_sha256": V2_COMMITMENT_SHA256,
        "stress_selection_sha256": stress_selection_sha256,
        "derivation_program_sha256": program_sha256,
        "metric_reducer": METRIC_REDUCER,
        "limits": limits,
        "holdout_state": "SEALED_NOT_CONSUMED",
        "manual_editing_or_rounding": "PROHIBITED",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibration-corpus", required=True, type=Path)
    parser.add_argument("--stress-pool", required=True, type=Path)
    parser.add_argument("--selection-commitment", required=True, type=Path)
    parser.add_argument("--stress-selection", required=True, type=Path)
    parser.add_argument("--calibration-summary", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    manifest = derive_v2_threshold_manifest(
        calibration_corpus=json.loads(args.calibration_corpus.read_text(encoding="utf-8")),
        stress_pool=json.loads(args.stress_pool.read_text(encoding="utf-8")),
        selection_commitment=json.loads(args.selection_commitment.read_text(encoding="utf-8")),
        stress_selection=json.loads(args.stress_selection.read_text(encoding="utf-8")),
        calibration_summary=json.loads(args.calibration_summary.read_text(encoding="utf-8")),
        program_sha256=sha256_file(Path(__file__)),
    )
    args.out.write_bytes(canonical_json_bytes(manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
