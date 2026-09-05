#!/usr/bin/env python3
"""InferSwarm issue #95 Gemma v4 prediction-aligned methodology (CPU-only).

Implements the accepted issue #93 two-tier numerical classification and issue
#83 semantic contract before any physical execution. Pure stdlib: it never
imports or initializes a model runtime and never queries accelerators.
"""
from __future__ import annotations

import math
from fractions import Fraction
from typing import Any, Iterable, Sequence

# Reuse ONLY the pure frozen helpers of the v1 tool (byte-identical file,
# proven by the living v1 MANIFEST.sha256). All v1 selection/threshold
# semantics are re-defined here as v4 identities, not reused.
from issue74_methodology import (  # noqa: F401 (re-exported identity)
    ENVELOPES,
    MethodologyError,
    canonical_json_bytes,
    sha256_bytes,
)

CONTRACT_ID = "inferswarm.gemma4-prediction-aligned-qualification/1"
METHODOLOGY_ID = "inferswarm.issue95.v4-methodology/1"
ISSUE83_ACCEPTED_SHA = "d60b8f6c4490c91312e8d073b4ac55794bf68841"

# --- frozen issue #95 v4 corpus identities --------------------------------

V4_CALIBRATION_SEED = "inferswarm-issue-95-calibration-v4-2"
V4_STRESS_POOL_SEED = "inferswarm-issue-95-stress-pool-v4"
V4_CALIBRATION_SCHEMA = "inferswarm.issue95.v4-calibration-corpus/1"
V4_STRESS_POOL_SCHEMA = "inferswarm.issue95.v4-stress-pool/1"
V4_HOLDOUT_PLAINTEXT_SCHEMA = "inferswarm.issue95.v4-holdout/1"
V4_HOLDOUT_COMMITMENT_SCHEMA = "inferswarm.issue95.v4-holdout-commitment/1"
V4_HOLDOUT_CUSTODY_SCHEMA = "inferswarm.issue95.v4-holdout-custody-record/1"
V4_STRESS_COMMITMENT_SCHEMA = "inferswarm.issue95.v4-stress-selection-commitment/1"
V4_MARGIN_SUMMARY_SCHEMA = "inferswarm.issue95.v4-reference-margin-summary/1"
V4_SELECTED_EIGHT_SCHEMA = "inferswarm.issue95.v4-selected-stress-eighth/1"
V4_COMMITMENT_STATE = "COMMITTED_BEFORE_MATCHED_REFERENCE_EXECUTION"
V4_SELECTION_STATE = "FROZEN_AFTER_MATCHED_REFERENCE_BEFORE_HETEROGENEOUS_CANDIDATE"
V4_CORE_FAMILY_COUNT = 4
V4_ALPHA = Fraction(1, 20)
V4_CELLS = 24
V4_TELEMETRY_FAMILY_COUNT = 12
V4_STRESS_POOL_CASES = 48
V4_HOLDOUT_CASES = 24
V4_SELECTED_STRESS_CASES = 8


def derive_prediction_aligned_design(
    *, family_count: int = V4_CORE_FAMILY_COUNT, alpha: Fraction = V4_ALPHA,
    cells: int = V4_CELLS, selected_stress_cases: int = V4_SELECTED_STRESS_CASES,
) -> dict[str, Any]:
    """Mechanically solve family_count/(r+1) <= alpha for minimum integer r.

    Selected stress cases deliberately contribute zero predictive sample size;
    they only participate in the independently derived maxima/bands.
    """
    if family_count <= 0 or alpha <= 0 or alpha >= 1 or cells <= 0:
        raise MethodologyError("invalid predictive-design inputs")
    r = 0
    while Fraction(family_count, r + 1) > alpha:
        r += 1
    per_family = Fraction(1, r + 1)
    familywise = family_count * per_family
    return {
        "cells": cells,
        "cases_per_cell": r,
        "statistical_cases": cells * r,
        "holdout_cases": cells,
        "core_family_count": family_count,
        "alpha": float(alpha),
        "per_core_family_strict_exceedance_bound": f"1/{r + 1}",
        "familywise_bonferroni_bound": f"{family_count}/{r + 1}",
        "familywise_failure_probability": float(familywise),
        "zero_exceedance_probability_at_least": float(1 - familywise),
        "inclusive_holdout_comparison": "observed<=limit",
        "stress_cases": selected_stress_cases,
        "stress_cases_contribute_predictive_sample_size": 0,
        "theorem": "within-cell exchangeability; global maximum lies in one cell; a strict future record in that cell has probability <=1/80",
    }


