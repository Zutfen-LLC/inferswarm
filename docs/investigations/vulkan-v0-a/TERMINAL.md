# V0-A terminal: V0A_MATCHED_CHARACTERIZATION_COMPLETE

Issue #141 terminal classification.

- Required AMD Vulkan evidence: COLLECTED (2 physical Polaris GPUs
  inventoried; full campaign on 02:00.0; smoke on 03:00.0; greedy
  correctness 3x + 1x; matched perf distributions).
- AMD HIP/ROCm native: truthfully unavailable — mechanically
  demonstrated (error 100 / CPU-agent-only rocminfo on the frozen
  stack), which the terminal definition explicitly allows.
- NVIDIA Vulkan + CUDA matched control on one physical GPU (04:00.0,
  RTX 3060 Ti, host inferswarm02 — no frozen-topology node touched):
  COLLECTED, same-device ratios computed (pp512 0.949, tg128 0.884
  Vulkan/CUDA).
- Correctness/stability: no crashes, shader-compile failures, device
  loss, or output instability observed in any retained run; greedy
  fixture byte-stable across every run and device.
- Every canonical run pins and proves the intended physical
  device/backend via `--device` + enumeration banner.

Recommendation for V0-B: Vulkan on NVIDIA is within ~5-12% of CUDA for
this probe/subject, making it a credible portable substrate where CUDA
is unavailable; AMD Polaris Vulkan works correctly but is
compute-limited (no fp16/matrix cores) — treat as correctness-yes,
economics-marginal. A future V0 qualification on RDNA-class AMD with
fp16/coopmat would likely change the AMD economics picture.
