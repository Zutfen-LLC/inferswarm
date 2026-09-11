# V0-A correction methodology (frozen before any new physical collection)

Issue: Zutfen-LLC/inferswarm#141 (parent #140) — maintainer-review
correction of PR #145.
Reviewed head corrected by this document:
`2b14fbae21206ecc042e29c5e44df3650f68db2d` (branch `vulkan-v0-a`).
Original methodology freeze commit: `76a4307b22cabf98df2793297a46f64c42e33d45`.
Original base: `main@d1afad64ca8bdd05634d3d0e1e09b8077da525d5`.

This correction is ADDITIVE. The frozen `METHODOLOGY.md` is NOT rewritten;
its known limitation stands as historical record:

> Correctness smokes (Phase 3) may precede the freeze

Issue #141 Phase 1 requires the external probe identity to be frozen BEFORE
performance/correctness collection. The Phase-3 smokes therefore proceeded
under an authority that did not yet exist. This document is the replacement
freeze: every new physical observation described here executes only after
this file is committed, and the commit SHA of this file binds all correction
evidence recorded under `results-correction/`, `correctness/`, and the
updated capability records.

## Defects found by maintainer review

1. **Manifest lifecycle violation** — `MANIFEST.sha256` used
   bundle-relative rows (`METHODOLOGY.md`), but the repository-wide
   lifecycle (`tests/test_evidence_manifest_lifecycle.py`) resolves every
   row against the repository root. Hosted CI run `34652071487` fails at
   `Check evidence manifest lifecycle`. Fix: regenerate with
   repository-root paths, self-excluding, duplicate-free, existing,
   digest-exact, living-file-free, and bundle-complete.
2. **Correctness claim exceeds retained evidence** —
   `results/correctness-greedy-fixture.txt` is a hand-maintained summary;
   no raw per-run record exists to prove each run used the intended
   backend/device or produced the claimed output. Fix: re-execute the
   frozen fixture and retain a full raw record per run (§3).
3. **Materialization methodology defect** — `llama-cli -n 0` was described
   as "load-only", but `mat2-*.out` proves the process entered the
   interactive prompt, evaluated input, and produced output before exit;
   `mat2-*.err`/`mat2-*.loadinfo` are empty; RSS/VRAM streams carry no
   event marker binding samples to a model-ready boundary. The
   `materialization-walltime.txt` values are therefore NOT canonical for
   load/ready/materialization claims. They are retained, unmodified, and
   reclassified as PRELIMINARY/SUPERSEDED (§4).
4. **`-r 5` description defect** — methodology says "full per-rep rows
   retained"; the retained CSVs actually contain one
   `avg_ts/stddev_ts` aggregate row per 5-repetition process (3 process
   runs per arm). Individual internal repetition rows do not exist and are
   NOT fabricated (§5).
5. **Causal/economic overreach** — "compute-limited (no fp16/matrix
   cores)", "f32-bound", and "economics-marginal" are stated as V0-A
   verdicts; the evidence supports only the advertised-capability facts
   and the measured numbers. Causal decomposition and economics
   classification belong to #142 / V0-B (§6).
6. **PCIe description overreach** — "root port forced Gen3" for NV-A is
   not established by the retained capture, which records
   `LnkCap 2.5GT/s x16 / LnkSta 2.5GT/s x1` (§7).

## Evidence status after this correction

VALID, retained unchanged (original physical captures; never overwritten):

- original inventory (`inventory/*`, incl. `amd-native-path/*`);
- HIP/ROCm-unavailable evidence (`inventory/amd-native-path/`);
- original `results/bench-*.csv` / `bench-*.err` (the accepted NVIDIA
  throughput campaign: Vulkan pp512 median ~3579.0 t/s, CUDA pp512 median
  ~3773.1 t/s, ratio ~0.949; Vulkan tg128 median ~95.5 t/s, CUDA tg128
  median ~108.0 t/s, ratio ~0.884);
- original materialization files `results/mat2-*` and
  `results/materialization-walltime.txt` (retained bytes; interpretation
  superseded per defect 3);
