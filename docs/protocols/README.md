# Protocols and semantic execution boundaries

InferSwarm's final wire protocol does not exist yet and is **not invented
here**. These notes record constraints learned from experiments and the current
Fabric Doctrine so a future protocol is extracted from real strategy/runtime
requirements rather than frozen around one FreeToken/Qwen mechanism.

Canonical architecture:

- [ADR 0008](../adr/0008-canonical-fabric-doctrine.md)
- [Fabric Doctrine](../architecture/fabric-doctrine.md)

## Core rule

There is no universal InferSwarm model-work message.

> **Cross-resource execution boundaries carry strategy-specific semantic
> work/state. The generic planner understands their legality and normalized
> economics, not one universal payload schema.**

A routed sparse/MoE contribution boundary, a coarse hidden-state model-stage
boundary, and a future recurrent/dense boundary may therefore use different
payloads while participating in the same resource/planning architecture.

## Execution-plan epoch requirement

Any future correctness-bearing distributed protocol must preserve the semantic
ability to associate work/results/state transitions with the Execution Plan
epoch that authorized them.

After a replacement epoch becomes authoritative for a serving scope, late work
from a retired epoch cannot mutate current state or contribute to current
outputs.

This does not freeze an `epoch_id` field name or wire encoding; it is a
correctness requirement the eventual protocol must satisfy.

## State authority and recovery

Protocol/runtime design must make mutable-state authority unambiguous.

A transport-visible copy of bytes does not automatically become an authoritative
replica. If a plan claims failover/recovery, freshness/coherence and the covered
failure domain must be explicit under the strategy/state contract.

A resource loss may trigger a replacement plan that uses another path, Node,
GPU, CPU/RAM, or granularity. That is a new epoch, not a silent rewrite of the
old plan's resource identity.

## Common transport goals

Where a particular semantic boundary uses an explicit transport protocol, it
will generally benefit from being:

- **versioned** — incompatible semantics/configuration fail explicitly;
- **binary-friendly** — tensor/state payloads do not traverse hot-path JSON/text
  serialization unless a bounded control message genuinely warrants it;
- **persistent where economically useful** — avoid avoidable connection/process
  setup on repeated hot boundaries;
- **compact** — framing overhead should remain small relative to semantic work;
- **correctness-aware** — model/revision/strategy/representation state cannot
  silently drift into an incompatible execution path;
- **epoch-aware** — stale work cannot mutate the active plan scope;
- **transport-independent at the semantic layer where practical** — changing
  TCP/shared-memory/P2P/etc. must not silently change what the work means;
- **measurable** — payload bytes, frequency, latency, bandwidth, contention,
  staging, and end-to-end contribution can be captured with provenance.

These are design goals, not a frozen common header.

## Historical strategy example A — fine-grained resident sparse/MoE execution

Phase1R physically proved one same-host strategy in which selected routed work
was dispatched to resident remote expert execution and contributions were
returned for deterministic reconstruction/reduction.

Its semantic information included, as applicable:

- activation state;
- selected route/execution identities;
- weights/positions required for reconstruction;
- returned contributions.

D5/D6 showed that physical work and transport should scale with actual active
routes where the backend permits it, and that fixed/dummy work can be a real
performance tax.

These facts remain valuable strategy evidence. They do **not** define a
universal `ExpertRequest` or worker protocol.

## Historical strategy example B — coarse contiguous model blocks

[ADR 0007](../adr/0007-coarse-model-block-partitioning-as-first-network-strategy.md)
remains accepted as InferSwarm's first network strategy/evidence direction.

The historical coarse-block concept keeps one model region's weights and
block-local state resident and exchanges strategy-defined block-boundary state,
expected initially to include hidden-state/request-position information needed
by the downstream region.

ADR 0008/Fabric Doctrine clarifies the scope:

- coarse blocks remain a legitimate first network candidate;
- `inter-node = contiguous block` is **not** permanent architecture;
- the strategy defines legal boundaries and the planner chooses granularity
  from measured communication/state/execution/demand economics;
- intra-node and inter-node granularities may differ;
- a future network experiment must be derived from the current roadmap rather
  than reopening retired issues #32-#34 verbatim.

## 1 GbE baseline

ADR 0003 remains accepted:

> ordinary **1 Gigabit Ethernet** is the baseline network target; faster
> networking may improve performance but must not be required by architecture.

That is a network target, not a guarantee that every strategy boundary will be
useful over 1 GbE.

For any retained network experiment, measure rather than assume:

- semantic payload bytes;
- boundary frequency;
- latency/RTT for the actual payload/work pattern;
- sustained payload bandwidth;
- serialization/copy/staging cost;
- shared-path contention where material;
- node-local execution time;
- end-to-end service impact.

A coarse strategy may reduce round-trip frequency; a fine strategy may exploit
conditional demand or smaller residency units. #45 doctrine requires measuring
the global trade rather than canonizing either shape.

## Capability and strategy negotiation

The old issue #8 plan to freeze a universal worker/node capability contract was
retired by the resource/residency/planner Wayfinder. Do not revive it as a
protocol requirement.

A future protocol may need to negotiate enough information to establish a
specific Execution Plan/strategy implementation safely, for example:

- model/revision/strategy compatibility;
- backend/representation legality;
- relevant resource/capacity constraints;
- semantic boundary version;
- state/authority/recovery requirements;
- correctness/equivalence contract;
- transport/runtime compatibility.

The exact schema is intentionally deferred until doctrine-shaped local/network
experiments reveal the minimum real seam.

## Transport is subordinate to semantics

Possible substrates include:

- same-host staging/device copies;
- shared memory;
- backend/device IPC or P2P;
- ordinary TCP over Ethernet;
- RDMA-style/faster network transports where measurement justifies them;
- future transport mechanisms.

A transport optimization must not become a semantic requirement for every
strategy or resource type.

Same-backend local fusion may bypass an explicit message protocol entirely while
still realizing the same higher-level Execution Plan semantics.

## Anti-patterns

Avoid treating any of the following as universal architecture:

- HTTP/JSON tensor RPC on a latency-critical hot path;
- connection/process setup per repeated execution boundary when persistence is
  available and useful;
- one network request per expert merely because the first sparse strategy used
  experts;
- moving large immutable weights as normal per-token work when useful residency
  is possible;
- moving mutable state unnecessarily when it can remain with its legal owner;
- shared-process globals masquerading as an explicit distributed boundary;
- per-operation host orchestration that destroys backend-native fast execution;
- defining generic protocol fields around CUDA/NVFP4/Qwen-specific structures;
- assuming duplicate state implies coherent failover;
- accepting late retired-epoch results;
- inventing one physical `Worker` capability schema before the runtime seam is
  supported by evidence.

## Current roadmap relationship

The current first runtime gate is issue #48: accelerator residency without an
implicit persistent host mirror. Protocol/network implementation is downstream
of clean residency, frozen-plan realization, local heterogeneous/split
execution, and minimum automatic planning.

When network work resumes, ADR 0007 is the leading first candidate and ADR 0003
sets the 1 GbE baseline, but the exact semantic boundary/protocol must be
re-derived under the current Fabric Doctrine and measured topology.
