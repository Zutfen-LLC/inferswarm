#!/usr/bin/env python3
"""InferSwarm issue #109: freeze the v5 stress-selection commitment.

Creates the PUBLIC commitment binding the frozen v5 selector program,
eligibility rule, and margin definition to the exact frozen p109-* pool,
BEFORE any reference observation. The eligibility/selection rule and margin
definition are unchanged from the accepted v4 (issue #86/#95) rule — ADR
0012 revises only the statistical construction and metric tiers, not stress
selection.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Sequence

from issue109_v5_methodology import (
    CONTRACT_ID,
    MARGIN_DEFINITION,
    MIN_ELIGIBLE,
    V5_COMMITMENT_STATE,
    V5_ELIGIBILITY,
    V5_SELECTED_STRESS_CASES,
    V5_SELECTION_RULE,
    V5_STRESS_COMMITMENT_SCHEMA,
    V5_STRESS_POOL_SCHEMA,
)
from issue74_methodology import canonical_json_bytes, sha256_bytes, sha256_file

SELECTOR_PATH = "scripts/select_issue109_margin_stress_v5.py"


def build_commitment(pool: dict[str, Any]) -> dict[str, Any]:
    if pool.get("schema") != V5_STRESS_POOL_SCHEMA:
        raise ValueError("v5 stress pool schema mismatch")
    selector = Path(__file__).resolve().parents[1] / SELECTOR_PATH
    return {
        "schema": V5_STRESS_COMMITMENT_SCHEMA,
        "contract_id": CONTRACT_ID,
        "state": V5_COMMITMENT_STATE,
        "candidate_pool_sha256": sha256_bytes(canonical_json_bytes(pool)),
        "candidate_pool_case_count": len(pool["cases"]),
        "candidate_observations_forbidden": True,
        "selected_case_count": V5_SELECTED_STRESS_CASES,
        "selection_program": SELECTOR_PATH,
        "selection_program_sha256": sha256_file(selector),
        "eligibility_rule": V5_ELIGIBILITY,
        "selection_rule": V5_SELECTION_RULE,
        "minimum_eligible_cases": MIN_ELIGIBLE,
        "margin_definition": MARGIN_DEFINITION,
        "margin_inputs": "MATCHED_REFERENCE_MARGINS_ONLY",
        "tie_break": "deterministic tie-break by case_id",
        "historical_inputs_forbidden": (
            "no v1/v2/v3/v4 observed margin or selected-case identity may be used "
            "as a v5 selection input"
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    import json

    commitment = build_commitment(json.loads(args.pool.read_text()))
    args.out.write_bytes(canonical_json_bytes(commitment))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
