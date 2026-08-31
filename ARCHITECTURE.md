# InferSwarm Architecture

```
Status: Research / Proof of Concept
```

InferSwarm is a **heterogeneous inference fabric**: a layer that turns
disparate compute and memory resources into one logical inference platform
without requiring the host engine to treat every device or machine as the same
kind of worker.

The architecture is evidence-driven. Concrete execution strategies are proven
first in the FreeToken integration fork; only then are stable concepts extracted
into InferSwarm. Accepted architecture decisions live under
[`docs/adr/`](docs/adr/README.md).

## Purpose

For a given model/workload and a set of contributed resources, InferSwarm must
eventually answer:

1. **where** state lives — weights, KV/recurrent state, activations, caches;
2. **where** computation executes;
3. **what execution granularity** is appropriate for each boundary;
4. **how** data moves between resources/nodes;
5. **how capabilities are measured** so placement decisions are based on
   evidence rather than device labels.

Model semantics, tokenization, serving APIs, and user-visible generation
behavior remain owned by the host inference engine.

## Current architectural shape

Conceptually:

```text
Inference Engine
      |
      v
Execution Adapter
      |
      v
InferSwarm execution/placement plan
      |
      +--------------------------+
      |                          |
      v                          v
Node-local resources        Remote node block
(GPU/RAM/etc.)              (persistent model block)
      |                          |
backend-native fast path    backend-native fast path
      |                          |
      +------------ semantic boundaries ------------+
```

The conceptual layers are not yet stable public interfaces. They exist to keep
experiments from defining the permanent API accidentally.

## Two execution granularities now supported by evidence/direction

### 1. Node-local fine-grained resource execution

The first proven strategy is distributed MoE expert execution within one
machine.

Conceptually for one MoE layer:

```text
router
  |
  +-- local selected experts
  +-- resident secondary-GPU experts
  +-- host-RAM/CPU tier where applicable
  |
  v
route reconstruction / reduction
```

Phase1R D1-D7 established several important facts:

- backend-native captured execution matters enormously on the first
  NVIDIA/FreeToken stack;
- a healthy-link resident secondary GPU can improve throughput;
- worker service cost depends materially on link topology and physical work;
- dummy expert execution and fixed transport are real costs;
- simply balancing logical routes or minimizing fan-in does not make a very
  slow link behave like a fast performance worker.

This makes local GPU/RAM placement a measured resource-planning problem, not a
rule that "more VRAM always means more speed."

A future planner may therefore distinguish resources that are
performance-positive, neutral/constrained, or capacity-only. Those categories
are descriptive research concepts today, not a frozen API.

### 2. Inter-node coarse model-block execution

[ADR 0007](docs/adr/0007-coarse-model-block-partitioning-as-first-network-strategy.md)
sets the first multi-machine strategy.

A remote machine is **not initially treated as a long-distance PCIe expert
worker**. Instead, it owns a contiguous block of model execution:

```text
Node A
  embedding / layers 0..N
  block-local KV/recurrent state
        |
        | hidden-state boundary
        v
Node B
  layers N+1..M
  block-local KV/recurrent state
        |
        | hidden-state boundary
        v
Node C / final block
```

Each node:

- loads only the state assigned to its block;
- keeps that block's persistent KV/recurrent state local;
- executes the block using its backend-native fast path;
- exchanges only the semantic state needed at the block boundary.

The first network baseline remains ordinary **1 Gigabit Ethernet** (ADR 0003).
Faster networking is an optimization/comparison, not a prerequisite baked into
the architecture.

The active evidence sequence is #31 through #34.

## Node-local composition

The two granularities are intended to compose eventually:

```text
Distributed InferSwarm

Node A
  model block A
  +-- local GPU coordinator
  +-- local secondary GPU(s)
  +-- local RAM/CPU tier
        |
        | Ethernet block boundary
        v
Node B
  model block B
  +-- local resources appropriate to that node
```

This composition is a direction, not yet a demonstrated runtime. The first
network POC deliberately keeps node-local behavior simple enough to isolate the
block/network boundary.

## State ownership

### Model weights

Placement assigns only the model state a node/resource needs. A node must not
require full-model host RAM merely because the checkpoint contains unrelated
layers. Selective loading is therefore a core distributed requirement, tracked
by issue #31.

### KV and recurrent state

