# V0-A results: Vulkan vs native inference on inferswarm02

CORRECTED by `METHODOLOGY-CORRECTION.md` (freeze `8115933`, addenda
`36af6e0`/`d265480`/`51f9489`); supersedes the 2b14fba result
interpretations where noted. All numbers MEASURED on `inferswarm02`
(Debian 13.6, Celeron G3900, 16 GiB RAM) unless marked CALCULATED.
Probe: llama.cpp `8ea2902` (hashes in `probe/build-identities.json`;
verified byte-identical before every corrected run). Subject:
`Qwen2.5-3B-Instruct-Q4_K_M.gguf`
sha256 `9c9f56a391a3abbd5b89d0245bf6106081bcc3173119d4229235dd9d23253f94`,
`-ngl 99` (all layers on the pinned device), pp512 / tg128, `-r 5`
in-process reps AGGREGATED by llama-bench, 3 independent process runs
per arm; medians over process runs reported (see `-r 5` note below).
Methodology: `METHODOLOGY.md` (frozen at 76a4307) as corrected by
`METHODOLOGY-CORRECTION.md`.

## Throughput (original campaign, retained; identity checks re-passed)

The accepted NVIDIA throughput campaign is unchanged and remains the
V0-A throughput evidence (original `results/bench-*.csv`; not rerun).
The corrected identity/comparability checks re-passed: binaries,
libraries, and model verified byte-identical; same physical NV-A link
state for both backends (see PCIe note); device pins proven by the
retained enumeration banners (`Vulkan3`, `CUDA0`).

### NVIDIA RTX 3060 Ti (04:00.0): Vulkan (NVIDIA ICD 615.71.09) vs CUDA (13.1)

| metric                    | Vulkan  | CUDA    | VK/CUDA ratio (CALCULATED) |
|---------------------------|---------|---------|----------------------------|
| prefill pp512 t/s (median)| 3579.0  | 3773.1  | 0.949                      |
| decode tg128 t/s (median) | 95.5    | 108.0   | 0.884                      |

Process-run t/s: VK pp512 3604.4 / 3579.0 / 3512.0, tg128 95.2 / 95.5 /
95.6; CUDA pp512 3731.7 / 3775.3 / 3773.1, tg128 107.9 / 108.1 / 108.0.

`-r 5` note (correction defect 4): each canonical llama-bench process
used `-r 5`; llama-bench emitted one `avg_ts/stddev_ts` AGGREGATE row
per process for its five internal repetitions. Three independent
process-level observations were retained per arm and the reported
median is over those three aggregates. Individual internal repetition
rows were not emitted by the tool, are unavailable, and are NOT
claimed. The methodology's earlier "full per-rep rows retained" wording
is corrected here.

### AMD Ellesmere RX 570/580-class (02:00.0): Vulkan vs HIP/ROCm

HIP/ROCm: **NATIVE_BACKEND_UNAVAILABLE** — mechanically demonstrated
(`hipGetDeviceCount` = error 100, `rocminfo` CPU-agent-only, with amdgpu
bound; Debian-packaged ROCm runtime does not support gfx803). Evidence:
`inventory/amd-native-path/`. No Vulkan/native ratio is computed for AMD.

AMD Vulkan throughput (characterization, no native comparator on this
host; original campaign retained):

| metric                     | AMD-A Vulkan (RADV 25.0.7) |
|----------------------------|----------------------------|
| prefill pp512 t/s (median) | 498.0 (runs 499.6/497.8/498.0) |
| decode tg128 t/s (median)  | 43.7 (runs 43.7/43.6/43.7)  |

AMD-B (03:00.0): identical silicon; smoke rule per methodology.

## Corrected correctness evidence (supersedes the old fixture summary)

Raw per-run records with full device-identity proof:
`correctness/correction-*/run.json`; mechanical summary:
`results-correction/correctness-summary.json` (derived by
`scripts/v0a_correctness_derive.py`).

- Every run proves its intended physical device in its own retained
  stderr (`using device Vulkan1|Vulkan2|Vulkan3|CUDA0 ... (<BDF>)`),
  offloads 37/37 layers to that GPU, and exits cleanly. No run is
  attributable to llvmpipe, the Intel iGPU, the other AMD card, or a
  CPU fallback.
- Backend-local repeatability: stable — all AMD-A x3 runs produce one
  identical visible greedy generation; AMD-B, NV-A/VK, NV-A/CUDA each
  a single clean observation.
