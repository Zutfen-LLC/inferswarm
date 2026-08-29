# Phase-1 POC success criteria

```
Status: Decision document. Written before Phase 0 baselines exist and before
any Phase-1 result exists. Nothing here claims a measurement.
```

> **Canonical placement amendment (2026-08-28).** Before any canonical
> Phase-1 candidate output or performance was observed, the v1 zero-overlap
> geometry was found incompatible with the unchanged per-class F2 floor.
> The canonical pre-performance candidate is now
> `phase1-qwen36-placement-v2` / `coverage_constrained_complement_5442`,
> SHA-256
> `2f62bb84df40d4cc5649e940a39cb53d2975eadecbc320fb97d2b037d4e005f4`.
> The deterministic P0-I-only correction is recorded in
> [`phase1-placement-methodology-correction-v2.md`](implementation/phase1-placement-methodology-correction-v2.md).
> F2 remains ≥20% independently in W1, W2, W3, and W4; no gate, workload,
> tolerance, or performance rule in this document changed.

> **Canonical campaign-order amendment (2026-08-29).** Before any canonical
> Phase-1 candidate performance existed, §10's repetition-level `A/B/A/B…`
> interleaving was found physically impossible to execute on the canonical
> rig without destroying the warmed serving state it exists to measure: both
> arms require exclusive use of the same physical GPU 0. §10's executable
> ordering is now two **counterbalanced arm-major sessions** (Session 1
> baseline→candidate from a fresh thermal reset; Session 2
> candidate→baseline from an independent thermal reset; `W1 → W2 → W3 → W4`
> within every arm; one fresh server process per arm per session; no radix
> cache clearing between classes). The §8.7 optional repetition pairing is
> structurally unavailable under this ordering and the already-permitted
> unpaired path applies. The amendment is recorded in
> [`phase1-campaign-order-amendment.md`](benchmarks/phase1-campaign-order-amendment.md).
> No threshold, statistic, workload, gate, baseline identity, placement, or
> candidate configuration changed.

Canonical for [ROADMAP.md](../ROADMAP.md) Phase 1 and for InferSwarm issue #1.
Subordinate to the [benchmark contract](../BENCHMARKING.md), which governs
labels, provenance, and the microbenchmark rule everywhere in this project.

This document fixes **how the first distributed-execution experiment will be
judged**, so that the judgement cannot be invented after the numbers arrive.
It is written to be applied *mechanically*: a reviewer holding the Phase-1
result directory and this document should reach the same verdict the author
did, without further negotiation.

Absolute values that genuinely cannot exist before Phase 0 (baseline
tokens/sec, baseline TTFT, VRAM splits) are expressed here as **ratios,
bands, and rules**. No decision rule in this document is deferred.

**Changing this document after Phase-1 measurement has begun requires a new
PR that states what changed, why, and what the verdict would have been under
the previous rules.** That record is not optional; it is the anti-goalpost
mechanism.

---

## 1. The hypothesis under test

> **H1.** For a MoE model whose routed-expert set exceeds the practical
> expert capacity of one RTX 3060 12 GB, keeping a subset of experts
> **resident on a second RTX 3060 and executing them there** improves
> end-to-end interactive inference relative to the best existing single-RTX
> 3060 + host-RAM FreeToken execution path, on the same host, model, and
> workload.

Model: `Qwen3.6-35B-A3B`. Rig: `2x RTX 3060 12GB`, same machine, PCIe only.
Checkpoint and weight format are pinned in §1.1.

### What H1 does not assert

Phase 1 tests exactly one mechanism. It does **not** test, and a Phase-1 GO
does **not** support, any of:

| Not under test | Where it is actually decided |
|---|---|
| Execution over a network | ROADMAP Phase 4 / [ADR 0003](adr/0003-1gbe-baseline-network-target.md) |
| 1 GbE viability | ROADMAP Phase 4 — untested as of this document |
| AMD ROCm / Intel XPU workers | ROADMAP Phase 6 |
| Dense-model pipeline execution | Later/exploratory |
| Generalized InferSwarm architecture | ROADMAP Phase 5 |
| Scaling beyond two devices | ROADMAP Phase 2 |
| Mixed GPU + GPU + RAM placement in one run | ROADMAP Phase 3 |
| Larger models / capacity-constrained regimes | ROADMAP Phase 7 |
| Other weight precisions (Q6/Q8/FP8/BF16) | §1.1 — a separate future format-scaling experiment |

Two further distinctions that the criteria below enforce with hard gates:

- **All experts need not fit in VRAM.** Host RAM stays a first-class tier
  ([ADR 0005](adr/0005-ram-remains-first-class-tier.md)). The candidate is
  allowed — expected — to keep some experts in host RAM.
