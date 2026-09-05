# Issue #90 — Post-v3 numerical-envelope holdout-failure diagnosis

## Status

```
V3_ENVELOPE_DIAGNOSIS_ORDINARY_TAIL
```

Diagnostic-only gate. Issue #88 remains terminally `V3_HOLDOUT_FAIL`,
unchanged and un-reinterpreted. No v3 threshold was modified, widened, or
re-derived. No successor threshold value is proposed from #88 observations.
Consumed `h86-*` holdout observations are used here as diagnostic data only
and are permanently ineligible as future calibration or holdout evidence.

## Provenance and evidence boundary

All four accepted SHAs verified before analysis:

- InferSwarm evidence PR #89 merged as `dc00dd933fcbdcaddffc0c9fd4fd25baf5b70da5`
- FreeToken producer PR #30 merged as `5e44be50cd9ed322366a01cd5d80d958950d1ac5`
- physical producer `560bb7e833ad4ca9386eb87799bb0aafb82b3e59`
- frozen v3 methodology base `a8ec98a9fb9b673c93de5100d784ea772395efdb`

**Evidence boundary (material to scope).** After maintainer adjudication of
#88, ALL node-local evidence was expunged from every InferSwarm host
(verified again for this gate: `/srv/inferswarm/state/i88`,
`/srv/models/i88-scratch`, worktrees, staging — none exist on 00/01/03/04).
The durable record is exactly the compact artifacts merged in git. The
retained inputs, pinned by byte-exact sha256 inside the analysis tool, are:

| artifact | sha256 (first 16) |
|---|---|
| campaign-88 `phaseEF/calibration-summary.json` (576+8 cases × 15 envelopes, per-decision E_D hex) | `81bbd737977426fd` |
| campaign-88 `phaseEF/threshold-manifest.json` (15 frozen limits + E_D) | `251c4b7a8127e086` |
| campaign-88 `phaseHI/phaseI-failures.json` (the single terminal exceedance) | `820ee1a1a57752dd` |
| campaign-88 `phaseB/reference-margin-summary.json` | `8d13d5bba3968b8f` |
| campaign-88 `phaseB/selected-eight.json` | `9866e4f194f476ae` |
| campaign-88 `phaseC/decision-domain-manifest.json` (4672 rows) | `df446d71bc044558` |
| v3 `manifests/calibration-corpus.json` (cell structure) | `09731f1b2e66a689` |
| v3 `manifests/stress-pool.json` | `4e4735c19f10bdcf` |
| v3 `manifests/sealed-holdout-commitment.json` (public commitment) | `48a40c13171bf97e` |

Because the failing case's raw tensors were expunged with the node-local
evidence, the reported observation **cannot be recomputed from retained
bytes at tensor level**. Instead, the diagnosis binds the failing value at
the maximum retained specificity: the committed failure row's exact binary64
triples (case, family, gate, observed `0x1.570b737619580p+1`, limit
`0x1.4e7a83acd6bccp+1`) are pinned by hash; the limit provably equals the
calibration statistical max case `c86-03-03-21`'s committed per-case value
byte-for-byte; and every derived diagnostic number reproduces from the
pinned per-case calibration evidence. No new physical execution was needed
or performed (issue rule 6 satisfied: the diagnosis was fully resolvable
from retained evidence).

## 1. The failing observation, reconstructed

- Case `h86-03-05-01`, cell `repetitive-low-entropy`, length regime
  `[36, 40]`, 36 tokens, holdout case of the 24 (one per cell).
- Family `final-normalized-hidden-state:rms-difference`, per-case family
  maximum over 4 historical capture positions (0/1/3/7), host-float64 RMS
  over the full hidden-state domain.
- Observed `2.6800369574218053` (`0x1.570b737619580p+1`) vs frozen limit
  `2.6131138414325275` (`0x1.4e7a83acd6bccp+1`): exceedance +2.561%.
- The frozen limit is byte-identical to the calibration statistical-arm max,
  produced by case `c86-03-03-21` (mathematics-numerals, [36,40]).
- The failing observation exceeds **every one of the 584** retained
  calibration (576 statistical + 8 stress) case values: it would rank
  above the entire retained sample (585th of 585; equivalently above all
  576 statistical cases, the basis of the prediction arithmetic in §5).
  It is 3.16% above the second-highest calibration case
  (`c86-04-05-12`, 2.5979, repetitive-low-entropy [52,56]) and 2.56% above
  the highest. The next-highest holdout case observed was 1.1518 — the
  failing case is 2.33x the runner-up holdout observation.

The failing case's own calibration cell (`repetitive-low-entropy`, [36,40])
has cell max 1.8799 (global rank 12/576) — the case exceeded its own cell's
calibration maximum by 42.6%, and the failing value is 1.43x its cell max.

## 2. Family distribution characterization (584 retained cases)

Sorted summary (statistical arm, n=576): min 0.1278, median 0.4629,
p90 0.9470, p99 2.1505, max 2.6131. Stress arm (n=8): 0.1796–0.4928
(all far below statistical max; the stress arm never drove any of the 15
frozen limits — all 15 are statistical-arm driven).

