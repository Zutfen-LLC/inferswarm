# 0005. System RAM remains a first-class tier

Date: 2026-08-26
Status: Superseded by 0008

> **Current doctrine clarification (2026-08-31):** ADR 0008 supersedes this
> ADR's intrinsic tier, `primary`/`secondary`, expert-placement, and universal
> `FabricWorker` framing. The durable decision survives unchanged in substance:
> system RAM is a first-class Memory Resource, CPU execution is first-class
> compute, and a valid plan may prefer or require them rather than treating them
> as a deprecated fallback.

## Context

Once distributed GPU execution exists, the natural failure mode is treating
host RAM as a legacy fallback: "experts belong on GPUs now." That assumption
is wrong on the merits and destructive to the project's purpose.

Wrong on the merits: the
[feasibility investigation](../investigations/multi_gpu_moe_feasibility.md)
found that for large models the expert pool vastly exceeds aggregate VRAM of
consumer rigs, so host RAM remains the dominant capacity tier no matter how
secondary GPUs are used — and host RAM is often bigger and no slower to reach
than secondary GPUs hanging off narrow PCIe lanes. A GPU tier that *replaces*
RAM offload would make capacity worse, not better.

Destructive to the purpose: "1 GPU + RAM" is a legitimate InferSwarm
configuration (README, principle 4/6). Users with one GPU and a lot of RAM
are first-class participants, not a deprecated mode.

## Decision

System RAM / CPU execution remains a first-class execution tier, permanently.
Secondary GPUs must **augment** rather than replace host-memory offload.

Concretely:

- valid InferSwarm configurations include `1 GPU + RAM`, `2 GPUs + RAM`,
  `multiple machines + RAM`;
- an expert need not reside on a GPU merely because distributed GPU execution
  exists — placement is a measured decision, not a rank ordering where GPU
  beats RAM;
- mixed placement (some experts on primary GPU, some on secondary GPU(s),
  some in host RAM, in one run) is a hard architectural acceptance criterion
  (ROADMAP Phase 3), not a nice-to-have;
- the scheduling/placement layer must be able to reason about RAM as a
  capacity tier with its own measured bandwidth/latency profile, alongside
  GPU workers.

## Consequences

- Placement policy can and should choose RAM for experts where measurement
  says RAM wins — e.g. cold experts on models whose pool exceeds aggregate
  VRAM.
- RAM and CPU workers participate in the same capability abstraction as GPU
  workers (a `FabricWorker` with CPU execution capability and a RAM storage
  profile is a peer, not a fallback).
- The FreeToken integration inherits its existing host-RAM offload path as an
  asset: it is the baseline to beat *and* a permanent tier to integrate with,
  not a competitor to eliminate.

## Hypotheses distinguished from decisions

- **Decided:** RAM is first-class; mixed placement is an acceptance
  criterion; GPUs augment rather than replace.
- **Not decided:** the placement *policy* — which experts go where under what
  measured conditions. That is open research (ROADMAP Phases 2–3), informed
  but not settled by the investigation's estimates.
- **Not a claim:** that any mixed placement has run yet. Phase 3 is future
  work.
