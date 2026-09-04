#!/usr/bin/env python3
"""Issue #83: re-derive the first-divergence diagnostic aggregates from the
committed evidence JSONs.

Pure stdlib (no numpy/torch/subprocess) so it runs on any host including the
torch-free coordinator. Every aggregate is derived from the evidence files;
nothing is set by constant. A hard reproduction gate first re-derives the
historical #81 semantic-fail counts (236/576 statistical, 4/8 stress) and
aborts on mismatch, so parsing/ordering mistakes cannot poison conclusions.

Usage:
    python3 scripts/issue83_first_divergence.py [--evidence-dir DIR]

Exit code 0 with a JSON aggregate document on stdout; nonzero on any
reproduction-gate or consistency failure (fail-closed).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = (REPO_ROOT / "docs" / "qualification"
                    / "gemma4-12b-it-semantic-83" / "evidence")

# Historical issue-81 terminal verdict constants (issue #81 report / PR #82;
# reproduced here ONLY as the reproduction gate, not as new thresholds).
HISTORICAL_STATISTICAL_TOTAL = 576
HISTORICAL_STATISTICAL_MISMATCH = 236
HISTORICAL_STRESS_TOTAL = 8
HISTORICAL_STRESS_MISMATCH = 4

CAPTURE_STEPS = (0, 1, 3, 7)


class ReproductionGateError(SystemExit):
    pass


def load(evidence_dir: Path, name: str) -> dict:
    return json.loads((evidence_dir / name).read_text())


def percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        raise ReproductionGateError(1)
    idx = min(len(sorted_vals) - 1, max(0, int(math.ceil(p * len(sorted_vals))) - 1))
    return sorted_vals[idx]


def reproduce_gate(stat: dict, stress: dict) -> None:
    """Historical counts must reproduce exactly before anything interpretive."""
    stat_div = sum(1 for c in stat["cases"]
                   if c["first_divergence_step"] is not None)
    stress_div = sum(1 for c in stress["cases"]
                     if c["first_divergence_step"] is not None)
    if len(stat["cases"]) != HISTORICAL_STATISTICAL_TOTAL:
        raise ReproductionGateError(
            f"gate: statistical case count {len(stat['cases'])} != "
            f"{HISTORICAL_STATISTICAL_TOTAL}")
    if stat_div != HISTORICAL_STATISTICAL_MISMATCH:
        raise ReproductionGateError(
            f"gate: statistical diverged {stat_div} != "
            f"{HISTORICAL_STATISTICAL_MISMATCH}")
    if len(stress["cases"]) != HISTORICAL_STRESS_TOTAL:
        raise ReproductionGateError(
            f"gate: stress case count {len(stress['cases'])} != "
            f"{HISTORICAL_STRESS_TOTAL}")
    if stress_div != HISTORICAL_STRESS_MISMATCH:
        raise ReproductionGateError(
            f"gate: stress diverged {stress_div} != "
            f"{HISTORICAL_STRESS_MISMATCH}")
    # token-level divergence definition cross-check: a diverged case must
    # diverge exactly at first differing step.
    for dec in (stat, stress):
        for c in dec["cases"]:
            t = c["first_divergence_step"]
            r, ch = c["ref_tokens"], c["chain_tokens"]
            if len(r) != len(ch):
                raise ReproductionGateError(f"gate: token length {c['case_id']}")
            first = next((i for i, (x, y) in enumerate(zip(r, ch)) if x != y),
                         None)
            if first != t:
                raise ReproductionGateError(
                    f"gate: first-divergence mismatch {c['case_id']}: "
                    f"{t} vs {first}")
            if t is not None and r[:t] != ch[:t]:
                raise ReproductionGateError(
                    f"gate: prefix not exact before divergence {c['case_id']}")


def divergence_details(stat: dict, stress: dict) -> dict:
    """Aggregate first-divergence decision diagnostics."""
    hist: dict[int, int] = {}
    at_captured = 0
    total_div = 0
    for dec in (stat, stress):
        for c in dec["cases"]:
            t = c["first_divergence_step"]
            if t is None:
                continue
            total_div += 1
            hist[t] = hist.get(t, 0) + 1
            if t in CAPTURE_STEPS:
                at_captured += 1
    return {
        "diverged_cases": total_div,
        "first_divergence_step_histogram": dict(sorted(hist.items())),
        "divergences_at_captured_steps": at_captured,
        "divergences_at_uncaptured_steps": total_div - at_captured,
    }


def row_aggregates(metrics: dict, local: dict) -> dict:
    """Aggregate same-prefix full-vocab error metrics + decision-local errors."""
    mby = {(r["case_id"], r["step"]): r for r in metrics["rows"]}
    lrows = local["rows"]
    same = [r for r in lrows if r["same_prefix"]]
    div = [r for r in lrows if r["is_first_divergence_step"]]

    # cross-check the two evidence files describe the same rows
    for r in lrows:
        m = mby.get((r["case_id"], r["step"]))
        if m is None:
            raise ReproductionGateError(
                f"gate: row {r['case_id']} s{r['step']} missing in metrics")
        if m["same_prefix"] != r["same_prefix"] or \
                m["is_first_divergence_step"] != r["is_first_divergence_step"]:
            raise ReproductionGateError(
                f"gate: row classification mismatch {r['case_id']} "
                f"s{r['step']}")

    max_abs = sorted(r["max_abs_err"] for r in metrics["rows"]
                     if r["same_prefix"])
    never = sorted(r["max_abs_err"] for r in metrics["rows"]
                   if r["same_prefix"] and r["tstar"] is None)
    margins = sorted(r["ref_margin"] for r in same)

    ranks: dict[int, int] = {}
    for r in div:
        k = r["cand_rank_under_ref"]
        ranks[k] = ranks.get(k, 0) + 1
    admissible = sum(1 for r in div
                     if r["gap_top1_to_cand"]
                     <= r["err_top1"] + r["err_cand"] + 1e-9)
    # Theorem-1 empirical check: no same-prefix flip may occur with
    # margin > 2 * max(err_top1, err_top2) on its own row.
    thm_violations = sum(
        1 for r in same
        if r["argmax_flip"] and r["ref_margin"]
        > 2 * max(r["err_top1"], r["err_top2"]) + 1e-9)
    flips_before_tstar = sum(
        1 for r in same
        if r["argmax_flip"] and r["tstar"] is not None
        and r["step"] < r["tstar"])

    never_rows = [r for r in same if r["tstar"] is None]
    never_flips = sum(1 for r in never_rows if r["argmax_flip"])

    def yield_for(E: float) -> int:
        return sum(1 for m in margins if m > 2 * E)

    emp_E = max_abs[-1] if max_abs else float("nan")
    return {
        "same_prefix_rows": len(same),
        "first_divergence_rows": len(div),
        "full_domain_max_abs": {
            "p50": percentile(max_abs, 0.50),
            "p90": percentile(max_abs, 0.90),
            "p99": percentile(max_abs, 0.99),
            "max": emp_E,
        },
        "never_diverged_rows": len(never_rows),
        "never_diverged_max_abs_max": never[-1] if never else None,
        "never_diverged_argmax_flips": never_flips,
        "ref_margin_same_prefix": {
            "p50": percentile(margins, 0.50),
            "p90": percentile(margins, 0.90),
            "max": margins[-1] if margins else None,
        },
        "candidate_rank_under_ref_at_divergence": dict(sorted(ranks.items())),
        "flips_admissible_under_row_envelope": admissible,
        "flips_inadmissible": len(div) - admissible,
        "theorem1_empirical_violations": thm_violations,
        "argmax_flips_strictly_before_first_divergence": flips_before_tstar,
        "stability_certification_yield": {
            "note": "rows with margin > 2E, computed over same-prefix rows; "
                    "descriptive only — no threshold is set from these values",
            f"E={emp_E:.6g}": yield_for(emp_E),
            "E=1.0": yield_for(1.0),
            "E=0.5": yield_for(0.5),
            "E=0.25": yield_for(0.25),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence-dir", default=str(DEFAULT_EVIDENCE))
    args = ap.parse_args()
    ed = Path(args.evidence_dir)

    stat = load(ed, "first-divergence-statistical.json")
    stress = load(ed, "first-divergence-stress.json")
    metrics = load(ed, "same-prefix-error-metrics.json")
    local = load(ed, "decision-local-errors.json")

    reproduce_gate(stat, stress)
    out = {
        "schema": "inferswarm.issue83.diagnostic-aggregates/1",
        "reproduction_gate": "PASS (236/576 statistical, 4/8 stress)",
        "divergence": divergence_details(stat, stress),
        "rows": row_aggregates(metrics, local),
    }
    json.dump(out, sys.stdout, indent=1)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
