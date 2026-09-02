# 0009. Plan-driven model artifact acquisition and distribution

Date: 2026-09-02
Status: Accepted

## Context

InferSwarm's current research/bootstrap workflow commonly downloads a complete
upstream model repository/checkpoint and then copies that complete repository to
each participating compute host. That has been convenient for experiments, but
it is not the architecture InferSwarm is trying to prove.

The accepted Fabric Doctrine already separates:

- Logical State Units from their physical representations;
- Materializations from backing/sources;
- residency from staging, caches, and replicas;
- model-strategy semantics from generic planning;
- source/checkpoint form from backend-native accelerator representations.

N0 proved selective checkpoint loading/materialization for the Qwen proving
ground: only assigned block state had to be materialized for an isolated block.
R6 extends that question to a materially different dense model and explicitly
forbids proving distribution by loading a complete model independently on every
participant and discarding most of it.

Those results and requirements concern **materialization**, however. They do not
yet make selective **network/storage acquisition** an architectural invariant.
A Node may still possess an entire copied model repository even when it only
materializes a small assigned subset.

That distinction matters because network bandwidth is a scarce fabric resource
and model repositories may be much larger than the state assigned to any one
Node. Whole-model replication also risks baking today's SCP/bootstrap behavior
into future planning, recovery, heterogeneous-device, and cache semantics.

The architecture therefore needs an explicit answer to a separate question:
what model bytes is a participant required to acquire in order to realize an
Execution Plan?

## Decision

InferSwarm adopts **plan-driven model artifact acquisition and distribution**.

Canonical invariant:

> **InferSwarm distributes required state, not model repositories. An Execution
> Plan determines the Logical State Units and explicitly shared/global state a
> participant requires; those requirements resolve to verifiable artifacts or
> source ranges from which the required Materializations can be created. Whole-
> model replication is optional backing/cache/replica/operator-preload behavior,
> never an implicit prerequisite for participation.**

The following rules are part of this decision.

### 1. Placement/state requirements drive acquisition

A Model Execution Strategy defines legal logical-state/execution decomposition.
The generic planner selects a feasible Execution Plan. That selected plan, plus
strategy-declared shared/global requirements, determines the immutable source
state each participant is required to obtain before or during realization.

A Node is not required to acquire unrelated model state merely because it is
present in the upstream model repository.

### 2. Source packaging does not define InferSwarm distribution granularity

Upstream repository/checkpoint packaging is an input format, not a planning
ontology. Hugging Face repository layout, safetensors shard boundaries, archive
files, or another provider's packaging must not silently become the unit of
placement or distribution.

InferSwarm may read only selected byte ranges from an upstream object where that
is correct and supported, or may ingest/transform upstream files into finer-
grained internal artifacts. Any transformation must retain sufficient
provenance and integrity information to establish the exact model/revision and
logical state represented.

### 3. Four boundaries remain distinct

The architecture must not conflate:

1. **upstream source-file boundaries** — how a publisher packaged a model;
2. **artifact/transfer-chunk boundaries** — how InferSwarm stores or moves
   immutable bytes efficiently;
3. **Logical State Unit / strategy boundaries** — model-semantic state identity
   and legal placement/decomposition;
4. **Materialization boundaries** — the physical representation resident on a
   Memory Resource for a plan/runtime role.

These boundaries may align in a convenient implementation, but alignment is not
an invariant.

### 4. Artifact possession is not residency

Possessing checkpoint/CAS/artifact bytes on local durable storage does not by
itself create active RAM/VRAM residency. Such bytes are backing/source or cache
state according to their declared role.

Residency continues to mean a plan-intended retained Materialization on a Memory
Resource. Bounded loading, conversion, and transfer remain staging.

### 5. Immutable artifact identity is verifiable

Immutable model artifacts used for correctness-bearing realization must have a
verifiable identity tied to exact bytes and provenance. Content addressing is
the preferred architectural model because it supports integrity verification,
deduplication, resumability, source discovery, and cache reuse, but this ADR
does not freeze a particular hash algorithm, manifest schema, CAS API, or wire
format.

A logical-state requirement may resolve to one or more immutable artifacts,
byte ranges, or transform inputs. The mapping must be deterministic and
auditable for a frozen model/revision/representation contract.

### 6. Any authorized valid Source may satisfy acquisition

A required immutable artifact may be acquired from any Source whose provenance,
integrity, authorization, representation, and freshness semantics make it
valid, including as applicable:

- the original model provider/repository;
- operator-managed durable storage;
- an InferSwarm artifact/cache store;
- another Node's verified cache;
- a deliberately retained replica;
- another future authorized source type.

A valid cache may therefore become a source for another participant.

### 7. Coordinator controls intent; bulk bytes need not transit the Coordinator

