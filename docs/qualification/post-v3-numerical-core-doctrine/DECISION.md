# Post-v3 numerical-core doctrine decision (issue #93)

Status: accepted doctrine gate; prospective, API-unfrozen

Terminal disposition:

`NUMERICAL_CORE_TWO_TIER_DOCTRINE_ACCEPTED`

This decision is a doctrine/contract result only. It authorizes neither CUDA
execution nor a successor methodology, corpus, threshold, sample size, holdout,
or physical campaign. The exact next gate is a **prospective successor
methodology freeze** that declares its core and telemetry tiers before any
physical calibration.

## Scope and historical boundary

The historical v3 contract remains the contract used by issue #88. Its terminal
`V3_HOLDOUT_FAIL`, including the final-normalized-hidden-state RMS exceedance,
remains immutable. Issue #90 remains an ordinary-tail diagnosis, not a cause to
retune or reinterpret #88. Consumed `h86-*` evidence is diagnostic-only and is
not future calibration or holdout input. This gate sets no threshold.

Exact integrity, finite-output policy, strict exact-token semantics, `E_full`,
`E_D`, `DECISION_LOCAL_BOUND_EXCEEDED`, `DECISION_DOMAIN_ESCAPE`, and frozen
tie semantics remain acceptance-bearing. A semantic pass never waives a failure
of a numerical observation declared acceptance-bearing by its frozen contract.

## Q1 — necessary operational rule for the numerical core

A checkpoint/metric is an **acceptance-bearing numerical gate** only if its
prospectively declared bounded comparison is necessary to establish a distinct
strategy correctness property that the acceptance core otherwise cannot prove.
At least one of these must be true:

1. it is a full declared domain of a direct strategy-consumed output whose
   numerical value determines an externally committed behavior;
2. a mathematical semantic theorem or a declared semantic gate uses its bound
   as a premise (for example the observed `E_D` bound);
3. it is authoritative mutable numerical state, or state intended for future
   use, for which the accepted observation does not fully exercise all future
   consumers;
4. it crosses a strategy semantic boundary whose declared computation requires
   bounded numerical equivalence in addition to exact bytes; or
5. retained prospective evidence shows a distinct correctness risk that no
   stronger core gate already covers.

Causal upstream influence alone is not sufficient: every intermediate can
influence an output. A full tensor domain says how to compare a selected
checkpoint; it does not require every internal checkpoint to become a gate.

### Downstream subsumption

An internal comparison may be mandatory telemetry when the strategy documents
that its only protected property is fully exercised by a stronger downstream
acceptance-bearing observable on the same canonical input, with no unobserved
state lifetime or lossy semantic transformation between them. This is
**downstream subsumption**, not deletion of evidence.

Subsumption is unavailable for persistent or future-use state, authoritative
mutable state, a lossy semantic boundary, an independently strategy-consumed
surface, or a theorem prerequisite. A strategy must make that justification
prospectively; an observed output match after the fact is not sufficient.

Promotion from telemetry requires a new comparator version and prospective
justification that identifies the distinct property, comparison domain,
reducer, finite policy, applicability dimensions, calibration/holdout method,
and why existing core gates cannot subsume it. It cannot change an old verdict.

## Q2 — two-tier contract

S6 is doctrinally valid. Every future comparator must record a prospective tier
for every numerical family before physical calibration:

- **qualification core:** exact integrity, finite-output requirements,
  acceptance-bearing numerical gates, and semantic gates. These are
  conjunctive; a valid exceedance fails the frozen qualification.
- **mandatory telemetry:** versioned checkpoint/domain/reducer/finite/reporting
  semantics and retained per-case evidence. A telemetry observation is required
  for evidence completeness, but its numeric exceedance alone does not fail an
  otherwise passing qualification.

Tier identity is an applicability and comparator-contract identity. Moving a
family between tiers creates a new comparator/qualification contract version
and requires new prospective qualification evidence.

## Q3 — first-contract forward classification

`first-contract-classification.json` enumerates all fifteen actual frozen
family/metric identities from the committed checkpoint-family map. Prospectively:

