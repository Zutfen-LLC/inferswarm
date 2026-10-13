# Hardware recipe — resident MoE overlap prototype (proposed, NOT authorized)

This is a proposed bounded experiment plan for the separately authorized
hardware phase (Hermes handoff). Executing any step below requires the
maintainer's explicit authorization per `AGENTS.md` / `docs/campaign-gate-ordering.md`;
this document grants nothing. STOP conditions and resource bounds below are
part of the proposal.

Current numerical status (2026-10-13): the legacy CPU-unsplit criterion below
is unchanged and its T=128 FAIL remains recorded. The new independent backend
operand reference is an **implemented offline check with physical validation
pending**. Use the untimed export/check commands in
[`numerical-reference.md`](numerical-reference.md); it also documents missing
whole-fixture weights, reserved inputs and the separate proposed criterion.
No hardware run is part of the
offline correction task. CUDA builds still require the externally documented
nvcc-wrapper/libcuda-link amendments; build-system repair is out of scope.

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
| Model shard (weights only, no download) | existing local backing: `Qwen3.8-Flash-Next-Q8_0-00004-of-00006.gguf`, recorded lfs sha256 `bfa634025fabbd2658bf7694bc80b90e571699c768723f844c934c7ef06c691a` (from the reference bundle `model-and-runtime.json`; reuse retained verified identity when unchanged custody makes it applicable; otherwise verify once and STOP on mismatch) |
| Block | `blk.2` MoE FFN (all eight required tensors are in shard 00004; census-relative offsets recorded in the reference bundle `q8-metadata.json`) |
| Inputs | SYNTHETIC seeded gaussians (default) — labeled as such in every output. A real captured activation fixture (`--inputs-file`, F32 `[2560×T]` little-endian) may be supplied if the maintainer authorizes the minimal capture described in the reference bundle `INPUT_GAPS.md`; otherwise the run is explicitly "real weights, real routing under synthetic activations" and is reported with that caveat |

## Build (hardware host)

```bash
cd <inferswarm checkout at the reviewed commit>
ARCHIVE=/path/to/retained/llama.cpp-b29c606e28a01b1bc8c1351026a0fa6e616bf6c4.tar.gz
RUN_DIR=$(mktemp -d "$HOME/.cache/moe-overlap-pr307.XXXXXX")
env -u MOE_OVERLAP_SOURCE -u MOE_OVERLAP_OPT MOE_OVERLAP_TARBALL="$ARCHIVE" \
    python3 tools/moe-overlap/build.py --cache "$RUN_DIR" --cuda --jobs 2
B="$RUN_DIR/build-cuda/moe_overlap_harness_cuda"
```

Requires a working `nvcc` (the toolchain that produced the accepted B-side
binaries) and the retained source archive. The fresh directory makes
`build.py` verify the archive SHA-256 and extract a new source tree, verify the
contract file digests, and compile into an empty build directory. If the
archive is absent, fetch the pinned source archive once within the separately
authorized handoff; no toolchain installation is part of this recipe. Record
compiler identity (`nvcc --version`, `gcc --version`, `g++ --version`).

The current recipe compiles the CPU closure plus all 188 CUDA translation
units at this pin (top-level `.cu` files and template instances), using `-O3`
and `sm_86` for CUDA. It defines `GGML_USE_CUDA` at compile time for the host
closure too and links `libcuda` for the pin's enabled VMM path in addition to
the runtime/cuBLAS libraries. CUDA compilation runs first, with
`min(--jobs, 8)` workers; host compilation follows with `--jobs` workers. The
command above therefore permits two concurrent compiles in each phase. It
builds one CUDA executable containing both arms and the CPU reference. A
separate CPU fallback/comparison build is unnecessary.

Complete CUDA compilation/linking and its peak RAM/disk use are unverified by
the offline correction tests. Earlier estimates for one fat CUDA TU do not
bound this full closure. The authorized handoff must set build memory/disk
ceilings independently of the admission floors below.

## Pre-launch checks (machine-observable, cheap)

1. `"$B" --list-devices` → exactly one CPU device and one GPU
   device (CUDA). If no GPU device appears, STOP (driver/toolchain anomaly,
   not a fallback case).
