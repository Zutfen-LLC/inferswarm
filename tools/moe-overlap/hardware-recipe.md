# Hardware recipe — resident MoE overlap prototype (proposed, NOT authorized)

This is a proposed bounded experiment plan for the separately authorized
hardware phase (Hermes handoff). Executing any step below requires the
maintainer's explicit authorization per `AGENTS.md` / `docs/campaign-gate-ordering.md`;
this document grants nothing. STOP conditions and resource bounds below are
part of the proposal.

## Objective and success question

Does overlapping CPU expert computation, GPU expert computation and activation
transfers reduce one representative MoE block's critical-path latency relative
to a strictly serialized execution of identical work on identical resident
weights? Success criterion: the overlapped arm's median block time is lower
than the serial arm's by more than run-to-run spread, with all correctness
gates passing. A measured non-improvement is a valid STOP result and is
retained, not retried.

## Subject host

`inferswarm01` (the accepted single-host baseline subject): Xeon E5-2683 v3
(14 cores), ~125.7 GiB RAM, RTX 3060 12 GB (sm_86), CUDA-capable. No host
configuration change, driver installation, or new credentials are part of this
recipe; the existing toolchain that built the accepted binaries is assumed.

## Assets

| Asset | Identity |
|---|---|
| llama.cpp source | `ggml-org/llama.cpp` @ `b29c606e28a01b1bc8c1351026a0fa6e616bf6c4` (tarball sha256 `03fb04316eb32a7b7347004a79a8dd60531c02f5a064d853fed3b53828951723`, fetched and verified by `tools/moe-overlap/build.py`) |
| Harness | `tools/moe-overlap/moe_overlap_harness.cpp` at the reviewed commit of this branch |
| Model shard (weights only, no download) | existing local backing: `Qwen3.8-Flash-Next-Q8_0-00004-of-00006.gguf`, recorded lfs sha256 `bfa634025fabbd2658bf7694bc80b90e571699c768723f844c934c7ef06c691a` (from the reference bundle `model-and-runtime.json`; verify with sha256sum before use and STOP on mismatch) |
| Block | `blk.2` MoE FFN (all eight required tensors are in shard 00004; census-relative offsets recorded in the reference bundle `q8-metadata.json`) |
| Inputs | SYNTHETIC seeded gaussians (default) — labeled as such in every output. A real captured activation fixture (`--inputs-file`, F32 `[2560×T]` little-endian) may be supplied if the maintainer authorizes the minimal capture described in the reference bundle `INPUT_GAPS.md`; otherwise the run is explicitly "real weights, real routing under synthetic activations" and is reported with that caveat |

## Build (hardware host)

```bash
cd <inferswarm checkout at the reviewed commit>
python3 tools/moe-overlap/build.py --cuda          # CPU closure + CUDA TU, -O3, sm_86
python3 tools/moe-overlap/build.py                 # CPU-only binary (fallback/comparison)
```

Requires a working `nvcc` (the toolchain that produced the accepted B-side
binaries) and network access to fetch the pinned tarball once (or
`MOE_OVERLAP_TARBALL`/`MOE_OVERLAP_SOURCE` pointing at an already-verified
copy). Record compiler identity (`nvcc --version`, `gcc --version`) in the run
notes. Expected resource bounds for the build: ~2 GiB disk in the cache
directory, ~8 GiB RAM for the fat CUDA TU, single-job nvcc plus parallel CPU
TUs.

## Pre-launch checks (machine-observable, cheap)

1. `moe_overlap_harness --list-devices` → exactly one CPU device and one GPU
   device (CUDA). If no GPU device appears, STOP (driver/toolchain anomaly,
   not a fallback case).
2. sha256sum of the model shard equals the recorded value; else STOP.
3. Free VRAM ≥ 4 GiB and free RAM ≥ 8 GiB (weights slice ~2.55 GiB host + up
   to ~2.55 GiB device-resident at `--split 256`, plus small graph buffers);
   else STOP (resource anomaly).

## Execution (one bounded worker session, one process per shape)

Loading (~2.55 GiB selective read + GPU slice upload) happens once per process
and is reported separately; timing uses only block execution.

```bash
B=~/.cache/inferswarm-moe-overlap/build-cuda/moe_overlap_harness_cuda
GGUF=/path/to/Qwen3.8-Flash-Next-Q8_0-00004-of-00006.gguf

# decode shape (T=1): 3 warmups, 10 measured repetitions, balanced arm order
$B --gguf "$GGUF" --layer 2 --tokens 1  --split 256 --secondary cuda \
   --threads 14 --warmup 3 --reps 10 --self-check-negative \
   --json results-decode-t1.json

# prefill shape (T=128)
$B --gguf "$GGUF" --layer 2 --tokens 128 --split 256 --secondary cuda \
   --threads 14 --warmup 3 --reps 10 --self-check-negative \
   --json results-prefill-t128.json
```

Optional secondary evidence (not the success criterion): one run with
`--split 128` and one with `--split 384` to characterize sensitivity of the
overlap benefit to ownership balance.

## Correctness gates (each run must pass before its timing is considered)

From the JSON: `verdict.pass == true`; every repetition's
`routed_counts_ok`, `serial_vs_ref_pass`, `overlap_vs_serial_bitwise`,
`overlap_vs_serial_pass` true; `determinism_recheck.reference_bitwise` and
`.serial_bitwise` true; `negative_control.comparator_rejected` true. Any
failure: retain the failing JSON, STOP, report; do not adjust tolerances or
retry to repair.

## Timing outputs to retain

Per run: `summary` (medians/mins, `overlap_to_serial_ratio`,
`serial_minus_overlap_ms`), per-repetition `serial_ms`/`overlap_ms` and the
stage breakdowns (serial: h2d/cpu/sec/d2h/combine; overlapped:
h2d_submit/cpu/sec_wait/combine), `load.weights_ms`, `load.secondary_slice_ms`,
plus `config` for the identity echo. Interpretation guardrails: the serial arm
is the in-process reference for the scheduling delta only; neither arm is a
full-model tokens/s claim. GPU utilization, if desired, is optional supporting
evidence (`nvidia-smi dmon` sampling around the runs) and never the success
criterion.

## Resource bounds and stop conditions

- One process per shape; sequential; no services, daemons, RAM disks or
  persistent state. Total wall-clock budget: ≤ 30 minutes including builds.
- Memory ceilings as in pre-launch; weights read is bounded by the harness to
  the eight tensors.
- STOP and retain: any correctness-gate failure, any resource exhaustion, GPU
  errors, thermal throttling beyond the host's normal envelope, or a driver
  anomaly. A measured "overlap did not help" is a result, not a failure.
- No rerun to repair wording or numbers; failures are preserved as-is.

## Provenance to record with results

Reviewed commit of this branch; tarball sha256; harness `config` block
(pins, backends, thread counts, split); model shard sha256; compiler
identities; host identity and boot epoch; the three JSON outputs; the
optional dmon capture if taken. These records are campaign evidence candidates
only if the maintainer accepts them; this recipe does not create a gate.
