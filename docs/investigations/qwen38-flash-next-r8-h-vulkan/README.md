# R8-H — Qwen3.8-Flash-Next UD-IQ1_S on one V340L die through pinned llama.cpp Vulkan

Issue #234. Status: **IN PROGRESS** — authority frozen, producers
committed and closure-pinned, runtime qualified on inferswarm02;
canonical physical execution pending model backing transfer
(blocked on the inferswarm01 authorized_keys repair, see
`evidence/host-inventory/` once retained).

Campaign: `issue234-r8h-vulkan-single-die-qualification`

The purpose is narrow: qualify ONE independently addressed Radeon Pro
V340L Vega10 die as a truthful local Vulkan execution resource for the
exact accepted Qwen3.8-Flash-Next UD-IQ1_S subject under the pinned
llama.cpp runtime (`b29c606e`, v0.4.1), before authorizing any Vulkan
RPC, mixed AMD/NVIDIA, multi-die, or ordinary InferSwarm serving
experiment. A prerequisite/fail terminal is a valid result.

## Frozen authorities (consumed, never reopened)

- Model: exact accepted UD-IQ1_S 3-member split, 72,546,461,344 bytes,
  member sha256 `88a14208…`, `3a62e35b…`, `0e25ceae…` (R8-A/R8-B/R8-D
  authority, re-hashed at freeze).
- Runtime: llama.cpp `b29c606e28a01b1bc8c1351026a0fa6e616bf6c4`
  (v0.4.1), Vulkan-only build (`GGML_VULKAN=ON`, `GGML_CUDA=OFF`,
  Release, g++ 14.2.0, cmake 3.31.6).
- Correctness: accepted R8-D frozen true-greedy reference (fixture
  ladder sha256 `419bde66…822db`; canonical request contract
  `samplers=["top_k"], top_k=1, temperature=0.0, seed=0,
  cache_prompt=false, stream=false, return_tokens=true, n_predict=8`).
- Hardware: V2-series V340L authority (two INDEPENDENT 8-GiB dies —
  never one 16-GiB resource); V2-G remediated-path context.

See [PHYSICAL-AUTHORITY.json](PHYSICAL-AUTHORITY.json) for the
machine-derived binding (every pinned file re-hashed against its
accepted MANIFEST at build).

## Physical subject (fresh census, boot 433128ac, 2026-09-20)

| die | BDF | Vulkan deviceUUID | heap |
|---|---|---|---|
| selected (primary arm) | 00000000:06:00.0 | 00000000-0600-0000-… | 8176 MiB |
| excluded (zero active bytes) | 00000000:09:00.0 | 00000000-0900-0000-… | 8176 MiB |

Selector: `GGML_VK_VISIBLE_DEVICES=1` (vulkaninfo GPU1 == server
Vulkan0 under restriction; RADV UUID encodes the BDF — V2-E #228 join,
both sides 16-char domain-prefixed).

## Phases

- Phase 0 reconcile/freeze — DONE (branch `issue-234-r8h-vulkan-qualification`
  off origin/main@8862ada; predecessor merges verified ancestral;
  producer closure written).
- Phase 1 runtime qualification — DONE (build + identity + selector
  mapping; no model).
- Phase 2 placement freeze — PENDING model backing (load-only ngl
  ladder, smallest nonzero residency rule, output-blind).
- Phase 3 correctness ladder — PENDING (case-256 → 1024 → 3072 → 4096,
  3 repeats, exact token/stop vs frozen reference).
- Phase 4 execution-truth proof — PENDING (residency deltas on both
  dies, backend activity, process/drm association, PLE host-side
  classification).
- Phase 5 restart control — PENDING (exact-PID termination, die idle
  tolerance, relaunch, case-256 + largest passed case).
- Phase 6 platform health — collector built (amdgpu/AER/PCIe stop
  classes from raw journal bytes; armed between ladder cases).

## Terminals (deterministic, scripts/issue234_reduce.py)

R8H_QWEN38_VULKAN_SINGLE_DIE_QUALIFICATION_PASS ·
R8H_QWEN38_VULKAN_CORRECTNESS_FAIL · R8H_QWEN38_VULKAN_PLATFORM_FAIL ·
R8H_QWEN38_VULKAN_RUNTIME_PREREQUISITE · R8H_QWEN38_BACKING_PREREQUISITE ·
R8H_EVIDENCE_BLOCKED

## Non-claims

No Vulkan RPC, no mixed AMD/NVIDIA execution, no simultaneous both-die
use, no coherent 16-GiB claim, no cross-die external memory, no
planner preference, no throughput claim, no production support, no
runtime repair, no llama.cpp revision change, no alternate
quantization, no ordinary InferSwarm serving, no causality between the
historical RxErr condition and amdgpu faults.