Tail structure:

- Top-10 values span **10 distinct cells across 5 of 6 content classes**
  (top-20: 14 cells); the top of the distribution is not concentrated in
  any regime.
- Smooth heavy tail, no multimodality and no isolated outlier: consecutive
  top order-statistic ratios 1.006, 1.009, 1.008, 1.040, 1.047, 1.050,
  1.076, 1.090 — the failing observation continues this sequence
  (+2.56% over max) rather than breaking it.
- Log-normal QQ R² = 0.9856 (exponential QQ R² = 0.7813); Hill tail index
  0.166 (k=10) to 0.406 (k=160) — heavy-tailed but finite; top decile
  holds 26.6% of the total sum.
- Sensitivity across descriptions: whether modeled as log-normal, or read
  distribution-free, the 2.6800 observation sits within the plausible
  next-record range of a smooth heavy tail whose calibration max is 2.6131.
  46 statistical cases exceed 1.5; 24 exceed 2.0; 9 exceed 2.0+; 2 exceed
  2.4 — a populated tail, not a single anomaly.

By-cell/leave-one-cell-out (all 24 cells): dropping ANY single cell leaves
the max-based limit in [1.79, 2.61] and the failing observation still
exceeds every leave-one-cell-out limit. By class, medians range 0.37
(ordinary-prose) to 0.57 (punctuation/rare); by regime, medians rise
monotonically with length (0.33 → 0.53) but the extreme tail appears at
every length (top-20 token counts span 4–56).

## 3. Applicability-split audit — no split survives

Dimensions tested, all frozen pre-execution (committed corpus manifests,
hence genuinely pre-observable): content class, length regime, cell,
token count. Results:

- **Cell**: leave-one-cell-out never rescues the limit (above). The failing
  case's own cell max (1.8799, rank 12) is unremarkable.
- **Class**: no class separation; the top-10 spans 5 of 6 classes.
- **Regime/token count**: Spearman(value, token_count) = 0.232 — weak
  monotone length effect on the bulk, no separation at the tail; the
  top-20 tail spans 4–56 tokens.
- **Capture position / stage / backend / kernel geometry**: not retained in
  the committed compact record (expunged with node-local captures). No
  pre-observable split of this kind is available from retained evidence,
  and none is needed to explain the observation (section 2 explains it).

Answers to the four required questions: (a) cell/class/regime/token-count
were observable before candidate output (frozen manifests) — yes;
(b) genuinely strategy/backend applicability information rather than
post-hoc labels — no candidate dimension meets the bar, because
(c) no split materially explains error behavior beyond the one failed case
(the tail is cross-cell); (d) prospectively encoding any of these as an
applicability key would be post-hoc relabeling, not regime detection.
**Explanation B (hidden mixture/applicability regime) is not supported.**

## 4. Propagation to downstream correctness

Direct trace for `h86-03-05-01` per-decision rows is not possible from
retained bytes (expunged); the retained verdict facts bound it: on the
holdout arm, 192/192 decisions SEMANTIC_PASS, zero
`DECISION_LOCAL_BOUND_EXCEEDED`, zero `DECISION_DOMAIN_ESCAPE`, zero
NaN/Inf — including the failing case. The +2.56% hidden-state RMS spike
produced zero downstream limit breaches and zero decision instability:
**attenuated to no observable downstream effect** on the retained record.

Quantified indirectly over the 584 calibration cases: the failing family
co-moves with consumer-facing error families (Spearman: 0.799 with
E_full max-abs, 0.811 with E_full RMS, 0.783 with case E_D, 0.893 with
fnhs max-abs, 0.852 with residual-stream RMS) — correlated but not
redundant. All 59 top-decile failing-family cases stayed within ALL other
14 frozen family limits, and their case E_D max equals the frozen E_D
bound (by construction of the max rule). Interpretation: the family is an
**early-warning tensor metric** with real co-movement but no demonstrated
independent causal path to decision failure anywhere in this campaign —
relevant to successor doctrine (S5/S6 below) but NOT a waiver of the #88
failure.

## 5. Statistical-contract audit

The frozen v3 design (reproduced exactly by the retained tool): 15 envelope
families + E_D = 16 simultaneous acceptance-bearing bounds; target marginal
coverage p=0.99 per family; simultaneous confidence 0.95; Bonferroni
alpha 0.05/16; distribution-free maximum-order-statistic tolerance
`ceil(log(alpha)/log(p))` = 574 ≤ 576.

The three statements are distinct and were conflated by the acceptance
rule:

1. **Tolerance statement** (what n=574/576 supports): P(at least 99% of the
   case population lies below X_(n)) ≥ 0.996875 per family — a coverage
   statement about the bound.
2. **Estimator**: `limit[e] = max(statistical_max[e], stress_max[e])` =
   the pooled sample maximum X_(584).
3. **Acceptance rule**: zero of 24 fresh holdout cases may exceed the
   limit.

