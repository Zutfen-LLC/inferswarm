# MoE overlap prototype (resident block scheduling experiment)

Status: **prototype / offline-validated coding deliverable**. Nothing here is a
qualification result, a performance claim, or execution authority for any
hardware campaign. Hardware execution, if approved, follows
[`hardware-recipe.md`](hardware-recipe.md) through the separate Hermes handoff.

## What this tests

One representative routed MoE FFN block of the accepted Q8 model
(`unsloth/Qwen3.8-Flash-Next-GGUF` @ `38bb39ee`, `qwen4exp`, 48 layers, 512
experts/layer, 10 active, Q8_0 banks of 891,289,600 bytes each, plus one Q8_0
shared expert and F32 routers — the authenticated #299 census geometry):

- router: `mul_mat(ffn_gate_inp F32 [2560,512])` → softmax → `argsort_top_k`
  (10) → `get_rows` → llama.cpp `norm_w` pipeline (sum/clamp/div);
- routed experts: `mul_mat_id` up+gate (Q8_0 `[2560,640,512]`), `swiglu_split`,
  `mul_mat_id` down (Q8_0 `[640,2560,512]`), per-expert weighting after the
  down projection, plane-order sum — exactly
  `llm_graph_context::build_moe_ffn` for this configuration;
- shared expert: `build_ffn(LLM_FFN_SILU, LLM_FFN_PAR)` + sigmoided
  `ffn_gate_inp_shexp` gate, then `add(moe_out, shared)`.

The experiment runs the **same** block twice per repetition on the **same**
resident weights, inputs and routing decisions (computed once per repetition by
the same router graph and shared by both arms), with the same device ownership,
kernels and precision:

- **serial**: every stage fully synchronized before the next (blocking input
  copies → compute → synchronize → blocking reads, separately for the CPU
  subset, the activation upload, the GPU subset and the read-back).
- **overlapped**: the activation H2D sets, the secondary-device expert graph
  and the D2H read-back are enqueued in order on the secondary backend's
  stream (`ggml_backend_tensor_set_async` → `ggml_backend_graph_compute_async`
  → `ggml_backend_tensor_get_async`); the CPU expert subset and the shared
  branch run on the CPU backend's host threadpool concurrently; a single
  `ggml_backend_synchronize` joins. Dependencies stay ordered because copies,
  kernels and read-back share one device stream; work is only called
  "overlapped" because this ordering genuinely permits concurrent execution.

Ownership is fixed for both arms: the CPU backend owns experts `[0, split)`
(plus router and shared expert), the secondary backend owns a resident device
copy of experts `[split, 512)` uploaded once at load. `--secondary cuda`
selects the GPU (fail-closed if absent); `--secondary cpu` runs the full
two-backend code path on a second CPU backend for offline validation, where
the timing comparison is explicitly meaningless (the harness prints that
disclaimer in its verdict).

There is **no expert skipping or approximation anywhere in the harness**: every
router-selected expert and the shared expert execute in both arms, and each
repetition asserts `routed_total == 10 * n_tokens` fail-closed.

## What is reused (and what is new)

Reused, unmodified, from llama.cpp pin `b29c606e28a01b1bc8c1351026a0fa6e616bf6c4`
(public upstream tree; source identity and build recipe below):

- `gguf` selective header parsing + targeted `pread` of exactly the eight block
  tensors (~2.55 GiB from one shard; no full-shard load);
- the ggml CPU and CUDA backends and their existing kernels: `MUL_MAT`,
  `MUL_MAT_ID` (Q8_0; CPU and CUDA, including the CUDA fused up+gate+GLU MoE
  path), `SOFT_MAX`, `ARGSORT_TOP_K`, `GET_ROWS`, `SWIGLU_SPLIT`, `SIGMOID`,
  `SUM_ROWS`, `CLAMP`, `DIV`, `CPY`;
- the async backend APIs (`set_async` / `graph_compute_async` / `get_async` /
  `synchronize`) exactly as the pin's scheduler uses them for stream-ordered
  copies around graph compute.

New (this directory only): a ~900-line single-file harness that builds the
block's graphs out of those ops, two scheduling arms, host-side split/remap of
routing, validation and JSON reporting; a build script; these docs; offline
tests. No loader redesign, no RPC protocol, no scheduler framework, no kernel
port, no engine.

### Strata verdict (candidate code, inspected not adopted)

`Niko1221/Strata` @ `7695859aa13afb248bdb4d36f9b2e95707db079d` (MIT) and its
stripped fork `robertkarl/UnbiasedStrata` @ `46c46ecfc11d2315512f21f7549b0a7792ccd2ae`
are complete custom engines for this same model family with their own quant
packs and custom MoE/expert-cache/DMA kernels (pinned-host batched
`cudaMemcpyAsync` uploads overlapping compute, VRAM expert cache with CPU/SSD
tiers). They were inspected as mechanism references only: adopting any Strata
kernel would be exactly the kernel/format adaptation this prototype is scoped
to avoid, and nothing in this implementation depends on Strata code or its
installer. The pinned-llama.cpp path supplies every mechanism the experiment
needs.

## Decode vs prefill, and padding

- **T=1 (decode)**: the per-device expert subsets are exact (one token).
- **T=128 (prefill)**: `mul_mat_id` requires one uniform expert count `k` per
  device across all tokens, while per-token routing varies. Each subset is
  padded to its per-repetition maximum with a valid local expert id and weight
  exactly `+0.0f`. The padding work is identical in both arms, is real executed
  work (it is measured), and is reported per repetition (`k_cpu`/`k_sec` vs
  `k_cpu_real`/`k_sec_real`) so the overhead is never hidden. At `--split 256`
  the offline prefill run measured 612+668 real selections padded to 8×128 and
  10×128 planes. Zero-waste prefill would require an expert-major batching
  scheduler; that is out of scope for this prototype and is listed under
  limitations.

## Numerical criteria (fixed before any comparison)

- All paths at this pin quantize activations to Q8_0 inside quantized
  `MUL_MAT`/`MUL_MAT_ID`, so CPU and CUDA arms share the same activation
  quantization behavior.
- **overlapped vs serial**: must be bit-identical (same kernels, same order,
  deterministic per fixed shapes/thread counts). Any difference fails the run.
- **each arm vs the unsplit reference** (llama.cpp op order on the primary
  backend): per element `|diff| <= tol` with
  `tol = 8 · 2⁻²³ · Σᵢ|planeᵢ| + (secondary non-CPU ? 2⁻⁷ · Σᵢ|planeᵢ| : 0)`,
  where `Σᵢ|planeᵢ|` is the per-element L1 mass of the reference's ten
  weighted expert planes. The first term bounds F32 reassociation over ≤10
  plane sums plus cross-backend block-accumulation order; the second is
  documented headroom for one activation-quantization step (1/127 ≈ 2⁻⁷) when
  a non-CPU kernel path participates. Criteria are computed from the actual
  operands and never widened after a failure; the reports include
  `max_ratio = max|diff|/tol` (observed ≤ 0.48 offline).
- **single-device identity**: with everything on the primary backend the
  serial arm must match the reference bit-for-bit.
- **comparator sensitivity**: `--self-check-negative` recomputes the block
  with the shared branch omitted and requires the comparator to reject it.
- **isolation/determinism**: distinct per-repetition inputs must produce
  distinct outputs, and replaying repetition 0 must reproduce its reference
  and serial outputs bit-for-bit (guards against stale-buffer reuse across
  repetitions; warm weights never imply reused answers).

## Files

- `moe_overlap_harness.cpp` — the harness (single translation unit).
- `build.py` — fetches the sha256-pinned source tarball once into the user
  cache, compiles the minimal ggml CPU closure plus the harness with a direct
  GCC/Clang recipe (no CMake, no installs), `--cuda` adds the CUDA closure for
  the hardware host. `MOE_OVERLAP_OPT` overrides the optimization level.
- `offline-validation/` — retained offline run reports (SYNTHETIC weights and
  inputs; reduced smoke + full-authentic-shape decode/prefill runs).
- `hardware-recipe.md` — the proposed, separately authorized hardware steps.
- `../../tests/test_moe_overlap_prototype.py` — offline tests.

## Offline validation results (SYNTHETIC; not performance evidence)

Dev container (22-core, CPU-only; secondary = second CPU backend, so overlap
timing is meaningless by construction and is not reported as a result):

- full-authentic decode (`--tokens 1 --split 256 --reps 5`): all gates pass,
  overlapped arm bit-identical to serial in every repetition, single-device
  bit-identity holds, negative control rejected (ratio ≈ 2.8×10⁶ over
  tolerance).
- full-authentic prefill (`--tokens 128 --split 256 --reps 5`): all gates
  pass; routed counts exactly 1280/1280; padding overhead reported per rep.
- `tests/test_moe_overlap_prototype.py`: 7/7 pass.

## Limitations

- Single-node only. This experiment informs — but does not demonstrate — a
  distributed claim: it isolates the mechanism (CPU expert compute concurrent
  with GPU expert compute and activation transfers over a PCIe boundary) that
  the earlier two-host observation could not isolate. A network experiment
  would replace the secondary-backend stream with a link and is out of scope.
- Inputs are synthetic gaussians offline. The hardware recipe uses the real
  Q8 weights (real router → real routing under those inputs) and states
  explicitly how representative block activations are obtained or that the
  synthetic-input caveat applies until a capture exists (no real per-block MoE
  activation capture exists today; see the reference bundle's INPUT_GAPS).
- H2D/D2H use pageable host memory via the pinned backend APIs; pinned
  staging buffers are a later optimization, not part of this prototype.
- Prefill padding overhead (above) is included in both arms and reported.
- Graph plans for the routed subsets are rebuilt per repetition (routing
  changes `k`); build time is measured and reported separately from the
  block-execution comparison and models precompiled-graph selection, not
  block execution.
- The harness is a prototype: fail-closed errors are preferred, but it has
  not been through production hardening, fuzzing, or sanitizer campaigns.
