# Phase-0 P0-D real-serving smoke

```
Status: Active pre-canonical validation
First smoke:  2026-08-27 — intentionally NON_CANONICAL, incomplete
Second smoke: 2026-08-27 — intentionally NON_CANONICAL, incomplete
```

P0-D exists to discover serving-path failures before the two canonical B1–B5 sessions. The
real RTX 3060 smokes are doing exactly that. Their observations are retained as diagnostic
information only; none of their throughput or latency values is a Phase-0 baseline result.

## Frozen inputs

The smokes use the already-frozen Phase-0 inputs:

- model repository: `nvidia/Qwen3.6-35B-A3B-NVFP4`;
- model revision: `491c2f1ea524c639598bf8fa787a93fed5a6fbce`;
- model path on the measurement host:
  `/srv/models/nvidia/Qwen3.6-35B-A3B-NVFP4/491c2f1ea524c639598bf8fa787a93fed5a6fbce`;
- manifest: `docs/benchmarks/workloads/phase0-v1/manifest.json`;
- physical GPU UUID: `GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55`.

Each attempted smoke runs one measured generation, no warmup, for B2 and B3 across W1–W4.
It is explicitly `--dev-smoke` and therefore NON_CANONICAL regardless of outcome.

## Blocker 1 — W3 requires a larger held-constant KV reserve

The first smoke left `--kv-reserve-tokens` unspecified, so FreeToken used its then-current
8,192-token reserve while `--moe-cache-auto` jointly solved the MoE cache and KV pool. On B2
and B3 the live engine reported `moe_cache_size=4224` and `num_pages=8197`. The frozen W3
serving prompt is 16,819 tokens and its frozen completion is 256 tokens, so the request was
correctly rejected before generation.

The Phase-0 campaign therefore freezes this held-constant value **before any canonical
performance measurement**:

```
canonical kv_reserve_tokens = 17,075
                           = 16,819 W3 prompt tokens
                           +   256 W3 completion tokens
```

This is the minimum sequence-capacity reserve that can execute the already-frozen longest
workload at its exact output length. Every B1–B5 arm, P0-D rerun, and correctness-reference
capture must use the same `--kv-reserve-tokens 17075` unless a later reviewed methodology
change explicitly invalidates and reruns the affected measurements.

This does **not** hand-tune an individual baseline arm. FreeToken's auto-cache solver consumes
the reserve and jointly resolves expert slots and KV pages for each backend under the same
held-constant sequence requirement.

It is also important that increasing this value further is **not** a remedy for transient
activation OOM. `kv_reserve_tokens` only redistributes the fixed persistent pool budget between
KV pages and expert slots; it does not increase the VRAM left outside those pools.

## Blocker 2 — overlap scheduling reports fixed-length output one token short

Every successful first-smoke B2/B3 generation was reported one token below the request's exact
fixed length: W1/W2 returned 511 for 512, and W4 returned 127 for 128. The pattern was identical
across both arms and is not accepted by the Phase-0 contract: `ignore_eos=true` means the
requested completion length must be exact.

Source tracing found the defect in FreeToken's overlap scheduler. The overlap loop launches a
future decode forward before draining the previous sampled result. `Engine.forward_batch`
advances the shared request's device-side length for that future forward. The result-drain path
then used the future-looking `not req.can_decode` to decide whether the *previous* sampled token
had exhausted the output budget. On the penultimate token, the already-launched final forward
could therefore make `req.can_decode` false one result too early; that penultimate reply became
the terminal reply and the actual final speculative result was suppressed.

FreeToken PR #3 fixed the boundary by deciding length exhaustion from host-appended accepted
output length after the sampled token is drained. Its regression recreates the overlap boundary
and proves token N−1 remains non-terminal while token N carries `finish_reason=length`.

## Blocker 3 — 0.90 memory ratio leaves no W3 GDN activation margin