The Coordinator/planning authority determines or authorizes the required
artifact set for a frozen plan/realization scope and must be able to account for
which source/provenance satisfied it.

The Coordinator is not inherently a bulk data proxy. Nodes may fetch directly
from authorized origins or peers when the implementation can preserve the
required identity, authorization, accounting, and fail-closed behavior.

This preserves the accepted external-Coordinator architecture: a CPU-only
Coordinator need not acquire or relay model weights simply because it owns
planning/epoch/realization authority.

### 8. Peer-assisted distribution is allowed; BitTorrent is not the architecture

InferSwarm may use peer-assisted, chunked, resumable, multi-source transfer and
may allow Nodes to seed verified immutable artifacts to one another. Those are
useful torrent-like semantics for a bandwidth-constrained fabric.

This ADR does **not** select BitTorrent, DHTs, trackers, libtorrent, IPFS, a
specific CAS implementation, or any other transport/storage product. The Swarm
already has authenticated membership/control context; a future implementation
should use the minimum mechanism that satisfies the architectural contract.

### 9. Caches may outlive placement

A Node is required to possess only the artifacts needed to realize its current
assignment, but it may retain additional verified artifacts as optional cache
state until storage policy evicts them.

Cached artifact locality may later become planner evidence because it changes
materialization/reconfiguration cost. It must not be treated as a correctness
requirement unless explicitly promoted to a required replica/recovery role.

### 10. Recovery/replanning uses sources, not whole-model recopy assumptions

When a plan changes after resource addition, loss, or policy/evidence change,
new participants acquire only the source state necessary for the replacement
plan plus declared shared/global state. Existing valid local caches/replicas may
satisfy part or all of that need.

Recovery logic must not assume every Node already contains a complete model
repository, nor require broadcasting a complete model as the default recovery
operation.

### 11. Current whole-model SCP is research scaffolding

Existing scripts/manual procedures that download or SCP a complete model remain
legal research/bootstrap scaffolding until replaced. Their existence does not
establish a public interface, storage contract, planner prerequisite, or
production deployment requirement.

Implementations and tests must not introduce new generic planner/runtime
correctness assumptions that every compute Node has the full upstream model
repository available locally.

## Consequences

This decision adds a missing layer between planning and materialization:

```text
Execution Plan
      |
      v
required Logical State Units + shared/global state
      |
      v
artifact/source resolution
      |
      v
acquisition from authorized valid Source(s)
      |
      v
bounded staging / transform / packing
      |
      v
Materializations on plan-selected Memory Resources
      |
      v
backend-native execution
```

It also means artifact/source locality and acquisition cost may eventually be
planner evidence alongside compute, memory, path, transition, and workload
economics.

The first implementation does not need a full peer swarm. A minimal compliant
step may use one content-addressed local cache and one authorized source at a
time, provided a participant acquires only its required artifact set. Peer
advertisement, parallel chunk sourcing, resumable transfers, and locality-aware
planning may be added incrementally.

Artifact distribution must remain model-independent in the generic control
plane. Model-specific knowledge used to map logical state to checkpoint tensors,
ranges, or internal artifacts belongs in the Model Execution Strategy / model
adapter boundary.

## Interaction with R6

R6 remains a dense-model architecture falsification gate, not an artifact-
distribution implementation project.

R6 must continue to prove selective **materialization**: a participant may not
materialize a complete model merely to discard unassigned state. For R6,
however, an entire frozen checkpoint/repository may still exist on a Node's
local storage as temporary backing/source scaffolding, provided the retained
canonical plan obeys the R6 selective-materialization and accounting rules.

R6 therefore does **not** fail merely because selective network acquisition is
not yet implemented.

A successor evidence gate should separately prove selective **acquisition**:
for a frozen plan, a participant receives/retains only the required immutable
artifacts plus declared shared/global state, with integrity/provenance,
resumability/failure semantics, cache/source accounting, and no hidden
whole-model dependency.

## Hypotheses distinguished from decisions

This ADR decides the architectural contract above. It does **not** decide or
claim that:

- peer-assisted transfer is faster than a central artifact server on every
  topology;
- BitTorrent is an appropriate implementation;
- one chunk size or artifact granularity is optimal;
- SHA-256 or another specific hash is the final content identity;
- Hugging Face range requests are sufficient for every model/provider;
- upstream safetensors layout should be preserved internally;
- the Coordinator should host a durable artifact store;
- every cache should be advertised to every peer;
- artifact locality should outweigh execution/network economics in planning;
- R6 has already proven selective network acquisition;
- current SCP scripts must be removed before the successor proof exists.

Those remain implementation/evidence questions. The decision is only that
whole-model replication is optional and that acquisition must ultimately follow
plan-required state through verifiable authorized artifacts/sources.
