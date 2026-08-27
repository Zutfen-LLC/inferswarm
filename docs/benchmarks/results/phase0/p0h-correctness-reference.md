# Phase-0 P0-H correctness-reference result

```
Label: MEASURED CANONICAL EVIDENCE
Verdict: PASS
Date: 2026-08-27
Canonical issue: #2 — Establish reproducible RTX 3060 FreeToken baseline
```

This result publishes the completed Phase-0 `CORRECTNESS_REFERENCE` self-consistency gate. It is a correctness fixture, **not** a performance baseline and must not be used as a throughput comparator.

The final corrected pair archive was independently reviewed in full before this result was written.

## Pair identity

- pair archive SHA-256: `a12340d75565f02dbecf56a17642184e6dce14428f630dd607504c955a687fa6`
- FreeToken commit: `2c3da952e47391bf392e0ece8ae4c67acbc91762`
- InferSwarm methodology commit: `bc5f7ecf3cb3d56cd1d5cd3588e51dbde96a64e0`
- model: `nvidia/Qwen3.6-35B-A3B-NVFP4`
- model revision: `491c2f1ea524c639598bf8fa787a93fed5a6fbce`
- physical GPU UUID: `GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55`
- workload manifest: `phase0-v1-2026-08-27`
- manifest SHA-256: `10f81e5418a71a68f387632de422c3337cc7ba0518111a8746ad856d0210b24a`
- `memory_ratio`: `0.85`
- `kv_reserve_tokens`: `17075`
- reference MoE backend: `offload`
- reference CPU MoE layers: `0`
- resolved NVFP4 backend: `triton`
- fixed expert cache: `512` slots
- sampling override: `temperature=0.0`, `top_p=1.0`, `top_k=-1`

The first 3,774-slot P0-H attempt is not part of this reference. It was structurally invalid because fixed-size cache mode left only 15,900 KV pages and every W3 request was rejected before inference. PR #24 records that attempt and the mechanical correction to 512 slots before any valid reference or Phase-1 candidate result existed.

## Independent capture status

| Capture | Session id | Status | Validity | Warmups | Measured | Failures |
| --- | --- | --- | --- | ---: | ---: | ---: |
| 1 | `p0h-reference-valid-1` | `COMPLETE` | `VALID` | 8 | 40 | 0 |
| 2 | `p0h-reference-valid-2` | `COMPLETE` | `VALID` | 8 | 40 | 0 |

Each capture contains four complete W1-W4 blocks with two discarded warmups plus ten measured repetitions. Both have zero campaign invalidations and zero failure records.

Both servers resolved the same runtime geometry:

- `expert_quant=nvfp4`;
- `moe.backend_resolved=offload`;
- `moe.decode_target=gpu`;
- `moe.cpu_layers_resolved=[]`;
- `_auto_cpu_layers` did not fire;
- `nvfp4.resolved=triton` and the flag was not inert;
- `cache.resolved_slots=512`;
- `cache.resolved_bytes=909115392`;
- `runtime.num_pages=298524` with page size 1;
- `moe.prefill_overlap_resolved=true`;
- CUDA graph capture occurred for batch size 1.

The selected GPU UUID, engine-reported UUID, and Phase-0 RTX-3060 hardware preflight agree in both captures.

## Workload and exact-length checks

All 96 requests used the frozen workload bytes and the correctness-reference greedy override. Every request reports `sampling_overridden_for_correctness_reference=true`, `greedy=true`, and `ignore_eos=true`.

| Class | Prompt tokens | Frozen completion | Observed completion |
| --- | ---: | ---: | ---: |
| W1 | 569 | 512 | 512 |
| W2 | 54 | 512 | 512 |
| W3 | 16,819 | 256 | 256 |
| W4 | 121 | 128 | 128 |

Every completion matches the requested fixed length. Every generated output is nonempty, retained as text, and its stored `output_sha256` matches the actual UTF-8 text bytes.

Every repetition also has exact request-UID-attributed prefill instrumentation with `prefill_status.code="ok"`. W3 therefore proves the corrected reference can admit and execute the full frozen long-context fixture rather than merely passing startup.

## Measured self-consistency

Within each independent capture, all ten **measured** repetitions of a workload produced exactly one output hash. The same hash then reproduced in the second independent capture:

| Class | Canonical measured output SHA-256 |
| --- | --- |
| W1 | `59b9b9dc2cb001576a156e39fa5141d454253e8550babb795567b546e3fa0f84` |
| W2 | `1e601a5673bab480a371d8d558912598f28f33cd59efda18ebda61f3cbd467bd` |
| W3 | `0102f179f1479573dd11d8bf429e5ddc1869b6c5b0903962aff252ad16519f8e` |
| W4 | `02804bb980bd21cf7c3b189512d8ec4b504cfcb809e7abac0032603048f80414` |

That is 20/20 measured repetitions per workload across the pair agreeing bit-for-bit on the generated text hash.

This satisfies the Phase-1 correctness-reference self-consistency prerequisite. These hashes identify the deterministic fixture that later C1/C2/C3/C4 candidate evidence is evaluated around; they do **not** replace the later per-layer, routing, token, logit, and NaN/Inf gates.

## Prefix-cache state diagnostic

The raw artifacts expose one useful diagnostic that is retained rather than hidden.

For W1 and W3, the first discarded warmup in each fresh server has no reusable prefix for that workload and produces a different greedy output from the subsequent warmed-prefix state. The same cold-state alternative reproduces identically in both independent sessions:

| Class | First cold warmup SHA-256 | Warmed canonical measured SHA-256 |
| --- | --- | --- |
| W1 | `a5a2b605f3ce5daf511e7d48f5f029178ae9badf6614546e003534e76a0edf95` | `59b9b9dc2cb001576a156e39fa5141d454253e8550babb795567b546e3fa0f84` |
| W3 | `d871931c9c8d343197592c9f70a2b0529fede073a6890d6bdd4cd2aeb08a7f8b` | `0102f179f1479573dd11d8bf429e5ddc1869b6c5b0903962aff252ad16519f8e` |

For W1 the first warmup reports `cached_tokens=0`; all later repetitions use a 512-token cached prefix. For W3 the first warmup reports `cached_tokens=0`; all later repetitions use a 16,768-token cached prefix. W2 and W4 do not show a hash change across their 12 repetitions.

This is **not stochastic reference instability**: both the cold-state and warmed-state hashes independently repeat across the two fresh-server sessions, and the canonical protocol deliberately discards two warmups before the measured reference. The canonical hashes above therefore name the warmed measured state.

The dependency is nevertheless material diagnostic evidence. Phase-1 candidate correctness must compare like-for-like cache state rather than comparing a cold candidate request to a warmed reference hash and interpreting the difference as an expert-execution failure.

## Server-log review

Neither final reference server log contains a serving `ERROR`, traceback, OOM, or backend-worker crash. Each ends with the already-known Python `resource_tracker` warning about four semaphore objects after shutdown; it remains cleanup noise outside the measured serving path.

## P0-H verdict

**PASS.** Two independent, valid canonical captures reproduce the same W1-W4 measured greedy outputs under the fixed single-RTX-3060 Triton reference configuration.

P0-H completes the `CORRECTNESS_REFERENCE` acceptance item for issue #2. The separate `CANONICAL_PERFORMANCE_BASELINE`, full provenance, and run-to-run variance were already published by P0-E/P0-F. Phase-0 work now moves to issue #3 for routing/residency evidence; no routing claim is implied by this correctness result.
