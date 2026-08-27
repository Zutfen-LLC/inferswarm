# Phase-0 P0-H correctness-reference capacity amendment

```
Status: Binding correction after an INVALID first capture
Date: 2026-08-27
Canonical issue: #2 — Establish reproducible RTX 3060 FreeToken baseline
```

This amendment corrects only the fixed MoE cache size in the P0-H `CORRECTNESS_REFERENCE` freeze. It does not change the model, GPU, Triton NVFP4 kernel family, frozen workload, greedy sampling, memory ratio, KV-reserve target, correctness tolerances, performance baseline, or any Phase-1 verdict rule.

## Invalid first capture

The first canonical reference attempt used the previously frozen 3,774-slot cache. Its raw archive SHA-256 is:

`6e332575bce34d5ada81b69b95cd442446df2c3480df4eb7b1218c1a382682d0`

The artifact is `execution_status=INCOMPLETE`, `validity=INVALID`, with 12 generation failures, all in W3. W1, W2 and W4 completed, but the attempt is not reference evidence and none of its outputs may be promoted as `CORRECTNESS_REFERENCE`.

The server log gives the causal failure directly for every W3 request:

`Input sequence length 16819 exceeds 15900, request ... is dropped.`

The resolved fixed-size reference configuration had:

- Triton NVFP4 GPU decode;
- zero CPU MoE layers;
- 3,774 expert slots;
- only 15,900 KV pages.

Thus W3 was rejected before model inference. No W3 correctness output was observed.

## Why the earlier 3,774-slot inference was wrong

The two valid performance sessions used `--moe-cache-auto`. FreeToken's auto planner jointly solves one MoE+KV budget: it first reserves the requested KV capacity, then fills expert slots, and writes both the chosen slot count and KV page count into runtime configuration. On this host that produced 3,774 slots **and 17,091 KV pages**.

The fixed-size reference path is different. Supplying `--moe-cache-size 3774` fixes only the expert cache. It does not reuse the auto planner's paired `num_pages=17091` decision; KV pages are later derived from the remaining live free-memory state. In the invalid reference attempt that yielded 15,900 pages. Therefore copying the auto-resolved slot count into a fixed-size reference did **not** preserve the auto-resolved MoE/KV geometry.

This distinction is a capacity/configuration issue, not a numerical-correctness result.

## Corrected fixed cache size

The P0-H correctness reference is amended to:

`MoE cache size: 512 expert slots`

The value is mechanical:

- Qwen3.6-35B-A3B has 256 experts per MoE layer;
- FreeToken's prefill-overlap cache requires `cache_size >= 2 * num_experts`;
- therefore 512 is the smallest fixed cache that preserves the existing prefill-overlap execution mode;
- 512 also satisfies the ordinary `cache_size >= num_experts` floor;
- Triton has no Marlin 992-slot cap.

Relative to 3,774 slots, 512 removes 3,262 expert slots from the fixed GPU cache. At the measured 1,775,616 bytes/slot this releases about 5.40 GiB of GPU pool capacity, far more than the additional KV capacity needed to admit the 16,819-token W3 prompt above the failed 15,900-page geometry.

The smaller cache changes only how often expert weights must be fetched into the slot cache. Section 2.4 already defines cache size as a stability/capacity control rather than part of the numerical reference computation; the reference is not a performance comparator.

## Corrected frozen reference

All future P0-H captures use:

```text
model repository:    nvidia/Qwen3.6-35B-A3B-NVFP4
model revision:      491c2f1ea524c639598bf8fa787a93fed5a6fbce
physical GPU:        GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55
moe backend:         offload
moe CPU layers:      0
NVFP4 backend:       triton
MoE cache size:      512 expert slots
memory ratio:        0.85
KV reserve tokens:   17075
workload manifest:   phase0-v1-2026-08-27
sampling:             greedy request override: temperature=0.0, top_p=1.0, top_k=-1
```

The two independent canonical captures must both resolve enough KV capacity to admit every frozen workload, including W3. Any new incomplete or invalid capture remains preserved but is not reference evidence.

## Anti-goalpost boundary

This correction is made after one INVALID P0-H attempt but before any valid `CORRECTNESS_REFERENCE` exists and before any Phase-1 candidate measurement exists.

The change is not selected from correctness output:

- W3 produced no model output at all because admission failed;
- 512 is derived from FreeToken's existing `2 * num_experts` prefill-overlap floor;
- W1/W2/W4 outputs from the invalid attempt are retained only as failed-attempt evidence and are not used to choose the new cache size;
- Triton, greedy sampling, prompts, output lengths, memory ratio, KV-reserve target and all correctness rules remain unchanged.

The earlier freeze remains part of project history; this amendment supersedes only its 3,774-slot value for P0-H.
