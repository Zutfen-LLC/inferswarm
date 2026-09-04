# Heterogeneous numerical-equivalence contract

Status: **Normative Fabric Doctrine supplement**

Adopted by [ADR 0010](../adr/0010-heterogeneous-numerical-equivalence.md).
This supplement refines Fabric Doctrine sections 4, 5, 6, and 10 for
correctness-bearing heterogeneous backend execution. It is API-unfrozen: the
concepts and invariants are normative; names of classes, enums, schemas, and
public interfaces are not.

Historical R6 remains `R6_DENSE_ARCHITECTURE_FALSIFICATION_FAIL`. Nothing here
retroactively changes that experiment or its frozen comparator.

## 1. Three-layer correctness

InferSwarm correctness is conjunctive:

```text
correct candidate
  = exact integrity invariants pass
  AND qualified numerical execution equivalence passes
  AND strategy-declared semantic output correctness passes
```

Evidence from one layer cannot waive failure in another.

### 1.1 Exact integrity invariants

Exact integrity proves that the authorized computation actually ran. Applicable
facts include:

- model/checkpoint identity and content hashes;
- representation, packing/transform provenance, and frozen semantic precision;
- immutable Execution Plan identity;
- required Logical State Unit coverage and declared shared-state exceptions;
- Materialization owner/source/version reconciliation;
- sender/receiver semantic boundary shape, dtype, length, bytes, and digest;
- session, epoch, generation, realization, plan, operation, and position
  attribution;
- mutable authority and fencing state;
- observed backend/device/path identity where qualification requires it;
- absence of silent fallback or substitution.

An exact-layer mismatch stops the comparison. No floating-point tolerance is
meaningful for wrong state, transport corruption, stale authority, or an
unauthorized execution path.

### 1.2 Qualified numerical execution equivalence

Numerical equivalence applies only to declared floating-point outputs after the
exact layer proves that:

- inputs and immutable state are exact;
- semantic configuration is exact;
- declared shape/dtype semantics are exact;
- transfer integrity and attribution are exact;
- the observed backend path matches an applicable qualification subject.

A Model Execution Strategy may then accept bounded floating-point differences
under a versioned comparator contract and applicable qualification evidence.
There is no universal epsilon and no assumption that one tolerance is valid for
all tensor families, representations, models, or backends.

### 1.3 Semantic output correctness

