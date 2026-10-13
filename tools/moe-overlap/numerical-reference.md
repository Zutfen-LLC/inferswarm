# Backend operand reference handoff (PR #307)

Status on 2026-10-13: **partial offline correction; full reference blocked**.
The branch was based on live PR head
`9ace4700e8c3a315f1cdf4b56c797905396b337a`. No inference host was accessed,
no GPU or model download was used, and no hardware validation was performed.

## What is implemented

The existing independent loader-fixture dot now rounds the activation
reciprocal multiplication to F32 before `roundf`, matching the pin's scalar
CPU quantizer. Previously Python multiplied in F64, which changes codes near
half ties. It explicitly supports only `cpu-scalar-q8_0` and rejects AVX,
CUDA and unknown modes. Its weights have scale 1 and its initial activations
are quantization-exact; it is not a reference for arbitrary real GGUF weights.
The ordinary loader fixture has a saturated router, so its numerical check
does not prove that all ten nonzero expert contributions are present. A small
development fixture now covers that sensitivity separately.

New reports name the existing native-CPU comparison `legacy-cpu-unsplit/1`
and repeat its unchanged metrics under `legacy_cpu_unsplit_diagnostic`.
The original `serial_vs_ref_*` fields and their effect on `verdict.pass`
remain intact. Historical reports are untouched. The proposed independent
contract has a separate identifier, `moe-operand-reference/2-proposed`, and
reports `NOT_IMPLEMENTED`; a legacy PASS is not a PASS under that contract.
Serial/overlap bitwise equality, replay, routing, ownership, shared branch,
quantization, status/error checks and their execution paths are unchanged.

## Source facts and unresolved scope

At native pin `b29c606e28a01b1bc8c1351026a0fa6e616bf6c4`:

| Path | Code arithmetic | Stored activation scale | Local source |
|---|---|---|---|
| CPU scalar Q8_0 | F32 `d=amax/127`, `id=1/d`, `x*id`, ties away | fp16 | `ggml/src/ggml-quants.c`, `quantize_row_q8_0_ref` |
| CPU AVX Q8_0 | F32 `id=127/amax`, `x*id`, ties to even | fp16 | `ggml/src/ggml-cpu/arch/x86/quants.c`, `quantize_row_q8_0` |
| CUDA MMVQ Q8_1 | `d=amax/127`, `roundf(x/d)` | fp16 | `ggml/src/ggml-cuda/quantize.cu`, `quantize_q8_1` |
| CUDA MMQ Q8_1 D4 for Q8_0 weights | `d_inv=127/amax`, `roundf(x*d_inv)`, `d=1/d_inv` | fp32 | `ggml/src/ggml-cuda/quantize.cu`, `quantize_mmq_q8_1`; layout in `mmq.cuh` |

This table describes source paths, not a verified universal shape dispatcher.
Actual CPU compiler flags and CUDA kernel selection, architecture, fusion,
mapping and reciprocal behavior must be established for the named executable.
T=1 and T=128 alone do not identify every supported path. Future references
must record and check the actual mode per projection and reject unrecognized
modes. The shared branch needs its own CPU reference. A CPU-owned subset and
a CUDA-owned subset contain different experts and cannot serve as each
other's expected output.

