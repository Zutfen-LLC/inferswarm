#!/usr/bin/env python3
"""InferSwarm issue #86: freeze the v4 stress-selection commitment.

Creates the PUBLIC commitment binding the frozen v4 selector program,
eligibility rule, and margin definition to the exact frozen p95-* pool,
BEFORE any reference observation. Mirrors the accepted v2 commitment shape
(issue #76 v2 / PR #78) with v4 eligibility per issue #86 section 2:

- non-finite margin: unconditional reference failure (fail closed);
- finite negative margin: unconditional reference/order-consistency failure;
- finite ZERO margin: ELIGIBLE exact-tie stress case (v4 change);
- finite positive margin: eligible.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Sequence

from issue95_v4_methodology import CONTRACT_ID
from issue74_methodology import canonical_json_bytes, sha256_bytes, sha256_file
from issue95_v4_methodology import (
    MARGIN_DEFINITION,
    MIN_ELIGIBLE,
    V4_COMMITMENT_STATE,
    V4_ELIGIBILITY,
    V4_SELECTION_RULE,
    V4_STRESS_COMMITMENT_SCHEMA,
    V4_STRESS_POOL_SCHEMA,
)

SELECTOR_PATH = "scripts/select_issue95_margin_stress_v4.py"


def build_commitment(pool: dict[str, Any]) -> dict[str, Any]:
    if pool.get("schema") != V4_STRESS_POOL_SCHEMA:
        raise ValueError("v4 stress pool schema mismatch")
    selector = Path(__file__).resolve().parents[1] / SELECTOR_PATH
    return {
        "schema": V4_STRESS_COMMITMENT_SCHEMA,
        "contract_id": CONTRACT_ID,
        "state": V4_COMMITMENT_STATE,
        "candidate_pool_sha256": sha256_bytes(canonical_json_bytes(pool)),
        "candidate_pool_case_count": 48,
        "candidate_observations_forbidden": True,
        "selected_case_count": 8,
        "selection_program": SELECTOR_PATH,
        "selection_program_sha256": sha256_file(selector),
        "eligibility_rule": V4_ELIGIBILITY,
        "selection_rule": V4_SELECTION_RULE,
        "minimum_eligible_cases": MIN_ELIGIBLE,
        "margin_definition": MARGIN_DEFINITION,
        "margin_inputs": "MATCHED_REFERENCE_MARGINS_ONLY",
        "tie_break": "deterministic tie-break by case_id",
        "historical_inputs_forbidden": (
            "no v1/v2 observed margin or selected-case identity may be used "
            "as a v4 selection input"
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
