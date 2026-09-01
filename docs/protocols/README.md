# Protocols and semantic execution boundaries

InferSwarm's final wire protocol does not exist yet and is **not invented
here**. These notes record constraints learned from experiments and the current
Fabric Doctrine so a future protocol is extracted from real strategy/runtime
requirements rather than frozen around one FreeToken/Qwen mechanism.

Canonical architecture:

- [ADR 0008](../adr/0008-canonical-fabric-doctrine.md)
- [Fabric Doctrine](../architecture/fabric-doctrine.md)
- [ROADMAP](../../ROADMAP.md)

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
correctness requirement the eventual protocol must satisfy. R5B is the first
planned physical execution of these epoch/recovery semantics.

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

## Strategy example B — coarse contiguous model blocks

[ADR 0007](../adr/0007-coarse-model-block-partitioning-as-first-network-strategy.md)
remains accepted as InferSwarm's first network strategy/evidence direction.

R4 / issue #57 physically proved the first two-Node instance of this shape. The
accepted `[0,19) / [19,40)` Qwen split kept each region's model/runtime state
resident and exchanged two plane-major contiguous bf16 tensors (`hidden` and
`residual`) at the semantic block boundary.

The accepted R4 research transport used one persistent ordinary-TCP connection
with a bounded versioned frame and binary activation payload. That wire shape is
**evidence**, not a public protocol contract.

ADR 0008/Fabric Doctrine continues to define the scope:

- coarse blocks are a legitimate measured network strategy;
- `inter-node = contiguous block` is **not** permanent architecture;
- the strategy defines legal boundaries and the planner chooses granularity
  from measured communication/state/execution/demand economics;
- intra-node and inter-node granularities may differ;
- later strategies may expose different semantic payloads without changing the
  generic resource ontology.

## Accepted R4 transport evidence

R4 established these context-specific facts for the frozen candidate:

- physical Nodes: `inferswarm01` ↔ `inferswarm03`;
- ordinary TCP over mechanically verified negotiated 1 GbE full-duplex,
  MTU 1500, direct LAN;
- persistent connection reused across workload/session re-establishment;
- decode semantic payload: `8,192` bytes;
- max 64-row prefill semantic payload: `524,288` bytes;
- diagnostic boundary checksum equality on every checked transfer;
- clean serving-like arm excluded full-logit diagnostic transfer;
- no model-state materialization crossed the steady-state network boundary;
- fail-closed handling for protocol/session/length/layout/checksum/drift errors;
- backend-native resident execution remained active on both Nodes.

The temporary R4 header included enough identity/operation/layout/session
metadata to make the POC fail closed. Its names and encoding are not canonized.

## 1 GbE baseline

ADR 0003 remains accepted:

> ordinary **1 Gigabit Ethernet** is the baseline network target; faster
> networking may improve performance but must not be required by architecture.

R4 now provides the first accepted physical capacity evidence. Corrected
methodology measured actual clean-arm workload application demand rather than
mistaking socket-buffer timing or transport-microbenchmark capability for
demand.

For the exact R4 context:

- lower sustainable TCP direction: `933.9 Mb/s`;
- frozen 80% margin: `747.12 Mb/s`;
- peak clean-arm demand: about `2.947 Mb/s` A→B and `0.0769 Mb/s` B→A;
- retransmits: `0`;
- disposition: `R4_1GBE_PRIMITIVE_CAPACITY_VIABLE`.

That result means network **capacity** is comfortably sufficient for this exact
coarse semantic boundary. It does not guarantee acceptable latency or serving
economics for every strategy/model/concurrency level.

For retained network/serving experiments continue to measure rather than
assume:

- semantic and protocol bytes;
- boundary frequency/cadence;
- latency/RTT for the actual payload/work pattern;
- sustainable bandwidth and contention;
- serialization/copy/staging cost;
- node-local execution time;
- end-to-end service impact.

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

The exact schema remains deliberately unfrozen. R5A should reuse the smallest
proven research seams necessary for static serving without promoting the R4
wire frame into a product protocol.

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

R4 / #57 is complete. The physical network primitive is correct, resident,
measured, and explainable.

Issue [#59](https://github.com/Zutfen-LLC/inferswarm/issues/59) first establishes
a durable FreeToken integration line without rewriting the accepted evidence
lineage. Then [#60](https://github.com/Zutfen-LLC/inferswarm/issues/60) / R5A
must prove static end-to-end multi-Node serving through a normal host-runtime
request path and ingest applicable R4 measurements as planner evidence.

R5B subsequently exercises plan epochs, scale-up/down, and truthful failure
recovery. Neither R5A nor R5B should freeze a public universal wire protocol
unless the accumulated evidence actually identifies a stable seam.