- all three full-vocabulary FP32 consumer-logit metrics are
  `ACCEPTANCE_BEARING`; in particular `E_full` remains mandatory;
- `E_D` remains an additional acceptance-bearing semantic prerequisite and is
  not counted as a replacement for the consumer-logit family;
- local BF16 operation, hidden residual-stream, final normalized hidden-state,
  and BF16-logit families are `MANDATORY_TELEMETRY` because this first strategy
  has not established an independent core property for them beyond the
  downstream full-vocabulary consumer surface;
- no actual first-contract identity is silently omitted or labeled
  `INSUFFICIENT_DOCTRINE_BASIS`.

This is a general-rule application, not an exemption keyed to the metric that
failed #88. A future strategy may classify an analogous state as core if it
meets the operational rule, especially for a persistent/future-use or
boundary-owned state.

## Q4 — telemetry operations and evidence health

Telemetry remains mandatory retained evidence. A telemetry exceedance records
its values, identity, reducer, provenance, and comparison context; it can mark
qualification health `DEGRADED` pending focused revalidation, trigger
localization or an applicability review, and support a later prospective
promotion decision. It does not turn a passing qualification into a failure,
suspend a resource, or establish integrity distrust unless separate evidence
proves an exact-integrity defect or a failed acceptance-bearing gate.

`DEGRADED` is an evidence-health action, not quarantine. The narrow response
must be justified by the affected observable and its prospective strategy
scope; it does not retroactively alter historical records.

## Q5 — statistical qualification boundary

Future methodology applies its familywise coverage/confidence and acceptance
rule to acceptance-bearing numerical families. Mandatory telemetry may have
frozen reference or alert bands and must retain all measurements, but it does
not consume the qualification familywise error budget unless that future
methodology expressly places its alert in the core. This decision selects no
statistical model, parameter, threshold, corpus, sample size, or holdout rule.

## Q6 — authority mapping

ADR 0010 remains the accepted three-layer correctness decision. Accepted ADR
0011 refines its numerical-layer supplement, states the tier rule, and preserves
historical frozen-contract conjunctions.
`docs/architecture/numerical-equivalence-contract.md` is the detailed
normative wording; `ROADMAP.md` sequences the successor methodology gate.

### Retained before-to-after normative mapping

| Current authority / wording | Accepted replacement wording | Historical-contract carve-out |
|---|---|---|
| ADR 0010 §1–§3: qualified numerical execution equivalence is one conjunctive correctness layer, with strategy-declared numerical gates. | ADR 0011 retains that layer and makes its qualification core conjunctive: exact integrity, finite policy, acceptance-bearing numerical gates, and semantic gates. | The three-layer architecture is unchanged; issue #88 remains `V3_HOLDOUT_FAIL` under its frozen all-envelope conjunction. |
| Numerical-equivalence contract §2: strategy owns “mandatory numerical metrics and gates.” | The strategy prospectively owns acceptance-bearing numerical gates **and** mandatory telemetry families, including their tier identity. | No historical comparator or evidence record receives a retroactive tier change. |
| Contract §5.1 / §6: any exceeded mandatory frozen numerical limit is an unconditional failure. | Any exceeded **acceptance-bearing** frozen numerical limit is an unconditional failure; a finite mandatory-telemetry exceedance is evidence-health material, not qualification failure. | This accepted distinction applies only to a successor comparator version. It does not waive the #88 final-hidden-state limit. |
| Contract §7: mandatory metrics participate in the prospectively frozen statistical qualification method. | Future methodology declares every family's tier before calibration; familywise qualification accounting applies to core families, while telemetry alert/reference bands are not acceptance limits unless expressly promoted. | No successor threshold, sample size, corpus, or holdout is selected here, and consumed `h86-*` data remain ineligible. |

## Non-claims

This decision does not prove that any model/backend pair is qualified, that a
telemetry family is harmless, that #88 would pass under a different contract,
that all internal tensors are subsumed, or that telemetry can be omitted.
It creates no public API and no physical-execution authorization.
