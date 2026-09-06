# 0012. Statistical qualification and consumer-metric doctrine

Date: 2026-09-06
Status: Accepted

## Context

ADR 0010 requires prospective qualification. ADR 0011 distinguishes an
acceptance-bearing numerical property from mandatory telemetry. Issue #105
showed that the v4 probability statement used full cross-cell exchangeability
while the methodology declared only within-cell exchangeability. It also showed
that p99 upper-tail prevalence was not an independently established
correctness property for the current deterministic greedy comparator.

Issue #108 resolved both forward doctrine questions from retained repository
evidence. Historical #88, #90, #93, #95, #97, and #105 verdicts remain frozen.

## Decision

Adopt
[`post-v4-statistical-metric-doctrine/DECISION.md`](../qualification/post-v4-statistical-metric-doctrine/DECISION.md)
as an ADR 0010/0011 forward refinement.

1. A successor qualification must state whether it claims marginal per-case
   coverage or zero-exceedance coverage for a finite campaign. It must state
   the target population, applicability scope, exchangeability assumptions,
   estimator construction, and familywise composition before calibration.
2. A pooled order-statistic construction is permitted only when a frozen IID
   target generator produces both calibration and future cases from one
   declared mixture population. The claim then applies to that mixture, not to
   every component or named stratum.
3. A qualification that needs named-stratum coverage must use named-stratum
   accounting. It must compose the covered stratum paths and metrics with a
   valid bound. It must not treat a fixed balanced-cell design as one pooled
   exchangeable sample without a prospective generator basis.
4. For the next Gemma comparator, full-vocabulary FP32 consumer-logit
   max-absolute difference and RMS remain acceptance-bearing. p99
   absolute-error moves to mandatory telemetry. This tier change requires a
   new comparator version and fresh qualification evidence.
5. For the current Gemma canonical-prefix profile, every acceptance-bearing
   consumer-logit metric and `E_D` applies to all eight canonical decisions.
   A subset cannot stand for the full canonical decision surface.

## Consequences

- Issue #109 must choose a permitted construction and declare its parameters
  before any physical v5 work.
- Issue #108 records permitted assumption profiles, construction classes, and
  compatibility constraints. It does not select a v5 profile or construction.
- A probability statement can no longer use a pooled maximum with only
  within-stratum exchangeability.
- p99 remains retained, finite-checked telemetry. Its finite exceedance alone
  does not fail a qualification under the new comparator.
- The next comparator has more complete canonical-decision measurement than
  v4. This can change future calibration burden. It does not alter v4.
- The pure-stdlib validator and static tests fail closed when an incompatible
  prospective statistical combination is proposed. They also verify every
  retained raw FP32 row and producer case record named by the hash-bound
  retention manifest.

## Hypotheses distinguished from decisions

This ADR does not choose a v5 threshold, sample count, corpus, holdout,
familywise error value, mixture weights, parametric model, hardware subject,
or physical qualification result. It does not claim the new comparator is
achievable or that any device/backend is qualified. It does not change a
historical verdict or admit consumed holdout observations as successor input.