The construction **targeted, but never guaranteed, zero holdout
exceedances**. Exact calculations (basis: the 576 statistical cases — the
8 selected stress cases are margin-extreme by selection and are NOT
pooled as exchangeable calibration draws; all 15 frozen limits are
statistical-arm driven, so the stress arm never enters the prediction
arithmetic):

- P(a single fresh case exceeds X_(576)) = 1/577 ≈ 0.17%.
- Under iid exchangeability, P(≥1 of 24 holdout cases exceeds the
  statistical-maximum limit) = 24/600 = **4.00% per family even with no
  distributional change at all** (equivalently, P(the global max of all
  600 cases lands in the 24-case holdout arm) = 24/600).
- If the bound had exactly 99% marginal coverage (the tolerance target),
  P(≥1 exceedance in 24) = 1 − 0.99²⁴ = **21.4%**.
- Zero-of-24 at 95% requires per-case coverage ≥ 99.79% (exceedance
  budget 0.00213/case), which the max-order-statistic rule delivers only
  with n ≥ 2700 at the Bonferroni confidence; the exchangeable zero-of-24
  95% requirement alone needs n ≥ 456 (24·0.95/0.05).
- 16 simultaneous families: between 4.00% (perfect dependence) and 47.96%
  (independence, P(none of 16 fails) = 0.96¹⁶ = 0.5204) built-in
  probability that at least one family registers a holdout exceedance
  somewhere.
- Selected stress arm: all 15 limits are statistical-arm driven (stress
  maxima 3–30x below statistical maxima), so the stress arm never raised
  any limit and — being selection-biased rather than exchangeable — does
  not improve the iid prediction-bound arithmetic.

The observed event — one case exceeding a sample-maximum limit by 2.56%
with zero semantic effect — is precisely what this arithmetic predicts
as an ordinary tail draw. **The acceptance rule was stricter than the
statistical statement it was built on.**

## 6. Successor envelope-family options (no thresholds proposed)

| id | direction | verdict |
|---|---|---|
| S1 | Prospective one-sided prediction bound matching the acceptance rule (claim = rule) | **Recommended core** |
| S2 | Keep estimator, restate acceptance as the coverage claim it makes | Fallback; doctrine decision |
| S3 | Stratified/applicability-conditioned envelopes | **Rejected on current evidence** (no split found, §3) |
| S4 | Log-scale parametric tail bound (log-normal QQ R² 0.986 for the failing family; cross-family fits not claimed) | Viable alternative; assumption-heavy |
| S5 | Demote the hidden-state family to telemetry | Maintainer doctrine decision; must precede v4 freeze |
| S6 | Two-tier: coherent acceptance core (E_full, E_D, integrity) + all-15-family mandatory telemetry | **Recommended companion** |

Full comparison matrix (correctness claim / assumptions / tuning-avoidance /
sample size / holdout contract / failure modes per option) is in
`diagnosis-record.json` → `successor_options`. None proposes a numeric
threshold; all forbid h86-* reuse as future calibration/holdout input.

**Recommendation for the next gate**: a successor methodology freeze that
(1) adopts S1 so the statistical claim and the zero-exceedance-style rule
coincide — either a larger calibration corpus (n ≥ 2700 for zero-of-24 at
the Bonferroni confidence) or an explicitly exceedance-tolerant prediction
rule (e.g. ≤k-of-m with exact beta-binomial levels) on a fresh corpus and
fresh sealed holdout; (2) adopts S6 tiering with all 15 families retained
as mandatory telemetry; (3) settles S5 (whether the normalized
hidden-state family remains acceptance-bearing) as an explicit doctrine
decision BEFORE the freeze. S3 should not be pursued.

## 7. Historical record / non-claims

- `R6_DENSE_ARCHITECTURE_FALSIFICATION_FAIL` — unchanged.
- #76 stopped v1 qualification (`PHASE0_STOP` adjudicated) — unchanged.
- #81 `CALIBRATION_SEMANTIC_FAIL` — unchanged, not reinterpreted.
- #88 `V3_HOLDOUT_FAIL` — unchanged, terminal; this diagnosis classifies
  the failure, it does not adjudicate a pass.
- #74 holdout sha `23311c55…` — sealed, untouched.
- `EXACT_TOKENS_REQUIRED` / `BIT_EXACT_REQUIRED` — unchanged, unsatisfied.
- No threshold widened, no case rerun, no holdout unsealed or reconstructed,
  no physical execution, no successor numeric threshold proposed.

## 8. Reproducibility

Everything above re-derives from committed bytes via
`python3 scripts/issue90_post_v3_diagnosis.py --out <path>`; the tool
fails closed on any pinned-hash drift. `diagnosis-record.json` in this
directory is its output (regenerate to verify byte-equality). Tests:
`python3 -m unittest tests.test_issue90_post_v3_diagnosis -v` (hash-drift
and missing-evidence negative controls, derived-not-constant checks,
exact statistical identities, purity, historical-verdict preservation).
