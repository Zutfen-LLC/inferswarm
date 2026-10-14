# Independent backend operand reference (PR #307)

`moe-operand-reference/2` is implemented as an **offline, block-scoped
empirical check**, with physical validation still pending. It independently
computes expected outputs from original Q8_0 weight bytes, captured F32 inputs
and the original token/slot routing. It never calls a native backend to
produce expected values. It covers all ten selected experts, both ownership
subsets, the CPU shared branch, and both final scheduling-arm outputs.

## Scope and numerical modes

`operand_reference.py` adapts the portable t128r2 quantizers and the existing
CPU loader-fixture FFN reference. It fixes signed Q8 decoding, block layouts,
weight-scale indexing and duplicate scale application in the supplied script.
Projection dots use exact per-block integer sums and F64 accumulation, with
explicit F32 graph intermediates before SwiGLU and down-input quantization.
The packs it computes are **predictions, not captured device bytes**.

At native pin `b29c606e28a01b1bc8c1351026a0fa6e616bf6c4`:

| Mode | Code arithmetic | Stored activation scale |
|---|---|---|
| `cpu-scalar-q8_0` | F32 `d=amax/127`, `id=1/d`, `x*id`, ties away | fp16 |
| `cpu-avx-q8_0` | F32 `id=127/amax`, `x*id`, ties to even | fp16 |
| `cuda-mmvq-q8_1` | F32 `d=amax/127`, `roundf(x/d)` | fp16 |
| `cuda-mmq-d4` | F32 `d_inv=127/amax`, `roundf(x*d_inv)`, `d=1/d_inv` | fp32 |

Source: `ggml-quants.c:quantize_row_q8_0_ref`,
`ggml-cpu/arch/x86/quants.c:quantize_row_q8_0`, and
`ggml-cuda/quantize.cu:quantize_q8_1/quantize_mmq_q8_1` (`mmq.cuh` selects D4
for Q8_0). Unknown reference modes are rejected.

The harness exporter supports only T=1 and T=128, the existing 2560/640 block,
x86 CPU, and either a CPU secondary or the named CUDA0 RTX 3060 subject.
It records the linked CPU closure's compiled AVX features; the CPU TUs must
have coherent flags, as in the existing build recipe. CUDA source dispatch
at this pin is MMVQ for T=1 and MMQ D4 for T=128 on this subject. Unsupported
shapes/subjects fail closed. This is not a universal CUDA shape dispatcher.
GPU compiler arithmetic, nonlinear implementation differences and held-out
behavior still require physical validation. No native quantizer was changed.

## Retained T=1 diagnosis (offline, 2026-10-13; no hardware access)

The latest retained T=1 hardware case passed native scheduling, replay and the
legacy numerical gates but failed `moe-operand-reference/2`. Offline analysis
of that retained case (controller evidence package
`offline-5db3de7-20261013`, reproduced once against the original verified
GGUF) established:

- **Scalar CPU Q8 projections**: the examined build performs source-order
  **F32 scaled-block accumulation with separate multiply/add** per block —
  disassembly confirms F32 combined scale, integer-to-F32 conversion, separate
  `mulss`/`addss`, no fused multiply-add. The reference's exact integer dots
  with F64 scale/sum (and an earlier F32-accumulator hypothesis) do not match
  this arithmetic.
- **Shared-gate dot**: scalar **F32 products accumulated in F64 in source
  order, then cast to F32**. (An F32 accumulator was an incorrect earlier
  hypothesis; it is withdrawn here.)
- **Shared sigmoid** uses `1.f/(1.f+expf(-x))` with **expf/F32 boundaries**;
  the examined **SwiGLU** (640 elements) uses the **SSE2 vector exponential
  polynomial** (no FMA, divide then multiply), not scalar `expf`.
- **The retained shared-branch discrepancy is explained by one FP16 stored
  scale boundary, not integer-code changes**: zero of 640 down-input integer
  codes change; exactly one of 20 stored FP16 scales flips (the two candidate
  F32 scales sit one F32 ULP either side of the FP16 rounding midpoint).
  Propagating only that scale change predicts the observed worst-element
  error to 0.06% of its magnitude; the full source/object-justified CPU
  reconstruction reproduces the captured shared output **bit-for-bit**.
