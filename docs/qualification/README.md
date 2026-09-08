# Correctness qualification

This directory is the record of a single long question, asked five times:

> Can heterogeneous InferSwarm execution of a dense model be shown *correct*
> against a trusted reference, under a standard fixed before the experiment
> runs?

It exists because historical R6 / issue #65 terminated
`R6_DENSE_ARCHITECTURE_FALSIFICATION_FAIL` and issue #71 localized the first
single-versus-distributed difference to legal backend execution on different
devices. That is not a bug to patch; it is a correctness contract the project
did not yet have.

The controlling doctrine is
[ADR 0010](../adr/0010-heterogeneous-numerical-equivalence.md) and its
normative supplement
[`architecture/numerical-equivalence-contract.md`](../architecture/numerical-equivalence-contract.md),
refined by [ADR 0011](../adr/0011-two-tier-numerical-core-and-telemetry.md) and
[ADR 0012](../adr/0012-statistical-qualification-and-consumer-metric-doctrine.md).

Correctness is the conjunction of three layers:

1. **exact integrity** — model state, inputs, and transport are byte-exact;
2. **qualified numerical execution equivalence** — declared metric families
   stay inside limits derived *before* the deciding evidence is seen;
3. **strategy-declared semantic output correctness** — execution satisfies
   the selected semantic profile. For greedy generation, the strict profile
   requires exact token identity; the decision-stability profile requires
   identity at stable canonical-prefix decisions and permits only bounded
   ambiguity at unstable decisions, after the decision-local bound and domain
   containment checks pass. It does not promise identical free-running token
   sequences.

All three must hold. Matching output never waives a numerical failure, and a
passing numerical envelope never waives a semantic one.

## The rules that make this record trustworthy

- **Prospective freeze.** Corpora, metric families, sample sizes, the
  threshold-derivation procedure, and the acceptance rule are frozen and
  committed *before* physical calibration. Threshold values are then derived
  only from complete calibration evidence under that procedure and committed
  *before* holdout unsealing. A methodology directory describes itself at
  freeze time and is never updated with its outcome.
- **Single-use sealed holdout.** Each version's holdout is generated once,
  CMS-sealed, its plaintext discarded, and opened at most once under explicit
  maintainer authorization. Once consumed, its observations are permanently
  diagnostic-only and can never become successor calibration, stress, or
  holdout inputs.
- **Terminal means terminal.** A failed campaign authorizes no threshold
  tuning, no rerun, no resealing, and no replacement holdout. The successor is
  a *new* methodology with a new corpus and a new holdout.
- **Failures are diagnosed, not reinterpreted.** Each failure produced a
  read-only diagnosis tool that re-derives every published quantity from
  retained bytes, and — where the diagnosis found a design defect — a doctrine
  decision that constrains the next attempt only prospectively.

## Lane record

Read top to bottom; each row is caused by the one above it.

