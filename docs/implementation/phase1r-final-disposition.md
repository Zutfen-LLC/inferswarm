# Phase1R final local-research disposition

Date: 2026-08-30

## Status

Phase1R local resident-expert architecture search is **complete through D7** for
the currently available topology.

The detailed chronological record remains:

- [`phase1r-architecture-search-handoff.md`](phase1r-architecture-search-handoff.md)

This disposition does not modify the immutable canonical Phase-1 `NO-GO`.

## What Phase1R established

- D1: leaving backend-native CUDA-graph execution was the dominant whole-model
  failure mode of the original candidate.
- D2: graph-compatible resident remote execution on a healthy-link RTX 3060
  improved the short W4 serving screen materially.
- D3: two resident workers could execute concurrently and correctly, but adding
  the Gen2 x1 worker imposed a meaningful marginal penalty.
- D4: capability-weighted logical route placement did not materially improve
  throughput.
- D5: fixed-width dummy expert execution was real; compact execution improved
  equal two-worker throughput by about 11.9%.
- D6: count-aware transport cut remote worker-path bytes roughly in half and
  improved equal two-worker throughput by about 3.3%; fan-in on the slow x1
  worker remained the principal residual.
- D7: whole-layer/fan-in-sparse placement removed simultaneous A+B
  participation entirely and reduced mean active remote workers per layer by
  about half, yet throughput declined slightly. The slow x1 worker remained
  expensive even when it was the only active remote worker for a layer.

## Current hardware-specific conclusion

For the measured `inferswarm01` configuration:

- the Gen3 x16 RTX 3060 is a useful performance worker;
- the Gen2 x1 RTX 3060 is **capacity-positive but throughput-negative** on the
  tested execution path;
- this is a conclusion about the measured worker/link/runtime combination, not
  a universal claim that all x1 devices or all narrow links are unusable.

Do not continue reshaping placement solely to make the current Gen2 x1 worker
throughput-positive.

## Deferred local hardware causality test

Issue #35 tracks a future retest after moving the third RTX 3060 to the Z440's
PCIe Gen3 x8 electrical slot through a suitable riser/extension.

That test will ask whether multiworker scaling improves when both workers have
materially healthy PCIe links. It does not block the current network research.

## Research pivot

The highest-value available architecture question is now coarse multi-node
model-block execution over ordinary Ethernet.

[ADR 0007](../adr/0007-coarse-model-block-partitioning-as-first-network-strategy.md)
records that decision. The active sequence is:

- #31 — selective model-block loading;
- #32 — local split-block equivalence;
- #33 — two-machine block execution over 1 GbE;
- #34 — end-to-end two-node serving.

The first network strategy is not fine-grained expert RPC on every MoE layer.
Each node should own a contiguous model block, keep block-local state resident,
and exchange hidden-state boundary payloads between persistent node-local fast
execution plans.

## Preservation rule

D2-D7 FreeToken/InferSwarm `poc/*` heads are evidence-bearing research history.
Their exact SHAs and accepted results remain documented; they need not be
merged wholesale into a production/integration branch. Branches may be archived
or deleted only after reproducibility references are preserved per
[`../integrations/freetoken.md`](../integrations/freetoken.md).
