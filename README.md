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
benchmark/evidence records, and the current evidence-gated roadmap. Runtime
experiments continue in the
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

<!-- project-status:capabilities:start -->
| Capability | Evidence scope | Demonstrated result |
|---|---|---|
| Automatic planning | Physical | Strategy-constrained selection among legal local plans using applicable evidence and operator policy. [Evidence](https://github.com/Zutfen-LLC/inferswarm/issues/55#issuecomment-5495529413); [acceptance](https://github.com/Zutfen-LLC/inferswarm/issues/55#issuecomment-5495529413). |
| Distributed serving | Physical | A normal request drives planning, multi-Node realization, and backend-native execution on the tested Qwen path. [Evidence](https://github.com/Zutfen-LLC/inferswarm/issues/60#issuecomment-5504161037); [acceptance](https://github.com/Zutfen-LLC/inferswarm/issues/60#issuecomment-5504161037). |
| Plan epochs and recovery | Physical | Resource changes and recovery preserve plan-epoch authority and reject retired work on the tested serving path. [Evidence](https://github.com/Zutfen-LLC/inferswarm/issues/62#issuecomment-5508822299); [acceptance](https://github.com/Zutfen-LLC/inferswarm/issues/62#issuecomment-5508822299). |
| Separate Coordinator | Physical | A CPU-only Coordinator handles ingress, planning, epoch coordination, and committed output without hosting model execution. [Evidence](https://github.com/Zutfen-LLC/inferswarm/issues/67#issuecomment-5516608982); [acceptance](https://github.com/Zutfen-LLC/inferswarm/issues/67#issuecomment-5516608982). |
| Selective artifact acquisition | CPU fixture | Participants acquire only required model artifacts in the model-independent acquisition proof. [Evidence](https://github.com/Zutfen-LLC/inferswarm/blob/53fb8f4c7ba3108a21f983712e5cbdb747a26600/docs/implementation/plan-driven-artifact-acquisition-99/README.md); [acceptance](https://github.com/Zutfen-LLC/inferswarm/commit/53fb8f4c7ba3108a21f983712e5cbdb747a26600). |
| Peer reuse and replacement deltas | CPU fixture | Verified inventory, source selection, peer publication, and replacement-plan acquisition work across participants. [Evidence](https://github.com/Zutfen-LLC/inferswarm/blob/ffbc51a85dfa492b11ff8f3b0ea31b7762d6a5da/docs/implementation/plan-driven-artifact-orchestration-101/README.md); [acceptance](https://github.com/Zutfen-LLC/inferswarm/commit/ffbc51a85dfa492b11ff8f3b0ea31b7762d6a5da). |
| Locality-aware transition planning | CPU fixture | Verified artifact locality affects transition ranking without changing technical feasibility or execution ranking. [Evidence](https://github.com/Zutfen-LLC/inferswarm/blob/47624abe14a84d27188018200a48a8652f93bfd6/docs/implementation/artifact-locality-transition-planning-103/README.md); [acceptance](https://github.com/Zutfen-LLC/inferswarm/commit/47624abe14a84d27188018200a48a8652f93bfd6). |
| Dense Gemma numerical qualification | Physical | The frozen Gemma subject passed V5 numerical and semantic qualification; applicability remains specific to that subject. [Evidence](https://github.com/Zutfen-LLC/inferswarm/blob/546ff9d44c727b6eba5abf3c8b40669b0b9b0b76/docs/qualification/gemma4-12b-it-v5-campaign-110/b/TERMINAL-REPORT.md); [acceptance](https://github.com/Zutfen-LLC/inferswarm/commit/546ff9d44c727b6eba5abf3c8b40669b0b9b0b76). |

- Research / proof of concept; no released production runtime.
- Physical results apply to their tested model, backend, hardware, and topology. CPU fixture proofs do not establish physical integration.
- Public planner/strategy APIs, wire formats, and storage schemas remain unfrozen; broad vendor support remains an objective.
- Historical Phase 1 NO-GO and R6 failure remain unchanged. GLM-5.3-Flash / #13 is a later falsifier.
<!-- project-status:capabilities:end -->

Earlier work established selective loading, accelerator residency without an
unexplained persistent host mirror, and local/multi-Node execution on Qwen.
Canonical Phase 1 retained a scoped `NO-GO` performance verdict; subsequent
Phase1R experiments established topology-dependent performance and capacity
tradeoffs. See [ROADMAP.md](ROADMAP.md) and the
[historical Phase1R record](docs/implementation/phase1r-architecture-search-handoff.md)
for the exact experiments and immutable results.

## Current research direction

<!-- project-status:frontier:start -->
**[Issue #117 — R6 successor dense full integration](https://github.com/Zutfen-LLC/inferswarm/issues/117)**

Integrate V5-qualified dense Gemma with automatic planning, participant-exact artifact acquisition, selective materialization, and ordinary fenced serving.

- **Arm A — V5 execution-math bridge observation:** [`ISSUE117_ARM_A_EXECUTION_EQUIVALENCE_PASS`](https://github.com/Zutfen-LLC/inferswarm/pull/122).
- **Maintainer acceptance:** pending maintainer acceptance.
- **Recorded execution authorization:** blocked — Arm B — canonical cold acquisition + realization. [Authority](https://github.com/Zutfen-LLC/inferswarm/issues/117).

- Arm A has an observed 192/192 PASS (PR #122) but is awaiting maintainer acceptance; it is not yet an accepted capability.
- Arm B is not authorized until Arm A is reviewed and accepted/merged.
- No Arm-A rerun is authorized by this status update.
- Arms C-E remain sequential later gates and are not authorized.
- No consumed h109 holdout material may be used as new evidence.
<!-- project-status:frontier:end -->

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

<!-- project-status:runtime:start -->
The [FreeToken fork](https://github.com/Zutfen-LLC/FreeToken) is the initial runtime vehicle.
Its durable integration branch is `inferswarm-research` ([established by #59](https://github.com/Zutfen-LLC/inferswarm/issues/59)).
Upstream-tracking `main` and immutable evidence branches have separate roles.
Execution uses the exact producer named by the current gate authority,
never an unreviewed branch tip. FreeToken is not the permanent product boundary.
<!-- project-status:runtime:end -->

See [`docs/integrations/freetoken.md`](docs/integrations/freetoken.md).

## Repository layout

```text
.github/             issue templates, pull request template, CI
docs/                documentation map and reading rules
docs/adr/            architecture decision records
docs/architecture/   normative Fabric Doctrine and its supplements
docs/benchmarks/     benchmark methodology/results
docs/investigations/ research inputs and feasibility work
docs/implementation/ active/historical experiment plans and handoffs
docs/protocols/      semantic-boundary and transport design notes
docs/qualification/  heterogeneous correctness-qualification lane (v1-v5)
docs/integrations/   host-engine integration notes
scripts/             CPU-only, deterministic, fail-closed evidence tooling
tests/               tests that guard the retained evidence
ARCHITECTURE.md      derived architecture overview
BENCHMARKING.md      benchmark/evidence contract
ROADMAP.md           evidence-gated successor roadmap
```

[`docs/README.md`](docs/README.md) maps the whole documentation tree and states
the rules for reading retained evidence. [`scripts/README.md`](scripts/README.md)
and [`tests/README.md`](tests/README.md) cover the tooling and how to verify the
repository locally.

## License

Apache License 2.0. See [LICENSE](LICENSE). Contributions are accepted under the
same license; see [CONTRIBUTING.md](CONTRIBUTING.md).
