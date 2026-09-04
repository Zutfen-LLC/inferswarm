#!/usr/bin/env python3
"""Select the eight issue #76 v2 stress cases from reference-only margins.

Differences from the v1 selector (scripts/select_issue74_margin_stress.py),
which is retained unchanged as historical evidence:

- eligibility: a pool case is stress-selection-eligible only when its
  margin is finite AND strictly positive. A FINITE zero or negative margin
  is unsuitable for stress selection: the case is retained as reference
  evidence but is INELIGIBLE, not a fatal pool-wide error. A NON-FINITE
  reference margin (NaN, +Inf, -Inf) means the reference correctness path
  produced invalid numerical output and is an UNCONDITIONAL reference
  correctness failure: the selector fails closed immediately with
  NONFINITE_REFERENCE_MARGIN and never continues selection;
- reference-margin binding: every reference-margin row must carry the
  exact frozen pool case identity — its case_id must exist in the frozen
  pool, its case_sha256 must equal the frozen pool case's case_sha256,
  each frozen case must be covered exactly once, and duplicate rows are
  rejected;
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


def _is_sha256_hex(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(ch in "0123456789abcdef" for ch in value)
    )


class NonfiniteReferenceMarginError(ValueError):
    """A reference margin was NaN/+Inf/-Inf: the reference correctness path
    produced invalid numerical output. Fail closed; never convert a
    non-finite reference value into an ineligible case count."""


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
    # Bind every reference-margin row to the exact frozen case identity:
    # case_id alone is NOT sufficient — the row's case_sha256 must equal the
    # frozen pool case's case_sha256 (chain: margin summary -> exact v2 pool
    # SHA -> exact case-ID set -> exact case_id->case_sha256 mapping -> value).
    seen_ids: set[str] = set()
    for row in rows:
        case_id = row.get("case_id")
        if not isinstance(case_id, str) or case_id not in pool_cases:
            raise ValueError(f"reference margin row has unknown case id: {case_id!r}")
        if case_id in seen_ids:
            raise ValueError(f"v2 reference margins contain duplicate case ID {case_id!r}")
        seen_ids.add(case_id)
        row_case_sha = row.get("case_sha256")
        if row_case_sha is None:
            raise ValueError(f"reference margin row for {case_id!r} is missing case_sha256")
        if not _is_sha256_hex(row_case_sha):
            raise ValueError(f"reference margin row for {case_id!r} has a malformed case_sha256")
        expected_sha = pool_cases[case_id].get("case_sha256")
        if not _is_sha256_hex(expected_sha):
            raise ValueError(f"frozen pool case {case_id!r} lacks a well-formed case_sha256")
        if row_case_sha != expected_sha:
            raise ValueError(
                f"reference margin row for {case_id!r} does not bind the exact frozen "
                f"pool case identity (case_sha256 mismatch: got {row_case_sha}, "
                f"frozen pool has {expected_sha})"
            )
    eligible: list[tuple[float, str]] = []
    ineligible: list[dict[str, Any]] = []
    for row in rows:
        margin = float.fromhex(row["top1_margin_hex"])
        if not math.isfinite(margin):
            raise NonfiniteReferenceMarginError(
                "NONFINITE_REFERENCE_MARGIN: reference case "
                f"{row['case_id']!r} produced margin {margin!r} "
                f"({row['top1_margin_hex']!r}); the reference correctness path "
                "emitted invalid numerical output — selection stops "
                "unconditionally (non-finite is NOT an ineligible case)"
            )
        if margin > 0.0:
            eligible.append((margin, row["case_id"]))
        else:
            ineligible.append({
                "case_id": row["case_id"],
                "case_sha256": row["case_sha256"],
                "top1_margin_hex": row["top1_margin_hex"],
                "reason": "finite-nonpositive-margin-ineligible",
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
        "eligibility_rule": (
            "eligible iff margin is finite and > 0; finite <= 0 is ineligible "
            "(retained as reference evidence); a non-finite margin (NaN/+Inf/"
            "-Inf) is an unconditional reference correctness failure "
            "(NONFINITE_REFERENCE_MARGIN) and stops selection"
        ),
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
