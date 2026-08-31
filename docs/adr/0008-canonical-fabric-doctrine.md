# 0008. Canonical Fabric Doctrine

Date: 2026-08-31
Status: Accepted

## Context

InferSwarm's Phase 0, Phase 1, Phase1R, and N0 research established useful
mechanisms and measurements, but the repository's earlier architecture language
was still shaped by the first Qwen/NVIDIA/FreeToken experiments. Terms such as
`primary`, L0/L1/L2/L3 tiers, `FabricWorker`, expert-centric capability trees,
and a fixed local-fine/remote-coarse hierarchy were useful scaffolding, not a
sufficient model-independent ontology.

N0 also exposed a stronger residency requirement that the old roadmap did not
state cleanly: a final accelerator-resident materialization must not inherently
force an equivalent persistent host-RAM mirror merely because the loader or
backend happened to create one.

The resource/residency/planner Wayfinder (#37), resolved through decisions
#38-#46, therefore re-derived the architecture from first principles before
continuing implementation.

## Decision

InferSwarm adopts the normative
[Fabric Doctrine](../architecture/fabric-doctrine.md) as the detailed canonical
resource, residency, planning, evidence, strategy, reconfiguration, adaptive-
demand, and distribution-granularity specification.

Repository precedence is:

> **ADRs decide; the Fabric Doctrine specifies; `ARCHITECTURE.md` explains;
> `ROADMAP.md` sequences.**

The doctrine is **doctrine-shaped, API-unfrozen**: its concepts and invariants
are canonical, but it intentionally does not freeze final public type names,
planner algorithms, plugin APIs, wire formats, persistence schemas, or migration
mechanisms before implementation evidence warrants them.

The following architectural commitments are adopted:

1. **Resource graph.** A `Swarm` is the durable planning/management domain; a
   `Coordinator` is a replaceable control-plane role; a `Node` is one physical
   host/resource domain; `Compute Unit`, `Memory Resource`, and discovered
   `Link`/topology relationships are distinct concepts. Physical hardware has
   no intrinsic `primary`, worker, performance/capacity, or L0/L1/L2/L3 plan
   role.
2. **State and residency.** Logical state identity is distinct from physical
   materialization. Backing/source, residency, staging, cache, replica,
   execution location, and mutable authority are separate semantics.
   Accelerator residency never inherently requires an equivalent persistent
   host-RAM materialization; deliberate persistent host copies remain legal
   when they have an explicit plan/runtime role and are accounted.
3. **Planning objective.** Correctness and feasibility precede optimization.
   Among feasible plans, the planner selects the one expected to deliver the
   greatest useful inference service under current evidence, workload, and
   operator policy. Slow-but-viable remains technically feasible unless an
   explicit service requirement makes it policy-infeasible.
4. **Measured evidence and trust.** Nominal capability, discovered
   configuration, measured/runtime behavior, accepted historical baselines,
   planner estimates, availability, integrity trust, and evidence
   confidence/freshness remain distinct. Performance degradation changes
   economics; integrity failures quarantine the narrowest evidence-supported
   correctness-bearing scope until explicit successful revalidation.
5. **Model Execution Strategy boundary.** Model/revision semantics are
   translated into an abstract constrained planning problem. Strategies expose
   opaque state/execution units, legal boundaries/groupings, state and demand
   semantics, representations/backend/correctness constraints, legal
   implementation alternatives, and strategy-specific economics. **Strategy
   constrains; planner chooses.** The generic planner does not require
   model/backend nouns such as expert, router, KV cache, Qwen, CUDA Graph, or
   NVFP4.
6. **Execution-plan epochs and elasticity.** Execution plans are immutable,
   versioned snapshots. Epochs isolate correctness while allowing better
   resources to be prepared and folded into active sessions at safe strategy
   boundaries and allowing resource loss to trigger degraded-but-valid
   replanning over surviving trusted resources. Unrecoverable loss of required
   authoritative mutable state is the hard stop.
7. **Adaptive Demand Profiles.** Structural demand over strategy-defined opaque
   units may be learned from model-wide/general, applicable profile/workload,
   Swarm-local, and current-session evidence. Explicit Workload Intent is only
   optional prior evidence. Demand learning need not persist prompt/response
   content and may influence later plan epochs when expected benefit justifies
   transition cost.
8. **Distribution granularity.** Granularity is a plan/epoch decision. Strategies
   define legal cuts/groupings; the planner chooses globally using measured
   communication, locality, execution, state/capacity, contention, demand,
   workload, and transition economics. Coarse is not intrinsically better, and
   intra-node and inter-node granularities may differ.
9. **Automatic planning and explanation.** Normal planning is automatic.
   Operators provide generic resource/policy constraints rather than manually
   mapping model-specific components. Plan participation, exclusions,
   bottlenecks, health/trust decisions, and expected poor performance must be
   explainable on demand.

## Relationship to earlier ADRs

- ADR 0001 remains Accepted. Its `worker`/agent wording describes a possible
  runtime implementation role, not a physical resource class.
- ADR 0002 remains Accepted. FreeToken remains the initial proving/integration
  vehicle; old roadmap phase-number references are historical rather than
  current sequencing.
- ADR 0003 remains Accepted. Ordinary 1 GbE remains the baseline network target;
  its MoE-specific batching examples are historical/strategy-specific, while
  this doctrine governs granularity selection.
- ADR 0004 remains Accepted as the historical decision to begin with MoE expert
  execution. Its provisional `FabricWorker` vocabulary is not the canonical
  domain model.
- **ADR 0005 is superseded by this ADR in scope.** Its durable requirement
  survives: system RAM and CPU execution remain first-class resources and may
  participate whenever a plan finds them useful. The intrinsic tier,
  `primary`/`secondary`, expert-placement, and universal-worker framing does
  not survive.
- **ADR 0006 is superseded by this ADR in scope.** Its durable principles
  survive: backend-native fast paths, backend-native representations,
  strategy-specific semantic boundaries, transport orthogonality, bounded
  heterogeneous correctness contracts, and fast-path rebuilding at epochs.
  The universal physical Worker abstraction does not survive.
- ADR 0007 remains Accepted as the first coarse-block-over-Ethernet network
  strategy/evidence direction. It is not a permanent rule that inter-node
  execution must use contiguous blocks.

## Historical evidence

This ADR does not rewrite completed experiments.

- Phase 1's `NO-GO` remains the verdict for the exact tested candidate, not a
  rejection of distributed inference generally.
- Phase1R remains hardware/topology/runtime-specific measured evidence.
- `N0_SELECTIVE_BLOCK_PASS` remains valid for selective checkpoint loading,
  block-only ownership, bounded block-scoped loading, and exact isolated-block
  correctness.
- N0 did **not** prove release of all equivalent persistent CPU backing after
  final accelerator residency; the retained `expert_bank_final_host_bytes`
  exposed that successor requirement.
- The aborted N1 partial run is non-canonical evidence, and retired N1-N3 issues
  are historical scaffolding rather than an active roadmap sequence.

## Implementation handoff

Implementation resumes from the first currently unproven doctrine invariant,
not from the next retired N-series ticket:

1. prove accelerator residency without implicit persistent host mirrors;
2. prove doctrine-shaped frozen-plan realization without freezing public APIs;
3. relaunch local heterogeneous/split execution with correctness and matched
   A/B evidence;
4. introduce minimum automatic planning so strategy constrains and planner
   chooses;
5. resume measured multi-node boundary research, with ADR 0007 as the leading
   first candidate but this doctrine governing granularity;
6. validate end-to-end multi-node serving plus elastic admission/recovery;
7. use a materially different model architecture to falsify/refine the
   abstraction before declaring public planner/strategy APIs stable, with
   GLM-5.3-Flash later serving as a large heterogeneous-capacity validation
   target where appropriate.

## Consequences

- `ARCHITECTURE.md` and `ROADMAP.md` are derived documents and must not become
  independent sources of architectural truth.
- Current documentation must retire obsolete intrinsic tier/primary/worker
  claims while preserving historical documents in their original experimental
  context.
- New implementation may use temporary/internal research structures. Conceptual
  stability does not require premature public API stability.
- Future architecture changes that materially alter this doctrine require a
  new ADR and synchronized doctrine update rather than silent drift in roadmap
  or implementation prose.

## Hypotheses distinguished from decisions

- **Decided:** the concepts/invariants above, documentation precedence, ADR
  dispositions, historical-evidence treatment, and evidence-gated successor
  implementation order.
- **Not decided:** exact planner/search algorithm, cost function, final public
  classes/interfaces, plugin mechanism, capability schema, wire protocol,
  Adaptive Demand Profile statistical/storage/privacy implementation, migration
  protocol, transparent failover machinery, cache/promotion policy, or final
  vendor backend APIs.
- **Not proven:** that every model family or commodity network can yield a
  performance-positive distributed plan. Slow-but-correct feasibility and
  performance benefit remain separate questions measured per the benchmark
  contract.
