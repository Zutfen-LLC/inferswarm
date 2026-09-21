# R8-H — Matched backend/device parity: Qwen3.8-Flash-Next UD-IQ1_S across CUDA/Vulkan and NVIDIA/AMD

Issue #234 (corrected per maintainer amendment, 2026-09-20).
Campaign: `issue234-r8h-matched-backend-device-parity`.
Status: **COMPLETE — `R8H_QWEN38_MULTI_AXIS_DIVERGENCE_CHARACTERIZED`**
(case-256 rung; ladder escalation correctly stopped at first
deterministic divergence).

## 1. Why the original df0cf4 experiment was superseded

The original PR head `df0cf43` ran ONE arm — V340L/Vulkan — and
compared it against the historical R8-D output as the sole correctness
oracle. R8-D was single-host CUDA on two RTX 3060 GPUs plus CPU
spill: a confounded comparator. Its retained observation (V340L
Vulkan case-256, 3 identical repeats, token `34227` at generated
position 5 vs R8-D CUDA `271`, ~1.05 GB selected-die residency,
12,288-byte excluded-die noise, clean platform window) is genuine and
byte-preserved, but it could not establish
`R8H_QWEN38_VULKAN_CORRECTNESS_FAIL` — only that the V340L arm
differed from a historical CUDA-derived stream under unmatched
geometry. That terminal is RETIRED.

The original evidence lives, byte-identical, under
`evidence/superseded-20260920-original-comparator/` (14 files, each
sha256-verified against its df0cf43 git blob by the authority
builder). Three further defects motivated the redo: the physical
producers were edited after the claimed closure commit, and the
assembler registered zero of its advertised controls.

## 2. Corrected experiment — matched A/B/C

Same subject, same minimal placement (`ngl=1`), same pin, same
request, three arms:

| Arm | Host | Device | Backend | binary sha256 (llama-server) |
|---|---|---|---|---|
| A | inferswarm01 | RTX 3060 `GPU-1fc28f83…` @ `00000000:02:00.0` | CUDA (Vulkan OFF) | `9a39749c1ff448fe…` |
| B | inferswarm01 | SAME RTX 3060 (same UUID/BDF) | Vulkan (CUDA OFF) | `21707f2568d80fb7…` |
| C | inferswarm02 | V340L die `00000000:06:00.0` (die `09:00.0` excluded) | Vulkan (CUDA OFF) | `21707f2568d80fb7…` (same bytes as B) |

- llama.cpp pin `b29c606e28a01b1bc8c1351026a0fa6e616bf6c4` for all
  arms. The Vulkan build was produced once on inferswarm01 and the
  identical bin dir deployed to inferswarm02 (ldd-verified), so B and
  C share binary bytes; its CPU component is built with baseline
  intrinsics (`GGML_NATIVE/AVX/AVX2/FMA/F16C/BMI2=OFF`) because 02's
  Celeron G3900 has no AVX — same pin, same source, no runtime
  upgrade.
- Model: exact accepted UD-IQ1_S members, re-hashed on BOTH hosts
  before canonical output (72,546,461,344 bytes, 3/3 sha256 verified
  per host).
- Selector bindings proven mechanically: A by
  `CUDA_VISIBLE_DEVICES=GPU-<uuid>`; B by
  `GGML_VK_VISIBLE_DEVICES=0` under the NVIDIA ICD (residency probe);
  C by `GGML_VK_VISIBLE_DEVICES=0` under the radeon ICD (residency
  probe; RADV UUID encodes the BDF).
- A/B same-GPU proof: both selectors bind `00000000:02:00.0` /
  `GPU-1fc28f83…` (census join + per-repeat selected-device residency
  on that exact GPU, sibling `d5c05739…` flat at 1–2 MiB counter
  noise through every repeat).

## 3. Result — case-256, 3 repeats per arm, all deterministic

| Arm | tokens (identical ×3) |
|---|---|
| A (3060/CUDA) | `328 760 40554 1 271 12188 279 1727` |
| B (3060/Vulkan) | `561 324 55965 51624 29014 271 248068 271` |
| C (V340L/Vulkan) | `561 324 55965 51624 29014 34227 18030 16382` |

Pairwise: **A≠B from generated position 0; B≠C at position 5
(`271` vs `34227`); A≠C from position 0.** Per frozen order, ladder
escalation STOPPED at case-256 (no later rung was executed).

### Position-5 score characterization (R8-E methodology, non-perturbing)

Three DIFFERENT winners from materially different score structures:

| Arm | winner | runner-up | margin | notes |
|---|---|---|---|---|
| A | `12188` @ 17.114 | `760` @ 16.349 | 0.766 | `271` rank 79; `34227` rank 21184 |
| B | `271` @ 16.682 | `34227` @ 15.996 | 0.686 | focal pair occupies ranks 1/2 |
| C | `34227` @ 16.476 | `271` @ 16.206 | 0.269 | focal pair occupies ranks 1/2 |

Raw sidecars (jsonl + float32 rows, 248,320 floats each) retained
under `evidence/candidate/characterization/`; observation runs
reproduced the canonical token streams exactly (non-perturbation
proven per arm). The historical R8-E near-tie (271/34227) is seen on
the VULKAN arms, not on CUDA — and B vs C still picks opposite
winners.

## 4. Terminal

`R8H_QWEN38_MULTI_AXIS_DIVERGENCE_CHARACTERIZED` — the deterministic
A/B/C relation is neither backend-only (A≠B but B≠C) nor device-only
(A≠B). Exact pairwise map retained in
`evidence/TERMINAL.json`/`ASSEMBLY.json`.

Non-claims (explicit):
- NOT an AMD/V340L correctness failure;
- NOT a CUDA correctness failure;
- NOT a driver/silicon defect claim;
- no common-root-cause inference from B≠C or token overlap;
- no Vulkan PASS/FAIL derived from the historical R8-D stream
  (retained as an external anchor only; its two-GPU CUDA geometry is
  not equivalent to Arm A).

## 5. Producer authority (corrected closure doctrine)

- Physical producers frozen at `e7d822a` (host, runtime, placement,
  ladder, health) — byte-identical from that pin through final HEAD,
  and hash-verified as the bytes deployed on BOTH execution hosts
  (`evidence/freeze/deployed-producers.json`).
- Closure `PRODUCER-CLOSURE.json` pins producer commit `6357c8a`
  (ancestor of final HEAD; reduction-producer amendments re-pinned
  per doctrine 7), computed from git blobs at the pin; any
  physical-producer modification after execution fails closed
  (`verify_closure`, exercised by the control suite and tests).
- 36/36 numbered controls all_ok on the final evidence
  (`evidence/ASSEMBLY.json`), covering the original 27 plus the nine
  corrected-campaign controls (same-GPU A/B, backend purity, matched
  geometry, retired-oracle, B==C over-inference, characterization
  gate, exactly-3-repeats, ladder stop, residency-geometry match).

## 6. Validation at final head

- closure verifies (ancestor + blob identity pin→HEAD + worktree);
- deployed producer hashes match pin on both hosts;
- deterministic terminal reduction ×2 (byte-identical);
- `finalize_repository.py --check` and `sync_project_status.py
  --check` pass; CI planner untouched (test module name unchanged).

## 7. Non-events (confirmed)

No RPC, no mixed simultaneous AMD/NVIDIA execution, no cross-die
V340L use, no runtime upgrade past the pin, no alternate
quantization, no planner policy change, no ordinary serving traffic.
