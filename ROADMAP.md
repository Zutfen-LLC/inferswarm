# InferSwarm Roadmap

This roadmap tracks **evidence-gated research and implementation**, not feature
shipping. Results follow [BENCHMARKING.md](BENCHMARKING.md): if an experiment
fails, the roadmap changes rather than the thresholds or the numbers.

## Documentation authority

Repository precedence is:

> **[ADRs](docs/adr/README.md) decide; the
> [Fabric Doctrine](docs/architecture/fabric-doctrine.md) specifies;
> `ARCHITECTURE.md` explains; `ROADMAP.md` sequences.**

[ADR 0008](docs/adr/0008-canonical-fabric-doctrine.md) and the completed
resource/residency/planner Wayfinder (#37, decisions #38-#46) define the
architecture this roadmap must implement.

The current posture is **doctrine-shaped, API-unfrozen**. Each gate should
implement only enough internal structure to prove its question; no gate is an
excuse to invent the final planner, strategy plugin API, control plane, wire
protocol, or telemetry schema prematurely.

---

## Completed foundation

### Phase 0 — baseline and routing evidence — COMPLETE

Phase 0 established the reproducible single-GPU baseline, correctness reference,
and initial Qwen3.6 routing/cache-pressure evidence.

Primary records include:

- [`docs/benchmarks/results/phase0/`](docs/benchmarks/results/phase0/)
- [`docs/investigations/p0i-qwen36-routing-residency.md`](docs/investigations/p0i-qwen36-routing-residency.md)

Phase 0 remains historical evidence; its first-strategy terminology does not
constrain the current resource ontology.

### Phase 1 — two-GPU local candidate — COMPLETE / canonical `NO-GO`

Canonical Phase 1 proved resident remote expert execution correct but was
materially slower than the matched baseline. The immutable verdict for that
**exact tested candidate** is:

`NO-GO`

This is not a blanket rejection of distributed inference, multi-GPU execution,
or remote resident state.

Canonical report:

- [`docs/benchmarks/results/phase1/phase1-go-no-go-report.md`](docs/benchmarks/results/phase1/phase1-go-no-go-report.md)

### Phase1R — local architecture search D1-D7 — COMPLETE

Phase1R investigated why Phase 1 failed and whether a backend-fast-path local
resident architecture could still be useful.

Canonical handoff:

- [`docs/implementation/phase1r-architecture-search-handoff.md`](docs/implementation/phase1r-architecture-search-handoff.md)

Durable evidence includes:

- leaving the current FreeToken/CUDA captured path was catastrophically
  expensive on the tested stack;
- graph-compatible resident remote execution can be performance-positive;
- topology, physical work, transport volume, fan-in, and placement materially
  affect service cost;
- a healthy Gen3 x16 RTX 3060 was performance-positive on the tested path;
- the available Gen2 x1 RTX 3060 was capacity-positive but throughput-negative
  on that tested path;
- this is hardware/topology/runtime-specific evidence, not a universal PCIe
  cutoff or a permanent device class.

Issue #35 remains an independent hardware-causality retest opportunity and does
not block the successor roadmap.

### N0 — selective model-block loading — COMPLETE

Issue #31 completed with:

`N0_SELECTIVE_BLOCK_PASS`

N0 proved, on the pinned Qwen3.6 proving ground:

- checkpoint selection before materialization;
- loading only assigned block state instead of the full model/expert bank;
- bounded block-scoped loading/staging;
- exact isolated-block correctness for prefill/decode fixtures;
- explicit block-local KV/recurrent ownership and complete/disjoint state
  coverage for the frozen split.

N0 **did not** prove that final accelerator-resident state releases all
equivalent persistent CPU backing. The retained `expert_bank_final_host_bytes`
exposed that separate requirement when the next experiment was attempted.

The aborted N1 partial run is non-canonical evidence.

### Resource/residency/planner Wayfinder — COMPLETE

Issue #37 and decisions #38-#46 resolved the foundational doctrine before
further implementation:

- canonical Swarm/Coordinator/Node/Compute Unit/Memory Resource/Link graph;
- Logical State Units, Materializations, residency/staging/cache/replica and
  mutable authority;
- correctness/feasibility-first planning and plan-relative roles;
- measured evidence, baselines, degradation, and quarantine;
- generic planner / Model Execution Strategy boundary;
- immutable Execution Plan epochs, seamless scale-up, and degraded recovery;
- Adaptive Demand Profiles;
- measured distribution-granularity selection;
- documentation/roadmap handoff.

The normative synthesis is
[`docs/architecture/fabric-doctrine.md`](docs/architecture/fabric-doctrine.md).

### Retired N1-N3 sequence — HISTORICAL SCAFFOLDING

Issues #32-#34 and
[`docs/implementation/distributed-node-poc.md`](docs/implementation/distributed-node-poc.md)
record the earlier coarse-block sequence. They are preserved for reasoning and
provenance but are **not** the active roadmap.

In particular, no work should resume merely by reopening N1, N2, or N3
verbatim. Successor experiments must satisfy the doctrine/evidence gates below.

---

## Current handoff work

### Documentation synchronization — issue #47

Synchronize the repository around ADR 0008 and the Fabric Doctrine:

- umbrella ADR and normative doctrine;
- derived `ARCHITECTURE.md` and this roadmap;
- ADR forward/supersession notes;
- current README/contributor/integration/protocol guidance;
- repository-wide stale-assumption sweep.

Historical measurements remain unchanged except for explicit forward scope notes
where a document could otherwise be mistaken for current planning guidance.

### Runtime Gate R0 — accelerator residency without implicit host mirrors — issue #48

**This is the first corrected post-Wayfinder implementation gate.**

Starting from the valid N0 selective-loader substrate, prove:

> creating/retaining the tested accelerator materialization does not inherently
> retain an equivalent persistent host-RAM materialization after bounded staging
> has completed.

Required evidence includes:

- final accelerator-native execution correctness;
- persistent required memory accounting;
- persistent optional cache/replica accounting;
- transient staging/packing/transfer peak accounting;
- no lazy reappearance of the equivalent host materialization during repeated
  execution;
- deliberate accelerator bytes `X`;
- deliberate persistent host bytes `Y` with explicit roles;
- bounded transient host overlap `Z`;
- **unexplained persistent host mirror bytes = 0** for the proven path.

RSS/HWM is supporting evidence, not a substitute for component/materialization
accounting.

**Gate:** do not specify the replacement local split/heterogeneous experiment
until R0 passes and its evidence is frozen.

---

## Successor evidence gates

The issue numbers after #48 should be created only when the preceding evidence
makes their exact acceptance criteria knowable. The names below describe the
intended sequence, not pre-frozen implementation APIs.

### R1 — doctrine-shaped frozen-plan realization — BLOCKED BY R0

Prove that the runtime can realize one explicitly frozen test plan using the
current doctrine concepts without building a generalized optimizer.

The experiment should be able to account for, as applicable:

- participating Compute Units and Memory Resources;
- Logical State Units and concrete Materializations;
- execution locations/resource subgraphs;
- required/optional/staging state roles;
- legal Model Execution Strategy boundary;
- paths/transport used;
- mutable authority where relevant;
- complete plan memory accounting.

A hand-authored research plan or temporary internal manifest is acceptable.
The point is to prove that the runtime can express/realize the doctrine—not to
publish final `ExecutionPlan`, `ComputeUnit`, or strategy classes.

**Gate to R2:** frozen-plan realization must preserve correctness, accounting,
and backend-native fast execution without reintroducing implicit host mirrors.

### R2 — local heterogeneous/split execution — BLOCKED BY R1

Relaunch local multi-resource execution using a strategy-legal boundary selected
for the experiment. It may be expert-scale, block-scale, or another legal unit;
the old N1 split is not automatically canonical.

Required evidence:

- complete inference correctness against a matched reference;
- explicit state ownership/authority and boundary semantics;
- no hidden shared state that makes the boundary unreal;
- backend-native fast execution on participating backends;
- exact persistent/transient memory accounting;
- matched end-to-end A/B performance and latency evidence;
- resource/link/topology provenance;
- explicit explanation of why each participating resource helps feasibility,
  performance, or another declared plan objective.

A slow-but-correct result remains valid evidence even if it produces a `NO-GO`
for that placement candidate.

**Gate to R3:** prove at least one nontrivial doctrine-shaped local plan and
capture enough real candidate economics to justify minimum automatic selection.

### R3 — minimum automatic planning — BLOCKED BY R2

Introduce the smallest planner/strategy seam needed to demonstrate:

> **strategy constrains; planner chooses.**

The Model Execution Strategy supplies legal opaque units/constraints and
strategy-specific economics. The generic planner consumes the current resource
graph/evidence/operator policy and selects among multiple legal candidates.

The first implementation may use:

- exhaustive enumeration at POC scale;
- bounded heuristic search;
- temporary internal data structures.

It must not pretend to be a production scheduler.

Required outcomes:

- technically infeasible plans are excluded for explicit reasons;
- performance-poor but correct plans remain distinguishable from unsupported
  plans;
- available resources may remain unused when appropriate;
- plan explanations identify participation, exclusions, bottlenecks, and
  evidence confidence;
- no generic planner branch depends on model nouns such as `expert` or Qwen.

**Gate to R4:** the planner must be capable of comparing legal strategy
alternatives using measured evidence before network boundary work is promoted
back to the primary track.

### R4 — measured multi-node boundary primitive — BLOCKED BY R3

Resume multi-node research only after the local/resource/planning substrate is
clean.

[ADR 0007](docs/adr/0007-coarse-model-block-partitioning-as-first-network-strategy.md)
remains the **leading first network candidate**: a coarse contiguous model block
over ordinary 1 GbE. It is not permanent doctrine.

Before implementation, re-check the candidate against the target model,
measured resource graph, and #45 granularity economics. If another strategy-
legal boundary is clearly the stronger experiment, record the reason before
changing direction.

Primitive-level evidence should establish:

- exact cross-node correctness;
- strategy-semantic boundary state;
- payload size/frequency;
- network latency/bandwidth/contention provenance;
- persistent backend-native execution on each Node;
- state residency/authority behavior;
- exact memory requirements per Node;
- honest 1 GbE viability result for the frozen primitive.

Faster networking may be measured as a comparison after preserving the 1 GbE
baseline arm.

**Gate to R5:** no end-to-end distributed performance claims until the actual
network primitive is correct, resident, measured, and explainable.

### R5 — end-to-end multi-node serving and elasticity — BLOCKED BY R4

Measure complete serving with matched controls, including as applicable:

- correctness;
- TTFT;
- prefill throughput/latency;
- decode tok/s/latency;
- aggregate throughput/concurrency;
- network contribution;
- per-resource utilization/evidence where measurement does not perturb results;
- RAM/VRAM/materialization accounting;
- paging;
- plan explanation and confidence.

Then exercise #43 elasticity semantics:

#### Scale up

Add a beneficial resource/Node while serving, characterize it, prepare a better
replacement epoch, and activate it at a strategy-safe boundary with little/no
perceptible interruption when the test strategy permits.

#### Scale down

Remove a required resource/Node and prove that InferSwarm searches the surviving
trusted graph for the best correct feasible recovery plan—even when it must use
slower/smaller GPUs, CPU/RAM, caches/replicas, or changed legal granularity.

Service should fail only when no feasible plan exists or required authoritative
mutable state cannot be safely recovered under the declared state contract.

#### Scale back up

Return/add useful resources and demonstrate a later optimization epoch where
expected benefit warrants it.

Transparent zero-downtime failover is not a universal acceptance criterion;
correct authority continuity and truthful recovery semantics are.

**Gate to R6:** the resource/planner/epoch seams must work under real changes
before the public strategy/planner API is considered stable.

### R6 — architecture falsification with a materially different model — BLOCKED BY R5 FOR API STABILITY

Before declaring a public Model Execution Strategy/planner interface stable,
validate the doctrine against a model architecture materially different from
the first Qwen sparse proving ground.

A dense model is especially useful because it removes expert sparsity as an
easy decomposition assumption.

The purpose is not necessarily to beat the Qwen benchmark. It is to ask:

- can the strategy expose legal opaque units without changing the generic
  resource ontology?
- can the planner reason without expert/router assumptions?
- do state/residency/authority semantics remain sufficient?
- does granularity remain a measured strategy choice?
- which internal interfaces were accidental first-model artifacts?

Revise internal APIs freely if the falsification test exposes a better seam;
change doctrine only if a foundational invariant itself is disproven.

---

## Deferred validation targets

### GLM-5.3-Flash — issue #13

GLM-5.3-Flash remains a valuable **large heterogeneous-capacity** validation
target, not an assumption baked into the substrate.

Resume its investigation after the model-strategy and heterogeneous-capacity
foundation is strong enough to evaluate the exact pinned model honestly.

The investigation should census its real state/architecture and evaluate any
strategy authorized by the doctrine—coarse stages, local sparse placement,
mixed accelerator/RAM residency, caches/replicas, or combinations—rather than
forcing Qwen or ADR 0007 semantics onto it.

### Heterogeneous vendors

AMD/ROCm, Intel XPU/Arc, CPU-native paths, and future accelerators remain
long-term product goals.

Near-term Qwen/NVIDIA/FreeToken-specific code is acceptable when isolated
inside a research strategy/backend implementation. Vendor abstraction should be
extracted when real evidence identifies the stable seam, not invented ahead of
proof.

### Adaptive Demand Profiles

Demand-profile learning from model-wide, profile/Swarm history, and live
structural demand is doctrine-approved but does not block R0-R3.

Introduce it only when a strategy exposes a meaningful demand signal and there
are enough legal placement alternatives for adaptation to matter. It should be
possible without persistent raw prompt/response retention.

### Cache/promotion and progressive materialization

The doctrine permits executing against valid caches, streaming/progressive
promotion, and prepared materializations where strategy/backend semantics allow
it. Concrete policies should be introduced only when measured economics justify
them.

### Future NVMe/CXL/storage roles

Do not block future backing/storage resources, but do not predefine an intrinsic
NVMe tier or assume it belongs on the latency-critical hot path.

### Local topology follow-up — issue #35

The Gen3 x8 third-GPU retest remains useful hardware-causality evidence. Its
result can refine applicable resource/path evidence but does not define a
universal link-class policy or block the current R0 residency gate.

---

## Evidence and issue discipline

- InferSwarm issues are canonical for experiment questions, gates, and
  acceptance criteria.
- FreeToken carries focused implementation experiments and links back to the
  corresponding InferSwarm issue.
- Exact tested commits/model revisions/hardware/topology/runtime geometry are
  frozen with retained results.
- Every numeric claim follows `BENCHMARKING.md` evidence labels:
  `MEASURED`, `CALCULATED`, `ESTIMATED`, or `SPECULATIVE`.
- Microbenchmarks diagnose; end-to-end inference concludes end-to-end claims.
- A fast-but-wrong path is a bug, not a result.
- Negative results are preserved. A failed experiment changes the roadmap; it
  does not disappear from project history.
- New downstream issues should be created when prior evidence makes their
  concrete methodology/acceptance criteria knowable, rather than precreating a
  long speculative implementation ladder.