- original correctness summary `results/correctness-greedy-fixture.txt`
  (retained bytes; superseded as authority by §3);
- original commits `76a4307`, `ed8c5ab`, `2b14fba`.

The committed inventory/correctness artifacts in `ed8c5ab` were restored
from the durable originals identified in that commit's message after a
parallel-session deletion incident; that restoration is recorded and is
not itself disqualifying. Historical captures are never reconstructed
from memory or regenerated.

SUPERSEDED / requiring new observation:

- the correctness summary as terminal authority (defect 2 → §3);
- the materialization interpretation of `mat2-*` / walltime values
  (defect 3 → §4);
- the `-r 5` "per-rep rows" description (defect 4 → §5);
- AMD causal/economic claims (defect 5 → §6);
- NV-A PCIe "root port forced Gen3" wording (defect 7 → §7).

## Unchanged frozen identity (identical for every new run)

The probe identity is NOT rebuilt, retuned, or changed in any way:

- llama.cpp commit: `8ea290247c87ced2ab245b056ffe96dbcf90d36c`
  (ggml-org/llama.cpp).
- Build `build-vulkan` (backends CPU+Vulkan; `Release`,
  `-DGGML_VULKAN=ON`; gcc 14.2.0-19, glibc 2.41-12, cmake 3.31.6,
  ninja 1.12.1), SHA-256:
  - `llama-bench` `f78e6786c7fbdeff3f89c97c02df078cfbc297b886fd3f8010a639720b66914c`
  - `llama-cli` `c4bcd6a94e0b7fdb1959e6542ce0f85bb905c6c9083fcd1a7b6b0daf15e2c9be`
  - `libggml-vulkan.so.0.23.0` `7e4c8980986ec061bffbde1b0b5b6f279526d685d4ed39ec8b982436da83ecc6`
  - `libggml-base.so.0.23.0` `369aaa53f5446eaa2436c6485c69aeadbcfcdb8b247e0baa369d37672af28acc`
  - `libllama.so.0.4.0` `af7bdcb9d68451d8e18b200a73c211fd446a858e38be63e350a19d48efedcf85`
- Build `build-cuda` (backends CPU+CUDA; `Release`,
  `-DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=86`; nvcc CUDA 13.1
  V13.1.115), SHA-256:
  - `llama-bench` `378a89f869db6d9a6715e4ab55d03e3a74e3f930013deb6328776bf0da849e55`
  - `llama-cli` `066d371207569e431cabe95191b38dc41683b722fdb6c2b6b41008d0b4ebda1e`
  - `libggml-cuda.so.0.23.0` `ea71a0e0668e09b8722c26db1db3ad468ca0378703cb32343c089febac817183`
  - `libggml-base.so.0.23.0` `369aaa53f5446eaa2436c6485c69aeadbcfcdb8b247e0baa369d37672af28acc`
  - `libllama.so.0.4.0` `4c9d7381b90684fa9842f1366047a2fa306688e5813c7d026bfccc1e8eb0cedf`

Model — unchanged, byte-identical for every run:

- `Qwen2.5-3B-Instruct-Q4_K_M.gguf`, 1,929,903,264 bytes,
  SHA-256 `9c9f56a391a3abbd5b89d0245bf6106081bcc3173119d4229235dd9d23253f94`.

Correctness fixture — unchanged and re-frozen here verbatim:

- prompt: `The quick brown fox jumps over the lazy dog. Explain what happens next in one sentence:`
- sampling: `--temp 0 --seed 42`, `-n 48`, single-turn;
- device selection: pinned `--device` per arm (`Vulkan1` = AMD-A,
  `Vulkan2` = AMD-B, `Vulkan3` = NV-A, `CUDA0` = NV-A CUDA), `-ngl 99`;
- every new run retains the tool's backend/device enumeration banner and
  offload summary from stderr; a run whose banner does not prove the
  intended physical device is discarded, not reinterpreted.

Arms and run counts for the correction correctness campaign (§3):