- **This tests remote *execution*, not remote *storage*.** A candidate that
  parks weights on GPU 1 and streams them to GPU 0 per invocation is a
  different architecture (the feasibility investigation's "Architecture A"),
  and gate **F5** below fails it.

### 1.1 Phase-1 checkpoint, and why the format is not the architecture

FreeToken supports several `Qwen3.6-35B-A3B` checkpoints and weight formats.
Every mechanic this document depends on — NVFP4 expert banks, the
Marlin/Triton backend choice, the `MARLIN_MAX_CACHE_SIZE = 992` slot cap, the
`rtol/atol = 2e-3` backend-vs-backend tolerance (§5), the ~16.9 GB compact
expert-pool arithmetic (§13) — is a property of **one** of them. Naming the
model family without naming the checkpoint would leave the document's own
constants unanchored.

```
Checkpoint:   nvidia/Qwen3.6-35B-A3B-NVFP4
Revision:     MUST be pinned to an exact upstream revision (commit SHA)
              before the first Phase-0 run.
```

The revision is **not chosen in this document** — the pin is a Phase-0
prerequisite, not a decision rule, and inventing a SHA now would be a
fabricated provenance record. The binding rule is:

> No Phase-0 measurement may begin until the exact upstream revision of
> `nvidia/Qwen3.6-35B-A3B-NVFP4` is recorded in the result directory. Both
> arms run that same pinned revision (§2.3, §3 rule 4). A revision change
> re-runs Phase 0 *and* the candidate, per §2.2.

#### NVFP4 is the Phase-1 POC format, not an InferSwarm constraint

> **NVFP4 is the controlled Phase-1 POC format. It is not an InferSwarm
> architectural constraint, and nothing in this document may be read as
> making Q4-class weights the preferred or permanent InferSwarm format.**

InferSwarm's architecture is intended to pool heterogeneous inference
resources **regardless of the model weight precision the operator chooses**.
It must remain capable in principle of distributing experts and other model
components at any precision the underlying model and worker backend support —
Q6-class, Q8-class, FP8, BF16/FP16, and future formats added by worker or
runtime backends.

This is not a new commitment; it is what the existing resource abstraction
already says. [ARCHITECTURE.md](../ARCHITECTURE.md)'s worker contract is
capability-shaped rather than format-shaped — `ExpertExecutionCapability` is
defined as *"can execute MoE experts (formats, latency)"*, plural, and
`StorageCapability` as *"can hold state"*, byte-denominated — and
[ADR 0004](adr/0004-moe-as-first-execution-strategy.md) keeps the abstraction
independent of the first target's specifics. Accordingly a higher precision
is treated as:

- **larger resident byte requirements** per expert, so fewer experts fit per
  device and placement changes;
- **different execution capability and performance** per device;
- **possibly different kernels** on the execution path;

and **not** as a fundamentally different distributed architecture. Dispatch
shape, placement, residency accounting, and the remote-execution boundary are
unchanged by the number of bits in a weight.

Concretely, all three of these are conceptually valid InferSwarm workloads
wherever the model/worker backend supports the representation:

| | Hardware | Operator's choice | What they are buying |
|---|---|---|---|
| **User A** | 2x 12 GB GPUs | NVFP4 / Q4-class | maximum model capacity on small cards |
| **User B** | 2x 24 GB GPUs | Q6 / Q8-class | fidelity, traded against capacity |
| **User C** | larger accelerator fleet | FP8 or BF16 experts | fidelity at fleet scale |

A user with multiple large GPUs may deliberately prefer a larger
quantization for higher model fidelity rather than Q4-class weights, and that
is a first-class InferSwarm case, not a degenerate one.

**Phase 1 nevertheless runs NVFP4 only**, because a single fixed format keeps
the experiment controlled: §3 requires both arms to hold weight format
constant, and sweeping precisions would confound the one variable Phase 1
exists to isolate. This document therefore does **not** expand the Phase-1
benchmark campaign to multiple quantizations, and a Phase-1 verdict says
nothing about any other format.

**Future validation (not Phase 1).** Format and precision scaling —
whether distributed expert execution behaves the same at Q6/Q8/FP8/BF16, and
how placement responds to larger resident expert bytes — is its own
experiment with its own criteria, to be run separately once the mechanism
itself has a verdict. §16 does not authorize any cross-format claim from
Phase 1.

---

## 2. Baselines and references

Phase 1 needs two different non-distributed configurations, and conflating
them is a methodological error in both directions. They are named explicitly,
and the names are used throughout this document:

| Term | Role | Chosen how |
|---|---|---|
| **`CANONICAL_PERFORMANCE_BASELINE`** | What InferSwarm must actually beat. Every performance ratio, bound, threshold and verdict in §6, §7, §10, §11 and §15 is computed against it | **The measured winner** of the B1–B5 sweep (§2.2), subject only to being a valid, working FreeToken configuration (§5.5) |
| **`CORRECTNESS_REFERENCE`** | What the distributed candidate must compute **the same result as**. C1, C2, C3 and C5 compare against it (§5) | **Fixed and declared** before Phase 0 (§2.4). Never selected by speed, never a performance comparator |

The performance baseline is not the candidate's numeric correctness target,
and the correctness reference is not a performance claim about anything. The
two roles were previously carried by one word, which is wrong on this rig: the
sweep winner may legitimately be a configuration that computes experts on the
CPU, in different kernels and a different accumulation order, while the
candidate's remote experts are GPU-resident NVFP4 (§5.1).

`CANONICAL_PERFORMANCE_BASELINE` is not "whatever single-GPU configuration we
happened to run". It is **the strongest legitimate FreeToken single-GPU
configuration for this hardware, model, and workload**, chosen by measurement
before the candidate is benchmarked.

### 2.1 Baseline sweep (Phase 0, issue #2)

All runs on **one** RTX 3060 — specifically the same physical card the
candidate later uses as GPU 0 (`ft serve --gpu <uuid>`), with the second card
either absent or unused.

| Id | Configuration (as passed, not as defaulted) |
|---|---|
| **B1** | `--moe-backend offload --moe-cache-auto --nvfp4-backend auto` |
| **B2** | `--moe-backend hybrid --moe-cache-auto --nvfp4-backend triton`, after a fresh `ft bench bw` profile for this GPU + expert format |
| **B3** | `--moe-backend auto --moe-cache-auto --nvfp4-backend auto` — record which MoE backend it resolves to; must coincide with B1 or B2 |
| **B4** | `--moe-backend offload --moe-cache-auto --nvfp4-backend triton` |
| **B5** | `--moe-backend cpu --moe-cache-auto --nvfp4-backend triton` |

**Every row states `--nvfp4-backend` explicitly, because the default is not
`auto`.** `EngineConfig.nvfp4_backend` defaults to `"triton"`
(`python/freetoken/engine/config.py:25`, mirrored in
`python/freetoken/models/config.py:226`; the flag is declared at
`python/freetoken/server/args.py:476-485`). A table row that only said "NVFP4
backend auto" in prose would run **Triton** unless the flag was actually
passed — silently duplicating B4 and leaving the hardware-selected path
unmeasured. `--moe-cache-auto` is written out for the same reason: it is
applied by the CLI when no sizing flag is given
(`python/freetoken/server/args.py:665-678`), not by the dataclass default
(`config.py:33`). A baseline must be reproducible from explicit configuration,
never inferred from a default that may change.

What the values mean here, from source:

- **`auto`** resolves through `select_nvfp4_backend`
  (`python/freetoken/moe/nvfp4_backends.py:183-265`): `marlin` on sm_80–99
  **when vLLM is importable and its Marlin donor symbols are usable**,
  flashinfer `b12x` on sm_120+, otherwise `triton`. On the sm_86 RTX 3060 it
  is `marlin` **if and only if** those donor symbols are usable in the actual
  environment.
- **`triton`** forces the portable native-layout inline-dequant kernels
  (first branch of the same function).
- The flag reaches the expert path through the bank loader
  (`python/freetoken/moe/expert_banks.py:179-215`), the runtime's only caller
  of `select_nvfp4_backend`.

**Where the flag is inert, recorded accurately rather than implied to
matter.** The engine loads expert banks with `decode_target="cpu"` for **both**
`--moe-backend cpu` and `--moe-backend hybrid`
(`python/freetoken/engine/engine.py:582`), and `_nvfp4_banks` then keeps the
native ModelOpt layout and never calls `select_nvfp4_backend` at all
(`expert_banks.py:179-207`). So in **B2** and **B5**:

- the NVFP4 expert kernels are the native-layout Triton ones — `quant_format
  == "nvfp4"` dispatching to `fused_experts_nvfp4` (prefill) and
  `fused_experts_decode_nvfp4_marlin` (decode) in
  `python/freetoken/layers/moe.py:433-505` — whatever `--nvfp4-backend` says;
- this is not only a decode statement: both modes still run GPU expert GEMMs,
  since prefill streams whole expert layers into the GPU double buffer and
  computes there, and hybrid additionally computes its cache hits plus its
  capped PCIe fetches on the GPU
  (`python/freetoken/moe/cpu_offload.py:8-45`);
- B5's *decode* expert compute is not a GPU NVFP4 kernel at all: it runs in
  the CPU executor's own dequant-in-GEMV kernels
  (`python/freetoken/moe/cpu_executor.py`).

Both rows therefore pass `--nvfp4-backend triton`, which is what actually
executes, and the report records the flag as **inert for the expert path** in
those two configurations rather than pretending it selected something.

**A third resolution path that must be recorded.** Under `--moe-backend
offload`, with `--moe-cpu-layers` unset and CUDA pinning quota-capped,
`_auto_cpu_layers` may lock some MoE layers onto the CPU executor
(`engine.py:517-523`). That flips the whole process to the native bank layout
and makes `--nvfp4-backend` inert in B1 and B4 too. §2.3 already requires
recording whether `_auto_cpu_layers` locked any layers; if it did, the report
says so, and the **resolved** backend — not the flag — is the configuration.

**B4 is not padding.** On sm_86 the NVFP4 Marlin path is what
`--nvfp4-backend auto` selects **where vLLM's Marlin donor symbols are usable**
(`python/freetoken/moe/nvfp4_backends.py:245-254`), and
`OffloadMoeCache` refuses a slot cache larger than `MARLIN_MAX_CACHE_SIZE =
992` (`python/freetoken/moe/offload_cache.py:93`, enforced at line 415). For
Qwen3.6-35B-A3B that is 992 of `40 x 256 = 10,240` expert slots — at most
**9.7 % resident coverage regardless of free VRAM**. The Triton NVFP4 backend
carries no such cap and may hold several times more experts with a slower
per-GEMM kernel. Which side of that trade wins on this hardware is an
empirical question, and skipping it would hand InferSwarm a baseline that was
capacity-starved by a *kernel limit* rather than by the GPU. Whether the cap
actually binds must be recorded either way (§13).

**B1 and B4 are a pair, and the pair is allowed to collapse.** B1 measures
what the hardware-aware selection actually chooses on this rig; B4 forces
Triton to find out whether a larger resident cache beats the
faster-but-992-slot-limited Marlin path. If `--nvfp4-backend auto` resolves to
`triton` on the actual rig — vLLM absent, donor symbols unusable, or any other
reason `select_nvfp4_backend` declines Marlin — **that is the result, and it is
reported**: B1 and B4 are then recorded as equivalent observations of the same
resolved configuration, with the reason `auto` did not land on Marlin stated.
Marlin is not installed, forced, or otherwise arranged merely to make B1
distinct from B4, and a duplicate pair is never padded into a difference.

### 2.2 Selection rule

> **`CANONICAL_PERFORMANCE_BASELINE`** is whichever of B1–B5 achieves the
> highest aggregate warm decode throughput (§6, §10) on the frozen workload
> set, **provided it is a valid, working FreeToken configuration** in the
> sense of §5.5.

All five results are recorded, with provenance, before any candidate run.
Consequences, binding:

- Beating a non-winning configuration while losing to the winner is **not** a
  GO, and must never be reported as a speedup.
- Every performance ratio quoted in the Phase-1 report is against
  `CANONICAL_PERFORMANCE_BASELINE`. Ratios against B1–B5 individually may
  appear as context, always labelled as such.
- If `CANONICAL_PERFORMANCE_BASELINE` changes because Phase 0 is re-run (new
  driver, new model revision, new FreeToken commit), the candidate is re-run
  too. The
  benchmark contract already requires this; it is restated because it is the
  cheapest rule to quietly break.

**Validity, not numeric identity.** §5.5 states the requirement in full. In
short: a baseline configuration has to be a known-good FreeToken configuration
that passes FreeToken's applicable existing model/backend correctness checks —
"fast but wrong" is not a baseline — but it is **not** disqualified because its
floating-point execution order, its kernels, or its expert-compute device
differ from the candidate's. `--moe-backend cpu` and `--moe-backend hybrid`
compute routed experts on the CPU executor in different kernels and a different
accumulation order (§5.1); either may legitimately win this sweep, and if it
does, it is the baseline InferSwarm has to beat. The candidate's *numeric*
target is `CORRECTNESS_REFERENCE` (§2.4, §5), never the sweep winner.

### 2.3 Recorded baseline configuration

The Phase-0 record must state all of the following for every B1–B5 arm, for
`CANONICAL_PERFORMANCE_BASELINE`, for `CORRECTNESS_REFERENCE` (§2.4), and,
unchanged, for the candidate:

```
model repository            (Phase 1: nvidia/Qwen3.6-35B-A3B-NVFP4, §1.1)
model revision              (exact upstream commit SHA, pinned before Phase 0)
expert_quant                (resolved weight format, not the flag text)
FreeToken commit + InferSwarm branch commit
--moe-backend                 and, for hybrid, the ft bench bw profile used
--nvfp4-backend               (as passed AND the resolved value; for a
                             cpu/hybrid arm, recorded as "not selected —
                             native nvfp4 layout, Triton kernels")
--moe-cache-size / -rate / -auto   AND the resolved moe_cache_size in slots
--kv-reserve-tokens           AND the resolved num_pages / page_size
--memory-ratio
--moe-cpu-threads             AND whether _auto_cpu_layers locked any layers
--moe-cpu-layers              (resolved set, not the flag text)
--moe-hybrid-max-fetch        (resolved value / fetch fraction)
--max-prefill-length, --max-running-requests, --max-seq-len-override
--cuda-graph-max-bs           AND whether capture actually happened
--attention-backend, --cache-type, --page-size   (resolved values)
--sampling-defaults + the effective sampling params
context length, output length, ignore_eos
host CPU / RAM size and speed / driver / CUDA version
nvidia-smi topo -m  and  nvidia-smi topo -p2p r
```

Anything that cannot be filled is recorded with the reason, per the benchmark
contract. Resolved values matter more than flag text: `auto` is not a
configuration record.

### 2.4 The correctness reference (`CORRECTNESS_REFERENCE`)

> **Amendment (Phase-1 correctness-reference v2).** The original Phase-1
> `CORRECTNESS_REFERENCE` was the P0-H R512 single-device configuration. It was
> superseded — before any corrected Phase-1 candidate evaluation and after the
> methodology-change PR required by this section — by the matched-state
> `PHASE1_CORRECTNESS_REFERENCE_V2` defined below. R512 remains a valid,
> self-consistent configuration and remains the historical Phase-0 evidence;
> it is superseded only as the Phase-1 numerical comparator. The full causal
> record, the preserved historical NO-GO verdicts, and the frozen v2
> configuration are in
> [`phase1-correctness-reference-methodology-correction-v2.md`](implementation/phase1-correctness-reference-methodology-correction-v2.md).
> §2.4 was **not** always this way; the amendment history is part of the
> record, not an edit of it.

A fixed, non-distributed, single-device GPU configuration, never chosen by
speed, identical for every correctness fixture in §5, and constructed to
isolate the Phase-1 treatment: the candidate's GPU0 serving configuration with
the InferSwarm treatment removed. Since the v2 amendment, the canonical
Phase-1 reference is:

```
ft serve  --model nvidia/Qwen3.6-35B-A3B-NVFP4   (pinned revision, §1.1)
          --gpu GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55
          --moe-backend offload
          --moe-cpu-layers 0
          --nvfp4-backend triton
          --moe-cache-size 3774
          --kv-reserve-tokens 17075
          --num-tokens 17075
          --memory-ratio 0.85
          --cuda-graph-max-bs 0
          --max-running-requests 1
          --sampling-defaults none        (framework defaults -> greedy, §5.3)
          one GPU; the second card absent or unused; no placement artifact,
          no InferSwarm resident bank, no remote decode, no remote transport
```

Resolved values — not flags — are the record: expert quant `nvfp4`, GPU MoE
decode target, empty CPU MoE layers, Triton NVFP4 backend, 3,774 expert-cache
slots, page size 1, attention backend FI, hybrid radix cache, prefill overlap
enabled, enough KV capacity for W3, and no decode CUDA graphs, matching the
distributed Phase-1 candidate. The warmed serving-state protocol (fresh server
per session, canonical W1 → W2 → W3 → W4 order, frozen request bodies and
output lengths, `ignore_eos`, greedy, two warmups per workload, no restart or
radix-cache clearing between classes) is part of the frozen fixture, so the
local reference has the same deterministic cache-history opportunity as the
candidate. The reference is defined by this mechanical derivation, not by
numerical closeness to the candidate.

Why exactly this, from source rather than by preference:

1. **It has to run the same NVFP4 kernel family and bank layout as the
   candidate's GPU-resident experts**, or C1's `2e-3` backend-vs-backend
   tolerance means nothing. The kernel follows the loaded bank layout
   (`python/freetoken/layers/moe.py:433-505`, dispatching on `quant_format`),
   which follows `--nvfp4-backend` through `select_nvfp4_backend`
   (`python/freetoken/moe/expert_banks.py:179-215`). Pinning the flag to the
   candidate's resolved value pins the kernel; both cards are the same sm_86
   SKU, so the same value is available on each.
2. **`--moe-backend fused` cannot serve this checkpoint.** The resident-expert
   path allocates bf16 / block-fp8 experts only, and `auto` never picks it
   (`python/freetoken/engine/engine.py:1353-1360`). It is not an available
   NVFP4 reference, so the offload family is the only single-device path that
   runs the GPU NVFP4 grouped-GEMM over these banks.
3. **`cpu` and `hybrid` are excluded by construction.** Both load banks with
   `decode_target="cpu"` (`engine.py:582`), which keeps the native layout and
   skips backend selection entirely (`expert_banks.py:179-207`), and `cpu`
   computes decode experts in the CPU executor's own kernels
   (`python/freetoken/moe/cpu_executor.py`). Neither is the candidate's
   numeric path.
4. **`--moe-cpu-layers 0` is load-bearing.** It forces every MoE layer onto the
   GPU offload path (`python/freetoken/server/args.py:547-558`;
   `_parse_cpu_layers_spec` maps `"0"` to the empty set,
   `engine.py:1091-1117`) and suppresses `_auto_cpu_layers`, which fires only
   when `config.moe_cpu_layers is None` (`engine.py:517-523`). Without it, a
   quota-capped host could silently move part of the *reference* onto the CPU
   executor and change what "the same kernel" means.
 5. **A fixed `--moe-cache-size`** keeps the reference stable run to run instead
    of tracking whatever `--moe-cache-auto` resolves to on the day. It must
    satisfy the `cache_size >= num_experts` floor and, under `marlin`,
    `MARLIN_MAX_CACHE_SIZE = 992` (`python/freetoken/moe/offload_cache.py:93`,
    enforced at 408-422). The original wording of this item — "Cache size
    changes how often the reference fetches, not what it computes" — was
    corrected by the v2 amendment: for the complete warmed serving state,
    cache geometry also alters radix-cache eviction history, so the reference
    must match the candidate's resolved cache/KV geometry rather than merely
    share its kernel family. See
    [`phase1-correctness-reference-methodology-correction-v2.md`](implementation/phase1-correctness-reference-methodology-correction-v2.md).

Binding rules:

- The correctness reference **does not have to be the fastest** configuration,
  and it is **never** quoted as a performance comparator. No ratio, bound,
  threshold or verdict in §6, §7, §10, §11, §13 or §15 is computed against it.
- It is **not required to be** `CANONICAL_PERFORMANCE_BASELINE` and is not
  chosen to be. If the sweep winner turns out to be the same configuration,
  that is a coincidence, recorded as one.
- Its resolved configuration is recorded exactly as §2.3 requires of the other
  arms, resolved `--nvfp4-backend` included.
- It must be **self-consistent before it is used**: two independent reference
  runs of every fixture must produce identical token sequences (§5.3). An
  unstable reference makes the correctness campaign INVALID; it never makes the
  candidate wrong.
- If no single-device configuration can match the candidate's remote expert
  GEMM — something Phase 0 would have to discover — the mismatch is named in
  the report and C1's tolerance is **not** loosened to paper over it. The
  correctness method is amended in a PR, with its thresholds written before any
  candidate result is seen (§5.3's rule, applied to the reference itself).

---

## 3. Anti-starvation rules

`CANONICAL_PERFORMANCE_BASELINE` must use the RTX 3060 as effectively as
FreeToken normally can. The following are **prohibited**, and any one of them
invalidates the campaign rather than merely weakening it. They govern the
performance arms; `CORRECTNESS_REFERENCE` is not a performance arm and is
instead fixed by §2.4 — though rule 4 binds it too, since it must run the same
checkpoint at the same pinned revision as everything else.

1. **Shrinking the baseline expert cache.** The baseline runs with
   `--moe-cache-auto` (the default for offload-family backends) or the
   largest cache its configuration supports. Manually lowering
   `--moe-cache-size` / `--moe-cache-rate` below the auto-resolved value is
   prohibited.
2. **Asymmetric KV headroom.** `--kv-reserve-tokens` and `--memory-ratio` are
   identical on both arms. If the candidate ends up with *more* allocated KV
   capacity because experts moved off GPU 0, that is a legitimate consequence
   of the mechanism and is allowed — but the resolved KV capacity of both arms
   must be reported, **and** a supplementary baseline run with `--num-tokens`
   pinned to the candidate's KV capacity must be recorded, so a reader can
   separate "more KV" from "remote experts".
3. **Forcing avoidable cache misses** — artificial cache resets, synthetic
   routing, or disabling `--moe-prefill-hit-d2d` / prefill overlap on the
   baseline only.
4. **Different quantization or weight format** between arms. Same
   `expert_quant`, same checkpoint, same pinned revision (§1.1). No
   NVFP4-vs-FP8 comparisons. This holds the format constant *within* Phase 1;
   it is not a statement that InferSwarm is an NVFP4 architecture (§1.1).
5. **Different context length, prompt set, or output length.** `ignore_eos`
   is used so output length is exact and identical.
6. **Different CPU resources.** Same `--moe-cpu-threads`, same physical cores
   available, no `taskset`/cgroup restriction on the baseline only. The
   baseline's CPU MoE executor is part of its legitimate strength.
7. **Workload cherry-picking.** Workloads are frozen and hash-pinned before
   the candidate is first benchmarked (§9).
8. **Excluding candidate overhead a user would pay.** Dispatch cost,
   synchronization, and any performance lost to disabled CUDA graphs are
   *inside* the candidate's number (§12). One-time startup cost is reported
   separately and is not amortized per token (§11), which is the only
   exclusion this document permits.

InferSwarm must beat the real existing system. A strawman baseline does not
just produce a wrong verdict; it destroys the value of every later phase that
builds on it.

---

## 4. Mechanism gates (F) — is the thing actually happening?

These decide whether the run is **evidence at all**. They are evaluated
before correctness and before performance. A failed mechanism gate makes the
run **INVALID** — not NO-GO, because it says nothing about H1.

| Gate | Requirement | Evidence |
|---|---|---|
| **F1 — residency** | GPU 1 holds resident routed experts, and its expert bytes are **≥ 25 %** of the two GPUs' combined expert-cache bytes | Engine placement table (slots + bytes per device) cross-checked against `nvidia-smi` per-GPU memory |
| **F2 — execution locality** | **≥ 20 %** of all decode-time expert executions occur on GPU 1, **in every** workload class | Per-device executed-expert counters, accumulated device-side like the existing `stat_active` / `stat_missing` counters |
| **F3 — dispatch shape** | One activation payload per (device, layer, step) — not one per expert | Dispatch count per decode step must equal the number of layers in which GPU 1 held ≥ 1 selected expert |
| **F4 — combine** | Remote results returned and combined correctly | Covered by C1/C2 (§5) |
| **F5 — no weight streaming** | Steady-state host→GPU-1 traffic must be **< 1 %** of the bytes that streaming the remotely executed experts' weights would require | Measured host→GPU-1 bytes per decode step vs. the CALCULATED weight bytes from `_BANK_BYTES_PER_EXPERT` (`offload_cache.py:82-89`); plus a GPU-1 expert-copy counter at ~0 in steady state |
| **F6 — no silent fallback** | Every route that placement assigned to GPU 1 either executes on GPU 1 or produces an explicit, recorded failure. **Zero** silent fallback of GPU-1-assigned work to GPU 0, CPU, or host RAM | The four counters below, per class: `selected_for_gpu1 == executed_on_gpu1`, `fallback_elsewhere == 0`, `explicit_failure == 0` |

**Failure semantics differ by gate**, and the difference is deliberate:

- **F1, F2, F4, F5, F6 are invalidating.** Failing any of them means the run
  is not exercising resident remote expert execution — the mechanism is
  absent, barely present, wrong, or actually a weight-streaming path. The run
  is **INVALID**: it is evidence for nothing, in either direction.
- **F3 is a conformance gate, not an invalidating one.** A prototype that
  dispatches per expert *is* executing experts remotely; it is just paying an
  avoidable protocol cost. F3 failure therefore **blocks GO** but permits
  ITERATE under case E, with the per-expert dispatch named as the I4
  bottleneck. It must be reported prominently either way.

Notes that make these checkable rather than aspirational:

- **F1 and F2 have numbers on purpose.** "We placed three experts on GPU 1"
  or "0.4 % of executions were remote" would otherwise satisfy a
  qualitatively-worded gate while telling us nothing about the architecture.
- **F3 is the protocol rule** from [ARCHITECTURE.md](../ARCHITECTURE.md) and
  [ADR 0003](adr/0003-1gbe-baseline-network-target.md): one payload per
  worker per layer, per-expert fan-out hidden behind the dispatch boundary.
  A prototype that dispatches per expert **fails F3**, and therefore cannot
  be GO — but per the failure semantics above it is exactly the kind of
  bounded implementation cost that can support ITERATE (§7 case E, §8 Rule A).
- **F5 is the difference between the two architectures.** If host→GPU-1 bytes
  scale with remote invocations, the candidate is a weight-streaming path
  wearing a remote-execution costume, and its numbers do not test H1.

**F6 tests fallback semantics, not participation.** MoE routing is sparse: for
any given decode step or layer, the router may legitimately select no expert
whose placement is GPU 1. That is ordinary sparse routing, **not** fallback,
and such steps and layers are valid and counted normally. F6 therefore does
**not** require GPU 1 to participate in every layer or every token — F2
already carries the participation requirement (≥ 20 % of decode-time expert
executions on GPU 1 in every workload class), which is where a mechanism that
is present but negligible is caught.

What F6 forbids is work that *was* assigned to GPU 1 quietly being served
somewhere else. The candidate must therefore instrument four distinct
counters, accumulated per (class, session) and reported separately:

```
selected_for_gpu1   routes the router selected whose placement is GPU 1
executed_on_gpu1    of those, the ones that actually executed on GPU 1
explicit_failure    of those, the ones that failed and were recorded as failures
fallback_elsewhere  of those, the ones served on GPU 0 / CPU / host RAM instead
```

For a valid measured campaign:

```
selected_for_gpu1 == executed_on_gpu1
fallback_elsewhere == 0
explicit_failure   == 0
```

A step or layer with `selected_for_gpu1 == 0` contributes zero to all four and
is a normal measured step. A nonzero `fallback_elsewhere` is invalidating: the
arm being measured is not the arm being claimed. A nonzero `explicit_failure`
is also invalidating for the campaign, but it is the honest failure mode —
recorded, visible, and diagnosable — which is the entire point of requiring
failures to be explicit rather than silently absorbed.

---

## 5. Correctness gates (C) — hard prerequisite

**Performance numbers from an incorrect run are not evidence.** Correctness
is never traded for speed and is never re-tuned to fit an observed deviation.

The tolerances below are chosen from FreeToken's own numeric formats and its
existing test conventions, not from what happens to pass.

### 5.1 What the comparison actually is

**Correctness compares the distributed candidate against
`CORRECTNESS_REFERENCE` (§2.4)** — not against
`CANONICAL_PERFORMANCE_BASELINE`, which may be a configuration that computes
routed experts in entirely different kernels on an entirely different device.

Candidate and correctness reference run the **same NVFP4 grouped-GEMM kernel
family over the same bank layout**, on **two identical RTX 3060 SKUs**, with
the **same weights**, the **same pinned checkpoint revision**, the **same
router selections** and the **same routing weights**. The only legitimate
source of numeric difference is that the candidate's combine reorders a
mathematically equivalent sum across devices, and bf16/fp32 accumulation is
not associative.

**The performance baseline may not share that property, and does not have to.**
If **B5** (`--moe-backend cpu`) wins the §2.1 sweep, its decode experts are
computed by the CPU executor's own dequant-in-GEMV kernels
(`python/freetoken/moe/cpu_executor.py`), in a different accumulation order.
If **B2** (`hybrid`) wins, some routed experts run on the GPU from the slot
cache and the freshly fetched set, while the remaining misses are computed on
the CPU and the two partial results are summed
(`python/freetoken/moe/cpu_offload.py:33-45`). Both are legitimate FreeToken
configurations, either may be the thing InferSwarm has to beat, and neither
defines what the candidate is supposed to *compute*. A candidate is never
failed for differing numerically from a CPU or hybrid arm — which is exactly
why C1, C2, C3 and C5 name the correctness reference instead of "the
baseline".

That rules out both failure modes named in issue #1:

- **Bit-identity is not required**, because reduction reordering makes it
  unachievable for sound reasons.
- **A loose tolerance is not acceptable either.** FreeToken's `3e-2`-class
  MoE tolerances (`tests/moe/test_nvfp4_backends.py:79-84`,
  `tests/moe/test_fused_moe.py:98`) exist for *quantized-kernel vs. dequantized
  fp32 reference* comparisons, and their docstring says so explicitly. The
  candidate-vs-reference comparison is same-kernel-family on both sides.
  Borrowing the dequant tolerance here would hide a mis-scaled alpha, a
  dropped expert, or a wrong routing weight.

The right precedent is FreeToken's **backend-vs-backend** check —
`fused_experts_decode_nvfp4_marlin` vs `fused_experts_decode_nvfp4_serial`
(both native-layout kernels in `python/freetoken/moe/fused_nvfp4.py` — the
"Marlin-style" name is the wide-load dequant, not the vLLM Marlin backend),
same device, same weights, differing only in how the dequant arithmetic is
ordered — which uses `rtol=2e-3, atol=2e-3`
(`tests/moe/test_nvfp4_backends.py:392-411`). That is the same *kind* of
difference §2.4 constructs the correctness reference to isolate: identical
inputs, identical weights, identical routing, one reordering of equivalent
arithmetic. The tolerance is kept unchanged for that pair, and it is not
extended to any GPU-vs-CPU comparison, where the precedent does not apply and
where this document does not gate correctness at all (§5.5).

### 5.2 The gates

| Id | Scope | Metric and threshold |
|---|---|---|
| **C1** | Combined MoE-layer output: distributed candidate vs. `CORRECTNESS_REFERENCE` (§2.4), with identical hidden input, identical weights, identical router selections and identical routing weights | `torch.testing.assert_close(out.float(), ref.float(), rtol=2e-3, atol=2e-3)`. **Also report the observed max absolute and relative deviation.** A deviation above `1e-4` relative must be *explained* in the report, not merely declared in-tolerance |
| **C2** | Router selections and placement accounting, candidate vs. the same `CORRECTNESS_REFERENCE` fixture | **Exact.** Top-k expert ids per layer at decode step 0 from identical state: `torch.equal` against the correctness reference. Per-device executed-expert counts must sum exactly to `top_k x num_moe_layers x steps`. These are integers; there is no tolerance |
| **C3** | End-to-end greedy token sequence | See 5.3 |
| **C4** | Numerical health | **Zero** NaN/Inf in candidate logits across the entire measured campaign |
| **C5** | Task-level sanity (**supporting, non-gating**) | FreeToken's own `tests/e2e/test_aime.py` fixture run on the candidate and on `CORRECTNESS_REFERENCE`; the candidate must not fall below the reference on the same problem set |

C2's exactness is grounded: FreeToken's own cross-implementation cache test
compares slot bookkeeping with `torch.equal`
(`tests/moe/test_hybrid_fetch.py:112-114`). Routing and placement are integer
bookkeeping and must be exact.

C2 is scored on the correctness-reference fixture, which is also what makes
§8.3's matched touch set well defined: the routing recorded there is routing
the candidate and the reference provably agree on. Where §8 needs
`CANONICAL_PERFORMANCE_BASELINE`'s per-touch residency state — or needs that
arm to have routed the same touch at all — it says so explicitly and takes it
from that arm's own counters (§8.3).

### 5.3 C3 — end-to-end token equality, stated explicitly

FreeToken's `SamplingParams` defaults to `temperature = 0.0`
(`python/freetoken/core.py:19-31`) and exposes **no seed parameter anywhere**.
Greedy decoding is therefore the only reproducible fixture available, and the
correctness fixtures run with `--sampling-defaults none` (framework defaults →
greedy), fixed prompt, fixed `max_tokens`, and `ignore_eos`.

1. **Self-consistency precondition.** Two independent
   **`CORRECTNESS_REFERENCE`** runs of every correctness fixture must produce
   **identical** token sequences. This is checked *before* any candidate
   correctness testing begins, and it is checked on the reference — not on
   whichever configuration won the performance sweep.

   **If the precondition fails, the correctness campaign is INVALID** — not
   downgraded, not relaxed. Concretely:

   > If `CORRECTNESS_REFERENCE` fails the C3 greedy self-consistency
   > precondition, the correctness campaign is **INVALID** until either a
   > stable deterministic fixture is established, or a different method is
   > predeclared — in a PR amending this document, with its exact thresholds
   > written before any candidate result is seen. No Phase-1 verdict may be
   > issued in the meantime.

   The reasoning is simple: the candidate is never benchmarked for
   correctness against an unstable reference. An unstable reference makes
   "candidate differs from reference" uninterpretable, and any rule that
   tolerated it would hand the decision back to post-result discretion, which
   is exactly what issue #1 exists to remove. There is deliberately **no**
   softer fallback rule here — an undefined "divergence-index rule" would be
   a threshold chosen after seeing the data.

   The failure is reported prominently, with both reference sequences and the
   index at which they first diverge, as the diagnostic input to establishing
   a stable fixture.
2. **Given self-consistency, the gate is:** the candidate must reproduce
   `CORRECTNESS_REFERENCE`'s generated tokens **exactly for the first 64
   tokens** of every correctness fixture. The comparison is candidate vs.
   reference, never candidate vs. whichever backend won B1–B5.
3. **Beyond token 64**, divergence attributable to accumulated reduction-order
   differences at near-tie logit positions is **expected and is not a
   failure**. The candidate-vs-reference divergence index is recorded for every
   fixture as a reported diagnostic. It is **not** a gate and no threshold is
   attached to it — it explains a result, it never decides one.
4. **Step-0 logits.** At the first generated token: identical `argmax`,
   identical top-5 ordering, and full logit vector within `rtol=2e-3,
   atol=2e-3`.

Why 64 and not "the whole sequence": 64 greedy tokens across 40 MoE layers is
several thousand remote expert executions, which is far more than enough to
surface a dropped expert, a wrong scale, or a mis-ordered combine — while
being short enough not to fail on a legitimate near-tie that a
mathematically equivalent reordering resolved the other way. Requiring
full-sequence equality would be an arbitrary bar that a correct
implementation cannot clear.

### 5.4 Precedence

- A candidate failing **any of C1–C4** is **NO-GO** for that build.
- That NO-GO can become a real verdict **only** after the defect is fixed and
  the **entire campaign is re-run from scratch**. Partial re-runs are not
  permitted, and performance numbers from the incorrect build are discarded,
  never reused or spliced.

### 5.5 Performance-baseline validity is a separate, weaker requirement

B1–B5 are not held to C1–C3. They are held to this:

> Every configuration in the §2.1 sweep must be a **legitimate, working
> FreeToken run**: a supported, known-good configuration that passes
> FreeToken's applicable existing model/backend correctness checks for that
> mode — its own `tests/moe` backend and cache tests, with
> `tests/e2e/test_aime.py` as the task-level sanity fixture — produces zero
> NaN/Inf, and generates coherent output on the frozen fixtures. Whichever arm
> wins the sweep must satisfy this before it can be
> `CANONICAL_PERFORMANCE_BASELINE`.

**Do not read this as "performance baselines may produce garbage so long as
they are fast".** A configuration that fails its own correctness checks is not
a baseline, it is a bug: it leaves the sweep, with the failure recorded.

What it does mean:

- A baseline is **not** disqualified because its floating-point execution
  order, its kernels, or its expert-compute device differ from the candidate's.
  Those differences are expected and designed-in for `cpu` and `hybrid` (§5.1).
- **Candidate-vs-baseline token divergence is not a candidate correctness
  failure.** C3 is scored against `CORRECTNESS_REFERENCE` only. Divergence
  between the candidate and a CPU or hybrid performance baseline is a recorded
  observation with no threshold attached to it, and may never be reported as a
  correctness result in either direction.
- The strict `rtol/atol = 2e-3` comparison and the exact-token window belong to
  the candidate-vs-reference pair and to nothing else in this document.

The asymmetry is deliberate. Performance asks "is InferSwarm faster than the
best real thing this hardware already does?", which requires the strongest
valid baseline whatever kernels it uses. Correctness asks "does distributed
execution compute the intended MoE result?", which requires a reference whose
arithmetic the candidate is genuinely supposed to reproduce. One configuration
cannot answer both questions without weakening one of them.

---

## 6. Primary performance metric

> **Primary metric: batch-1 warm steady-state decode throughput
> (tokens/sec), reported per workload class, aggregated as the geometric mean
> of per-class candidate / `CANONICAL_PERFORMANCE_BASELINE` ratios.**

Justification, not assumption:

- **The mechanism's cost and benefit both land in decode.** Remote dispatch
  recurs every decode step, in every MoE layer, for whichever selected
  experts live on GPU 1 — roughly `40 layers x steps` dispatch opportunities
  per generation. Prefill touches the expert set differently: FreeToken's
  `materialize_layer` reloads a whole layer's experts per prefill chunk
  regardless of prior residency, so prefill is dominated by bulk transfer
  rather than by per-selection dispatch.
- **Decode is what InferSwarm's stated target feels.** The project targets
  interactive local inference; for a single user at batch 1, wall-clock is
  dominated by decode for anything but the shortest replies.
- **It is the metric where the baseline is strongest.** In offload/hybrid
  mode, decode cost is dominated by per-step expert movement over PCIe or CPU
  execution of misses — precisely the cost H1 claims to remove. Choosing a
  metric where the baseline is weak would be a subtler form of strawman.
- **FreeToken already measures exactly this** through the full serving path
  (`benchmarks/bench_decode_moe.py`: batch-1 decode tok/s of a served MoE
  model, timing token arrivals over streamed `/v1/chat/completions`), so the
  primary metric does not depend on new measurement code that only the
  candidate exercises.

Batch-1 is chosen deliberately: it is the interactive case, and it is the
*hardest* case for the mechanism, since there is no batching to amortize
dispatch latency. A win at batch 1 is a strong result; a loss at batch 1 that
becomes a win at batch 8 is a real finding but does not satisfy H1.

### Secondary metrics (recorded for every run, non-gating except where §7 binds them)

TTFT · prefill throughput · per-token latency distribution (p50/p95/max) ·
complete MoE-layer latency · dispatch latency · remote expert compute time ·
combine latency · per-GPU utilization · per-GPU VRAM residency and capacity ·
CPU utilization · host↔GPU-1 and host↔GPU-0 traffic · decode miss rate from
the existing `decode_miss_stats` counters · resident expert coverage.

### The microbenchmark rule

Per the [benchmark contract](../BENCHMARKING.md):

> A faster expert or transfer microbenchmark does not constitute Phase-1
> success unless end-to-end inference improves.

Restated as a decision rule: **no microbenchmark, per-layer timing, or
transfer measurement can produce a GO.** Diagnostic measurements exist to
*explain* an end-to-end result and to distinguish implementation failure from
architectural failure (§8). They cannot substitute for one, and they may not
be arithmetically combined into a projected end-to-end number that is then
treated as the result.

---

## 7. Decision thresholds

Definitions used below:

- `R_c` = (candidate median warm decode tok/s) / (`CANONICAL_PERFORMANCE_BASELINE`
  median warm decode tok/s) for workload class `c`, per §10. The denominator is
  always the measured B1–B5 winner (§2.2) — never `CORRECTNESS_REFERENCE`,
  which carries no performance meaning (§2.4).
- `R_agg` = geometric mean of `R_c` over the four frozen workload classes.
  Geometric, because these are ratios and the aggregate must not be dragged
  by whichever class is fastest in absolute tokens/sec.
- **Significant** = the bootstrap 95 % CI on the ratio excludes `1.000`
  (§10), as measured by the campaign.

**The verdict vocabulary is closed.** Phase 1 produces exactly one of:

```
GO   ·   ITERATE   ·   NO-GO   ·   INVALID
```

No other decision state exists, and none may be introduced by a later
section, a report, or an amendment that does not say it is changing this
list. Where a condition is worth recording but is not itself a decision — an
out-of-band startup cost (§11), a Marlin cap that bound (§13), a dropped
workload class (§9) — it is attached to the ordinary verdict as a **recorded
caveat**, written as `GO — startup caveat` or `ITERATE — startup caveat` or
equivalent prose. A caveat qualifies a verdict; it never becomes one. This
matters because a proliferating set of half-verdicts is how a NO-GO quietly
becomes a "GO, with reservations".

### GO

**All** of the following:

| # | Condition |
|---|---|
| G1 | All mechanism gates F1–F6 pass |
| G2 | All correctness gates C1–C4 pass |
| G3 | Reproducibility rules satisfied: `CANONICAL_PERFORMANCE_BASELINE` CV ≤ 5 % in every class, both sessions completed, no early stopping (§10) |
| G4 | `R_agg ≥ 1.20`, **and** the 95 % CI lower bound on `R_agg` is `≥ 1.10` |
| G5 | **Every** class is significant with `R_c ≥ 1.05` — the mechanism helps everywhere, not on average |
| G6 | TTFT ≤ `1.25x` `CANONICAL_PERFORMANCE_BASELINE` **and** prefill throughput ≥ `0.80x` `CANONICAL_PERFORMANCE_BASELINE`, in every class |
| G7 | The Issue #5 complete-layer breakdown (dispatch → per-device execution → combine) exists for **both** arms and is consistent with the end-to-end result |

**Why +20 %, with the CI floor at +10 %.** This is an architecture proof, not
a production target, so the bar must be well below the ~2x a mature scaling
result would demand — issue #1 explicitly rejects a 2x requirement. But it
must also be well above "we added an entire second GPU for a rounding error".
Two anchors set the value:

- *From below:* §10 caps the **ordinary run-to-run noise** this campaign will
  tolerate at all — baseline CV ≤ 5 % in every class, or the campaign is
  re-run. +20 %, with a +10 % CI floor, is placed comfortably beyond that
  allowed noise band, so a GO cannot be a dressed-up "statistically
  indistinguishable". This placement is an **architectural judgment call**,
  not a derivation: the width of the bootstrap CI on a median ratio at
  n = 10 is not determined by the CV, and the CI the campaign actually
  produces is the authority. G4's CI floor is what enforces this at
  decision time — the observed interval must clear +10 % on its own, whatever
  the CV turned out to be.
- *From above:* the mechanism's theoretical headroom is large. Under
  `CANONICAL_PERFORMANCE_BASELINE` a substantial share of decode time is PCIe expert
  fetches and CPU miss execution; the candidate can in principle remove most
  of that for GPU-1-resident experts. A working prototype that removes a
  large fraction of miss traffic and still cannot reach +20 % is telling us
  something real about dispatch cost — which is exactly the ITERATE
  conversation, not the GO conversation.

**Why G5 exists separately from G4.** Without a per-class floor, one
spectacular class could carry three neutral ones through the geometric mean.
G5 makes "it helps everywhere, clearly" the actual claim, and it is what
makes the split-workload case (§7, ITERATE case C) an ITERATE rather than a
GO.

**Why G6's bounds are asymmetric.** Issue #1's guidance is that a decode win
must not hide catastrophic prefill loss, while a modest bounded prefill
regression is acceptable if decode clearly improves. A 25 % TTFT regression is
perceptible but not disqualifying for a prototype targeting the decode path;
beyond that the interactive experience the project exists to serve is
degraded, and the tradeoff stops being modest.

### ITERATE

ITERATE means: **the mechanism has credible promise, and we can name the
specific measured cost standing between it and GO.** It is a bounded
follow-up experiment, never a mood.

Entry requires **all** of:

| # | Condition |
|---|---|
| I1 | F1, F2, F4, F5, F6 pass and C1–C4 pass (an INVALID or incorrect run is never ITERATE). F3 may fail, in which case per-expert dispatch is the I4 bottleneck |
| I2 | G3 reproducibility satisfied |
| I3 | The Issue #5 complete-layer breakdown exists for **both** arms |
| I4 | A **named, source-grounded bottleneck** is identified from that breakdown — a specific code path or mechanism, not "overhead" |
| I5 | **Bounded remediation arithmetic:** removing that named cost, quantified from the measured breakdown, would place `R_agg` above `1.20`. Labelled CALCULATED per the benchmark contract, and explicitly not a claim of success |
| I6 | A **single named next experiment** that would test I5 |
| I7 | **No class regresses beyond** `R_c = 0.95`. A mechanism that materially harms one workload class while helping others has not earned a positive verdict, however promising the aggregate |

and **at least one** of these circumstances:

| Case | Condition |
|---|---|
| **A — sub-threshold but real** | `R_agg` significant and in `[1.05, 1.20)` |
| **B — mechanism wins, the loss is elsewhere** | Per §8 Rule A `REMOTE_INTRINSIC < BASE_NONLOCAL_SERVICE` over the matched non-local touch set (§8.3) — the cross-device service path is cheaper than the best **non-local** baseline service path for the same touches — but the §8.6 removable overhead, or a named placement/scheduling cost per §8.8 and §8.9, consumes the gain |
| **C — split workloads** | **2 or 3** of the 4 classes significant with `R_c ≥ 1.20`, the remainder neutral (`R_c ≥ 0.95`, not significant), so `R_agg` misses G4/G5. A benefit confined to a **single** class is not this case — it is N6 |
| **D — prefill tradeoff out of band** | Decode satisfies G4 and G5, but TTFT is in `(1.25x, 1.60x]` or prefill in `[0.60x, 0.80x)`, with a named cause |
| **E — bounded prototype cost** | GO is missed and the shortfall is attributable to a declared prototype limitation — disabled CUDA graph capture (§12), F3 per-expert dispatch, an unoptimized combine — that satisfies I5 |

**What ITERATE explicitly cannot be:** "we don't like the result, so try
harder". Without I4, I5, and I6 the verdict is NO-GO. A result that misses GO
with no identifiable, measured, bounded cause **is** the architecture's
answer on this hardware.

### NO-GO

**Any** of the following:

| # | Condition |
|---|---|
| N1 | Correctness (C1–C4) cannot be maintained after a reasonable fix attempt |
| N2 | `R_agg` is not significant — the 95 % CI includes `1.000` |
| N3 | `R_agg < 1.05`, or `R_agg < 1.20` with no ITERATE case satisfied |
| N4 | `R_agg < 1.00` beyond noise — the candidate is slower than `CANONICAL_PERFORMANCE_BASELINE` |
| N5 | Per §8 Rule B: over the **matched non-local touch set** (§8.3), the apples-to-apples intrinsic remote-execution path (`REMOTE_INTRINSIC` — activation transfer + remote expert execution + result return, with §8.6 removable prototype overhead excluded) is already no cheaper than the equivalent best **non-local** baseline service path (`BASE_NONLOCAL_SERVICE`, which includes the baseline's transfers **and** its expert compute) — and all seven §8.8 preconditions hold — B-vi, so baseline GPU-0-local cache hits were excluded, and B-vii, so the sign was established on a repetition-block bootstrap (§8.7) rather than on individually resampled expert touches. A candidate that is merely slower than a baseline local hit does **not** satisfy N5, and neither does a touch-level interval that excludes zero |
| N6 | Per §8 Rule C: the benefit is confined to a single workload class — **3 or more** of the 4 frozen classes show no significant gain |
| N7 | The benefit requires conditions a real user would not experience: an artificially shrunk baseline, a hand-picked routing trace, a synthetic prompt, or a configuration outside FreeToken's normal supported modes |
| N8 | The apparent gain exists in per-layer or microbenchmark measurement but disappears under end-to-end measurement |
| N9 | Any class regresses beyond `R_c = 0.95` and no fix is available (I7 fails), **or** reaching the benefit would require architectural complexity disproportionate to it — stated with the specific complexity and the specific measured benefit, not asserted |

A NO-GO is a **result**, recorded and published like any other (issue #10,
[ROADMAP.md](../ROADMAP.md) Phase 1). Per the benchmark contract: *"If the
honest result is 'no improvement' or 'slower', publish that. That is the
experiment working."* If NO-GO invalidates the architecture strongly enough,
Phases 2–4 are reconsidered rather than executed on momentum.

---

## 8. Architectural failure vs. implementation failure

This section separates *"the cross-device path is intrinsically too
expensive on this hardware"* from *"the prototype is rough"*. Getting the
separation wrong in either direction is fatal: excusing everything as
prototype roughness turns NO-GO into ITERATE forever, while an unmatched
cost comparison can manufacture an architectural NO-GO that the architecture
did not earn.

Everything in §8 is a **diagnostic decomposition**. It never produces a
performance number, never replaces `R_agg`, and never rescues an end-to-end
result. Its only job is to classify a result §7 has already produced.

### 8.1 The matching invariant

> **Candidate and baseline comparisons must include equivalent mandatory work
> on both sides.** Whatever a route *must* do to produce an expert's output
> is counted on both sides, or excluded from both. Only costs that are
> genuinely removable from the candidate without changing what it computes
> may be excluded, and they are excluded from the candidate side alone —
> because there is nothing equivalent to remove on the baseline side.

The concrete failure this rules out: expert **compute** is mandatory work on
every route. A comparison that counts the candidate's remote expert
execution while omitting the baseline's expert execution charges the
candidate for arithmetic the baseline also performs, and can produce a false
architectural NO-GO. Expert compute appears on both sides of every comparison
below, or on neither.

§8.2 adds the second half of the same discipline: the two sides must also be
the same *population* of expert touches, serviced from the same starting
condition.

### 8.2 Which tier remote execution is asked to beat

The resource hierarchy of [ARCHITECTURE.md](../ARCHITECTURE.md), applied to
a single expert touch on this rig:

| Tier | Service path | Role in Phase 1 |
|---|---|---|
| **L0** | Expert already resident in GPU 0's expert cache — a local cache hit, compute only, no transfer | The cheapest tier. **Not** what remote execution replaces |
| **L1** | Expert resident on GPU 1 — activation out, remote compute, result back | The InferSwarm candidate mechanism |
| **L2** | Expert not resident on GPU 0 — host→GPU-0 weight fetch, or CPU execution, or the hybrid overlap of both | The existing FreeToken non-local path |

H1 (§1) asks whether **L1 improves on L2**. It does not ask whether L1 beats
L0, and no sane placement policy would want it to: an L0 hit contains no
capacity-boundary service to replace, so requiring a remote worker to beat
local residency would test a hypothesis this project never advanced.

> **Binding rule: a baseline GPU-0-local cache hit (L0) is not an eligible
> baseline service comparator for Rule A or Rule B.** Those rules operate only
> over the matched non-local touch set defined in §8.3, against
> `BASE_NONLOCAL_SERVICE` (§8.4).

**This changes nothing about the performance verdict.** The cost of routing a
touch to GPU 1 whose baseline counterpart was an L0 hit is real, a user pays
it, and it stays fully inside:

- the candidate's end-to-end `R_agg` and every per-class `R_c` (§6, §7);
- the placement and residency analysis (§13);
- the hit-rate analysis (§13), which stays separate from coverage and
  throughput.

Baseline local hits are **never** excluded from `R_agg`. The canonical
end-to-end baseline remains the strongest B1–B5 configuration (§2.2), local
hits included, and the candidate must still beat that real baseline
end-to-end. The exclusion in this section is scoped to §8's architectural
diagnostic and nowhere else. §8.9 says what a local-hit displacement *is*
evidence of.

### 8.3 The matched non-local touch set

C2 (§5.2) requires the candidate's router selections to be **exactly** equal to
`CORRECTNESS_REFERENCE`'s, so the triple `(layer, decode step, expert id)`
identifies the same unit of work rather than a reconstruction. The §8
comparison additionally needs the *performance* baseline arm to have executed
that same triple: only touches where the recorded routing of
`CANONICAL_PERFORMANCE_BASELINE` agrees with the candidate's are eligible. If
the winning baseline is a numerically different configuration whose greedy
trajectory diverges (§5.1, §5.5), the eligible population is limited to the
touches where the routing provably matches, the divergence point is reported,
and if that leaves the comparison unsupported §8 is INCONCLUSIVE per §8.8 —
routing is never assumed to match.

```
MATCHED_NONLOCAL_TOUCH_SET =
    { (layer L, step S, expert E) :
        the candidate executed E on GPU 1 at (L, S),
        AND CANONICAL_PERFORMANCE_BASELINE did NOT serve the same touch
            (L, S, E) as a GPU-0-resident cache hit }
```

For every candidate GPU-1 touch, the corresponding
**`CANONICAL_PERFORMANCE_BASELINE`** route is classified into exactly one of:

| Class | What the baseline did at that touch | Eligible for Rule A/B |
|---|---|---|
| **LOCAL_HIT** | Expert weights already resident in GPU 0's expert cache before the touch; executed on GPU 0 with no fetch | **No** |
| **OFFLOAD_MISS** | Not resident; baseline fetched weights host→GPU 0 and executed there | Yes |
| **CPU_SERVICE** | Not resident; baseline computed the expert on CPU and returned the result | Yes |
| **HYBRID_NONLOCAL** | Not resident; baseline served the route through its overlapped hybrid CPU/PCIe miss path | Yes |

The classification is a function of the **baseline arm's own state** at that
touch and of nothing the candidate did, so it cannot be tuned after seeing
candidate results.

**Evidence, and its limits.** The classification is built from
`CANONICAL_PERFORMANCE_BASELINE`'s own per-touch residency state — the existing `OffloadMoeCache` hit/miss
accounting (`stat_active` / `stat_missing`, `decode_miss_stats`), which §12
rule 5 records as graph-safe — joined to the recorded C2 routing on
`(layer, step, expert id)`. This requires hit/miss resolution **per touch**,
not merely an aggregate miss rate per layer or per run. If the instrumentation
yields only aggregate rates, the matched set cannot be constructed and §8 is
INCONCLUSIVE per §8.8. It may not be approximated by apportioning an
aggregate miss rate across touches: that would assign baseline tiers to
individual touches by assumption, which is the failure this correction exists
to prevent.

**Census, required in the Phase-1 report**, per workload class and in total —
and, per §8.7, per measured repetition for `N_eligible` — so a reviewer cannot
unknowingly compare different service regimes:

```
N_total      candidate expert touches executed on GPU 1
N_local        of which baseline route was LOCAL_HIT        (ineligible)
N_offload      of which baseline route was OFFLOAD_MISS     (eligible)
N_cpu          of which baseline route was CPU_SERVICE      (eligible)
N_hybrid       of which baseline route was HYBRID_NONLOCAL  (eligible)
N_eligible   = N_offload + N_cpu + N_hybrid, the size of
               MATCHED_NONLOCAL_TOUCH_SET
```

`N_total = N_local + N_eligible` must hold exactly; these are integer
counters and, per C2's precedent, integers have no tolerance.

### 8.4 Service costs, per route

Issue #5 requires the complete-layer breakdown for both arms:

```
candidate, per MoE layer per decode step:
    t_dispatch → t_act_xfer → t_remote_exec → t_result_xfer → t_combine → t_sync
    (plus t_local_exec on GPU 0)

baseline, per MoE layer per decode step, by the route the baseline used:
    local   : t_expert_exec(GPU0)                              ← L0, ineligible
    offload : t_weight_fetch(host→GPU0) → t_expert_exec(GPU0)
    cpu     : t_act_xfer(GPU→CPU) → t_cpu_expert_exec → t_result_xfer(CPU→GPU)
    hybrid  : the offload and cpu routes, deliberately overlapped, then combined
```

A **service cost** is the cost of getting one expert's output produced. All of
the following are computed **over `MATCHED_NONLOCAL_TOUCH_SET` only**, on the
same touches, in the same measured window — where "measured window" means one
measured repetition, since §8.7 aggregates these costs within a repetition
before any comparison or resampling happens. Matched by construction:

```
REMOTE_INTRINSIC        = t_act_xfer(GPU0→GPU1)
                        + t_remote_expert_exec(GPU1)
                        + t_result_xfer(GPU1→GPU0)

OFFLOAD_MISS_SERVICE    = t_weight_fetch(host→GPU0)
                        + t_expert_exec(GPU0)

CPU_SERVICE             = t_act_xfer(GPU→CPU)
                        + t_cpu_expert_exec
                        + t_result_xfer(CPU→GPU)

HYBRID_NONLOCAL_SERVICE = the measured critical-path service attributable to
                          the corresponding nonresident routes, preserving
                          overlap — never a sum of the two above (§8.5)
```

Each includes transfer **and** execution. None is a miss-traffic-only
quantity, and `BASE_MISS` — transfer without the corresponding compute — is
not used anywhere in this document.

```
BASE_NONLOCAL_SERVICE = the best applicable baseline service cost over the
                        matched non-local touches
```

"Best applicable" means the minimum over the baseline configurations actually
measured in the §2.1 sweep — the whole sweep, not only
`CANONICAL_PERFORMANCE_BASELINE`, each computed by the declared §8.5 method, and
restricted to the non-local classes of §8.3. Best, not merely canonical: Rule
B is an architectural claim, so it must survive the strongest non-local
baseline path available on this hardware. **Ordinary local-cache hits are not
used when computing `BASE_NONLOCAL_SERVICE`**, in any configuration, under
either method.

### 8.5 Hybrid: overlap is measured, never summed

FreeToken's hybrid backend **deliberately overlaps** the PCIe-fetch/GPU route
with the CPU route: some misses are fetched to GPU 0 and computed there while
the remainder are computed on the CPU, and the partial results are combined.
Adding `OFFLOAD_MISS_SERVICE + CPU_SERVICE` would therefore charge the
baseline twice for time it spent once, inflating the baseline's cost and
manufacturing a candidate win.

> **No hybrid comparison may sum the PCIe/GPU route and the CPU route.**

Exactly one of the two methods below is used, **declared in the result
directory before the comparison is computed**, and used for both arms:

- **M1 — matched expert-route service cost.** Partition the matched non-local
  touches by the route the baseline actually served each one on. Compute
  `OFFLOAD_MISS_SERVICE` over the GPU-route touches and `CPU_SERVICE` over the
  CPU-route touches, each as a per-touch cost. The baseline's service cost for
  the matched touch set is the **occupancy-weighted per-touch cost**, never
  the sum of two wall-clock totals that ran concurrently. The candidate's
  `REMOTE_INTRINSIC` is computed per touch over the same touches. Both sides
  are aggregated **within each measured repetition** before comparison (§8.7);
  the per-touch costs are inputs to that aggregation, never independent
  observations for a bootstrap.
- **M2 — measured critical-path contribution.** Take the measured
  wall-clock contribution of the **complete MoE layer** to the decode step —
  end of attention to MoE output ready — for each arm, from the Issue #5
  breakdown, attributed to the matched non-local touches. Overlap is then
  handled by the measurement itself, because concurrent work contributes to
  the critical path once. On the candidate side, and only there, the §8.6
  removable costs are subtracted. The attribution is done per measured
  repetition, so each repetition yields its own `D_rep` (§8.7); an M2
  attribution that can only be produced by pooling repetitions makes §8
  inconclusive rather than licensing a pooled comparison.

M2 is the safer default and is preferred when hybrid wins the §2.2 sweep,
precisely because it cannot double-count. If M1 is used, the report must
state the measured overlap fraction and show that no interval was counted
in both route totals.

Under M2 the attribution to matched non-local touches must be stated: a
complete-layer measurement contains L0 local-hit work as well, and that share
belongs to neither side of the Rule A/B comparison. If the layer measurement
cannot be attributed to the non-local touches, M2 is unavailable for that run
and M1 or §8.8's inconclusive path applies.

**Double-counting check, mandatory in the report.** Under either method the
summed per-route baseline costs must not exceed the measured
complete-MoE-layer wall clock for that arm. If they do, the accounting is
wrong and Rule B may not be invoked on it.

### 8.6 Removable prototype overhead (candidate side only)

These are costs a working implementation could remove **without changing what
the candidate computes**, so they are excluded from the candidate's intrinsic
path and named individually with their measured magnitude:

```
t_dispatch_python     unnecessary Python-level dispatch on the decode path
t_dispatch_per_expert per-expert rather than per-device dispatch (F3)
t_sync_redundant      synchronization not required for correctness
t_launch_avoidable    avoidable kernel/stream launches
t_combine_unopt       unoptimized combine
t_graph_disabled      performance lost to disabled CUDA-graph capture, where
                      §12 shows capture can eventually be restored
```

Three constraints on that list:

1. **Named and quantified, or not excluded.** An unmeasured "overhead" term
   may not be excluded from `REMOTE_INTRINSIC`.
2. **Removable in principle, demonstrably.** `t_graph_disabled` may be
   excluded only under the §12 conditions; a cost that cannot be shown to be
   removable stays inside the intrinsic path.
3. **Mandatory work is never on this list.** Activation transfer, remote
   expert execution, and result transfer are what remote execution *is*. They
   stay in `REMOTE_INTRINSIC` — which is exactly why the baseline side keeps
   its transfers and its expert compute too (§8.1).

Placement is **not** on this list either, in either direction. A wrong
placement decision is not a removable overhead term to be subtracted from
`REMOTE_INTRINSIC`; it is a separate finding, handled by §8.9.

Everything excluded here remains inside the candidate's **end-to-end**
`R_agg` (§3 rule 8, §12 rule 1). §8 is a diagnostic decomposition, not a
second, kinder performance number.

### 8.7 Sampling unit for the Rule-A/B diagnostic

Rule B can fire a hard architectural NO-GO, so the uncertainty behind it has to
be computed over units that are actually independent. **An individual expert
touch is not one.** Touches within a single measured generation share the
prompt and its routing trajectory, the evolving expert-cache state, scheduler
state, placement, GPU thermal and power state, CPU state, host load, and the
surrounding layer execution. Treating `40 layers x steps x top_k` touches drawn
from ten generations as thousands of independent observations is
pseudoreplication: it produces an artificially narrow interval on precisely the
comparison that can end the project.

> **The independent sampling unit for §8 is the measured repetition — one
> benchmark generation block as defined in §10 — not the expert touch.**

**What a block is.** `REMOTE_INTRINSIC` is measured on the candidate arm and
`BASE_NONLOCAL_SERVICE` on the baseline arms, so a repetition block was
originally conceived as the candidate repetition together with its
**interleaved counterpart** at the same index within (session, workload
class) — the A/B/A/B ordering §10 originally fixed was what made that pairing
meaningful, since paired repetitions ran under the same thermal and load
conditions. §10's campaign-order amendment replaced repetition-level
interleaving with counterbalanced arm-major sessions before any candidate
performance existed, so the pairing is **structurally unavailable** in the
canonical campaign: repetitions with equal indices did not run under
contemporaneous conditions and must not be manufactured into paired
observations. The already-permitted unpaired path therefore applies: each arm
is still aggregated per repetition and the bootstrap still resamples
repetition blocks; the pairing is dropped, and the fact is reported. Touch
-level resampling is not an alternative in either case.

**Per-repetition diagnostic.** Within each measured repetition `r` of each
(configuration, workload class, session), using only that repetition's own
touches:

1. construct that repetition's matched non-local touch set (§8.3), with its own
   census;
2. aggregate `REMOTE_INTRINSIC` over those eligible touches, under the declared
   §8.5 method;
3. aggregate `BASE_NONLOCAL_SERVICE` over the **same** eligible touches, under
   the same method;
4. reduce the repetition to a single diagnostic value:

```
D_rep(r) =   aggregate remote intrinsic service        (repetition r)
           - aggregate matched baseline non-local service  (repetition r)
```

`D_rep` may equivalently be declared as the **within-repetition normalized
per-touch difference**,
`(sum REMOTE_INTRINSIC - sum BASE_NONLOCAL_SERVICE) / N_eligible(r)`, which
normalizes for repetitions of unequal length. Exactly one of the two forms is
declared before the comparison is computed and used everywhere in the report.
Both are repetition-level quantities: per-touch costs never leave the
repetition that produced them.

**Cluster bootstrap.** Inference runs over the `D_rep` values, matching the
campaign structure §10 already fixes (`n = 10` repetitions per configuration,
class and session):

```
within each (session, workload class):
    10 repetition-level D_rep observations

bootstrap, 10,000 iterations:
    resample repetition BLOCKS with replacement, within (session, class)
    each block carries its complete touch set -- touches are never
        resampled individually, split, or exchanged between repetitions
    recompute the class-level diagnostic, and the aggregate across
        classes, on each resample
    report the 95 % percentile interval on the resulting statistic
```

Workload-class and session boundaries are respected rather than pooled:
sessions are evaluated as §10 evaluates them — independently, with the worse
verdict standing — and classes keep their own intervals, since Rule B may be
claimed per class or in aggregate and each claim needs its own interval.

This is deliberately the same unit §10 already uses: `R_c` and `R_agg` are
computed from per-repetition decode throughputs. §8 was the only place in this
document that had drifted to a finer unit. **The §10 end-to-end rules are
unchanged by this section**, are not re-derived from it, and nothing here
alters how `R_c` or `R_agg` are resampled.

**Sparse and underpowered repetitions.** Repetitions differ in how many
eligible touches they contain, and some may contain very few:

- the per-repetition eligible-touch count `N_eligible(r)` is **reported**
  alongside the §8.3 census, per class and per session, with its distribution
  (min / median / max) and the number of repetitions contributing at all;
- a repetition with `N_eligible(r) = 0` contributes no `D_rep` value. It is
  reported, never imputed, and never treated as a zero difference;
- **no expert-touch-count threshold is invented here.** There is no "at least
  N touches per repetition" rule, because nothing in the existing
  instrumentation would justify a particular N, and an invented one would be
  exactly the after-the-fact-adjustable number this document exists to
  prevent. Adequacy is settled by the block-level interval and the published
  counts, not by a floor;
- if the repetition-level diagnostic cannot be measured credibly — too few
  repetitions carry eligible touches, the §8.5 attribution cannot be done
  per repetition, or the census cannot be built per repetition — **§8 is
  INCONCLUSIVE** per §8.8. An underpowered diagnostic is never converted into
  architectural failure.

The existing `N_eligible = 0` handling (§8.8) is unchanged: a class with no
eligible touches supports no Rule-B claim for that class.

### 8.8 The rules

All comparisons below are computed over `MATCHED_NONLOCAL_TOUCH_SET` (§8.3),
using `BASE_NONLOCAL_SERVICE` (§8.4) under the declared §8.5 method.

**Rule A — implementation or placement opportunity.** If, over the matched
non-local touch set,

```
REMOTE_INTRINSIC < BASE_NONLOCAL_SERVICE
```

but the candidate misses GO, then remote execution is intrinsically cheaper
than the baseline's non-local service for exactly those touches: the remote
tier is doing its job where it was asked to. The remaining loss lives
somewhere else, and **which** somewhere else must be named from the measured
evidence rather than assumed. Candidates, all visible in the §8.3 census and
the Issue #5 breakdown:

- **removable prototype overhead** (§8.6) — dispatch, sync, combine, graphs;
- **placement quality** — GPU-1 touches whose baseline counterpart was
  `LOCAL_HIT`, i.e. experts the baseline kept resident on GPU 0 that the
  candidate displaced to the remote tier (§8.9);
- **routing imbalance** across layers, classes, or devices;
- another measured scheduling or serialization cost, named as a code path.

> **Do not label every Rule-A case an implementation problem.** Where the
> census and the breakdown distinguish remote-path overhead from local-hit
> displacement, the report says which, with the numbers. "Overhead" is not a
> permitted summary of a placement result, and vice versa.

**ITERATE may be available**, subject to the unchanged I4–I7 — including I4's
requirement that the bottleneck be named and source-grounded, which a
placement finding satisfies exactly as well as an overhead finding.

**Rule B — architectural failure of the remote tier on this hardware.** Rule
B may fire only if, over a sufficiently supported matched non-local touch set,

```
REMOTE_INTRINSIC ≥ BASE_NONLOCAL_SERVICE
```

after all of: equivalent mandatory work counted on both sides (§8.1);
removable candidate overhead excluded only under §8.6; hybrid overlap handled
per §8.5; baseline GPU-0-local cache hits excluded (§8.2); the same
expert-touch population compared on both sides (§8.3); and **the sign of that
comparison established at repetition-block level** (§8.7) — never by treating
individual expert touches as independent samples.

Then the remote resident tier fails to improve on the **non-local service it
is intended to replace** — not merely on local residency — and no
implementation polish changes that sign on this hardware. **NO-GO (N5).** No
ITERATE case may be invoked against Rule B: an ITERATE justified by removing
overhead that is already excluded from the comparison is circular.

Rule B may only be invoked when **all seven** of the following hold, and the
report states each one:

| | Precondition for invoking Rule B |
|---|---|
| B-i | Both sides include the same mandatory work: transfer **and** expert execution on each route (§8.1) |
| B-ii | The §8.5 method (M1 or M2) was declared before the comparison was computed, and hybrid overlap is not summed |
| B-iii | The double-counting check of §8.5 passes |
| B-iv | Every §8.6 exclusion is named and quantified from the measured breakdown |
| B-v | `BASE_NONLOCAL_SERVICE` is the minimum over the measured B1–B5 sweep, not a convenient single configuration |
| **B-vi** | **The comparison excludes baseline GPU-0-local cache hits. Every touch used for Rule B corresponds to a baseline non-local service path (`OFFLOAD_MISS`, `CPU_SERVICE`, or `HYBRID_NONLOCAL`), and the §8.3 census is published** |
| **B-vii** | **The sign is established at repetition-block level (§8.7): `D_rep` is computed within measured repetitions, the bootstrap resamples repetition blocks carrying their complete touch sets, and the resulting 95 % CI excludes zero on the architectural-failure side. Per-repetition `N_eligible(r)` counts are published. A touch-level resampled interval does not satisfy this precondition** |

**Insufficient matched non-local evidence.** If the matched non-local touch
set cannot support a credible apples-to-apples service comparison, then:

> **§8 is INCONCLUSIVE, Rule B may not fire, and the formal Phase-1 verdict is
> decided by §7 on the end-to-end result.** The report must state why the §8
> comparison was considered insufficient.

At minimum, the comparison is insufficient when any of these holds:

1. The baseline's hit/miss state is not available at **per-touch** resolution,
   so `MATCHED_NONLOCAL_TOUCH_SET` cannot be constructed without apportioning
   an aggregate rate (§8.3);
2. `N_eligible = 0` for any workload class over which a Rule-B claim is being
   made;
3. The **block bootstrap 95 % CI on the repetition-level difference** `D_rep`
   (§8.7) does not exclude zero on the architectural-failure side. Rule B needs
   an interval lying entirely on the side where remote service is no cheaper
   than matched non-local baseline service; an interval containing zero leaves
   the sign unestablished, and one lying on the other side is a Rule-A
   observation, not a Rule-B one;
4. The interval was computed by resampling **individual expert touches** rather
   than repetition blocks. Touch-level resampling is pseudoreplication (§8.7)
   and is not an acceptable basis for Rule B under any circumstance, however
   narrow the interval it produces;
5. The repetition-level diagnostic itself is not credibly measurable — too few
   repetitions carry eligible touches, or the per-repetition census or §8.5
   attribution cannot be built (§8.7).

No percentage floor and no minimum touch count are invented here, because the
existing instrumentation justifies neither; conditions 3–5 defer to the same
measured-CI discipline §10 already applies everywhere else, computed on the
same repetition-level unit §10 already uses, and the measured CI remains
authoritative.

Two things this must not become:

- **A missing or statistically insufficient diagnostic is never a NO-GO.**
  Absence of §8 evidence, and evidence too weak to establish a sign at
  repetition-block level, are both absence of evidence about the
  *architecture*; §7 still decides the verdict
  on the end-to-end result, which may itself be GO, ITERATE, or NO-GO on its
  own terms.
- **INCONCLUSIVE is not a verdict.** It describes the §8 diagnostic only. The
  formal verdict vocabulary remains closed at GO / ITERATE / NO-GO / INVALID
  (§7), and "§8 inconclusive" is recorded as a stated property of the report,
  never as a decision state.

**Rule C — generality failure.** If the advantage is present only where
routing happens to concentrate on GPU-1-resident experts — concretely, if
**3 or more** of the 4 frozen classes show no significant gain, leaving at
most one class carrying the result — the general claim fails. **NO-GO (N6).**
The narrow finding is recorded, with the class named: it is real, it is just
not H1.

The boundary between Rule C and ITERATE case C is deliberate. Two or three
classes improving materially while the rest are neutral is a *partial* result
with an investigable cause — plausibly a routing-locality or placement
question, which is exactly what Phases 2–3 exist to study. One class
improving while three do not is indistinguishable from having found the one
workload that happens to suit the placement, which is the cherry-picking
failure mode this document exists to prevent.

Rule B remains the harshest reading available to the candidate, because "the
prototype was rough" is the easiest story to tell about any disappointing
result. What §8.1 and §8.2 add is symmetry in both dimensions: the baseline
is not judged on transfer alone while the candidate is judged on transfer
plus compute, and the candidate is not asked to beat a tier it was never
meant to replace. Excluding *removable* overhead is the only way to ask the
architecture question separately from the implementation question; excluding
*mandatory* work on one side, or comparing against the *wrong tier*, would be
different errors with the same shape.

### 8.9 Placement mistakes are placement evidence

A candidate can be slow because it put the wrong experts on the wrong device:

```
baseline:   hot expert X stays resident in GPU 0's cache   → L0 local hit
candidate:  expert X is assigned to GPU 1                  → L1 remote dispatch
```

Every touch of X now pays an activation transfer, a remote execution, and a
result return in place of a local GEMM. That is a genuine, user-visible cost
and it is fully charged to the candidate in `R_agg`, per class, and in the
hit-rate analysis — a candidate that displaces enough hot experts can miss GO
and reach an end-to-end NO-GO on §7 alone, with §8 having said nothing.

But it is **not** evidence that the remote-execution mechanism is
intrinsically bad. It is evidence about:

- placement quality and the placement policy that produced it;
- scheduling and residency policy;
- whether hot experts should be replicated rather than moved;
- promotion/demotion between tiers as routing shifts.

Those are Phase 2/3 questions ([ROADMAP.md](../ROADMAP.md)) and Phase-5
runtime questions. **Phase 1 neither implements nor commits to any of them** —
no hot-expert replication, no routing-aware placement, no dynamic
promotion/demotion, no heterogeneous capacity scheduler. §8's only obligation
is to classify the evidence correctly so that a later phase inherits a
placement finding as a placement finding, and an architectural finding as an
architectural finding.

The §8.3 census is what makes this checkable: a report showing a large
`N_local` alongside `REMOTE_INTRINSIC < BASE_NONLOCAL_SERVICE` is describing
a placement problem sitting on top of a working mechanism, and must say so in
those words rather than filing it under "overhead".


## 9. Workload selection — frozen before benchmarking

**Four workload classes**, all required. Prompts, token counts, and sha256
hashes are committed to the result directory **before the candidate is
benchmarked for the first time**. Issue #3's routing traces supply the
realistic fixtures; this section fixes the selection rules that Issue #3 must
satisfy.

| Class | Character | Prompt tokens | Output tokens | Why it is in the set |
|---|---|---|---|---|
| **W1** | Coding / agentic — replayed real agent transcript | ≤ 2,000 | 512 | FreeToken's stated target use case; the workload whose routing locality the feasibility investigation flagged as `[SPEC]` |
| **W2** | Open-ended reasoning / conversation | ≤ 1,000 | 512 | The general case; FreeToken's own decode benchmark already uses an AIME-25 prompt here |
| **W3** | Long context | ~16,000 | 256 | KV pressure changes the MoE/KV VRAM split (`plan_cache_budget` fills experts only after reserving KV), so it can change the mechanism's benefit |
| **W4** | Short interactive turn | ~128 | 128 | The TTFT-sensitive case; guards G6 against being decided only by long generations |

Rules:

1. **All four must be run.** The primary GO number `R_agg` is the geometric
   mean over all four.
2. **Each class independently satisfies a regression bound.** For GO, every
   class must clear `R_c ≥ 1.05` (§7, G5); for ITERATE, no class may fall
   below `R_c = 0.95` (§7, I7). A class may not be excused because the
   aggregate is healthy.
3. **Frozen means frozen.** A class may not be added, replaced, or reworded
   after any candidate result has been seen.
4. **Dropping a class after results are seen** requires a written record in
   the result directory naming the reason, and that record is reproduced in
   the Phase-1 go/no-go report (issue #10). A verdict computed over fewer
   than four classes is reported as such, everywhere, without exception.
5. **Batch size is 1 for all gating runs.** Larger batches may be recorded as
   context and are never part of `R_agg`.
6. **Outliers within a class are handled by §10, never by class removal.**

Four classes is deliberately small. The goal is a fixed, representative set
that resists cherry-picking, not a benchmark suite that becomes its own
project.

---

## 10. Repeatability and statistics

Precommitted, because a few percent is easily noise on enthusiast hardware.

**Warmup.** Server started and model fully loaded (`/health` ready), then
**2 discarded warmup generations** per class per configuration. This warms the
offload LRU cache and, for the candidate, GPU-1 residency. Note that
FreeToken calls `_reset_moe_offload_cache()` after CUDA-graph capture
(`python/freetoken/engine/graph.py:184`), so a cold expert cache at the first
request is the expected starting state for both arms.

**Repetitions.** `n = 10` measured generations per (configuration, class,
session).

**Sessions and ordering.** Two full sessions. As originally written, this
section required: *"Session 1 interleaves `A/B/A/B…`; session 2 runs on a
different day and thermal state with the order reversed. Interleaving keeps
thermal drift symmetric between arms rather than assigned to whichever arm
ran second."* That original language is preserved here and superseded, before
any candidate performance existed, by the
[Phase-1 campaign-order amendment](benchmarks/phase1-campaign-order-amendment.md):
repetition-level interleaving cannot be executed on the canonical rig because
both arms require exclusive use of the same physical GPU 0, and reloading a
server between individual measured repetitions would destroy the warmed
serving state this section exists to measure. The executable ordering is two
**counterbalanced arm-major sessions**. Session 1 begins from a fresh
thermal-reset state and runs `CANONICAL_PERFORMANCE_BASELINE` first, then
`PHASE1_CANDIDATE`; Session 2 begins from an independent thermal-reset state
and reverses the arm order. Within each arm/server process the workload-class
order is `W1 → W2 → W3 → W4` in both sessions, with one fresh server process
per arm per session, no restart between classes, and no radix-cache clearing
between classes. Counterbalancing keeps thermal/order drift symmetric between
arms rather than assigned to whichever arm ran second — the unchanged intent
of the original rule.

**Primary statistic.** Median of the per-rep decode tok/s within each
(configuration, class, session). Median rather than mean because a single
background process or scheduler hiccup skews a mean at `n = 10`, and this is
a desktop, not a cluster.

**Aggregation.** `R_c` = candidate median / `CANONICAL_PERFORMANCE_BASELINE`
median, per class.
`R_agg` = geometric mean of the four `R_c`.

**Session agreement.** Both sessions are evaluated independently. If they
disagree, **the worse verdict stands** and the disagreement is reported.

**Uncertainty.** Bootstrap 95 % CI (10,000 resamples over the per-rep values,
resampling within class, recomputing the geometric mean) on `R_agg` and on
every `R_c`. A difference **counts only if its 95 % CI excludes 1.000**.

**Variance reporting.** For every (configuration, class): min, median, max,
IQR, and coefficient of variation.

**Noise-floor guard.** If `CANONICAL_PERFORMANCE_BASELINE` **CV > 5 %** in any class, the environment
is not quiet enough for these thresholds. The campaign is re-run after
identifying the source; the noisy campaign is not used.

**Outliers.** **No individual rep is discarded.** If a rep is known-bad — the
machine ran something else, thermal throttling was observed — the entire
(configuration, class) block is re-run and the discard is recorded with its
reason. Selective rep removal is prohibited.

**No early stopping.** All reps, classes, configurations, and sessions are
completed before any ratio is computed. Computing ratios mid-campaign and
stopping when a number looks good is prohibited, and the completion order is
recorded so the prohibition is auditable.

**The sampling unit is the measured repetition**, here and in §8. `R_c` and
`R_agg` already resample per-repetition values, and §8.7 applies the same unit
to the §8 diagnostic with a block bootstrap. Nothing in §8 changes the rules in
this section: the end-to-end resampling described here is unaltered by the
clustered diagnostic inference §8 requires.

**The measured CI is authoritative.** Every significance decision in §7 —
G4's `R_agg` CI lower bound, G5's per-class significance, N2 — is made on the
bootstrap interval this campaign actually produces, never on an interval
inferred from the CV or from `n`. No rule in this document substitutes a
predicted CI width for a measured one.

These rules are what make §7's thresholds meaningful, in this sense: §10
places a hard ceiling on the ordinary run-to-run noise the campaign will
accept (CV ≤ 5 %, or re-run), and §7's thresholds are then placed comfortably
beyond that ceiling — +20 % for GO with a +10 % CI floor, +5 % for the
ITERATE floor. Where exactly to place them beyond it is an architectural
judgment call (§7), not a quantity derived from the CV and `n`. A dispersion
statistic on per-rep throughputs does **not** determine the half-width of a
bootstrap CI on a **median ratio** at `n = 10`, and this document does not
claim that it does.

As an explicitly labelled **heuristic observation** only, and binding on
nothing: a CV in the low single digits is the regime in which a few-percent
difference is usually hard to distinguish from noise, which is the intuition
behind not setting a +5 % GO bar. If the campaign's measured CIs turn out
wider or narrower than that intuition suggests, the measured CIs win and the
thresholds are unchanged — they were never derived from the intuition.

---

## 11. Warm, cold, and startup

Three regimes, with only one of them gating.

| Regime | What it covers | Role |
|---|---|---|
| **M-start** | Model load, expert placement, GPU-1 initialization, CUDA-graph capture, time to `/health` ready | Operational, **non-gating** |
| **M-warm** | Steady-state decode after §10 warmup | **Gating — this decides Phase 1** |
| **M-cold** | First generation after ready, including cache transition; decode steps needed to reach steady-state remote-execution fraction | Supporting, **non-gating** |

Rules:

- **M-warm is the verdict.** §7's thresholds are evaluated on M-warm only.
  TTFT for G6 is warm TTFT, measured as the first token of each measured
  generation after warmup.
- **Startup is reported, never amortized.** A one-time model-load or
  placement cost is not charged to every generated token. It is also not
  hidden: M-start is reported for both arms with the same provenance as
  everything else.
- **Startup bound, as a caveat and not a verdict.** If candidate M-start
  exceeds baseline M-start by more than **3x** or by more than **180 seconds
  absolute**, the ordinary §7 verdict is unchanged and a **recorded startup
  caveat** is attached to it — written `GO — startup caveat`,
  `ITERATE — startup caveat`, or equivalent prose — and the report must name
  a remediation. Per §7 the verdict vocabulary is closed
  (GO / ITERATE / NO-GO / INVALID): the caveat is a qualifier on one of those
  four, never a fifth state. Startup remains **operational and non-gating** —
  it is genuinely a one-time cost, and this document defines no reason for it
  to gate — but an unbounded startup cost is a real usability problem and
  naming it on the verdict line is the honest treatment.
- **M-cold is reported because residency is the hypothesis.** H1 is about
  *resident* experts; how long residency takes to establish, and how the
  system behaves before it does, is exactly the kind of fact that would
  otherwise disappear between "startup" and "steady state".

---

## 12. CUDA graphs

Issue #4 permits the first prototype to disable CUDA-graph capture for
affected paths, since FreeToken has no precedent for cross-device operations
inside a captured graph, and its capture region covers the whole decode
forward including the offload cache's expert copies
(`python/freetoken/engine/graph.py:160-184`) — so disabling capture costs the
whole decode step, not only the MoE portion.

Binding rules:

1. **Any performance lost to disabled graphs is part of the candidate's
   actual end-to-end result.** It is inside `R_agg`. A user running this
   build would pay it.
2. **Diagnostic estimation is allowed.** A graph-disabled *baseline* run may
   be recorded to bound the graph-related component. It is labelled
   CALCULATED and lives in the diagnostics section.
3. **Subtraction is prohibited.** Comparing a graph-disabled candidate
   against a graph-enabled baseline and then subtracting the estimated graph
   cost to claim a GO is a review-blocking defect. Any such arithmetic
   presented as a result fails review regardless of the numbers.
4. **Graphs may support ITERATE only with evidence** — case E of §7, which
   requires: (a) the graph-disabled baseline was actually measured, (b) the
   estimated graph cost is bounded by that measurement, (c) the candidate's
   shortfall from GO is smaller than that measured cost, and (d) the report
   names how capture would be restored. Absent (a)–(d), "CUDA graphs were
   off" is not an explanation.
5. **Instrumentation validity.** `OffloadMoeCache.collect_stats` is
   documented as graph-safe, so miss-rate statistics may come from gating
   runs. `collect_decode_freq` is documented as accurate **only with CUDA
   graphs disabled** (`offload_cache.py:230-234`), so routing histograms must
   come from graph-disabled diagnostic runs. A routing histogram taken from a
   graph-enabled run is invalid evidence and must not appear in the report.

---

## 13. Capacity is evidence, not performance

Record per arm, per GPU:

```
total VRAM, free VRAM before load
non-expert weight bytes
resolved moe_cache_size (slots)  x  expert_bytes_per_slot  =  expert cache bytes
KV: num_pages x page bytes  (and the resolved kv_reserve)
GDN / linear-state pool bytes
(1 - memory_ratio) graph/activation headroom
peak reserved
```

and derive **resident expert coverage** = resident slots ÷ (`num_moe_layers x
num_experts`) — for Qwen3.6-35B-A3B, ÷ 10,240.

Also record, explicitly: **whether the Marlin 992-slot cap bound the baseline
or the candidate.** If GPU-0 coverage was limited by `MARLIN_MAX_CACHE_SIZE`
rather than by VRAM, the phrase "the practical expert capacity of one RTX
3060" means something different from what it appears to mean, and every
capacity statement in the report must say so. B4 in §2.1 exists to measure
the alternative.

**The binding rule:**

> Coverage, hit rate, and throughput are three different quantities, reported
> separately, and **no GO may cite coverage**.

- *Coverage* is a placement fact — how many experts are resident.
- *Hit rate* is a routing fact — measured from the existing
  `decode_miss_stats` / `stat_missing` / `stat_active` counters, not inferred
  from coverage.
- *Throughput* is the verdict.

Improved coverage with unchanged hit rate, or improved hit rate with
unchanged throughput, is a **finding worth publishing** — it would tell us the
routing distribution or the dispatch cost is the real constraint — but it is
not success. This section exists because "more experts fit in VRAM" is the
single most tempting substitute for "inference got faster", and
[ARCHITECTURE.md](../ARCHITECTURE.md) already warns that coverage and hit
rate are different quantities.

---

## 14. Secondary / contextual baselines

FreeToken supports tensor parallelism, which is a legitimate two-GPU
configuration on this rig. A `2x RTX 3060` TP run **may** be recorded as
**secondary and contextual**, clearly labelled as not the gate.

It answers a different question. Per the
[feasibility investigation](investigations/multi_gpu_moe_feasibility.md), TP
is unaware of the expert-offload cache — under TP each rank independently
builds its own full host-RAM cache, and the offload cache modules carry no
rank/TP awareness at all. So a TP comparison measures "shard the model across
two cards" rather than "execute resident experts on a second card", and it
cannot substitute for either arm of H1.

**The canonical gate remains:**

```
InferSwarm resident remote expert execution
    vs.
best existing FreeToken single-GPU + host-RAM execution
```

Redefining `CANONICAL_PERFORMANCE_BASELINE` — for instance, deciding that the TP
configuration should be the thing to beat — is a **decision requiring
explicit review**: a new ADR and an amendment to this document, not a
silent substitution while writing up results. Issue #1's framing is the
canonical experiment until it is deliberately changed on the record.

This section also bounds itself: Phase 1 is not a comparative
inference-engine study, and this document does not authorize one.

---

## 15. Decision table

Precedence, applied top to bottom. The first row that fires decides.

| Order | Gate | GO | ITERATE | NO-GO / INVALID |
|---|---|---|---|---|
| **1** | **Mechanism validity** (F1–F6) | All pass: GPU 1 holds ≥ 25 % of combined expert bytes; ≥ 20 % of decode expert executions on GPU 1 in every class; one payload per (device, layer, step); host→GPU-1 steady-state traffic < 1 % of weight-streaming equivalent; `selected_for_gpu1 == executed_on_gpu1` with zero silent fallback and zero explicit failures | F1, F2, F4, F5, F6 pass; **F3 may fail** and be named as the case-E bottleneck | F1, F2, F4, F5, or F6 fails ⇒ **INVALID**: the run is not evidence about H1 in either direction |
| **2** | **Correctness** (C1–C4) | C1 within `rtol/atol 2e-3` with deviation reported; C2 exact; C3 first 64 greedy tokens identical to `CORRECTNESS_REFERENCE` + step-0 argmax/top-5 identical, after the reference passed the self-consistency precondition (§2.4, §5.3); C4 zero NaN/Inf | Identical requirement — correctness is never traded | Any failure ⇒ **NO-GO** for that build; a verdict is possible only after fix + full campaign re-run. C3 self-consistency precondition failure ⇒ **INVALID** until a stable fixture or another predeclared method exists (§5.3) |
| **3** | **Reproducibility** (§10) | `CANONICAL_PERFORMANCE_BASELINE` CV ≤ 5 % in every class; both sessions completed; no early stopping; no rep discarded | Same | Violation ⇒ **INVALID**, re-run required |
| **4** | **Decode performance** (all ratios against `CANONICAL_PERFORMANCE_BASELINE`) | `R_agg ≥ 1.20` with 95 % CI lower bound ≥ 1.10; **every** class significant with `R_c ≥ 1.05` | Significant `R_agg ∈ [1.05, 1.20)`, **or** a §7 case B/C/D/E — **and** I4–I7 satisfied, including no class below `0.95` | CI includes 1.000; or `R_agg < 1.05`; or `R_agg < 1.20` with no ITERATE case; or slower than baseline beyond noise |
| **5** | **TTFT / prefill** | TTFT ≤ 1.25x `CANONICAL_PERFORMANCE_BASELINE` **and** prefill ≥ 0.80x `CANONICAL_PERFORMANCE_BASELINE`, every class | TTFT ∈ (1.25x, 1.60x] or prefill ∈ [0.60x, 0.80x) with a named cause and decode meeting G4/G5 | TTFT > 1.60x or prefill < 0.60x — the tradeoff is unbounded |
| **6** | **Full-layer evidence** (issue #5) | Breakdown present for **both** arms and consistent with the end-to-end result | Breakdown present for both arms and identifies the named bottleneck | Missing, single-arm, or contradicting the end-to-end result ⇒ **INVALID** |
| **7** | **Architecture vs. implementation** (§8) — evaluated over the matched non-local touch set only; baseline GPU-0-local hits excluded | n/a — GO does not need this distinction | Rule A: `REMOTE_INTRINSIC < BASE_NONLOCAL_SERVICE`; the loss is in the §8.6 removable overhead **or** in a named placement/scheduling cost (§8.9) | Rule B: `REMOTE_INTRINSIC ≥ BASE_NONLOCAL_SERVICE` with all seven §8.8 preconditions met (B-vi: no local hits in the comparison; B-vii: the repetition-block bootstrap CI on `D_rep` excludes zero on the architectural-failure side, §8.7) ⇒ **NO-GO (N5)**; preconditions unmet, the CI including zero, or evidence otherwise insufficient ⇒ **§8 INCONCLUSIVE** (not a verdict), §7 decides on the end-to-end result. Rule C: benefit confined to a single class (≥ 3 classes with no significant gain) ⇒ **NO-GO (N6)** |
| **8** | **Capacity** (§13) | Recorded; **cannot contribute to GO** | Recorded | Recorded. Coverage improvements never offset a performance NO-GO |

**Precedence, stated plainly:**

1. A **hard correctness failure is NO-GO regardless of performance.** It can
   become another verdict only after the defect is fixed and the entire
   campaign is re-run from scratch; numbers from the incorrect build are
   discarded, never spliced into the corrected run.
2. A **mechanism-gate failure is INVALID, not NO-GO** — it produces no
   evidence about H1 in either direction, and reporting it as a NO-GO would
   be as dishonest as reporting it as a GO.
3. A **reproducibility violation is INVALID** and requires a re-run.
4. **Performance is evaluated only after 1–3 pass.**
5. **Capacity never produces or rescues a verdict.**

---

## 16. What a Phase-1 verdict authorizes

### A GO authorizes

- ROADMAP **Phase 2** — three-GPU scaling (issue #7);
- ROADMAP **Phase 3** — mixed GPU + GPU + RAM placement (issue #6);
- continued prototype work in the FreeToken fork's `inferswarm` branch;
- publishing the measured Phase-1 result, with its exact scope, as MEASURED.

### A GO does **not** authorize

- generalized runtime extraction (ROADMAP Phase 5 — its own gate);
- network worker implementation (Phase 4);
- **any** claim about 1 GbE viability — untested, [ADR 0003](adr/0003-1gbe-baseline-network-target.md);
- ROCm / Intel XPU support (Phase 6);
- claims that heterogeneous inference has been proven broadly;
- claims about larger or capacity-constrained models (Phase 7);
- commercial product work, or performance claims in any product context;
- describing the InferSwarm architecture as validated. One mechanism, on one
  model, on one pair of identical cards, in one machine, was validated.

### An ITERATE produces

Exactly one bounded follow-up experiment — the I6 experiment — with its own
pass condition written down before it runs. Not an open-ended optimization
period. If the follow-up experiment does not move `R_agg` above `1.20`, the
verdict reverts to NO-GO unless a *new* ITERATE case is satisfied on fresh
evidence, and a second consecutive ITERATE requires explicit review of
whether Phase 1 is still the right experiment.

### A NO-GO produces

- the negative result, recorded and published (issue #10) with full
  provenance, not buried;
- an explicit statement of which §7 rule fired and which §8 rule applied;
- a roadmap review. If Rule B fired — the matched intrinsic cross-device
  service path is not cheaper than the best **non-local** baseline service
  path on this hardware, over touches `CANONICAL_PERFORMANCE_BASELINE` did not
  already serve from GPU 0's cache, with the sign established on
  repetition-block evidence (§8.7) — then Phases 2 and 4 inherit that finding,
  and
  proceeding with them unchanged would require an argument this document does
  not supply.

---

## 17. Product and economic observations (non-gating)

The Phase-1 report **may** include, clearly separated and explicitly
non-gating:

- marginal decode tok/s per added GPU;
- tokens/sec per watt, from `nvidia-smi` power draw over the measured window,
  for both arms;
- an honest note on whether the measured benefit would eventually be
  compelling to an enthusiast weighing a second card.

These are observations, never criteria. In particular:

- Phase 1 does **not** require that two GPUs deliver 2x performance. That is
  a mature-scaling question and this is not a mature scaling benchmark.
- Phase 1 does **not** accept "any positive speedup" as success either — §7's
  thresholds exist precisely because a statistically indistinguishable result
  from an entire added GPU is not a success.

Phase 1 asks one question: **is there enough technical signal to justify
further engineering?** Economics do not answer it, and may not override it in
either direction.

---

## 18. Validation checklist for the Phase-1 report

The go/no-go report (issue #10) is reviewable against this list:

- [ ] Every threshold applied is the one written here; any amendment is a
      separate PR with the would-have-been verdict recorded
- [ ] `CANONICAL_PERFORMANCE_BASELINE` is the measured winner of B1–B5, and all
      five are published; every performance ratio is against it
- [ ] `CORRECTNESS_REFERENCE` (§2.4) is stated as a resolved configuration,
      declared before Phase 0, and is used for C1/C2/C3/C5 and for nothing
      else — no ratio, bound or threshold is computed against it
- [ ] Every baseline row's `--nvfp4-backend` is recorded **as passed and as
      resolved**; B1 passed `auto`, B4 passed `triton`; cpu/hybrid arms are
      recorded as "not selected — native nvfp4 layout, Triton kernels"; if
      `auto` resolved to `triton`, B1 and B4 are reported as equivalent
      observations rather than as a difference
- [ ] Whether `_auto_cpu_layers` locked any layers is recorded for every
      offload-family arm, since it makes `--nvfp4-backend` inert (§2.1)
- [ ] Held-constant list (§2.3) recorded as *resolved* values, for every arm
- [ ] No §3 prohibition violated
- [ ] F1–F6 evaluated and reported before any performance number
- [ ] F6 reported as the four counters (`selected_for_gpu1`,
      `executed_on_gpu1`, `explicit_failure`, `fallback_elsewhere`), not as a
      participation claim; steps with no GPU-1-selected expert counted as
      normal
- [ ] C1–C4 evaluated; C1 deviation reported as a number, not just a verdict
- [ ] C3 self-consistency precondition checked on two independent
      `CORRECTNESS_REFERENCE` runs before any candidate correctness testing; if
      it failed, the campaign is marked INVALID and no verdict is issued
- [ ] No candidate correctness failure is claimed from a numeric difference
      against a CPU or hybrid performance baseline (§5.5); B1–B5 validity is
      reported as FreeToken's own applicable correctness checks, not as C1–C3
- [ ] Primary metric is warm batch-1 decode; no microbenchmark contributed to
      the verdict
- [ ] Four frozen workload classes, hash-pinned before candidate benchmarking;
      any drop recorded with reason
- [ ] n = 10, two sessions, counterbalanced arm-major order per the campaign
      -order amendment, medians, bootstrap CIs, CV reported, no rep discarded,
      no early stopping; the report states that §8.7 repetition pairing is
      unavailable
- [ ] M-start / M-warm / M-cold reported separately; startup not amortized;
      any startup breach recorded as a caveat on an ordinary verdict, not as a
      new decision state
- [ ] The verdict is exactly one of GO / ITERATE / NO-GO / INVALID (§7)
- [ ] Every significance claim cites the campaign's measured bootstrap CI, not
      a CI inferred from CV or `n` (§10)
- [ ] CUDA-graph status stated; no subtraction arithmetic anywhere
- [ ] Coverage, hit rate, and throughput reported as three separate quantities
- [ ] Any TP run labelled secondary/contextual
- [ ] If §8 was invoked: the §8.5 method (M1/M2) was declared before the
      comparison was computed, hybrid overlap was not summed, the
      double-counting check passed, and each §8.6 exclusion is named with its
      measured magnitude
- [ ] The §8.3 census is published per class and in total (`N_total`,
      `N_local`, `N_offload`, `N_cpu`, `N_hybrid`, `N_eligible`), and
      `N_total = N_local + N_eligible` exactly
- [ ] The §8 diagnostic's sampling unit is the measured repetition (§8.7):
      `D_rep` computed within repetitions, repetition blocks resampled with
      their complete touch sets, per-repetition `N_eligible(r)` published with
      its distribution — no interval anywhere in §8 comes from resampling
      individual expert touches
- [ ] If Rule B is claimed: all seven §8.8 preconditions stated and met,
      including expert compute counted on **both** sides (B-i), baseline
      GPU-0-local cache hits excluded from the comparison (B-vi), and the
      repetition-block CI on `D_rep` excluding zero on the architectural-failure
      side (B-vii)
- [ ] If the block-level CI includes zero, or the repetition-level diagnostic
      is underpowered or unmeasurable, §8 is reported INCONCLUSIVE and N5 is
      not claimed
- [ ] Baseline local hits are counted in full in `R_agg` and every `R_c` —
      excluded only from §8's Rule A/B diagnostic
- [ ] If the matched non-local evidence was insufficient, §8 is reported
      INCONCLUSIVE with the reason stated, and the verdict came from §7 alone
- [ ] Any GPU-1 touch whose baseline counterpart was a local hit is reported
      as placement evidence (§8.9), not as remote-path overhead
- [ ] Checkpoint `nvidia/Qwen3.6-35B-A3B-NVFP4` and its exact pinned revision
      recorded, identical on both arms (§1.1)
- [ ] No cross-format or cross-precision claim made from an NVFP4-only
      campaign (§1.1, §16)
- [ ] Verdict states which rule fired, and which §8 rule applied
- [ ] No claim that distributed execution, 1 GbE, or heterogeneous inference
      has been validated beyond what §16 authorizes

---

## 19. Genuinely open until Phase 0

These cannot be settled before measurement exists, and none of them is a
decision rule:

1. **Absolute values** — baseline decode tok/s, TTFT, prefill tok/s. Every
   rule above is a ratio or a rule for exactly this reason.
2. **Which of B1–B5 wins.** The selection *rule* is fixed; the winner is
   measured.
3. **Whether the Marlin 992-slot cap binds**, and therefore what "one RTX
   3060's practical expert capacity" actually is (§13).
4. **Actual per-GPU expert coverage** after non-expert weights, KV, state
   pools, and graph headroom — recorded in Phase 0, not assumed here.
5. **Whether PCIe P2P engages between the two cards**, or copies are
   host-staged. Recorded from `nvidia-smi topo -p2p r`. Either way it is a
   property of this hardware, not an excuse: the candidate's measured number
   is what it is.
6. **The exact Issue #3 fixtures** filling the four W-classes. The selection
   *policy* is fixed here (§9); the specific prompts come from real traces.
7. **The exact upstream revision of `nvidia/Qwen3.6-35B-A3B-NVFP4`.** The
   checkpoint is fixed here (§1.1); the revision SHA is pinned in the result
   directory **before the first Phase-0 run**, and inventing one now would be
   a fabricated provenance record.
8. **Whether `CORRECTNESS_REFERENCE` greedy decoding is bit-reproducible
   run-to-run** on this runtime — checked by the C3 self-consistency
   precondition on the reference itself (§2.4, §5.3). If it is not,
   the consequence is fully defined and is not a relaxation: the correctness
   campaign is INVALID until a stable deterministic fixture or another
   predeclared correctness method exists (§5.3).
