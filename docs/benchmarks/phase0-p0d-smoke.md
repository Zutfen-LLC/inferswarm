# Phase-0 P0-D real-serving smoke

```
Status: Active pre-canonical validation
First smoke: 2026-08-27 — intentionally NON_CANONICAL, incomplete
```

P0-D exists to discover serving-path failures before the two canonical B1–B5 sessions. The
first real RTX 3060 smoke did exactly that. Its observations are retained as diagnostic
information only; none of its throughput or latency values is a Phase-0 baseline result.

## Frozen inputs

The smoke used the already-frozen Phase-0 inputs:

- model repository: `nvidia/Qwen3.6-35B-A3B-NVFP4`;
- model revision: `491c2f1ea524c639598bf8fa787a93fed5a6fbce`;
- model path on the measurement host:
  `/srv/models/nvidia/Qwen3.6-35B-A3B-NVFP4/491c2f1ea524c639598bf8fa787a93fed5a6fbce`;
- manifest: `docs/benchmarks/workloads/phase0-v1/manifest.json`;
- physical GPU UUID: `GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55`.

The attempted smoke ran one measured generation, no warmup, for B2 and B3 across W1–W4.
It was explicitly `--dev-smoke` and therefore NON_CANONICAL regardless of outcome.

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

This is the minimum reserve that can execute the already-frozen longest workload at its exact
output length. It is intentionally not padded upward: `--moe-cache-auto` should still choose
the largest expert cache that fits after satisfying the workload's actual sequence-capacity
requirement. Every B1–B5 arm, P0-D rerun, and correctness-reference capture must use the same
`--kv-reserve-tokens 17075` unless a later reviewed methodology change explicitly invalidates
and reruns the affected measurements.

This does **not** hand-tune an individual baseline arm. FreeToken's auto-cache solver consumes
the reserve and jointly resolves expert slots and KV pages for each backend under the same
held-constant sequence requirement.

## Blocker 2 — overlap scheduling reports fixed-length output one token short

Every successful B2/B3 smoke generation was reported one token below the request's exact
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

The fix requirement is semantic, not benchmark-specific: length termination must be decided
from the number of sampled tokens actually appended/drained to the host-visible request, not
from device scheduling state that may be one forward ahead. A regression must recreate the
overlap boundary and prove token N−1 is non-terminal while token N carries
`finish_reason=length`.

No canonical Phase-0 serving run may begin until that FreeToken fix is merged and the P0-D
smoke passes the exact-length checks.

## What did work in the first smoke

The failed smoke still established useful operational facts without promoting its timing
numbers:

- the pinned checkpoint loaded from `/srv/models`;
- B2 resolved to `hybrid` and consumed the fresh NVFP4 bandwidth calibration;
- B3 `--moe-backend auto` also resolved to `hybrid`, as expected from that profile;
- the selected physical RTX 3060 UUID was used;
- W1, W2, and W4 reached real prefill/decode serving paths;
- W3 failed for the explicit sequence-capacity reason above rather than an opaque crash.

## Exit gate for P0-D

Rerun only after both blockers above are fixed. P0-D passes when all eight B2/B3 × W1–W4
observations complete with:

- zero generation failures;
- exact frozen completion lengths;
- W3 accepted at its 16,819-token serving prompt length;
- usable prefill attribution;
- B2/B3 live resolved configuration and GPU identity recorded;
- overall `execution_status=COMPLETE` and `validity=NON_CANONICAL`.

Only after that gate passes do P0-E/P0-F canonical B1–B5 sessions begin.