- Cross-backend: all five Vulkan runs (AMD-A x3, AMD-B, NV-A) produce
  byte-identical visible generations; the NV-A CUDA run DIFFERS at one
  word choice ("could be any word or phrase" vs "could be anything").
  Vulkan and CUDA are therefore NOT exact-equal at this fixture — a
  real same-GPU cross-backend numerical difference, retained as
  evidence (NOT a defect and NOT a new threshold; logits not exposed).
  This supersedes the original campaign's "semantically equal across
  backends" claim.

## Corrected materialization evidence (supersedes the preliminary walltimes)

The original `llama-cli -n 0` "load-only" runs demonstrably entered the
interactive prompt, evaluated input, and produced output before exit;
their wall times are NOT load/ready/materialization times. Those files
(`results/mat2-*`, `results/materialization-walltime.txt`) are retained
unmodified and reclassified PRELIMINARY/SUPERSEDED.

Corrected zero-inference harness (`scripts/v0a_materialization_run.py`):
launches the pinned binary on the pinned model/device, waits for the
mechanically detectable interactive-ready banner WITHOUT submitting any
model prompt, samples memory at pre-launch / ready / predeclared 5 s
idle-hold boundaries with event markers, then sends only `/exit`.
Zero-inference proof per run: retained transcript contains no
evaluation markers, no generated text; every canonical run.json records
`zero_inference_proven: true`. Diagnostic validation preceded canonical
collection.

Corrected medians (3 independent process runs per arm;
`results-correction/materialization-correction.json`):

| metric                     | AMD-A VK  | NV-A VK   | NV-A CUDA |
|----------------------------|-----------|-----------|-----------|
| startup-to-ready (s)       | 26.48     | 13.02     | 11.36     |
| VRAM at ready (B)          | 3254091776| 3279945728| 3423600640|
| host RSS at ready (kB)     | 469720    | 1003172   | 789488    |

NV-A Vulkan-minus-CUDA deltas (CALCULATED): +1.66 s to ready; -143655
kB VRAM (Vulkan lower); +213684 kB host RSS (Vulkan higher). VRAM/RSS
were flat from ready through the idle hold in every run.

## Cross-vendor AMD-vs-NVIDIA (DESCRIPTIVE ONLY — not a backend ratio)

AMD-A Vulkan decode 43.7 t/s vs NV-A Vulkan decode 95.5 t/s on the same
host/probe/model: different silicon, descriptive only.

## Backend capability facts (machine-readable: capabilities/)

- AMD Polaris RADV advertises NO fp16 compute storage→compute fast
  path, NO integer-dot, NO matrix cores (subgroup 64) in the retained
  llama.cpp banner; NVIDIA ICD advertises fp16, integer-dot,
  NV_coopmat2 (subgroup 32). These are ADVERTISED-CAPABILITY facts of
  this stack — a demonstrated causal decomposition of the AMD/NVIDIA
  throughput gap (compute-bound vs memory-bound vs f32-arithmetic-
  bound) is NOT established by V0-A and belongs to #142/V0-B.
- The Vulkan loader also enumerates llvmpipe (CPU) and the Intel iGPU;
  every corrected run proves the pinned device via its own stderr
  BDF-bearing device line, so no silent fallback can pass unnoticed.
- The retained endpoint capture records NV-A LnkCap 2.5GT/s x16 /
  LnkSta 2.5GT/s x1 — i.e., the endpoint itself advertises 2.5 GT/s.
  The earlier "root port forced Gen3" wording is retracted; nothing in
  the retained evidence establishes root-port state or a forced Gen3
  event. Both NV-A backend arms share the identical physical link
  state, so the same-device Vulkan/CUDA comparison remains valid.

## Explicit non-claims

- No AMD native numbers exist in this campaign; the truthful record is
  NATIVE_BACKEND_UNAVAILABLE for HIP on the frozen stack.
- No claim of bit-equality across backends (and none of
  cross-backend semantic equality — the retained fixture shows a
  one-word divergence); no new numerical threshold.
- No demonstrated sole-cause for the AMD throughput level
  ("compute-limited"/"f32-bound" are NOT claimed as demonstrated); no
  economics classification ("economics-marginal" is NOT claimed).
- llama-server and multi-GPU modes not characterized.
- Individual `-r 5` internal repetition rows unavailable and not
  claimed (aggregate rows + 3 process runs per arm only).
