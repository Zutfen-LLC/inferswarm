# Protocols

Design notes for InferSwarm execution boundaries and transport. **The final wire
protocol does not exist yet and is not invented here.** These notes record
constraints learned from experiments so the protocol is extracted from evidence
rather than from one FreeToken implementation.

## Common design goals

Any eventual node/worker protocol should be:

- **versioned** — explicit compatibility/version refusal;
- **binary-friendly** — tensors/state are not serialized through per-request
  JSON/text paths;
- **persistent** — connections/execution contexts are established once and
  reused;
- **compact** — framing overhead should remain small relative to semantic
  payloads;
- **correctness-aware** — model/block/representation identities and checksums
  prevent silent configuration drift;
- **capability-aware** — a participant advertises what it can legally execute
  and the measured resources relevant to placement;
- **transport-independent at the semantic layer where practical** — transport
  choices should not redefine the meaning of the work being executed.

The important correction from early design notes is that InferSwarm now has
more than one plausible **work-unit granularity**. Do not force all execution
strategies into one request shape.

## Work unit A — local / fine-grained MoE expert execution

This is the first physically proven execution strategy from Phase1R.

For a local resident expert worker, the semantic unit is routed work for one
MoE layer:

- activation state;
- selected expert/slot IDs relevant to that worker;
- route weights / original positions as required;
- route contributions returned for deterministic reconstruction/reduction.

The key rule remains:

> batch all work for a destination rather than making one request per expert.

D5/D6 further showed that physical work and transport should scale with active
routes where the backend permits it.

This work unit is appropriate for same-host fast transports and may be revisited
on sufficiently fast networks later. It is **not** the first multi-machine wire
protocol.

## Work unit B — coarse model-block execution

[ADR 0007](../adr/0007-coarse-model-block-partitioning-as-first-network-strategy.md)
sets the first network strategy.

A node owns a contiguous model block and persistent block-local state. The
cross-node work unit is therefore conceptually:

### Request

- block/session identity;
- hidden-state input tensor;
- sequence/request position metadata required by that block;
- only model-specific boundary state that cannot remain resident with the
  owning block.

### Node-local execution

- execute the assigned block through the backend-native fast path;
- update block-local KV/recurrent state in place;
- do not involve the network inside every layer of that block.

### Response / forward handoff

- output hidden state for the next block;
- minimal status/correctness metadata;
- final block may return token/logit state appropriate to the host runtime.

The exact fields, dtype/layout, ownership rules, and framing remain experimental
until issues #31-#34 establish them.

## State ownership is part of the protocol contract

For coarse nodes, the protocol must make clear what state is **resident** and
what state crosses a boundary.

Expected first rule:

- weights stay with their assigned block;
- KV/recurrent state stays with the block that consumes/updates it;
- hidden activations cross between blocks;
- control/version/session metadata crosses explicitly.

A protocol that silently depends on shared process globals is not a valid
multi-machine prototype.

## 1 GbE constraint

ADR 0003 remains authoritative:

> ordinary 1 Gigabit Ethernet is the baseline network target; faster networking
> may improve performance but must not be required by design.

The earlier fine-grained expert-RPC plan made per-dispatch latency a likely
major risk. Coarse model-block execution changes the experiment: network
boundaries happen a small number of times per token rather than once per remote
worker on every MoE layer.

Issues #33 and #34 must therefore measure, rather than assume:

- exact decode boundary payload bytes;
- prefill boundary payload bytes;
- message latency/RTT for those shapes;
- serialization/copy overhead;
- end-to-end throughput impact at 1 GbE;
- optional 10 GbE comparison if available.

## Capability negotiation

The eventual protocol will need capability/version negotiation, but issue #8
remains deliberately deferred. The N-series should collect the real fields
needed for:

- selective block loading;
- backend-native block execution;
- memory capacity;
- network transport;
- model/block identity;
- correctness/state compatibility.

Do not freeze a generalized schema before those experiments exist.

## Anti-patterns

Avoid:

- HTTP/JSON tensor RPC on the hot path;
- connection setup per token/block;
- one network request per expert;
- sending full model weights as part of normal token execution;
- moving block-local KV state unnecessarily;
- per-layer host orchestration that destroys the node's backend-native fast
  execution;
- defining the generic InferSwarm protocol in terms of CUDA/NVFP4 structures.

## Room to grow

The eventual architecture must leave room for:

- same-host expert/resource execution;
- coarse network nodes;
- RAM/CPU tiers;
- AMD/Intel backends;
- future replicas or storage-backed strategies;
- faster transports such as shared memory, P2P, RDMA, or other mechanisms when
  measurement justifies them.

Those strategies may share session/capability framing while using different
semantic work-unit payloads.
