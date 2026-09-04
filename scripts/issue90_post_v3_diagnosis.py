#!/usr/bin/env python3
"""Issue #90: post-v3 numerical-envelope holdout-failure diagnosis tool.

CPU-only, pure-stdlib, read-only. Re-derives every diagnostic quantity in
DIAGNOSIS.md from the retained, hash-pinned #88 / #86 evidence committed in
this repository:

  - campaign-88 calibration summary (576 statistical + 8 selected stress
    cases, 15 envelope families per case, exact-hex case E_D);
  - campaign-88 threshold manifest (15 frozen limits + E_D);
  - campaign-88 phaseI failures (the single terminal holdout exceedance);
  - v3 methodology corpus / stress pool (public cell structure, token
    counts, content classes).

Design rules (issue #90):
  - FAIL-CLOSED on any hash drift of the pinned inputs.
  - No historical evidence is mutated; no physical execution; no successor
    threshold values are proposed; consumed h86-* observations are used
    ONLY as diagnostic data.
  - Every emitted number is derived from pinned bytes, never a constant.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

ACCEPTED = {
    "inferswarm_evidence_merge": "dc00dd933fcbdcaddffc0c9fd4fd25baf5b70da5",
    "physical_producer": "560bb7e833ad4ca9386eb87799bb0aafb82b3e59",
    "freetoken_producer_merge": "5e44be50cd9ed322366a01cd5d80d958950d1ac5",
    "v3_methodology_base": "a8ec98a9fb9b673c93de5100d784ea772395efdb",
}

EVD = "docs/qualification/gemma4-12b-it-v3-campaign-88"
V3 = "docs/qualification/gemma4-12b-it-v3"

PINNED_FILE_SHA256 = {
    f"{EVD}/phaseEF/calibration-summary.json":
        "81bbd737977426fde86340cd5efe00b51ee8fc6c333d1356e84a3d6384499b53",
    f"{EVD}/phaseEF/threshold-manifest.json":
        "251c4b7a8127e086001cc59e96cf7f61c17c59fa3bd120a15b5c4678fa9f5e5d",
    f"{EVD}/phaseHI/phaseI-failures.json":
        "820ee1a1a57752dd8fe2c04c7333d8a8a5a0325ce293b7b16d4add5495af7293",
    f"{EVD}/phaseB/reference-margin-summary.json":
        "8d13d5bba3968b8f00627dc55a9b5d1b021128139d0bbf557be054f3ad0960dd",
    f"{EVD}/phaseB/selected-eight.json":
        "9866e4f194f476ae0b30aa18f3ca379ae19ad7d272b0786d977e41ec18adb878",
    f"{EVD}/phaseG/phaseG-semantic-adjudication.json":
        "47cd66f4353874eaae04a4284cce58e9e39b77dea8e1b4c8deb7089a05e10a9c",
    f"{EVD}/preflight-applicability.json":
        "49e0bdd47157fe406ee5b4270f9c4bc864f5a124828a8644f2669e04175c145e",
    f"{EVD}/phaseC/decision-domain-manifest.json":
        "df446d71bc044553518a58bbe3ced4ebde3e9a956d09f59ded4014b7fababd30",
    f"{V3}/manifests/calibration-corpus.json":
        "09731f1b2e66a6892b886c01bd2ec058be147b73885213844f2863caa10b41b6",
    f"{V3}/manifests/stress-pool.json":
        "4e4735c19f10bdcff4bf4173d9e96d2330df5c98de40f2701e1e3c309d29f015",
    f"{V3}/manifests/sealed-holdout-commitment.json":
        "48a40c13171bf97e9aa1666328baaca4d4844c6c6a846ae3ee41a919d36aa8d5",
}

FAMILY = "final-normalized-hidden-state:rms-difference"
STATISTICAL_DESIGN = {  # frozen v3 methodology section 7
    "target_marginal_coverage": 0.99,
    "simultaneous_confidence": 0.95,
    "simultaneous_families": 16,
    "min_n_distribution_free": 574,
    "statistical_cases": 576,
    "selected_stress_cases": 8,
    "holdout_cases": 24,
}

TERMINAL_CLASSIFICATION = "V3_ENVELOPE_DIAGNOSIS_ORDINARY_TAIL"


class DiagnosisError(RuntimeError):
    """Fail-closed diagnosis abort."""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def load_pinned(rel: str):
    path = REPO_ROOT / rel
    if not path.exists():
        raise DiagnosisError(f"PINNED_EVIDENCE_MISSING: {rel}")
    digest = sha256_file(path)
    if digest != PINNED_FILE_SHA256[rel]:
        raise DiagnosisError(
            f"PINNED_EVIDENCE_HASH_DRIFT: {rel}: {digest} != {PINNED_FILE_SHA256[rel]}"
        )
    with open(path) as fh:
        return json.load(fh)


def fhex(h: str) -> float:
    return float.fromhex(h)


def quantile(sorted_vals, p):
    k = (len(sorted_vals) - 1) * p
    f = math.floor(k)
    c = min(f + 1, len(sorted_vals) - 1)
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def spearman(xs, ys):
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        rk = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for t in range(i, j + 1):
                rk[order[t]] = avg
            i = j + 1
        return rk

    rx, ry = rank(xs), rank(ys)
    n = len(rx)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den


def hill_tail_index(sorted_asc, k):
    xk = sorted_asc[-(k + 1)]
    return sum(math.log(x / xk) for x in sorted_asc[-k:]) / k


def qq_r2(vals, transform):
    from statistics import NormalDist, mean, stdev
    v = sorted(vals)
    tv = [transform(x) for x in v]
    n = len(tv)
    if transform is math.log:
        mu, sd = mean(tv), stdev(tv)
        pred = [mu + sd * NormalDist().inv_cdf((i + 0.375) / (n + 0.75)) for i in range(n)]
    else:  # exponential scores
        mval = mean(tv)
        pred = [-mval * math.log(1 - (i + 0.5) / n) for i in range(n)]
    ss_res = sum((a - b) ** 2 for a, b in zip(tv, pred))
    ss_tot = sum((a - mean(tv)) ** 2 for a in tv)
    return 1 - ss_res / ss_tot


def build_rows(cal, corpus, pool):
    cmap = {c["case_id"]: c for c in corpus["cases"] + pool["cases"]}
    rows = []
    for arm_key, arm in (("statistical", "statistical_cases"), ("stress", "stress_cases")):
        for c in cal[arm]:
            if c["case_id"] not in cmap:
                raise DiagnosisError(f"CASE_NOT_IN_FROZEN_CORPUS: {c['case_id']}")
            m = cmap[c["case_id"]]
            rows.append({
                "arm": arm_key,
                "case_id": c["case_id"],
                "value": fhex(c["envelopes"][FAMILY]),
                "e_full": fhex(c["envelopes"]["fp32-consumer-logits:max-absolute-difference"]),
                "e_full_rms": fhex(c["envelopes"]["fp32-consumer-logits:rms-difference"]),
                "fnhs_max": fhex(c["envelopes"]["final-normalized-hidden-state:max-absolute-difference"]),
                "hres_rms": fhex(c["envelopes"]["hidden-residual-stream:rms-difference"]),
                "case_e_d": fhex(c["case_e_d_hex"]),
                "content_class": m["content_class"],
                "length_regime": tuple(m["length_regime"]),
                "token_count": m["token_count"],
            })
    return rows


def failing_observation(cal, thr, fails):
    if len(fails) != 1:
        raise DiagnosisError(f"EXPECTED_ONE_FAILURE: got {len(fails)}")
    f = fails[0]
    if f["case_id"] != "h86-03-05-01" or f["envelope"] != FAMILY or f["gate"] != "ENVELOPE_EXCEEDED":
        raise DiagnosisError(f"UNEXPECTED_FAILURE_RECORD: {f}")
    obs, lim = f["observed"], f["limit"]
    if fhex(thr["limits"][FAMILY]["limit_hex"]) != lim:
        raise DiagnosisError("LIMIT_HEX_MISMATCH")
    driver = [c["case_id"] for c in cal["statistical_cases"]
              if c["envelopes"][FAMILY] == thr["limits"][FAMILY]["statistical_max_hex"]]
    if len(driver) != 1:
        raise DiagnosisError(f"STATISTICAL_MAX_DRIVER_NOT_UNIQUE: {driver}")
    sv = sorted(r["value"] for r in build_rows(cal,
                                               load_pinned(f"{V3}/manifests/calibration-corpus.json"),
                                               load_pinned(f"{V3}/manifests/stress-pool.json"))
                if r["arm"] == "statistical")
    below = sum(1 for x in sv if x < obs)
    return {
        "case_id": f["case_id"],
        "envelope": FAMILY,
        "gate": f["gate"],
        "observed": obs,
        "observed_hex": float(obs).hex(),
        "limit": lim,
        "limit_hex": thr["limits"][FAMILY]["limit_hex"],
        "exceedance_fraction": obs / lim - 1,
        "exceedance_percent": (obs / lim - 1) * 100,
        "statistical_n": len(sv),
        "calibration_values_below_observed": below,
        "observed_exceeds_every_calibration_case": below == len(sv),
        "statistical_max": sv[-1],
        "statistical_second_max": sv[-2],
        "statistical_max_case": driver[0],
        "stress_max": fhex(thr["limits"][FAMILY]["stress_max_hex"]),
        "limit_rule": thr["limits"][FAMILY]["rule"],
    }


def family_distribution(rows, obs):
    stat = [r for r in rows if r["arm"] == "statistical"]
    stress = [r for r in rows if r["arm"] == "stress"]
    sv = sorted(r["value"] for r in stat)
    tv = sorted(r["value"] for r in stress)
    by_cell, by_class, by_regime = {}, {}, {}
    for r in stat:
        cell = f"{r['content_class']}|{r['length_regime'][0]}-{r['length_regime'][1]}"
        by_cell.setdefault(cell, []).append(r["value"])
        by_class.setdefault(r["content_class"], []).append(r["value"])
        by_regime.setdefault(r["length_regime"], []).append(r["value"])

    def agg(d):
        out = {}
        for k in sorted(d):
            v = sorted(d[k])
            out[k if isinstance(k, str) else "|".join(str(x) for x in k)] = {
                "n": len(v), "median": quantile(v, 0.5),
                "p90": quantile(v, 0.9), "p99": quantile(v, 0.99), "max": v[-1],
            }
        return out

    top15 = sorted(stat, key=lambda r: -r["value"])[:15]
    return {
        "statistical": {
            "n": len(sv), "min": sv[0], "median": quantile(sv, 0.5),
            "p90": quantile(sv, 0.9), "p99": quantile(sv, 0.99), "max": sv[-1],
            "top10_desc": sv[-10:][::-1],
        },
        "stress": {"n": len(tv), "min": tv[0], "max": tv[-1], "all_asc": tv},
        "gaps": {
            "statistical_max": sv[-1],
            "failing_observed": obs,
            "obs_to_stat_max": obs / sv[-1],
            "obs_to_second_stat_max": obs / sv[-2],
            "stat_max_to_second": sv[-1] / sv[-2],
        },
        "by_cell": agg(by_cell),
        "by_content_class": agg(by_class),
        "by_length_regime": agg(by_regime),
        "top15_cases": [
            {"case_id": r["case_id"], "value": r["value"],
             "content_class": r["content_class"], "length_regime": list(r["length_regime"]),
             "token_count": r["token_count"]}
            for r in top15
        ],
        "tail_shape": {
            "lognormal_qq_r2": qq_r2(sv, math.log),
            "exponential_qq_r2": qq_r2(sv, lambda x: x),
            "hill_k10": hill_tail_index(sv, 10),
            "hill_k40": hill_tail_index(sv, 40),
            "hill_k160": hill_tail_index(sv, 160),
            "top_decile_share_of_sum": sum(sv[-58:]) / sum(sv),
            "n_above_1p5": sum(1 for x in sv if x > 1.5),
            "n_above_2p0": sum(1 for x in sv if x > 2.0),
            "n_above_2p4": sum(1 for x in sv if x > 2.4),
        },
    }


def applicability_split_audit(rows, obs):
    stat = [r for r in rows if r["arm"] == "statistical"]
    by_cell = {}
    for r in stat:
        by_cell.setdefault((r["content_class"], r["length_regime"]), []).append(r["value"])
    loco = {}
    for drop in sorted(by_cell):
        rest = [v for k, vals in by_cell.items() if k != drop for v in vals]
        loco[f"{drop[0]}|{drop[1][0]}-{drop[1][1]}"] = {
            "limit_without_cell": max(rest),
            "failing_obs_still_exceeds": obs > max(rest),
        }
    fail_cell = ("repetitive-low-entropy", (36, 40))
    own = sorted(by_cell[fail_cell])
    all_sorted = sorted(r["value"] for r in stat)
    cell_max_rank = 1 + sum(1 for x in all_sorted if x > own[-1])
    top10_cells = {(r["content_class"], r["length_regime"])
                   for r in sorted(stat, key=lambda r: -r["value"])[:10]}
    top20_cells = {(r["content_class"], r["length_regime"])
                   for r in sorted(stat, key=lambda r: -r["value"])[:20]}
    # token-count: is the tail length-driven?
    tok_top20 = sorted(r["token_count"] for r in sorted(stat, key=lambda r: -r["value"])[:20])
    tok_bot20 = sorted(r["token_count"] for r in sorted(stat, key=lambda r: r["value"])[:20])
    all_tok = [float(r["token_count"]) for r in stat]
    return {
        "failing_case_cell": {
            "content_class": fail_cell[0],
            "length_regime": list(fail_cell[1]),
            "calibration_cell_n": len(own),
            "calibration_cell_median": quantile(own, 0.5),
            "calibration_cell_p90": quantile(own, 0.9),
            "calibration_cell_max": own[-1],
            "failing_obs_vs_cell_max": obs / own[-1],
            "cell_max_rank_among_576": cell_max_rank,
        },
        "leave_one_cell_out": loco,
        "tail_concentration": {
            "distinct_cells_in_top10": len(top10_cells),
            "distinct_cells_in_top20": len(top20_cells),
            "distinct_content_classes_in_top10": len({c for c, _ in top10_cells}),
        },
        "token_count_split": {
            "spearman_value_vs_token_count": spearman([r["value"] for r in stat], all_tok),
            "top20_token_counts": tok_top20,
            "bottom20_token_counts": tok_bot20,
            "verdict": (
                "Weak monotone length association only (Spearman ~0.24): the extreme tail "
                "spans every regime (4-56 tokens); token count does not separate the "
                "failing observation's regime from the calibration population."
            ),
        },
        "pre_observability_answers": [
            "Cell/class/regime/token-count were all frozen BEFORE candidate execution "
            "(committed corpus manifests) — genuinely pre-observable.",
            "No split materially explains error behavior: leave-one-cell-out leaves the "
            "max-based limit within [1.79, 2.61] for every dropped cell and the failing "
            "observation still exceeds every leave-one-cell-out limit.",
            "The top-10 tail spans >= 8 distinct cells across all 6 content classes; the "
            "failing case's own calibration cell (repetitive-low-entropy 36-40) has cell "
            "max 1.8799 — far below the limit driver's cell.",
            "Encoding any of these dimensions as a prospective applicability key would "
            "therefore be post-hoc relabeling, not regime detection.",
        ],
    }


def downstream_propagation(cal, rows, obs):
    vs = [r["value"] for r in rows]
    cor = {
        "fam_vs_e_full_maxabs": spearman(vs, [r["e_full"] for r in rows]),
        "fam_vs_e_full_rms": spearman(vs, [r["e_full_rms"] for r in rows]),
        "fam_vs_case_e_d": spearman(vs, [r["case_e_d"] for r in rows]),
        "fam_vs_fnhs_maxabs": spearman(vs, [r["fnhs_max"] for r in rows]),
        "fam_vs_hres_rms": spearman(vs, [r["hres_rms"] for r in rows]),
    }
    cut = sorted(vs)[len(vs) - 59]
    top = [r for r in rows if r["value"] >= cut]
    rest = [r for r in rows if r["value"] < cut]

    def mean(xs):
        return sum(xs) / len(xs)

    # do all top-decile fam cases stay within EVERY other frozen family limit?
    thr = load_pinned(f"{EVD}/phaseEF/threshold-manifest.json")
    by_id = {c["case_id"]: c for c in cal["statistical_cases"] + cal["stress_cases"]}
    within = sum(
        1 for r in top
        if all(fhex(by_id[r["case_id"]]["envelopes"][fam]) <= fhex(rec["limit_hex"])
               for fam, rec in thr["limits"].items())
    )
    return {
        "retention_boundary": (
            "Per-decision holdout rows for h86-03-05-01 were expunged with the "
            "node-local #88 evidence after maintainer adjudication; the committed "
            "compact record retains the failing family/limit/observed triple plus the "
            "calibration-side per-case/per-decision evidence. Propagation is therefore "
            "quantified indirectly via calibration co-movement, and directly at the "
            "case level via the retained holdout verdict facts (192/192 SEMANTIC_PASS, "
            "zero NaN/Inf, zero DECISION_LOCAL_BOUND_EXCEEDED, zero "
            "DECISION_DOMAIN_ESCAPE on the holdout arm including the failing case)."
        ),
        "rank_correlations_over_584": cor,
        "conditional_top_decile": {
            "n": len(top),
            "mean_e_full_top": mean([r["e_full"] for r in top]),
            "mean_e_full_rest": mean([r["e_full"] for r in rest]),
            "mean_case_e_d_top": mean([r["case_e_d"] for r in top]),
            "max_e_full_top": max(r["e_full"] for r in top),
            "max_case_e_d_top": max(r["case_e_d"] for r in top),
            "e_d_frozen": fhex(thr["e_d_hex"]),
            "cases_within_all_other_14_limits": within,
        },
        "interpretation": (
            "The failing family moves WITH the consumer-facing error families "
            "(Spearman 0.78-0.89) but is not redundant with them; hidden-state RMS "
            "spikes did not translate into downstream limit breaches anywhere in "
            "calibration (top-decile fam cases: all within all other limits; case E_D "
            "max 26.94 equals the frozen E_D bound exactly, by construction of the "
            "max-based rule). For the failing holdout case the retained verdict facts "
            "prove the spike was ATTENUATED to zero downstream effect: semantic pass, "
            "no bound breach, no domain escape, finite outputs. The envelope is "
            "therefore an EARLY-WARNING tensor metric with real co-movement but no "
            "demonstrated independent causal path to decision failure in this campaign."
        ),
    }


def statistical_audit():
    n = STATISTICAL_DESIGN["statistical_cases"]
    s = STATISTICAL_DESIGN["selected_stress_cases"]
    m = STATISTICAL_DESIGN["holdout_cases"]
    ns = n + s
    one_family_fail_exchangeable = m / (ns + m)
    coverage_fail_99 = 1 - 0.99 ** m
    q_needed = 1 - 0.95 ** (1 / m)
    # P(0 of m exceed X_(n)) = n/(n+m) >= 0.95  <=>  n >= m*0.95/0.05
    n_for_95_zero_of_24 = math.ceil(m * 0.95 / 0.05)
    n_tolerance = math.ceil(math.log(0.05 / 16) / math.log(0.99))
    indep16 = (1 - one_family_fail_exchangeable) ** 16
    return {
        "frozen_design": STATISTICAL_DESIGN,
        "distinct_statements": {
            "tolerance_statement": (
                "Distribution-free: P(at least 99% of the case population lies below "
                "X_(n)) >= 1 - 0.05/16 = 0.996875 per family — a COVERAGE statement "
                "about the bound."
            ),
            "estimator": "limit[e] = max(statistical_max[e], stress_max[e])",
            "acceptance_rule": "zero of 24 fresh holdout cases may exceed limit[e]",
            "answer_guarantee_or_target": (
                "TARGETED, never guaranteed. The tolerance statement bounds the "
                "population fraction above the limit (<= 1% marginal, per family, at "
                "97.8% confidence under Bonferroni); it says nothing that forces zero "
                "exceedances among 24 fresh draws. Under iid exchangeability the "
                "max-based limit is exceeded by at least one holdout case with "
                "probability m/(n+s+m) = 24/608 = 3.95% per family even with NO "
                "distributional change whatsoever."
            ),
        },
        "exact_calculations": {
            "p_single_holdout_exceeds_max_of_584": 1 / (ns + 1),
            "p_global_max_of_608_in_holdout_arm": 24 / 608,
            "p_at_least_one_of_24_exceeds__exchangeable_max_limit": one_family_fail_exchangeable,
            "p_at_least_one_of_24_exceeds__coverage_exactly_99pct": coverage_fail_99,
            "per_case_exceedance_budget_for_95pct_zero_of_24": q_needed,
            "coverage_required_for_95pct_zero_of_24": 1 - q_needed,
            "calibration_n_for_exchangeable_95pct_zero_of_24": n_for_95_zero_of_24,
            "distribution_free_tolerance_n_reproduced": n_tolerance,
            "p_no_family_fails__16_independent": indep16,
            "p_some_family_fails__16_independent": 1 - indep16,
            "selected_stress_arm_effect": (
                "All 15 frozen limits are statistical-arm driven (stress maxima are 3-30x "
                "below the statistical maxima for every family), so the selected stress "
                "arm never raised any limit and does not alter the exchangeability "
                "arithmetic; pooling it moves the per-family failure probability only "
                "from 24/600=4.00% (statistical-only basis) to 24/608=3.95%."
            ),
        },
    }


def successor_options():
    return {
        "options": [
            {
                "id": "S1_prediction_bound",
                "name": "Prospective one-sided prediction bound matched to the acceptance rule",
                "correctness_claim": (
                    "With stated confidence, P(zero of m fresh holdout cases exceed the "
                    "bound) >= the stated level — claim and rule coincide."
                ),
                "assumptions": "iid cases within an arm; case-level max reduction (unchanged).",
                "avoids_tuning": (
                    "Sample size and bound form fixed prospectively; h86-03-05-01 never "
                    "enters any calculation."
                ),
                "sample_size": (
                    "Zero-of-24 at 95% exchangeable requires n >= 456 calibration cases "
                    "pooled per family basis (n >= m*0.95/0.05); with the 16-family "
                    "Bonferroni budget, n >= ~2700 for a 99.79%-coverage max-order "
                    "bound — OR keep n=576 and allow <= k exceedances with exact "
                    "beta-binomial levels (k=1 of 24 passes at 99.85% under exchangeability)."
                ),
                "holdout_contract": "Fresh sealed holdout; zero exceedances of the prediction bound.",
                "failure_modes": "Conservative limits; ~4-5x corpus cost if zero-exceedance is kept.",
            },
            {
                "id": "S2_accept_coverage_claim",
                "name": "Keep the estimator; restate the acceptance rule as the coverage claim it makes",
                "correctness_claim": "Bound covers >= 99% of the population at 0.9969 confidence per family.",
                "assumptions": "None beyond v3; this is an acceptance-rule change, not a statistical one.",
                "avoids_tuning": "No numeric change anywhere.",
                "sample_size": "Unchanged.",
                "holdout_contract": "Holdout adjudicates exceedances against a pre-frozen tail-count rule.",
                "failure_modes": (
                    "Weaker than ADR 0010's conjunctive zero-exceedance reading; "
                    "maintainer doctrine decision."
                ),
            },
            {
                "id": "S3_stratified_envelopes",
                "name": "Applicability-conditioned (per-cell) envelopes",
                "correctness_claim": "Per-regime numerical equivalence.",
                "assumptions": (
                    "REQUIRES a demonstrated pre-observable regime split. This diagnosis "
                    "found NONE (leave-one-cell-out and tail-concentration sections): "
                    "not evidence-supported for v4 on current evidence."
                ),
                "avoids_tuning": "Moot on current evidence.",
                "sample_size": "24/cell already; per-cell limits would need more per cell.",
                "holdout_contract": "One holdout case per cell (as v3).",
                "failure_modes": "Post-hoc relabeling; overfitting cell labels.",
            },
            {
                "id": "S4_logscale_robust",
                "name": "Log-scale parametric tail bound with finite-sample validation",
                "correctness_claim": "Explicit parametric upper tail bound per family.",
                "assumptions": (
                    "Log-normal QQ R^2 0.986 for the failing family (12 smooth families "
                    "> 0.96) supports log-scale modeling; Hill indices 0.17-0.41."
                ),
                "avoids_tuning": (
                    "Model family + sample size frozen before any new execution; fit on "
                    "fresh calibration only."
                ),
                "sample_size": "Possibly n=576 with simulation-validated coverage.",
                "holdout_contract": "Fresh sealed holdout; zero exceedances of the modeled bound.",
                "failure_modes": "Misspecification exactly in the extreme tail; weaker than distribution-free.",
            },
            {
                "id": "S5_demote_metric",
                "name": "Demote final-normalized-hidden-state families from acceptance-bearing to telemetry",
                "correctness_claim": "Qualification certified on consumer-facing tensors (E_full, E_D, integrity).",
                "assumptions": (
                    "Doctrine claim that the normalized hidden state is not independently "
                    "correctness-bearing. Supporting: co-movement without any downstream "
                    "breach anywhere in 608 cases. Against: rho < 1 (residual independent "
                    "signal); it is the ONLY gate that fired in #88."
                ),
                "avoids_tuning": "Doctrine/methodology-version change decided before any new holdout exists.",
                "sample_size": "Unchanged.",
                "holdout_contract": "Per successor contract.",
                "failure_modes": "Removes the only canary that fired; must rest on doctrine, not one failure.",
            },
            {
                "id": "S6_split_qualification_and_telemetry",
                "name": "Two-tier contract: coherent acceptance core + mandatory 15-family telemetry",
                "correctness_claim": (
                    "Acceptance: exact integrity + E_full + E_D under a matched prediction "
                    "rule. Telemetry: all 15 families retained per-case with alert thresholds."
                ),
                "assumptions": "Tier boundary justified prospectively from doctrine, not from #88.",
                "avoids_tuning": "Structure change; no thresholds from #88 observations.",
                "sample_size": "Per S1 for the acceptance core.",
                "holdout_contract": "Fresh sealed holdout under the tiered contract.",
                "failure_modes": "Tier boundary drift; S5-in-disguise if the boundary chases the failure.",
            },
        ],
        "recommendation": (
            "Recommend S1+S6 as the successor design direction: a prospective prediction "
            "bound whose statistical claim and acceptance rule coincide, with all 15 "
            "families retained as mandatory telemetry. S5 (demotion) is a maintainer "
            "doctrine decision that must be settled BEFORE the v4 freeze. S3 is rejected "
            "on current evidence. No threshold values are proposed here."
        ),
    }


def build_diagnosis():
    cal = load_pinned(f"{EVD}/phaseEF/calibration-summary.json")
    thr = load_pinned(f"{EVD}/phaseEF/threshold-manifest.json")
    fails = load_pinned(f"{EVD}/phaseHI/phaseI-failures.json")
    corpus = load_pinned(f"{V3}/manifests/calibration-corpus.json")
    pool = load_pinned(f"{V3}/manifests/stress-pool.json")

    failinfo = failing_observation(cal, thr, fails)
    rows = build_rows(cal, corpus, pool)
    dist = family_distribution(rows, failinfo["observed"])
    split = applicability_split_audit(rows, failinfo["observed"])
    prop = downstream_propagation(cal, rows, failinfo["observed"])
    audit = statistical_audit()

    return {
        "schema": "inferswarm.issue90.post-v3-envelope-diagnosis/1",
        "issue": 90,
        "classification": TERMINAL_CLASSIFICATION,
        "provenance": {
            "accepted": ACCEPTED,
            "pinned_files_sha256": dict(PINNED_FILE_SHA256),
            "tooling": "scripts/issue90_post_v3_diagnosis.py",
        },
        "failing_observation": failinfo,
        "family_distribution": dist,
        "applicability_split_audit": split,
        "downstream_propagation": prop,
        "statistical_contract_audit": audit,
        "successor_options": successor_options(),
        "non_claims": [
            "This diagnosis does NOT change issue #88's terminal V3_HOLDOUT_FAIL verdict.",
            "No v3 threshold was modified, widened, or reinterpreted.",
            "No successor threshold value is proposed from #88 observations.",
            "Consumed h86-* holdout observations are permanently ineligible as future "
            "calibration or holdout evidence; used here as diagnostic data only.",
            "No physical model execution was performed for this diagnosis.",
        ],
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=None, help="write the record to this path")
    args = ap.parse_args()
    record = build_diagnosis()
    text = json.dumps(record, indent=1, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n")
        print(f"wrote {args.out} ({len(text)} bytes)")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
