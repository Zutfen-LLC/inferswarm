#!/usr/bin/env python3
"""Select the eight issue #76 v2 stress cases from reference-only margins.

Differences from the v1 selector (scripts/select_issue74_margin_stress.py),
which is retained unchanged as historical evidence:

- eligibility: a pool case is stress-selection-eligible only when its margin
  is finite AND strictly positive. Zero/nonpositive-margin cases are retained
  as reference evidence but are INELIGIBLE, not a fatal pool-wide error;
- minimum eligible count: at least 8 eligible cases are required;
- selection: four smallest positive margins + four largest positive margins
  from eligible cases only.

The numeric margin definition is UNCHANGED from the v1 pre-registered
producer definition:

    positive_top1_margin(case) = min over all 8 greedy steps of
                                 fp32(top1_logit - top2_logit)

A tie is a zero margin. No epsilon, no tie-breaking by token id or rank.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Sequence

from issue74_methodology import CONTRACT_ID, canonical_json_bytes, sha256_bytes, sha256_file

V2_POOL_SCHEMA = "inferswarm.issue76.margin-stress-pool/2"
V2_COMMITMENT_SCHEMA = "inferswarm.issue76.margin-stress-selection-commitment/2"
V2_MARGIN_SUMMARY_SCHEMA = "inferswarm.issue76.reference-margin-summary/2"
V2_SELECTION_SCHEMA = "inferswarm.issue76.margin-stress-selection/2"
MIN_ELIGIBLE = 8
MARGIN_DEFINITION = "min over all 8 greedy steps of fp32(top1_logit - top2_logit)"


def select(pool: dict[str, Any], margins: dict[str, Any], commitment: dict[str, Any]) -> dict[str, Any]:
    if pool.get("schema") != V2_POOL_SCHEMA:
        raise ValueError("v2 stress pool schema mismatch")
    if margins.get("schema") != V2_MARGIN_SUMMARY_SCHEMA:
        raise ValueError("v2 reference margin schema mismatch")
    if margins.get("contract_id") != CONTRACT_ID:
        raise ValueError("reference margin contract mismatch")
    if margins.get("margin_definition") != MARGIN_DEFINITION:
        raise ValueError("reference margin definition is not the unchanged min-over-8 definition")
    pool_hash = sha256_bytes(canonical_json_bytes(pool))
    if commitment.get("schema") != V2_COMMITMENT_SCHEMA:
        raise ValueError("v2 stress selection commitment schema mismatch")
    if commitment.get("contract_id") != CONTRACT_ID:
        raise ValueError("v2 stress selection commitment contract mismatch")
    if commitment.get("state") != "COMMITTED_BEFORE_MATCHED_REFERENCE_EXECUTION":
        raise ValueError("v2 stress selection rule was not committed before reference execution")
    if commitment.get("candidate_pool_sha256") != pool_hash:
        raise ValueError("v2 stress selection commitment does not bind the exact frozen pool")
    if commitment.get("candidate_observations_forbidden") is not True:
        raise ValueError("v2 stress selection commitment does not forbid candidate observations")
    if commitment.get("selected_case_count") != 8:
        raise ValueError("v2 stress selection commitment must require eight cases")
    if commitment.get("selection_program") != "scripts/select_issue76_margin_stress_v2.py":
        raise ValueError("v2 stress selection commitment program path mismatch")
    if commitment.get("selection_program_sha256") != sha256_file(Path(__file__)):
        raise ValueError("v2 stress selection commitment program hash mismatch")
    if commitment.get("eligibility_rule") != "margin is finite AND margin > 0":
        raise ValueError("v2 stress selection commitment eligibility rule mismatch")
    if commitment.get("minimum_eligible_cases") != MIN_ELIGIBLE:
        raise ValueError("v2 stress selection commitment minimum eligible count mismatch")
    if commitment.get("margin_definition") != MARGIN_DEFINITION:
        raise ValueError("v2 commitment margin definition is not the unchanged min-over-8 definition")
    if margins.get("stress_pool_sha256") != pool_hash:
        raise ValueError("v2 reference margins do not bind the exact frozen pool")
    pool_cases = {row["case_id"]: row for row in pool["cases"]}
    rows = margins.get("cases")
    if not isinstance(rows, list) or {row.get("case_id") for row in rows} != set(pool_cases):
        raise ValueError("v2 reference margins must cover each pool case exactly once")
    if len(rows) != len(pool_cases):
        raise ValueError("v2 reference margins contain duplicate case IDs")
    eligible: list[tuple[float, str]] = []
    ineligible: list[dict[str, Any]] = []
    for row in rows:
        margin = float.fromhex(row["top1_margin_hex"])
        if math.isfinite(margin) and margin > 0.0:
            eligible.append((margin, row["case_id"]))
        else:
            ineligible.append({
                "case_id": row["case_id"],
                "top1_margin_hex": row["top1_margin_hex"],
                "reason": "nonpositive-or-nonfinite-margin-ineligible",
            })
    if len(eligible) < MIN_ELIGIBLE:
        raise ValueError(
            f"v2 stress selection requires at least {MIN_ELIGIBLE} eligible cases; "
            f"observed {len(eligible)}"
        )
    eligible.sort(key=lambda item: (item[0], item[1]))
    chosen = eligible[:4] + eligible[-4:]
    if len({case_id for _margin, case_id in chosen}) != 8:
        raise ValueError("smallest and largest selections overlap")
    selected = []
    for rank_group, group in (("four-smallest-positive", eligible[:4]), ("four-largest-positive", eligible[-4:])):
        for margin, case_id in group:
            selected.append({
                "selection_group": rank_group,
                "case": pool_cases[case_id],
                "reference_top1_margin_hex": margin.hex(),
            })
    return {
        "schema": V2_SELECTION_SCHEMA,
        "contract_id": CONTRACT_ID,
        "margin_definition": MARGIN_DEFINITION,
        "margin_definition_unchanged_from": "v1 pre-registered producer definition (FreeToken 29e04d0)",
        "stress_pool_sha256": pool_hash,
        "selection_commitment_sha256": sha256_bytes(canonical_json_bytes(commitment)),
        "reference_margin_summary_sha256": sha256_bytes(canonical_json_bytes(margins)),
        "selection_inputs": "MATCHED_REFERENCE_MARGINS_ONLY",
        "eligibility_rule": "margin is finite AND margin > 0; ineligible cases retained as reference evidence",
        "selection_rule": "sort eligible positive margins by (margin,case_id); take first four and last four",
        "minimum_eligible_cases": MIN_ELIGIBLE,
        "eligible_case_count": len(eligible),
        "ineligible_case_count": len(ineligible),
        "ineligible_cases": ineligible,
        "selected_count": 8,
        "selected": selected,
        "state": "FROZEN_AFTER_MATCHED_REFERENCE_BEFORE_HETEROGENEOUS_CANDIDATE",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", required=True, type=Path)
    parser.add_argument("--reference-margins", required=True, type=Path)
    parser.add_argument("--selection-commitment", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    result = select(
        json.loads(args.pool.read_text()),
        json.loads(args.reference_margins.read_text()),
        json.loads(args.selection_commitment.read_text()),
    )
    args.out.write_bytes(canonical_json_bytes(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
