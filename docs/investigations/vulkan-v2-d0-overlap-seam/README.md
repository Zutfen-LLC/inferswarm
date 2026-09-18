# V2-D0 — Vulkan workload-overlap observation-seam qualification (issue #219)

Status: IN PROGRESS — seam implemented and validated on-host; campaign
evidence capture pending. No terminal claimed yet.

## Objective

Qualify one non-perturbing observation seam that can prove whether the
two independently qualified V340L dies execute their correctness-bearing
Vulkan GPU workload at overlapping times (the #216 V2-D prerequisite).
This issue qualifies the measuring instrument ONLY.

## Selected seam (frozen rubric: SEAM-RUBRIC.json)

`vulkan-timestamp-observe-seam`: an insert-only diagnostic patch to the
pinned ggml-vulkan.cpp (llama.cpp 8ea290247c87ced2ab245b056ffe96dbcf90d36c)
that:

- is inert unless `GGML_VK_OBSERVE_INTERVAL` is set (single env gate);
- fail-closed capability proof at device creation: compute queue family
  timestampValidBits in [2,64], timestampComputeAndGraphics,
  VK_EXT_calibrated_timestamps enumerated, DEVICE + CLOCK_MONOTONIC
  calibrateable domains present;
- writes device timestamp queries (BEGIN at compute command-buffer
  creation, END at each compute command-buffer end-for-submit) inside
  the existing compute submissions — no new buffers, barriers,
  semaphores, fences, or host waits;
- drains query results ONLY after the runtime's own fence wait
  (end of ggml_vk_wait_for_fence), without eWait;
- at every drain takes a calibrated timestamp pair
  (DEVICE + CLOCK_MONOTONIC) via vkGetCalibratedTimestampsEXT and
  retains raw values + the implementation-reported maxDeviation;
- emits an append-only JSONL record (drain records + one final header
  with device identity: deviceUUID, PCI bus/device/function, vendor/
  device IDs, timestampPeriod, timestampValidBits, tick index);
- changes zero pristine source lines (provably insert-only diff,
  re-generated deterministically by scripts/issue219_patch.py from the
  pristine bytes).

Rejected candidates (see rubric): process/wrapper lifetime;
GPU-utilization polling; the existing GGML_VK_PERF_LOGGER seam (adds a
per-graph-compute host fence wait — perturbs async ordering; device
domain only; never checks timestampValidBits).

## Exact-stack capability facts (Phase 1, measured)

Both V340L dies (RADV Mesa 25.0.7-2+deb13u1, Vulkan loader 1.4.309):
timestampComputeAndGraphics=true, timestampPeriod=37.037 ns,
timestampValidBits=64 on all queue families,
VK_EXT_calibrated_timestamps revision 2, calibrateable domains include
DEVICE + CLOCK_MONOTONIC. Live measured calibration maxDeviation on the
instrumented runtime: 7-19 µs per capture.

## Non-claims

V2-D0 establishes NO: concurrent V340L correctness qualification; V2-D
repeatability; shared-x1 throughput/contention; 60-minute stability;
thermal/power envelope; fault isolation; device-reset isolation; 16-GiB
aggregate claim; Qwen3.8/DeepSeek V4.1 results; production support;
planner/backend policy. A PASS would say only that #216 has a qualified
way to observe actual GPU-work overlap.

## Layout

- `SEAM-RUBRIC.json` — frozen candidate ledger + selection rubric +
  conservative-overlap contract (generated, single source:
  scripts/issue219_seam_rubric.py)
- `capability/` — Phase 1 raw probes + CAPABILITY.json
- `perturbation/` — Phase 3 disabled/enabled arms per die (3x each)
- `discrimination/` — Phase 5 sequential control + concurrent candidate
- `REDUCTION.json` — Phase 6 replayed reduction + terminal
- `runtime-patch.diff` — the exact committed patch bytes