- AMD-A (02:00.0) / Vulkan: 3 independent runs;
- AMD-B (03:00.0) / Vulkan: 1 run;
- NV-A (04:00.0) / Vulkan: 1 run;
- NV-A (04:00.0) / CUDA: 1 run.

## Corrected materialization procedure (§4 summary)

The corrected harness (produced by `scripts/v0a_matcorrection_driver.py`)
launches the pinned binary with the pinned model and device, waits for the
mechanically detectable interactive-ready boundary WITHOUT submitting any
model prompt or generating any token, samples pre-launch baseline,
ready-boundary, and predeclared idle-hold memory, then sends only the CLI
exit command. A pre-canonical diagnostic run proves zero inference work
(§4). Canonical arms: AMD-A/Vulkan, NV-A/Vulkan, NV-A/CUDA, multiple
independent process runs each, distributions reported as medians.

## Required new raw-evidence layout

All new physical evidence lands ONLY under (never overwriting `results/`):

```
docs/investigations/vulkan-v0-a/correctness/correction-<RUNID>/run.json
docs/investigations/vulkan-v0-a/results-correction/materialization/<arm>-<n>/...
docs/investigations/vulkan-v0-a/results-correction/correctness-summary.json
docs/investigations/vulkan-v0-a/results-correction/materialization-correction.json
```

Every raw `run.json` records: unique run ID; UTC timestamp; exact argv;
relevant environment variables; executable SHA-256; model SHA-256;
intended physical BDF/device label; backend/device selector; stdout
verbatim; stderr verbatim; process exit code; backend/device enumeration
lines; selected-device proof; offload/layer proof; generated token/text
output; digest of canonicalized generated output; NaN/Inf/failure/warning
status. The summary is DERIVED mechanically from these raw records by
`scripts/v0a_correctness_derive.py`; no hand-edited summary counts.

The device-identity proof chain (enumeration banner order + pinned
`--device` + stderr device/offload lines, cross-checked against BDF via
retained inventory) is what shows llvmpipe, the Intel iGPU, the other AMD
card, or another backend cannot silently satisfy a run attributed to a
different device.

## Non-delegation clause

This correction does NOT permit tuning, re-selection, or re-parameterization
after observing outputs. Probe identity, model bytes, prompt, sampling,
token counts, device pins, arms, run counts, harness behavior, and idle
windows are frozen by this document before the first corrected physical run
executes. Deviations discovered mid-campaign invalidate the affected runs
and require a new correction document; they are never absorbed silently.

## Addendum A — logging verbosity flag (pre-canonical, before any successful run)

Producer bring-up exposed that llama-cli at the pinned commit sets
`params.verbosity = LOG_LEVEL_ERROR` (1) in `tools/cli/cli.cpp`, and
`common_params_parse_ex` applies it as the log threshold BEFORE flag
parsing. At verbosity 1 the tool suppresses all `LOG_INF` output on
stderr — including the `ggml_vulkan: N = <device>` enumeration and the
`offloaded X/Y layers` summary that this correction REQUIRES as
device-identity proof. (`llama-bench` uses a different default, which is
why the retained `results/bench-*.err` carries its banners.)

Every corrected run therefore adds `-lv 3` (logging verbosity 3 =
info) to the llama-cli invocation. This flag changes ONLY which log
lines the tool prints; it does not touch model bytes, prompt, sampling,
seed, token count, device selection, backend, binaries, or libraries.
The unchanged identity section above still holds byte-for-byte.

Three producer defects were repaired before any successful physical run
under this authority (commits `10eed90`, `b6584b6`, `179d3ed`); the
verbosity repair is Addendum A itself. The one diagnostic AMD-A run
retained before this addendum (`correction-cor-amdavk-01`) produced a
generation but NO stderr device-proof lines; it is recorded as a
diagnostic, is NOT canonical, and is superseded by the canonical
campaign below.

## Scope guards

No new heterogeneous numerical threshold is authorized. No throughput
re-run is performed (the original NVIDIA campaign remains the accepted
V0-A throughput evidence). Nodes 01/03/04 are untouched; all corrected runs
execute on `inferswarm02` only. Accepted #117/#133/#137 evidence and
authorization are untouched.
