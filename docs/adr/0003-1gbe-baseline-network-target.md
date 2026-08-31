# 0003. 1 GbE baseline network target

Date: 2026-08-26
Status: Accepted

> **Current doctrine clarification (2026-08-31):** the 1 GbE baseline and
> no-exotic-networking requirement remain accepted. The MoE-specific batching
> and dispatch examples below are historical strategy context, not permanent
> protocol/granularity doctrine. ADR 0008/Fabric Doctrine governs legal
> strategy boundaries and measured granularity selection.

## Context

Distributed inference projects conventionally assume fast interconnects —
InfiniBand, RDMA, GPUDirect, 10/25/100 GbE. Most hardware people already own
does not have those. If the architecture *requires* exotic networking, it
fails the project's purpose of turning the hardware you already own into
inference capacity (README, principle 2).

MoE expert dispatch gives a reason to believe commodity networking could
suffice: activation payloads are tiny relative to expert weights (on the
order of a few to tens of kilobytes for the models studied, versus megabytes
of expert weights per expert touch, per the
[feasibility investigation](../investigations/multi_gpu_moe_feasibility.md)),
so a dispatch/execute/combine flow moves orders of magnitude fewer bytes than
a weights-migration flow. Whether that reason survives contact with real
synchronization costs is unknown.

## Decision

**1 Gigabit Ethernet is the baseline network target** for distributed nodes.

Concretely:

- the architecture must not *require* InfiniBand, RDMA, GPUDirect, or
  10/25/100 GbE;
- faster networking should improve performance and is welcome, but commodity
  1 GbE is the design-and-test baseline;
- ROADMAP Phase 4 (two-machine execution over 1 GbE) is the validation gate.

## Consequences

- Protocol design is biased toward few, batched round trips rather than bulk
  transfer ([docs/protocols/](../protocols/README.md)): one activation
  payload per worker/layer, multiple experts executed per dispatch, small
  combined returns.
- "It only works on fast networks" is a project failure condition, not an
  acceptable outcome; Phase 4's honest measurement decides the question.
- Latency-sensitive design (persistent connections, minimal per-dispatch
  overhead) matters as much as bandwidth, since at these payload sizes the
  risk is synchronization-dominated, not bandwidth-dominated.

## Hypotheses distinguished from decisions

- **Decided:** 1 GbE is the baseline network target and the
  no-exotic-networking requirement.
- **Not accepted as fact:** that 1 GbE is fast enough. Whether 1 GbE is
  viable — and whether its limiting factor is latency/synchronization rather
  than bandwidth once activation payloads are small — **remains to be
  experimentally determined** (ROADMAP Phase 4). No performance over any
  network has been demonstrated by this project at the time of this ADR.
