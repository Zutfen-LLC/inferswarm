# InferSwarm Roadmap

This roadmap tracks **validation questions**, not feature shipping. Results follow
[BENCHMARKING.md](BENCHMARKING.md): if an experiment fails, the plan changes
rather than the thresholds or the numbers.

## Completed foundation

### Phase 0 — baseline and routing evidence — COMPLETE

The Qwen3.6/RTX 3060 baseline, correctness reference, and W1-W4 MoE routing /
cache-pressure evidence are complete. Canonical issues #1-#3 are closed.

Primary records include:

- [`docs/benchmarks/results/phase0/`](docs/benchmarks/results/phase0/)
- [`docs/investigations/p0i-qwen36-routing-residency.md`](docs/investigations/p0i-qwen36-routing-residency.md)

### Phase 1 — two-GPU local POC — COMPLETE / canonical `NO-GO`

The original Phase-1 candidate proved resident remote expert execution correct
but was dramatically slower than the canonical baseline. The immutable verdict
is:

`NO-GO`

This verdict applies only to the exact tested Phase-1 mechanism and hardware;
it is not a blanket rejection of distributed inference.

Canonical report:

- [`docs/benchmarks/results/phase1/phase1-go-no-go-report.md`](docs/benchmarks/results/phase1/phase1-go-no-go-report.md)

Issues #4, #5, and #10 are closed as completed.

### Phase1R — local architecture search D1-D7 — COMPLETE

Phase1R investigated why Phase 1 failed and whether a graph-compatible local
resident-worker architecture could still be useful.

The accumulated result is maintained in:

- [`docs/implementation/phase1r-architecture-search-handoff.md`](docs/implementation/phase1r-architecture-search-handoff.md)

Key findings:

- backend-native captured execution is critical on the current NVIDIA stack;
- a healthy-link resident RTX 3060 can improve decode throughput materially;
- graph-compatible multiworker execution is correct and physically concurrent;
- dummy expert work and fixed transport were real, measurable scaling taxes and
  were reduced by D5/D6;
- capability weighting and fan-in-sparse placement did not repair scaling on
  the available Gen2 x1 worker;
- the tested Gen2 x1 RTX 3060 is best treated provisionally as a
  capacity-positive / throughput-negative resource, not as evidence that all
  narrow-link devices are universally unsuitable.

Historical three-GPU issue #7 is closed for the tested topology. A future
Gen3 x8 hardware-causality retest is tracked in #35 and does not block the
current roadmap.

## Current active track — N-series coarse multi-node execution

[ADR 0007](docs/adr/0007-coarse-model-block-partitioning-as-first-network-strategy.md)
sets the current network direction.

The first multi-machine strategy is **coarse contiguous model-block
partitioning over ordinary 1 Gigabit Ethernet**, not fine-grained expert RPC on
every MoE layer.

Why:

- the project goal is to use hardware and networking people already have;
- local experiments showed fine-grained worker participation is highly
  sensitive to service latency/interconnect quality;
- a coarse node boundary lets each machine retain backend-native fast execution
  locally and pay network transitions only between large blocks;
- selective loading also solves the independent problem that a node should not
  require enough host RAM for model state it does not own.

### N0 — selective model-block loading — ACTIVE — issue #31

Prove that a process/node can load only its assigned contiguous model block,
with bounded host RAM and no mandatory full CPU expert-bank materialization.

**Exit criteria:** complementary blocks load/execute correctly; peak RAM and
materialized bytes are accounted; unrelated model state is never loaded.

### N1 — local split-block equivalence — BLOCKED BY N0 — issue #32

On one machine, execute two complementary model blocks across an explicit
process/execution boundary before networking is introduced.

**Exit criteria:** complete deterministic inference matches the unsplit
reference; block-local KV/recurrent state ownership and boundary payload are
explicit; backend-native fast execution remains active within each block.

### N2 — two-machine block primitive over 1 GbE — BLOCKED BY N1 — issue #33

Move one block to a second physical machine using a persistent compact binary
boundary over ordinary 1 GbE.

**Exit criteria:** exact two-machine correctness; decode/prefill boundary bytes
and network wall measured; no node needs full-model host RAM; 1 GbE gets an
honest primitive-level viability verdict. If available, 10 GbE is an optional
comparison only.

### N3 — end-to-end two-node serving — BLOCKED BY N2 — issue #34

Run the frozen W1-W4-style end-to-end serving comparison across two nodes.

**Exit criteria:** correctness, decode tok/s, TTFT, prefill, and network overhead
measured with provenance; the 1 GbE verdict determines whether a three-node N4
experiment is justified.

### N4 — three-node scaling — NOT YET CREATED

Create only if N3 earns it. Do not pre-design three-node scheduling before the
two-node execution boundary is measured.

## Deferred but still valid work

### Mixed accelerator + RAM execution — issue #6

ADR 0005 remains accepted: system RAM is a first-class tier. The original
GPU+GPU+RAM expert-placement issue remains open but deferred until the N-series
clarifies the broader node/block boundary.

### Model-independent capability contract — issue #8

Do not freeze the public worker/node contract before N0-N3 reveal the actual
fields needed for selective loading, block execution, network boundaries, and
measured hardware profiles.

### Larger-model validation — issue #13

GLM-5.3-Flash remains a potentially valuable capacity-constrained target, now
explicitly deferred until the node-partition substrate exists. Future analysis
must consider both coarse node partitioning and optional local expert residency.

### Heterogeneous vendors

AMD ROCm, Intel XPU/Arc, and CPU contributions remain long-term goals. They
should be introduced after the execution boundary is stable enough that vendor
bring-up does not get conflated with distributed-architecture debugging.

### Local link-class follow-up — issue #35

When a suitable x8→x16 riser arrives, retest the third RTX 3060 on the Z440's
Gen3 x8 slot. This is useful hardware-causality evidence but does not block N0.

## Superseded network plan

Issue #9 proposed making the first 1 GbE POC a fine-grained remote MoE expert
worker. It is closed `not planned` and preserved as historical reasoning.
ADR 0003 — **1 GbE as the baseline network target** — remains accepted. ADR
0007 changes the first network execution granularity, not the commodity-network
requirement.

## Later / exploratory

No schedule or commitment yet:

- node-local composition of local GPUs + RAM beneath a coarse distributed node;
- automatic hardware capability profiling and performance/capacity worker
  classification;
- elastic/borrowed accelerator capacity;
- NVMe backing tier;
- multi-site execution;
- replicas and other model-independent strategies;
- commercial control-plane integration.

## Issue tracking

InferSwarm issues are canonical for architecture, roadmap, and acceptance
criteria. FreeToken carries focused implementation experiments and links back
to the corresponding InferSwarm issue. Accepted experimental heads/evidence are
recorded before research branches are archived; see
[`docs/integrations/freetoken.md`](docs/integrations/freetoken.md).
