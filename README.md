# InferSwarm

**by Zutfen LLC**

> InferSwarm is an open-source heterogeneous inference fabric for turning
> disparate compute and memory resources into one logical inference platform.

**Many machines. One model.**

*Turn the hardware you already own into distributed inference capacity.*

```text
Status: Research / Proof of Concept
```

InferSwarm is an experimental Apache-2.0 project intended to let heterogeneous
resources cooperate on inference without requiring every device or machine to
look like the same kind of worker.

There is no released production InferSwarm runtime today. The repository is the
canonical home for architecture decisions, the normative Fabric Doctrine,
benchmark/evidence records, and the current evidence-gated roadmap. Early
runtime experiments continue in the
[Zutfen FreeToken fork](#current-implementation-vehicle).

## Canonical docs

Repository precedence is:

> **[ADRs](docs/adr/README.md) decide; the
> [Fabric Doctrine](docs/architecture/fabric-doctrine.md) specifies;
> [ARCHITECTURE.md](ARCHITECTURE.md) explains;
> [ROADMAP.md](ROADMAP.md) sequences.**

[ADR 0008](docs/adr/0008-canonical-fabric-doctrine.md) adopts the current
resource/residency/planning model after the completed Wayfinder (#37,
decisions #38-#46).

The architecture is **doctrine-shaped, API-unfrozen**: current implementation
must preserve the doctrine's semantics, but final public planner/strategy type
names, plugins, wire protocols, and storage schemas are deliberately deferred
until real implementations prove the seam.

## What the research has established

The first research track used Qwen3.6-35B-A3B-NVFP4 and NVIDIA hardware to test
resident sparse/MoE execution and then selective model-block loading.

- **Phase 0** established a reproducible baseline, correctness reference, and
  routing/cache-pressure evidence.
- **Canonical Phase 1** proved its resident remote-expert mechanism correct but
  produced an immutable `NO-GO` performance verdict for the exact tested
  host-orchestrated two-GPU candidate.
- **Phase1R D1-D7** established that backend-native fast execution matters
  enormously on the tested FreeToken/CUDA stack and measured the effects of
  physical work, PCIe topology, transport volume, placement, and fan-in. A
  healthy Gen3 x16 RTX 3060 was performance-positive on the tested path; the
  available Gen2 x1 RTX 3060 was capacity-positive but throughput-negative.
  That is topology/runtime-specific evidence, not a universal PCIe cutoff.
- **N0** completed with `N0_SELECTIVE_BLOCK_PASS`, proving selective checkpoint
  loading, block-only ownership, bounded block-scoped loading, and exact
  isolated-block correctness on the frozen Qwen proving ground.
- **R0 / #48** completed with `P48_ACCELERATOR_RESIDENCY_PASS`, proving that the
  tested final accelerator materialization did not require an equivalent
  persistent host-RAM mirror after bounded staging completed.
- **R1 / #50** completed with `R1_FROZEN_PLAN_REALIZATION_PASS`, proving that a
  versioned doctrine-shaped frozen plan could drive realization,
  reconciliation, authority/accounting, and correct execution.
- **R2 / #51** completed with `R2_LOCAL_SPLIT_EXECUTION_PASS`, proving the frozen
  `[0,19) / [19,40)` split across two real Compute Units with byte-exact
  corrected-methodology correctness, captured backend-native execution, and
  zero steady-state model-state movement.
- **#53** completed with `HOST_STAGING_RECLAMATION_PASS`, proving physical host
  staging reclamation after final residency for the accepted RELEASE lifecycle.
- **R3 / #55** completed with `R3_MINIMUM_AUTOMATIC_PLANNING_PASS`, proving the
  first automatic strategy-constrained, generic-planner selection across
  multiple legal local candidates using context-valid evidence and operator
  policy. The selected plan remained immutable and auditable before
  heavyweight realization/execution.
- **R4 / #57** completed with `R4_MULTI_NODE_BOUNDARY_PASS`, proving the accepted
  contiguous Qwen split across two physical Nodes over persistent ordinary TCP
  while preserving byte-exact correctness, backend-native residency/execution,
  #53 staging release, and complete boundary/wire accounting. The canonical
  1-GbE arm is `R4_1GBE_PRIMITIVE_CAPACITY_VIABLE`: peak measured clean-arm
  application demand was about `2.947 Mb/s` A→B against a frozen `747.12 Mb/s`
  80%-margin limit on the measured path.

Historical evidence remains historical and scope-qualified; the project does
not rewrite old results simply because the architecture vocabulary improved.

The detailed Phase1R record is maintained in
[`docs/implementation/phase1r-architecture-search-handoff.md`](docs/implementation/phase1r-architecture-search-handoff.md).

## Current research direction

The resource/residency/planner Wayfinder and runtime gates R0-R4 are complete.
The old N1-N3 coarse multi-node sequence remains retired historical scaffolding.

The next implementation prerequisite is:

> **[#59 — Pre-R5: establish a durable FreeToken InferSwarm integration
> line](https://github.com/Zutfen-LLC/inferswarm/issues/59)**

The current successor evidence gate is:

> **[#60 — R5A: prove static end-to-end multi-node serving from a
> planner-selected plan](https://github.com/Zutfen-LLC/inferswarm/issues/60)**

R5A moves from a manually coordinated research primitive to an integrated
serving path: a normal host-runtime request must reach strategy legality,
generic planning, a frozen plan, multi-Node realization, backend-native
execution, and a correct response. Accepted R4 network measurements now become
context-valid planner evidence rather than remaining a `FEASIBLE_UNRANKED`
evidence-collection input.

Live plan epochs, scale-up/down, and failure recovery are deliberately deferred
to R5B after static serving is correct, measured, and explainable.

See [ROADMAP.md](ROADMAP.md) for the exact gates.

## Long-term objective

InferSwarm aims to make resources such as:

- NVIDIA GPUs;
- AMD GPUs;
- Intel GPUs;
- CPUs;
- GPU VRAM / HBM;
- system RAM;
- multiple GPUs with asymmetric local links;
- multiple machines connected over ordinary Ethernet;
- future useful backing/memory resources such as NVMe or CXL where evidence
  supports them;

available to one logical planning domain, with decisions driven by model
semantics, measured capability, state requirements, workload demand, and
operator policy rather than assumed hardware symmetry.

## Design principles

These are a concise overview; the
[Fabric Doctrine](docs/architecture/fabric-doctrine.md) is normative.

1. **Heterogeneity is first-class.** Vendor, generation, memory size, compute
   speed, bus topology, and network speed may differ.
2. **Resources do not have permanent plan roles.** There is no canonical
   `primary`/`secondary` GPU or L0/L1/L2/L3 hierarchy. A GPU, CPU, RAM domain,
   or link participates according to the current plan.
3. **System RAM and CPU remain first-class.** They may provide residency,
   execution, staging, cache/replica value, or no active role depending on the
   plan; accelerators augment rather than deprecate them.
4. **State identity and physical copies are different things.** Logical state,
   materializations, backing, residency, staging, cache, replica, execution
   location, and mutable authority are distinct.
5. **Accelerator residency does not imply a host mirror.** Persistent host
   copies require an explicit purpose and accounting.
6. **Correctness and feasibility precede optimization.** Slow-but-viable is
   still viable unless an explicit operator service requirement says otherwise.
7. **Measure hardware; do not stereotype it.** Context-valid measurements drive
   economics; unknown is uncertainty; correctness failures quarantine rather
   than merely reduce a performance score.
8. **Model semantics stay behind a Model Execution Strategy.** Strategies
   define legal opaque state/execution units and boundaries; the generic
   planner chooses among them without needing concepts such as `expert`, Qwen,
   CUDA Graph, or NVFP4.
9. **Granularity is measured and plan-relative.** High-frequency/dependency-
   sensitive communication should stay on the lowest-cost measured locality
   practical, but coarse boundaries have costs too. Intra-node and inter-node
   granularities may differ.
10. **Elasticity works both directions.** Better resources may be prepared and
    folded into active sessions at safe boundaries; resource loss should fall
    back to any correct feasible surviving plan—including slower GPUs or
    CPU/RAM—before declaring outage.
11. **InferSwarm can adapt to structural demand.** Model/profile/Swarm/session
    history may inform future placement without requiring prompt/response
    retention or assigning human meanings to model parts.
12. **Commodity networking matters.** Ordinary 1 Gigabit Ethernet remains the
    baseline network target. Faster networks are welcome optimizations, not a
    mandatory project dependency.
13. **Execution fabric and management plane are distinct.** The open-source
    fabric must remain fully usable without a paid control plane.
14. **Keep the host integration seam narrow.** FreeToken is the first proving
    vehicle, not the product boundary.

## Conceptual architecture

```text
Host inference engine
        |
        v
Model Execution Strategy
        |
        | legal opaque units / state / demand /
        | representations / correctness / economics
        v
Generic InferSwarm planner
        |
        | Swarm resource graph + evidence + policy
        v
Versioned Execution Plan / epoch
        |
        +-------------------+-------------------+
        |                   |                   |
   Compute Units       Memory Resources      Links/paths
   GPU/CPU/NPU/...     RAM/VRAM/HBM/...     local/network
```

The resource graph describes what InferSwarm **has**. The Execution Plan
describes what InferSwarm **intends to do with it**.

## Historical execution strategies

MoE expert execution remains the first strategy actually researched and is
preserved by ADR 0004.

ADR 0007 remains accepted as the first **network strategy/evidence direction**:
coarse contiguous model blocks over ordinary Ethernet. It is not a permanent
rule that inter-node execution must use contiguous blocks. The current doctrine
allows the Model Execution Strategy and planner to select another legal
intra/inter-node granularity when measurements justify it.

## Current implementation vehicle

The experimental host/runtime vehicle is the Zutfen fork of FreeToken:

> **<https://github.com/Zutfen-LLC/FreeToken>**

Focused `poc/*` branches answer bounded questions. InferSwarm issues and this
repository remain canonical for architecture, methodology, acceptance criteria,
and retained evidence. A positive experiment does not automatically become a
permanent FreeToken fork feature or a public InferSwarm API.

Accepted R4 evidence remains immutable on its R3-descended research lineage.
Issue #59 establishes a durable integration branch before R5A so continuing
FreeToken development does not require rebasing or rewriting that evidence
history.

See [`docs/integrations/freetoken.md`](docs/integrations/freetoken.md).

## Repository layout

```text
.github/             issue templates, pull request template, CI
docs/adr/            architecture decision records
docs/architecture/   normative Fabric Doctrine
docs/benchmarks/     benchmark methodology/results
docs/investigations/ research inputs and feasibility work
docs/implementation/ active/historical experiment plans and handoffs
docs/protocols/      semantic-boundary and transport design notes
docs/integrations/   host-engine integration notes
ARCHITECTURE.md      derived architecture overview
BENCHMARKING.md      benchmark/evidence contract
ROADMAP.md           evidence-gated successor roadmap
```

## License

Apache License 2.0. See [LICENSE](LICENSE). Contributions are accepted under the
same license; see [CONTRIBUTING.md](CONTRIBUTING.md).
