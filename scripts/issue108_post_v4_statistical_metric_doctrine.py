#!/usr/bin/env python3
"""Validate the issue #108 statistical and numerical-core doctrine.

This is pure-stdlib, CPU-only static tooling. It reads the versioned doctrine
area, verifies the hash-bound historical inputs, and reproduces the probability
identities that constrain the successor methodology gate. It does not read
node-local data or execute a model.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
AREA = REPO_ROOT / "docs/qualification/post-v4-statistical-metric-doctrine"
RETENTION_MANIFEST = (
    "docs/qualification/gemma4-12b-it-post-v4-core-diagnosis/"
    "RAW-EVIDENCE-RETENTION.json"
)

ASSUMPTION_PROFILES = {
    "MIXTURE_POPULATION_EXCHANGEABILITY",
    "WITHIN_NAMED_STRATUM_EXCHANGEABILITY",
}

QUALIFICATION_CLAIMS = {
    "ZERO_EXCEEDANCE_CAMPAIGN_MIXTURE",
    "ZERO_EXCEEDANCE_CAMPAIGN_NAMED_STRATA",
    "MARGINAL_PER_CASE_MIXTURE",
    "MARGINAL_PER_CASE_NAMED_STRATUM",
}


class DoctrineError(ValueError):
    """A doctrine artifact is incomplete, inconsistent, or unsupported."""


def load_json(name: str) -> dict:
    with (AREA / name).open(encoding="utf-8") as source:
        return json.load(source)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def retained_repo_path(path_text: str) -> Path:
    """Return a repository-local retained-evidence path or fail closed."""
    candidate = Path(path_text)
    if candidate.is_absolute():
        raise DoctrineError("RETAINED_RAW_EVIDENCE_PATH_INVALID")
    resolved = (REPO_ROOT / candidate).resolve()
    try:
        resolved.relative_to(REPO_ROOT.resolve())
    except ValueError as error:
        raise DoctrineError("RETAINED_RAW_EVIDENCE_PATH_INVALID") from error
    return resolved


def campaign_max_exceedance_probability(
        calibration_cases: int, holdout_cases: int) -> float:
    """Return P(any future campaign value exceeds a calibration maximum).

    This identity requires all calibration and holdout values to be
    exchangeable under the declared target population. Continuous errors make
    it exact. Ties can only make the strict-exceedance probability smaller.
    """
    if calibration_cases < 1 or holdout_cases < 1:
        raise DoctrineError("POSITIVE_CAMPAIGN_COUNTS_REQUIRED")
    return holdout_cases / (calibration_cases + holdout_cases)


def marginal_order_statistic_exceedance_probability(
        calibration_cases: int, order: int) -> float:
    """Return P(a future value exceeds the selected calibration order statistic)."""
    if calibration_cases < 1 or not 1 <= order <= calibration_cases:
        raise DoctrineError("INVALID_ORDER_STATISTIC")
    return (calibration_cases + 1 - order) / (calibration_cases + 1)


def stratified_campaign_exceedance_upper_bound(
        calibration_cases_per_stratum: list[int],
        holdout_cases_per_stratum: list[int]) -> float:
    """Return the union bound for named-stratum calibration maxima."""
    if len(calibration_cases_per_stratum) != len(holdout_cases_per_stratum):
        raise DoctrineError("STRATUM_COUNT_MISMATCH")
    if not calibration_cases_per_stratum:
        raise DoctrineError("AT_LEAST_ONE_STRATUM_REQUIRED")
    return math.fsum(
        campaign_max_exceedance_probability(calibration_cases, holdout_cases)
        for calibration_cases, holdout_cases in zip(
            calibration_cases_per_stratum, holdout_cases_per_stratum)
    )


def validate_statistical_contract(contract: dict) -> None:
    """Validate prospective statistical doctrine without selecting v5."""
    if contract["schema"] != "inferswarm.issue108.statistical-contract/1":
        raise DoctrineError("UNSUPPORTED_STATISTICAL_CONTRACT_SCHEMA")
    if {"assumption_profile", "construction"} & set(contract):
        raise DoctrineError("CONCRETE_V5_SELECTION_FORBIDDEN")
    profiles = set(contract["permitted_assumption_profiles"])
    if profiles != ASSUMPTION_PROFILES:
        raise DoctrineError("INCOMPLETE_ASSUMPTION_PROFILE_DOCTRINE")
    requirements = contract["assumption_profile_requirements"]
    if set(requirements) != profiles:
        raise DoctrineError("INCOMPLETE_ASSUMPTION_PROFILE_DOCTRINE")
    for requirement in requirements.values():
        if not requirement:
            raise DoctrineError("INCOMPLETE_ASSUMPTION_PROFILE_DOCTRINE")
    allowed = set(contract["permitted_construction_classes"])
    comparison = contract["construction_comparison"]
    if set(comparison) != allowed:
        raise DoctrineError("INCOMPLETE_CONSTRUCTION_COMPARISON")
    for entry in comparison.values():
        for field in ("assumptions", "finite_sample_guarantee",
                      "familywise_composition", "sample_burden_scaling",
                      "failure_modes"):
            if not entry.get(field):
                raise DoctrineError("INCOMPLETE_CONSTRUCTION_COMPARISON")
    compatibility = contract["compatibility_constraints"]
    pairs = set()
    for entry in compatibility:
        profile = entry["assumption_profile"]
        construction = entry["construction"]
        claims = entry["qualification_claims"]
        pair = (profile, construction)
        if profile not in profiles or construction not in allowed:
            raise DoctrineError("INVALID_DOCTRINE_COMPATIBILITY")
        if pair in pairs or not claims or not set(claims) <= QUALIFICATION_CLAIMS:
            raise DoctrineError("INVALID_DOCTRINE_COMPATIBILITY")
        pairs.add(pair)
    if (not pairs or {construction for _, construction in pairs} != allowed
            or {profile for profile, _ in pairs} != profiles):
        raise DoctrineError("INCOMPLETE_DOCTRINE_COMPATIBILITY")
    familywise = contract["familywise_composition"]
    if familywise["independence_assumed"]:
        raise DoctrineError("FAMILYWISE_INDEPENDENCE_ASSUMPTION_FORBIDDEN")
    if familywise["method"] != "BONFERRONI_OR_STRONGER_VALID_BOUND":
        raise DoctrineError("INVALID_FAMILYWISE_COMPOSITION")
    prohibitions = set(contract["prohibitions"])
    required = {
        "NO_POST_HOC_POOLING",
        "NO_CONSUMED_HOLDOUT_AS_SUCCESSOR_INPUT",
        "NO_UNDECLARED_CROSS_STRATUM_EXCHANGEABILITY",
    }
    if not required <= prohibitions:
        raise DoctrineError("STATISTICAL_PROHIBITION_MISSING")


def validate_prospective_methodology(methodology: dict, contract: dict) -> None:
    """Reject a proposed methodology that is outside the accepted doctrine.

    This validator checks a prospective proposal. It does not choose one.
    """
    validate_statistical_contract(contract)
    profile = methodology["assumption_profile"]
    construction = methodology["construction"]
    claim = methodology["qualification_claim"]
    if construction not in set(contract["permitted_construction_classes"]):
        raise DoctrineError("UNPERMITTED_CONSTRUCTION_CLASS")
    if profile not in set(contract["permitted_assumption_profiles"]):
        raise DoctrineError("UNKNOWN_ASSUMPTION_PROFILE")
    matches = [
        entry for entry in contract["compatibility_constraints"]
        if entry["assumption_profile"] == profile
        and entry["construction"] == construction
    ]
    if not matches:
        raise DoctrineError("INCOMPATIBLE_ASSUMPTION_CONSTRUCTION")
    if profile == "MIXTURE_POPULATION_EXCHANGEABILITY":
        if not methodology["declared_iid_mixture_target"]:
            raise DoctrineError("UNDECLARED_CROSS_STRATUM_EXCHANGEABILITY")
        if methodology["claims_per_stratum_coverage"]:
            raise DoctrineError("MIXTURE_DOES_NOT_ESTABLISH_PER_STRATUM_COVERAGE")
    elif profile == "WITHIN_NAMED_STRATUM_EXCHANGEABILITY":
        if not methodology["declared_named_strata"]:
            raise DoctrineError("NAMED_STRATA_UNDECLARED")
    if claim not in matches[0]["qualification_claims"]:
        raise DoctrineError("INCOMPATIBLE_QUALIFICATION_CLAIM")


def verify_retained_raw_evidence(retention_manifest: dict) -> None:
    """Verify every durable repository file named by the retention manifest."""
    if retention_manifest.get("schema") != "inferswarm.issue105.raw-evidence-retention/1":
        raise DoctrineError("UNSUPPORTED_RETAINED_RAW_EVIDENCE_SCHEMA")
    files = retention_manifest.get("retained_durable_repo", {}).get("files")
    if not isinstance(files, list):
        raise DoctrineError("RETAINED_RAW_EVIDENCE_INVENTORY_INVALID")
    raw_rows = 0
    producer_records = 0
    seen_paths = set()
    for entry in files:
        if not isinstance(entry, dict):
            raise DoctrineError("RETAINED_RAW_EVIDENCE_INVENTORY_INVALID")
        path_text = entry.get("path")
        expected_sha256 = entry.get("sha256")
        if (not isinstance(path_text, str) or not isinstance(expected_sha256, str)
                or len(expected_sha256) != 64):
            raise DoctrineError("RETAINED_RAW_EVIDENCE_INVENTORY_INVALID")
        if path_text in seen_paths:
            raise DoctrineError("RETAINED_RAW_EVIDENCE_INVENTORY_INVALID")
        seen_paths.add(path_text)
        path = retained_repo_path(path_text)
        if not path.is_file():
            raise DoctrineError("RETAINED_RAW_EVIDENCE_FILE_MISSING")
        if sha256_file(path) != expected_sha256:
            raise DoctrineError("RETAINED_RAW_EVIDENCE_HASH_DRIFT")
        if path.suffix == ".f32":
            raw_rows += 1
        if "producer case record" in entry.get("role", ""):
            producer_records += 1
    if raw_rows < 16 or producer_records < 2:
        raise DoctrineError("RETAINED_RAW_EVIDENCE_INVENTORY_INCOMPLETE")


def validate_metric_classification(classification: dict) -> None:
    if classification["schema"] != "inferswarm.issue108.metric-core-classification/1":
        raise DoctrineError("UNSUPPORTED_METRIC_CLASSIFICATION_SCHEMA")
    metrics = {metric["identity"]: metric for metric in classification["metrics"]}
    required_tiers = {
        "fp32-consumer-logits:max-absolute-difference": "ACCEPTANCE_BEARING",
        "fp32-consumer-logits:rms-difference": "ACCEPTANCE_BEARING",
        "fp32-consumer-logits:p99-absolute-error": "MANDATORY_TELEMETRY",
        "decision_local_E_D": "ACCEPTANCE_BEARING",
    }
    for identity, tier in required_tiers.items():
        if metrics.get(identity, {}).get("tier") != tier:
            raise DoctrineError("METRIC_TIER_MISMATCH")
    rule = classification["capture_position_rule"]
    if rule["current_gemma_profile"] != "ALL_8_CANONICAL_DECISIONS":
        raise DoctrineError("INCOMPLETE_CANONICAL_DECISION_COVERAGE")
    if rule["subset_permitted_for_current_gemma_profile"]:
        raise DoctrineError("CURRENT_GEMMA_SUBSET_FORBIDDEN")


def verify_source_bindings(bindings: dict) -> None:
    if bindings["schema"] != "inferswarm.issue108.source-bindings/1":
        raise DoctrineError("UNSUPPORTED_SOURCE_BINDINGS_SCHEMA")
    for binding in bindings["historical_inputs"]:
        path = REPO_ROOT / binding["path"]
        if not path.is_file():
            raise DoctrineError("HISTORICAL_SOURCE_MISSING")
        if sha256_file(path) != binding["sha256"]:
            raise DoctrineError("HISTORICAL_SOURCE_HASH_DRIFT")
    if not any(binding.get("path") == RETENTION_MANIFEST
               for binding in bindings["historical_inputs"]):
        raise DoctrineError("RETAINED_RAW_EVIDENCE_MANIFEST_UNBOUND")
    retention_path = REPO_ROOT / RETENTION_MANIFEST
    try:
        with retention_path.open(encoding="utf-8") as source:
            retention_manifest = json.load(source)
    except (OSError, json.JSONDecodeError) as error:
        raise DoctrineError("RETAINED_RAW_EVIDENCE_MANIFEST_INVALID") from error
    verify_retained_raw_evidence(retention_manifest)


def calculation_identities() -> dict:
    """Return the v4 regression values and general prospective identities."""
    v4_stratified = stratified_campaign_exceedance_upper_bound([79] * 24, [1] * 24)
    v4_pooled = campaign_max_exceedance_probability(1896, 24)
    return {
        "schema": "inferswarm.issue108.probability-identities/1",
        "v4_regression": {
            "within_cell_per_family_upper_bound": campaign_max_exceedance_probability(79, 1),
            "within_cell_24_stratum_per_family_union_upper_bound": v4_stratified,
            "within_cell_four_family_union_upper_bound": 4 * v4_stratified,
            "mixture_population_per_family_probability": v4_pooled,
            "mixture_population_four_family_bonferroni_upper_bound": 4 * v4_pooled,
        },
        "prospective_identities": {
            "pooled_campaign_maximum": "H/(N+H)",
            "marginal_order_statistic": "(N+1-k)/(N+1)",
            "named_strata_campaign_union": "sum_s H_s/(N_s+H_s)",
            "familywise_composition": "sum_m alpha_m <= alpha_familywise",
        },
    }


def build_record() -> dict:
    contract = load_json("statistical-contract.json")
    classification = load_json("metric-core-classification.json")
    bindings = load_json("source-bindings.json")
    validate_statistical_contract(contract)
    validate_metric_classification(classification)
    verify_source_bindings(bindings)
    return {
        "schema": "inferswarm.issue108.post-v4-doctrine-record/1",
        "terminal_classification": "POST_V4_STATISTICAL_METRIC_DOCTRINE_ACCEPTED",
        "statistical_contract": contract,
        "metric_core_classification": classification,
        "source_bindings": bindings,
        "calculation_identities": calculation_identities(),
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None,
                        help="write the deterministic record to this path")
    args = parser.parse_args()
    rendered = json.dumps(build_record(), indent=2, sort_keys=True) + "\n"
    if args.out is None:
        print(rendered, end="")
    else:
        args.out.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
