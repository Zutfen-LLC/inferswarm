# InferSwarm Roadmap

This roadmap tracks validation work, not feature shipping. Each phase exists
to answer a question; the question is stated, the hardware and model are
named, and the exit criteria are measurable. Later phases depend on earlier
results — if a phase fails its criteria, we change the plan rather than the
numbers.

A core rule for every phase: results follow the
[BENCHMARKING.md](BENCHMARKING.md) contract. No phase is "done" on a
microbenchmark alone.

## Phase 0 — Baseline and instrumentation

Establish the ground truth everything else will be compared against.

- [ ] Establish deterministic benchmark methodology (fixed seeds, fixed
      prompts/workloads, fixed measurement protocol, warmup rules).
- [ ] Profile one RTX 3060: memory bandwidth, PCIe link width/speed, single-
      expert execution latency at the relevant weight formats.
- [ ] Measure existing FreeToken host-RAM/offload behavior on that GPU as the
      baseline configuration.
- [ ] Capture real MoE routing behavior (expert selection traces) for
      representative workloads.
- [ ] Establish a correctness reference: recorded outputs from a known-good
      non-distributed configuration to compare against.

**Exit criteria:** reproducible baseline numbers for one 3060 with recorded
provenance, plus routing traces. No distributed code yet.

## Phase 1 — Two-GPU local POC

Hardware:

```
2× RTX 3060 12GB
```

Model:

```
Qwen3.6-35B-A3B
```

Why this model for the POC:

- already supported by FreeToken (no model-porting work blocking the
  experiment);
- its expert set (~16.9 GB at FreeToken's compact formats, per the
  [feasibility investigation](docs/investigations/multi_gpu_moe_feasibility.md))
  is larger than one 12 GB card's practical expert capacity, so a second GPU
  has real work to hold;
- the expert set is plausibly distributable across two 12 GB cards (Phase
  0/1 will establish the practical expert capacity after runtime and
  non-expert allocations), so the experiment is controlled rather than
  capacity-starved;
- on larger cards (e.g. a 24 GB RTX 3090) the same expert set should fit
  entirely, which gives us a built-in control case for sanity-checking.

Goal:

> Demonstrate resident expert execution on a second GPU and compare it
> against existing RAM offload.

**Exit criteria:** end-to-end decode/prefill comparison (second-GPU resident
experts vs. host-RAM offload baseline from Phase 0) with correctness checks
against the non-distributed reference. Implementation happens primarily in
the [FreeToken fork](docs/integrations/freetoken.md).

## Phase 2 — Three-GPU scaling

Hardware:

```
3× RTX 3060 12GB
```

Goal:

- test fan-out (dispatch to multiple secondary devices per layer);
- test per-GPU batching (multiple selected experts executed per dispatch);
- test whether performance scales with device count, and if it does not,
  measure the actual cause — synchronization is one candidate among several,
  not a presupposed answer.

**Exit criteria:** one-/two-/three-GPU comparison at identical workloads;
cause(s) of any scaling bend identified with evidence; synchronization
overhead quantified separately.

## Phase 3 — Mixed GPU + RAM placement

Demonstrate, in one inference run:

```
some experts → primary GPU
some experts → secondary GPU(s)
some experts → host RAM / existing FreeToken path
```

This is a **hard architectural acceptance criterion**: tiers must
participate together, not as alternative modes. System RAM remains a
first-class tier (design principle 4) — secondary GPUs augment, not replace,
host-memory offload.

**Exit criteria:** a single run with all three tiers active, verified by
placement accounting, with end-to-end numbers and correctness checks.

## Phase 4 — 1 GbE POC

Move one worker to another physical machine.

Baseline network:

```
ordinary 1 Gigabit Ethernet
```

No exotic networking requirement — the architecture targets commodity
networking (design principle 2).

Measure:

- activation dispatch latency;
- complete MoE-layer latency (dispatch → per-device selected-expert execution
  → combine);
- decode tokens/sec;
- prefill separately from decode;
- impact of 1 / 2.5 / 5 / 10 GbE links if hardware permits;
- latency sensitivity independently of bandwidth (e.g. artificial delay at
  constant payload size).

**Exit criteria:** an evidence-backed answer to "is 1 GbE viable, and is the
limiting factor latency/synchronization or bandwidth?" — with the
expectation, tested rather than assumed, that once activation payloads are
small, viability depends primarily on latency/synchronization behavior.

## Phase 5 — Generalized worker abstraction

Only after the preceding POCs justify it:

- extract the proven execution seam from the FreeToken fork;
- introduce stable worker/resource abstractions (only what the experiments
  actually required — see the open capability-contract issue);
- move reusable InferSwarm runtime code into this repository.

**Exit criteria:** distributed-execution functionality lives in
`Zutfen-LLC/inferswarm`, the fork's divergence shrinks, and the seam is thin
enough to describe in one page.

## Phase 6 — Heterogeneous vendor workers

Investigate:

- AMD ROCm expert worker;
- Intel XPU expert worker;
- CPU worker improvements.

Worker support need not imply that the hardware can serve as the primary
model runtime — a contributing worker is valuable on its own
([ARCHITECTURE.md](ARCHITECTURE.md#heterogeneous-hardware-future-direction)).

**Exit criteria:** at least one non-NVIDIA worker executing experts correctly
with measured performance, and a decision on backend interface shape.

## Phase 7 — Larger-model validation

Use models that genuinely exceed individual GPU capacity, where multi-device
capacity is not optional. Potential cases (per the
[feasibility investigation](docs/investigations/multi_gpu_moe_feasibility.md)):

- DeepSeek-V4-Flash — already supported by FreeToken; expert pool (~137 GB)
  far exceeds aggregate VRAM of the POC rig, so partial-coverage effects
  dominate;
- Ling-3.0-flash — compelling aggregate-capacity fit, *if/when runtime model
  support exists* (its architecture is not implemented in FreeToken today;
  this is a separate, prior workstream);
- other large sparse MoE models.

**Exit criteria:** measured end-to-end results on at least one
capacity-constrained model, with the fabric's benefit stated honestly
relative to host-RAM offload on the same hardware.

## Later / exploratory

Exploratory only — no schedule, no commitment, revisited after Phase 7:

- dense-model pipeline execution;
- elastic GPU borrowing (partial/idle-capacity contribution);
- NVMe backing tier;
- multi-site execution;
- automatic expert replication;
- routing-aware placement;
- commercial control-plane integration.

## Issue tracking

Each phase's near-term work is tracked as issues in this repository.
InferSwarm issues are canonical; implementation PRs land in the FreeToken
fork and link back (see [docs/integrations/freetoken.md](docs/integrations/freetoken.md)).