State should live with the model block that consumes and updates it. Moving KV
state across the network every token would defeat the purpose of coarse
partitioning unless a specific model requires an explicit cross-block state
transfer.

### Activations

Activations are transient boundary state. Their representation and transport
are execution-strategy specific and are not yet a stable public protocol.

## Resource hierarchy

The earlier L0/L1/L2/L3 vocabulary remains useful **within a node**:

```text
L0 — primary/local accelerator resources
L1 — additional local accelerator resources
L2 — system RAM / CPU
L3 — future NVMe backing
```

A remote machine is better described as a **node containing its own resource
hierarchy**, not merely another L1 device. This avoids conflating PCIe-local
latency with network-node semantics.

System RAM remains first-class per ADR 0005. Secondary GPUs augment capacity;
they do not make RAM obsolete.

## Capability concept

A future capability model must represent measured behavior without hard-coding
one vendor, transport, or work unit.

Conceptually only:

```text
Node / FabricResource
├── StorageCapability
├── ExpertExecutionCapability
├── ModelBlockExecutionCapability
├── BackendExecutionCapability
└── ResourceProfile
```

Potential measured profile inputs already supported by evidence include:

- resident capacity;
- supported representations/backends;
- backend-native fast-path availability;
- PCIe generation/width/topology;
- H2D/D2H bandwidth and small-message latency;
- expert/branch service curves;
- network RTT/bandwidth;
- node RAM limits;
- block execution latency.

The exact fields/type names are deliberately **not frozen**. Issue #8 stays
deferred until the N-series adds real block/network requirements.

## Backend-independent execution

ADR 0006 remains authoritative: CUDA Graphs and NVFP4/Triton are first-backend
implementation choices, not InferSwarm semantics.

The generalized rule is:

> keep the hot path inside the fastest stable execution mechanism the backend
> provides, and keep cross-resource boundaries semantic rather than tied to a
> particular device API.

Examples:

- local NVIDIA expert workers may participate in CUDA-graph-compatible
  execution;
- another accelerator backend may use its own compiled/queued/persistent path;
- a network node may execute a locally captured model block and exchange hidden
  state only at block boundaries.

The semantic boundary is strategy-specific: routed work/contributions for the
expert strategy, block input/output state for the model-block strategy.

## Transport

Transport is subordinate to execution semantics.

Possible substrates include:

- same-host pinned staging/device copies;
- future CUDA/ROCm/XPU IPC or P2P mechanisms;
- shared memory;
- ordinary TCP over Ethernet;
- faster network transports when useful.

InferSwarm does not require one transport to serve every work unit. A
fine-grained local expert boundary and a coarse network block boundary may have
different transport needs while still belonging to one execution plan.

Protocol design notes live in [`docs/protocols/`](docs/protocols/README.md).

## Hardware heterogeneity

The intended backend direction remains:

```text
Backend implementations
├── CUDA / NVIDIA
├── ROCm / AMD
├── Intel XPU
└── CPU
```

The first experiments are NVIDIA-focused to isolate architecture mechanics.
Later AMD/Intel work should begin only after the boundary it is implementing is
stable enough that vendor bring-up is not confused with architecture debugging.

A weak or narrow-link GPU can still be useful as a capacity resource even when
it is not throughput-positive. That tradeoff should eventually be measured and
surfaced rather than hidden behind a binary "supported/unsupported" label.

## FreeToken relationship

The Zutfen FreeToken fork is the initial host/runtime integration used for
validation. Focused `poc/*` branches carry experimental implementation; this
repository carries canonical roadmap, evidence artifacts, and architecture
decisions.

The long-term goal remains a narrow integration seam, not a permanently deep
fork. See [`docs/integrations/freetoken.md`](docs/integrations/freetoken.md).

## Open questions

Current evidence questions, in order:

- Can a node selectively load only its assigned model block with bounded RAM?
  (#31)
- Can two model blocks separated by an explicit local boundary reproduce the
  unsplit model exactly? (#32)
- Can that boundary move across ordinary 1 GbE while preserving useful
  backend-native execution? (#33)
- What is the end-to-end two-node decode/prefill cost, and does 1 GbE remain a
  viable commodity baseline? (#34)
- If two-node evidence is positive, how should three-node placement and
  capability-aware block sizing work?
- When should a local accelerator be considered performance-positive versus
  capacity-only, and how should that measured distinction enter placement?
- What exact model-independent capability contract is justified after these
  POCs? (#8)