_V4_DERIVED_DESIGN = derive_prediction_aligned_design()
V4_CASES_PER_CELL = _V4_DERIVED_DESIGN["cases_per_cell"]
V4_STATISTICAL_CASES = _V4_DERIVED_DESIGN["statistical_cases"]
MARGIN_DEFINITION = "min over all 8 greedy decisions of fp32(top1_logit - top2_logit)"
V4_ELIGIBILITY = (
    "non-finite margin: unconditional reference failure (NONFINITE_REFERENCE_MARGIN); "
    "finite negative margin: unconditional reference/order-consistency failure "
    "(NEGATIVE_REFERENCE_MARGIN); finite zero margin: eligible exact-tie stress case; "
    "finite positive margin: eligible"
)
V4_SELECTION_RULE = (
    "sort finite nonnegative margins by (margin,case_id); take first four and last four"
)
MIN_ELIGIBLE = 8

# --- frozen decision domain / E_D / semantic identities --------------------


def _check_v4_frozen_identity(
    value: Any,
    expected: str,
    label: str,
) -> str:
    if value != expected:
        raise MethodologyError(f"{label} mismatch: expected {expected!r}, got {value!r}")
    return value


def decision_domain_construction_identity() -> str:
    """The frozen v4 decision-domain construction rule identity (issue #95)."""
    return "reference-top-1024-with-cutoff-ties/1"


def argmax_tie_break_identity() -> str:
    """The frozen deterministic greedy rule identity (issue #95)."""
    return "ARGMAX_FIRST_MAX/lowest-token-id-among-exactly-equal-fp32-maxima"


def decision_local_error_identity() -> str:
    return "max_{i in D(r)}|candidate_i - reference_i| over canonical-prefix decision rows"


def e_d_reducer_identity() -> str:
    return (
        "case_E_D=max over 8 decisions of decision_local_error; "
        "statistical_E_D=max over 1896 statistical cases; "
        "stress_E_D=max over 8 selected stress cases; E_D=max(statistical_E_D,stress_E_D)"
    )


DECISION_LOCAL_BOUND_EXCEEDED = "DECISION_LOCAL_BOUND_EXCEEDED"
DECISION_DOMAIN_ESCAPE = "DECISION_DOMAIN_ESCAPE"
SEMANTIC_PASS = "SEMANTIC_PASS"
BRANCHED_PREFIX = "BRANCHED_"


def is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


# ---------------------------------------------------------------------------
# Section 5: the frozen decision-domain construction.
# ---------------------------------------------------------------------------


def decision_domain(reference_logits: Sequence[float], k: int = 1024) -> tuple[int, ...]:
    """Build the frozen decision domain D(r) from ONE reference FP32 row.

    Construction ``reference-top-1024-with-cutoff-ties/1``:

    1. find the k-th-highest reference logit value (the cutoff);
    2. D(r) = every token whose reference logit is >= the cutoff
       (so exact ties AT the cutoff are all included and |D(r)| may exceed k);
    3. membership/ordering of the returned tuple is by ascending token id
       after set construction.

    The domain is reference-derived only; candidate output never alters
    membership. K=1024 is a fixed, conservative power-of-two reference-head
    budget chosen prospectively; it is not derived from any #81 statistic.
    """
    if k <= 0:
        raise MethodologyError("decision-domain K must be positive")
    if not reference_logits:
        raise MethodologyError("a reference logit row must not be empty")
    values = [float(v) for v in reference_logits]
    if not all(math.isfinite(v) for v in values):
        raise MethodologyError("reference logits must be finite")
    cutoff = sorted(values, reverse=True)[min(k, len(values)) - 1]
    domain = tuple(i for i, v in enumerate(values) if v >= cutoff)
    if not domain:
        raise MethodologyError("decision domain construction produced an empty set")
    # winner containment by construction: the full-vocabulary argmax value is
    # >= the cutoff, so the argmax index(es) are members.
    top = max(values)
    if not any(values[i] == top for i in domain):
        raise MethodologyError("decision domain does not contain the reference winner")
    return domain


