#!/usr/bin/env python3
"""Issue #241 Phase 4: practicality projection and disposition.

Projects the full Phase-A cost from MEASURED wall times (historical
excluded fixtures at the selected matched placement, comparator/2
semantics: ONE request per case per arm) — never from nominal
arithmetic. Emits exactly one disposition from the frozen vocabulary:

  R8I3_RX580_COMPARATOR_V2_PRACTICAL     same-host identities valid,
                                         matched placement stable,
                                         comparator/2 deterministic,
                                         projected candidate Phase A
                                         <= ~24 h central, no blockers;
  R8I3_RX580_INFRASTRUCTURE_BLOCKED      host/GPU cannot sustain the
                                         subject or multi-day projection
                                         from physical infrastructure;
  R8I3_RX580_RUNTIME_BLOCKED             pinned Vulkan/runtime path
                                         cannot execute the RX 580
                                         subject correctly enough;
  R8I3_COMPARATOR_V2_BLOCKED             continuous observer cannot be
                                         implemented/adjudicated
                                         honestly.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue241_constants as C

SCHEMA = "inferswarm.issue241.phase4-practicality/1"

# Low/central/high spread over the measured per-request wall: the central
# estimate is the measured value; the band is a fixed ±25% projection
# spread retained with the projection (labeled ESTIMATED per
# BENCHMARKING.md), not an observed variance.
BAND_FRACTION = 0.25


def project_arm(measured_wall_s_by_case: dict[str, float]) -> dict[str, Any]:
    """Project one arm's Phase-A total from measured per-case walls.

    comparator/2: ONE request per case; 8 decisions per request.
    """
    missing = [c for c in C.FIXTURE_CASES if c not in measured_wall_s_by_case]
    if missing:
        raise ValueError(f"measured walls missing for {missing}")
    for case_id, wall in measured_wall_s_by_case.items():
        if not isinstance(wall, (int, float)) or wall <= 0:
            raise ValueError(f"measured wall for {case_id} must be positive")
    total = 0.0
    per_regime: dict[str, Any] = {}
    for regime, count in C.R8J_REALIZED_REGIME_COUNTS.items():
        case_id = next(c for c, r in C.REGIME_OF_CASE.items() if r == regime)
        wall = float(measured_wall_s_by_case[case_id])
        regime_s = count * wall
        per_regime[regime] = {
            "draws": count, "case": case_id,
            "measured_wall_s_per_request": wall,
            "projected_s": round(regime_s, 1),
        }
        total += regime_s
    return {
        "requests_per_case": 1,
        "population_draws": sum(C.R8J_REALIZED_REGIME_COUNTS.values()),
        "per_regime": per_regime,
        "central_s": round(total, 1),
        "low_s": round(total * (1 - BAND_FRACTION), 1),
        "high_s": round(total * (1 + BAND_FRACTION), 1),
    }


def project_stress(measured_wall_s_by_case: dict[str, float]) -> dict[str, Any]:
    """Selected-stress total: 8 draws, one request each, regime-matched.

    Uses the long regime (worst-case among measured) — a bound, not a
    measurement of the still-sealed stress population.
    """
    worst_regime_case = max(
        C.FIXTURE_CASES, key=lambda c: measured_wall_s_by_case[c])
    wall = float(measured_wall_s_by_case[worst_regime_case])
    total = C.R8J_SELECTED_STRESS_COUNT * wall
    return {
        "draws": C.R8J_SELECTED_STRESS_COUNT,
        "bound_case": worst_regime_case,
        "measured_wall_s_per_request": wall,
        "projected_s": round(total, 1),
    }


def derive_disposition(*, census_valid: bool,
                       census_problems: list[str] | None = None,
                       placement: dict[str, Any] | None,
                       comparator_v2: dict[str, Any] | None,
                       candidate_projection: dict[str, Any] | None,
                       infrastructure_blockers: list[str] | None = None,
                       runtime_blockers: list[str] | None = None) -> dict[str, Any]:
    """Emit exactly one disposition from the frozen vocabulary."""
    census_problems = list(census_problems or [])
    infrastructure_blockers = list(infrastructure_blockers or [])
    runtime_blockers = list(runtime_blockers or [])

    def terminal(disposition: str, detail: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema": SCHEMA, "campaign": C.CAMPAIGN_ID,
            "disposition": disposition, **detail,
        }

    if not census_valid:
        return terminal(C.DISPOSITION_INFRA, {
            "reason": "same-host identity census invalid",
            "census_problems": census_problems,
        })
    if infrastructure_blockers:
        return terminal(C.DISPOSITION_INFRA, {
            "reason": "host/GPU stability or infrastructure blocker",
            "infrastructure_blockers": infrastructure_blockers,
        })
    if runtime_blockers:
        return terminal(C.DISPOSITION_RUNTIME, {
            "reason": "pinned Vulkan/runtime path cannot execute the subject",
            "runtime_blockers": runtime_blockers,
        })
    if not isinstance(placement, dict) or placement.get("placement_blocked"):
        return terminal(C.DISPOSITION_RUNTIME, {
            "reason": "no stable matched placement",
            "placement": placement,
        })
    if not isinstance(comparator_v2, dict) or not comparator_v2.get("validated"):
        return terminal(C.DISPOSITION_V2_BLOCKED, {
            "reason": "continuous observer not prospectively validated",
            "comparator_v2": comparator_v2,
        })
    if not isinstance(candidate_projection, dict):
        raise ValueError("candidate projection required for the practical gate")
    central = candidate_projection.get("central_s")
    if not isinstance(central, (int, float)):
        raise ValueError("candidate projection lacks a central estimate")
    practical = central <= C.PRACTICAL_CANDIDATE_PHASE_A_BOUND_S
    return terminal(
        C.DISPOSITION_PRACTICAL if practical else C.DISPOSITION_INFRA,
        {
            "reason": ("projected candidate Phase A within the ~24 h bound"
                       if practical else
                       "projected candidate Phase A exceeds the ~24 h bound"),
            "matched_ngl": placement.get("matched_ngl"),
            "candidate_phase_a": candidate_projection,
            "bound_s": C.PRACTICAL_CANDIDATE_PHASE_A_BOUND_S,
        })


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--inputs", type=Path, required=True,
                    help="JSON with measured walls and gate inputs")
    args = ap.parse_args(argv)
    data = json.loads(args.inputs.read_text())
    walls = data["measured_wall_s_by_case"]
    out = {
        "reference": project_arm(walls["reference"]),
        "candidate": project_arm(walls["candidate"]),
        "selected_stress": project_stress(walls["candidate"]),
        "sequential_total_s": round(
            project_arm(walls["reference"])["central_s"]
            + project_arm(walls["candidate"])["central_s"], 1),
    }
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
