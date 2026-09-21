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
- Phase 2 placement freeze — DONE 2026-09-20: ngl=1 selected by the
  frozen mechanical rule (smallest nonzero model-buffer residency on
  the selected die: 1,050,275,840 bytes at 0000:06:00.0; excluded die
  0000:09:00.0 shows only 12,288 bytes of driver-enumeration noise,
  under the frozen <1 MiB bound). Load-only preflight; no correctness
  output emitted; all attempts retained in evidence.
- Phase 3 correctness ladder — EXECUTED 2026-09-20, halted at first
  case per the frozen escalation rule: case-256 FAIL_DETERMINISTIC
  (all 3 repeats identical; tokens diverge from the accepted R8-D
  reference at position 5: candidate 34227 vs reference 271).
  Cases 1024/3072/4096 NOT_EXECUTED per the escalation contract.
- Phase 4 execution-truth proof — residency deltas captured per
  attempt and per ladder run (selected die loaded/released, excluded
  die flat); platform health windows clean (no amdgpu fault classes,
  0 correctable RxErr lines).
- Phase 5 restart control — NOT REACHED (only required for a PASS
  path; the correctness terminal short-circuits escalation).
- Phase 6 platform health — collector armed between cases; final
  snapshot clean; no stop classes fired.

## Terminal result

**R8H_QWEN38_VULKAN_CORRECTNESS_FAIL** (reduced 2026-09-20,
scripts/issue234_reduce.py, evidence/TERMINAL.json):

- backing VERIFIED (3/3 members byte-exact vs accepted authority,
  total 72,546,461,344);
- runtime QUALIFIED (pin b29c606e Vulkan-only build, selector binds
  die 06:00.0, other die excluded);
- placement LEGAL (ngl=1, nonzero residency on selected die only);
- Vulkan execution PROVEN and DETERMINISTIC (3/3 identical repeats);
- case-256 deterministically differs from the accepted R8-D
  true-greedy reference at token 5 (34227 "e" → "forty-one…" vs
  271 "\n"): a cross-backend numerical divergence in the IQ1_S
  dequant/greedy path, not nondeterminism and not a platform fault.

Meaning: this die/runtime pair is a deterministic, healthy Vulkan
execution environment whose greedy token stream does NOT match the
accepted CUDA-derived reference byte-for-byte. It does not qualify as
a truthful local execution environment for this subject under the
frozen exact-match contract, and nothing here authorizes mixed-vendor
execution. A successor campaign may investigate the divergence class
(near-tie logits at the divergence point) under a separately reviewed
issue.

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
