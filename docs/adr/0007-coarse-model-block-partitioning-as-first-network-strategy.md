# 0007. Coarse model-block partitioning as first network strategy

Date: 2026-08-30
Status: Accepted

> **Current doctrine clarification (2026-08-31):** this remains the accepted
> first network strategy/evidence direction. ADR 0008/Fabric Doctrine does not
> canonize `inter-node = contiguous block`: strategies define legal boundaries
> and the planner selects intra/inter-node granularity from measured economics.
> The retired N1-N3 sequence below is historical planning scaffolding, not the
> current roadmap.

> **Accepted evidence update (2026-09-01):** R4 / issue #57 completed the first
> physical two-Node proof for this direction. The frozen `[0,19) / [19,40)` Qwen
> split earned `R4_MULTI_NODE_BOUNDARY_PASS` over persistent ordinary TCP, and
> the exact canonical 1-GbE arm earned
> `R4_1GBE_PRIMITIVE_CAPACITY_VIABLE`. Corrected accepted evidence measured
> about `2.947 Mb/s` peak clean-arm A→B application demand against a
> precommitted `747.12 Mb/s` 80%-margin limit on the measured path, with zero
> retransmits. This validates the first candidate/context; it does not convert
> contiguous blocks into permanent inter-node doctrine. R5A/R5B now own
> integrated serving and elasticity questions.

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

Those results do not prove that Ethernet expert RPC is impossible. They do show
that fine-grained per-layer remote participation is highly sensitive to
service latency and execution-boundary overhead. Extending that shape over the
ordinary 1 GbE baseline is therefore no longer the strongest first network
experiment.

At the same time, the product goal remains "use the hardware you already have."
Requiring 10/25/40/100 GbE simply to make multi-machine participation viable
would weaken that goal materially.

A coarser model partition provides a different payload/work ratio: a node can
keep a contiguous block of layers and its block-local state resident, execute
that block through its backend-native fast path, and exchange comparatively
small hidden-state payloads only at block boundaries.

## Decision

InferSwarm's **first multi-machine execution strategy is coarse contiguous
model-block partitioning**, tested first over ordinary 1 Gigabit Ethernet.

Concretely:

1. **A distributed node owns a contiguous block of model execution.** It loads
   only the weights/state required by that block plus bounded runtime/staging
   overhead.

2. **Block-local KV/recurrent state stays with the block that uses it.** It is
   not shuttled across the network every layer/token unless a future model
   semantics requires a specifically documented boundary state.

3. **The cross-node hot-path payload is semantic block-boundary state.** For
   the first POC this is expected to be the hidden activation plus the minimum
   explicit request/sequence metadata required by the downstream block.

4. **Backend-native fast execution remains local to each node.** On the first
   NVIDIA/FreeToken implementation this may mean a CUDA Graph or another
   captured/compiled local block. InferSwarm does not require one global graph
   spanning machines.

5. **Networking occurs between coarse blocks, not inside every model layer.**
   Persistent connections and compact binary framing remain design goals.

6. **1 GbE remains the baseline.** ADR 0003 is not superseded. Faster networking
   is an optional performance improvement and comparison point, not a minimum
   requirement for the first network architecture.

7. **Fine-grained remote expert execution remains an available research
   strategy, not the primary network strategy.** It may be revisited on faster
   networks or for workloads/hardware where measurement supports it.

8. **A node may later contain its own local InferSwarm resource plan.** Coarse
   inter-node partitioning does not prevent a node from using multiple local
   GPUs, RAM, or other tiers internally. That composition is future work and is
   not required by the first network POC.

9. **The generic execution boundary is strategy-specific semantic work/state.**
   ADR 0006's routed-work/route-contribution boundary describes the proven MoE
   expert strategy. It is not a universal wire shape. Model-block execution
   instead consumes and produces block-boundary model state. The eventual
   top-level capability contract must represent both without forcing either
   into the other's message schema.

The first evidence sequence is tracked by canonical issues:

- #31 — selective model-block loading with bounded host RAM;
- #32 — local split-block execution equivalence;
- #33 — two-machine block execution over 1 GbE;
- #34 — end-to-end two-node distributed decode.

A three-node experiment is created only if the two-node evidence earns it.

## Consequences

- Selective loading is now a distributed-architecture prerequisite rather than
  merely a startup optimization. A node must not require full-model host RAM
  for state it does not own.
- Model-block boundaries, KV/state ownership, and block-local fast execution
  become first-class research objects.
- The original Phase-4 fine-grained remote-expert issue is superseded before
  implementation; its historical reasoning remains useful evidence.
- Protocol work must distinguish expert-dispatch and model-block work units.
  A stable public protocol is still deferred until the POCs reveal the required
  fields.
- Larger-model validation may distribute arbitrary contiguous model state, not
  only routed experts, where evidence says that is the correct granularity.
- Local expert-residency work remains valuable independently, especially on
  healthy PCIe links and as a possible within-node strategy.
- Hardware capability measurement remains important, but D7 does not justify a
  generic worker score. The eventual capability contract stays deferred.

## Hypotheses distinguished from decisions

- **Decided:** coarse contiguous model-block partitioning is the first
  multi-machine strategy; 1 GbE remains the baseline; nodes should load only
  assigned state and keep block-local runtime/KV state local.
- **Decided:** the project does not require fine-grained network expert RPC to
  succeed before testing coarse node partitioning.
- **Not yet proven:** that two-node block execution is correct in the current
  FreeToken integration; issues #31 and #32 establish that prerequisite.
- **Not yet proven:** that 1 GbE produces acceptable end-to-end decode or
  prefill performance. Issues #33 and #34 measure that directly.
- **Not yet decided:** optimal block boundaries, scheduling policy, network wire
  format, capability schema, failure/retry semantics, elastic node membership,
  or three-plus-node topology.
- **Not claimed:** that 10 GbE is unnecessary in every workload. The claim to
  test is that it should not be required to make the first commodity-LAN
  architecture useful.
