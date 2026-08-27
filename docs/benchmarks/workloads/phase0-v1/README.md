# Phase-0 canonical workloads v1

This directory contains the W1–W4 workload set frozen for the InferSwarm
Phase-0 baseline/routing campaign and, unchanged, the first Phase-1 candidate
comparison. The selection contract is defined in
[the Phase-1 POC success criteria](../../../phase1-poc-success-criteria.md) §9;
current execution status lives in
[the Phase-0 plan](../../../implementation/phase0-baseline.md).

## Frozen set

| Class | Character | Formatted prompt tokens | Output tokens | SHA-256 |
|---|---|---:|---:|---|
| W1 | Real public coding-agent transcript replay: InferSwarm issue #2 maintainer task + FreeToken PR #1 agent report + fixed continuation | 569 | 512 | `cea659ba97b16ed7909dbb5a581ad83c46606a374610a50a69494791a0b186f1` |
| W2 | `math-ai/aime25` test id `0`, revision `9692efc2d7ffbd5fc1b167e2bb4d0972010c4af4` | 54 | 512 | `a4f2fdc66c946d8f9097d34fe8d173c7dbb9d647401e8f6bc9b79a0158d26e5d` |
| W3 | Non-repetitive long technical synthesis over the Phase-0/1 contract plus the existing feasibility investigation | 16,819 | 256 | `7b2002252e06b28f5841d0d5467de9898423af57b84c3d5cb6d141b35df1647b` |
| W4 | Short interactive capacity-vs-performance explanation | 121 | 128 | `41226057cf336c5f7fb618bda61f11c98927167629ef4b5bdfbfa1ba48ae54f7` |

The token counts above are a pre-measurement check produced with the exact
pinned Qwen checkpoint tokenizer and chat template. They satisfy the frozen
harness rules: W1 ≤ 2,000, W2 ≤ 1,000, W3 13,600–18,400, and W4 96–160. They
are not benchmark measurements; the prompt-token counts reported by the real
FreeToken serving path remain authoritative during P0-D and canonical runs.

## Request contract

All four performance workloads explicitly use the pinned checkpoint's
recommended sampling:

```json
{"temperature": 1.0, "top_p": 0.95, "top_k": 20}
```

They also set `ignore_eos = true`, `seed = null`, `role = user`, and
`chat_template_kwargs = {"enable_thinking": true}`. The FreeToken
`CORRECTNESS_REFERENCE` path deliberately overrides these same frozen prompts
to greedy sampling; it does not mutate the performance manifest.

## Freeze boundary

`manifest.json` is canonical and pins the exact fixture bytes, model revision,
sampling, output lengths, template settings, and source provenance. The
permanent `scripts/check_phase0_workloads.py` CI check fails if a fixture is
edited without a deliberate manifest re-freeze.

Do not update a hash merely to make CI match changed prompt text. A prompt
change is an experiment change; once candidate performance exists, the
success criteria's anti-goalpost rules apply.
