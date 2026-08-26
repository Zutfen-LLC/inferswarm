# InferSwarm Architecture

```
Status: Research / Proof of Concept — this document records direction and
open questions, not settled design.
```

InferSwarm is a **heterogeneous inference fabric**: a layer that turns
disparate compute resources — GPUs of different vendors and generations,
CPUs, system RAM, and eventually storage — into one logical inference
platform that a host engine can use without caring where each piece of work
actually runs.

This is an initial architecture document. Several questions are called out
as unresolved deliberately; they will be settled by the roadmap's
proof-of-concept phases and recorded as ADRs in
[docs/adr/](docs/adr/README.md), not decided by fiat here.

## Purpose

The fabric's job is to answer, for a given inference workload and a set of
contributed resources:

1. **where** each piece of state (weights, activations, KV cache) should live;
2. **where** each piece of computation should execute;
3. **how** data moves between those places;
4. **how all of the above is measured**, so that (1) and (2) are decisions
   based on evidence rather than assumptions about hardware.

Everything else — model semantics, tokenization, serving API — belongs to the
host inference engine. InferSwarm deliberately does not own those.

## Architectural layers

Conceptual layering:

```
Inference Engine
      │
      ▼
Execution Adapter          ← narrow seam; engine-specific, thin
      │
      ▼
InferSwarm Planner / Scheduler
      │
      ▼
Transport / Worker Interface
      │
      ├── same-machine GPU
      ├── network worker
      ├── CPU/RAM
      └── future storage tier
```

