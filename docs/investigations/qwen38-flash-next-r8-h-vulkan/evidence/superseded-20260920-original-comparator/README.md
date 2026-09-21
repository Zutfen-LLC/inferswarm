# Superseded 2026-09-20 — original-comparator campaign (df0cf43)

This directory preserves, byte-for-byte, the physical evidence of the
ORIGINAL R8-H experiment (PR #235 head `df0cf4348e993628344919424a0515c6b485c3b7`,
campaign commit `df0cf43`, producer closure `d31a52d`).

## Why superseded

The maintainer amended Issue #234 on 2026-09-20: the original experiment
used the accepted R8-D output as the sole Vulkan correctness oracle, but
that R8-D reference is a single-host NVIDIA/CUDA placement using two RTX
3060 GPUs plus CPU spill — NOT a matched Vulkan reference. The retained
observation therefore establishes only:

> under the then-used geometry, AMD/V340L Vulkan produced a deterministic
> token stream that differs from the historical CUDA-derived R8-D output
> at case-256 generated position 5 (candidate token 34227 vs historical
> anchor token 271), across 3 identical repeats.

It does NOT establish `R8H_QWEN38_VULKAN_CORRECTNESS_FAIL`. That terminal
is RETIRED for this campaign and must not be reused.

Additional defects corrected by the successor campaign (none of which
rewrite the observation below):

1. the producer closure was not mechanically proven at final head
   (physical producers were modified after the claimed producer pin);
2. the comparator design confounded backend and hardware axes;
3. execution/reduction controls were insufficient (control suite
   advertised but registered zero).

## Scientific value (historical, unadmitted for terminal classification)

- V340L Vulkan, single die 00000000:06:00.0, ngl=1, case-256;
- 3 identical repeats (deterministic);
- first difference vs the historical R8-D CUDA anchor at position 5
  (token 34227 vs 271);
- approximately 1.05 GB selected-die residency (1,050,275,840 bytes);
- 12,288-byte excluded-die enumeration noise (under the frozen <1 MiB
  bound);
- clean retained platform window (no amdgpu fault classes, 0 correctable
  RxErr lines, VRAM released, link width stable).

## Layout (byte-identical to the df0cf43 tree)

- `TERMINAL.json` — the retired terminal reduction output;
- `PHYSICAL-AUTHORITY.json` — the original authority binding;
- `backing/backing-verification.json` — 3/3 member hash verification
  on inferswarm02 (source: inferswarm01 fleet Source);
- `candidate/ladder.json`, `candidate/ladder-server.log`,
  `candidate/placement.json` — the case-256 execution record;
- `host-inventory/census.json`, `host-inventory/runtime-qualification.json`,
  `host-inventory/INCIDENT-authorized-keys-20260920.md`;
- `placement/placement.json` and `runtime/runtime-qualification.json`
  duplicate the candidate-side copies at their frozen-path locations.

Do not delete, relabel, or rewrite anything in this directory. The
corrected matched A/B/C campaign lives in the parent evidence tree.
