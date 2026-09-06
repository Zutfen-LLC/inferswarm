#!/usr/bin/env python3
"""InferSwarm issue #109 Gemma v5 mixture-population methodology (CPU-only).

Instantiates the accepted issue #108 / ADR 0012 post-v4 doctrine: it chooses
the MIXTURE_POPULATION_EXCHANGEABILITY assumption profile, the
POOLED_ORDER_STATISTIC_PREDICTION construction, and declares the concrete v5
statistical parameters. It does not physically execute a model. Pure stdlib:
it never imports or initializes a model runtime and never queries
accelerators.

The v5 comparator keeps the frozen v4 canonical-prefix semantic gate (decision
domain construction, argmax/tie-break rule, and E_D reducer) unchanged; ADR
0012 revises only the statistical construction and the numerical-core metric
tiers, both instantiated here and in ``issue109_v5_contract.py``.
"""
from __future__ import annotations

import hashlib
import random
from fractions import Fraction
from typing import Any, Iterator

# Reuse the frozen v4 semantic/decision-domain machinery unchanged (byte-
# identical import, not a redefinition): ADR 0012 does not revise the
# decision-domain construction, the argmax/tie-break rule, or the E_D
# reducer, only the statistical construction and metric tiers.
from issue95_v4_methodology import (  # noqa: F401 (re-exported identity)
    DECISION_DOMAIN_ESCAPE,
    DECISION_LOCAL_BOUND_EXCEEDED,
    SEMANTIC_PASS,
    argmax_tie_break_identity,
    ambiguity_set,
    case_e_d,
    decision_domain,
    decision_domain_construction_identity,
    decision_local_error,
    decision_local_error_identity,
    derive_e_d,
    domain_membership_sha256,
    e_d_reducer_identity,
    evaluate_decision,
    frozen_argmax,
    is_sha256,
    margin_on_domain,
    MARGIN_DEFINITION,
    MIN_ELIGIBLE,
    V4_ELIGIBILITY as V5_ELIGIBILITY,
    V4_SELECTION_RULE as V5_SELECTION_RULE,
)
from issue74_methodology import (
    CONTENT_CLASSES,
    LENGTH_REGIMES,
    MethodologyError,
    canonical_json_bytes,
    sha256_bytes,
)

CONTRACT_ID = "inferswarm.gemma4-mixture-population-qualification/1"
METHODOLOGY_ID = "inferswarm.issue109.v5-methodology/1"
ISSUE108_ACCEPTED_RECORD = "POST_V4_STATISTICAL_METRIC_DOCTRINE_ACCEPTED"

# --- frozen issue #109 v5 mixture-population identities --------------------

V5_CALIBRATION_SEED = "inferswarm-issue-109-calibration-v5-2"
V5_STRESS_POOL_SEED = "inferswarm-issue-109-stress-pool-v5"
V5_CALIBRATION_SCHEMA = "inferswarm.issue109.v5-calibration-corpus/1"
V5_STRESS_POOL_SCHEMA = "inferswarm.issue109.v5-stress-pool/1"
V5_HOLDOUT_PLAINTEXT_SCHEMA = "inferswarm.issue109.v5-holdout/1"
V5_HOLDOUT_COMMITMENT_SCHEMA = "inferswarm.issue109.v5-holdout-commitment/1"
V5_HOLDOUT_CUSTODY_SCHEMA = "inferswarm.issue109.v5-holdout-custody-record/1"
V5_STRESS_COMMITMENT_SCHEMA = "inferswarm.issue109.v5-stress-selection-commitment/1"
V5_MARGIN_SUMMARY_SCHEMA = "inferswarm.issue109.v5-reference-margin-summary/1"
V5_SELECTED_EIGHT_SCHEMA = "inferswarm.issue109.v5-selected-stress-eighth/1"
V5_MIXTURE_POPULATION_SCHEMA = "inferswarm.issue109.v5-mixture-population/1"
V5_COMMITMENT_STATE = "COMMITTED_BEFORE_MATCHED_REFERENCE_EXECUTION"
V5_SELECTION_STATE = "FROZEN_AFTER_MATCHED_REFERENCE_BEFORE_HETEROGENEOUS_CANDIDATE"
V5_CORE_FAMILY_COUNT = 3
V5_ALPHA = Fraction(1, 20)
V5_MIXTURE_COMPONENTS = 24
V5_TELEMETRY_FAMILY_COUNT = 13
V5_STRESS_POOL_CASES = 48
V5_CALIBRATION_CASES = 1416
V5_HOLDOUT_CASES = 24
V5_SELECTED_STRESS_CASES = 8
V5_STATISTICAL_CASES = V5_CALIBRATION_CASES