- **Inference Engine** — the host runtime that owns model semantics and the
  serving surface. Today: FreeToken (see
  [FreeToken relationship](#freetoken-relationship)). Tomorrow: potentially
  others.
- **Execution Adapter** — the narrow, engine-specific glue that exposes the
  fabric to one host engine. This is the seam that keeps host-engine changes
  and fabric changes from entangling (principle 10 in the
  [README](README.md)).
- **Planner / Scheduler** — decides placement and dispatch based on worker
  capabilities and measured profiles. Unbuilt; its contract will be
  formalized only to the extent the POCs actually require (ROADMAP Phase 5).
- **Transport / Worker Interface** — talks to workers, whether they are
  another GPU in the same machine, a process exposing system RAM, or a remote
  node over ordinary Ethernet. Protocol direction:
  [docs/protocols/](docs/protocols/README.md).

These layers are conceptual. The first POCs will not implement them as
separate components; they exist so that experimental code grown inside the
FreeToken fork has a target shape to converge toward.

## Resource hierarchy

A vocabulary for talking about resource tiers:

```
L0 — primary/local accelerator resources
L1 — secondary accelerator resources
L2 — system RAM / CPU
L3 — future NVMe backing
```

L0 is the accelerator the host engine would use on its own (e.g. the one GPU
in a single-GPU machine). L1 adds further accelerators — a second GPU in the
same machine, or a GPU in another machine. L2 is host memory and CPU, which
remain full citizens (principle 4 in the [README](README.md)), not a fallback
that exists only until something better arrives. L3 is future NVMe-backed
capacity, expected to serve as a backing tier rather than a latency-critical
hot execution tier.

This is a **conceptual hierarchy for describing resources, not a strict cache
hierarchy**. The scheduler may execute work where data already resides rather
than promoting everything toward L0 — that is the entire point of resident
remote execution. Nothing here dictates a fixed promotion path.

## Worker concept

A worker should eventually expose **capabilities, not vendor identity**.
Conceptual shape only — these types do not exist yet and are not implemented
in this repository:

```
FabricWorker
├── ExpertExecutionCapability      ← can execute MoE experts (formats, latency)
├── LayerStageCapability            ← can execute a dense layer/stage
├── StorageCapability               ← can hold state (VRAM/RAM/future NVMe)
└── ResourceProfile                 ← measured capabilities (principle 8)
```

The naming is deliberately model-independent (`FabricWorker`,
`WorkerCapability`, `ExecutionPlan`, `ResourceProfile`). MoE is the first
execution strategy, not the definition of the platform — an MoE-specific
executor can exist *underneath* the capability abstraction, but the
abstraction itself must not assume every worker is an "expert worker"
(principle 9). Exactly how much of this contract the first POCs need is an
open question, deliberately deferred until the POCs reveal requirements
(ROADMAP Phase 5, issue "Define model-independent worker capability
contract").

## MoE execution concept

The first execution strategy: distributed expert execution. Conceptual flow
for one MoE layer:

```
router
  │
  ├── local selected experts        (L0)
  │
  ├── remote selected experts       (L1: same-machine or network GPU)
  │
  └── RAM/CPU fallback              (L2)
  │
  ▼
combine
```

The core protocol-level rule: a remote worker should receive **one activation
payload plus all selected expert IDs / routing information relevant to that
worker**, execute and accumulate locally, and return the smallest practical
combined result. Consequences:

- one network round trip per worker per layer (batched by destination), not
  one request per expert;
- per-expert fan-out is the worker's local problem, hidden behind the
  dispatch boundary;
- the combine step receives few, already-reduced results.

This is spelled out further in [docs/protocols/](docs/protocols/README.md).
The scheduling question — which experts live where, given measured routing
behavior and device capabilities — is open, and the first inputs are being
collected in ROADMAP Phases 0–3.

Note also: resident expert *coverage* (which experts are resident where) and
cache *hit rate* (which experts actually get selected) are different
quantities. Coverage is a placement decision; hit rate depends on the model's
real routing distribution and must be measured, not assumed (see
[docs/investigations/](docs/investigations/)).

## Dense model future direction

For dense models, per-expert dispatch does not apply. The plausible direction
is coarse layer/pipeline partitioning across workers, or replica placement
for small models. This is recorded as a future direction only — no
implementation commitment, no design yet. The lesson carried forward from the
MoE work: pick the granularity at which the payload-to-work ratio favors
moving small things and keeping big things resident.

## Heterogeneous hardware future direction

Intended backend shape:

```
Worker Backend
├── CUDA
├── ROCm
├── Intel XPU
└── CPU
```

CUDA is first because the initial POC hardware is NVIDIA. Worker support for
a vendor does not imply that vendor's hardware must be able to serve as the
primary model runtime — a weak or unusual device can still be a useful
contributing worker. ROCm and XPU backends are investigations (ROADMAP
Phase 6), not current work; nothing in the architecture should hard-code
NVIDIA, CUDA, or multi-GPU assumptions into the fabric itself.

## FreeToken relationship

FreeToken (specifically the [Zutfen-LLC fork](https://github.com/Zutfen-LLC/FreeToken))
is the **initial host/runtime integration used for validation**. It is where
the first POC implementation work happens, because it already has the MoE
offload machinery, model support, and measurement tooling the early phases
need.

It is not necessarily InferSwarm's permanent, exclusive runtime dependency.
The long-term intent is that distributed-execution functionality proven in
the fork is extracted into this repository behind the narrow execution seam
(ROADMAP Phase 5), so that InferSwarm's runtime components become cleanly
separable and the fork does not have to remain deeply divergent from
upstream FreeToken.

Branch policy, and how issues/PRs flow between the two repositories:
[docs/integrations/freetoken.md](docs/integrations/freetoken.md).

## Open questions

Deliberately unresolved, to be answered by experiment and recorded as ADRs:

- Is resident remote expert execution actually faster than host-RAM offload
  on target hardware, end-to-end? (ROADMAP Phase 1)
- Does 1 GbE networking sustain useful inference participation, and is its
  limiting factor latency/synchronization or bandwidth? (Phase 4)
- What subset of the `FabricWorker` capability contract do the POCs actually
  need? (Phase 5)
- How should expert placement weigh routing locality, capacity, and measured
  per-device latency? (Phases 2–3)
- Where exactly is the boundary between the open-source fabric and future
  commercial management tooling? (Principle 7 governs the direction; exact
  boundary TBD.)
