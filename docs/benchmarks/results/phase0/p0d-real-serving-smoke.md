# Phase-0 P0-D real-serving smoke result

```
Label: NON-CANONICAL DEVELOPER VALIDATION
Verdict: PASS
Date: 2026-08-27
```

This result records completion of the Phase-0 P0-D real-serving smoke. It is developer-validation evidence only. **No throughput, TTFT, prefill-rate, or other timing value from this run is a Phase-0 baseline result and none may be quoted as such.**

## Run identity

- FreeToken commit: `7aaece53e152980ed1f068062312276d0e861a47`
- InferSwarm methodology commit: `a64c8cf296f2d59c840a8e7e410861b8adb998eb`
- model: `nvidia/Qwen3.6-35B-A3B-NVFP4`
- model revision: `491c2f1ea524c639598bf8fa787a93fed5a6fbce`
- physical GPU UUID: `GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55`
- workload manifest: `phase0-v1-2026-08-27`
- manifest SHA-256: `10f81e5418a71a68f387632de422c3337cc7ba0518111a8746ad856d0210b24a`
- `memory_ratio`: `0.85`
- `kv_reserve_tokens`: `17075`
- archive SHA-256: `6cae9ec7a12e678f629c59d1ca394199a5c26c91da9e9ecfbac81ce074c72a8f`

The FreeToken working tree was clean. The model revision was recorded as an exact upstream SHA. The local model path is the explicit revision-addressed `/srv/models` directory, so the harness correctly records that it cannot independently infer the Hugging Face snapshot revision from the cache-directory naming convention; the explicit repository/revision pin remains the provenance authority.

## Exit-gate result

The run artifact reports:

- headline: `NON-CANONICAL DEVELOPER RUN`;
- `execution_status=COMPLETE`;
- `validity=NON_CANONICAL`;
- `failure_count=0`;
- `measured_repetition_count=8`;
- zero campaign invalidations;
- every B2/B3 × W1-W4 block complete.

The run is non-canonical only because it deliberately used the P0-D smoke protocol (`--dev-smoke`, zero warmups, one measured repetition). It is not non-canonical because of a serving, workload, provenance, or instrumentation failure.

## Workload-shape and exact-length checks

The authoritative serving path reproduced the frozen prompt-token counts exactly:

| Class | Serving prompt tokens | Frozen completion | Observed completion in B2 | Observed completion in B3 |
| --- | ---: | ---: | ---: | ---: |
| W1 | 569 | 512 | 512 | 512 |
| W2 | 54 | 512 | 512 | 512 |
| W3 | 16,819 | 256 | 256 | 256 |
| W4 | 121 | 128 | 128 | 128 |

All eight records report `completion_matches_request=true`, with no prompt-shape or completion-length deviation.

This closes the off-by-one blocker discovered by the first smoke: fixed-length `ignore_eos=true` generations now deliver the exact requested token count under overlap scheduling.

## Long-context W3 check

W3 completed on both arms without OOM or sequence rejection. The scheduler served its 16,819-token prompt as three measured prefill chunks:

```
8192 + 8192 + 435 = 16819
```

Each W3 repetition has one exact request-UID-attributed prefill record whose accumulated token count is 16,819, whose `chunks` field is `3`, and whose `shared_batch` field is false. This closes both earlier W3 blockers: the KV reserve is large enough for the frozen prompt plus completion, and `memory_ratio=0.85` leaves sufficient transient activation headroom for the real GDN prefill path.

## B2/B3 resolution and fresh bandwidth profile

The session-level `ft bench bw` prerequisite completed successfully on the selected RTX 3060 and produced a usable NVFP4 calibration. Its profile GPU UUID matches the declared physical GPU.

The fresh profile recommended `hybrid`, and both consuming arms used it as intended:

- B2 requested `hybrid` and resolved `hybrid`;
- B3 requested `auto` and resolved `hybrid`;
- B3 therefore coincides with the declared B2 path;
- both arms resolved the native NVFP4 layout / Triton-kernel expert path;
- both arms consumed the same positive bandwidth-derived hybrid fetch fraction;
- `model.expert_quant` resolved to `nvfp4` on both arms;
- no held-constant field disagreed between B2 and B3.

With `memory_ratio=0.85` and `kv_reserve_tokens=17075`, both arms resolved `moe_cache_size=3774` and `num_pages=17091`. These are configuration/provenance facts, not performance claims.

## Prefill instrumentation

All eight measured repetitions have `prefill_status.code="ok"` and are attributed by exact request UID. No repetition used TTFT as a substitute for prefill throughput. No prefill record is stale, ambiguous, shared across requests, disabled, or missing.

## GPU identity

The requested UUID, harness-resolved UUID, engine-reported UUID, and fresh `ft bench bw` profile UUID all agree on:

`GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55`

The live engine identified the card as an NVIDIA GeForce RTX 3060 in the accepted 12-GB Phase-0 hardware class.

## Output sanity

Full output text was retained in the local developer artifact. W1-W4 produced coherent task-related text rather than empty, corrupted, repeated-token, or obviously malformed output. P0-D is not a correctness verdict; formal correctness remains the separate `CORRECTNESS_REFERENCE` work.

## Teardown-only log anomaly

B3 emitted one `FrontendAPI ERROR` after the final W4 instrumentation fetch, during `INFO: Shutting down`:

`Backend supervisor: backend worker freetoken-detokenizer-0 exited`

This is classified as **non-invalidating shutdown noise**, not a serving failure. The benchmark stopper sends SIGTERM to the whole process group; a worker can therefore exit immediately before Uvicorn's lifespan shutdown hook sets FreeToken's `_SHUTTING_DOWN` flag. The supervisor then briefly classifies an expected worker exit as a crash. The error occurred after every B3 generation and its final instrumentation read had completed, and the run artifact contains no failure or invalidation from it.

Both arm shutdowns also print Python `resource_tracker` warnings about four leaked semaphore objects. These occur after serving and do not affect P0-D's data, but they remain cleanup debt rather than benchmark evidence.

## P0-D verdict

**PASS.** The pre-canonical real-serving path now demonstrates that the exact pinned model, workload set, GPU identity, B2/B3 resolution, fresh bandwidth calibration, long-context W3 path, fixed completion lengths, and prefill instrumentation can all execute together on the Phase-0 host.

P0-D performance numbers remain excluded from all baseline claims. The next measurement stage is P0-E/P0-F: the two canonical B1-B5 sessions (second session reversed), followed by baseline selection and the separate correctness reference.
