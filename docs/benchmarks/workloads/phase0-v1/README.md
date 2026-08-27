# Phase-0 canonical workloads v1

This directory freezes the W1–W4 workload set used by InferSwarm Phase 0 and,
unchanged, by the Phase-1 comparison. It implements the workload-selection
contract in `docs/phase1-poc-success-criteria.md` §9 and is consumed by the
FreeToken Phase-0 harness.

## Canonical files

- `manifest.json` — canonical workload manifest, including exact SHA-256,
  output-token counts, sampling parameters, `ignore_eos`, chat-template
  settings, model pin, and source provenance.
- `materialize_w3.py` — deterministic source for the long-context W3 fixture.
  The generated `w3-long-context.txt` is intentionally not versioned; the
  generator refuses to produce bytes whose SHA-256 differs from the manifest.

Materialize W3 before validating or running the manifest:

```bash
cd docs/benchmarks/workloads/phase0-v1
python materialize_w3.py --check
python materialize_w3.py
```

The expected W3 digest is:

```text
279c11ce0194e1d839dc92d910785d996a93e33046d047a018a652b24e75f2b3
```

## Frozen workload choices

| Class | Frozen character | Output |
|---|---|---:|
| W1 | Real public coding-agent transcript replay: direct maintainer-task excerpt from InferSwarm issue #2 + direct agent-report excerpt from FreeToken PR #1 + one fixed replay-continuation instruction | 512 |
| W2 | `math-ai/aime25`, pinned revision `9692efc2d7ffbd5fc1b167e2bb4d0972010c4af4`, test id `0`, with the same boxed-answer instruction used by FreeToken's decode benchmark | 512 |
| W3 | Deterministic, project-grounded long engineering ledger for audit/synthesis under long-context KV pressure | 256 |
| W4 | Short interactive question about what evidence would make two-GPU resident expert execution genuinely useful | 128 |

W3 is deliberately described as synthetic: it is generated from public,
precommitted InferSwarm/FreeToken contract facts and contains no fabricated
benchmark observations. Its job is to give the experiment a stable technical
long-context workload. W1 and W2 provide the real public agent/reasoning
workload anchors, while issue #3 measures routing behavior on the frozen set.

## Sampling

Performance runs use the pinned checkpoint's own recommended sampling,
recorded explicitly rather than inherited from a server default:

```json
{"temperature": 1.0, "top_p": 0.95, "top_k": 20}
```

All four classes set:

```json
{"ignore_eos": true, "seed": null, "chat_template_kwargs": {"enable_thinking": true}}
```

`CORRECTNESS_REFERENCE` is different by design: the existing FreeToken harness
overrides these same frozen prompts to greedy sampling and records that
override. The performance sweep does not.

## Hashes

| Class | SHA-256 |
|---|---|
| W1 | `078303fe708aadb247e01e416a6ca16db933a353d38aee8b550a19bfb72b15df` |
| W2 | `51e1235f1c85cf333085c9e2889a20fb7e7ef65f320856975bac705eb04e43d4` |
| W3 | `279c11ce0194e1d839dc92d910785d996a93e33046d047a018a652b24e75f2b3` |
| W4 | `345802e1ac06ec0357fe67d19ca0ba2439a10be8fae134fa4e1e302d52c347c6` |

These hashes are the freeze boundary. Do not “fix” a hash to match edited
prompt text. Any prompt change is a deliberate experiment re-freeze; after
candidate performance measurement has begun, it also requires the written
record required by the success criteria.

## Token-shape validation

The criteria define W1/W2 as upper bounds and W3/W4 as token bands. The
FreeToken harness checks the **actual prompt token count reported by the
serving path** and invalidates an out-of-shape block without rewriting or
truncating the prompt. That runtime count is authoritative.

This repository freeze therefore does not claim a measured tokenizer count.
P0-D's non-canonical serving smoke must materialize W3 and exercise the frozen
manifest before the canonical sessions. If the pinned model reports a prompt
outside its precommitted class band, the smoke has found a P0-D blocker; do
not silently resize the prompt after any candidate result exists.

Before the first Phase-1 candidate benchmark, the Phase-0 evidence publication
must archive the actual materialized prompt identity and serving-reported
prompt-token counts alongside these frozen hashes, satisfying §9's requirement
that prompts, token counts, and hashes all be committed before candidate
measurement begins.

## Immutability

This set was frozen on 2026-08-27 against:

```text
nvidia/Qwen3.6-35B-A3B-NVFP4
491c2f1ea524c639598bf8fa787a93fed5a6fbce
```

It is the workload set for both the Phase-0 baseline/routing work and the
Phase-1 candidate. Coverage, hit rate, and throughput conclusions must not be
made by swapping in a friendlier workload after results are visible.
