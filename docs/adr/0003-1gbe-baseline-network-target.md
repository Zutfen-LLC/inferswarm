# 0003. 1 GbE baseline network target

Date: 2026-08-26
Status: Accepted

> **Current doctrine/evidence clarification (2026-09-01):** the 1 GbE baseline
> and no-exotic-networking requirement remain accepted. ADR 0008/Fabric
> Doctrine governs legal strategy boundaries and measured granularity
> selection. R4 / issue #57 has now supplied the first accepted physical
> two-Node evidence under this ADR: the tested coarse Qwen boundary earned
> `R4_MULTI_NODE_BOUNDARY_PASS` and the exact canonical 1-GbE arm earned
> `R4_1GBE_PRIMITIVE_CAPACITY_VIABLE`. This is context-specific primitive
> evidence, not a universal claim that every model/workload is 1-GbE viable.

## Context

Distributed inference projects conventionally assume fast interconnects —
InfiniBand, RDMA, GPUDirect, 10/25/100 GbE. Most hardware people already own
does not have those. If the architecture *requires* exotic networking, it
fails the project's purpose of turning the hardware you already own into
inference capacity.

The first MoE feasibility work suggested commodity networking could be useful
because activation payloads can be tiny relative to expert/model state. Later
Phase1R evidence showed that the stronger enduring question is not one fixed
expert-RPC shape but whether a strategy can choose a semantic boundary with
enough useful work/state behind it to justify the measured path cost.

Whether commodity networking would survive real synchronization, execution,
and latency costs therefore remained an evidence question rather than an
assumption.

## Decision

**1 Gigabit Ethernet is the baseline network target** for distributed nodes.

Concretely:

- the architecture must not *require* InfiniBand, RDMA, GPUDirect, or
  10/25/100 GbE;
- faster networking should improve performance and is welcome, but commodity
  1 GbE is the design-and-test baseline;
- network viability is measured for the actual strategy boundary and workload,
  not inferred from nominal link speed alone.

## Consequences

- Strategy/transport design should minimize unnecessary round trips and
  transfer only semantic boundary state/control required by the plan.
- Latency and synchronization remain first-class path costs even when bandwidth
  demand is small.
- Faster networking is evidence that may alter planner economics, not a
  prerequisite embedded in the resource ontology.
- A 1-GbE-negative candidate is evidence against that candidate/context, not a
  license to change the baseline after seeing results.

## Accepted R4 evidence

Issue #57 moved the already-proven contiguous Qwen `[0,19) / [19,40)` split
between two physical Nodes over one persistent ordinary-TCP connection while
keeping local backend-native execution resident on each side.

The retained canonical path was mechanically verified as:

```text
1000 Mb/s
full duplex
MTU 1500
direct LAN
ordinary TCP
```

Corrected accepted capacity methodology compared **actual clean-arm application
wire demand** against the precommitted 80% margin of the lower measured
sustainable TCP direction.

Accepted figures for the frozen R4 context:

- lower measured sustainable TCP throughput: `933.9 Mb/s`;
- 80% applicable margin: `747.12 Mb/s`;
- peak clean-arm A→B application demand: about `2.947 Mb/s`;
- peak clean-arm B→A application demand: about `0.0769 Mb/s`;
- retransmits: `0`.

Therefore the exact tested primitive is accepted as:

`R4_1GBE_PRIMITIVE_CAPACITY_VIABLE`

The transport-only microbenchmark remains service-capability evidence and is
not treated as workload demand.

## Hypotheses distinguished from decisions

- **Decided:** 1 GbE remains the baseline network target and the architecture
  must not require exotic networking.
- **Proven for the accepted R4 context:** the first coarse physical two-Node
  boundary is correct/resident and has ample 1-GbE capacity margin.
- **Not yet proven:** complete ordinary serving-path economics, bounded
  concurrency behavior, or live elasticity/recovery. R5A/R5B address those
  questions.
- **Not claimed:** that 1 GbE is sufficient for every model, strategy boundary,
  concurrency level, topology, or workload. Planner evidence remains contextual
  and must pass applicability checks.