The second smoke used the fixed 17,075-token KV reserve and the corrected overlap runtime. W3
therefore passed the sequence-capacity gate, but the scheduler then failed inside the Qwen3.6
Gated Delta Network prefill kernel with a CUDA OOM. At the failing allocation:

- the RTX 3060 had 128.12 MiB free;
- `chunk_gated_delta_rule_fwd_h` requested another 128.00 MiB for its chunk-state tensor;
- PyTorch reported approximately 11.45 GiB of the card's 11.63 GiB capacity already in use.

This is a persistent-pool versus transient-activation problem, not a workload-capacity problem.
FreeToken's cache-budget policy explicitly defines `(1 - memory_ratio)` as CUDA-graph/activation
headroom. With the canonical command's previous `--memory-ratio 0.90`, the server reported about
11.49 GiB free before model loading, so the nominal 10% headroom was about 1.15 GiB. Runtime
state, graph capture, executor buffers, and other persistent allocations consumed almost all of
that by the time the long-context GDN prefill reached its 128 MiB chunk-state allocation.

Phase 0 therefore freezes the following held-constant value **before any canonical performance
measurement**:

```
canonical memory_ratio = 0.85
```

The choice is made from capacity evidence, not throughput. Relative to 0.90 and the observed
~11.49 GiB pre-load free-memory baseline, 0.85 removes about 0.574 GiB (~588 MiB) from the
persistent cache-pool budget. At the same observed W3 allocation point this changes the margin
from roughly 128 MiB to roughly 716 MiB before the 128 MiB allocation. The exact resolved expert
slot count remains FreeToken's job: `--moe-cache-auto` still chooses the largest expert cache
that fits after both the 17,075-token KV requirement and this common activation-headroom policy.

This is not baseline starvation. The anti-starvation rule requires `memory_ratio` to be
identical across arms; it does not require a value that crashes the frozen workload. Every
B1–B5 arm, P0-D rerun, and correctness-reference capture must therefore pass
`--memory-ratio 0.85`. Alternate values are developer experiments, not Phase-0 canonical data.

Two tempting alternatives are explicitly rejected:

- increasing `kv_reserve_tokens` cannot create activation headroom because the MoE+KV pool still
  consumes the same total memory-ratio budget;
- reducing the frozen W3 prompt or output length would change the workload after seeing a
  failure, and is prohibited.

A smaller prefill chunk could reduce the GDN transient allocation, but it would also change the
prefill execution schedule and measured prefill behavior. It is unnecessary while the intended
`memory_ratio` control can provide a common, explicit activation margin, so Phase 0 leaves the
prefill-chunk policy unchanged.

## What did work in the smokes

The incomplete smokes still establish useful operational facts without promoting their timing
numbers:

- the pinned checkpoint loads from `/srv/models`;
- B2 resolves to `hybrid` and consumes the fresh NVFP4 bandwidth calibration;
- B3 `--moe-backend auto` also resolves to `hybrid`, as expected from that profile;
- the selected physical RTX 3060 UUID is used;
- W1, W2, and W4 reach real prefill/decode serving paths;
- the first W3 failure was an explicit sequence-capacity rejection;
- after the 17,075-token reserve was applied, W3 reached the real long-context GDN prefill path;
- the exact-completion overlap defect has a source-level fix and targeted regression.

## Exit gate for P0-D

Rerun only with all three blockers above addressed. P0-D passes when all eight B2/B3 × W1–W4
observations complete with:

- `--kv-reserve-tokens 17075`;
- `--memory-ratio 0.85`;
- zero generation failures;
- exact frozen completion lengths;
- W3 accepted at its 16,819-token serving prompt length and full 256-token completion;
- usable prefill attribution;
- B2/B3 live resolved configuration and GPU identity recorded;
- overall `execution_status=COMPLETE` and `validity=NON_CANONICAL`.

Only after that gate passes do P0-E/P0-F canonical B1–B5 sessions begin.