The maintainer reports that an external source-faithful reconstruction of one
frozen T=128 failure matched CPU planes to 1.7e-8, CUDA partial to 3.3e-8,
and their delta to 4.3e-8 unexplained. These are **reported fixture-specific
observations, not locally inspected artifacts or error bounds**. The original
CPU-versus-CUDA max_abs 0.0004935832694 / max_ratio 1.765354018 remains a
FAIL under the legacy criterion. [Comment 6134734665](https://github.com/Zutfen-LLC/inferswarm/pull/307#issuecomment-6134734665)
withdraws the inverse-minimum-router-weight derivation. No fitted 32x
allowance or additional `2^-6 * weighted_L1` term is adopted here.

## Smallest portable handoff

No relevant reconstruction/capture was found in the accessible local task
directories or caches. `/home/zutfen/.hermes/cache/evidence/pr-307/` is absent
on this computer. The reported controller directory
`/home/zutfen/.hermes/cache/evidence/pr-307/t128r2-20261013/` and inferswarm01
directory `/home/hermes/moe-pr307/diag-t128/t128r2/` were not inspected.

Provide locally, without a full model or new host run:

1. The vetted reconstruction script and only its imported local helpers;
   its exact invocation, dependencies, pin/build identity, and hashes.
2. The smallest existing self-contained reproduction slice: pre-quantization
   activations and Q8_0 weight bytes **including block scales** for one named
   expert/token/slot through up, gate, SwiGLU and down; routing ID and exact
   F32 weight; packed activation codes/scales and matching CPU/CUDA stage
   outputs. Include dimensions/strides and compact-to-original mapping.
3. If the script requires complete-subset reduction inputs, include precisely
   those existing selected-expert tensors/activations/planes and the shared
   branch inputs/output, or document that dependency before copying. One
   expert proves a stage reconstruction, not the ten-expert block combine.
   Include the original failing JSON, frozen-input hash and provenance/seed.

Exact remote filenames cannot be named until the script's dependency list is
available. Do not substitute backend-generated outputs for independently
computed expected values. Captures check the reconstruction's operand/mapping
fidelity; full references must compute their own projection/nonlinear inputs
from the original weights and activations. Adapting the vetted script is the
next step; duplicating an engine is outside this correction.

## Criteria and reserved inputs

No full-block/backend tolerance is responsibly declared while that reference
is missing. Before any subsequent held-out hardware run, freeze a new criterion
with a narrow rationale for accumulation and nonlinear implementation error
after operands match. A block/backend empirical criterion is permissible if
labeled as such, but neither observed fixture agreement nor weighted-plane
L1 alone proves a uniform bound. Do not tune constants until the known case
passes, or relabel it held-out.

The existing crafted CPU loader-fixture criterion remains relative error
`<5e-5` (denominator floor `1e-9`) and absolute error `<5e-3` for the split
case. These retained empirical thresholds accommodate F32 nonlinear ops vs
the F64 reference for that fixture only; they are not a CUDA or arbitrary
real-weight accumulation bound. The 32-element operand tests use exact
hand-computed codes/scales. The tiny block's analytic F64 check allows only
12-decimal-place arithmetic-order agreement before testing sensitivity.

Reserve these explicit `--seed` values for later validation with the existing
real GGUF weights, layer 2, split 256, one measured repetition per seed:

| Tokens | Reserved seeds |
|---|---|
| T=1 | `0x30700101`, `0x30700102`, `0x30700103` |
| T=128 | `0x30712801`, `0x30712802`, `0x30712803` |

These seeds have not been generated or used by this change's tests. Development
inputs are the existing crafted loader fixture, new small deterministic
fixtures, and the harness's existing default seed `0x4953573030303033`.
The externally inspected frozen failure is consumed development evidence;
its seed/input hash is currently unavailable here. Verify the reserved seeds
against external provenance and compare input hashes before calling them
held-out. If previously consumed, record that and reserve fresh values before
the new criterion is validated. Record the seed explicitly in the run
manifest/command: the current GGUF report does not echo `--seed`.

## Smallest next physical step (after the blocker is resolved)

First adapt and verify the portable reconstruction offline and freeze its
mode dispatch and criterion. Then, under separately established hardware
authority, perform one T=1 and one T=128 reference-validation smoke run at
the new reviewed SHA using the first reserved seed for each shape. Use the
existing harness invocation (`--gguf`, `--layer 2`, `--split 256`,
`--secondary cuda`, `--seed`, `--warmup 0`, `--reps 1`, `--self-check-negative`)
and the vetted capture/reconstruction's documented invocation. A complete
copy-paste reference-validation command is blocked on that script; the
repository's present dumps omit internal codes/scales and failed runs do not
emit arm outputs. Existing dumps alone cannot complete the new validation.

Check each backend against independently computed operands for the same
expert/token/slot, every selected expert and the shared branch, plus strict
serial/overlap bitwise equality and replay. Retain both contract statuses and
the unchanged legacy diagnostic, including FAIL. STOP and preserve any failed
case. Only after that smoke succeeds should the remaining reserved seeds be
used once each. Neither offline CI nor a successful known-fixture replay
qualifies T=128. The clean post-fix CUDA racecheck remains outstanding.

CUDA builds still need the externally documented nvcc-wrapper/libcuda-link
amendments. This change does not repair `build.py`, dispatch Final CPU
Validation, run the campaign, grant execution authority, merge the PR or close
an issue. No living project-status claim changes: this is local prototype
preparation with an explicit blocker, not new acceptance or capability evidence.
