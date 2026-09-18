# V2-D0 — Vulkan workload-overlap observation-seam qualification (issue #219)

Status: COMPLETE — terminal `V2D0_VULKAN_WORKLOAD_OVERLAP_SEAM_PASS`
(derived by `scripts/issue219_reduce.py` from retained bytes; see
`REDUCTION.json`). The qualified seam is available to #216 as its
GPU-work-overlap observation instrument.

Instrument validation results (Phase 5, conservative contract):

- sequential (non-overlap) control: NON_OVERLAP with margin — the
  upper bound on overlap after ADDING the full uncertainty is
  −4.072 s (the runs are seconds apart; uncertainty is ~36 µs);
- concurrent (overlap-candidate) schedule: OVERLAP — the lower bound
  on overlap after SUBTRACTING the full uncertainty is +2.40 ms
  (combined uncertainty ~50 µs, worst per-capture maxDeviation 26.6 µs).

Non-perturbation (Phase 3): 12/12 runs clean — both dies, disabled and
enabled arms, 3 repeats each: byte-exact visible output vs the accepted
frozen V1-A reference (accepted comparator), accounting tuple 0/0/0
(accepted reducer), full offload, no fallback, clean exits, selected
BDF per die as frozen (Vulkan1→06:00.0, Vulkan2→09:00.0).

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
instrumented runtime: 7-28 µs per capture across all retained
captures (Phase 3 enabled arms reach 27.6 µs; discrimination
captures reach 26.6 µs).

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

## Provenance and review corrections (round 1)

Adversarial exact-head review (two lanes) at the pre-correction head
produced one P1 (authored-boolean trap) and several P2/P3 findings;
all are closed in the correction commit:

- The reducer now REPLAYS the non-perturbation predicates from
  retained raw bytes: retained per-run stdout/stderr are re-hashed
  against the ledger digests, then the accepted comparator
  (v0c_correctness) and accepted accounting reducer (v1c_accounting)
  re-run over the bytes; ledger summaries are cross-checks only and
  any disagreement fails closed.
- `capability_ok` is parsed from the retained CAPABILITY.json (never
  hard-coded); a capability-missing record yields the UNAVAILABLE
  terminal.
- The observe-record header guard actually fails closed on a third
  header record; timestampValidBits is range-checked [2, 64].
- Added controls: envelope-vs-union discrimination, forged valid bits,
  doctored-ledger-vs-bytes cross-check, rubric-digest binding, and a
  host-portable insert-only check of the committed diff.
- Terminal re-derived from the same retained bytes: unchanged
  (`V2D0_VULKAN_WORKLOAD_OVERLAP_SEAM_PASS`).
- Lane-1 P3 (informational): calibration drift across the ~1.2 s
  window is not spec-bounded by maxDeviation; worst realistic drift
  (≤500 ppm → ≤600 µs) remains ≥4× below the +2.40 ms overlap margin
  and ~3 orders below the −4.07 s control gap. The eAllCommands
  end-tick brackets conservatively (begin ticks can only be early);
  the pool-growth destroyQueryPool race is unreachable at this
  campaign's tick volume and fail-closed (availability=0) if reached.