2. Confirm the retained verified model-shard identity remains applicable to
   this unchanged backing. If verification is absent or custody/identity has
   materially changed, hash once against the recorded value; else reuse the
   retained verification for both shapes. STOP on mismatch.
3. Free VRAM ≥ 4 GiB and free RAM ≥ 8 GiB (CALCULATED weights slice ~2.50 GiB
   host and ~1.25 GiB device-resident expert half at `--split 256`, before
   graph buffers and native scratch allocations);
   else STOP (resource anomaly).

These free-memory values are **admission floors**, not maximum allocations or
execution limits. They do not establish peak resource use. Separate execution
ceilings and their enforcement belong to the approved handoff.

## Execution (one bounded worker session, one process per shape)

Loading (~2.50 GiB selective read + GPU slice upload) happens once per process
and is reported separately; timing uses only block execution.

```bash
# B is the CUDA executable in the fresh RUN_DIR from the build above.
GGUF=/path/to/Qwen3.8-Flash-Next-Q8_0-00004-of-00006.gguf

# decode shape (T=1): 3 warmups, 10 measured repetitions, balanced arm order
"$B" --gguf "$GGUF" --layer 2 --tokens 1  --split 256 --secondary cuda \
   --threads 14 --warmup 3 --reps 10 --self-check-negative \
   --json results-decode-t1.json

# prefill shape (T=128)
"$B" --gguf "$GGUF" --layer 2 --tokens 128 --split 256 --secondary cuda \
   --threads 14 --warmup 3 --reps 10 --self-check-negative \
   --json results-prefill-t128.json
```

The proposed scope is exactly these two shapes at `--split 256`, sequentially.

## Correctness gates (each run must pass before its timing is considered)

From the JSON: `verdict.pass == true`; every repetition's
`routed_counts_ok`, `serial_vs_ref_pass`, `overlap_vs_serial_bitwise`,
`overlap_vs_serial_pass` true; `determinism_recheck.reference_bitwise` and
`.serial_bitwise` true; `negative_control.comparator_rejected` true. Any
failure: retain the failing JSON, STOP, report; do not adjust tolerances or
retry to repair.
Native compute failure also stops output reads/comparisons immediately, joins
outstanding backend work before buffer release, and makes the verdict fail
even during determinism replay or the negative control. An uncompleted check
is not comparator rejection; failed runs do not emit arm-output dumps.

## Timing outputs to retain

Per run: `summary` (medians/mins, `overlap_to_serial_ratio`,
`serial_minus_overlap_ms`), per-repetition `serial_ms`/`overlap_ms` and the
stage breakdowns (serial: h2d/cpu/sec/d2h/combine; overlapped:
h2d_submit/cpu/d2h/combine), `load.weights_ms`, `load.secondary_slice_ms`,
plus `config` for the identity echo. Interpretation guardrails: the serial arm
is the in-process reference for the scheduling delta only; neither arm is a
full-model tokens/s claim. GPU utilization, if desired, is optional supporting
evidence (`nvidia-smi dmon` sampling around the runs) and never the success
criterion.

## Resource bounds and stop conditions

- One process per shape; sequential; no services, daemons, RAM disks or
  persistent state. Total wall-clock budget: ≤ 30 minutes including builds.
- Freeze separate build and execution RAM/VRAM/disk ceilings plus an external
  supervisor/deadline mechanism in the authorized handoff before launch.
  Admission floors are not ceilings, and the harness itself does not enforce
  memory caps or the 30-minute session budget. Its weights read is bounded to
  the eight tensors; graph buffers and backend scratch are additional.
- STOP and retain: any correctness-gate failure, any resource exhaustion, GPU
  errors, thermal throttling beyond the host's normal envelope, or a driver
  anomaly. A measured "overlap did not help" is a result, not a failure.
- No rerun to repair wording or numbers; failures are preserved as-is.

## Provenance to record with results

Reviewed commit of this branch; tarball sha256; harness `config` block
(pins, backends, thread counts, split); model shard sha256; compiler
identities; host identity and boot epoch; the two JSON outputs; the
optional dmon capture if taken. These records are campaign evidence candidates
only if the maintainer accepts them; this recipe does not create a gate.
