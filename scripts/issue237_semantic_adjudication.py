#!/usr/bin/env python3
"""Semantic adjudication tooling for the future physical R8-I campaign.

Applies the frozen decision-stability gate (ADR 0010 §1.3) to ONE
canonical-prefix decision row pair. CPU-only, deterministic, fail-closed.

Gate order (frozen; never reordered):
  1. exact-integrity applicability was proven upstream (Layer 1);
  2. decision-local bound: max_{i in D}|candidate_i - reference_i| <= E_D
     else DECISION_LOCAL_BOUND_EXCEEDED;
  3. containment: actual candidate full-vocabulary winner j in D
     else DECISION_DOMAIN_ESCAPE;
  4a. m_D > 2E_D (STABLE): require j == reference winner a exactly
      else STABLE_DECISION_MISMATCH;
  4b. m_D <= 2E_D (UNSTABLE): require j in A_ED(r)
      else UNSTABLE_DECISION_INADMISSIBLE.

D is the FULL VOCABULARY for v1, so containment can only fail on a
non-finite row (structural), and A_ED uses the same frozen rule.
Post-divergence free-running rows are handled by the campaign reducer as
diagnostic-only; they never re-enter this gate as same-input evidence.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

import issue237_methodology as m  # noqa: E402

SEMANTIC_ROW_SCHEMA = "inferswarm.issue237.semantic-row/1"


class AdjudicationError(RuntimeError):
    pass


def _finite_row(values: Sequence[float], label: str) -> list[float]:
    row = []
    for v in values:
        f = float(v)
        if not math.isfinite(f):
            raise AdjudicationError(f"{label} row contains NaN/Inf: unconditional failure")
        row.append(f)
    return row


def evaluate_decision(
    reference_logits: Sequence[float],
    candidate_logits: Sequence[float],
    e_d: float,
    *,
    candidate_emitted_token: int | None = None,
) -> dict[str, Any]:
    """Evaluate one acceptance-bearing decision; returns the semantic row."""
    if len(reference_logits) != len(candidate_logits) or not reference_logits:
        raise AdjudicationError("reference/candidate rows must share a nonzero size")
    if not math.isfinite(e_d) or e_d < 0.0:
        raise AdjudicationError("E_D must be finite and nonnegative")
    reference = _finite_row(reference_logits, "reference")
    candidate = _finite_row(candidate_logits, "candidate")
    if len(reference) != m.VOCAB_SIZE:
        raise AdjudicationError(
            f"row size {len(reference)} != frozen vocabulary {m.VOCAB_SIZE}"
        )

    a = m.frozen_argmax(reference)
    # D = full vocabulary (no subset dodge)
    domain = m.decision_domain_full_vocab(len(reference))

    # (2) decision-local bound FIRST
    error = m.decision_local_error(reference, candidate, domain)
    row: dict[str, Any] = {
        "schema": SEMANTIC_ROW_SCHEMA,
        "decision_local_error_hex": error.hex(),
        "reference_winner_token": a,
        "domain_rule": m.DECISION_DOMAIN_RULE,
        "tie_rule": m.TIE_RULE,
    }
    if not (error <= e_d):
        row["verdict"] = m.DECISION_LOCAL_BOUND_EXCEEDED
        return row

    j = (
        int(candidate_emitted_token)
        if candidate_emitted_token is not None
        else m.frozen_argmax(candidate)
    )
    row["candidate_winner_token"] = j

    # (3) containment (structurally available only for non-finite rows at v1)
    if j not in set(domain):
        row["verdict"] = m.DECISION_DOMAIN_ESCAPE
        return row

    m_d = m.margin_on_domain(reference, domain)
    row["m_d_hex"] = m_d.hex()

    # (4a) stable
    if m_d > 2.0 * e_d:
        row["stability"] = "STABLE"
        row["verdict"] = (
            m.SEMANTIC_PASS if j == a else "STABLE_DECISION_MISMATCH"
        )
        return row
    # (4b) unstable
    allowed = set(m.ambiguity_set(reference, domain, e_d))
    row["stability"] = "UNSTABLE"
    row["ambiguity_membership"] = j in allowed
    row["verdict"] = (
        m.SEMANTIC_PASS if j in allowed else "UNSTABLE_DECISION_INADMISSIBLE"
    )
    return row


def evaluate_case(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Case-level rollup over exactly 8 decisions; any non-PASS fails the case."""
    if len(rows) != m.DECISION_COUNT:
        raise AdjudicationError(
            f"each case must report exactly {m.DECISION_COUNT} decisions"
        )
    verdicts = [r.get("verdict") for r in rows]
    return {
        "schema": "inferswarm.issue237.semantic-case/1",
        "case_verdict": (
            m.SEMANTIC_PASS if all(v == m.SEMANTIC_PASS for v in verdicts)
            else next(v for v in verdicts if v != m.SEMANTIC_PASS)
        ),
        "decision_verdicts": verdicts,
        "stable_decisions": sum(1 for r in rows if r.get("stability") == "STABLE"),
        "unstable_decisions": sum(1 for r in rows if r.get("stability") == "UNSTABLE"),
        "case_e_d_hex": m.case_e_d(
            [float.fromhex(r["decision_local_error_hex"]) for r in rows]
        ).hex(),
    }
