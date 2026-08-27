# Phase-0 P0-H correctness-reference freeze

```
Status: Binding pre-measurement decision
Date: 2026-08-27
Canonical issue: #2 — Establish reproducible RTX 3060 FreeToken baseline
```

This document resolves the two placeholders intentionally left open in `docs/phase1-poc-success-criteria.md` §2.4 and `docs/implementation/phase0-baseline.md` P0-H before any `CORRECTNESS_REFERENCE` measurement or Phase-1 candidate measurement exists.

It does **not** change the already-selected `CANONICAL_PERFORMANCE_BASELINE`, any Phase-1 performance threshold, any correctness tolerance, any workload, or any candidate verdict rule. The performance baseline was fixed first, by the predeclared B1–B5 rule, and is published separately in `docs/benchmarks/results/phase0/p0ef-canonical-baseline.md`.

## Frozen reference configuration

The Phase-0 correctness reference is:

```text
model repository:    nvidia/Qwen3.6-35B-A3B-NVFP4
model revision:      491c2f1ea524c639598bf8fa787a93fed5a6fbce
physical GPU:        GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55
moe backend:         offload
moe CPU layers:      0
NVFP4 backend:       triton
MoE cache size:      3774 expert slots
memory ratio:        0.85
KV reserve tokens:   17075
workload manifest:   phase0-v1-2026-08-27
sampling:             greedy request override: temperature=0.0, top_p=1.0, top_k=-1
```

Equivalent serving flags owned by the reference arm are:

```text
--moe-backend offload
--moe-cpu-layers 0
--nvfp4-backend triton
--moe-cache-size 3774
```

The common canonical controls remain `--memory-ratio 0.85` and `--kv-reserve-tokens 17075`.

## Why Triton is frozen

The Phase-1 implementation plan requires the GPU-1 resident expert bank to use the same production NVFP4 bank layout/kernel family as `CORRECTNESS_REFERENCE`; the reference therefore cannot remain `auto` or be chosen after candidate output exists.

The actual Phase-0 RTX 3060 campaign resolved B1's hardware-selected NVFP4 path to **Triton**. B1 and forced-Triton B4 consequently collapsed to the same valid offload configuration and that resolved configuration became `CANONICAL_PERFORMANCE_BASELINE`. Nothing in the Phase-1 POC requires installing or forcing Marlin merely to create a different numerical path. The first resident-remote-expert POC is therefore frozen to the same Triton expert-kernel family, and the correctness reference pins `triton` explicitly.

If the Phase-1 POC deliberately changes the remote expert GEMM to another kernel family before canonical candidate measurement, that is a controlled experiment change: the correctness reference must be regenerated under that newly declared backend before candidate correctness can be judged. A candidate run may never retroactively choose which reference backend it prefers.

## Why 3,774 slots is frozen

§2.4 requires a fixed explicit cache size because `--moe-cache-auto` would let the reference's residency vary with ambient allocator conditions or future runtime changes. The cache size changes fetch frequency, not the expert computation being used as the numerical reference.

`3774` is not tuned from correctness output. It is the cache size already resolved independently by the valid canonical B1/B4 performance sessions under the same pinned RTX 3060, model, `memory_ratio=0.85`, and `kv_reserve_tokens=17075` controls. Both sessions proved that size fits with zero CPU MoE layers and the Triton backend. Freezing that already-observed value:

- satisfies the `cache_size >= num_experts` requirement (`3774 >= 256`);
- avoids deliberately shrinking the reference to an artificial minimum cache;
- avoids `--moe-cache-auto` changing the reference between independent captures;
- introduces no new capacity tuning based on candidate results.

The Marlin 992-slot cap is irrelevant because the frozen reference backend is Triton.

## Capture and self-consistency gate

Run the FreeToken `reference` subcommand twice with distinct session IDs. The harness forces the frozen W1-W4 requests to greedy sampling regardless of the performance manifest's sampling values and always stores full generated text.

Both canonical captures must independently be complete and valid. Before the reference may be used by Phase 1:

1. the same pinned model revision, GPU UUID, FreeToken commit, InferSwarm methodology commit, manifest, memory controls, Triton backend, zero CPU layers, and 3,774-slot cache must be recorded in both artifacts;
2. every W1-W4 serving prompt and requested completion length must match the frozen manifest;
3. every generated output must be nonempty and retained;
4. `output_sha256` must match **exactly per workload class across the two independent captures**.

A hash mismatch blocks Phase-1 correctness comparison. It is not repaired by loosening C1/C2/C3 or by selecting whichever reference output resembles a later candidate.

Matching reference text hashes establish only the deterministic fixture prerequisite from §5.3. They do not replace the later candidate-vs-reference per-layer numerical, routing, token, and logit evidence required by C1/C2/C3/C4.

## Anti-goalpost record

At the time of this freeze:

- P0-E/P0-F performance measurement is complete;
- `CANONICAL_PERFORMANCE_BASELINE` is already fixed and published as B1, with B4 an equivalent duplicate of the same resolved offload+Triton configuration;
- no correctness-reference capture has begun;
- no Phase-1 candidate performance measurement exists.

Consequently this decision can neither improve nor worsen the already-selected Phase-0 performance winner. Its only effect is to turn the predeclared §2.4 placeholders into an immutable reproducible correctness fixture before that fixture is measured.