| Area | Issue | Kind | Terminal state |
|---|---|---|---|
| [`gemma4-12b-it-v1/`](gemma4-12b-it-v1/README.md) | #74 | methodology freeze | first prospective freeze: 576 balanced calibration prompts, 15 numerical envelopes, sealed 24-case holdout |
| [`gemma4-12b-it-v2/`](gemma4-12b-it-v2/METHODOLOGY.md) | #77 / #79 | methodology repair + tooling | stress-pool eligibility repaired without changing the pre-registered margin definition |
| [`gemma4-12b-it-v2-campaign-81/`](gemma4-12b-it-v2-campaign-81/REPORT.md) | #76 / #81 | physical campaign | #76 stopped `STRESS_SELECTION_BLOCKED`; #81 terminal **`CALIBRATION_SEMANTIC_FAIL`** — 236/576 statistical and 4/8 stress cases changed a greedy token under the strict exact-token profile. Thresholds never derived; holdout never opened. |
| [`gemma4-12b-it-semantic-83/`](gemma4-12b-it-semantic-83/README.md) | #83 | contract adjudication | decision-stability semantic contract accepted: canonical-prefix replay separated from free-running behavior, mandatory `E_full`, supplemental decision-local `E_D`, frozen argmax tie-break |
| [`gemma4-12b-it-v3/`](gemma4-12b-it-v3/README.md) | #86 | methodology freeze | first executable implementation of the #83 contract; fresh corpora and sealed v3 holdout |
| [`gemma4-12b-it-v3-campaign-88/`](gemma4-12b-it-v3-campaign-88/TERMINAL-REPORT.md) | #88 | physical campaign | terminal **`V3_HOLDOUT_FAIL`** — the semantic layer passed everywhere (4672/4672 calibration, 192/192 holdout), but one inherited `final-normalized-hidden-state:rms-difference` envelope exceeded its frozen limit by 2.56% |
| [`gemma4-12b-it-post-v3-envelope-diagnosis/`](gemma4-12b-it-post-v3-envelope-diagnosis/DIAGNOSIS.md) | #90 | diagnosis | **`V3_ENVELOPE_DIAGNOSIS_ORDINARY_TAIL`**, maintainer-accepted (PR #92, `b3562c48`) — an ordinary heavy-tail draw, no pre-observable applicability split; the v3 acceptance rule was stricter than the statistical statement it was built on |
| [`post-v3-numerical-core-doctrine/`](post-v3-numerical-core-doctrine/DECISION.md) | #93 / ADR 0011 | doctrine | **`NUMERICAL_CORE_TWO_TIER_DOCTRINE_ACCEPTED`** — a comparator must declare an acceptance-bearing core and mandatory retained telemetry before physical calibration |
| [`gemma4-12b-it-v4/`](gemma4-12b-it-v4/METHODOLOGY.md) | #95 | methodology freeze | **`GEMMA_V4_PREDICTION_ALIGNED_METHODOLOGY_FROZEN`** — 24 cells × 79 cases, four acceptance-bearing scalar families separated from twelve telemetry identities |
| [`gemma4-12b-it-v4-campaign-97/`](gemma4-12b-it-v4-campaign-97/b/TERMINAL-REPORT.md) | #97 | physical campaign | terminal **`V4_HOLDOUT_CORE_FAIL`** — calibration passed completely; one holdout case exceeded the `fp32-consumer-logits:p99-absolute-error` limit by 0.75% (16.765625 vs 16.640625), semantic layer 192/192 |
| [`gemma4-12b-it-post-v4-core-diagnosis/`](gemma4-12b-it-post-v4-core-diagnosis/DIAGNOSIS.md) | #105 | diagnosis | **`V4_CORE_DIAGNOSIS_MIXED`** — an ordinary tail draw made terminal by two design defects: the p99 order-statistic knife edge, and a prediction theorem whose Bonferroni statement was exact only under full cross-cell exchangeability the design never established |
| [`post-v4-statistical-metric-doctrine/`](post-v4-statistical-metric-doctrine/DECISION.md) | #108 / ADR 0012 | doctrine | **`POST_V4_STATISTICAL_METRIC_DOCTRINE_ACCEPTED`** — pooled order-statistic prediction is permitted only for an IID frozen mixture population; named-cell coverage requires named-stratum accounting; p99 moves to telemetry |
| [`gemma4-12b-it-v5/`](gemma4-12b-it-v5/METHODOLOGY.md) | #109 | methodology freeze | **`GEMMA_V5_CORRECTED_QUALIFICATION_METHODOLOGY_FROZEN`** — a 24-component IID mixture population replaces balanced cells; 1416 calibration + 24 sealed holdout draws from the same generator, giving a valid `3/60 = 5%` familywise bound |
| [`gemma4-12b-it-v5-campaign-110/`](gemma4-12b-it-v5-campaign-110/README.md) | #110 / #115 | physical campaign | terminal **`V5_QUALIFICATION_PASS`** — the single-use holdout was consumed exactly once: 24/24 reference and 24/24 candidate passes, 192/192 semantic identities, zero invalid attempts, all within the frozen #109 limits. #115 then retained a hash-bound raw-evidence archive and completed the audited cleanup. |

## Why each attempt failed, in one line each

- **v2 / #81** — execution failed the selected strict exact-token profile.
  Issue #83 introduced the decision-stability profile as a prospective
  alternative for qualified heterogeneous variation. Both profiles remain
  valid; #81 remains `CALIBRATION_SEMANTIC_FAIL` under its frozen contract.
- **v3 / #88** — the *metric set* was wrong: an internal checkpoint family was
  acceptance-bearing without evidence that it gated a real correctness path.
  Fixed by the #93 core/telemetry split. Accepting the #90 diagnosis explained
  the failure; it did not reclassify it — #88 remains `V3_HOLDOUT_FAIL`.
- **v4 / #97** — the *statistics* were wrong: the prediction theorem assumed an
  exchangeability the balanced-cell design did not establish, and p99 added an
  order-statistic knife edge. Fixed by the #108 doctrine and the v5 mixture
  population.
- **v5 / #110** — passed.

That sequence is the point of the lane. Each failure was terminal, was
diagnosed from retained bytes, and produced a prospective constraint rather
than a retuned threshold.

## What a `V5_QUALIFICATION_PASS` does and does not authorize

It **does** make applicable V5 qualification evidence available to the generic
planner's applicability barrier, which is what unblocked the successor dense
full-integration gate, issue #117.

It does **not** qualify a different model, revision, representation, backend,
or stage geometry. Applicability is decided by exact subject-digest equality
against the accepted qualification subject; every materially different
candidate derives `QUALIFICATION_NOT_APPLICABLE`. See
[`../implementation/r6-successor-dense-full-integration-117/`](../implementation/r6-successor-dense-full-integration-117/README.md).

## Directory shape

A version generally has a methodology area and a campaign area:

```text
gemma4-12b-it-vN/            frozen methodology (never updated with outcomes)
  METHODOLOGY.md             corpora, metric families, gates, acceptance rule
  REDUCER.md / TOOLING.md    numerical reduction; tool inventory and SHAs
  manifests/                 corpora, commitments, custody, disjointness proofs
  schemas/                   versioned JSON Schemas
  sealed/                    holdout ciphertext + recipient certificate
  MANIFEST.sha256            hashes of every review artifact

gemma4-12b-it-vN-campaign-NN/  the physical execution and its terminal verdict
```

Sealed material is ciphertext only. Private holdout keys and secret seeds are
never in this repository; custody records are non-secret metadata that name
the custodians and prove independence.

## Tooling

Every derivation, freeze, selection, commitment, and preflight in this lane is
CPU-only, deterministic, and fail-closed. The inventory is in
[`../../scripts/README.md`](../../scripts/README.md); the frozen-producer rule
there applies to all of it. Most of these tools are hash-pinned by the
evidence in this directory — editing one invalidates the record that cites it.
