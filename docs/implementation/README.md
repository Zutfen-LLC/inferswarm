# Implementation plans

These documents turn InferSwarm's research roadmap into ordered engineering and
experiment sequences. They are subordinate to `ROADMAP.md`, `BENCHMARKING.md`,
accepted ADRs, canonical GitHub issues, and any precommitted success criteria.

The distinction between **historical evidence** and **active implementation
plans** is important: completed plans remain in the repository because their
methodology/results are provenance, not because they are still the current
roadmap.

## Completed historical tracks

| Track | Record | State |
|---|---|---|
| Phase 0 — baseline and instrumentation | [phase0-baseline.md](phase0-baseline.md) | **Complete.** Canonical baseline, correctness, routing, and residency evidence exist. |
| Phase 1 — two-GPU local POC | [phase1-two-gpu-poc.md](phase1-two-gpu-poc.md) | **Complete.** Canonical verdict `NO-GO`; methodology/results remain immutable historical evidence. |
| Phase1R — post-NO-GO architecture search | [phase1r-architecture-search-handoff.md](phase1r-architecture-search-handoff.md) | **Complete through D7.** Records graph-compatible local worker experiments, multiworker scaling, loader/route/transport optimizations, and the Gen2 x1 limitation on tested hardware. |

The Phase-1 placement/correctness correction documents remain historical
methodology records and are not superseded by the current N-series.

## Active track — coarse distributed nodes

The active plan is:

- [distributed-node-poc.md](distributed-node-poc.md)

It implements the research direction accepted by
[ADR 0007](../adr/0007-coarse-model-block-partitioning-as-first-network-strategy.md).

Canonical issues:

| Step | Issue | Purpose |
|---|---|---|
| N0 | [#31](https://github.com/Zutfen-LLC/inferswarm/issues/31) | selective model-block loading with bounded host RAM |
| N1 | [#32](https://github.com/Zutfen-LLC/inferswarm/issues/32) | local split-block execution equivalence |
| N2 | [#33](https://github.com/Zutfen-LLC/inferswarm/issues/33) | two-machine block execution over 1 GbE |
| N3 | [#34](https://github.com/Zutfen-LLC/inferswarm/issues/34) | end-to-end two-node serving measurement |

A three-node N4 issue should be created only if N3's measured result justifies
it.

## Deferred tracks

- Mixed GPU + RAM participation remains open under issue #6 and ADR 0005.
- The generalized worker/node capability contract remains deliberately deferred
  under issue #8 until the N-series establishes the real seam.
- GLM-5.3-Flash larger-model investigation remains open/deferred under issue
  #13.
- The local three-GPU Gen3 x8 hardware-causality retest is tracked separately
  under issue #35 and does not block N0.

## Planning rule

Later implementation plans should be written only when prior evidence makes
the concrete sequence knowable. Do not pre-design the generalized scheduler,
wire protocol, or heterogeneous backend API before the corresponding POCs
establish what they actually need.
