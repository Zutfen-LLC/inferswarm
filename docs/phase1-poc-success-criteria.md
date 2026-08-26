# Phase-1 POC success criteria

```
Status: Decision document. Written before Phase 0 baselines exist and before
any Phase-1 result exists. Nothing here claims a measurement.
```

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

Two further distinctions that the criteria below enforce with hard gates:

- **All experts need not fit in VRAM.** Host RAM stays a first-class tier
  ([ADR 0005](adr/0005-ram-remains-first-class-tier.md)). The candidate is
  allowed — expected — to keep some experts in host RAM.
- **This tests remote *execution*, not remote *storage*.** A candidate that
  parks weights on GPU 1 and streams them to GPU 0 per invocation is a
  different architecture (the feasibility investigation's "Architecture A"),
  and gate **F5** below fails it.

---

## 2. The canonical baseline

The baseline is not "whatever single-GPU configuration we happened to run".
It is **the strongest legitimate FreeToken single-GPU configuration for this
hardware, model, and workload**, chosen by measurement before the candidate
is benchmarked.

### 2.1 Baseline sweep (Phase 0, issue #2)

All runs on **one** RTX 3060 — specifically the same physical card the
candidate later uses as GPU 0 (`ft serve --gpu <uuid>`), with the second card
either absent or unused.

| Id | Configuration |
|---|---|
| **B1** | `--moe-backend offload`, `--moe-cache-auto` (default), NVFP4 backend auto |
| **B2** | `--moe-backend hybrid`, after a fresh `ft bench bw` profile for this GPU + expert format |
| **B3** | `--moe-backend auto` — record which backend it resolves to; must coincide with B1 or B2 |
| **B4** | `--moe-backend offload --nvfp4-backend triton` |
| **B5** | `--moe-backend cpu` |

**B4 is not padding.** On sm_86 the NVFP4 Marlin path is the auto choice, and
`OffloadMoeCache` refuses a slot cache larger than `MARLIN_MAX_CACHE_SIZE =
992` (`python/freetoken/moe/offload_cache.py:93`, enforced at line 415). For
Qwen3.6-35B-A3B that is 992 of `40 x 256 = 10,240` expert slots — at most
**9.7 % resident coverage regardless of free VRAM**. The Triton NVFP4 backend
carries no such cap and may hold several times more experts with a slower
per-GEMM kernel. Which side of that trade wins on this hardware is an
empirical question, and skipping it would hand InferSwarm a baseline that was
capacity-starved by a *kernel limit* rather than by the GPU. Whether the cap
actually binds must be recorded either way (§13).

### 2.2 Selection rule

> The **canonical baseline** is whichever of B1–B5 achieves the highest
> aggregate warm decode throughput (§6, §10) on the frozen workload set,
> **provided it passes the same correctness fixtures the candidate must pass**
> (§5).

All five results are recorded, with provenance, before any candidate run.
Consequences, binding:

- Beating a non-winning configuration while losing to the winner is **not** a
  GO, and must never be reported as a speedup.
- Every ratio quoted in the Phase-1 report is against the canonical baseline.
  Ratios against B1–B5 individually may appear as context, always labelled as
  such.
- If the canonical baseline changes because Phase 0 is re-run (new driver,
  new model revision, new FreeToken commit), the candidate is re-run too. The
  benchmark contract already requires this; it is restated because it is the
  cheapest rule to quietly break.

### 2.3 Recorded baseline configuration

The Phase-0 record must state all of the following for the canonical baseline
and, unchanged, for the candidate:

```
model repository / revision / expert_quant (weight format)
FreeToken commit + InferSwarm branch commit
--moe-backend                 and, for hybrid, the ft bench bw profile used
--nvfp4-backend               (resolved value, not "auto")
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

---

## 3. Anti-starvation rules

The baseline must use the RTX 3060 as effectively as FreeToken normally can.
The following are **prohibited**, and any one of them invalidates the
campaign rather than merely weakening it:

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
   `expert_quant`, same checkpoint revision. No NVFP4-vs-FP8 comparisons.
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
| **F6 — no silent fallback** | Zero fallback events in the measured window; no measured decode step routed 0 experts to GPU 1 | Fallback counter reported as exactly 0; per-step remote-execution counts recorded |

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

---

## 5. Correctness gates (C) — hard prerequisite

**Performance numbers from an incorrect run are not evidence.** Correctness
is never traded for speed and is never re-tuned to fit an observed deviation.

The tolerances below are chosen from FreeToken's own numeric formats and its
existing test conventions, not from what happens to pass.

### 5.1 What the comparison actually is

Baseline and candidate run the **same NVFP4 grouped-GEMM kernels** on **two
identical RTX 3060 SKUs** with the **same weights**. The only legitimate
source of numeric difference is that the combine reorders a mathematically
equivalent sum across devices, and bf16/fp32 accumulation is not associative.

That rules out both failure modes named in issue #1:

- **Bit-identity is not required**, because reduction reordering makes it
  unachievable for sound reasons.
- **A loose tolerance is not acceptable either.** FreeToken's `3e-2`-class
  MoE tolerances (`tests/moe/test_nvfp4_backends.py:79-84`,
  `tests/moe/test_fused_moe.py:98`) exist for *quantized-kernel vs. dequantized
  fp32 reference* comparisons, and their docstring says so explicitly. Our
  comparison is kernel-vs-same-kernel. Borrowing the dequant tolerance here
  would hide a mis-scaled alpha, a dropped expert, or a wrong routing weight.

The right precedent is FreeToken's **backend-vs-backend** check —
`fused_experts_decode_nvfp4_marlin` vs `..._serial`, same device, same
weights — which uses `rtol=2e-3, atol=2e-3`
(`tests/moe/test_nvfp4_backends.py:411`).

### 5.2 The gates

| Id | Scope | Metric and threshold |
|---|---|---|
| **C1** | Combined MoE-layer output, distributed vs. single-device reference, identical inputs/weights/routing | `torch.testing.assert_close(out.float(), ref.float(), rtol=2e-3, atol=2e-3)`. **Also report the observed max absolute and relative deviation.** A deviation above `1e-4` relative must be *explained* in the report, not merely declared in-tolerance |
| **C2** | Router selections and placement accounting | **Exact.** Top-k expert ids per layer at decode step 0 from identical state: `torch.equal` against baseline. Per-device executed-expert counts must sum exactly to `top_k x num_moe_layers x steps`. These are integers; there is no tolerance |
| **C3** | End-to-end greedy token sequence | See 5.3 |
| **C4** | Numerical health | **Zero** NaN/Inf in candidate logits across the entire measured campaign |
| **C5** | Task-level sanity (**supporting, non-gating**) | FreeToken's own `tests/e2e/test_aime.py` fixture run on both arms; candidate must not fall below baseline on the same problem set |

C2's exactness is grounded: FreeToken's own cross-implementation cache test
compares slot bookkeeping with `torch.equal`
(`tests/moe/test_hybrid_fetch.py:112-114`). Routing and placement are integer
bookkeeping and must be exact.

### 5.3 C3 — end-to-end token equality, stated explicitly

FreeToken's `SamplingParams` defaults to `temperature = 0.0`
(`python/freetoken/core.py:19-31`) and exposes **no seed parameter anywhere**.
Greedy decoding is therefore the only reproducible fixture available, and the
correctness fixtures run with `--sampling-defaults none` (framework defaults →
greedy), fixed prompt, fixed `max_tokens`, and `ignore_eos`.

1. **Self-consistency precondition.** Two independent baseline runs of every
   correctness fixture must produce **identical** token sequences. If they do
   not, the runtime is not deterministic enough for exact-equality gating;
   C3 downgrades to the divergence-index rule alone, and the failure of the
   precondition is reported prominently. This is checked *before* the
   candidate is run.
2. **Given self-consistency, the gate is:** the candidate must reproduce the
   baseline's generated tokens **exactly for the first 64 tokens** of every
   correctness fixture.
3. **Beyond token 64**, divergence attributable to accumulated reduction-order
   differences at near-tie logit positions is **expected and is not a
   failure**. The divergence index is recorded for every fixture.
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

---

## 6. Primary performance metric

> **Primary metric: batch-1 warm steady-state decode throughput
> (tokens/sec), reported per workload class, aggregated as the geometric mean
> of per-class candidate/baseline ratios.**

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

- `R_c` = (candidate median warm decode tok/s) / (canonical baseline median
  warm decode tok/s) for workload class `c`, per §10.
- `R_agg` = geometric mean of `R_c` over the four frozen workload classes.
  Geometric, because these are ratios and the aggregate must not be dragged
  by whichever class is fastest in absolute tokens/sec.
- **Significant** = the bootstrap 95 % CI on the ratio excludes `1.000`
  (§10).

### GO

**All** of the following:

| # | Condition |
|---|---|
| G1 | All mechanism gates F1–F6 pass |
| G2 | All correctness gates C1–C4 pass |
| G3 | Reproducibility rules satisfied: baseline CV ≤ 5 % in every class, both sessions completed, no early stopping (§10) |
| G4 | `R_agg ≥ 1.20`, **and** the 95 % CI lower bound on `R_agg` is `≥ 1.10` |
| G5 | **Every** class is significant with `R_c ≥ 1.05` — the mechanism helps everywhere, not on average |
| G6 | TTFT ≤ `1.25x` baseline **and** prefill throughput ≥ `0.80x` baseline, in every class |
| G7 | The Issue #5 complete-layer breakdown (dispatch → per-device execution → combine) exists for **both** arms and is consistent with the end-to-end result |

**Why +20 %, with the CI floor at +10 %.** This is an architecture proof, not
a production target, so the bar must be well below the ~2x a mature scaling
result would demand — issue #1 explicitly rejects a 2x requirement. But it
must also be well above "we added an entire second GPU for a rounding error".
Two anchors set the value:

- *From below:* with the reproducibility rules of §10 (CV ≤ 5 %, n = 10,
  median), the 95 % CI half-width on a class ratio is roughly ±5 %. A
  threshold at +5–10 % would sit inside the measurement's own uncertainty,
  which is how "statistically indistinguishable" gets reported as success.
  +20 % with a +10 % CI floor is unambiguously outside that band.
- *From above:* the mechanism's theoretical headroom is large. Under the
  canonical baseline a substantial share of decode time is PCIe expert
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
| **B — mechanism wins, overhead eats it** | Per §8 Rule A the intrinsic cross-device path is cheaper than the baseline's miss path, but scheduler/synchronization/dispatch overhead consumes the gain |
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
| N4 | `R_agg < 1.00` beyond noise — the candidate is slower than the canonical baseline |
| N5 | Per §8 Rule B: the intrinsic cross-device path (remote execution + result return, **excluding all dispatch/sync/combine overhead**) is already no cheaper than the baseline's PCIe-fetch/CPU-execute path for the same expert touches |
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

Issue #5 requires the complete-layer breakdown for both arms:

```
candidate, per MoE layer per decode step:
    t_dispatch → t_remote_exec → t_return → t_combine → t_sync
    (plus t_local_exec on GPU 0)

canonical baseline, per MoE layer per decode step:
    t_miss_detect → t_pcie_fetch  or  t_cpu_exec → t_local_exec
```

Define, over the same set of expert touches in the same measured window:

```
INTRINSIC  = t_remote_exec + t_return
OVERHEAD   = t_dispatch + t_sync + t_combine
BASE_MISS  = t_pcie_fetch + t_cpu_exec
```

**Rule A — implementation failure.** If `INTRINSIC < BASE_MISS` but the
candidate misses GO, then executing an expert on the other card and shipping
the result back is genuinely cheaper than the baseline's miss path, and the
loss lives in `OVERHEAD`. That is an implementation problem. ITERATE is
available, subject to I4–I6.

**Rule B — architectural failure.** If `INTRINSIC ≥ BASE_MISS` — that is, the
cross-device path loses *even after every gram of prototype overhead is
excluded* — then no amount of implementation polish changes the sign on this
hardware. **NO-GO (N5).** No ITERATE case may be invoked against Rule B: an
ITERATE justified by removing overhead that is already excluded from the
comparison is circular.

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

Rule B is deliberately the harshest reading available, and it exists because
"the prototype was rough" is the easiest story to tell about any
disappointing result. Excluding overhead entirely is the only way to ask the
architecture question separately from the implementation question.

---

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

**Sessions and ordering.** Two full sessions. Session 1 interleaves
`A/B/A/B…`; session 2 runs on a different day and thermal state with the
order reversed. Interleaving keeps thermal drift symmetric between arms
rather than assigned to whichever arm ran second.

**Primary statistic.** Median of the per-rep decode tok/s within each
(configuration, class, session). Median rather than mean because a single
background process or scheduler hiccup skews a mean at `n = 10`, and this is
a desktop, not a cluster.

**Aggregation.** `R_c` = candidate median / baseline median, per class.
`R_agg` = geometric mean of the four `R_c`.

**Session agreement.** Both sessions are evaluated independently. If they
disagree, **the worse verdict stands** and the disagreement is reported.

**Uncertainty.** Bootstrap 95 % CI (10,000 resamples over the per-rep values,
resampling within class, recomputing the geometric mean) on `R_agg` and on
every `R_c`. A difference **counts only if its 95 % CI excludes 1.000**.

**Variance reporting.** For every (configuration, class): min, median, max,
IQR, and coefficient of variation.

**Noise-floor guard.** If baseline **CV > 5 %** in any class, the environment
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

These rules are what make §7's thresholds meaningful: with CV ≤ 5 % and
n = 10 the 95 % CI half-width on a class ratio is roughly ±5 %, so the +20 %
GO threshold and its +10 % CI floor sit clearly outside run-to-run noise,
while the ITERATE floor at +5 % is exactly where "real but small" begins.

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
- **Startup bound.** If candidate M-start exceeds baseline M-start by more
  than **3x** or by more than **180 seconds absolute**, the verdict is
  recorded as **GO-with-caveat** (or ITERATE-with-caveat) and the report must
  name a remediation. It does not by itself block GO — it is genuinely a
  one-time cost — but an unbounded startup cost is a real usability problem
  and naming it is the honest treatment.
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

Redefining the canonical baseline — for instance, deciding that the TP
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
| **1** | **Mechanism validity** (F1–F6) | All pass: GPU 1 holds ≥ 25 % of combined expert bytes; ≥ 20 % of decode expert executions on GPU 1 in every class; one payload per (device, layer, step); host→GPU-1 steady-state traffic < 1 % of weight-streaming equivalent; zero fallback events | F1, F2, F4, F5, F6 pass; **F3 may fail** and be named as the case-E bottleneck | F1, F2, F4, F5, or F6 fails ⇒ **INVALID**: the run is not evidence about H1 in either direction |
| **2** | **Correctness** (C1–C4) | C1 within `rtol/atol 2e-3` with deviation reported; C2 exact; C3 first 64 greedy tokens identical + step-0 argmax/top-5 identical; C4 zero NaN/Inf | Identical requirement — correctness is never traded | Any failure ⇒ **NO-GO** for that build; a verdict is possible only after fix + full campaign re-run |
| **3** | **Reproducibility** (§10) | Baseline CV ≤ 5 % in every class; both sessions completed; no early stopping; no rep discarded | Same | Violation ⇒ **INVALID**, re-run required |
| **4** | **Decode performance** | `R_agg ≥ 1.20` with 95 % CI lower bound ≥ 1.10; **every** class significant with `R_c ≥ 1.05` | Significant `R_agg ∈ [1.05, 1.20)`, **or** a §7 case B/C/D/E — **and** I4–I7 satisfied, including no class below `0.95` | CI includes 1.000; or `R_agg < 1.05`; or `R_agg < 1.20` with no ITERATE case; or slower than baseline beyond noise |
| **5** | **TTFT / prefill** | TTFT ≤ 1.25x baseline **and** prefill ≥ 0.80x baseline, every class | TTFT ∈ (1.25x, 1.60x] or prefill ∈ [0.60x, 0.80x) with a named cause and decode meeting G4/G5 | TTFT > 1.60x or prefill < 0.60x — the tradeoff is unbounded |
| **6** | **Full-layer evidence** (issue #5) | Breakdown present for **both** arms and consistent with the end-to-end result | Breakdown present for both arms and identifies the named bottleneck | Missing, single-arm, or contradicting the end-to-end result ⇒ **INVALID** |
| **7** | **Architecture vs. implementation** (§8) | n/a — GO does not need this distinction | Rule A: `INTRINSIC < BASE_MISS`, loss is in `OVERHEAD` | Rule B: `INTRINSIC ≥ BASE_MISS` ⇒ **NO-GO (N5)**. Rule C: benefit confined to a single class (≥ 3 classes with no significant gain) ⇒ **NO-GO (N6)** |
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
- a roadmap review. If Rule B fired — the intrinsic cross-device path is not
  cheaper on this hardware — then Phases 2 and 4 inherit that finding, and
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
- [ ] The canonical baseline is the measured winner of B1–B5, and all five are
      published
- [ ] Held-constant list (§2.3) recorded as *resolved* values, both arms
- [ ] No §3 prohibition violated
- [ ] F1–F6 evaluated and reported before any performance number
- [ ] C1–C4 evaluated; C1 deviation reported as a number, not just a verdict
- [ ] C3 self-consistency precondition checked before the candidate ran
- [ ] Primary metric is warm batch-1 decode; no microbenchmark contributed to
      the verdict
- [ ] Four frozen workload classes, hash-pinned before candidate benchmarking;
      any drop recorded with reason
- [ ] n = 10, two sessions, interleaved, medians, bootstrap CIs, CV reported,
      no rep discarded, no early stopping
- [ ] M-start / M-warm / M-cold reported separately; startup not amortized
- [ ] CUDA-graph status stated; no subtraction arithmetic anywhere
- [ ] Coverage, hit rate, and throughput reported as three separate quantities
- [ ] Any TP run labelled secondary/contextual
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
7. **Whether baseline greedy decoding is bit-reproducible run-to-run** on this
   runtime — checked by the C3 self-consistency precondition, with a defined
   fallback if it is not.
