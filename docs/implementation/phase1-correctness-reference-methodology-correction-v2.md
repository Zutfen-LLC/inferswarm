# Phase-1 correctness-reference methodology correction — v2

```
Status: FROZEN BEFORE CORRECTED PHASE-1 CANDIDATE RE-EVALUATION
Supersedes for the Phase-1 numerical comparator only: the P0-H R512 CORRECTNESS_REFERENCE
configuration (docs/benchmarks/phase0-p0h-correctness-reference-amendment.md)
Related: placement methodology PR #27; FreeToken diagnostic PR #10 (split reduction);
FreeToken branch poc/phase1-route-preserving-reduction
```

This amendment corrects a methodology defect in the Phase-1 numerical correctness
reference. It changes no correctness threshold, no workload, no placement, no
performance baseline, and no F gate. It is frozen before the corrected Phase-1
candidate is re-evaluated under it.

## What was wrong

The role of `CORRECTNESS_REFERENCE` (§2.4 of the success criteria) is:

> compare the distributed candidate against the same computation with the
> distributed treatment removed.

The R512 reference and the 3,774-slot candidate did not have the same warmed
serving state. The 512-slot and 3,774-slot expert-cache geometries produce
different hybrid-radix prefix-cache eviction histories, so by the time W3/W4
execute, the two configurations hold materially different cached-prefix state.
The reference therefore varied two things at once — the InferSwarm treatment and
the cache-history-dependent serving state — and could not isolate the
experimental variable C3 exists to test.

## What was discovered

### Local control: the difference is not distributed execution

The C3 step-0 difference was reproduced without InferSwarm. For W3 and W4:

```
L3774 == P3774 == D3774 != R512
```

where:

- `R512` = the old canonical single-GPU correctness reference, 512 expert slots;
- `L3774` = single-GPU FreeToken, 3,774 expert slots, no InferSwarm;
- `P3774` = same, plus P2 secondary residency, remote decode disabled;
- `D3774` = the corrected distributed candidate.

Disabling MoE prefill hit-D2D additionally produced:

```
L3774-FULLCOPY == L3774
```

The difference is therefore not: remote decode, remote prefill (none exists),
P2 residency, split reduction after its correction (FreeToken PR #10, head
`3c8bb56ff49d83a2faebcded500317c8e27d2566`, established
`SPLIT_REDUCTION_TOPOLOGY`), GPU1 execution, transport, overlap, or MoE prefill
hit-D2D. The route-preserving reduction itself is raw-byte exact on the
canonical W3/layer-0 fixed-input replay:

- ordinary unsplit output SHA-256:
  `4177608e92ea08d8e8408c0026b374722067724a61ee5910f1a9c388e28abcc5`
- corrected distributed output SHA-256: the same value;
- max abs = 0, max rel = 0;
- evidence `phase1-v2-evidence/route-preserving-fixed-input-pass.json`,
  SHA-256 `dce6bcddc7b279823dfbc43d4245adfba040231cc87a3643f48c8888dcb26938`.

### Exact first divergent state

For W3 and W4:

- decoder layers 0-2 are bitwise exact, hidden and residual streams included;
- layer-3 entry hidden/residual, input norm, q/k/v/gate projections, q/k
  normalization, and RoPE are exact;
- the cached logical K/V already differ **before** the layer-3 FlashInfer
  attention call;
- only logical cached positions `0, 1, 2` differ — the shared three-token radix
  prefix.

R512 retained the original W1-produced canonical pages `0, 1, 2`, and W3/W4
reused those exact cached K/V values. Under the 3,774-slot geometry, cache
pressure during W3 evicted that canonical leaf; the same logical prefix was
later recomputed and reinserted as new canonical pages `3911, 3912, 3913`
(followed by W3 page `3914`), and W4 subsequently reused the recomputed prefix.
The recomputed K/V is numerically close but not bit-identical, because it
passed through finite-precision model execution again.

The first differing operation is therefore:

> hybrid-radix cached-prefix canonical-page eviction/recomputation/reinsertion

not the distributed mechanism. Classification: `CACHED_PREFIX_STATE`. The
behavior is deterministic but cache-history dependent.

## What this does NOT mean

- R512 is **not** random and **not** corrupt.
- FlashInfer is not wrong.
- HybridRadixCache is not corrupt; no stale or dangling pointer evidence
  exists.
- P0-H was not invalid: R512 passed its own self-consistency requirement and
  remains a valid, self-consistent FreeToken configuration.

The defect is methodological: R512 does not isolate the Phase-1 treatment for
the complete warmed serving state, because its cache geometry gives it a
different deterministic cache history than the candidate's.

## Historical verdict — preserved

> Under the original frozen R512 methodology, build `9befb0e5...` (FreeToken
> P4 parent `9befb0e5eff7d06be925b98aab1579358ccce2d7`) and the experimental
> route-preserving candidate are correctness NO-GO because W3/W4 fail C3.

Historical record under R512:

- original distributed build `9befb0e5...`: W1 PASS, W2 PASS, W3 FAIL, W4 FAIL;
- route-preserving candidate: W3 FAIL (max abs `0.65625`), W4 FAIL (max abs
  `0.46875`); evidence SHA-256
  `60c2886fadcd0cfb74ac604050a77c5bb5fb05730845bce65b15df1e9e47a3d3`.