ASSUMPTION_PROFILE = "MIXTURE_POPULATION_EXCHANGEABILITY"
CONSTRUCTION = "POOLED_ORDER_STATISTIC_PREDICTION"
QUALIFICATION_CLAIM = "ZERO_EXCEEDANCE_CAMPAIGN_MIXTURE"


def physical_subject_contract() -> dict[str, Any]:
    """Return the unchanged v5 physical subject and semantic gate contract."""
    return {
        "schema": "inferswarm.issue109.v5-physical-subject/1",
        "model": "google/gemma-4-12B-it",
        "revision": "707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7",
        "checkpoint_sha256": "5a84cb313260ac447237b890387116dfa8682e49a6b44bc585ae8353abbff18d",
        "execution": "native BF16 text execution; Triton attention; one <=64-row replay chunk",
        "reference_geometry": "single RTX 3090 reference path",
        "candidate_geometry": "accepted three-stage RTX 3060 heterogeneous chain",
        "decision_count": 8,
        "evaluation_order": [
            "finite and exact-integrity gate",
            "decision_local_error<=E_D",
            "actual candidate winner in reference-derived domain",
            "stable exact-winner or unstable ambiguity-set adjudication",
        ],
        "reason_codes": [
            "DECISION_LOCAL_BOUND_EXCEEDED",
            "DECISION_DOMAIN_ESCAPE",
            "STABLE_DECISION_MISMATCH",
            "UNSTABLE_DECISION_INADMISSIBLE",
            "SEMANTIC_PASS",
        ],
    }


def mixture_components() -> tuple[tuple[str, int], ...]:
    """Return the 24 frozen (content_class, length_regime_index) components."""
    return tuple(
        (content_class, regime_index)
        for content_class in CONTENT_CLASSES
        for regime_index in range(len(LENGTH_REGIMES))
    )


def derive_mixture_prediction_design(
    *, family_count: int = V5_CORE_FAMILY_COUNT, alpha: Fraction = V5_ALPHA,
    calibration_cases: int = V5_CALIBRATION_CASES, holdout_cases: int = V5_HOLDOUT_CASES,
    mixture_component_count: int = V5_MIXTURE_COMPONENTS,
    stress_pool_cases: int = V5_STRESS_POOL_CASES,
) -> dict[str, Any]:
    """Derive the v5 pooled-mixture zero-exceedance design.

    Under MIXTURE_POPULATION_EXCHANGEABILITY, a calibration maximum over N
    IID mixture draws has strict-exceedance probability at most H/(N+H) for H
    future exchangeable draws from the same frozen mixture population
    (continuous values give equality; ties only make it conservative). This
    mirrors the ``statistical-contract.json`` POOLED_ORDER_STATISTIC_PREDICTION
    identity accepted by issue #108, applied here to one declared mixture
    target rather than the historical fixed-balanced-cell design.
    """
    if (family_count <= 0 or not (0 < alpha < 1) or calibration_cases < 1
            or holdout_cases < 1 or mixture_component_count < 1 or stress_pool_cases < 0):
        raise MethodologyError("invalid mixture predictive-design inputs")
    per_family = Fraction(holdout_cases, calibration_cases + holdout_cases)
    familywise = family_count * per_family
    if familywise > alpha:
        raise MethodologyError(
            "mixture design does not meet the declared familywise error budget"
        )
    return {
        "assumption_profile": ASSUMPTION_PROFILE,
        "construction": CONSTRUCTION,
        "qualification_claim": QUALIFICATION_CLAIM,
        "mixture_components": mixture_component_count,
        "component_weights": f"uniform 1/{mixture_component_count} per component",
        "calibration_cases": calibration_cases,
        "holdout_cases": holdout_cases,
        "core_family_count": family_count,
        "alpha": float(alpha),
        "per_core_family_strict_exceedance_bound": f"{holdout_cases}/{calibration_cases + holdout_cases}",
        "familywise_bonferroni_bound": f"{family_count * holdout_cases}/{calibration_cases + holdout_cases}",
        "familywise_failure_probability": float(familywise),
        "zero_exceedance_probability_at_least": float(1 - familywise),
        "inclusive_holdout_comparison": "observed<=limit",
        "stress_cases": stress_pool_cases,
        "stress_cases_contribute_predictive_sample_size": 0,
        "theorem": (
            "IID frozen mixture-population exchangeability; a calibration "
            "maximum over N draws has strict-exceedance probability <= "
            "H/(N+H) for H future exchangeable draws from the same mixture"
        ),
    }


