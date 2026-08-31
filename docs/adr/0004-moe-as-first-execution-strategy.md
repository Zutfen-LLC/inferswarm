# 0004. MoE as first execution strategy

Date: 2026-08-26
Status: Accepted

> **Current doctrine clarification (2026-08-31):** this remains the accepted
> historical sequencing decision to begin with MoE expert execution. Under ADR
> 0008/Fabric Doctrine, `FabricWorker`, `WorkerCapability`, expert identity, and
> expert placement below are provisional first-strategy vocabulary rather than
> generic planner/resource ontology.

## Context

InferSwarm is a model-independent fabric (principle 9), but a research
project must start somewhere concrete. The candidate first strategies differ
hugely in how gracefully they distribute: dense models couple every token to
every layer sequentially; replicas don't distribute *a* model at all; MoE
models have an internal unit — the expert — that is independently placeable,
selectively executed, and large.

## Decision

MoE distributed expert execution is InferSwarm's first execution strategy:
distributed execution of MoE experts across multiple NVIDIA GPUs, beginning
with RTX 3060-class hardware (ROADMAP Phase 1), with Qwen3.6-35B-A3B as the
POC model.

Why MoE first:

- experts are independently placeable — expert *k* can live on a different
  device than expert *j* without changing model semantics;
- only selected experts execute per token, so remote capacity is touched only
  when the router selects it;
- expert weights are large relative to activation payloads, so resident
  remote execution may be substantially cheaper than repeatedly moving expert
  weights (see below: hypothesis, not fact);
- MoE provides a good first substrate for heterogeneous and elastic resource
  allocation.

**The platform abstraction stays model-independent.** High-level terminology
remains `FabricWorker`, `WorkerCapability`, `ExecutionPlan`,
`ResourceProfile`; MoE-specific executors live underneath the capability
abstraction, and the fabric is never defined as MoE-only. Later strategies
(dense layer/pipeline partitioning, replica placement, memory-tier plans for
oversized models) remain future directions, not commitments.

## Consequences

- The first POCs are deliberately NVIDIA/Qwen-focused even though the
  long-term architecture is vendor- and model-independent. This is a
  sequencing choice, not a permanent commitment.
- Placement research (routing locality, expert residency, cache-hit vs
  coverage distinctions) is MoE-specific work whose *findings* (measure
  placement benefit honestly) transfer to other strategies.
- The capability contract must not leak MoE assumptions into its top level;
  review attention goes there (see the model-independent-worker-capability
  issue).

## Hypotheses distinguished from decisions

- **Decided:** MoE expert execution is the first strategy; NVIDIA/RTX
  3060-class and Qwen3.6-35B-A3B are the first targets; the abstraction stays
  model-independent.
- **Not accepted as fact:** that resident remote expert execution beats
  host-RAM offload in end-to-end inference. That is the central hypothesis
  (README principle 3), to be tested by ROADMAP Phase 1 against the Phase 0
  baseline. The byte-ratio arithmetic supporting it is CALCULATED, not
  MEASURED — see the
  [feasibility investigation](../investigations/multi_gpu_moe_feasibility.md).
- **Not claimed:** any demonstrated performance gain from the POC to date.