def domain_membership_sha256(domain: Sequence[int]) -> str:
    """Hash the canonical per-row D(r) membership (sorted token-id tuple)."""
    ordered = sorted(int(i) for i in domain)
    return sha256_bytes(canonical_json_bytes(list(ordered)))


# ---------------------------------------------------------------------------
# Section 8: the frozen deterministic argmax/tie-break rule.
# ---------------------------------------------------------------------------


def frozen_argmax(logits: Sequence[float]) -> int:
    """ARGMAX_FIRST_MAX / lowest token-id among exactly equal FP32 maxima.

    Iterates token ids in ascending order and keeps the first exact maximum;
    a later index can replace the winner only under a strictly greater value,
    so exactly-equal maxima resolve to the lowest token id.
    """
    if not logits:
        raise MethodologyError("argmax requires a nonempty row")
    best_index = 0
    best_value = float(logits[0])
    if not math.isfinite(best_value):
        raise MethodologyError("argmax requires finite logits")
    for index in range(1, len(logits)):
        value = float(logits[index])
        if not math.isfinite(value):
            raise MethodologyError("argmax requires finite logits")
        if value > best_value:
            best_value = value
            best_index = index
    return best_index


def margin_on_domain(
    reference_logits: Sequence[float], domain: Iterable[int]
) -> float:
    """m_D = r[a] - r[b_D] over D with the frozen winner rule."""
    values = [float(v) for v in reference_logits]
    a = frozen_argmax(values)
    if a not in set(domain):
        raise MethodologyError("reference winner escaped the decision domain")
    best_other: float | None = None
    for i in domain:
        if i == a:
            continue
        v = values[i]
        if best_other is None or v > best_other:
            best_other = v
    if best_other is None:
        raise MethodologyError("decision domain must contain a runner-up")
    return values[a] - best_other


def ambiguity_set(
    reference_logits: Sequence[float], domain: Iterable[int], e_d: float
) -> tuple[int, ...]:
    """A_ED(r) = { k in D | r[a] - r[k] <= 2E_D }, ordered by token id."""
    if not math.isfinite(e_d) or e_d < 0.0:
        raise MethodologyError("E_D must be finite and nonnegative")
    values = [float(v) for v in reference_logits]
    a = frozen_argmax(values)
    if a not in set(domain):
        raise MethodologyError("reference winner escaped the decision domain")
    return tuple(sorted(k for k in domain if values[a] - values[k] <= 2.0 * e_d))


# ---------------------------------------------------------------------------
# Section 6: decision-local error and E_D derivation.
# ---------------------------------------------------------------------------


def decision_local_error(
    reference_logits: Sequence[float],
    candidate_logits: Sequence[float],
    domain: Iterable[int],
) -> float:
    """max_{i in D(r)} |candidate_i - reference_i| for one decision row."""
    if len(reference_logits) != len(candidate_logits) or not reference_logits:
        raise MethodologyError("reference and candidate rows must share a nonzero size")
    errors: list[float] = []
    members = set(domain)
    if not members:
        raise MethodologyError("the decision domain must not be empty")
    for i in members:
        left = float(reference_logits[i])
        right = float(candidate_logits[i])
        if not math.isfinite(left) or not math.isfinite(right):
            raise MethodologyError("NaN or Inf is an unconditional failure")
        error = abs(left - right)
        if not math.isfinite(error):
            raise MethodologyError("non-finite absolute error is an unconditional failure")
        errors.append(error)
    return max(errors)


def case_e_d(decision_errors: Iterable[float]) -> float:
    """case_E_D = max over all 8 decisions of decision_local_error."""
    values = [float(v) for v in decision_errors]
    if len(values) != 8:
        raise MethodologyError("each case must report exactly 8 canonical-prefix decisions")
    if not all(math.isfinite(v) and v >= 0.0 for v in values):
        raise MethodologyError("decision-local errors must be finite and nonnegative")
    return max(values)


