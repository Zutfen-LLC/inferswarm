# Issue #105 — Post-v4 numerical-core holdout-failure diagnosis

## Status

```
V4_CORE_DIAGNOSIS_MIXED
```

Diagnostic-only gate. Issue #97 remains terminally `V4_HOLDOUT_CORE_FAIL`,
unchanged and un-reinterpreted. No v4 threshold, telemetry band, decision
domain, semantic artifact, or holdout artifact was modified. No h95 case
was rerun; h95 is consumed and its observations are diagnostic-only,
permanently ineligible as future calibration/stress/holdout input. No
successor threshold value, sample size, corpus, or holdout construction is
proposed. No new physical/CUDA model execution was performed.

Classification basis (all machine-derived in
`scripts/issue105_post_v4_core_diagnosis.py` and recorded in
`diagnosis-record.json`):

- ordinary heavy-tail behavior: SUPPORTED (single cross-cell tail draw,
  no prospective split);
- metric/reducer mismatch: CONTRIBUTING (p99 order-statistic knife edge);
- statistical-contract defect: PRESENT (the frozen theorem did not bound
  the path the failure actually took);
- execution anomaly: ABSENT (integrity PASS; all 15 failing-case
  envelopes reproduce byte-exact through the frozen reducer);
- applicability regime: ABSENT (no pre-observable split explains more
  than the single case).

## Provenance and evidence boundary

All accepted identities verified before analysis:

- InferSwarm terminal evidence PR #98 merged to `main` as `3d25d8b6…`;
  accepted head before merge `81ff1798…`
- FreeToken producer PR #31 merged to `inferswarm-research` as `605e129c…`
- Phase A calibration producer `57dfcb7289efac8f66de5b3abbe8de04f2580f75`
- Phase B holdout-only producer `c60a4b7080913eba90585de8e8602460a7f5b1a7`
- frozen v4 methodology: issue #95 `GEMMA_V4_PREDICTION_ALIGNED_METHODOLOGY_FROZEN`
- historical: #88 `V3_HOLDOUT_FAIL`, #90
  `V3_ENVELOPE_DIAGNOSIS_ORDINARY_TAIL` (both immutable)

Unlike #90 (whose raw tensors had been expunged), the #97 node-local raw
evidence was retained. This diagnosis therefore reconstructs the failing
observation from **exact raw bytes**, committed durably under
`raw/h95-01-01-01/` (16 FP32 consumer-logit rows, 262144 float32 elements
each, plus both producer case records). Every row is double-bound: by
sha256 in the tool, and by the producer's own `row_f32_sha256` record.
Additionally, all 15 failing-case envelopes were reproduced byte-exact
through the frozen #76 reducer over the retained capture bundles (torch
CPU, retained bytes only, run on inferswarm01 2026-09-06) — closing the
loop from committed summaries to raw tensors.

## 1. The failing observation, reconstructed from bytes

- Case `h95-01-01-01` (ordinary-prose, length regime [4,8], 4 tokens),
  holdout cell 1 of 24.
- Family `fp32-consumer-logits:p99-absolute-error`, per-case maximum over
  the frozen capture positions (0, 1, 3, 7) of 8 teacher-forced decisions.
- **Reproduced exactly: 16.765625 (`0x1.0c4p+4`) from decision 3**,
  reference row sha256 `4dc65a7b4ace282d…`, candidate row
  `4a0a559e6c90e3b7…` (both producer-bound), vs frozen limit 16.640625.
  Exceedance +0.125 / +0.75%.
