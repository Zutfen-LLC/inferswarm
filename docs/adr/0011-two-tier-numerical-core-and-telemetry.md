# 0011. Two-tier numerical core and mandatory telemetry

Date: 2026-09-04
Status: Accepted

## Context

ADR 0010 establishes exact integrity, qualified numerical execution equivalence,
and semantic output correctness as conjunctive layers. The first Gemma v3
contract placed fifteen numerical envelope identities in one conjunctive set.
Issue #88 therefore correctly ended `V3_HOLDOUT_FAIL` when one frozen
final-normalized-hidden-state RMS limit exceeded its threshold despite exact
integrity, finite outputs, and semantic gates passing. Issue #90 diagnosed the
observation as an ordinary tail but did not and cannot change that historical
verdict.

Future strategies still need numerical localization and drift evidence, but
causal upstream influence alone would make every internal tensor an acceptance
gate. The doctrine needs a prospective rule for distinguishing a numerical
property that independently establishes correctness from one that remains
mandatory evidence without independently deciding qualification.

## Decision

Adopt the two-tier numerical comparator defined in
[`post-v3-numerical-core-doctrine/DECISION.md`](../qualification/post-v3-numerical-core-doctrine/DECISION.md)
as an ADR 0010 numerical-layer refinement:

1. The qualification core is conjunctive: exact integrity, applicable
   finite-output requirements, acceptance-bearing numerical gates, and semantic
   gates must pass.
2. A numerical observable is acceptance-bearing only when its bounded comparison
   establishes a distinct strategy correctness property not covered by stronger
   core gates: a strategy-consumed output, theorem prerequisite, authoritative
   or future-use state, declared numerical semantic boundary, or demonstrated
   independent correctness risk.
3. Mandatory telemetry remains versioned, complete, finite-checked where
   declared, retained, and reportable. A finite telemetry threshold exceedance
   can create `DEGRADED` evidence-health/focused-revalidation work but does not
   itself fail an otherwise passing qualification.
4. Downstream subsumption is allowed only with prospective strategy evidence that
   a stronger core observation completely exercises the protected property on
   the same canonical inputs and leaves no lossy, authoritative, or future-use
   state unobserved. Absent that basis, a strategy must use
   `INSUFFICIENT_DOCTRINE_BASIS`, not silently demote the field.
5. Every future methodology declares each numerical family's tier before physical
   calibration. Tier changes create a new comparator/qualification version and
   require fresh calibration and holdout evidence.

The prospective first-Gemma classification is retained in
[`first-contract-classification.json`](../qualification/post-v3-numerical-core-doctrine/first-contract-classification.json).
It keeps all FP32 consumer-logit reducers acceptance-bearing and classifies
internal first-contract families as mandatory telemetry under the documented
subsumption argument. `E_full`, `E_D`, exact integrity, finite output, strict
exact-token behavior, containment, and tie semantics remain acceptance-bearing.

## Consequences

- Historical contracts remain immutable: issue #88 stays `V3_HOLDOUT_FAIL`.
- Telemetry cannot disappear or be relabeled retroactively to rescue a campaign.
- A future methodology can use distinct familywise qualification accounting for
  the core while retaining telemetry reference/alert bands outside that budget.
- Persistent state, semantic-boundary values, and theorem inputs receive an
  explicit anti-demotion review rather than an output-only shortcut.

## Hypotheses distinguished from decisions

This ADR does not choose a v4 statistical model, threshold, corpus, sample size,
holdout, public API, or physical qualification subject. It does not claim any
telemetry family is harmless, any model/backend is qualified, or that #88 would
pass under a changed contract.
