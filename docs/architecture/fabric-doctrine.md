# InferSwarm Fabric Doctrine

Status: **Normative architecture specification**

Adopted by [ADR 0008](../adr/0008-canonical-fabric-doctrine.md) from the
completed resource/residency/planner Wayfinder (#37, decisions #38-#46).

## Precedence and purpose

Repository precedence is:

> **ADRs decide; the Fabric Doctrine specifies; `ARCHITECTURE.md` explains;
> `ROADMAP.md` sequences.**

This document is the detailed normative statement of InferSwarm's current
resource, state, planning, evidence, model-strategy, execution-epoch,
adaptive-demand, and distribution-granularity semantics.

The doctrine is intentionally **API-unfrozen**. Terms below name stable concepts
and invariants, not necessarily final public classes, wire fields, database
schemas, or plugin APIs. Temporary/internal research structures are acceptable
when they preserve these semantics.

Historical benchmark, investigation, and implementation records retain the
terminology and claims appropriate to the experiment that produced them. When a
historical document conflicts with this doctrine as a statement of *current*
architecture, this doctrine controls without retroactively changing the old
measurement.

---

## 1. Product-level planning rule

For a requested model/workload and the resources an operator is willing to
contribute, InferSwarm must conceptually:

1. determine which plans are correct and technically feasible;
2. apply hard operator constraints and distinguish technical feasibility from
   policy feasibility;
3. among remaining plans, choose the plan expected to deliver the greatest
   useful inference service under current evidence and workload needs;
4. explain why resources participate or do not participate and why the plan is
   expected to behave as predicted;
5. revise the plan at explicit epochs when resources, evidence, demand, policy,
   or failures make another plan sufficiently preferable or the current plan
   non-executable.

Performance is not the default feasibility gate. A correct plan that produces
0.7 tok/s may be slow but technically feasible. An operator may separately set
an explicit service requirement that makes such a plan policy-infeasible.

Maximizing device count, GPU utilization, VRAM utilization, or aggregate nominal
FLOPS is not the objective.

---

## 2. Canonical resource graph

### 2.1 Swarm

A **Swarm** is the durable logical management and planning domain. It survives
process replacement, Node joins/departures, model changes, and Execution Plan
changes.

The Swarm is not a machine and is not synonymous with the current Coordinator.

### 2.2 Coordinator

A **Coordinator** is a replaceable control-plane role responsible for the
currently authoritative coordination context. It is not a resource type and
need not provide inference-native compute.

Coordinator high availability, election, and durable-control-plane mechanisms
are implementation questions. The correctness invariant is that a serving
scope must not accept ambiguous control or mutable-state authority.

### 2.3 Node

A **Node** is one physically connected host/resource domain operating under one
local platform/runtime authority.

One physical machine with four GPUs is one Node. NUMA domains, PCIe root
complexes, accelerators, RAM, and local links are topology *within* that Node.
Two physical machines are two Nodes even when connected by an exceptionally
fast network.

### 2.4 Compute Unit

A **Compute Unit** is a planner-visible independently characterizable
execution-capable resource, for example:

- a GPU;
- a CPU execution domain;
- an NPU;
- another supported accelerator.

A Compute Unit has no intrinsic plan role such as primary, secondary, hot,
cold, performance, capacity, local executor, or worker.

### 2.5 Memory Resource

A **Memory Resource** is an independently accountable memory/addressability
domain capable of holding state, for example:

- system RAM / NUMA memory;
- VRAM;
- HBM;
- accelerator-local memory;
- a future CXL-attached memory domain.

Compute Units and their strongly affiliated memory remain distinct concepts so
that execution location and state location can be reasoned about independently
when strategy/backend semantics permit it.

System RAM remains first-class. CPU execution remains first-class. Neither is a
legacy fallback merely because accelerator resources exist.

### 2.6 Link and topology

A **Link** records discovered data-movement adjacency/connectivity and the
relevant measured/nominal evidence for that relationship.

If GPU0 reaches GPU1 only via GPU0 -> RAM -> GPU1 staging, the resource graph
contains those real relationships rather than inventing a direct GPU0-GPU1
link simply because data can eventually move between them.

**Locality is relational.** Terms such as same-device, same-NUMA-domain,
same-Node, PCIe-local, or network-remote are descriptive context, not fixed
performance tiers. Measured economics determine whether one path is preferable
to another.

### 2.7 Identity and epochs

Resource identities must be stable independently of transient CUDA ordinal,
PID, IP address, or enumeration order. Hardware replacement creates a new
resource identity. Availability, negotiated link state, topology, and runtime
context may change across resource/topology epochs without redefining durable
identity.

### 2.8 Runtime workers/executors

A worker/executor is an **Execution Plan or runtime construct**, not a canonical
physical resource class. A backend may map one runtime executor to one Compute
Unit, fuse multiple same-host Compute Units into one fast execution context, or
use another legal resource subgraph.

---

## 3. Logical state, materialization, and authority

### 3.1 Logical State Unit

A **Logical State Unit** is strategy-defined model/runtime state identity
independent of physical location and byte representation.

Examples may internally correspond to weights, a model region, recurrent
state, cache state, or other strategy-specific concepts, but those nouns are
not generic resource-planner semantics.

### 3.2 Materialization

A **Materialization** is one physical representation of a Logical State Unit.
It has, conceptually:

- a representation/form;
- a Memory Resource;
- provenance;
- version/freshness where applicable;
- a current plan/runtime role.

One Logical State Unit may have zero, one, or many valid materializations.

### 3.3 Backing and source

**Backing** is a retained origin/recovery path from which state can be obtained
again. It need not be active residency.

A **Source** is any currently valid origin from which another materialization
may be made, including a verified cache or replica when its semantics permit.

Checkpoint/storage backing is distinct from an equivalent persistent host-RAM
materialization.

### 3.4 Residency

**Residency** is a plan-intended commitment to retain a materialization on a
Memory Resource across an execution/placement scope. It is not merely the fact
that bytes briefly passed through that resource.

### 3.5 Staging

**Staging** is bounded-lifetime state/buffering used for load, conversion,
packing, transfer, migration, or an operation. Staging is not persistent
residency and should be released when its purpose ends unless it deliberately
changes role.

### 3.6 Cache

A **Cache** is a redundant valid materialization retained for economic benefit.
It is freely evictable without violating correctness or declared recovery
requirements.

A valid cache is a live source. A strategy may execute against it, stream from
it, progressively materialize elsewhere, retain it, or ignore it according to
legal semantics and measured economics.

### 3.7 Replica

A **Replica** is a deliberately retained redundant valid materialization that
may be relied on for sourcing/reconfiguration and, only when explicitly
guaranteed, recovery/failover.

Duplicate bytes do not imply a recovery guarantee.

### 3.8 Execution location

**Execution location** identifies the Compute Unit/resource subgraph performing
work. It is independent from state residency whenever the strategy/backend
supports such separation.

### 3.9 Authority

For state whose value can change, **authority** identifies the current lineage
allowed to define the logical value. Authority is not synonymous with location
or residency.

### 3.10 State semantic classes

A strategy declares at least the applicable semantics among:

1. **Immutable source state.** Identity is content/provenance based; no unique
   writable owner is required. Valid representations may be replicated.
2. **Derived/reconstructible state.** State may be discarded only when the
   strategy declares a valid reconstruction path and the required retained
   inputs actually exist. Theoretical replay does not make arbitrary mutable
   runtime state reconstructible.
3. **Mutable authoritative state.** There is one current authoritative lineage
   per independently mutable state unit unless a strategy explicitly provides a
   stronger coherence model. Stale copies cannot silently become current.

### 3.11 No implicit host mirror

Canonical invariant:

> **Creating or retaining an accelerator materialization never inherently
> requires retaining an equivalent persistent host-RAM materialization.**

A valid flow is:

```text
checkpoint/storage
      |
      v
bounded RAM staging
      |
      v
backend-native accelerator materialization
      |
      +--> staging released
```

Persistent host bytes remain legal when they have an explicit role, such as:

- deliberate RAM residency;
- CPU-executable representation;
- cache;
- replica/recovery materialization;
- metadata or unavoidable measured runtime overhead.

Backend/loader retention of an equivalent CPU tensor merely because the
accelerator copy exists is architectural leakage.

### 3.12 Representation plurality

The same logical state may have different valid physical forms: checkpoint
form, CPU-native form, NVIDIA-native packing, AMD-native representation, or
another supported form. Transformations require provenance and a correctness
contract. There is no universal canonical packed byte format.

### 3.13 Memory accounting

Memory feasibility and evidence must distinguish:

- **persistent required:** active residency, authoritative mutable state, and
  required runtime allocations;
- **persistent optional:** caches, replicas, speculative/prepared
  materializations;
- **transient peak:** staging, conversion/packing, transfer, migration overlap,
  scratch, and allocator/runtime overhead.

All physically resident bytes count regardless of label. A useful residency
proof explicitly reports deliberate accelerator bytes `X`, deliberate
persistent host bytes `Y` with roles, bounded transient peak `Z`, and unexplained
persistent equivalent host-mirror bytes `0` for the proven path.

---

## 4. Planner objective, roles, and operator policy

### 4.1 Feasible-plan set first

A candidate plan is technically feasible only if it satisfies applicable:

- Model Execution Strategy correctness and legal-boundary rules;
- backend/representation compatibility;
- required logical-state coverage;
- mutable authority/coherence requirements;
- persistent plus transient memory fit and headroom;
- execution and communication path requirements;
- resource availability and integrity trust;
- hard operator resource/policy constraints.

Expected poor performance does not by itself make an otherwise correct plan
unsupported.

### 4.2 Ranking objective

Among feasible plans, rank by **expected workload usefulness**, which may
include as relevant:

- TTFT/prefill behavior;
- decode latency/rate;
- aggregate throughput/concurrency;
- communication and synchronization overhead;
- startup/materialization/reconfiguration cost;
- stability and headroom;
- other strategy/workload service measures.

The exact cost function and weighting are deliberately unfrozen.

### 4.3 Functional plan roles

A resource/materialization may have overlapping functional roles such as:

- active execution;
- active/required residency;
- cache/replica;
- staging/scratch;
- backing/source access;
- no active use.

These are plan roles, not hardware classes.

### 4.4 Contribution descriptions

For explanation, a participating or available resource may be described as:

- performance-beneficial;
- feasibility/capacity-contributing;
- redundancy/cache-beneficial;
- operationally required;
- unused/unnecessary;
- incompatible;
- unavailable;
- quarantined;
- operator-excluded;
- performance-deprioritized.

These are conclusions about a resource *in the current planning context*.
They do not become intrinsic labels on the hardware.

### 4.5 Contributed hardware is eligible, not mandatory

Operator contribution means InferSwarm may use the resource within policy; it
does not require every available GPU/CPU/Memory Resource to participate in every
plan. A healthy compatible resource may remain unused when adding it would
reduce usefulness or add no meaningful value.

### 4.6 Operator policy

Normal configuration should express generic policy such as:

- resource eligibility/exclusion;
- reservations/contribution limits;
- locality/communication restrictions;
- trust/authority restrictions;
- dependency/availability policy;
- supported operational budgets such as power;
- explicit minimum service requirements;
- reconfiguration/admission policy.

Hard constraints remove plans from consideration; preferences affect ranking.
Manual model-specific placement, if ever exposed, is an advanced strategy/debug
facility rather than the normal product model.

### 4.7 Explanation

For a selected plan, InferSwarm should be able to explain:

- why it is correct/feasible;
- why each participant is used;
- why available resources are excluded;
- expected bottlenecks and poor-performance causes actually supported by
  evidence;
- applicable operator constraints;
- evidence confidence/freshness;
- health/trust decisions;
- transition/reconfiguration rationale.

The selected plan is the best **expected** plan under available valid evidence,
not a claim of perfect prediction.

---

## 5. Measurement, baseline, degradation, and quarantine

### 5.1 Evidence classes

Keep distinct:

- **nominal specification:** in-principle capabilities/context;
- **discovered configuration:** current attachment, capacity, negotiated link,
  backend/runtime availability;
- **measured behavior:** observations under a defined protocol;
- **runtime observation:** behavior during real service;
- **accepted reference baseline:** a versioned known-good historical
  expectation for a defined context;
- **planner estimate:** current prediction of future usefulness.

Nominal evidence may establish compatibility/possibility. Context-valid
measurements should drive economics where practical.

Unknown/unmeasured is uncertainty, not degradation or quarantine.

### 5.2 Evidence context

Reusable evidence conceptually records enough context to determine validity,
including as relevant:

- subject/resource/path/subgraph;
- hardware identity and topology;
- backend/runtime and relevant configuration;
- representation/strategy/model/revision;
- measurement protocol and conditions/load;
- provenance/time;
- confidence/quality.

Do not treat a measurement as a timeless device scalar such as
`gpu.speed = X` when material dependencies affect it.

### 5.3 Dependency-scoped revalidation

Invalidate/revalidate only evidence whose dependencies materially changed.
Examples:

- moving a GPU slot can stale PCIe/path evidence without changing instruction
  support or memory capacity;
- changing driver/backend can stale execution/kernel correctness/performance
  evidence without changing raw physical topology;
- model revision can stale model/strategy evidence without invalidating generic
  PCIe measurements;
- clock/power policy can stale performance baselines;
- hardware replacement invalidates identity-bound evidence.

### 5.4 Baselines do not silently drift

An **Accepted Reference Baseline** is versioned. Recent observations and Planner
Estimates may change, but a healthy historical baseline does not rolling-average
into a degraded new normal.

A new reference baseline is established deliberately after material context
change or explicit requalification, while old observations remain historical
records.

### 5.5 Separate trust axes

Do not collapse all health into one score. At minimum distinguish:

- availability;
- compatibility;
- integrity trust;
- performance expectation;
- evidence confidence/freshness.

A trusted but slow resource may remain useful capacity. A very fast untrusted
path is unusable for correctness-bearing work.

### 5.6 Performance degradation

Performance degradation affects economics and may trigger remeasurement,
deprioritization, replanning, or alerting. Slow links, thermal throttling,
reduced clocks, power limiting, or congestion do not by themselves imply data
corruption.

### 5.7 Availability degradation

Availability is separate from performance and integrity. A Node that
temporarily disappears is unavailable, not automatically corrupted. Returning
resources are revalidated as needed before future use.

### 5.8 Quarantine

Quarantine applies when evidence is sufficient to conclude that
correctness-bearing computation, state, or transport through the affected scope
cannot presently be trusted.

Examples include:

- correctness failure outside the declared tolerance;
- state/checksum mismatch;
- unexpected corruption;
- uncorrected memory/data errors;
- repeated attributable invalid/nonfinite results;
- transfer integrity failure;
- backend/representation validation failure.

Quarantine is **not** triggered merely by slowness, high temperature, narrow
links, reduced clocks, or one missed availability probe.

A quarantined scope is excluded from correctness-bearing execution and
authoritative state/source duties until remediation/context change plus required
successful integrity revalidation.

Quarantine uses the narrowest evidence-supported scope: Materialization, Memory
Resource, Compute Unit, Link/path, backend capability, representation/strategy
path, or Node. It does not silently expire and cannot be outweighed by
performance.

### 5.9 Alerts

Alerts should report the observed fact, affected scope, relevant baseline and
context, evidence freshness, planner response, service impact, and required
revalidation. Do not invent unsupported root-cause diagnoses.

### 5.10 Generic versus strategy evidence

Resource/topology evidence includes identity, capacity, topology/link state,
generic bandwidth/latency/contention, thermal/clock/power observations, and
basic integrity/availability.

Strategy/model-specific evidence includes service curves, representation/kernel
correctness/performance, strategy boundary costs, model-region execution
latency, route/count-aware behavior, and end-to-end model/workload outcomes.

Attach strategy evidence to the applicable resource/subgraph + backend/runtime
+ representation + strategy primitive (+ model/revision when needed), then
expose normalized economics to the generic planner.

---

## 6. Model Execution Strategy boundary

### 6.1 Central seam

> **A Model Execution Strategy translates model/revision semantics into an
> abstract constrained planning problem; the generic planner solves that
> problem against the Swarm.**

**Strategy constrains; planner chooses.**

### 6.2 Opaque planning units

Strategies expose opaque legal execution-planning units (called **Execution
Units** here as a conceptual term) distinct from Logical State Units.

The generic planner may reason about:

- identity;
- required state;
- legal implementations;
- dependencies;
- demand;
- memory requirements;
- normalized costs;

without knowing whether a unit means an expert, layer group, recurrent region,
or another model-specific construct.

### 6.3 Legal decomposition

The strategy defines all legal:

- split boundaries;
- grouping alternatives;
- co-location constraints;
- ordering/dependencies;
- concurrency;
- state/execution affinity;
- phase-specific decompositions where applicable.

The planner may not invent a model cut the strategy did not certify as legal.

### 6.4 Strategy-specific semantic boundaries

The strategy owns what crosses an execution boundary and how it is consumed,
produced, reconstructed, or reduced. The planner consumes normalized
communication/demand economics rather than one universal wire payload.

Fine-grained routed work and coarse hidden-state block boundaries can therefore
both exist without pretending to be the same work unit.

### 6.5 Demand behavior

Strategies expose enough demand structure to model materially relevant:

- access/execution frequency;
- conditional demand;
- sequencing;
- concurrency;
- reuse/lifetime;
- joint/correlated demand.

Do not collapse demand into independent marginal averages when correlation
materially affects placement.

### 6.6 Representation/backend legality

The strategy declares legal representations, transformations,
backend-capability predicates, implementation alternatives, and
correctness/equivalence contracts.

A legal implementation may target one Compute Unit or a resource subgraph. The
seam does not assume `one Execution Unit = one GPU` or `one worker = one GPU`.

### 6.7 Strategy economics

Strategies provide enough strategy-specific evidence/evaluation to compare
legal alternatives. The generic planner is not required to understand internal
variables such as route count, expert fan-in, layer count, or recurrent-state
meaning.

### 6.8 Correctness owns the feasible boundary

The strategy owns correctness legality for decomposition, representation,
boundary semantics, reconstruction/reduction, and state recovery. An
arrangement outside that contract never enters the planner's feasible set.

The generic planner must not require model/backend nouns such as expert, router,
transformer layer, KV cache, attention, SSM, Qwen, GLM, CUDA Graph, Triton, or
NVFP4.

Human-readable model-specific labels may be attached for diagnostics and plan
explanations without becoming planner semantics.

---

## 7. Execution Plans, epochs, reconfiguration, and failure

### 7.1 Immutable plan snapshot

An active **Execution Plan** is an immutable versioned snapshot for an explicit
execution scope. Resource/topology/evidence/policy changes never mutate it in
place; they may trigger a replacement plan.

### 7.2 Plan epoch/generation

Each activation has a distinct epoch/generation. Correctness-bearing work,
results, state transitions, and authority are attributable to the epoch that
authorized them.

Late work/results from a retired epoch cannot mutate current state or contribute
to current outputs.

### 7.3 Execution scope

Exactly one plan epoch owns execution and mutable authority for a given scope at
a time unless the strategy explicitly provides coherent shared authority.
Independent sessions/scopes may use different epochs concurrently when their
state semantics permit it.

### 7.4 Safe boundary

A Model Execution Strategy declares safe transition/recovery boundaries. A safe
boundary is a correctness boundary, not inherently a token, request, session,
or downtime boundary.

### 7.5 Prepare beside active service

Where resources permit, replacement plans should be prepared while the current
plan serves. Preparation may include:

- immutable/reconstructible materialization;
- allocation/buffer setup;
- backend-native capture/compilation/persistent contexts;
- connections and transport setup;
- validation.

**Make-before-break** is the preferred normal optimization path, but not a
correctness requirement when overlap does not fit.

### 7.6 Mutable authority cutover

Preparing a replacement does not transfer authority. At cutover:

1. old-epoch mutations for the affected scope settle;
2. replacement mutable state is validated/current where needed;
3. authority and future routing switch logically atomically;
4. the old epoch retires;
5. late old-epoch work is rejected;
6. old resources/materializations may be reclaimed when safe.

Mutable state need not move merely because execution resources change.

### 7.7 Scale up

New resources may be discovered, characterized, integrity-validated, and
incorporated automatically into a replacement plan. When operator policy and
strategy semantics permit, an already-active session may transition at the
earliest safe boundary with little or no perceptible interruption.

Automatic elasticity must still consider expected gain, evidence confidence,
transition cost, resource stability, and anti-thrashing policy.

### 7.8 Scale down and degraded recovery

If resource loss makes the active plan non-executable, InferSwarm searches the
remaining trusted resource graph for **any correct feasible replacement** before
declaring the scope unsalvageable.

Recovery may activate resources that were previously unused or optional,
including:

- smaller/slower accelerators;
- CPU execution;
- system RAM residency/execution;
- caches/replicas;
- a different legal distribution granularity.

The recovery planner optimizes the post-failure graph, not similarity to the
failed plan. A much slower correct plan is preferred to unnecessary outage
unless an explicit operator service requirement says otherwise.

### 7.9 Session continuity

Session continuity depends on trustworthy recovery of required mutable
authoritative state, not survival of a particular Compute Unit.

A session may continue/resume when required state at a valid recovery boundary:

- survives and remains trusted;
- has a coherently current replica under an explicit plan guarantee; or
- is explicitly reconstructible from actually retained trusted inputs.

Incomplete work may be discarded/replayed from a trustworthy boundary when the
strategy and host runtime allow it.

If required mutable authoritative state is lost and neither coherently
replicated nor reconstructible, the affected scope fails rather than
fabricating continuity.

### 7.10 Redundancy is explicit

Multiple materializations do not imply transparent failover. Any recovery
claim must explicitly describe freshness/coherence and the failure domain it
covers. Plans may intentionally provide partial or no redundancy.

### 7.11 Performance versus quarantine

Performance degradation may motivate a later replacement but does not
invalidate a correct current plan. Quarantine immediately excludes the affected
correctness-bearing scope. If already-produced mutable state may be
contaminated, recover from the latest trustworthy boundary or fail if none
exists.

### 7.12 Failed preparation

If replacement preparation/validation fails while the old plan remains valid,
the old plan continues unchanged. This transactional property is a key reason
plans are immutable snapshots rather than live-edited structures.

### 7.13 Authority uncertainty

If control-plane recovery cannot establish which epoch owns mutable authority,
the affected serving scope stops until authority can be proven. Split authority
is never preferable to interruption.

---

## 8. Adaptive Demand Profiles

### 8.1 Canonical concept

An **Adaptive Demand Profile** is predictive evidence about the structural
demand a workload/profile places on strategy-defined opaque planning units for
a compatible model/revision/strategy decomposition.

InferSwarm learns the **shape of demand**, not human-semantic meanings of model
parts.

### 8.2 Explicit Workload Intent is optional

A host/operator may provide an explicit intent or richer profile prior, but no
user is required to declare categories such as coding, chat, or analysis for
InferSwarm to function.

Intent/profile metadata is advisory prior evidence only. It cannot override
correctness, hard operator constraints, integrity trust, or feasibility.

### 8.3 Observation scopes

Applicable demand evidence may conceptually include:

- model-wide/general history;
- workload/profile-class history;
- Swarm-local history;
- a host-defined user/profile/tenant/application scope;
- current-session observations.

A profile need not map one-to-one to a human user. Host identity/profile
semantics are outside the generic planner.

More-specific evidence does not automatically trump much stronger broad
evidence; future statistical machinery may consider relevance, recency, sample
support, confidence, and drift.

### 8.4 Logical demand versus current placement

Where the strategy can expose the distinction, demand profiles should describe
underlying logical model demand rather than only current-plan consequences.

For example, remote dispatch counts alone are not a valid proxy for demand if a
unit looks cold merely because it is currently local. Cache hits and device
service time are execution/performance evidence, not replacements for the
logical demand signal.

### 8.5 Structural information

A strategy may preserve whatever structural demand materially affects planning,
including frequency, conditional demand, sequencing, concurrency, reuse,
lifetimes, boundary frequency, and joint/correlated demand.

No universal statistical schema is frozen.

### 8.6 Privacy boundary

Canonical demand adaptation must be possible without persistent retention of
raw prompts, generated responses, token sequences, or semantic prompt
embeddings. Structural execution metadata is sufficient in principle.

Demand profiles may still be sensitive operational data. Applicability scope
does not imply permission to upload/share it. Storage, retention, encryption,
sharing, and privacy UI are separate implementation/product decisions.

### 8.7 Applicability and transfer

A profile is scoped to compatible model/revision/strategy planning semantics
and any additional strategy-declared configuration that materially affects
logical demand.

Profiles do not silently transfer across incompatible model revisions or unit
decompositions. Cross-version/decomposition reuse requires an explicit
strategy-declared mapping or compatibility rule.

Hardware/topology changes do not inherently invalidate compatible structural
demand evidence: hardware changes the economics of satisfying demand, not
necessarily the demand itself.

### 8.8 Drift and live adaptation

Historical observations remain evidence but may lose predictive weight when
newer applicable observations show a changed regime. Explicit intent remains a
separate prior and is not silently rewritten.

Observations may accumulate continuously, but placement changes occur only via
#43-style plan epochs when expected benefit, confidence, transition cost, and
policy justify them. Active sessions may benefit from learned reconfiguration.

### 8.9 No guaranteed monotonic improvement

Adaptive placement **may** improve performance over time. It is not guaranteed
for every architecture/workload, is not necessarily monotonic, and can be
outweighed by changing resource conditions or workload drift.

A predicted better placement remains an estimate until runtime/benchmark
evidence shows the actual performance outcome.

---

## 9. Distribution-granularity selection

### 9.1 Plan-relative granularity

Distribution granularity is an Execution Plan/epoch decision, not a permanent
property of a model, Node, transport, or resource.

Avoid permanent rules such as:

- `MoE = experts`;
- `dense = blocks`;
- `local = fine`;
- `network = coarse`.

### 9.2 Legal cuts from strategy

The strategy defines all legal cuts/groupings. The planner selects among them;
it cannot invent semantically invalid boundaries.

### 9.3 Boundary economics

A distributed boundary is justified when useful value behind it outweighs the
cost of crossing it. Relevant value may include:

- useful computation;
- persistent state residency/capacity unlocked;
- reuse;
- parallelism/overlap;
- load distribution;
- avoided state movement elsewhere.

Relevant cost may include:

- payload volume;
- boundary frequency;
- latency and synchronization/dependency cost;
- serialization/copy/launch/queue cost;
- fan-out/fan-in;
- staging;
- shared-path contention;
- additional persistent memory;
- plan transition/reconfiguration cost.

### 9.4 Frequency and dependency sensitivity matter

Small frequent crossings can be worse than larger infrequent ones. Latency-
sensitive boundaries and bandwidth-sensitive boundaries are distinct economic
cases. High nominal bandwidth alone does not make arbitrary fine-grained
remote execution attractive.

### 9.5 Coarsening also costs

Coarse boundaries are not intrinsically better. Coarsening can:

- increase residency pressure;
- create load imbalance;
- serialize work/lower parallelism;
- force conditional-work waste;
- reduce placement flexibility;
- increase reconfiguration/materialization cost.

The planner seeks the economically best legal cut, not the coarsest cut.

### 9.6 Measured locality

For otherwise comparable legal arrangements, high-frequency and
high-dependency interactions should stay on the lowest-cost **measured** locality
practical.

Do not hardcode same-Node as always cheaper than inter-node. A pathological
local path may be worse than an excellent network path; #41 evidence governs.

### 9.7 Heterogeneous/nested granularity

Intra-node and inter-node granularities may differ. A plan may use a coarse
network stage containing fine heterogeneous GPU/RAM placement, but that nesting
shape is not mandatory.

Different boundaries at the same physical scope may also use different
granularities when links/resources differ.

### 9.8 Demand, workload, and phase

Adaptive Demand Profiles may influence grouping economics but cannot create
illegal boundaries. Different workload shapes or strategy-defined phases such
as prefill and decode may use different legal decompositions where that is
worthwhile.

### 9.9 Epoch changes

Granularity may change across plan epochs after resource joins/losses, new
measurements, demand changes, or policy changes.

### 9.10 Global optimization

Do not optimize boundaries independently when choices interact through memory,
shared links, contention, authority, or scarce fast resources. Candidate
partitions are evaluated as global plans under the #40 objective.

Legal distribution does not imply required distribution. A multi-node Swarm may
use only one Node for a particular model when that is best.

Capacity constraints may force a slower distributed decomposition merely to
make the model feasible; feasibility still precedes performance.

---

## 10. Backends, semantic execution, and transport

### 10.1 Backend-native fast execution

The architectural requirement is **backend-native fast execution**, not CUDA
Graphs specifically. A hot path should avoid per-operation host-orchestrated
eager execution when the backend provides a captured, compiled, queued,
persistent, or equivalent efficient mechanism.

CUDA Graphs are one NVIDIA implementation, not an InferSwarm semantic concept.

### 10.2 Same-backend fusion

A backend may fuse multiple same-host resources into one compiled/captured
execution structure when this is the fastest correct implementation. Such
fusion lives beneath the strategy/resource semantics and does not redefine the
canonical resource graph.

### 10.3 Semantic cross-resource boundaries

Cross-resource work is strategy-specific semantic work/state, not a universal
packed tensor or protocol shape. Routed MoE contributions, dense hidden-state
boundaries, or a future recurrent boundary may all use different payloads.

### 10.4 Numerical equivalence

Identical backend/representation paths should retain exactness tests where
available. Heterogeneous backends/representations may use predeclared bounded
numerical-equivalence contracts, finite-output requirements, and model-level
correctness checks where bitwise identity is impossible.

### 10.5 Transport orthogonality

Transport is subordinate to semantic execution. Possible substrates include
same-host copies/staging, shared memory, device IPC/P2P, ordinary TCP,
RDMA-style mechanisms, or future transports.

No transport is required to serve every strategy/boundary. 1 GbE remains the
baseline network target under ADR 0003; faster networking is allowed and should
improve plans where measurements support it.

---

## 11. Historical evidence and proving-ground scope

The current controlled proving ground remains:

`nvidia/Qwen3.6-35B-A3B-NVFP4`

for the evidence records that pinned that revision. NVIDIA/FreeToken/Qwen are
research substrates, not product boundaries.

Historical results retain their original scope:

- Phase 0 established the reproducible baseline/routing evidence used by the
  first research series.
- Canonical Phase 1 proved its tested resident remote-expert mechanism correct
  and gave that exact host-orchestrated candidate a `NO-GO` performance
  disposition.
- Phase1R D1-D7 established backend-fast-path importance and measured topology,
  work, transport, placement, and fan-in effects. Its hardware conclusions are
  specific to the tested topology/runtime and do not define universal PCIe
  cutoffs.
- N0's `N0_SELECTIVE_BLOCK_PASS` proves selective checkpoint loading,
  block-only state ownership, bounded block-scoped loading, and exact isolated
  block correctness. It does not prove release of all equivalent persistent
  CPU backing after final accelerator residency.
- The intentionally aborted N1 partial run is not canonical evidence. Retired
  N1-N3 issue sequencing is historical scaffolding.

Historical documents are not mechanically rewritten into current doctrine
terminology. When needed, add a forward scope note rather than altering the
measurement record.

---

## 12. Evidence-gated implementation posture

The current successor sequence is governed by `ROADMAP.md` and begins with the
first unproven doctrine invariant exposed after N0:

1. accelerator residency without implicit persistent host mirrors;
2. explicit doctrine-shaped frozen-plan realization;
3. local heterogeneous/split execution correctness and matched A/B evidence;
4. minimum automatic planner/strategy separation;
5. measured multi-node boundary research;
6. end-to-end multi-node serving plus elastic admission/recovery;
7. materially different model-architecture validation before declaring public
   planner/strategy APIs stable, followed by appropriate larger heterogeneous-
   capacity validation such as GLM-5.3-Flash.

ADR 0007 remains the leading first network strategy/evidence direction—coarse
contiguous model blocks over ordinary Ethernet—but this doctrine does not
precommit all future network execution to that granularity.

---

## 13. Intentionally deferred details

The following are implementation/research questions, not unresolved
foundational semantics:

- concrete public type names and object model;
- exact Execution Plan/control-plane schema and version negotiation;
- exact planner/search algorithm and cost function;
- capability/calibration schema and benchmark automation;
- exact Model Execution Strategy plugin/interface mechanism;
- exact semantic boundary/wire payload schemas;
- Adaptive Demand Profile statistics, storage, retention, privacy, and sharing;
- cache/promotion/prefetch/progressive-materialization algorithms;
- migration protocol and transparent failover machinery;
- anti-thrashing/hysteresis algorithms;
- production UI/control-plane design;
- final AMD/Intel/NPU/backend APIs;
- whether and how future NVMe/CXL/storage resources become useful in active
  plans.

A research implementation may choose temporary answers to these questions to
prove a bounded hypothesis. Such choices do not become architecture merely by
existing in a POC.
