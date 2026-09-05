# 0010. Heterogeneous numerical-equivalence correctness contract

Date: 2026-09-03
Status: Accepted

## Context

InferSwarm is intended to execute one inference workload across heterogeneous
Compute Units. R6 and its issue #71 localization established an important
correctness distinction: byte-identical model state, inputs, semantic
configuration, and transport can still produce small floating-point differences
when the same legal backend computation runs on different devices.

The accepted #71 evidence localized the first single-vs-distributed Gemma BF16
difference to a backend GEMM with byte-identical inputs and weights. The same
distributed stage code reproduced the single-GPU result on the RTX 3090 and the
distributed stage result on the RTX 3060. Both InferSwarm execution boundaries
preserved exact bytes. The evidence therefore classified the difference as
`BACKEND_EXECUTION_LOCAL`, not transport corruption, model-strategy state
mismatch, Coordinator error, or a generic planner defect.

Requiring universal bitwise identity across all GPU, CPU, NPU, and future
backend implementations would collapse an important part of the heterogeneous
fabric goal. Conversely, treating every floating-point difference as acceptable
would let a tolerance hide wrong state, wrong transport, stale authority, or a
semantic output change.

A durable correctness contract is therefore required before a heterogeneous
candidate can be admitted to the feasible plan set.

Historical R6 remains `R6_DENSE_ARCHITECTURE_FALSIFICATION_FAIL`. This ADR does
not reinterpret, relax, or replace that historical gate.

## Decision

### 1. Correctness has three conjunctive layers

A correctness-bearing candidate must satisfy all applicable layers:

1. **Exact integrity invariants.** Discrete identities and control facts remain
   exact: model/checkpoint and representation identity, Execution Plan identity,
   Logical State Unit coverage, Materialization ownership, sender/receiver
   boundary bytes and hashes, session/epoch/generation/realization/position
   attribution, fencing/authority, and absence of silent fallback or
   substitution.
2. **Qualified numerical execution equivalence.** Floating-point tensors
   produced by a backend may differ within a prospectively frozen,
   strategy-declared numerical-equivalence contract only after the exact layer
   has established identical authorized inputs/state/configuration and an
   applicable qualified execution path.
3. **Strategy-declared semantic output correctness.** Discrete model/workload
   decisions are evaluated separately from tensor closeness. For deterministic
   greedy generation, committed token IDs remain exact when the strategy's
   semantic profile requires them.

A pass in one layer cannot waive a failure in another. No aggregate score or
single epsilon replaces the conjunction.

### 2. The Model Execution Strategy owns numerical and semantic correctness

The Model Execution Strategy owns:

- legal comparison checkpoints/domains;
- numerical metrics and mandatory gates;
- semantic output profile;
- reference relationships;
- applicability dimensions that materially affect correctness.

A backend adapter may implement capture/metric mechanics and report the
observed execution path. A qualification evaluator applies the frozen contract
to frozen evidence.

The generic planner does **not** evaluate tensors or contain model-, GPU-,
CUDA-, or backend-specific tolerances. It consumes an applicable qualification
result, evidence identity/state, and reasons.

### 3. Numerical qualification is correctness-bearing feasibility evidence

Backend/representation support is a compatibility capability. Numerical
qualification is evidence that one compatible candidate implementation satisfies
a strategy correctness contract in a declared context.

A candidate without applicable qualification does not enter the
correctness-bearing feasible plan set merely because its hardware/backend can
execute the operations.

Qualification is context-scoped. Its applicability may depend on model and
representation identity, strategy/comparator version, backend/build and
software stack, precision, device architecture/class and ordered role mapping,
and execution geometry when those dependencies can materially change numerical
behavior.

The first qualification should match exact observable software versions.
Broader compatibility ranges require explicit evidence rather than semantic
version assumptions.

### 4. Exact transfer/state invariants never become tolerant

A numerical-equivalence envelope cannot excuse:

- wrong model or representation;
- wrong/missing/duplicated Logical State Units;
- wrong or stale authority;
- wrong plan/session/epoch/generation/realization/position;
- sender/receiver boundary-byte mismatch;
- checksum/hash failure;
- wrong shape or frozen semantic dtype;
- silent fallback or execution-path substitution.

