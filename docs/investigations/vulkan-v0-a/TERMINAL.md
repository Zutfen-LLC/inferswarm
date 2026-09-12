# V0-A terminal: V0A_MATCHED_CHARACTERIZATION_COMPLETE

Issue #141 terminal classification, re-derived after the correction
campaign (`METHODOLOGY-CORRECTION.md`, freeze `8115933`; addenda
`36af6e0`, `d265480`, `51f9489`).

- Required AMD Vulkan evidence: COLLECTED (2 physical Polaris GPUs
  inventoried; full campaign on 02:00.0; smoke on 03:00.0; corrected
  raw correctness runs 3x + 1x with per-run device proof; matched perf
  distributions retained from the original campaign).
- AMD HIP/ROCm native: truthfully unavailable — mechanically
  demonstrated (error 100 / CPU-agent-only rocminfo on the frozen
  stack), which the terminal definition explicitly allows.
- NVIDIA Vulkan + CUDA matched control on one physical GPU (04:00.0,
  RTX 3060 Ti, host inferswarm02 — no frozen-topology node touched):
  COLLECTED, same-device ratios computed from the retained campaign
  (pp512 0.949, tg128 0.884 Vulkan/CUDA).
- Corrected correctness/stability: every corrected run proves its
  physical device in its own stderr (BDF-bearing device line),
  offloads 37/37 layers, and exits cleanly; backend-local generations
  are stable across all arms. A real cross-backend numerical
  difference exists at the greedy fixture (NV-A CUDA differs from all
  Vulkan runs at one word choice); it is retained as evidence per
  Phase 3, does not set any threshold, and does not block this
  terminal (correct + measurable per the issue's blocked-vs-slow
  rule).
- Corrected materialization: canonical zero-inference harness runs
  with mechanically detected ready boundaries and event-marked memory
  sampling supersede the preliminary walltime interpretation;
  corrected distributions are in
  `results-correction/materialization-correction.json`.

## Corrections applied relative to 2b14fba (supersede earlier wording)

1. Manifest regenerated with repository-root paths (lifecycle fixed).
2. Correctness claim now rests on retained raw per-run records, not a
   hand-maintained summary; the cross-backend claim changed from
   "semantically equal" to "Vulkan arms identical to each other, CUDA
   differs at one word".
3. Old materialization walltimes reclassified PRELIMINARY/SUPERSEDED;
   corrected zero-inference distributions recorded.
4. `-r 5` rows are llama-bench aggregates; per-repetition rows
   unavailable and not claimed.
5. AMD causal ("compute-limited"/"f32-bound") and economic
   ("economics-marginal") claims retracted as undemonstrated;
   advertised-capability facts stated, causal decomposition deferred
   to #142/V0-B.
6. NV-A PCIe "root port forced Gen3" wording retracted; only the
   captured endpoint LnkCap/LnkSta is claimed.

## Recommendation for V0-B

Vulkan on NVIDIA is within ~5-12% of CUDA for this probe/subject
(pp512 0.949, tg128 0.884) and materially faster to ready than the
preliminary interpretation suggested remains as corrected: 13.0 s vs
11.4 s (+1.7 s, +15%). Vulkan on Polaris executes correctly and stably
but at ~43.7 t/s tg128 / ~498 t/s pp512 on this stack; WHY that gap
exists (compute, memory, f32 arithmetic, or x1 link) is an open causal
question for #142/V0-B, not a demonstrated verdict. A future V0
qualification on RDNA-class AMD with fp16/coopmat support is the
natural follow-up.
