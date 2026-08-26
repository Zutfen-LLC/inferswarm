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

Nothing in this repository is a product yet. There is no released runtime here
today, and no performance claim on this page has been demonstrated end-to-end.
What exists now is the project home: identity, architecture direction,
principles, benchmarking rules, and a research roadmap whose early phases are
in progress in the [FreeToken integration fork](#current-implementation-vehicle).

## The long-term objective

Modern inference engines generally assume one homogeneous machine: one GPU (or
several identical GPUs), local VRAM, and a fast interconnect. A great deal of
usable compute does not look like that. InferSwarm's long-term objective is to
make resources such as:

- NVIDIA GPUs
- AMD GPUs
- Intel GPUs
- CPUs
- GPU VRAM
- system RAM
- (eventually) NVMe backing storage
- multiple GPUs inside one machine
- multiple machines connected over ordinary Ethernet

available as one unified logical inference resource, with placement decisions
driven by measured capability rather than assumed symmetry.

## The first implementation target

The first target is deliberately much narrower:

> Distributed MoE (mixture-of-experts) expert execution using multiple NVIDIA
> GPUs, beginning with RTX 3060-class hardware.

MoE is the starting point because its structure makes distribution unusually
tractable:

- experts are independently placeable — expert *k* can live on a different
  device than expert *j* without changing model semantics;
- only selected experts execute per token, so remote capacity is only touched
  when the router actually selects it;
- expert weights are large relative to activation payloads, so keeping experts
  resident somewhere and moving small activations may be substantially cheaper
  than repeatedly moving multi-megabyte expert weights (this is the central
  hypothesis, and it is not yet proven);
- MoE provides a good first substrate for heterogeneous and elastic resource
  allocation — different experts can live on devices of different capability.

To be explicit: the POC has **not** yet demonstrated performance gains. The
hypothesis above is exactly what the first roadmap phases are designed to test.
See [ROADMAP.md](ROADMAP.md) and [BENCHMARKING.md](BENCHMARKING.md).

## Design principles

These principles are canonical for the project. They are elaborated in
[ARCHITECTURE.md](ARCHITECTURE.md).

1. **Heterogeneity is a first-class feature.** Vendor, generation, VRAM size,
   compute speed, and network speed may all differ across participating
   resources. The scheduler should reason about *measured* capabilities, not
   assume homogeneous nodes.
2. **Commodity networking matters.** The baseline network target is 1 Gigabit
   Ethernet. Faster networking should help, but the architecture must not
   *require* InfiniBand, RDMA, GPUDirect, or 10/25/100 GbE. Whether 1 GbE is
   performant enough is an empirical question that will be benchmarked honestly.
3. **Move computation intelligently, not blindly.** Primary hypothesis: keep
   experts resident where possible and move small activation payloads to the
   device that owns the expert, rather than repeatedly moving expert weights to
   the primary GPU. Hypothesis — pending POC validation.
4. **System RAM remains first-class.** Secondary GPUs must *augment* rather
   than replace host-memory offload. Valid configurations include 1 GPU + RAM,
   2 GPUs + RAM, and multiple machines + RAM. An expert need not reside on a
   GPU merely because distributed GPU execution exists.
5. **NVMe is a future backing tier.** Designs must not block eventual
   NVMe-backed cold storage. NVMe is expected to serve capacity, not as a
   latency-critical hot execution tier.
6. **Resource contribution may be partial and elastic.** A machine may
   contribute an entire GPU, a fixed amount of GPU memory, a guaranteed minimum
   plus borrowable VRAM, only idle capacity, or RAM without any GPU. InferSwarm
   must not assume exclusive ownership of every participating GPU.
7. **Execution fabric and management plane are distinct.** The open-source
   fabric must remain usable without a paid control plane. Future commercial
   offerings (deployment, governance, fleet management, enterprise support)
   must add convenience, not remove capability. The open-source project will
   not be artificially crippled to enforce a commercial tier.
8. **Measure hardware; do not stereotype it.** Workers should advertise
   measured characteristics — supported formats, execution latency, VRAM
   capacity, bandwidths, network RTT — and placement should be based on those
   measurements.
9. **Model-independent fabric.** InferSwarm is not defined as MoE-only. MoE is
   the first execution *strategy*; dense models, replicas, and memory-tier
   plans are potential later strategies over the same abstractions.
10. **Keep the integration seam narrow.** The objective is not to rewrite any
    host engine. A narrow execution interface separates the host from wherever
    work actually runs.

## Current implementation vehicle

InferSwarm does not yet contain its own runtime. The current experimental
vehicle for proving InferSwarm integration is the Zutfen fork of FreeToken:

> **<https://github.com/Zutfen-LLC/FreeToken>**

The intended relationship:

```
FreeToken
    transformer/runtime integration
            │
            ▼
InferSwarm execution abstraction
            │
     heterogeneous workers
```

FreeToken is the initial host/runtime integration used for validation — not
necessarily InferSwarm's permanent, exclusive runtime dependency. The long-term
intent is that the novel distributed-execution functionality proven in the fork
becomes cleanly separable, so that InferSwarm is not a permanently divergent
fork and can eventually host its own runtime components (see
[ROADMAP.md](ROADMAP.md), Phase 5).

See [docs/integrations/freetoken.md](docs/integrations/freetoken.md) for the
fork's branch policy and the issue/PR relationship between the two
repositories. InferSwarm issues are canonical for InferSwarm architecture and
roadmap; the fork carries implementation PRs and evidence.

This fork is used with appreciation for the upstream project. Nothing here
implies endorsement of InferSwarm by FlashML or the FreeToken upstream
maintainers.

## Current research sequence

```
1. 1× RTX 3060 baseline
2. 2× RTX 3060 local distributed expert execution
3. 3× RTX 3060 scaling
4. mixed GPU + system-RAM placement
5. 2-machine execution over ordinary 1 GbE
6. generalized runtime extraction
7. heterogeneous AMD / Intel workers
8. larger-model validation
```

Later items depend on earlier results. Each phase has success criteria and
honest-measurement requirements in [ROADMAP.md](ROADMAP.md); if a phase fails
its criteria, the sequence changes rather than the numbers.

## Repository layout

```
.github/            issue templates, pull request template, CI
docs/adr/           architecture decision records
docs/benchmarks/    benchmark result conventions
docs/investigations/ research inputs and feasibility studies
docs/protocols/     worker/transport protocol design notes
docs/integrations/  host-engine integration notes (FreeToken)
ARCHITECTURE.md     architecture direction and open questions
BENCHMARKING.md     the benchmark contract
CONTRIBUTING.md     how to contribute
ROADMAP.md          research phases and acceptance criteria
SECURITY.md         reporting and security posture
```

Runtime code does not exist in this repository yet. It will appear when
implementation work establishes real boundaries, not before.

## License

Apache License 2.0. See [LICENSE](LICENSE). Contributions are accepted under
the same license; see [CONTRIBUTING.md](CONTRIBUTING.md).