These fail before numerical comparison.

### 5. Numerical contracts are prospective and strategy/context specific

There is no universal InferSwarm epsilon. A contract must predeclare its metrics,
comparison domains, threshold-derivation method, semantic gates, evidence
applicability, and calibration/holdout protocol before candidate acceptance
results are observed.

Calibration produces frozen numerical limits. A sealed holdout then tests those
limits without post-result tuning. A changed method or limit creates a new
contract/evidence version; it does not repair an earlier failed gate.

### 6. Bit exactness is an optional hard operator policy

InferSwarm may expose a strict policy such as `BIT_EXACT_REQUIRED`.

When requested, the planner excludes every candidate lacking applicable
bit-exact qualification. It must not silently weaken the request to ordinary
numerical equivalence. Matching GPU model names alone is not proof of bit
identity; the relevant backend, software stack, role, and geometry must also be
covered by evidence.

Bit exactness is not the universal definition of correctness for the
heterogeneous fabric.

### 7. Qualification evidence ages and fails closed

Qualification records are immutable historical evidence, while their current
applicability/use state can change.

Material changes to correctness-relevant dependencies make evidence stale or
inapplicable pending requalification. A supported concern can degrade/suspend a
qualification, and an attributable frozen-contract violation suspends the
narrowest supported scope until explicit successful revalidation.

Missing qualification is uncertainty/inapplicability, not automatic hardware
corruption. Quarantine remains reserved for evidence-supported integrity
failure under the Fabric Doctrine.

### 8. Planner feasibility and performance remain separate

Correctness qualification is evaluated before performance ranking. A slow
qualified candidate may be feasible; a fast unqualified candidate is not.

Performance evidence cannot outweigh a missing or failed correctness
qualification.

## Consequences

- InferSwarm can remain genuinely heterogeneous without pretending floating
  point is bit-reproducible across all devices/backends.
- Exact state, authority, attribution, and transport integrity remain stronger
  invariants than numerical tensor equivalence.
- Strategies can express different sensitivity profiles: dense transformers,
  sparse/MoE routing, quantized representations, recurrent/state-space models,
  and future architectures need not share one comparator.
- The generic planner gains only a qualification/applicability concept; model
  and backend mathematics stay outside generic planning.
- Changing backend/library/device/geometry context can require correctness
  requalification even when the hardware remains nominally compatible.
- Qualification requires prospective calibration and unseen holdout evidence,
  increasing experiment cost but preventing post-hoc threshold tuning.
- Operators may request bit-exact execution at the cost of shrinking the
  feasible resource set.
- Historical R6 remains a valid failed experiment. Future qualification cannot
  be back-fitted onto its frozen comparator.

The detailed normative rules are specified by
[`docs/architecture/numerical-equivalence-contract.md`](../architecture/numerical-equivalence-contract.md),
which is adopted as a Fabric Doctrine supplement by this ADR and should be
consolidated into the main doctrine when that document is next structurally
revised.

### Forward clarification — issue #93

The adopted supplement now distinguishes prospectively declared
acceptance-bearing numerical gates from mandatory telemetry. This clarifies the
numerical layer without changing this ADR's three conjunctive layers: the
qualification core remains conjunctive, while retained telemetry remains
evidence-health material unless a future comparator declares it core. The
historical contracts and verdicts, including issue #88 `V3_HOLDOUT_FAIL`, remain
governed by their frozen all-envelope conjunction.

## Hypotheses distinguished from decisions

This ADR does **not** decide:

- a universal numerical tolerance;
- that the historical R6 `0.46875`/`0.5` differences are acceptable;
- that RTX 3060 and RTX 3090 are already qualified under the new contract;
- that a specific cuBLAS algorithm/tile-selection mechanism caused #71;
- that all cards of one GPU model are numerically interchangeable;
- that calibration results for one model/representation transfer automatically
  to another;
- that deterministic greedy-token identity is sufficient for every strategy;
- a final public planner, strategy, evidence, or plugin API.

Those claims require prospective evidence under issue #72 and successor
qualification work.