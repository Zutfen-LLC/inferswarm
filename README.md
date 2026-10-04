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
| Bounded two-host CUDA/RPC inference | Physical | One ordinary Qwen3.8-Flash-Next-UD-IQ1_S text-generation request executed materially on two homogeneous NVIDIA/CUDA hosts using fixed/manual placement and verified participant-local backing; applies only to the tested inferswarm01 RTX 3060 + inferswarm04 RTX 3090 topology and accepted runtime/artifact lineage. [Evidence](https://github.com/Zutfen-LLC/inferswarm/issues/255#issuecomment-5971666116); [acceptance](https://github.com/Zutfen-LLC/inferswarm/issues/255#issuecomment-5974171991). |

- Research / proof of concept; no released production runtime.
- Issue #209 R7-B derived R7B_DEEPSEEK_V41_PHYSICAL_GATE_READY at https://github.com/Zutfen-LLC/inferswarm/pull/211 from retained pinned vLLM lifecycle source; compact fixture substrate-contract only, maintainer acceptance pending, and it grants no execution authorization.
- Physical results apply to their tested model, backend, hardware, and topology. CPU fixture proofs do not establish physical integration.
- Issue #255 is accepted as MVP_DISTRIBUTED_INFERENCE_PASS only for the bounded tested homogeneous NVIDIA/CUDA two-host topology, exact Qwen3.8-Flash-Next-UD-IQ1_S and llama.cpp lineage, fixed/manual placement, verified participant-local backing, and ordinary text generation/repeatability (https://github.com/Zutfen-LLC/inferswarm/issues/255#issuecomment-5974171991). Issue #268 is the active ordinary operator-path integration frontier; it is not yet accepted and living status grants no execution permission. No numerical-equivalence, mixed-vendor, production-readiness, dynamic-scheduling, performance-superiority, or R8-J/Vulkan authority is implied.
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
**[Issue #268 — R8-K ordinary operator-path integration (three physical requests observed; not accepted)](https://github.com/Zutfen-LLC/inferswarm/issues/268)**

Issue #255 is accepted for its bounded homogeneous NVIDIA/CUDA two-host MVP: inferswarm01 RTX 3060 plus inferswarm04 RTX 3090, exact accepted Qwen3.8-Flash-Next-UD-IQ1_S three-part release and llama.cpp b29c606e28a01b1bc8c1351026a0fa6e616bf6c4 runtime lineage, fixed/manual whole-layer placement, verified participant-local backing, and ordinary text generation/repeatability. Issue #268 advances the frontier to integrating that accepted predecessor into a reproducible ordinary operator path. At measured product head 478eb5efc93476dc2be990ac738c7ddd40e11eab, three ordinary product-path physical requests were observed on that bounded topology with fixed CPU/local CUDA/remote RPC placement, verified participant-local backing and owned cleanup; physical-stage spec PASS and quality APPROVED are review inputs, not #268 maintainer acceptance. This does not assert #268 acceptance, numerical equivalence, mixed-vendor readiness, production readiness, dynamic scheduling, performance superiority, or R8-J/Vulkan authority. The separately accepted #264 bounded pilot remains limited to its path-transition scope: four fresh-process units observed SUBGROUP/subgroup/32x1x1 to LARGE/hybrid/128x1x1 at output.weight, with both arms screening-variable; numerical root cause and H2/H3/H5 theorem closure remain open. Acceptance authority: https://github.com/Zutfen-LLC/inferswarm/issues/264#issuecomment-5969219338.

- **Issue #255 bounded CUDA/RPC MVP (accepted predecessor) observation:** [`MVP_DISTRIBUTED_INFERENCE_PASS`](https://github.com/Zutfen-LLC/inferswarm/issues/255#issuecomment-5971666116).
- **Maintainer acceptance:** [accepted](https://github.com/Zutfen-LLC/inferswarm/issues/255#issuecomment-5974171991).
- **Recorded execution authorization:** blocked — Three ordinary Issue #268 physical product-path requests were observed at measured head 478eb5efc93476dc2be990ac738c7ddd40e11eab, with physical-stage spec PASS and quality APPROVED; ordinary CI run 37169789383 succeeded on that measured head, not necessarily on this documentation head. Issue #268 is not accepted; Final CPU Validation requires maintainer GO on the exact final head and remains REQUIRED/DEFERRED. Living status is informational and grants no execution permission. No fourth or further physical request is authorized. This status grants no further execution authority.. [Authority](https://github.com/Zutfen-LLC/inferswarm/issues/268).

- The #250 predecessor remains accepted as the ARM_A_STOPS_LADDER localized boundary only; observation https://github.com/Zutfen-LLC/inferswarm/pull/251#issuecomment-5904093750 and acceptance https://github.com/Zutfen-LLC/inferswarm/issues/250#issuecomment-5904094070 remain preserved. This was not established as root cause.
- Issue #264's sole live minimal experimental selector is subgroup32→large128 hybrid for the output.weight MMV q4_K*f32 route; dimensions/types and frozen comparator identity are scoped to that candidate only. The cooperative-matrix candidate is dead; do not revive it.
- Four fresh-process units at the frozen execution head observed the actual path transition at all 10 output events per unit. BASE and candidate both differ across their two full-row digests and are screening-variable; matching candidate response tokens do not establish numerical stability or causality.
- The bounded pilot stopped at two units per arm; no third units or retry. Controller preservation verified the accepted #262 150-file inventory unchanged and 69 new retained files byte-identical across remote and local roots. The pure report's preservation field remains external-pending by design.
- Issue #266 is COMPLETED (closed completed), and PR #256 is MERGED to main as 442e2a02ce89e7fb42bceff1f7a47c8789c17733 (https://github.com/Zutfen-LLC/inferswarm/pull/256); the aggregate #254/#258/#260/#262/#264 stack is historical R8-I3C authority, not a pending review frontier. The bounded #264 result is accepted, and PR #265 merged into the aggregate producer branch as b3b28825d860b01b40f7b5697d5a50266ecaeb39 after exact-head review and Final CPU Validation on 28120bb57bfa9b8997d3d616c24e59a70f96a9af (run 37122285620). Those historical receipts are not validation receipts for the current #255 head. A source/CI/subagent PASS or additive report head grants no new physical authority. No automerge, R8-J, dead-control, or broad-matrix work is authorized.
- The completed #258 prospective theorem (merged PR #259) keeps historical A3 terminal-capability separate from hypothesis coverage: closure remains impossible, required_arms is empty, and A5 remains observationally capable but nonterminal. #260/#262/#264 use distinct instrumented source identities; their path observations do not reopen historical theorem closure.
- Issue #241 remains accepted as R8I3_COMPARATOR_V2_BLOCKED; #244 and #239 remain blocked on their Vulkan/comparator path. Issue #255's accepted capability is limited to its bounded tested homogeneous NVIDIA/CUDA two-host MVP; it establishes no numerical equivalence, mixed-vendor readiness, production readiness, or new R8-J/Vulkan execution authority. The #255 observation asserts the MVP_DISTRIBUTED_INFERENCE_PASS terminal only within that accepted scope.
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