_V5_DERIVED_DESIGN = derive_mixture_prediction_design()


def component_stream(
    seed: str, namespace: str, count: int,
    *, component_count: int = V5_MIXTURE_COMPONENTS,
) -> Iterator[tuple[int, tuple[str, int]]]:
    """Yield ``count`` IID-drawn (draw_index, component) pairs.

    Each draw independently selects one of the frozen equally-weighted
    mixture components via a SHA-256-seeded RNG keyed on ``(seed, namespace,
    "mixture-component", draw_index)``. This is the precommitted
    component-selection rule required by the accepted issue #108 statistical
    contract: it is frozen before any case content is generated and does not
    depend on prior draws.
    """
    if count < 0:
        raise MethodologyError("mixture draw count must be nonnegative")
    components = mixture_components()
    if len(components) != component_count:
        raise MethodologyError("mixture component universe size mismatch")
    for index in range(count):
        material = "\0".join((seed, namespace, "mixture-component", str(index))).encode()
        rng = random.Random(int.from_bytes(hashlib.sha256(material).digest(), "big"))
        yield index, components[rng.randrange(len(components))]


def target_length_stream(
    seed: str, namespace: str, regime_index: int, count: int,
) -> Iterator[int]:
    """Yield IID uniform target lengths for one frozen length regime.

    A draw uses only its seed, namespace, regime, and draw index. It does not
    depend on another draw or on the selected mixture component.
    """
    if count < 0 or not 0 <= regime_index < len(LENGTH_REGIMES):
        raise MethodologyError("invalid target-length stream inputs")
    for index in range(count):
        yield target_length(seed, namespace, regime_index, index)


def target_length(seed: str, namespace: str, regime_index: int, draw_index: int) -> int:
    """Return one IID uniform target length for a complete prompt draw."""
    if not 0 <= regime_index < len(LENGTH_REGIMES) or draw_index < 0:
        raise MethodologyError("invalid target-length draw inputs")
    low, high = LENGTH_REGIMES[regime_index]
    material = "\0".join(
        (seed, namespace, "target-length", str(regime_index), str(draw_index))
    ).encode()
    rng = random.Random(int.from_bytes(hashlib.sha256(material).digest(), "big"))
    return rng.randint(low, high)


def mixture_population_declaration() -> dict[str, Any]:
    """The frozen, non-secret mixture-population generator declaration.

    This is the artifact required by statistical-contract.json Q2/Q3: the
    component-selection rule and component weights, frozen before any
    calibration or holdout draw, and identical for both arms.
    """
    return {
        "schema": V5_MIXTURE_POPULATION_SCHEMA,
        "contract_id": CONTRACT_ID,
        "assumption_profile": ASSUMPTION_PROFILE,
        "components": [
            {"content_class": content_class, "length_regime": list(LENGTH_REGIMES[regime_index])}
            for content_class, regime_index in mixture_components()
        ],
        "component_count": V5_MIXTURE_COMPONENTS,
        "component_weights": "uniform 1/24 per component",
        "component_selection_rule": (
            "for draw index i, component = components[SHA256(seed \\0 namespace \\0 "
            "'mixture-component' \\0 i)-seeded Random.randrange(24)]; frozen before "
            "any case content is generated"
        ),
        "target_length_selection_rule": (
            "for draw index i and selected regime r, length = "
            "SHA256(seed \\0 namespace \\0 'target-length' \\0 r \\0 i)-seeded "
            "Random.randint(low, high); each inclusive regime length is uniform"
        ),
        "draws_are_iid": True,
        "calibration_and_holdout_share_generator": True,
        "calibration_namespace": "calibration",
        "holdout_namespace": "v5-sealed-holdout",
        "generator": "scripts/generate_issue109_corpora.py",
        "note": (
            "The calibration draw uses a public seed; the holdout draw uses an "
            "independent secret seed. Both use this identical component-selection "
            "rule and weights, so calibration and holdout cases are IID draws from "
            "one frozen mixture population, per issue #108 Q2."
        ),
    }
