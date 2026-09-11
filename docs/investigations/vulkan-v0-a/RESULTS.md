# V0-A results: Vulkan vs native inference on inferswarm02

All numbers MEASURED on `inferswarm02` (Debian 13.6, Celeron G3900,
16 GiB RAM) unless marked CALCULATED. Probe: llama.cpp
`8ea2902` (hashes in `probe/build-identities.json`). Subject:
`Qwen2.5-3B-Instruct-Q4_K_M.gguf`
sha256 `9c9f56a391a3abbd5b89d0245bf6106081bcc3173119d4229235dd9d23253f94`,
`-ngl 99` (all layers on the pinned device), pp512 / tg128, `-r 5`
in-process reps, 3 independent process runs each; medians over process
runs reported. Methodology: `METHODOLOGY.md` (frozen at 76a4307 before
canonical runs).

## Same-device comparisons (primary)

### NVIDIA RTX 3060 Ti (04:00.0): Vulkan (RADV-free; NVIDIA ICD 615.71.09) vs CUDA (13.1)

| metric                    | Vulkan  | CUDA    | VK/CUDA ratio (CALCULATED) |
|---------------------------|---------|---------|----------------------------|
| prefill pp512 t/s (median)| 3579.0  | 3773.1  | 0.949                      |
| decode tg128 t/s (median) | 95.5    | 108.0   | 0.884                      |
| startup+load wall ms      | 13215   | 11359   | 1.16 (VK slower)           |
| VRAM peak                 | 3129 MiB| 3239 MiB| -110 MiB (VK lower)        |
| host peak RSS             | 2630 MB | 2332 MB | +298 MB (VK higher)        |

Run-to-run (process runs, t/s):
- VK pp512: 3604.4 / 3579.0 / 3512.0 — tg128: 95.2 / 95.5 / 95.6
- CUDA pp512: 3731.7 / 3775.3 / 3773.1 — tg128: 107.9 / 108.1 / 108.0

Correctness: greedy fixture produced one identical generation across all
five retained Vulkan runs (both AMD cards + 3060 Ti) and the CUDA run;
cross-backend outputs are semantically equal at this fixture. Bit-level
logit equality not claimed (not exposed by the CLI probe).

### AMD Ellesmere RX 570/580-class (02:00.0): Vulkan vs HIP/ROCm

HIP/ROCm: **NATIVE_BACKEND_UNAVAILABLE** — mechanically demonstrated
(`hipGetDeviceCount` = error 100, `rocminfo` CPU-agent-only, with amdgpu
bound; Debian-packaged ROCm runtime does not support gfx803). Evidence:
`inventory/amd-native-path/`. No Vulkan/native ratio is computed for AMD.

AMD Vulkan results (characterization, no native comparator on this host):

| metric                     | AMD-A Vulkan (RADV 25.0.7) |
|----------------------------|----------------------------|
| prefill pp512 t/s (median) | 498.0 (runs 499.6/497.8/498.0) |
| decode tg128 t/s (median)  | 43.7 (runs 43.7/43.6/43.7)  |
| startup+load wall ms       | 29101                      |
| VRAM peak                  | 3254099968 B (~3104 MiB)   |
| host peak RSS              | 2103 MB                    |

AMD-B (03:00.0): identical silicon; smoke run reproduced the identical
greedy generation (see `results/correctness-greedy-fixture.txt`).

## Cross-vendor AMD-vs-NVIDIA (DESCRIPTIVE ONLY — not a backend ratio)

AMD-A Vulkan decode 43.7 t/s vs NV-A Vulkan decode 95.5 t/s on the same
host/probe/model: different silicon, descriptive only.

## Backend capability facts (machine-readable: capabilities/)

- AMD Polaris RADV advertises NO fp16 compute, NO integer-dot, NO matrix
  cores (subgroup 64) — ggml computes f32 on these cards.
- NVIDIA ICD advertises fp16, integer-dot, NV_coopmat2 (subgroup 32).
- The Vulkan loader also enumerates llvmpipe (CPU) and Intel iGPU; every
  canonical run pins `--device` and retains the enumeration banner, so no
  silent CPU fallback can pass unnoticed.

## Explicit non-claims

- No AMD native numbers exist in this campaign; the truthful record is
  NATIVE_BACKEND_UNAVAILABLE for HIP on the frozen stack.
- No claim of bit-equality across backends; no new numerical threshold.
- llama-server and multi-GPU modes not characterized.
- The 3060 Ti's x1 riser link bounds host<->device transfer for BOTH its
  backends equally; absolute t/s are conservative.