A strategy declares semantic gates separately from tensor-error gates. For
deterministic greedy generation the strategy declares one of two profiles
(issue #83; both remain valid, neither implies the other):

- **strict exact-token profile** — exact deterministic greedy-token identity
  at every step (`EXACT_TOKENS_REQUIRED`, the operator-facing
  `BIT_EXACT_REQUIRED` policy of §9); or
- **decision-stability profile** — a *supplemental semantic layer on top of
  the unchanged mandatory numerical envelopes*: the strategy prospectively
  freezes a decision domain `D ⊆ {0..V−1}` with reference winner `a ∈ D`, a
  supplemental qualified consumer-logit max-absolute bound `E_D` on `D`
  (§5.4), and the deterministic argmax/tie-break rule (§1.3.1). At each
  canonical decision, with `j` the actual candidate full-vocabulary emitted
  winner, evaluated in fail-closed order:
  (1) the observed decision-local bound on the acceptance-bearing row,
  `max_{i∈D} |candidate_i − reference_i| ≤ E_D`, must hold — otherwise
  the decision fails immediately (`DECISION_LOCAL_BOUND_EXCEEDED`); the
  stability theorems are licensed only after the observed row proves the
  frozen `E_D` assumption, and passing `E_full` does not imply this
  tighter check passes;
  (2) if `j ∉ D` the decision fails immediately
  (`DECISION_DOMAIN_ESCAPE`);
  (3) if the reference top1–top2 margin on `D`
  `m_D > 2E_D` (stable decision), exact identity `j == a` is required;
  (4) when
  `m_D ≤ 2E_D` (unstable decision, including the tie boundary) the emitted
  token must lie in the ambiguity set
  `A_ED(r) = { k ∈ D | r[a] − r[k] ≤ 2E_D }`; after the first allowed
  unstable divergence the case branches and later free-running steps are
  excluded from same-input semantic evaluation (they are no longer
  same-input comparisons). Numerical envelopes are qualified exclusively on
  canonical identical-prefix replay.

The `m_D > 2E_D` stability rule and the `2E_D` admissibility bound are
theorems of the symmetric max-absolute envelope (issue #83
SEMANTIC-CONTRACT §3), not empirical tolerances.

#### 1.3.1 `E_D` supplements and never replaces the numerical layer

The decision-stability profile does not modify the numerical layer. The
mandatory FP32 consumer-logit qualification remains over the full
vocabulary where practical (`E_full`, §5.4); top-k/decision-local domains
may supplement but not replace it. A decision-stability qualification
requires the mandatory numerical envelopes (including `E_full`) to pass
AND the decision-local `E_D`/containment/stability gate to pass. A smaller
`D` never waives full-vocabulary correctness. The frozen `E_D` is an
assumption each acceptance-bearing row must prove: the observed
`max_{i∈D} |candidate_i − reference_i|` must not exceed `E_D` on any
calibration or fresh-holdout decision, checked before containment,
stability, or ambiguity adjudication (`DECISION_LOCAL_BOUND_EXCEEDED`
otherwise); passing `E_full` never implies this tighter per-row check.
A proper-subset decision
domain is valid only for contexts whose qualification demonstrates zero
decision-domain escapes under the frozen method (fail-closed
`DECISION_DOMAIN_ESCAPE`). Because `m_D = 2E_D` can produce ties, the
frozen argmax/tie-break semantics are part of the semantic profile's
applicability key whenever ties can affect emitted tokens; mismatched
reference/candidate tie-breaking makes the profile inapplicable or failed,
and `m_D = 2E_D` is treated as unstable absent a stronger prospective
proof.

Other semantic gates a strategy may declare:
- exact rank-one identity;
- top-k membership/overlap where appropriate;
- bounded rank movement;
- selected-token margin requirements;
- deterministic-sampling identity only when RNG, seed, draw order, logits
  processing, and sampling implementation are frozen;
- a separately defined statistical contract for intentionally nondeterministic
  output.

Small tensor error does not waive a changed semantic decision. Conversely,
matching token IDs do not waive an excessive mandatory numerical error.

## 2. Comparator ownership

The **Model Execution Strategy owns the numerical comparator and semantic output
contract**.

The strategy defines:

- comparison checkpoints and domains;
- mandatory numerical metrics and gates;
- semantic output profile;
- reference/candidate relationships;
- applicability dimensions that can materially change correctness.

A backend adapter may implement capture and metric mechanics, identify the
observed backend path, and report execution geometry. A qualification evaluator
applies the frozen contract to retained evidence.

The generic planner does not inspect tensors, evaluate logits, or contain
model-, device-, CUDA-, or backend-specific thresholds.

## 3. Numerical qualification

Numerical qualification is **correctness-bearing feasibility/integrity
evidence**, not merely hardware capability and not operator policy.

A conceptual qualification records enough identity to answer:

> Is this candidate implementation, in this declared context, qualified under
> this strategy comparator/semantic contract using evidence set X?

A qualification may conceptually include:

- qualification identity/state;
- comparator contract identity/version;
- reference and candidate implementation identities;
- model/revision and representation/precision scope;
- backend and software-stack scope;
- device architecture/class and ordered role mapping;
- execution-geometry/sequence regime;
- semantic profile identity;
- evidence/provenance identity;
- applicability result and reasons.

These are conceptual fields, not a frozen schema.

A compatible but unqualified candidate does not enter the correctness-bearing
feasible plan set.

## 4. Applicability key

### 4.1 Semantic identity

A mismatch in these dimensions defines a different correctness subject:

- immutable model/checkpoint identity;
- strategy identity/version when operation/state semantics change;
- comparator contract identity/version;
- representation and material precision semantics;
- semantic execution mode such as prefill/replay/decode where relevant;
- frozen comparison checkpoints/domains and semantic profile.

### 4.2 Evidence-applicability identity

Qualification evidence must record and initially match exact observable
correctness dependencies such as:

- candidate/reference backend implementation/build;
- torch/Triton/native-extension identities;
- CUDA/ROCm/oneDNN/other relevant math-runtime/library identity when observable;
- driver under the initial strict policy;
- device architecture and device class;
- ordered strategy-role mapping;
- math mode, attention backend, deterministic/configuration flags;
- matrix/attention/chunk/sequence geometry domains that can change kernel/path
  selection;
- runtime capacity only when it materially changes the executed path.

Broader compatibility ranges require explicit evidence. Semantic version labels
alone do not prove numerical compatibility.

### 4.3 Diagnostic metadata

Retain but do not key by default:

- device UUID/serial;
- Node/host/PCI address/topology;
- clocks, power, thermal/utilization state;
- memory/allocator headroom;
- timestamp/operator;
- exact kernel/algorithm identifier when observable but not contractually
  selected.

Promote a diagnostic field into the applicability key when evidence demonstrates
that it materially changes numerical behavior.

### 4.4 Device-class claims

A device-class qualification requires cross-card evidence from at least two
physical cards of that class when available. Otherwise the claim remains
instance-bound or explicitly `INSUFFICIENT_EVIDENCE` for class generalization.

## 5. Comparator metrics

A strategy may define additional metrics, but the first heterogeneous numerical
contract should distinguish mandatory gates from diagnostics.

### 5.1 Mandatory numerical gates for the first contract

- maximum absolute difference over the frozen complete comparison domain;
- RMS difference over that domain;
- a prospectively declared tail-percentile absolute-error measure;
- finite output: NaN/Inf are unconditional failures unless the strategy
  explicitly declares such values semantically valid, which the first Gemma
  contract does not.

### 5.2 Mandatory measurements / semantic gates

- exact equality is always measured and is a gate for exact fields and strict
  bit-exact policy;
- under the strict exact-token profile, deterministic greedy selected-token
  identity is exact at every step;
- under the decision-stability profile (issue #83), the reference top1–top2
  margin per decision, the observed decision-local bound
  `max_{i∈D} |candidate_i − reference_i| ≤ E_D` on every
  acceptance-bearing row (fail-closed `DECISION_LOCAL_BOUND_EXCEEDED`,
  checked before any theorem adjudication),
  decision-domain containment of the actual candidate
  emitted winner (fail-closed `DECISION_DOMAIN_ESCAPE`), and the candidate
  decision's membership in the frozen ambiguity set are mandatory
  measurements and gates. These are supplemental to — and conjunctive with
  — the mandatory numerical gates of §5.1/§5.4, including the
  full-vocabulary FP32 consumer-logit envelope `E_full`; they never replace
  them.

### 5.3 Supporting diagnostics

Useful diagnostics include:

- mean and signed-mean error;
- ULP-style error at same-operation/same-dtype checkpoints;
- relative error with a frozen scale floor;
- cosine/Pearson correlation;
- rank/Spearman behavior;
- top-k overlap;
- selected-token margin;
- max-error coordinates and source/candidate values.

Correlation or rank similarity is not sufficient as a sole correctness gate for
logits. ULP limits are useful locally but are not a universal accumulated-model
gate.

### 5.4 Comparison domains

Comparison domains are frozen before candidate output is observed. Full tensor
domains are preferred when practical. Final-row logits should use the full
vocabulary when practical; a historical/top-k subset can supplement but should
not be the sole qualification domain.

This rule governs the **numerical layer** and is unchanged by issue #83's
decision-stability profile: the full-vocabulary FP32 consumer-logit
max-absolute envelope (`E_full` =
`fp32-consumer-logits:max-absolute-difference`) remains a mandatory
qualification envelope. The decision-stability profile's frozen decision
domain `D` and its supplemental bound `E_D` live in the **semantic layer**
(§1.3.1): they are additional and conjunctive, never a replacement for or
waiver of the full-vocabulary numerical domain. If `D` is a proper subset,
the observed decision-local bound on the acceptance-bearing row
(`max_{i∈D} |candidate_i − reference_i| ≤ E_D`) is checked first, before
containment or any theorem adjudication (`DECISION_LOCAL_BOUND_EXCEEDED`
otherwise; passing `E_full` never implies it), the actual candidate
full-vocabulary emitted winner must be contained in
`D` on every acceptance decision (`DECISION_DOMAIN_ESCAPE` otherwise), and
the frozen deterministic argmax/tie-break rule is part of the semantic
profile because equality `m_D = 2E_D` can produce ties.

## 6. Unconditional failures

Fail closed on:

- exact integrity mismatch;
- wrong shape;
- wrong frozen semantic dtype;
- NaN/Inf at declared finite checkpoints;
- deterministic greedy-token mismatch under a profile that requires exact
  tokens (strict profile), or the observed decision-local error on the
  acceptance-bearing row exceeding the frozen `E_D` —
  `DECISION_LOCAL_BOUND_EXCEEDED`, a decision outside the frozen ambiguity
  set / a mismatch on a provably stable decision / the actual candidate
  full-vocabulary emitted winner outside the frozen decision domain
  `D` — `DECISION_DOMAIN_ESCAPE` (decision-stability profile);
- silent fallback/substitution;
- missing/inapplicable qualification for correctness-bearing serving;
- any exceeded mandatory frozen numerical limit.

A numerically close tensor cannot repair an exact or semantic failure. Matching
semantic output cannot waive a failed mandatory numerical envelope.

Missing qualification means evidence is absent/inapplicable; it does not by
itself prove corrupt hardware.

## 7. Prospective calibration and holdout

Numerical limits are never inferred retroactively from a failed canonical run.
A strategy qualification protocol must freeze before physical calibration:

- subject/applicability identity;
- calibration population/corpus-generation rule;
- independent-case definition;
- comparison checkpoints/domains;
- mandatory metrics;
- statistical risk target and sample-size method;
- threshold-derivation algorithm;
- semantic gates;
- invalid-run/rerun rules;
- sealed holdout commitment and acceptance rule;
- evidence/provenance schema.

Calibration produces numeric limits mechanically from the frozen method. The
limits are serialized, hashed, and frozen before the holdout is opened.

A changed method or limit creates a new contract/evidence version and requires a
new sealed holdout. A holdout failure is retained; it does not authorize
threshold tuning.

Exact corpus size, statistical targets, and thresholds belong to the concrete
qualification methodology, not this doctrine.

## 8. Planner behavior

For each legal candidate, the planner conceptually:

1. obtains the strategy comparator/semantic contract identity;
2. determines the candidate's observed applicability identity;
3. queries the frozen evidence snapshot for applicable qualification;
4. applies operator correctness policy;
5. excludes missing, stale, failed, suspended, or inapplicable candidates;
6. places qualified candidates in the technically feasible set;
7. ranks that set using separate performance/usefulness evidence;
8. retains qualification/evidence IDs and exclusion reasons in the explanation.

Performance cannot outweigh missing correctness qualification.

At realization, the observed backend/stack/device-role/geometry must still match
the selected qualification. Mismatch stops activation; it does not silently
weaken policy.

## 9. Optional bit-exact policy

InferSwarm may expose a hard operator policy conceptually named
`BIT_EXACT_REQUIRED`.

When active:

- only candidates with applicable bit-exact qualification remain feasible;
- numerical-only candidates are explained as operator-policy exclusions;
- no feasible bit-exact candidate produces a truthful no-feasible-plan result;
- the system never silently downgrades to bounded numerical equivalence.

A common GPU model is not itself bit-exact qualification.

The default heterogeneous mode is qualified numerical equivalence, not universal
bit identity.

## 10. Evidence lifecycle

Qualification evidence is immutable history; its current use state can change.

### 10.1 Stale or inapplicable

Correctness-relevant dependency changes make evidence inapplicable or stale
pending requalification, including relevant changes to model/revision,
representation/precision, strategy/comparator, backend/build, software/math
stack, device architecture/class, role mapping, or execution geometry.

The old record remains historically valid for its old context.

### 10.2 Degraded or suspended

A supported concern may mark qualification degraded pending focused
revalidation and exclude it from new correctness-bearing plans.

An attributable frozen-contract violation suspends the narrowest supported
qualification/resource/backend scope. Re-entry requires explicit successful
revalidation; suspension does not silently expire.

### 10.3 Invalid evidence

Only evidence whose provenance, integrity, method, or claimed applicability is
demonstrably defective is marked invalid. Preserve the record and invalidation
reason rather than rewriting history.

### 10.4 Dependency-scoped requalification

Requalify only the affected evidence scope. A backend/library change can stale
numerical qualification without invalidating topology/memory/link evidence; a
model revision can stale strategy correctness evidence without invalidating
generic resource measurements.

Quarantine remains governed by Fabric Doctrine section 5.8 and requires
evidence-supported integrity distrust rather than merely missing qualification.

## 11. Relationship to transport and semantic boundaries

Transport/state-transfer integrity remains exact. A strategy-specific semantic
boundary may carry floating-point values, but sender and receiver must agree on
the exact declared payload bytes. Numerical comparison is performed across
backend computation, never as a substitute for transfer-integrity proof.

Heterogeneous backend numerical behavior therefore does not weaken the doctrine
that semantic cross-resource state and attribution must be preserved exactly.

## 12. Evidence established by R6/#71

Accepted #71 evidence demonstrates only that, for the tested Gemma
BF16/FreeToken/Triton context, device-dependent backend GEMM numerics can appear
from byte-identical inputs and weights while the InferSwarm boundaries and
stage semantics remain exact.

It does not itself qualify the RTX 3090↔RTX 3060 pair under this contract and
does not define any acceptable tolerance. Qualification requires the separately
frozen prospective calibration and holdout process described above.