- **CUDA remains conditional**: source-guided MMVQ models (warp partial dots,
  sequential warp addition, XOR reduction, `roundf(x/d)` Q8_1 codes, fp16
  stored scales, float `expf`/divide) predict a similar single stored-scale
  flip on one expert, but the compiled contraction, division lowering and
  device `expf` are **not established from the binary**; no bitwise CUDA
  reconstruction exists. The missing adjudicating evidence (native
  expert-288/token-0/slot-6 down-input block-6 bytes and per-expert planes)
  was never captured and no new capture is authorized.

These findings motivate separating scheduling equivalence
([`check_scheduling.py`](check_scheduling.py), contract
`moe-scheduling-equivalence/1`) from backend numerical qualification. They do
**not** widen any threshold: the retained `/2` FAIL (CUDA secondary
6.40e-6, shared 4.51e-5 over-tolerance) remains FAIL. An isolated
projection-accumulation correction exists as a diagnostic patch outside the
repository and is deliberately **not applied**: adopting it alone would not
make the oracle a complete CPU/CUDA instruction emulation (the mathematical
F64 reference stays a mathematical reference), and no fitted amplification,
forced equality, output substitution, expert skipping or quantization change
is authorized.

## Contract and retained diagnostic

The native **`legacy-cpu-unsplit/1`** formula, `serial_vs_ref_*` fields,
`legacy_cpu_unsplit_diagnostic`, verdict and historical reports are unchanged.
A legacy FAIL stays FAIL. [Comment 6134734665](https://github.com/Zutfen-LLC/inferswarm/pull/307#issuecomment-6134734665)
withdraws the inverse-minimum-weight derivation; the fitted 32x / extra
`2^-6 * weighted_L1` allowance in the transferred report is not adopted.

`check_reference.py` produces a separate `/2` report, preserving the legacy
verdict/diagnostic and reporting `PROPOSED_EMPIRICAL_PASS`, `FAIL`, or
`INVALID_OR_INCOMPLETE`. **`hardware_qualified` is always false**: a numerical
check is not qualification or execution authority. The harness reports
`EXTERNAL_CHECK_PENDING` when exporting; it cannot declare an independent
PASS itself. Without an export, the new contract is `NOT_REQUESTED`.

For each CPU/secondary/shared partial and each final arm, the fixed criterion is

```
abs(observed - independent_expected) <= 2^-23 + 2^-19 * independent_plane_mass
```

Mass is the elementwise sum of absolute independently computed, router-weighted
planes belonging to that partial; shared mass is its absolute contribution.
Final mass includes both expert subsets and shared. These constants were
chosen before evaluating the transferred fixture or any held-out run: one
F32 epsilon absolute plus sixteen F32 epsilons of plane mass. This is narrow
**empirical headroom for accumulation/nonlinear implementation differences
after operand reconstruction**, not a bound on quantization error propagated
through the FFN. Cancellation and quantizer boundaries can invalidate a case;
retain FAIL rather than fitting a larger constant. No universal theorem or
error ceiling is claimed.

Every native routing/scheduling/replay/status check must still succeed, as
must `--self-check-negative`. The checker verifies exported arm bytes are
bit-identical and compares the CPU subset, secondary subset, shared branch
and final outputs separately. Missing data/weights, wrong shapes, unknown
modes, nonfinite operands or native error/status failures cannot fall back to
the legacy CPU output. Expected values never use captured partials/planes.

## Portable bundle inspected locally

Archive: `inferswarm-pr307-t128r2-reference.zip`.
Computed SHA-256:
`b886a71e7ad36f324515294ee687613052733bbcd4e3817749d0f8bf0d194dd2`.
No independently supplied expected archive hash exists; this is local
integrity, not external authentication. Safe extraction found 50 regular
files; all 49 entries in `SHA256SUMS` match (the manifest excludes itself).
No bundled shell script or native executable was run.

The bundle is complete for seven CUDA-owned experts of **frame 61 only**.
Its `recon/recon1.py` is not a functioning reproduction of the reported full
comparison: an impossible reshape, unsigned-code decoding, malformed scale
axes, double-applied scales and incorrect gate-scale selection occur before
its missing SwiGLU/down/comparison implementation. The declared
`recon/attribution.npy` is absent. The source-corrected adapter, rather than
that broken script, computes the following **CALCULATED offline comparisons
against retained observed arrays**:

- CPU weighted planes: max absolute difference `1.4901161193847656e-8`.
- CPU same-seven-expert partial: `1.5308614820241928e-8`.
- CUDA MMQ same-seven-expert partial: `3.133027348667383e-8`.
- Predicted initial CPU/CUDA integer codes: zero differences on this input.

This verifies only the available development slice, not a whole-block PASS,
native pack identity, a universal mechanism bound or T=128 qualification.
The observed original max_abs `0.0004935832694`, ratio `1.765354018` remains
FAIL under the legacy contract. Captured CPU and CUDA subsets are different
experts; comparisons above reconstruct the **same** seven experts.

Smallest missing full-frame-61 inputs, from existing GGUF bytes (no GPU run):

- up/gate/down Q8_0 extracts for experts **44, 106, 253**;
- shared up/gate/down Q8_0 tensors;
- F32 `ffn_gate_inp_shexp.weight` (2560 values).

Those 13 extracts total **20,899,840 bytes**. The complete working
reconstruction/cell history used for the transferred report is also requested
for provenance comparison. For all 128 captured tokens, 393 unique experts
are selected; only seven have extracts. A full known-fixture replay needs
all selected weights and shared, or the original existing shard. The checker
can read that shard selectively via the repository's existing bounded GGUF
index. No full-model download is needed. Do not treat captured CPU/shared
outputs as a substitute for missing independent reference weights.

Use the controller/Hermes evidence copy first; inferswarm01 only for missing
existing files. Reconstructed packs are optional, labeled as predictions;
native packs were never captured and a new capture is not a packaging
prerequisite. Preserve relative paths, a dependency list and SHA-256 manifest.

## Later physical validation (not run here)

The exporter adds only host writes outside arm timings, with no graph, kernel,
ownership or scheduling API changes. Export runs explicitly disclaim timing
as performance evidence. Use a new directory per process; never reuse stale
cases. Keep the existing CUDA nvcc-wrapper/libcuda-link amendments; this
change does not migrate or repair the build system.

After separate hardware authorization, for one numerical smoke case:

```bash
# B, GGUF and CPU/thread settings come from the existing authorized recipe.
# CASE must not already exist. Use the actual reviewed SHA and pinned weights.
"$B" --gguf "$GGUF" --layer 2 --tokens 128 --split 256 --secondary cuda \
  --threads 14 --warmup 0 --reps 1 --seed 0x30712801 \
  --self-check-negative --dump-reference-case "$CASE" --json native.json
python3 tools/moe-overlap/check_reference.py "$CASE" --gguf "$GGUF" \
  --json "$CASE/reference.json"
```

The native command can exit 3 for its retained legacy numerical FAIL. Inspect
its reason and the independent report: do not blanket-ignore native failures.
The checker rejects incomplete/status/schedule/replay/control failures even
when legacy numerics also fail. Keep both reports and all failed records.
Repeat once for T=1 with `--tokens 1 --seed 0x30700101` and a fresh CASE.
For every such case also run `check_scheduling.py CASE` and retain its
scheduling verdict beside the numerical reports (see
[`scheduling-contract.md`](scheduling-contract.md)); the operator recipe for
the next T=128 case lives in
[`hardware-recipe.md`](hardware-recipe.md).
A passing smoke does not itself qualify hardware. A clean post-fix CUDA
racecheck also remains outstanding; no new GPU/native capture is required by
this coding task.

Reserved held-out seed set (not generated or used by these tests):

| Tokens | Reserved seeds |
|---|---|
| T=1 | `0x30700101`, `0x30700102`, `0x30700103` |
| T=128 | `0x30712801`, `0x30712802`, `0x30712803` |

Development inputs are crafted offline fixtures and the transferred consumed
failure (`cur.f32` SHA `fc72b57256e32b5c5e1403228da12ace1ddd7e1969f0fa156bb11256b8683c1d`,
default seed lineage `0x4953573030303033`). Check external provenance/input
hashes before claiming the reserved seeds are held-out. Record the seed in
run provenance because GGUF native reports do not echo it. STOP on a failed
new-contract case; do not widen the criterion or retry until PASS.

No inference host was accessed, no GPU or model download was used, and no
hardware run, native-kernel change, Final CPU Validation dispatch, merger or
issue closure occurred. Documentation impact is confined to this prototype:
there is no new accepted capability, gate result or execution authority to
record in living project status.