def derive_e_d(statistical_case_e_ds: Sequence[float], stress_case_e_ds: Sequence[float]) -> float:
    """E_D = max(statistical_E_D, stress_E_D); no rounding, no safety factor.

    statistical arm: exactly the 1896 v4 statistical cases;
    stress arm: exactly the 8 committed selected stress cases.
    """
    if len(statistical_case_e_ds) != V4_STATISTICAL_CASES:
        raise MethodologyError(
            f"the statistical E_D arm requires exactly {V4_STATISTICAL_CASES} cases"
        )
    if len(stress_case_e_ds) != V4_SELECTED_STRESS_CASES:
        raise MethodologyError(
            f"the stress E_D arm requires exactly {V4_SELECTED_STRESS_CASES} cases"
        )
    values = [float(v) for v in statistical_case_e_ds] + [float(v) for v in stress_case_e_ds]
    if not all(math.isfinite(v) and v >= 0.0 for v in values):
        raise MethodologyError("case E_D values must be finite and nonnegative")
    statistical_e_d = max(float(v) for v in statistical_case_e_ds)
    stress_e_d = max(float(v) for v in stress_case_e_ds)
    return max(statistical_e_d, stress_e_d)


# ---------------------------------------------------------------------------
# Issue #95 prediction-aligned design is derived by
# derive_prediction_aligned_design above.  No population-content/tolerance
# qualification contract exists in v4.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Section 9: the frozen semantic gate (exact evaluation order).
# ---------------------------------------------------------------------------


def evaluate_decision(
    reference_logits: Sequence[float],
    candidate_logits: Sequence[float],
    domain: Sequence[int],
    e_d: float,
    *,
    tie_break_identity: str,
    domain_identity: str,
    candidate_emitted_token: int | None = None,
) -> dict[str, Any]:
    """Evaluate ONE canonical-prefix decision under the frozen v4 gate order.

    Order (issue #86 §9; #83 §4.2 fail-closed order):
      3. decision_local_error <= E_D (else DECISION_LOCAL_BOUND_EXCEEDED);
      4. actual candidate full-vocabulary winner j in D(r) (else
         DECISION_DOMAIN_ESCAPE);
      5. m_D = r[a] - r[b_D];
      6. m_D > 2E_D  -> require j == a exactly;
      7. m_D <= 2E_D -> require j in A_ED(r).

    ``candidate_emitted_token`` is the actual emitted full-vocabulary winner
    under the SAME frozen rule; when omitted it is derived from the candidate
    row with the frozen rule (executor-proof-of-rule is the physical
    campaign's obligation, recorded in applicability/provenance).
    """
    _check_v4_frozen_identity(tie_break_identity, argmax_tie_break_identity(), "argmax/tie-break")
    _check_v4_frozen_identity(domain_identity, decision_domain_construction_identity(), "decision-domain construction")
    if len(reference_logits) != len(candidate_logits) or not reference_logits:
        raise MethodologyError("reference and candidate rows must share a nonzero size")
    reference = [float(v) for v in reference_logits]
    candidate = [float(v) for v in candidate_logits]
    if not all(math.isfinite(v) for v in reference + candidate):
        raise MethodologyError("NaN or Inf is an unconditional failure")
    members = set(int(i) for i in domain)
    if not members:
        raise MethodologyError("the decision domain must not be empty")

    a = frozen_argmax(reference)
    if a not in members:
        raise MethodologyError("reference winner escaped the decision domain: invalid frozen D")

    error = decision_local_error(reference, candidate, members)
    record: dict[str, Any] = {
        "decision_local_error_hex": error.hex(),
        "reference_winner_token": a,
    }
    # (3) decision-local bound FIRST, before containment and theorems.
    if not (error <= e_d):
        record["verdict"] = DECISION_LOCAL_BOUND_EXCEEDED
        return record

    j = (
        int(candidate_emitted_token)
        if candidate_emitted_token is not None
        else frozen_argmax(candidate)
    )
    record["candidate_winner_token"] = j
    # (4) containment second — on the ACTUAL emitted full-vocabulary winner.
    if j not in members:
        record["verdict"] = DECISION_DOMAIN_ESCAPE
        return record

    m_d = margin_on_domain(reference, members)
    record["m_d_hex"] = m_d.hex()
    # (6) stable decision.
    if m_d > 2.0 * e_d:
        record["stability"] = "STABLE"
        record["verdict"] = SEMANTIC_PASS if j == a else "STABLE_DECISION_MISMATCH"
        return record
    # (7) unstable decision (m_D <= 2E_D, including exact equality).
    allowed = set(ambiguity_set(reference, members, e_d))
    record["stability"] = "UNSTABLE"
    record["verdict"] = SEMANTIC_PASS if j in allowed else "UNSTABLE_DECISION_INADMISSIBLE"
    return record
