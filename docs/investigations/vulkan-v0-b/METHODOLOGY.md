# V0-B — matched-evidence reduction and integration-seam selection: methodology (frozen before supplemental collection)

Issue: Zutfen-LLC/inferswarm#142 (parent #140; consumes accepted #141 /
PR #145 evidence). Branch `vulkan-v0-b` off
`main@273b9e8e32c779f063903cd75a0c6772d0d1e451`.

This document freezes the ONE authorized physical collection of this
bundle — the bounded supplemental matched CPU baseline of issue #142
Phase 2 — BEFORE that collection executes. Everything else in V0-B is
pure reduction of retained V0-A evidence and consumes no new
observation.

## Authority consumed (pinned)

- Issue #141 terminal: `V0A_MATCHED_CHARACTERIZATION_COMPLETE`
  (`../vulkan-v0-a/TERMINAL.md`).
- Accepted PR #145 merge: `273b9e8e32c779f063903cd75a0c6772d0d1e451`
  (V0-A final head `2b2d546dc77350f14016b31a105696b257c063f2`).
- The superseded pre-correction interpretations of PR #145 head
  `2b14fbae21206ecc042e29c5e44df3650f68db2d` are NOT consumed.
- Canonical corrected evidence: `../vulkan-v0-a/results-correction/`
  (correctness-summary.json, materialization-correction.json);
  retained throughput: `../vulkan-v0-a/results/bench-*.csv`
  (identity re-verified mechanically by
  `scripts/v0b_comparability_audit.py`).

## What this issue runs physically (and the only thing)

Issue #142 Phase 2 authorizes at most ONE bounded supplemental matched
CPU baseline on `inferswarm02` to separate "slower than the native
backend" from "not useful compared with host-memory execution" for the
AMD Vulkan path, which has no native comparator
(`NATIVE_BACKEND_UNAVAILABLE`).

Frozen method — fixed before the first run:

- Probe: the UNCHANGED V0-A `build-vulkan` binaries (CPU+Vulkan build;
  `llama-bench` SHA-256
  `f78e6786c7fbdeff3f89c97c02df078cfbc297b886fd3f8010a639720b66914c`;
  `llama-cli` SHA-256
  `c4bcd6a94e0b7fdb1959e6542ce0f85bb905c6c9083fcd1a7b6b0daf15e2c9be`;
  library hashes per `../vulkan-v0-a/probe/build-identities.json`),
  byte-verified before the first run.
- Model: `Qwen2.5-3B-Instruct-Q4_K_M.gguf`, SHA-256
  `9c9f56a391a3abbd5b89d0245bf6106081bcc3173119d4229235dd9d23253f94`,
  1,929,903,264 bytes — byte-verified before the first run.
- Workload: the V0-A canonical bench invocation with `-ngl 0`
  (the ONLY changed parameter; everything else identical):
  `llama-bench -m <subject> -ngl 0 -fa 0 -p 512 -n 128 -r 5 -t 2`
  — 3 independent process runs, matching the V0-A arm structure.
  (Warmups are tool-default and not separately configurable at the
  pinned commit; `-r 5` retains 5 measured repetitions. This argv
  differs from the GPU arms in `-ngl` (the intended change), the
  explicit `-t 2`, and the absence of `-w 3` (not a recognized flag at
  this commit's llama-bench; warmup behavior is tool-default). All
  deviations are declared here, before collection, not absorbed later.)
- Backend-selection proof: each run must record `backends == "CPU"` in
  its own CSV row (proving no GPU backend participated) and zero Vulkan
  enumeration lines in retained stderr; any GPU line fails the run.
- Host identity: `inferswarm02`, Intel Celeron G3900 (2C/2T), 16 GiB
  RAM, Debian 13.6 — the SAME host as every V0-A arm, so the comparison
  shares CPU, RAM, kernel, and filesystem.
- Threads: `-t 2` (both logical CPUs), frozen.
- Scope limits: NO tuning, NO other quantization, NO other model, NO
  longer contexts, NO optimization iterations. Any failure is retained
  as evidence, not retried into success.
- The purpose is DECISION-GRADE context for the AMD usefulness question
  and the integration-seam economics; it is NOT a general CPU
  performance characterization of the host.

## What this issue does NOT run

- No re-run of any V0-A GPU arm (their retained evidence is accepted).
- No new correctness campaign (V0-A's corrected campaign stands).
- No materialization re-measurement (corrected zero-inference
  distributions stand).
- No AMD-native retry (out of scope by issue #141 acceptance).

## Reduction rules

- Ratios are CALCULATED from retained MEASURED medians; every ratio in
  the V0-B reductions must be mechanically traceable to a matched
  same-device pair (per `scripts/v0b_comparability_audit.py`).
- Prefill and decode are never collapsed into one average.
- Cross-vendor numbers remain DESCRIPTIVE_ONLY.
- The CPU supplemental arm is matched to AMD-A/Vulkan only as
  "same host, same probe, same model, same workload" — the physical
  execution substrate differs (device-local VRAM vs host RAM), which is
  exactly the question being asked. It is classified
  `MATCHED_WITH_DECLARED_DIFFERENCE`, and it is NOT a backend ratio.
- Non-claims of V0-A (TERMINAL + RESULTS) carry forward unchanged
  except where this bundle's own evidence adds a scoped finding.
