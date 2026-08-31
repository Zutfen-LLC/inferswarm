# InferSwarm

**by Zutfen LLC**

> InferSwarm is an open-source heterogeneous inference fabric for turning
> disparate compute resources into one logical inference platform.

**Many machines. One model.**

*Turn the hardware you already own into distributed inference capacity.*

```
Status: Research / Proof of Concept
```

InferSwarm is an experimental open-source heterogeneous inference fabric
intended to let multiple machines and hardware resources cooperate on a single
inference workload. It is a Zutfen LLC project; it is not a separate company or
organization.

Nothing in this repository is a product yet. There is no released InferSwarm
runtime today. What exists is the project home, architecture record, benchmark
contract, experimental evidence, and the current validation roadmap. Early
implementation work continues in the [FreeToken integration fork](#current-implementation-vehicle).

## What the research has established

The first research track used Qwen3.6-35B-A3B-NVFP4 and RTX 3060-class NVIDIA
hardware to test fine-grained resident MoE expert execution.

- Phase 0 established the reproducible single-GPU baseline and exact routing
  evidence.
- Canonical Phase 1 proved resident remote expert execution correct but produced
  an immutable `NO-GO` for the tested host-orchestrated two-GPU candidate.
- Phase1R then showed why: dropping out of backend-native captured execution was
  catastrophic, while a graph-compatible resident remote worker could improve
  decode throughput substantially.
- D3-D7 extended that mechanism to multiple local workers and measured the
  effects of PCIe topology, dummy expert work, transport volume, placement, and
  fan-in. A healthy Gen3 x16 RTX 3060 was strongly useful; the available Gen2
  x1 worker was capacity-positive but throughput-negative on the tested path.

The completed local-expert research record is maintained in
[`docs/implementation/phase1r-architecture-search-handoff.md`](docs/implementation/phase1r-architecture-search-handoff.md).
These results do not establish a universal PCIe cutoff or a production worker
policy; they establish the measured behavior of the tested hardware/runtime.

## Current research direction

The next primary architecture track is **coarse multi-node model-block
partitioning over ordinary Ethernet**.

Instead of treating another machine as a fine-grained remote expert endpoint on
every MoE layer, each node should own a contiguous block of model layers and the
state needed to execute that block. Network boundaries move comparatively small
hidden-state payloads between persistent node-local execution plans. This keeps
backend-native fast execution local to each machine and aims to make 1 Gigabit
Ethernet a viable baseline rather than requiring specialized networking.

The immediate sequence is:

1. selective model-block loading with bounded host RAM;
2. local split-block correctness across an explicit execution boundary;
3. two-node block execution over ordinary 1 GbE;
4. end-to-end two-node decode, with faster networking as an optional comparison;
5. three-node scaling only if the two-node result earns it.

The previous fine-grained network-expert idea remains useful historical
research, not the current first network strategy. See [ADR 0007](docs/adr/0007-coarse-model-block-partitioning-as-first-network-strategy.md).

## Long-term objective

Modern inference engines generally assume one homogeneous machine: one GPU (or
several similar GPUs), local VRAM, and a fast interconnect. A great deal of
usable compute does not look like that. InferSwarm's long-term objective is to
make resources such as:

- NVIDIA GPUs;
- AMD GPUs;
- Intel GPUs;
- CPUs;
- GPU VRAM;
- system RAM;
- eventually NVMe backing storage;
- multiple GPUs inside one machine;
- multiple machines connected over ordinary Ethernet;

available as one logical inference resource, with placement decisions driven by
measured capability rather than assumed symmetry.

## Design principles

These principles are canonical for the project and are elaborated in
[ARCHITECTURE.md](ARCHITECTURE.md).

1. **Heterogeneity is a first-class feature.** Vendor, generation, VRAM size,
   compute speed, bus topology, and network speed may all differ. Placement
   should reason about measured capabilities, not assume symmetry.
2. **Commodity networking matters.** The baseline network target is 1 Gigabit
   Ethernet. Faster networking should help, but the architecture must not
   require InfiniBand, RDMA, GPUDirect, or 10/25/100 GbE.
3. **Move computation intelligently, not blindly.** Keep large state resident
   near the compute that uses it and move the smallest practical semantic state
   across resource boundaries. The correct granularity is strategy-dependent:
   routed experts locally, model blocks between machines, and potentially other
   units later.
4. **System RAM remains first-class.** Secondary accelerators augment rather
   than erase host-memory capacity. RAM remains a valid storage/execution tier.
5. **NVMe is a future backing tier.** Designs must not block eventual
   NVMe-backed cold storage, but NVMe is not assumed to be a latency-critical
   execution tier.
6. **Resource contribution may be partial and elastic.** A machine may
   contribute an entire GPU, part of its memory, RAM, or another bounded
   resource; exclusive ownership is not assumed universally.
7. **Execution fabric and management plane are distinct.** The open-source
   fabric must remain usable without a paid control plane.
8. **Measure hardware; do not stereotype it.** Workers/nodes should eventually
   advertise measured execution, capacity, bandwidth, latency, and topology
   characteristics. The exact contract remains evidence-driven and unfrozen.
9. **Model-independent fabric.** MoE expert execution was the first strategy,
   not the definition of InferSwarm. Model-block execution is the next strategy.
10. **Keep the integration seam narrow.** InferSwarm should not require a host
    inference engine rewrite; proven execution boundaries should converge on a
    small integration seam.

## Current implementation vehicle

The current experimental vehicle is the Zutfen fork of FreeToken:

> **<https://github.com/Zutfen-LLC/FreeToken>**

Conceptually:

```
FreeToken
    model/runtime integration
            │
            ▼
InferSwarm execution boundary
            │
     local resources / remote nodes
```

FreeToken is the initial validation runtime, not necessarily a permanent
exclusive dependency. Novel distributed-execution mechanisms are proven in
focused `poc/*` branches; accepted evidence and architecture decisions are
recorded canonically in this repository. See
[`docs/integrations/freetoken.md`](docs/integrations/freetoken.md).

## Repository layout

```
.github/            issue templates, pull request template, CI
docs/adr/           architecture decision records
docs/benchmarks/    benchmark methodology/results
docs/investigations/ research inputs, placement artifacts, feasibility work
docs/implementation/active and historical experiment plans/handoffs
docs/protocols/     execution-boundary and transport design notes
docs/integrations/  host-engine integration notes
ARCHITECTURE.md     architecture direction and open questions
BENCHMARKING.md     benchmark contract
ROADMAP.md          evidence-driven research roadmap
```

Runtime code will move into this repository only when experiments establish a
stable seam worth extracting.

## License

Apache License 2.0. See [LICENSE](LICENSE). Contributions are accepted under
the same license; see [CONTRIBUTING.md](CONTRIBUTING.md).
