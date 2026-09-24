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

import hashlib
import json
import math
import sys
from pathlib import Path, PurePosixPath
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue241_constants as C
import issue241_dispatch as dispatch

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
    if set(measured_wall_s_by_case) != set(C.FIXTURE_CASES):
        raise ValueError("measured walls must cover exactly four historical cases")
    for case_id, wall in measured_wall_s_by_case.items():
        if (not isinstance(wall, (int, float)) or isinstance(wall, bool)
                or not math.isfinite(wall) or wall <= 0):
            raise ValueError(f"measured wall for {case_id} must be finite and positive")
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


def _custody_bytes(root: Path, rel: Any) -> bytes:
    """Read a regular raw artifact without allowing aliases or traversal."""
    if not isinstance(rel, str) or not rel or PurePosixPath(rel).is_absolute():
        raise ValueError("measurement path must be relative")
    parts = PurePosixPath(rel).parts
    if any(p in (".", "..") for p in parts):
        raise ValueError("measurement path traversal")
    path = root
    for part in parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("measurement symlink/alias forbidden")
    if not path.is_file():
        raise ValueError("measurement raw file missing")
    return path.read_bytes()


def project_from_measurements(receipt_path: Path) -> dict[str, Any]:
    """Project from digest-bound timing files; never perform Phase-4 physical work."""
    receipt_path = Path(receipt_path)
    if receipt_path.is_symlink() or not receipt_path.is_file():
        raise ValueError("measured wall-time receipt missing or aliased")
    receipt = json.loads(receipt_path.read_bytes())
    if (receipt.get("schema") != "inferswarm.issue241.measured-wall-times/1"
            or receipt.get("campaign") != C.CAMPAIGN_ID
            or receipt.get("matched_ngl") not in C.LADDER_NGLS):
        raise ValueError("measured wall-time authority invalid")
    authority = receipt.get("dispatch_authority")
    if (not isinstance(authority, dict)
            or authority.get("schema") != dispatch.AUTHORITY_SCHEMA
            or not isinstance(authority.get("head_sha"), str)
            or len(authority["head_sha"]) != 40
            or authority.get("commenter_association")
            not in dispatch.AUTHORIZED_ASSOCIATIONS
            or not isinstance(authority.get("comment_id"), int)
            or authority.get("comment_id", 0) <= 0
            or dispatch.LEGACY_AUTHORITY_KEYS.intersection(authority)):
        raise ValueError("measured walls missing exact-head dispatch authority")
    measurements = receipt.get("measurements")
    if not isinstance(measurements, dict) or set(measurements) != {"B", "C"}:
        raise ValueError("both measured arms required")
    walls: dict[str, dict[str, float]] = {}
    for arm in ("B", "C"):
        entries = measurements[arm]
        if not isinstance(entries, dict) or set(entries) != set(C.FIXTURE_CASES):
            raise ValueError("exact historical case coverage required")
        walls[arm] = {}
        for case_id, entry in entries.items():
            if not isinstance(entry, dict):
                raise ValueError("measurement entry invalid")
            raw = _custody_bytes(receipt_path.parent, entry.get("timing_raw_path"))
            if hashlib.sha256(raw).hexdigest() != entry.get("timing_raw_sha256"):
                raise ValueError("raw timing digest mismatch")
            run_bytes = _custody_bytes(receipt_path.parent, entry.get("run_receipt_path"))
            if hashlib.sha256(run_bytes).hexdigest() != entry.get("run_receipt_sha256"):
                raise ValueError("comparator run receipt digest mismatch")
            run_receipt = json.loads(run_bytes)
            if (run_receipt.get("schema") != "inferswarm.issue241.comparator-v2-run/2"
                    or run_receipt.get("arm") != arm
                    or run_receipt.get("case_id") != case_id
                    or run_receipt.get("ngl") != receipt["matched_ngl"]
                    or run_receipt.get("dispatch_authority") != authority):
                raise ValueError("measured wall not bound to comparator run and dispatch")
            observed = json.loads(raw)
            wall = observed.get("wall_s")
            if (not isinstance(wall, (int, float)) or isinstance(wall, bool)
                    or not math.isfinite(wall) or wall <= 0
                    or observed.get("arm") != arm or observed.get("case_id") != case_id
                    or entry.get("wall_s") != wall
                    or run_receipt.get("wall_time_s") != wall):
                raise ValueError("claimed wall does not equal raw comparator run wall")
            walls[arm][case_id] = float(wall)
    reference = project_arm(walls["B"])
    candidate = project_arm(walls["C"])
    return {"reference": reference, "candidate": candidate,
            "selected_stress": project_stress(walls["C"]),
            "sequential_total_s": round(reference["central_s"] + candidate["central_s"], 1),
            "matched_ngl": receipt["matched_ngl"]}


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
