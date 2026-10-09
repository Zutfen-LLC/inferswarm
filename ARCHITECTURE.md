# InferSwarm Architecture

```text
Status: Research / Proof of Concept
```

InferSwarm is an **open-source heterogeneous inference fabric**: a layer that
turns disparate compute, memory, and connectivity resources into one logical
inference platform while allowing model-specific execution strategies to remain
separate from generic resource planning.

## Canonical documentation hierarchy

This file is a readable architecture overview, not the normative specification.
Repository precedence is:

> **[ADRs](docs/adr/README.md) decide; the
> [Fabric Doctrine](docs/architecture/fabric-doctrine.md) specifies;
> `ARCHITECTURE.md` explains; `ROADMAP.md` sequences.**

[ADR 0008](docs/adr/0008-canonical-fabric-doctrine.md) adopted the current
doctrine after the completed resource/residency/planner Wayfinder (#37,
decisions #38-#46).

The architecture is **doctrine-shaped, API-unfrozen**. The concepts below are
stable enough to guide implementation, but final public class names, planner
algorithms, strategy/plugin APIs, wire formats, storage schemas, and migration
mechanisms are intentionally not frozen yet.

## Purpose

For a requested model/workload and a set of operator-approved resources,
InferSwarm must eventually answer:

1. what resources exist and how they are connected;
2. what logical model/runtime state exists and where valid materializations
   reside;
3. what model-specific execution decompositions are legal;
4. which legal plan is correct and feasible;
5. among feasible plans, which is expected to deliver the greatest useful
   inference service under current measurements, workload evidence, and
   operator policy;
6. how a running plan adapts safely when resources, demand, evidence, or health
   change.

Model semantics remain owned by the host/model integration and its Model
Execution Strategy. Generic placement does not become a Qwen/MoE scheduler.

## Conceptual shape

```text
Host inference engine
        |
        v
Model Execution Strategy
(model/revision semantics)
        |
        | opaque legal state/execution units,
        | constraints, demand, representations,
        | correctness and strategy economics
        v
Generic InferSwarm planner
        |
        | resource graph + evidence + policy
        v
Versioned Execution Plan / epoch
        |
        +----------------+----------------+----------------+
        |                |                |                |
        v                v                v                v
  Compute Units     Memory Resources    Links/paths     backing/sources
 GPU/CPU/NPU/...    RAM/VRAM/HBM/...   local/network   checkpoint/etc.
        \                |                /
         \_______________|_______________/
                         |
                         v
             backend-native execution
```

The resource graph describes **what InferSwarm has**. An Execution Plan
describes **what InferSwarm intends to do with it**.

## Resource graph

### Swarm

A **Swarm** is the durable logical management/planning domain. It survives
Coordinator replacement, Node joins/departures, model changes, and plan changes.

### Coordinator

A **Coordinator** is a replaceable control-plane role, not a hardware class. It
may have no inference-native compute of its own.

### Node

A **Node** is one physical host/resource domain under one local
platform/runtime authority. A machine with several GPUs is one Node; PCIe root
complexes, NUMA domains, RAM, and local devices are topology inside it.

### Compute Unit

A **Compute Unit** is an independently characterizable execution-capable
resource such as a GPU, CPU execution domain, NPU, or future accelerator.

### Memory Resource

A **Memory Resource** is an independently accountable memory/addressability
domain such as system RAM, VRAM, HBM, or future CXL-attached memory.

Compute Units and Memory Resources are deliberately separate concepts: state
may reside somewhere other than the Compute Unit that executes against it when
the applicable strategy/backend allows that arrangement.

### Links and locality

**Links/topology** describe discovered connectivity and data-movement
relationships. Locality is relational and measured, not a permanent tier.

InferSwarm no longer canonizes L0/L1/L2/L3, `primary`, `secondary`, or
`performance`/`capacity` as intrinsic resource classes. Those terms may remain
inside historical research records where they accurately describe the
experiment at the time.

A pathological same-host path can be worse than a good network path. The
planner uses measured evidence rather than assuming that a nominal locality
label determines performance.

### Runtime executors/workers

A worker/executor is a **runtime/Execution Plan construct**, not a physical
resource ontology. A backend may map an executor to one Compute Unit, fuse
multiple same-host accelerators into one efficient execution structure, or use
another legal resource subgraph.

## State and residency

The key abstraction is **Logical State Unit**: strategy-defined logical state
identity independent of physical location or byte representation.

A Logical State Unit may have zero or more **Materializations** on Memory
Resources. The following concepts are distinct:

- **backing/source** — where state can validly be obtained again;
- **residency** — a plan commitment to retain a materialization;
- **staging** — bounded transient load/convert/transfer state;
- **cache** — redundant valid state retained for economic benefit and freely
  evictable without violating correctness/recovery guarantees;
- **replica** — deliberately retained redundancy that may be relied on only to
  the extent its freshness/recovery contract explicitly says so;
- **execution location** — where computation happens;
- **authority** — which lineage may define the current value of mutable state.

Strategies classify state according to semantics such as:

- immutable source state;
- derived/reconstructible state with an explicitly valid recovery path;
- mutable authoritative state with one current authoritative lineage unless an
  explicit coherence model provides otherwise.

### No implicit host mirror

A central invariant is:

> **Accelerator residency does not inherently require an equivalent persistent
> host-RAM materialization.**

A valid implementation can read/convert through bounded RAM staging, establish
a backend-native accelerator materialization, then release staging whose only
purpose was materialization/transfer.

Persistent host state remains entirely valid when it has an explicit plan or
runtime role—RAM residency, CPU execution, cache, replica, source state that
must actually remain resident, metadata, or measured runtime overhead. The
problem is unexplained duplicated backing retained merely because an accelerator
copy exists.

Memory evidence therefore distinguishes:

- persistent required;
- persistent optional;
- transient peak;
- unexplained duplication/leakage.

Issue #48 established `P48_ACCELERATOR_RESIDENCY_PASS` on the N0-derived
selective accelerator path: the final accelerator materialization remained
correct after equivalent live host source-bank materializations were released,
with no lazy rematerialization and zero unexplained persistent host mirror
bytes.

Issue #53 later established the stronger `HOST_STAGING_RECLAMATION_PASS` needed
for capacity accounting. On the accepted R2 two-worker path, staging pages whose
lifecycle ended after final accelerator residency were physically reclaimable
while workers and accelerator materializations remained live and correct.
Logical release, intentionally retained host materialization/cache state, and
physically available host capacity are therefore distinct facts.

The current RETAIN lifecycle is not a proven live-evictable post-finalization
cache and has no proven post-finalization rematerialization API. Planner logic
must not count that unproven behavior as on-demand runtime capacity.

## Planning

Planning has two stages conceptually:

```text
requested model/workload
+ strategy legality
+ operator-approved resources/policy
+ current trusted evidence
        |
        v
correct + feasible plan set
        |
        v
rank by expected workload usefulness
        |
        v
selected Execution Plan
```

Correctness and feasibility always precede performance ranking.

A slow but correct plan remains technically feasible unless an explicit
operator service requirement makes it policy-infeasible. The planner does not
maximize hardware participation or utilization for its own sake.

A resource can have plan-relative functions such as:

- active execution;
- active/required residency;
- cache/replica;
- staging/scratch;
- backing/source;
- no active use.

Its contribution may be described for explanation as performance-beneficial,
capacity/feasibility-contributing, redundancy-beneficial, unnecessary,
incompatible, unavailable, quarantined, operator-excluded, or
performance-deprioritized. These are conclusions about the current plan, not
permanent hardware labels.

### Operator policy

Normal users should not have to map experts, layers, or other model components
onto devices manually. Operators instead define generic constraints/preferences
such as:

- which resources may participate;
- reservations/contribution limits;
- locality or communication restrictions;
- trust/authority restrictions;
- dependency/availability expectations;
- supported operational budgets;
- explicit service requirements;
- automatic reconfiguration/admission policy.

Plans and exclusions must be explainable on demand.

## Measurement and health

InferSwarm is measurement-first where practical, but keeps evidence categories
separate:

- nominal specification;
- discovered configuration;
- measured behavior;
- runtime observation;
- accepted historical baseline;
- planner estimate.

Unknown performance is uncertainty, not failure.

Measurements have context: hardware identity, topology, runtime/backend,
representation, strategy/model where applicable, protocol, load/conditions, and
provenance. Revalidation is dependency-scoped rather than blindly rerunning
every benchmark or trusting measurements forever.

### Performance versus integrity

Do not collapse health into one score. Availability, compatibility, integrity
trust, performance expectation, and evidence confidence/freshness are distinct.

- A slow resource may remain useful.
- Thermal throttling or a narrow link usually changes economics, not
  correctness.
- A disappearing Node is unavailable, not automatically corrupted.
- Evidence that computation/state/transport is untrustworthy triggers
  **quarantine** of the narrowest supported correctness-bearing scope.

Quarantine cannot be outweighed by speed or silently expire. Explicit successful
integrity revalidation is required before the affected scope returns to
correctness-bearing use.

## Model Execution Strategies

The generic planner is neither an expert scheduler nor a block scheduler.

> **A Model Execution Strategy translates model/revision semantics into an
> abstract constrained planning problem; the generic planner solves that
> problem against the Swarm.**

A strategy exposes conceptually:

- opaque Logical State Units and execution-planning units;
- legal split/grouping/co-location/dependency boundaries;
- immutable/reconstructible/mutable state semantics;
- demand frequency, conditionality, sequencing, concurrency, reuse, and
  material correlations;
- legal representations/transformations;
- backend/capability requirements;
- correctness/equivalence contracts;
- strategy-specific execution/communication economics.

**Strategy constrains; planner chooses.**

The generic planner must not require concepts such as expert, router,
transformer layer, KV cache, attention, SSM, Qwen, GLM, CUDA Graph, Triton, or
NVFP4. A strategy may still attach such labels for diagnostics/explanations.

## Execution Plans, epochs, and elasticity

An active **Execution Plan** is an immutable versioned snapshot for an explicit
execution scope. Changes to resources, evidence, policy, or demand produce a
candidate replacement plan rather than mutating the active one in place.

Every activation has a distinct **plan epoch/generation**. Correctness-bearing
work/results/state transitions belong to the epoch that authorized them, and
late work from a retired epoch cannot mutate current state.

A strategy declares safe transition/recovery boundaries. A safe boundary is a
correctness concept—not necessarily a token, request, session, or downtime
boundary.

### Scale up

When better resources join, InferSwarm may:

1. discover/characterize and integrity-validate them;
2. prepare a better replacement plan while the current epoch keeps serving;
3. materialize immutable/reconstructible state, build backend fast paths, and
   prepare connections/buffers;
4. switch at the earliest safe strategy boundary when operator policy and
   expected benefit justify the transition.

An active session can therefore gain throughput with little or no perceptible
interruption.

### Scale down

When a required resource disappears, InferSwarm does not attempt to preserve
hardware symmetry with the failed plan. It replans against the surviving
trusted graph and prefers any correct feasible replacement over unnecessary
outage.

That replacement may use resources that were previously unused or optional:

- slower/smaller GPUs;
- CPUs;
- system RAM;
- existing caches/replicas;
- a different legal distribution granularity.

A materially slower plan is still valid when it is the best surviving feasible
plan, absent an explicit service constraint.

### Mutable-state hard stop

Session continuity depends on trustworthy mutable-authority continuity—not on
survival of a particular GPU. If required authoritative state survives, has a
coherent current replica, or is explicitly reconstructible from retained
trusted inputs, the session may continue/resume/replay from a valid recovery
boundary.

If required authoritative mutable state is unrecoverably lost, the affected
scope must fail rather than fabricate continuity.

## Adaptive Demand Profiles

InferSwarm may learn model/revision-specific structural demand over a strategy's
opaque planning units.

Applicable evidence may include:

- model-wide/general history;
- workload/profile-class history;
- Swarm-local history;
- host-defined user/application/tenant profile history;
- current-session observations.

A profile is not necessarily a human user identity.

Explicit **Workload Intent** is optional prior evidence only. InferSwarm should
not require users to classify a workload before serving it.

Demand learning should be possible without persistently storing raw prompts,
responses, token sequences, or semantic prompt embeddings. Structural demand
can include access frequency, conditional/joint demand, sequencing,
concurrency, reuse, and other strategy-relevant statistics.

Hardware changes normally alter the *cost of satisfying demand*, not necessarily
the underlying demand profile, so compatible model/revision/strategy demand
history can remain useful after hardware joins/leaves. Model revisions or
strategy decompositions require explicit compatibility/mapping before profiles
transfer.

Observations can accumulate continuously, but placement changes happen through
deliberate plan epochs rather than per-request migration. Adaptive placement may
make a model faster over time, but improvement is not guaranteed or monotonic.

## Distribution granularity

Distribution granularity is an Execution Plan/epoch choice, not a permanent
model or topology property.

The strategy defines legal cuts/groupings. The planner globally evaluates those
choices using:

- communication volume and frequency;
- latency/dependency sensitivity;
- measured bandwidth/path contention;
- execution cost;
- state residency/capacity/reuse;
- mutable-state constraints;
- parallelism/load balance;
- Adaptive Demand Profiles;
- transition/reconfiguration cost;
- workload objective.

The enduring heuristic is:

> **Keep high-frequency/dependency-sensitive communication on the lowest-cost
> measured locality practical, and cross a more expensive boundary only when
> enough useful compute, state residency, capacity, reuse, or parallelism lies
> behind it to justify the crossing.**

But coarse is not intrinsically better. Coarsening can increase memory pressure,
imbalance, serialization, conditional-work waste, and transition cost while
reducing flexibility/parallelism.

Intra-node and inter-node granularities may differ or even be heterogeneous at
the same physical scope. A coarse network region may contain fine local GPU/RAM
placement, but that arrangement is not a universal hierarchy.

ADR 0007 therefore remains the accepted **first** coarse-block-over-Ethernet
network strategy/evidence direction, not permanent `inter-node = contiguous
block` architecture.

## Backend-native execution and transport

The architecture requires **backend-native fast execution**, not CUDA Graphs
specifically. NVIDIA implementations may use CUDA Graphs/Triton/native packing;
AMD, Intel, CPU, or future backends may use their own compiled/queued/persistent
mechanisms and native representations.

Same-backend multi-device fusion is allowed beneath the semantic planning
boundary when it is the fastest correct implementation.

Cross-resource boundaries are strategy-specific semantic work/state rather than
one universal message schema. Transport is subordinate to those semantics and
may include same-host copies/staging, shared memory, P2P/IPC, ordinary TCP,
RDMA-style mechanisms, or future transports.

Ordinary **1 Gigabit Ethernet remains the baseline network target** under ADR
0003. Faster networking is welcome and should improve plans where measurements
support it, but it is not a mandatory architectural dependency.

R4 supplied the first accepted physical network-boundary evidence for that
posture. On the frozen Qwen `[0,19) / [19,40)` two-Node candidate, actual
clean-arm application demand peaked at about `2.947 Mb/s` A→B against a
`747.12 Mb/s` frozen 80%-margin limit derived from the measured ordinary-1-GbE
path, with zero retransmits. That is strong evidence that link **capacity** is
not the limiting resource for this exact semantic boundary; it is not a claim
that 1 GbE is universally sufficient or that latency/end-to-end serving
performance is already solved.

## Heterogeneous numerical correctness

[ADR 0010](docs/adr/0010-heterogeneous-numerical-equivalence.md) and its
[normative supplement](docs/architecture/numerical-equivalence-contract.md)
define heterogeneous numerical correctness. They control if this explanatory
summary differs from them.

Correctness has three conjunctive layers:

1. Exact integrity invariants prove that the authorized model, representation,
   state, plan, input, and execution path ran.
2. Qualified numerical equivalence applies the strategy's prospectively frozen
   envelopes to declared floating-point checkpoints.
3. The strategy's semantic contract checks discrete output decisions. The first
   deterministic greedy profile requires exact token IDs.

Each layer must pass. Tensor closeness cannot excuse wrong state, transport,
authority, attribution, or fallback. Matching tokens cannot excuse a numerical
envelope failure.

The Model Execution Strategy owns its checkpoint, comparator, applicability,
reference, and semantic definitions. Backend adapters can capture tensors and
report the observed path. The generic planner does not compare tensors and does
not contain model, GPU, CUDA, or backend tolerances.

The planner consumes immutable, context-scoped qualification evidence before
it ranks performance. A compatible candidate without applicable qualification
does not enter the correctness-bearing feasible set. A material change to the
model, representation, strategy contract, backend build, math stack, device
class or role, or relevant geometry can require requalification.

Transfer and state invariants remain exact. Sender and receiver boundary bytes,
Logical State Unit coverage, Materialization ownership, plan and session
attribution, and authority or fencing facts never become tolerant.

An operator can request the optional hard policy `BIT_EXACT_REQUIRED`. The
planner then excludes candidates without applicable bit-exact evidence. It must
not weaken the request to ordinary numerical equivalence. Bit exactness is not
the default requirement for the heterogeneous fabric.

## Current evidence and implementation posture

The controlled historical proving ground remains Qwen3.6-35B-A3B-NVFP4 on the
recorded NVIDIA/FreeToken environments.

- Phase 0 established baseline/routing evidence.
- Canonical Phase 1 proved the tested mechanism correct and gave that exact
  host-orchestrated candidate a `NO-GO` performance verdict.
- Phase1R D1-D7 measured backend-fast-path importance, topology, physical work,
  transport, placement, fan-in, and multiworker effects. Those hardware results
  are topology/runtime-specific, not universal PCIe cutoffs.
- N0 produced `N0_SELECTIVE_BLOCK_PASS`: selective checkpoint loading,
  block-only state ownership, bounded block-scoped loading, and exact isolated
  block correctness.
- R0 / issue #48 produced `P48_ACCELERATOR_RESIDENCY_PASS`: final
  accelerator-resident routed state remained exact after equivalent live host
  source materializations were released, with zero unexplained persistent host
  mirror bytes.
- R1 / issue #50 produced `R1_FROZEN_PLAN_REALIZATION_PASS`: a versioned frozen
  doctrine-shaped plan drove validation, realization, observed-state
  reconciliation, authority, memory roles, staging release, and correct
  execution without freezing a generalized public planner API.
- R2 / issue #51 produced `R2_LOCAL_SPLIT_EXECUTION_PASS`: one frozen
  `[0,19) / [19,40)` local split executed complete inference across two real
  Compute Units with byte-exact corrected-methodology correctness, disjoint
  state ownership/authority, an exact measured activation boundary, captured
  backend-native execution on both sides, zero steady-state model-state
  movement, and zero unexplained host model mirrors.
- R2's exact measured placement remains `PERFORMANCE_NEGATIVE` for decode
  throughput (median split/baseline ratio about `0.9122`) despite dramatically
  lower TTFT for the resident split. Correctness/feasibility and placement
  economics remain separate conclusions.
- Pre-R3 issue #53 produced `HOST_STAGING_RECLAMATION_PASS`: after final
  accelerator residency, the full-residency RELEASE lifecycle physically
  reclaimed `99.974%` of known combined Block A/B staging bytes while workers
  remained live and W2/W4 remained byte-exact with no rematerialization or
  graph recapture.
- R3 / issue #55 produced `R3_MINIMUM_AUTOMATIC_PLANNING_PASS`: the minimum
  generic planner independently selected among multiple legal local candidates
  from a frozen resource snapshot, operator policy, and context-valid evidence.
  The same physical graph selected the single-resource candidate for warm decode
  throughput and the resident split for warm TTFT, while lower-ranked feasible
  candidates and unused/excluded resources remained explicitly explainable.
- R4 / issue #57 produced `R4_MULTI_NODE_BOUNDARY_PASS`: the accepted contiguous
  split executed across `inferswarm01` and `inferswarm03` over one persistent
  ordinary-TCP 1-GbE path with byte-exact correctness, complete wire accounting,
  backend-native resident execution, #53 RELEASE, and zero steady-state
  model-state movement/fallback/recapture/source fetches. Its exact canonical
  network disposition is `R4_1GBE_PRIMITIVE_CAPACITY_VIABLE`.
- The aborted N1 partial run remains non-canonical; N1-N3 are retired historical
  scaffolding rather than the current roadmap.

Accepted R4 canonical provenance is physical producer
`e97f60b7b0120a72a7cf9926cf6a5c558782c9b2` and corrected evidence
`d5735c6b5075e835e7e8118922c44a7b0cf7439b`. The earlier `9a26fd2` evidence is
invalidated historical ancestry. The accepted evidence remains immutable even
though FreeToken `main` has since diverged.

Issue [#59](https://github.com/Zutfen-LLC/inferswarm/issues/59) is complete and
established the durable FreeToken `inferswarm-research` line without rewriting
accepted evidence. Issue [#60](https://github.com/Zutfen-LLC/inferswarm/issues/60)
is also complete with `R5A_STATIC_MULTI_NODE_SERVING_PASS`: a normal
host-runtime request reached generic planning, an immutable selected plan,
multi-Node realization, backend-native execution, and a correct measured
response. The accepted FreeToken merge head is
`d9f45a9ef7b5f89800f96c54397202a7d43beb52`.

Issue [#62](https://github.com/Zutfen-LLC/inferswarm/issues/62) is complete with
accepted disposition `R5B_PLAN_EPOCH_RECOVERY_PASS`. Its accepted FreeToken
merge head is `00ccd01fede8d2ad21ee83104f3b998c89ff9d1f`. R5B exercised the
already-accepted #43 semantics through ordinary serving without freezing a
public epoch field, final protocol, planner/strategy API, daemon, or production
control plane.

Historical R6 / issue
[#65](https://github.com/Zutfen-LLC/inferswarm/issues/65) remains permanently
`R6_DENSE_ARCHITECTURE_FALSIFICATION_FAIL`. Issue
[#71](https://github.com/Zutfen-LLC/inferswarm/issues/71) localized the first
single-versus-distributed numerical difference as `BACKEND_EXECUTION_LOCAL`
while retaining exact transport and state evidence. It did not set a tolerance
or reinterpret R6.

ADR 0010 / issue #72 established the heterogeneous correctness contract, and
the subsequent prospective methodology gates (#74, #86, #95, #109) culminated
in issue #110's terminal `V5_QUALIFICATION_PASS` on the qualified dense Gemma
subject (with #115 completing the audited raw-evidence cleanup). That
applicable qualification evidence enabled a separate successor full-integration
attempt. Current execution scope is recorded below.

<!-- project-status:frontier:start -->
**[Issue #280 — AMD-only Vulkan same-request pooling (candidate-B-only result STOP; authorization spent)](https://github.com/Zutfen-LLC/inferswarm/issues/280)**

Issue #268 is accepted as R8K_QWEN_CUDA_ORDINARY_OPERATOR_PATH_PASS on exact reviewed head 438c09ff1f3fb0e161f0bbf6d8389554ab8a1515, merged as 4c6df96cd03e50fbb990256507eb859769536aad (https://github.com/Zutfen-LLC/inferswarm/issues/268#issuecomment-5979357776), and Issue #255 remains accepted as MVP_DISTRIBUTED_INFERENCE_PASS (https://github.com/Zutfen-LLC/inferswarm/issues/255#issuecomment-5974171991). Both are bounded to the homogeneous NVIDIA/CUDA two-host topology inferswarm01 RTX 3060 plus inferswarm04 RTX 3090, the exact Qwen3.8-Flash-Next-UD-IQ1_S release and llama.cpp b29c606e28a01b1bc8c1351026a0fa6e616bf6c4 lineage, fixed placement, and verified participant-local backing; they establish no capacity or speed advantage over the recorded single-host comparison. The Issue #188 roadmap priority of 2026-10-06 is AMD-only Vulkan same-request pooling: Issue #280 first, Issue #281 queued behind an accepted #280 result and an explicit CONTINUE decision, and Issue #279 (CUDA capacity/value proposal) open at lower priority as planning only. Issue #280 asks whether the two dies of one V340L can hold useful parts of one model and both execute one request through Vulkan. Its single-use candidate-B-only physical experiment terminated STOP: the cold request proved the same-request two-die mechanism, the warm request failed attribution admission, and the cold synchronized-copy share exceeded its frozen 20% screen. The result is bounded to one V340L, one small model that fits a single die, and one frozen placement; it is not a verdict on dual-die Vulkan execution in general.

- **Issue #280 candidate-B-only physical result observation:** [`STOP`](https://github.com/Zutfen-LLC/inferswarm/issues/280#issuecomment-6073758406).
- **Maintainer acceptance:** pending maintainer acceptance.
- **Recorded execution authorization:** blocked — Issue #280 has no unspent physical authorization; Issue #281 lacks a separately approved plan and physical execution authority, and Issue #279 remains planning-only. The single-use candidate-B-only authorization (https://github.com/Zutfen-LLC/inferswarm/issues/280#issuecomment-6073673930) was consumed by exactly one launch and two requests and is spent; the earlier 2-launch/4-request authorization (comment 6060425902) and the eight-launch/sixteen-request campaign authority were spent before it. Living status is informational and grants no further execution authority: an observed result, a merge, or green CI never authorizes a rerun, retry, relaunch, R1 repeat, or successor, each of which requires a new explicit maintainer decision. [Authority](https://github.com/Zutfen-LLC/inferswarm/issues/280).

- Issue #280 candidate-B-only result (comment 6073758406) executed authorization 6073673930 on accepted main c2f0396cbff20ac0c5c7ddda3412ffad43a6db26 with exactly one launch and two requests, B-cold then B-warm, a 10.479 s physical phase, and no R1 repeat, retry, replacement, or extra request. B-cold established the same-request two-die mechanism on the frozen placement (blocks 0–18 on die A; blocks 19–35 plus the tied output role on die B): die A weights 877,856,768 B (45.63%), KV 79,691,776 B, 445 completed commands; die B weights 1,046,089,728 B (54.37%), KV 71,303,168 B, 393 completed commands; forty graphs admitted; logical boundaries of 573,440 B and two host-staging legs totaling 1,146,880 B, which are logical and staging bytes rather than measured PCIe wire traffic. B-warm failed attribution admission (timeline completion identity does not match recorded event/value) and is not an admissible hardware result. Both responses passed the deterministic task rubric. B-cold synchronized copy time was 23.05% of request wall against the frozen 20% screen. Terminal STOP: the mechanism is proven for the cold request only, warm attribution failed, and no successor work is authorized.
- Issue #280 remains open and no maintainer disposition of the candidate-B-only STOP is recorded, so acceptance is pending and nothing is inferred from the result, the merged PR #296 engineering, or green CI. The result is bounded: one V340L on inferswarm05, Qwen2.5-3B-Instruct-Q4_K_M (which fits a single die, so this is a mechanism result and not a capacity result), the pinned llama.cpp b29c606e28a01b1bc8c1351026a0fa6e616bf6c4 Vulkan build with the PR #286 successor overlay, and one frozen placement. Custody is append-only: candidate-B-only evidence is retained at controller /home/zutfen/is280b-6073673930-evidence/ and host inferswarm05:/home/hermes/is280b-6073673930/ (TERMINAL.json, MANIFEST.sha256) and is not imported into this repository; the earlier r3 evidence at /home/zutfen/is280r3-evidence/ and inferswarm05:~/is280r3-physical/ is unchanged.
- Issue #289 and the merged PR #290 launcher and PR #296 kernel-verified serving-process identity mode are CPU and loopback engineering, not physical evidence; PR #296 does not change the pinned llama.cpp executable. The accepted PR #286 successor source identity and the frozen model, prompts, observer, thresholds, and STOP limits are unchanged.
- Issue #281 (V340L, RX 5600 XT and healthy RX580 Vulkan pooling) is queued behind an accepted #280 result and an explicit CONTINUE decision; neither exists, because the latest #280 result is STOP with acceptance pending. #281 has no recorded plan, plan approval, budget, or execution authorization, its first deliverable would be a concise plan, and no hardware relocation or purchase is assumed. One V340L result cannot establish multi-card scaling or justify a purchase.
- Issue #188 is roadmap authority and not an execution ticket. Its priority order is: #280, then #281 when queued, then #279 (CUDA capacity/value proposal, open and planning only). Mixed NVIDIA/AMD work is deferred, #239/R8-J remains blocked with its frozen contract and sealed holdout unchanged, and #244 is closed not-planned. No CUDA implementation or physical work is assigned.
- Research direction, not an authorization: the open capability question is a model or workload that is demonstrably infeasible under a declared single-resource envelope and is correctly executable when additional heterogeneous resources are added. It is a separate claim from GPU-residency expansion, where the single-resource comparison can still complete, and from performance. Issues #279 and #281 are the existing gates where this question would be scoped; this status creates no new prerequisite issue, experiment, or authority.
- The separately accepted #264 bounded pilot remains limited to its path-transition scope: four fresh-process units observed SUBGROUP/subgroup/32x1x1 to LARGE/hybrid/128x1x1 at output.weight, with both arms screening-variable; numerical root cause and H2/H3/H5 theorem closure remain open. Acceptance authority: https://github.com/Zutfen-LLC/inferswarm/issues/264#issuecomment-5969219338.
- The #250 predecessor remains accepted as the ARM_A_STOPS_LADDER localized boundary only; observation https://github.com/Zutfen-LLC/inferswarm/pull/251#issuecomment-5904093750 and acceptance https://github.com/Zutfen-LLC/inferswarm/issues/250#issuecomment-5904094070 remain preserved. This was not established as root cause.
- Issue #264's sole live minimal experimental selector is subgroup32→large128 hybrid for the output.weight MMV q4_K*f32 route; dimensions/types and frozen comparator identity are scoped to that candidate only. The cooperative-matrix candidate is dead; do not revive it.
- Four fresh-process units at the frozen execution head observed the actual path transition at all 10 output events per unit. BASE and candidate both differ across their two full-row digests and are screening-variable; matching candidate response tokens do not establish numerical stability or causality.
- The bounded pilot stopped at two units per arm; no third units or retry. Controller preservation verified the accepted #262 150-file inventory unchanged and 69 new retained files byte-identical across remote and local roots. The pure report's preservation field remains external-pending by design.
- Issue #266 is COMPLETED (closed completed), and PR #256 is MERGED to main as 442e2a02ce89e7fb42bceff1f7a47c8789c17733 (https://github.com/Zutfen-LLC/inferswarm/pull/256); the aggregate #254/#258/#260/#262/#264 stack is historical R8-I3C authority, not a pending review frontier. The bounded #264 result is accepted, and PR #265 merged into the aggregate producer branch as b3b28825d860b01b40f7b5697d5a50266ecaeb39 after exact-head review and Final CPU Validation on 28120bb57bfa9b8997d3d616c24e59a70f96a9af (run 37122285620). Those historical receipts are not validation receipts for the current #255 head. A source/CI/subagent PASS or additive report head grants no new physical authority. No automerge, R8-J, dead-control, or broad-matrix work is authorized.
- The completed #258 prospective theorem (merged PR #259) keeps historical A3 terminal-capability separate from hypothesis coverage: closure remains impossible, required_arms is empty, and A5 remains observationally capable but nonterminal. #260/#262/#264 use distinct instrumented source identities; their path observations do not reopen historical theorem closure.
- Issue #241 remains accepted as R8I3_COMPARATOR_V2_BLOCKED; #244 and #239 remain blocked on their Vulkan/comparator path. Issue #255's accepted capability is limited to its bounded tested homogeneous NVIDIA/CUDA two-host MVP; it establishes no numerical equivalence, mixed-vendor readiness, production readiness, or new R8-J/Vulkan execution authority. The #255 observation asserts the MVP_DISTRIBUTED_INFERENCE_PASS terminal only within that accepted scope.
<!-- project-status:frontier:end -->

FreeToken remains the initial validation/integration vehicle, not the permanent
product boundary. Reusable runtime functionality should eventually live behind
a narrow host-engine seam in this repository when evidence makes that seam
stable enough to extract.

## Intentionally open implementation questions

The following remain deliberately unfrozen:

- concrete public resource/plan/strategy type names;
- exact planner/search algorithm and cost function;
- exact capability/calibration schema;
- strategy/plugin/public extension API;
- execution-plan/control-plane wire schemas and version negotiation;
- migration/transparent-failover implementation;
- Adaptive Demand Profile statistics/storage/privacy implementation;
- cache/promotion/prefetch/progressive-materialization algorithms;
- exact heterogeneous backend interfaces;
- final production UI/control-plane shape.

These are downstream implementation/research questions under the doctrine, not
reasons to reopen the resource/residency/planner fundamentals.

