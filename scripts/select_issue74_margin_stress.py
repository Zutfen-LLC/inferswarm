#!/usr/bin/env python3
"""Select the eight issue #74 stress cases from reference-only margins."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Sequence

from issue74_methodology import CONTRACT_ID, canonical_json_bytes, sha256_bytes, sha256_file


def select(
    pool: dict[str, Any], margins: dict[str, Any], commitment: dict[str, Any]
) -> dict[str, Any]:
    if pool.get("schema") != "inferswarm.issue74.margin-stress-pool/1":
        raise ValueError("stress pool schema mismatch")
    if margins.get("schema") != "inferswarm.issue74.reference-margin-summary/1":
        raise ValueError("reference margin schema mismatch")
    if margins.get("contract_id") != CONTRACT_ID:
        raise ValueError("reference margin contract mismatch")
    pool_hash = sha256_bytes(canonical_json_bytes(pool))
    if commitment.get("schema") != "inferswarm.issue74.margin-stress-selection-commitment/1":
        raise ValueError("stress selection commitment schema mismatch")
    if commitment.get("contract_id") != CONTRACT_ID:
        raise ValueError("stress selection commitment contract mismatch")
    if commitment.get("state") != "COMMITTED_BEFORE_MATCHED_REFERENCE_EXECUTION":
        raise ValueError("stress selection rule was not committed before reference execution")
    if commitment.get("candidate_pool_sha256") != pool_hash:
        raise ValueError("stress selection commitment does not bind the exact frozen pool")
    if commitment.get("candidate_observations_forbidden") is not True:
        raise ValueError("stress selection commitment does not forbid candidate observations")
    if commitment.get("selected_case_count") != 8:
        raise ValueError("stress selection commitment must require eight cases")
    if commitment.get("selection_program") != "scripts/select_issue74_margin_stress.py":
        raise ValueError("stress selection commitment program path mismatch")
    if commitment.get("selection_program_sha256") != sha256_file(Path(__file__)):
        raise ValueError("stress selection commitment program hash mismatch")
    if margins.get("stress_pool_sha256") != pool_hash:
        raise ValueError("reference margins do not bind the exact frozen pool")
    pool_cases = {row["case_id"]: row for row in pool["cases"]}
    rows = margins.get("cases")
    if not isinstance(rows, list) or {row.get("case_id") for row in rows} != set(pool_cases):
        raise ValueError("reference margins must cover each pool case exactly once")
    if len(rows) != len(pool_cases):
        raise ValueError("reference margins contain duplicate case IDs")
    ranked = []
    for row in rows:
        margin = float.fromhex(row["top1_margin_hex"])
        if not math.isfinite(margin) or margin <= 0.0:
            raise ValueError("stress selection requires finite positive top-1 margins")
        ranked.append((margin, row["case_id"]))
    ranked.sort(key=lambda item: (item[0], item[1]))
    chosen = ranked[:4] + ranked[-4:]
    if len({case_id for _margin, case_id in chosen}) != 8:
        raise ValueError("smallest and largest selections overlap")
    selected = []
    for rank_group, group in (("four-smallest-positive", ranked[:4]), ("four-largest", ranked[-4:])):
        for margin, case_id in group:
            selected.append({
                "selection_group": rank_group,
                "case": pool_cases[case_id],
                "reference_top1_margin_hex": margin.hex(),
            })
    return {
        "schema": "inferswarm.issue74.margin-stress-selection/1",
        "contract_id": CONTRACT_ID,
        "stress_pool_sha256": pool_hash,
        "selection_commitment_sha256": sha256_bytes(canonical_json_bytes(commitment)),
        "reference_margin_summary_sha256": sha256_bytes(canonical_json_bytes(margins)),
        "selection_inputs": "MATCHED_REFERENCE_MARGINS_ONLY",
        "selection_rule": "sort finite positive margins by (margin,case_id); take first four and last four",
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
