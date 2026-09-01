# 0007. Coarse model-block partitioning as first network strategy

Date: 2026-08-30
Status: Accepted

> **Current doctrine/evidence clarification (2026-09-01):** this remains the
> accepted **first** network strategy/evidence direction, not permanent
> `inter-node = contiguous block` doctrine. ADR 0008/Fabric Doctrine governs
> legal strategy boundaries and measured granularity selection. The retired
> N1-N3 sequence is historical planning scaffolding. R4 / issue #57 has now
> completed the first physical two-Node proof for the coarse-block direction,
> earning `R4_MULTI_NODE_BOUNDARY_PASS` and
> `R4_1GBE_PRIMITIVE_CAPACITY_VIABLE` for the exact frozen candidate/context.

## Context

ADR 0003 established ordinary 1 Gigabit Ethernet as InferSwarm's baseline
network target. The original roadmap assumed that the first multi-machine POC
would extend the first local execution strategy directly: a remote machine
would behave like another MoE expert worker, receiving routed work and returning
expert contributions on individual MoE layers.

Phase 1 and the post-Phase-1 D1-D7 architecture search changed the evidence
base substantially.

- Canonical Phase 1 proved resident remote expert execution correct but rejected
  the tested host-orchestrated candidate on end-to-end performance.
- D1 showed that losing backend-native captured execution was catastrophic on
  the current FreeToken/CUDA stack.
- D2-D7 proved a graph-compatible local resident worker can be useful and then
  isolated the costs of multiworker participation, PCIe topology, dummy expert
  work, transport volume, placement, and fan-in.
- On the tested hardware, a healthy Gen3 x16 RTX 3060 was strongly useful while
  the Gen2 x1 worker remained throughput-negative even after route compaction,
  count-aware transport, and elimination of simultaneous A+B layer
  participation.

Those results did not prove Ethernet expert RPC impossible. They showed that
fine-grained per-layer remote participation is highly sensitive to service
latency and execution-boundary overhead, making it a poor first ordinary-1-GbE
experiment.

A coarser model partition offers a different payload/work ratio: a Node can
keep a contiguous block of model state and block-local mutable/runtime state
resident, execute that block through a backend-native fast path, and exchange
comparatively small semantic state only at block boundaries.

## Decision

InferSwarm's **first multi-machine execution strategy/evidence direction is
coarse contiguous model-block partitioning**, tested first over ordinary
1 Gigabit Ethernet.

Concretely:

1. **A distributed participant may own a contiguous block of model execution.**
   It loads only the weights/state required by that block plus declared bounded
   runtime/staging overhead.
2. **Block-local mutable/recurrent/KV state stays with the block that owns it**
   unless a future strategy declares a different semantic boundary.
3. **The cross-node hot path carries strategy-semantic block-boundary state,**
   not model weights/state that should remain resident.
4. **Backend-native fast execution remains local to each Node.** A global graph
   spanning machines is not required.
5. **Networking occurs at coarse semantic boundaries rather than automatically
   inside every model layer.** Persistent connections and compact transfer are
   appropriate when measurements support them.
6. **1 GbE remains the baseline.** Faster networking is a comparison/optimizer,
   not a minimum requirement baked into the architecture.
7. **Fine-grained remote expert execution remains a legal research strategy,**
   not the mandatory network shape.
8. **A Node may contain its own local resource plan.** Coarse inter-node
   partitioning does not imply one-GPU-per-Node architecture.
9. **The generic execution boundary is strategy-specific semantic work/state.**
   The planner/resource ontology must not collapse expert dispatch and block
   execution into one model-specific universal wire schema.

This decision chooses the **first experiment**, not the permanent granularity.

## Consequences

- Selective loading is a distributed-architecture prerequisite: a Node must not
  require full-model host RAM for state it does not own.
- Model/block boundaries, state ownership, and backend-native participant
  execution become measurable strategy objects.
- Protocol work must remain subordinate to semantic strategy boundaries; a
  stable public network protocol stays deferred.
- Larger-model validation may use other legal partitions when evidence supports
  them.
- Local sparse/expert residency remains independently useful and may coexist
  inside a coarse inter-node plan.
- Hardware/path capability is measured rather than reduced to one universal
  score or static locality tier.

## Accepted evidence progression

The original #31-#34 N-series planning sequence was superseded after N0 and the
Wayfinder. The accepted evidence path ultimately became:

- N0 / #31 — `N0_SELECTIVE_BLOCK_PASS`;
- R0 / #48 — `P48_ACCELERATOR_RESIDENCY_PASS`;
- R1 / #50 — `R1_FROZEN_PLAN_REALIZATION_PASS`;
- R2 / #51 — `R2_LOCAL_SPLIT_EXECUTION_PASS`;
- #53 — `HOST_STAGING_RECLAMATION_PASS`;
- R3 / #55 — `R3_MINIMUM_AUTOMATIC_PLANNING_PASS`;
- R4 / #57 — `R4_MULTI_NODE_BOUNDARY_PASS`.

R4 reused the already-proven `[0,19) / [19,40)` Qwen split and changed the
principal variable from local to physical Node/network locality. The two blocks
executed on `inferswarm01` and `inferswarm03` over persistent ordinary TCP with
byte-exact correctness, backend-native resident execution, complete
application-wire accounting, and zero steady-state model-state movement.

For the exact canonical 1-GbE arm, corrected accepted evidence found peak
clean-arm application demand of about `2.947 Mb/s` A→B against a precommitted
`747.12 Mb/s` 80%-margin limit on the measured path, with zero retransmits.
That exact primitive therefore earned:

`R4_1GBE_PRIMITIVE_CAPACITY_VIABLE`

## Hypotheses distinguished from decisions

- **Decided:** coarse contiguous model-block partitioning was the first
  multi-machine strategy/evidence direction; 1 GbE remains the baseline; Nodes
  should load only assigned state and retain block-local state where the
  strategy requires it.
- **Proven:** the accepted R4 two-Node implementation is correct, resident,
  backend-native, and honestly accounted for the frozen Qwen split.
- **Proven for the exact R4 context:** ordinary 1-GbE capacity is comfortably
  sufficient for the measured semantic boundary demand.
- **Not decided:** that future network plans must use contiguous blocks. The
  strategy/planner may choose another legal granularity from measured economics.
- **Not yet proven:** integrated ordinary serving-path economics/concurrency or
  live execution-plan elasticity/recovery. R5A and R5B are the successor gates.
- **Not claimed:** that 10 GbE or faster links are unnecessary in every
  workload/model/topology.
