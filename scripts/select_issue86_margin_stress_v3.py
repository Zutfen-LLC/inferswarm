#!/usr/bin/env python3
"""Select the eight v3 stress cases from reference-only margins (issue #86).

Eligibility differs from the accepted v2 selector per issue #86 section 2
(prospective change matching the accepted #83 tie semantics):

- non-finite margin (NaN/+Inf/-Inf): unconditional reference failure,
  fails closed immediately (NONFINITE_REFERENCE_MARGIN);
- finite NEGATIVE margin: unconditional reference/order-consistency failure,
  fails closed immediately (NEGATIVE_REFERENCE_MARGIN) — new in v3;
- finite ZERO margin: ELIGIBLE and retained as a real exact-tie stress case;
- finite positive margin: eligible.

Selection: four smallest finite margins INCLUDING zero when present, plus
four largest finite margins; deterministic tie-break by case_id. Requires
at least 8 eligible cases.

The numeric margin definition is UNCHANGED from the accepted v1/v2
pre-registered producer definition (min over all 8 greedy decisions of
fp32(top1_logit - top2_logit)).
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Sequence

from issue74_methodology import CONTRACT_ID, canonical_json_bytes, sha256_bytes, sha256_file
from issue86_v3_methodology import (
    MARGIN_DEFINITION,
    MIN_ELIGIBLE,
    V3_COMMITMENT_STATE,
    V3_ELIGIBILITY,
    V3_MARGIN_SUMMARY_SCHEMA,
    V3_SELECTED_EIGHT_SCHEMA,
    V3_SELECTION_RULE,
    V3_SELECTION_STATE,
    V3_STRESS_COMMITMENT_SCHEMA,
    V3_STRESS_POOL_SCHEMA,
    is_sha256,
)


class NonfiniteReferenceMarginError(ValueError):
    """A reference margin was NaN/+Inf/-Inf: unconditional reference failure."""


class NegativeReferenceMarginError(ValueError):
    """A finite negative reference margin: reference/order-consistency failure."""


def select(pool: dict[str, Any], margins: dict[str, Any], commitment: dict[str, Any]) -> dict[str, Any]:
    if pool.get("schema") != V3_STRESS_POOL_SCHEMA:
        raise ValueError("v3 stress pool schema mismatch")
    if margins.get("schema") != V3_MARGIN_SUMMARY_SCHEMA:
        raise ValueError("v3 reference margin summary schema mismatch")
    if margins.get("contract_id") != CONTRACT_ID:
        raise ValueError("reference margin contract mismatch")
    if margins.get("margin_definition") != MARGIN_DEFINITION:
        raise ValueError("reference margin definition is not the unchanged min-over-8 definition")
    pool_hash = sha256_bytes(canonical_json_bytes(pool))
    if commitment.get("schema") != V3_STRESS_COMMITMENT_SCHEMA:
        raise ValueError("v3 stress selection commitment schema mismatch")
    if commitment.get("contract_id") != CONTRACT_ID:
        raise ValueError("v3 stress selection commitment contract mismatch")
    if commitment.get("state") != V3_COMMITMENT_STATE:
        raise ValueError("v3 stress selection rule was not committed before reference execution")
    if commitment.get("candidate_pool_sha256") != pool_hash:
        raise ValueError("v3 stress selection commitment does not bind the exact frozen pool")
    if commitment.get("candidate_observations_forbidden") is not True:
        raise ValueError("v3 stress selection commitment does not forbid candidate observations")
    if commitment.get("selected_case_count") != 8:
        raise ValueError("v3 stress selection commitment must require eight cases")
    if commitment.get("selection_program") != "scripts/select_issue86_margin_stress_v3.py":
        raise ValueError("v3 stress selection commitment program path mismatch")
    if Path(commitment["selection_program"]).name and commitment.get(
        "selection_program_sha256"
    ) != sha256_file(Path(__file__).resolve().parent / "select_issue86_margin_stress_v3.py"):
        raise ValueError("v3 stress selection commitment program hash mismatch")
    if commitment.get("eligibility_rule") != V3_ELIGIBILITY:
        raise ValueError("v3 stress selection commitment eligibility rule mismatch")
    if commitment.get("minimum_eligible_cases") != MIN_ELIGIBLE:
        raise ValueError("v3 stress selection commitment minimum eligible count mismatch")
    if commitment.get("margin_definition") != MARGIN_DEFINITION:
        raise ValueError("v3 commitment margin definition is not the unchanged min-over-8 definition")
    if commitment.get("selection_rule") != V3_SELECTION_RULE:
        raise ValueError("v3 commitment selection rule mismatch")
    if margins.get("stress_pool_sha256") != pool_hash:
        raise ValueError("v3 reference margins do not bind the exact frozen pool")
    pool_cases = {row["case_id"]: row for row in pool["cases"]}
    rows = margins.get("cases")
    if not isinstance(rows, list) or not rows:
        raise ValueError("v3 reference margins must be a nonempty list")
    if {row.get("case_id") for row in rows} != set(pool_cases) or len(rows) != len(pool_cases):
        raise ValueError("v3 reference margins must cover each pool case exactly once")

    seen_ids: set[str] = set()
    for row in rows:
        case_id = row.get("case_id")
        if not isinstance(case_id, str) or case_id not in pool_cases:
            raise ValueError(f"reference margin row has unknown case id: {case_id!r}")
        if case_id in seen_ids:
            raise ValueError(f"v3 reference margins contain duplicate case ID {case_id!r}")
        seen_ids.add(case_id)
        row_case_sha = row.get("case_sha256")
        if not is_sha256(row_case_sha):
            raise ValueError(f"reference margin row for {case_id!r} has a malformed case_sha256")
        expected_sha = pool_cases[case_id].get("case_sha256")
        if not is_sha256(expected_sha):
            raise ValueError(f"frozen pool case {case_id!r} lacks a well-formed case_sha256")
        if row_case_sha != expected_sha:
            raise ValueError(
                f"reference margin row for {case_id!r} does not bind the exact frozen "
                f"pool case identity (case_sha256 mismatch)"
            )

    eligible: list[tuple[float, str]] = []
    ineligible: list[dict[str, Any]] = []
    for row in rows:
        margin = float.fromhex(row["top1_margin_hex"])
        if not math.isfinite(margin):
            raise NonfiniteReferenceMarginError(
                f"NONFINITE_REFERENCE_MARGIN: reference case {row['case_id']!r} "
                f"produced margin {margin!r}; the reference correctness path emitted "
                "invalid numerical output — selection stops unconditionally"
            )
        if margin < 0.0:
            raise NegativeReferenceMarginError(
                f"NEGATIVE_REFERENCE_MARGIN: reference case {row['case_id']!r} produced "
                f"finite negative margin {margin!r}; an unconditional reference/"
                "order-consistency failure — selection stops unconditionally"
            )
        if margin == 0.0:
            eligible.append((margin, row["case_id"]))
        else:
            eligible.append((margin, row["case_id"]))
    if len(eligible) < MIN_ELIGIBLE:
        raise ValueError(
            f"v3 stress selection requires at least {MIN_ELIGIBLE} eligible cases; "
            f"observed {len(eligible)}"
        )
    eligible.sort(key=lambda item: (item[0], item[1]))
    chosen = eligible[:4] + eligible[-4:]
    if len({case_id for _margin, case_id in chosen}) != 8:
        raise ValueError("smallest and largest selections overlap")
    selected = []
    for rank_group, group in (
        ("four-smallest-including-zero", eligible[:4]),
        ("four-largest", eligible[-4:]),
    ):
        for margin, case_id in group:
            selected.append({
                "selection_group": rank_group,
                "case": pool_cases[case_id],
                "reference_top1_margin_hex": margin.hex(),
                "exact_zero_margin": margin == 0.0,
            })
    return {
        "schema": V3_SELECTED_EIGHT_SCHEMA,
        "contract_id": CONTRACT_ID,
        "margin_definition": MARGIN_DEFINITION,
        "margin_definition_unchanged_from": "v1 pre-registered producer definition (FreeToken 29e04d0)",
        "stress_pool_sha256": pool_hash,
        "selection_commitment_sha256": sha256_bytes(canonical_json_bytes(commitment)),
        "reference_margin_summary_sha256": sha256_bytes(canonical_json_bytes(margins)),
        "selection_inputs": "MATCHED_REFERENCE_MARGINS_ONLY",
        "eligibility_rule": V3_ELIGIBILITY,
        "selection_rule": V3_SELECTION_RULE,
        "minimum_eligible_cases": MIN_ELIGIBLE,
        "eligible_case_count": len(eligible),
        "ineligible_case_count": len(ineligible),
        "ineligible_cases": ineligible,
        "selected_count": 8,
        "selected": selected,
        "state": V3_SELECTION_STATE,
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
