# P0-I — Qwen3.6 routing and expert-residency evidence

```
Label: MEASURED CANONICAL EVIDENCE
Verdict: PASS
Date: 2026-08-27
Canonical issue: #3 — Instrument Qwen3.6 MoE routing and residency behavior
```

This document publishes the Phase-0 P0-I routing/residency result for
`nvidia/Qwen3.6-35B-A3B-NVFP4`. It supersedes the Qwen-specific cache-pressure
speculation in the historical feasibility investigation with measured routing and cache
behavior. It does **not** claim a Phase-1 speedup: remote-GPU transport, execution,
synchronization, overlap, and end-to-end two-GPU performance remain unmeasured until
Phase 1.

Evidence labels used below:

- **[MEASURED]** — directly observed in the valid canonical P0-I artifact;
- **[CALCULATED]** — arithmetic derived from measured counts/traces;
- **[SPEC]** — hypothesis that still requires the Phase-1 mechanism/campaign.

## Canonical run identity

- **[MEASURED]** FreeToken commit: `a42c03ce0233451df699cfd6c4e09573751c067f`
  (PR #5 merged into `inferswarm` before measurement).
- **[MEASURED]** InferSwarm methodology commit: `0807842ce4cfd587ec77c5605cb61ed955dc3a11`.
- **[MEASURED]** model: `nvidia/Qwen3.6-35B-A3B-NVFP4`.
- **[MEASURED]** model revision: `491c2f1ea524c639598bf8fa787a93fed5a6fbce`.
- **[MEASURED]** workload manifest: `phase0-v1-2026-08-27`.
- **[MEASURED]** manifest SHA-256:
  `10f81e5418a71a68f387632de422c3337cc7ba0518111a8746ad856d0210b24a`.
- **[MEASURED]** physical GPU UUID:
  `GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55` (RTX 3060 12 GB).
- **[MEASURED]** `memory_ratio=0.85`, `kv_reserve_tokens=17075`, MoE backend
  `offload`, NVFP4 backend `triton`.
- **[MEASURED]** canonical observations: **288 expected / 288 observed / 0 missing**.
- **[MEASURED]** final run verdict: `VALID CANONICAL CAMPAIGN`.

Raw source-artifact integrity:

| Artifact | SHA-256 |
| --- | --- |
| complete canonical run archive | `7bb8e55b9abb10eab4168cef6df50b76057668469e3ded214c40d6ff62cd254a` |
| `run.json` | `1ecd14c8c157eb6cde62f8514b8f2af82a36dfe69e3a7241f5be6c9908e539dc` |
| `exact-routing.jsonl` | `4071e2bfd3c18f39e5c5a0b5ff8913ca0fb99b843cf7abca0ecc1f4ebd0a252f` |
| `cache-pressure.jsonl` | `f02d96a079a6af94b3fec9d2c571322a1274cd408a3a9ff2ef162f538babab3a` |

The raw archive remains a byte-preserved host artifact. Repository publication uses only
sanitized routing/count evidence: no prompt text, generated output text, hostname, or
host-local model path belongs in the committed public evidence.

## Measured miss-rate vs cache-fraction curve

The cache-pressure server used graph-safe cache counters with exact trace capture disabled.
Each point was predeclared from authoritative minimum `M=256` and auto-resolved feasible
size `A=3774`; no point was selected after observing a miss rate.

| Expert slots | Expert-slot coverage | Active selections | Misses | Miss rate | Hit rate |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 256 | 2.50% | 4,492,800 | 4,492,800 | **100.00%** | **0.00%** |
| 1,135 | 11.08% | 4,492,800 | 2,052,072 | **45.67%** | **54.33%** |
| 2,015 | 19.68% | 4,492,800 | 1,425,226 | **31.72%** | **68.28%** |
| 2,894 | 28.26% | 4,492,800 | 968,553 | **21.56%** | **78.44%** |
| 3,774 | 36.86% | 4,492,800 | 660,925 | **14.71%** | **85.29%** |

All values in this table are **[MEASURED]** except hit rate, which is
**[CALCULATED]** as `1 - miss_rate`.

The minimum 256-slot point is a particularly useful boundary result: every measured routed
selection missed. The runtime still completed the workload, proving a functional host-backed
floor even when the LRU cache contributes no measured hits. P0-I deliberately does not label
console token/s from this investigation as canonical performance evidence; Phase-0 B1 remains
the performance baseline.

## Per-workload miss rates

| Class | 256 slots | 1,135 slots | 2,015 slots | 2,894 slots | 3,774 slots |
| --- | ---: | ---: | ---: | ---: | ---: |
| W1 — coding/agentic | 100.00% | 44.33% | 29.47% | 19.76% | **13.00%** |
| W2 — reasoning | 100.00% | 47.60% | 34.25% | 22.43% | **14.95%** |
| W3 — long context | 100.00% | 44.84% | 31.37% | 22.22% | **15.87%** |
| W4 — short interactive | 100.00% | 45.03% | 31.31% | 23.97% | **18.31%** |

**[MEASURED]** The same qualitative curve appears in all four frozen workload classes. The
highest-capacity point is not equivalent to perfect locality: even with 36.86% of expert slots
resident, 13.00–18.31% of routed selections still miss depending on workload.

## Exact-routing concentration

Exact routing was captured separately in eager mode so CUDA graph replay could not hide or
corrupt route order. The exact traces cover all W1–W4 classes and retain selected expert IDs
by decode step, MoE layer, token row, and router top-k order.

From those **[MEASURED]** route histograms, the following static hot-set coverage is
**[CALCULATED]**:

| Static `(layer, expert)` slots retained | Fraction of all observed selections covered |
| ---: | ---: |
| 256 | 14.62% |
| 1,135 | 39.85% |
| 2,015 | 56.62% |
| 2,894 | 69.01% |
| 3,774 | 78.44% |

Per-workload static coverage is more concentrated:

| Class | Unique routed slots | Top 256 | Top 1,135 | Top 2,015 | Top 2,894 | Top 3,774 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| W1 | 9,005 | 21.19% | 52.14% | 69.78% | 81.00% | **88.43%** |
| W2 | 9,460 | 26.37% | 54.58% | 69.35% | 79.35% | **86.52%** |
| W3 | 8,081 | 21.56% | 51.21% | 68.93% | 80.79% | **88.80%** |
| W4 | 6,931 | 23.59% | 55.41% | 72.97% | 84.39% | **91.82%** |

These static-coverage numbers are not predicted cache hit rates. They answer a different
question: how much observed route demand would lie inside a fixed set if the set were chosen
with hindsight from the Phase-0 trace. The difference between static coverage and measured
LRU hit rate is itself evidence that both frequency locality and temporal locality matter.

## Hottest measured slots

The global histogram is not dominated by one or two experts. Even the hottest individual
slot contributes only 0.15% of observed selections. The top ten are:

| Rank | MoE layer | Expert | Selections | Global share |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 25 | 13 | 6,940 | 0.15% |
| 2 | 31 | 229 | 5,792 | 0.13% |
| 3 | 28 | 243 | 5,538 | 0.12% |
| 4 | 13 | 13 | 5,237 | 0.12% |
| 5 | 9 | 207 | 4,993 | 0.11% |
| 6 | 25 | 210 | 4,802 | 0.11% |
| 7 | 19 | 229 | 4,615 | 0.10% |
| 8 | 17 | 2 | 4,589 | 0.10% |
| 9 | 21 | 100 | 4,355 | 0.10% |
| 10 | 20 | 144 | 4,238 | 0.09% |

**[MEASURED]** This is broad skew rather than a tiny handful of universal experts. Phase-1
placement therefore needs thousands of resident slots to capture a large fraction of demand;
a toy placement of a few dozen hot experts would not represent the measured workload.

## What P0-I changes

The historical feasibility investigation treated Qwen3.6 as a control case and said
multi-GPU expert tiering had zero value because the compact full expert set can fit in the
VRAM capacity of a 24 GB RTX 3090. P0-I shows why that statement must not be generalized to
12 GB commodity GPUs:

- **[MEASURED]** the selected RTX 3060 auto-resolves only 3,774 / 10,240 expert slots
  (36.86%) under the frozen Phase-0 runtime geometry;
- **[MEASURED]** that capacity still incurs a 14.71% weighted miss rate;
- **[CALCULATED]** workload-specific static placement at the same slot count covers
  86.52–91.82% of observed routes;
- **[SPEC]** resident execution on a second RTX 3060 may replace a meaningful part of the
  remaining host-backed service and improve end-to-end decode, but only the Phase-1 A/B can
  establish that performance claim.

So Qwen3.6 is no longer merely a "multi-GPU unnecessary" control on the actual Phase-1
2×12 GB rig. It is a measured capacity-constrained expert-residency case on one RTX 3060 and
therefore a valid two-GPU POC target.

## Phase-1 placement consequence

P0-I supports a deterministic placement derived before any Phase-1 candidate throughput is
observed. The placement policy is specified separately in
[`phase1-placement-policy.md`](../implementation/phase1-placement-policy.md).

The policy intentionally distinguishes two artifacts:

1. a **global-hot diagnostic placement**, useful for describing raw frequency skew; and
2. the **canonical complementary placement**, which reserves a workload-balanced static
   proxy for GPU-0-local demand and assigns GPU 1 from the next hottest unique slots. This
   avoids deliberately duplicating the hottest primary-capacity proxy on both devices.

The exact expert list is generated mechanically from the sanitized P0-I histogram and
hash-pinned before Phase-1 candidate performance measurement. It is not hand-edited after a
benchmark result.

## Issue #3 acceptance mapping

- **Routing traces for ≥2 workload classes:** PASS — W1, W2, W3, and W4 captured.
- **Measured miss-rate-vs-cache-fraction curve:** PASS — five predeclared points from 2.50%
  through 36.86% coverage.
- **Findings summarized with evidence labels/speculation separated:** PASS — this document.
- **FreeToken instrumentation PR links back:** PASS — FreeToken PR #5.
- **Anonymized publication:** the repository retains sanitized histogram/placement evidence;
  raw host-local run material is integrity-addressed by the SHA-256 values above rather than
  copied verbatim.

P0-I therefore resolves the routing/cache uncertainty that blocked evidence-derived Phase-1
placement. It does not pre-judge the Phase-1 GO/ITERATE/NO-GO result.