These results are not erased, relabeled, or reinterpreted. They remain the
verdict under the methodology that produced them.

## Why this amendment is allowed

The success criteria predeclare exactly this path (§2.4 binding rules and
§5.3): a correctness method may be amended in a PR, with its thresholds written
before any candidate result is seen under the amended method. Recorded:

- **what changed**: only the configuration serving as the Phase-1
  `CORRECTNESS_REFERENCE` comparator (R512 → matched-state v2 below);
- **why**: the reference must remove the InferSwarm treatment alone; R512 also
  changed the cache-history-dependent serving state;
- **the old would-have-been verdict**: correctness NO-GO for W3/W4 under R512
  (retained above as the historical verdict);
- **the evidence that motivated the correction**: the local-control chain and
  `CACHED_PREFIX_STATE` diagnosis above, all collected without any performance
  measurement.

The earlier §2.4 assertion that a fixed cache size "changes how often the
reference fetches, not what it computes" is corrected: for the complete warmed
serving state, cache geometry can alter radix-cache eviction history, causing a
logical prefix to be recomputed instead of retaining its original
finite-precision K/V. The result is deterministic, but cache-history dependent.

## The corrected rule: `PHASE1_CORRECTNESS_REFERENCE_V2`

The v2 reference is mechanically derived as:

> the frozen Phase-1 candidate's GPU0 serving configuration with the
> InferSwarm treatment removed.

Specifically:

- one physical GPU only;
- no secondary GPU;
- no placement artifact;
- no InferSwarm resident bank;
- no remote decode;
- no remote transport;
- otherwise candidate-local execution geometry is unchanged.

This rule — not numerical closeness to the candidate — defines the reference.

## Exact v2 reference configuration

Pinned:

```
model repository:    nvidia/Qwen3.6-35B-A3B-NVFP4
model revision:      491c2f1ea524c639598bf8fa787a93fed5a6fbce
physical GPU:        GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55
```

Required serving configuration:

```text
--moe-backend offload
--moe-cpu-layers 0
--nvfp4-backend triton
--moe-cache-size 3774
--kv-reserve-tokens 17075
--num-tokens 17075
--memory-ratio 0.85
--cuda-graph-max-bs 0
--max-running-requests 1
--sampling-defaults none
```

Resolved values are recorded, not merely flags. Expected resolved properties:

- expert quant: `nvfp4`;
- MoE decode target: GPU;
- CPU MoE layers: empty;
- NVFP4 backend: Triton;
- expert cache: 3,774 slots;
- page size: 1;
- attention backend: FI;
- cache: hybrid radix;
- prefill overlap enabled;
- enough KV capacity for W3 (16,819-token prompt + 256-token output);
- no decode CUDA graphs, matching the distributed Phase-1 candidate.

If actual resolved values disagree with the above, capture stops before
reference evidence is created. The configuration is never silently amended.

## Cache-state protocol is part of the correctness fixture

The correctness reference is not only static command-line geometry. The warmed
serving-state protocol is frozen with it:

- one fresh server per independent reference session;
- workloads in canonical W1 → W2 → W3 → W4 order;
- the same frozen request bodies and exact output lengths;
- `ignore_eos` and greedy sampling;
- two warmups per workload before the measured correctness capture;
- no server restart between workload classes;
- no radix prefix-cache clearing between classes;
- instrumentation reset must not clear serving caches.

This intentionally gives the local reference the same deterministic
cache-history opportunity as the candidate. Pages are never manually pinned and
the three-token radix prefix is never artificially preserved.

## Unchanged thresholds

C3 is untouched. The following remain exactly frozen:

- token gate: first 64 generated tokens exact;
- step-0 argmax: exact;
- step-0 top-5 ordering: exact;
- full logits: `rtol = 2e-3`, `atol = 2e-3`;
- numerical health: zero NaN/Inf.

No tolerance change, token-window change, workload change, or averaging. C1,
C2, C4, C5, all F gates, all performance thresholds, baseline definitions,
workload definitions, the placement policy, and the architecture-vs-
implementation rules are unchanged.

## Phase-0 R512 evidence is preserved

`docs/benchmarks/phase0-p0h-correctness-reference-amendment.md` and the
canonical P0-H result remain historical Phase-0 evidence:

- P0-H R512 remains a valid self-consistent configuration;
- it is superseded only as the **Phase-1 numerical comparator**;
- no performance baseline changes;
- no Phase-0 throughput result changes.

## Experiment firewall

At the time this amendment was frozen:

- no corrected-candidate evaluation under the v2 reference had been run;
- no candidate throughput, TTFT, prefill throughput, prefill-speed ratio,
  aggregate speedup, patched-P2P result, or GO/ITERATE performance verdict had
  been collected;
- the placement remained `phase1-qwen36-placement-v2`, SHA-256
  `2f62bb84df40d4cc5649e940a39cb53d2975eadecbc320fb97d2b037d4e005f4`;
- no v3 placement was derived and P5/P6 were not started.
