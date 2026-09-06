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


class DoctrineError(ValueError):
    """A doctrine artifact is incomplete, inconsistent, or unsupported."""


def load_json(name: str) -> dict:
    with (AREA / name).open(encoding="utf-8") as source:
        return json.load(source)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    """Reject a claim whose stated assumptions cannot establish it."""
    if contract["schema"] != "inferswarm.issue108.statistical-contract/1":
        raise DoctrineError("UNSUPPORTED_STATISTICAL_CONTRACT_SCHEMA")
    profile = contract["assumption_profile"]
    construction = contract["construction"]
    if (profile == "WITHIN_NAMED_STRATUM_EXCHANGEABILITY"
            and construction == "POOLED_CALIBRATION_MAXIMUM"):
        raise DoctrineError("UNSUPPORTED_POOLED_MAXIMUM_CLAIM")
    allowed = set(contract["permitted_construction_classes"])
    if construction not in allowed:
        raise DoctrineError("UNPERMITTED_CONSTRUCTION_CLASS")
    if profile == "MIXTURE_POPULATION_EXCHANGEABILITY":
        mixture = contract["mixture_population_requirements"]
        if not mixture["case_generator_is_iid_from_one_frozen_mixture"]:
            raise DoctrineError("MIXTURE_EXCHANGEABILITY_NOT_ESTABLISHED")
        if mixture["per_stratum_coverage_claim_allowed"]:
            raise DoctrineError("MIXTURE_DOES_NOT_ESTABLISH_PER_STRATUM_COVERAGE")
    elif profile != "WITHIN_NAMED_STRATUM_EXCHANGEABILITY":
        raise DoctrineError("UNKNOWN_ASSUMPTION_PROFILE")
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
