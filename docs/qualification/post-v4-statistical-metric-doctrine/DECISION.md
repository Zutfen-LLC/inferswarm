# Post-v4 statistical and metric doctrine decision (issue #108)

Status: accepted prospective doctrine gate. This decision is API-unfrozen.

Terminal disposition:

`POST_V4_STATISTICAL_METRIC_DOCTRINE_ACCEPTED`

This gate authorizes no v5 corpus, sample count, threshold, sealed holdout,
physical calibration, or model execution. It uses retained repository evidence
only. Historical #88, #90, #93, #95, #97, and #105 records remain immutable.
Consumed `h86-*` and `h95-*` observations remain diagnostic-only and cannot be
used as successor calibration, stress, or holdout inputs.

## Decision A — statistical qualification contract

### Q1. Qualification target

The primary qualification claim is a campaign-level claim. Before calibration,
the methodology must freeze a target case generator, a future campaign size,
the acceptance-bearing metric set, and a familywise error budget. The claim is:

> For a fresh campaign generated from that same target population, the
> unconditional probability of zero strict exceedances in all
> acceptance-bearing numerical families is at least `1 - alpha_familywise`.

This is not a marginal per-case claim. It is not a conditional-on-calibration
claim. It is not a claim for every workload cell. The methodology may also make
a marginal per-case order-statistic claim, but it must state it separately.

### Q2. Assumptions and applicability

Full cross-cell exchangeability is not inferred from #105. The v4 balanced
24-cell design did not make all retained numerical errors exchangeable. Its
content and length cells intentionally represent different conditional
populations.

The successor may use pooled calibration only for a prospectively frozen IID
mixture target. Each calibration and holdout case must be an independent draw
from the same generator, including a precommitted component-selection rule and
component weights. This establishes marginal exchangeability of numerical-error
values for the mixture population. It does not establish per-component or
per-cell coverage.

If the target requires a claim for named strata, it must use named-stratum
exchangeability and stratum-specific accounting. No post-hoc split or pooling
is permitted. A pooled maximum from a fixed balanced-cell design under only
within-cell exchangeability is invalid.

### Q3. Permitted construction classes

[`statistical-contract.json`](statistical-contract.json) compares each allowed
class by assumptions, finite-sample guarantee, familywise composition,
sample-burden scaling, and failure modes. The key distribution-free identities
are:

- For `N` exchangeable calibration cases and `H` exchangeable future campaign
  cases, a calibration maximum has strict-exceedance probability at most
  `H/(N+H)`. Equality requires continuously distributed values.
- For the `k`th calibration order statistic and one exchangeable future case,
  strict-exceedance probability is at most `(N+1-k)/(N+1)`. Equality requires
  continuously distributed values.
- For named strata, the campaign bound is at most
  `sum_s H_s/(N_s+H_s)` before metric composition.

The methodology must combine acceptance-bearing metric budgets with Bonferroni
or a stronger valid bound. It must not assume metric independence without a
separate proof. Parametric and hierarchical methods are permitted only with
their assumptions, validation rule, predictive coverage theorem, and failure
mode declared before calibration. They do not receive a distribution-free
claim by default.

The included static calculator reproduces the v4 defect: 24 strata with 79
calibration and one holdout case each give `24/80` per family, while an IID
mixture of 1896 calibration and 24 holdout cases gives `24/1920 = 1/80`.
The latter identity has a different assumption and target.

## Decision B — numerical-core metric doctrine

### Q4. Core properties

`fp32-consumer-logits:max-absolute-difference` remains acceptance-bearing. It
protects a pointwise full-vocabulary bound. `fp32-consumer-logits:rms-difference`
remains acceptance-bearing. It protects an aggregate full-vocabulary error
property that the pointwise limit does not quantify. `decision_local_E_D`
remains acceptance-bearing because the semantic theorem requires its observed
bound on every canonical decision.

`fp32-consumer-logits:p99-absolute-error` measures upper-tail prevalence. The
current deterministic greedy strategy has no separate consumer or theorem that
requires a percentile bound after the pointwise, aggregate, decision-domain,
containment, and semantic gates pass. The complete classification is in
[`metric-core-classification.json`](metric-core-classification.json).

### Q5. p99 disposition

The disposition is `P99_MOVE_TO_MANDATORY_TELEMETRY`.

This is not a response to the v4 failure result. The basis is prospective
subsumption: p99 adds no independently justified correctness property to this
comparator. It remains mandatory, finite-checked, retained, and reportable
telemetry. A future strategy can promote it only with an independent
strategy-consumed property or theorem that the other core gates do not cover.

### Q6. Capture positions

For the current Gemma canonical-prefix profile, all eight teacher-forced
canonical decisions are required for every acceptance-bearing consumer-logit
metric and for `E_D`. The case reducer is the maximum across those decisions.
Issue #105 showed that the omitted decision could have the larger full-vocabulary
error. This rule is prospective. It makes no alternate v4 pass/fail claim.

## Architecture and forward change

ADR 0012 adopts this decision as an ADR 0010/0011 forward refinement. It moves
p99 to telemetry only for the new comparator and requires complete current
Gemma canonical-decision coverage. The normative numerical-equivalence
supplement receives the matching forward reference. Issue #109 is the next
prospective v5 methodology-freeze gate.

## Non-claims

- This decision sets no numerical limit, sample count, corpus, or holdout.
- It does not establish a qualified model, backend, device, or deployment.
- It does not claim all workload cells have one numerical-error distribution.
- It does not reinterpret #97 or any other historical terminal verdict.
- It does not license a new physical observation or use consumed holdout data.

## Reproduction

Run:

```sh
python3 scripts/issue108_post_v4_statistical_metric_doctrine.py
python3 -m unittest tests.test_issue108_post_v4_statistical_metric_doctrine -v
```

The tool is pure stdlib and CPU-only. It verifies the source hashes in
[`source-bindings.json`](source-bindings.json) before it emits the doctrine
record.
