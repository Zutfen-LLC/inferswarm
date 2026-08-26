> **Provenance note.** This investigation originated during the initial
> FreeToken feasibility study, before the standalone InferSwarm repository
> existed. It is preserved here verbatim as historical research input: its
> findings informed the InferSwarm roadmap and ADRs, but it is **not the
> final architecture contract**, and its estimates and speculation remain
> labeled as such ([EST]/[SPEC] markers below) — none of its performance
> figures have been measured on the target hardware. It is unmodified except
> for this header. Where its recommendations were adopted or superseded, see
> the [ADRs](../adr/README.md) and [ROADMAP.md](../../ROADMAP.md).

# Feasibility: secondary NVIDIA GPUs as an expert-storage/cache tier for MoE inference

**Status:** investigation only, no production code changed.
**Target hardware:** 1× RTX 3090 (24GB) + 3× RTX 3060 (12GB) + 1× RTX 3060 Ti (8GB) = 68GB aggregate, PCIe-only (no NVLink-eligible pair present — RTX 3060/3060 Ti have no NVLink fingers at all, and the lone 3090 has no NVLink partner).

**Revision note:** the first pass of this investigation used Qwen3.6-35B-A3B as the sole test model and found the whole exercise unnecessary for it — at FreeToken's native sub-8-bit formats its entire expert set already fits on the 3090 alone. That finding is correct but was the wrong question: it tells us about the regime where multi-GPU expert tiering *isn't* needed, not whether it's ever useful. This revision keeps Qwen as the **control case** and adds three larger models spanning the regimes where the primary GPU's 24GB genuinely isn't enough, to answer the real question: **at what expert-pool-to-VRAM ratio does the secondary tier start mattering, and which architecture wins when it does?**

Labeling convention: **[CODE]** = verified against source, **[DOC]** = from `docs/*.md`, **[HF]** = fetched from the model's real HuggingFace `config.json`, **[CALC]** = arithmetic derived from [CODE]/[DOC]/[HF] numbers, **[EST]** = order-of-magnitude estimate from general hardware/ML-systems knowledge, not measured on the target rig, **[SPEC]** = speculative, needs a real experiment.

---

## Executive summary

Four models were sized against this hardware, spanning three memory regimes:

| Model | Native/assumed format | Total expert weight | Fits 3090 alone (20GB usable)? | Fits 68GB aggregate (60GB usable)? | Regime |
|---|---|---:|---|---|---|
| Qwen3.6-35B-A3B **(control)** | NVFP4/MXFP4/Q4_0 [CODE] | 16.9 GB [CALC] | **Yes**, 100%+ coverage | Yes | 1 — pool < primary GPU |
| Ling-3.0-flash *(not yet supported by FreeToken)* | NVFP4 [SPEC — hypothetical, model not implemented] | 63.4 GB [CALC from HF config] | No, 31.5% coverage | **Yes, 94.6% coverage** | 2 — pool fits aggregate, not primary |
| DeepSeek-V4-Flash-0731 | FP8 (dense) + DS-FP4 (experts), native shipped format [CODE] | 137.1 GB [CALC] | No, 14.6% coverage | No, 43.8% coverage | 3 — pool >> aggregate |
| GLM-5.2 | native (FreeToken's own comment states the figure) [CODE] | **~407 GB** [CODE, `glm_moe_dsa/config.py:61`] | No, 4.9% coverage | No, 14.7% coverage | 3 — pool much >> aggregate |

This reframes the finding cleanly: **multi-GPU expert tiering has zero value for Qwen-class models (already solved by quantization) and clearly diminishing value as the pool grows past the aggregate 68GB (GLM-5.2: host RAM stays dominant no matter what you do with the secondary GPUs).** The interesting zone is in between — DeepSeek-V4-Flash-0731 (already supported, real cache-hit improvement from 14.6%→43.8% is available but requires the same invasive engineering as before) and especially the hypothetical Ling-3.0-flash, whose expert pool (63.4GB) is almost exactly sized to this specific machine's 68GB aggregate, producing the largest swing of any model studied (31.5%→94.6% cache coverage) — but Ling's architecture isn't implemented in FreeToken at all today, so that result is conditional on a separate, non-trivial model-support effort.

A second finding changes the architecture recommendation from the first pass: activation-vs-weight byte ratios get **more** favorable to Architecture B (remote execution) as models get larger — 217× for Qwen, 325× for Ling, 816× for DeepSeek-V4-Flash — because activation size is fixed by `hidden_size` while expert weight size grows with both `hidden_size` and `moe_intermediate_size`. Combined with the persistent, unresolved uncertainty about real consumer-GPU PCIe/P2P bandwidth (Architecture A's core dependency), **Architecture B becomes the more robust bet for the models where multi-GPU tiering could plausibly matter**, because its cost (small-transfer synchronization latency) is far less topology-sensitive than Architecture A's cost (bulk bandwidth, which depends heavily on exactly which PCIe lanes and root complexes the secondary GPUs land on).

**Recommendation: verdict F, with a specific next step.** The single biggest unknown — real cross-GPU bandwidth and P2P availability on the actual 5-GPU rig — still hasn't been measured (no CUDA toolkit or second discrete GPU was available in this investigation's environment; see Minimal Proof of Concept). That measurement decides between "Architecture A is viable" and "only Architecture B is viable," which is a large fork in engineering cost. If forced to commit without it: **prioritize DeepSeek-V4-Flash-0731 first** (already supported, no new model-porting work, genuine 3× cache-hit improvement available), **build Architecture B, not A** (robust to the topology uncertainty), and treat Ling-3.0-flash as a compelling *second* target that requires implementing Bailing/`bailing_hybrid` model support in FreeToken before any multi-GPU work on it is worthwhile.

---

## Current architecture

*(unchanged from the first pass — the cache/offload mechanics don't depend on which model is loaded)*

```
router (per MoE layer, top-k of N experts)
   │
   ▼
expert_ids tensor  ──────────────────────────────────────────────►  OffloadMoeCache
   │                                                                 (offload_cache.py)
   │                                                     slot_for_id[layer, expert] → slot or -1
   │                                                     id_of_slot[slot] → flat_id
   │                                                     (dense int32 arrays, O(1) lookup,
   │                                                      one shared pool across ALL layers)
   │
   ├─ DECODE (per step, per layer): ensure_experts()/ensure_experts_hybrid() [offload_kernels.py]
   │    global-LRU victim selection (flat id = layer*E+expert), rewrites expert_ids to slot ids,
   │    hybrid caps fetch to hybrid_fetch_fraction ("q*"), overflow → CPU executor.
   │    copy_missing() → fast_index_copy_multi_jit: one fused kernel launch, GPU-initiated read
   │    directly from pinned/registered host pointers, on the CURRENT/compute stream (no
   │    dedicated decode copy stream, no decode-side double buffering).
   │
   ├─ PREFILL (per chunk, per layer): materialize_layer() unconditionally reloads the WHOLE
   │    layer's expert set every prefill pass regardless of prior cache residency. Hit rows come
   │    from device-to-device copy (HBM bandwidth); true misses cross PCIe via cudaMemcpyBatchAsync.
   │    prefill_overlap mode double-buffers layer L+1's copy against layer L's compute via a
   │    dedicated prefill_copy_stream + paired CUDA events — the only true double-buffering
   │    in the codebase.
   │
   ▼
grouped GEMM on the quant-format kernel (fused_mxfp4/nvfp4/fp8_block/q4_0/ds_fp4) → output
```

**Backends** (`docs/models.md:20-32`): `fused` (all experts resident, never auto), `offload` (host RAM + GPU LRU cache), `cpu` (misses computed on CPU), `hybrid` (per-step split, calibrated by `ft bench bw`'s measured CPU-vs-PCIe bandwidth ratio — the paper's "q\* policy", concretely `hybrid_fetch_fraction` in `moe/bench_profile.py`).

---

## Single-GPU assumptions

*(unchanged from the first pass — this is model-agnostic engine architecture, not something the model-target pivot affects)*

| Component | Code location | Assumption | Difficulty to generalize |
|---|---|---|---|
| CLI GPU selection | `server/args.py:634-639` | `--gpu` parser already accepts a list (`gpu_select.py:587-593`) but rejected unless `--tensor-parallel-size > 1` | Trivial — policy gate |
| Device binding | `gpu_select.py:773-791`, `engine.py:294-298` | One `torch.cuda.set_device()` per process (one process per TP rank) | Trivial — already the multi-GPU mechanism, for TP |
| VRAM budget | `engine/cache_budget.py`, `engine.py:707-726` | Per-rank `mem_get_info` + cross-rank `all_reduce(MIN)` | Trivial for equal-VRAM TP peers; **not designed for heterogeneous VRAM sizes** (24/12/12/12/8GB) |
| CUDA graphs | `engine/graph.py:94-198` | One graph pool per rank/device; cross-rank comm via NCCL-on-stream inside capture | Trivial for TP; **major** for ad hoc cross-device copies inside a captured decode graph |
| KV cache pools | `kvcache/*.py` | One `_device` per pool instance | Trivial |
| Checkpoint format/conversion | `checkpoint/convert.py:174-195` | TP-agnostic FTW format; conversion is single-process | Moderate — deliberate simplification, not a serving blocker |
| **MoE expert-offload cache** | `moe/offload_cache.py`, `offload_kernels.py`, `expert_banks.py`, `host_banks.py` | Single `torch.device`; flat `[cache_size]` slot pool; global LRU over one flat id space; **zero references to `tp_info`/`rank` anywhere in these files** | **Major architectural constraint / likely blocker.** Under existing TP, each rank independently builds its own full host-RAM cache — no cross-device cache sharing exists at any layer of this stack. |
| CPU MoE kernel | `kernel/csrc/cpu_moe/cpu_moe_ext.cpp:1094-1095` | Explicitly single-NUMA-node; no GPU-topology awareness anywhere in `moe/`/`engine/` | Moderate (NUMA) / n/a for GPU topology, since none exists |

**Bottom line, unchanged:** FreeToken already has real multi-GPU support (tensor parallelism — NCCL, per-rank sharding, per-rank CUDA graphs), but it solves a different problem (replicate/shard one model across *equal-ish* GPUs) and is completely unaware of the expert-offload cache. None of the four models in this revised study change that structural fact — the engineering gap is the same regardless of which model sits on top of it.

---

## Hardware analysis: 3090 + 3×3060 + 3060 Ti

*(unchanged core argument from the first pass, still the dominant constraint regardless of model choice)*

- **NVLink is moot** — no eligible pair exists in this rig. **[EST]**
- **Consumer motherboard lane budget is the sharpest constraint, independent of FreeToken's code.** A mainstream desktop CPU exposes ~20–24 PCIe lanes total; fitting 5 discrete GPUs means most secondary slots run at x4 or narrower, or sit behind the chipset's shared DMI uplink. Realistic secondary-GPU bandwidth is plausibly 3–8GB/s, not the ~24GB/s a PCIe4 x16 headline number implies. **[EST]**
- **Consumer GPU P2P is unreliable, not simply on/off** — `cudaDeviceEnablePeerAccess` between GeForce cards can work when both share a root complex/switch with compatible ACS/IOMMU settings, but silently falls back to a host-staged two-hop copy otherwise, which is worse than FreeToken's existing single-hop host-RAM path. **[EST]**
- **Host RAM is already bigger and closer than the secondary GPUs' 44GB** for any model whose need is *capacity*, undermining Architecture A's core value proposition regardless of which model runs. **[EST]**
- **New this revision — Ling-3.0-flash's router hints at a mitigation for Architecture B specifically.** Its real config **[HF]** shows `n_group: 8`, `topk_group: 4` — a DeepSeek-style grouped top-k router that first selects 4 of 8 expert groups, then routes within them (512 experts / 8 groups = 64 experts/group). If expert *groups* (not individual experts) are pinned to physical GPUs — e.g. 2 groups per secondary GPU — a token's forward pass touches at most `topk_group=4` groups instead of potentially all 512 experts' worth of devices, meaningfully bounding the cross-GPU fan-out Architecture B would otherwise incur. This is a real, source-grounded architectural affordance, but its magnitude (how many *distinct* GPUs get touched per layer in practice) depends on the model's actual routing distribution and hasn't been measured. **[SPEC]** No equivalent grouped-routing field was found for DeepSeek-V4-Flash-0731 or GLM-5.2 in the traces performed — those would route more uniformly across whichever placement is chosen, unless similar structure exists that wasn't checked.

---

## Model Size Regimes

**[CODE]/[HF]/[CALC]** exact figures, computed with FreeToken's own per-format byte formulas (`offload_cache.py:36-89`, extended per-model where the source agent captured a different formula, e.g. GLM-5.2's `expert_bank_row_bytes` in `glm_moe_dsa`'s AOT table):

| Model | Total params | Active params | Expert bytes (native/assumed fmt) | Fits 3090 (20GB usable)? | Fits 68GB aggregate (60GB usable)? | Expected multi-GPU value |
|---|---:|---:|---:|---|---|---|
| **Qwen3.6-35B-A3B** | ~35B (implied by name; not stated in-repo) | ~3B (implied by "A3B"; not stated in-repo) | 16.9GB (NVFP4/MXFP4/Q4_0) | **Yes**, 100%+ | Yes | **Control / none** |
| **Ling-3.0-flash** | 124B [SPEC, from HF model card, not verified against a param-count field — Ling's config.json carries no total/active-param field either] | 5.1B [SPEC, same caveat] | 63.4GB (NVFP4, hypothetical — FreeToken doesn't support this architecture) | No, 31.5% | **Yes, 94.6%** | **Potentially the largest swing of any model studied — but conditional on new model support** |
| **DeepSeek-V4-Flash-0731** | ~285B [CALC, derived from `args.py` fields — not stated in-repo] | ~8–10B [CALC, derived — not stated in-repo] | 137.1GB (FP8 dense + DS-FP4 experts, native shipped format) | No, 14.6% | No, 43.8% | **Real, measurable-in-principle improvement (3× cache-hit); already supported today** |
| **GLM-5.2** | not stated in-repo | not stated in-repo | **~407GB**, FreeToken's own source states this figure (`glm_moe_dsa/config.py:61`, a comment on a dev-only layer-cap knob: *"pinning the full ~407 GB of experts"*) | No, 4.9% | No, 14.7% | **Modest — host RAM remains dominant regardless of secondary-GPU tiering** |

Per-expert byte sizes and slot counts behind this table:

| Model | H (hidden) | I (expert intermediate) | Layers × Experts = slots | Bytes/expert | Format |
|---|---:|---:|---:|---:|---|
| Qwen3.6-35B-A3B | 2048 | 512 | 40 × 256 = 10,240 | 1.69 MiB (NVFP4) | native |
| Ling-3.0-flash | 2560 | 768 | 40 × 512 = 20,480 | 3.17 MiB (NVFP4) | hypothetical |
| DeepSeek-V4-Flash-0731 | 4096 | 2048 | 43 × 256 = 11,008 | 12.75 MiB (DS-FP4) | native |
| GLM-5.2 | 6144 | 2048 | ~20,561 (backed out from the 407GB figure) | 20.27 MiB (NVFP4) | native (per `aot_models.py`) |

**Important caveats attached to every number above:**
- None of the four models' total/active parameter counts are stated anywhere in FreeToken's source — the "35B-A3B", "124B/5.1B", etc. figures come from model names/HF cards, not from FreeToken. The `~8–10B active` figure for DeepSeek-V4-Flash-0731 and the total-param figures are this investigation's own arithmetic from `args.py`'s dataclass fields (params-per-expert × active/total expert counts), not something FreeToken asserts. **[CALC]**
- **Ling-3.0-flash's expert-bytes figure is doubly hypothetical**: FreeToken does not implement the `bailing_hybrid`/`BailingMoeV3ForCausalLM` architecture at all, so "63.4GB in NVFP4" assumes FreeToken's existing NVFP4 packing scheme would apply unchanged to a model it has never quantized. The geometry-only arithmetic (H, I, expert count → bytes) is solid; the packaging assumption is not verified.
- Ling's real config **[HF]** also revealed it isn't plain MHA as first summarized — it uses an MLA-style compressed KV path (`kv_lora_rank=512`, `qk_rope_head_dim=64`), which matters a lot: naive MHA math would put its KV cache at ~22GB at 32K context (unworkable against a 68GB budget with 63GB already spent on experts), but the actual MLA-compressed KV cache is **[CALC]** only ~1.5GB at 32K context and ~5.9GB at 128K context — small enough that Ling's "94.6% of experts fit in the aggregate" headline number survives realistic KV budgeting with room to spare.
- DeepSeek-V4-Flash-0731's dense/attention layers use MLA already (`num_kv_heads=1`, a single shared latent), so its KV cache is likewise compact relative to its huge expert pool — the bottleneck for this model is entirely expert-weight residency, not KV cache. **[CODE]**

---

## Weight movement vs. activation movement — quantified per model

**[CALC]**, bf16 activations, round-trip (hidden state in + expert output out) per single expert invocation, vs. that model's native/assumed per-expert weight size:

| Model | Activation round-trip | Weight/expert | Ratio (weight ÷ activation) |
|---|---:|---:|---:|
| Qwen3.6-35B-A3B | 8,192 bytes | 1.69 MiB | **217×** |
| Ling-3.0-flash | 10,240 bytes | 3.17 MiB | **325×** |
| DeepSeek-V4-Flash-0731 | 16,384 bytes | 12.75 MiB | **816×** |

The ratio *grows* with model size because activation cost scales with `hidden_size` alone while weight cost scales with `hidden_size × moe_intermediate_size`. This is the strongest single argument in this report for preferring **Architecture B (remote execution)** over **Architecture A (weight caching)** as models get larger — precisely the regime where multi-GPU tiering starts to matter at all. For DeepSeek-V4-Flash-0731, moving activations instead of weights cuts PCIe traffic per expert-touch by ~three orders of magnitude.

The catch, unchanged from the first pass: at batch=1 decode this becomes a **latency**, not bandwidth, problem. **[CALC]** With top-k experts per layer likely spanning most/all of the secondary GPUs under naive placement (e.g. DeepSeek-V4-Flash-0731's top-6-of-256 spread across 4 secondary GPUs, or Ling's top-8-of-512 — mitigated somewhat by its grouped router, see Hardware analysis above), a reasonable estimate is on the order of 100–200 cross-GPU dispatch/sync round-trips per decode token (batched per-GPU-per-layer). At an **[EST]** 20–50µs/hop synchronization cost (no NVLink, PCIe-only, likely CPU-mediated event signaling on consumer boards), that's roughly 2–10ms/token of pure overhead — a cost that scales with layer count and GPU fan-out, not model size directly, so it hits DeepSeek-V4-Flash-0731's 43 layers and Ling's 40 MoE layers similarly. Whether that's acceptable depends on the model's baseline per-token compute latency, which is larger for bigger active-param-count models — meaning the relative overhead of Architecture B's synchronization cost likely shrinks (as a fraction of total token time) for the larger models it's most relevant to. **[SPEC]** — no real measurement exists to confirm the actual per-hop latency on this hardware.

---

## Expert-cache pressure analysis

This section is necessarily the most speculative in the report: **no MoE routing traces for any of these four models were available to this investigation**, and none of FreeToken's benchmark tooling (`benchmarks/bench_offload_cache_copy.py`, `moe/benchbw.py`) captures real routing locality — they measure copy-path bandwidth at synthetic/parameterized miss rates, not actual expert-popularity distributions from real prompts. **[CODE]** Everything below is a framework for reasoning about the question, not measured data.

What determines whether a given cache-size fraction (e.g. "43.8% of DeepSeek-V4-Flash-0731's experts resident") translates into a *similar* miss rate, or something better/worse:

- **If routing were perfectly uniform random** across all experts, cache-hit rate for a Global-LRU cache holding fraction *f* of the total slots would (after warmup, with reuse across a token's neighbors' routing) roughly track *f* itself, possibly slightly better due to intra-request locality (a batch of related tokens is more likely to re-hit whatever was just loaded, before the LRU clock evicts it).
- **Real MoE routers are not uniform.** Public research on trained MoE models generally reports mild-to-moderate expert-popularity skew (a long-tail of frequently-used experts and a cold tail), and load-balancing auxiliary losses used in training exist specifically to *prevent* extreme skew — meaning cache-hit rate for a fixed cache fraction is plausibly somewhat *better* than the naive uniform estimate, but not dramatically so, for a well-trained router at production scale. This is a general characterization from ML-systems literature, not something specific to any model traced in this investigation, and should be treated as directional only. **[EST]**
- **Coding-agent workloads specifically** (FreeToken's own stated target use case, per its Anthropic/OpenAI-compatible tool-calling API support) plausibly show *more* expert-reuse locality than open-ended chat, if particular code/reasoning "modes" consistently activate overlapping expert subsets across a session — but this is a hypothesis about semantic routing correlation, not something this investigation can verify without running real traffic through an instrumented cache. **[SPEC]**
- **The actionable conclusion:** the cache-coverage percentages in the Model Size Regimes table (e.g. DeepSeek-V4-Flash-0731's 14.6%→43.8%) are a reasonable *floor* on the achievable improvement from adding the secondary tier, since real routing locality, if present, would only make a bigger cache pay off *more* per byte, not less. They should not be read as a promise of a proportional tokens/sec improvement, since PCIe transfer time for the remaining misses (whatever their true rate is) is what actually gates decode latency.

Recommended first real measurement (cheap, no multi-GPU code required): instrument the existing single-GPU `OffloadMoeCache`'s hit/miss counters (`slot_for_id` lookups already happen every decode step) across a representative session of the target workload (e.g. a real coding-agent transcript replayed through DeepSeek-V4-Flash-0731 at a few different `--moe-cache-size` values), and plot miss rate vs. cache-size fraction empirically. This requires zero new architecture — just logging — and would replace every `[EST]`/`[SPEC]` figure in this section with a real number for the one model that's both native and large enough to matter.

---

## Minimal proof of concept

**Question to answer:** *Is fetching an MoE expert's weights from a secondary GPU's VRAM, or executing it there and shipping back activations, actually faster than FreeToken's existing host-RAM/PCIe or CPU-compute path, on the real 5-GPU rig?*

**Environment note:** this investigation's sandbox has exactly one discrete GPU (an RTX 3060) and no CUDA toolkit or PyTorch installed — `nvcc`, `libcudart.so`, and `torch` are all absent. **None of the three tests below could be executed in this environment.** What follows is a ready-to-run design for the actual target machine; no numbers are fabricated in their place.

- **Test A — pinned host RAM → 3090, expert-weight transfer + execution.** This is FreeToken's existing `offload` backend path; run `ft bench bw` on the real rig to get this baseline directly, no new code needed.
- **Test B — 3060 → 3090, expert-weight transfer + execution.** Allocate a tensor of realistic expert shape (start with DeepSeek-V4-Flash-0731's `[2048,4096]`/`[4096,2048]` gate_up/down shapes at DS-FP4 packing, ~12.75MiB/expert) resident on a 3060; time a `cudaMemcpyAsync`/`cudaMemcpyPeerAsync` to the 3090 with CUDA events. **Critically, also record whether `cudaDeviceCanAccessPeer`/`cudaDeviceEnablePeerAccess` actually succeeds** — if it silently falls back to a host-staged copy, that result alone likely answers whether Architecture A is worth pursuing further.
- **Test C — 3090 activation → 3060 → expert execution → 3090 result.** Ship a `[batch, 2048]`-ish bf16 hidden-state tensor (10–16KB depending on model and batch size) to a 3060, run the grouped-GEMM kernel for one resident expert there, ship the small result back — time the full round trip including both cross-device syncs. This directly tests Architecture B's actual per-hop latency, replacing every `[EST]` synchronization-cost number in this report.
- **Also run, at zero engineering cost:** `nvidia-smi topo -m` and `nvidia-smi topo -p2p r` on the real rig. This alone would confirm or refute the "secondary GPUs likely sit behind narrow/chipset lanes with unreliable P2P" hypothesis this report leans on heavily, in about thirty seconds.
- **Success criterion for Architecture A:** Test B is meaningfully (>~30%) faster than Test A *and* P2P actually engages. **Success criterion for Architecture B:** Test C's round-trip latency is low enough (this report's rough budget: a few ms, given ~100+ hops/token would otherwise cost multiple ms) that a full decode step's worth of remote dispatches wouldn't dominate token latency for a large model. **Failure on both:** stop, and treat the answer as "host RAM + CPU/hybrid offload remains the right architecture on this hardware regardless of model size," i.e. converge back toward the original (Qwen-only) finding even for the larger models.
- This is a few hours of work on the real rig and should run **before** any of the phased roadmap below, exactly as recommended in the first pass — that recommendation is unchanged by the model-target pivot.

---

## Implementation roadmap (if Phase 0 supports proceeding)

**Phase 0 — measurement/instrumentation** (Small): the PoC above (Tests A/B/C + `nvidia-smi topo`), plus the cache-pressure instrumentation described above using DeepSeek-V4-Flash-0731 (already supported, largest native model, and the one with a real, already-quantified cache-hit-fraction upside). No production modules touched.

**Phase 1 — two-GPU PoC (3090 + one 3060), DeepSeek-V4-Flash-0731** (Moderate): if Phase 0 favors Architecture B, prototype remote execution for a single MoE layer's overflow experts on one secondary GPU, measuring real decode tokens/sec against the existing `offload`/`hybrid` baselines. If Phase 0 favors Architecture A instead, prototype a second-tier slot pool on device 1 fed from `OffloadMoeCache`'s eviction stream. Either way, expect to need to disable CUDA graph capture for the affected layers initially (`engine/graph.py` has no precedent for cross-device operations inside a captured graph).

**Phase 2 — generalized multi-GPU expert placement, still DeepSeek-V4-Flash-0731** (Large): extend to all four secondary GPUs with a heterogeneous-capacity-aware placement policy (12/12/12/8GB, unequal).

**Phase 3 — scheduler/cache policy** (Large): integrate with the existing q\*/`hybrid_fetch_fraction` calibration (now three-way: PCIe-to-secondary-GPU, PCIe-to-host, CPU-compute); extend `ft bench bw` to profile per-secondary-GPU bandwidth and per-hop remote-execution latency.

**Phase 4 — heterogeneous optimization + Ling-3.0-flash model support** (Very Large, two independent tracks): (a) load-balance by observed expert popularity across unequal-capacity GPUs for DeepSeek-V4-Flash-0731; (b) **separately**, implement `bailing_hybrid`/`BailingMoeV3ForCausalLM` support in FreeToken (a new model architecture: MLA-with-`kv_lora_rank` attention, grouped top-k MoE routing, per-layer SwiGLU clipping lists) — this is a substantial, self-contained engineering project independent of anything in this report, needed before Ling's compelling "94.6% aggregate coverage" number becomes actionable.

**Phase 5 — production integration** (Very Large): CUDA-graph compatibility, `--gpu` multi-device CLI surface, `/v1/stats` aggregation, failure handling for an absent/busy/thermal-throttled secondary GPU.

**Overall estimate: unchanged from the first pass — Large to Very Large** for a general solution; Moderate for the Phase 0/1 work that actually produces a go/no-go signal. Adding Ling-3.0-flash to the roadmap adds an entire independent Very-Large workstream (model porting) on top of the multi-GPU work itself.

---

## Risks / blockers

*(unchanged from the first pass — none of these are model-specific)*

- **PCIe topology on a 5-GPU consumer board**: likely narrower-than-headline lanes for most secondary GPUs.
- **Lack of reliable P2P**: silent host-staged fallback would erase Architecture A's rationale.
- **CUDA graph constraints**: no precedent in this codebase for cross-device operations inside a captured graph.
- **Device synchronization overhead**: tens of µs/hop, multiplied by potentially 100+ hops/token in Architecture B.
- **Heterogeneous GPU performance**: 12GB/8GB secondary cards have less VRAM *and* less compute than the 3090.
- **Scheduler complexity**: TP (existing) and expert-tiering (proposed) are different multi-GPU axes with zero precedent for combining them.
- **New this revision — model-porting risk for Ling-3.0-flash**: the single most compelling numeric result in this report (31.5%→94.6% cache coverage) is entirely conditional on a model architecture FreeToken has never implemented. Treat it as a strong argument for *prioritizing* Ling support on its own single-GPU merits (it's an unusually well-sized model for consumer hardware even without any multi-GPU work — Qwen-style, it mostly fits after MLA-compressed KV accounting), not as a validated multi-GPU proof point yet.

---

## Final verdict

1. **Can FreeToken reasonably be extended to use all five GPUs for one MoE model?** Technically yes, but the MoE cache internals remain single-device by construction for every model traced — this is unaffected by model choice. Large/Very-Large engineering regardless of target.
2. **Would doing so likely outperform FreeToken's existing 3090 + host RAM/CPU mode?** **Model-dependent, now clearly bracketed**: no for Qwen3.6-35B-A3B (control, confirmed); plausibly yes but unmeasured for DeepSeek-V4-Flash-0731 (14.6%→43.8% cache-hit-fraction improvement is real and available today); plausibly the strongest case of any model studied for Ling-3.0-flash (31.5%→94.6%), but conditional on first porting an unimplemented model architecture; modest at best for GLM-5.2, where host RAM remains dominant even with the full 68GB aggregate (4.9%→14.7%).
3. **Would secondary VRAM primarily be useful for storage, execution, or both?** The larger the model, the more the activation/weight byte ratio (217×→325×→816× across the three models compared) favors **execution** (Architecture B) over storage (Architecture A) — the opposite of what a purely capacity-driven intuition suggests, and a genuinely new finding from this revision.
4. **Is FreeToken a good architectural starting point?** Unchanged: reasonable but not a natural fit — its offload cache is deliberately single-device, and its existing multi-GPU code (TP) solves an orthogonal problem, for any model.
5. **Approximate implementation complexity?** Large to Very Large for a general solution; Moderate for Phase 0/1. Add an independent Very-Large workstream if Ling-3.0-flash support is pursued.
6. **What is the first experiment we should run?** Unchanged and now more urgent: the Test A/B/C proof-of-concept + `nvidia-smi topo -m -p2p` on the real 5-GPU rig — this investigation's sandbox physically cannot run it (one GPU, no CUDA toolkit), so every bandwidth/latency number in this report remains an estimate pending that measurement.
7. **Is this worth engineering?** **Not for Qwen-class models (confirmed). Conditionally yes for DeepSeek-V4-Flash-0731**, pending the Phase 0 measurement, since it's already supported and has a real, quantified cache-hit upside — this is the correct first target, not Qwen and not (yet) Ling. **Ling-3.0-flash is the most numerically compelling case in this study but requires a separate model-porting investment before the multi-GPU question is even answerable for it — pursue that decision on its own single-GPU merits first, independent of this report's conclusions.**