- Reducer (frozen #76): ascending sort of all 262144 float64 absolute
  errors; one-based nearest-rank/higher index ceil(0.99·262144)=259523.
- Same-decision neighbors: p98 15.8125, p99.5 17.59375, p99.9 19.359375,
  max 23.296875. The p99 value sits on a 10-element plateau
  (indices 259515–259524).
- **Knife-edge mechanism: p99 fails exactly when more than 1% of the
  vocabulary exceeds the limit.** Here 2854 elements (1.0887%) did. On
  the very same rows, max-absolute-difference passed with 12.4% headroom
  and RMS passed with 11.9%.
- Discretization: both rows are BF16-lattice-valued float32; at magnitude
  ~16 the lattice spacing is 0.125 — the exceedance is exactly one local
  lattice step.
- All three consumer-logit envelopes and the case E_D (20.875) reproduce
  byte-exact; the max-abs and E_D holdout maxima come from the same case.

## 2. Four core-family distributions (1896 c95 / 8 selected p95 / 24 h95)

All four families are near-collinear at case level (Spearman 0.93–0.99)
and share one smooth heavy tail: median→max spans 8–16x, upper-gap ratios
compact (max/second 1.04–1.06), no plateaus or multimodality, stress
maxima 3–6x below every limit (the stress arm never binds, as in #88).
Limits equal the statistical-arm maxima byte-for-byte in all four
families. The failing case ranks 1891/1896 (max-abs), 1891 (rms), 1890
(E_D) and 1897/1897 (p99, above everything) — extreme on all four
simultaneously; only p99 crossed because its limit was the closest to the
case's value. The p99 limit was set by `c95-02-03-28` (mathematics-numerals
[24,28]) at 16.640625; the next-highest holdout p99 is 5.25 (3.19x below).
Top-10 overlap: 3 cases common to all four families' top-10; union 17 —
a single shared tail population, not four independent statistics.

## 3. Applicability-split audit: NO prospective split

Tested: content class, length regime, cell, token count, decision index,
capture position, reference margins, activation scale, producer/device/
role identity. Findings:

- The failing case's own cell (ordinary-prose [4,8]) has calibration p99
  max 11.0078 — **ranks 14th of 24 cells**. The four LOWEST cell maxima
  are all [4,8] cells: the shortest-prompt regime is systematically the
  LIGHTEST tail in v4, opposite to an applicability story.
- Spearman(token count, p99) = 0.11 — negligible.
- The case does set new records in its own cell (rms, p99), but so would
  any extreme cross-cell draw; the dimension does not separate more than
  the one case, is unstable across arms, and could not be encoded
  prospectively without naming the failed case.

## 4. Downstream semantic trace

All 8 decisions of the failing case: UNSTABLE / SEMANTIC_PASS
(ambiguity-admissible; reference margins down to 0.125 near-ties between
tokens 236761/236770). Zero bound exceedances, zero domain escapes;
case-wide semantic 192/192. The p99-maximum decision's 2854 over-limit
full-vocab errors have best reference rank 32921 — **zero inside the
frozen top-1024 decision domain**. The worst-E_D decision (index 7, E_D
20.875) has 3 of 31 over-limit elements touching the domain but stays
under the frozen E_D limit 26.625. All four telemetry alerts are the same
case. Conclusion: the p99 spike did not translate into independent
decision risk — but semantic PASS does not waive the core failure, and
this is diagnostic only.

## 5. Cross-campaign comparison (#88/#90 vs #97)

Different cells (repetitive-low-entropy [36,40] vs ordinary-prose [4,8]),
different families (telemetry hidden-state RMS vs core p99), same shape:
each terminal failing value ranks above EVERY retained calibration case
(v3: 1 of 584; v4: 1 of 1897), small exceedance (+2.56% / +0.75%), holdout
runner-up far below (2.33x / 3.19x). Three consecutive single-case-dominated
terminals across different cells, families, and methodology generations
support a generic heavy-tail interpretation over any fixed applicability
split. #90's ordinary-tail classification and its brittleness warning were
correct and are materially strengthened. What #90 could not resolve —
whether the estimator or the metric design was at fault — this diagnosis
answers for v4: both contributed (Sections 6 and 7).

## 6. Statistical-contract audit: the frozen theorem had a real gap

Mechanically reproduced the frozen derivation (79/cell, 1/80, 4/80
Bonferroni, ≥95% claim, stress contributes zero predictive sample) — the
replay matches. The defect is in what the theorem bounded:

- The frozen argument bounds ONLY the strict-record path within the single
  cell holding the global maximum (1/80). But a holdout exceedance can
  arrive as a record in ANY cell that crosses the global max; each cell's
  record probability is ≤ 1/80 distribution-free, so the correct
  distribution-free per-family bound is the union 24/80 = 30%
  (familywise 96/80 — vacuous). A distribution-free 95% familywise claim
  needs ~1919 cases/cell (45,976 cases), not 79.
- **The observed failure arrived exactly through the unbounded path**:
  the failing case's own-cell max is 11.0078 (14th of 24), far below the
  global limit 16.6406; the case is a cross-cell draw, not a max-cell
  record.
- Even under full cross-cell homogeneity (all cells one distribution) —
  the most favorable reading — the correct union bound is 24/1897 per
  family, 96/1897 = 5.06% familywise: the "≥95%" claim was marginally
  invalid even under its best-case assumption.
- One observed exceedance is not inconsistent with a correct ≥95%
  statement, and the terminal failure does not invalidate exchangeability
  or the #97 verdict. But the ≥95% number was never established by the
  frozen proof. Reliance on an observed calibration maximum is
  operationally brittle for this heavy, lattice-discretized distribution
  even where a coverage statement is mathematically correct; a different
  tolerance construction would change the claim's shape, not remove the
  tail risk.

## 7. p99 reducer audit: REQUIRE_DOCTRINE_REVIEW (diagnostic only)

- Exact finite-sample definition: nearest-rank/higher order statistic at
  ceil(0.99·262144) of full-vocab float64 absolute errors; per-case max
  over positions (0,1,3,7).
- The 0.125 overage is NOT a broad upper-tail displacement: it is the
  259523rd order statistic stepping one 0.125 lattice quantum past the
  limit because 2854 rather than ~2621 elements crossed it — a knife edge
  max-absolute-difference does not have.
- Correlation with max-abs 0.984, rms 0.993, E_D 0.944 across 1896
  cases: no materially independent case-level correctness information.
- Position subsampling note: decision 2 (not a frozen capture position)
  has max-abs 27.0625 > the max-abs limit 26.625 — under a
  all-8-position capture design the SAME case would have failed
  max-absolute-difference too. The single-family failure is partly an
  artifact of which 4 of 8 decisions the frozen design samples.
- Allowed conclusion: p99's acceptance-bearing status is unchanged by
  this diagnosis; any tier/reducer change requires a separate prospective
  doctrine gate.

## 8. Successor-direction comparison (no v5 parameters chosen)

| direction | supported claim | conservatism | sample burden | avoids tuning to h95 |
|---|---|---|---|---|
| retain v4 unchanged | as frozen — but the real familywise rate is ≥5.06% (vacuous distribution-free), so "≥95%" was never established | miscalibrated, not conservative | unchanged (79/cell) | yes |
| corrected prediction/tolerance construction | honest ≥(1−α) zero-exceedance statement bounding the multi-cell union | distribution-free union needs ~1919/cell (infeasible); homogeneity/parametric assumptions trade rigor for size | large unless assumptions added | yes if prospective |
| prospective stratification | none — no split demonstrated (failing cell ranks 14/24; ρ=0.11) | n/a | multiplies per-stratum needs | a post-hoc key is forbidden |
| p99 reducer/domain revision | removes knife edge only if independently justified from the >1% mechanism | neutral | unchanged | must not use the 0.125 overage |
| backend investigation | none — integrity PASS, byte-exact reproduction, divergence consistent with #71-localized device-class bf16 GEMM residual | n/a | n/a | n/a |
| non-binary operational abstraction | separates decision-relevant semantics (192/192 both campaigns) from numerical-core drift | orthogonal to bound repair | unchanged | yes if prospective |

**Named next prospective gate: a statistical-contract and metric doctrine
review** — repair the prediction theorem's multi-cell union gap and decide
p99's acceptance-bearing status BEFORE any v5 methodology freeze, physical
calibration, or holdout construction. The ordinary-tail physical
phenomenon needs no backend investigation and justifies no stratification.

## Raw-evidence retention

See `RAW-EVIDENCE-RETENTION.json` for the full machine-readable
disposition (~850 GB node-local footprint classified into
RETAIN_DURABLE (repo-committed rows + four node capture bundles),
RETAIN_COMPACT_DERIVATION (committed campaign/diagnosis artifacts), and
SAFE_TO_EXPUNGE_AFTER_ACCEPTANCE (bulk Phase A/B captures whose
correctness-bearing content is hash-bound in git). No deletion is
authorized before maintainer acceptance of this PR and review of that
manifest.

## Historical / non-claims

- Issue #97 remains `V4_HOLDOUT_CORE_FAIL`; nothing here reclassifies it.
- Issues #88/#90/#93/#95 evidence and verdicts are unchanged and
  un-reinterpreted.
- No successor threshold value, sample size, corpus, holdout, or
  stratification key is proposed; consumed h95 observations are
  diagnostic-only and permanently ineligible as future
  calibration/stress/holdout input.
- No new physical model execution was performed (issue rule 6 satisfied:
  every diagnostic question was answerable from retained evidence).

## Tooling

`scripts/issue105_post_v4_core_diagnosis.py` — CPU-only, pure-stdlib,
read-only; re-derives every number above from hash-pinned bytes and fails
closed on any drift (raw-row byte mutation, committed-artifact drift,
row swap, size change). Tests: `tests/test_issue105_post_v4_core_diagnosis.py`
(25 tests: real-evidence derivation, fail-closed mutation controls,
classification logic, purity audit). Regenerate the record with
`python3 scripts/issue105_post_v4_core_diagnosis.py --out <path>`.
