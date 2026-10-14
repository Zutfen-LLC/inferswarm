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
- **overlapped**: the activation H2D sets and the secondary-device expert
  graph are enqueued on the secondary backend's stream
  (`ggml_backend_tensor_set_async` → `ggml_backend_graph_compute_async`);
  the CPU expert subset and the shared branch then run on the CPU backend's
  host threadpool concurrently with the secondary stream; only after the CPU
  work completes is the D2H read-back issued
  (`ggml_backend_tensor_get_async` into a pageable host buffer, then
  `ggml_backend_synchronize`). The read-back is deliberately deferred: CUDA
  documents that an async copy with a pageable destination may block the host
  until it completes, so enqueueing it before the CPU branch could silently
  serialize the arm and masquerade as a negative overlap result. Dependencies
  stay ordered because the copies, kernels and read-back share one device
  stream; work is only called "overlapped" because this ordering genuinely
  permits concurrent execution.

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
  padded to its per-repetition maximum with a **distinct** local expert id
  unused by that token (never a repeated id: MUL_MAT_ID ids are top-k output,
  unique per token, and the CUDA id-mapping kernel `mm_ids_helper` relies on
  that — duplicate padding ids raced there and caused the T=128
  nondeterminism diagnosed on 2026-10-12) and weight exactly `+0.0f`. An
  unrepresentable padded width (fewer unselected local ids than padding
  slots) or a duplicate genuine id fails closed with an explicit reason. The padding work is identical in both arms, is real executed
  work (it is measured), and is reported per repetition (`k_cpu`/`k_sec` vs
  `k_cpu_real`/`k_sec_real`) so the overhead is never hidden. At `--split 256`
  the offline prefill run measured 612+668 real selections padded to 8×128 and
  10×128 planes. Zero-waste prefill would require an expert-major batching
  scheduler; that is out of scope for this prototype and is listed under
  limitations.

## Stage timing attribution (`cpu_experts_ms` / `shared_ms`)

`cpu_ms` remains the aggregate CPU-stage elapsed time with its original outer
boundaries and meaning. Each repetition's `serial_stages` and `overlap_stages`
additionally report two observation-only substages of that same region:
`cpu_experts_ms` (the CPU-owned expert branch's existing input setup/copy,
compute, synchronization and output readback) and `shared_ms` (the shared
FFN/gate branch's existing input setup/copy, compute, synchronization and
output readback). These are wall-clock regions, **not pure kernel times** —
each includes its branch's copies and synchronization. Their purpose is to
identify whether CPU experts or shared work dominates the CPU stage (padding
performs the full expert computation before its zero routing weight applies,
so it lands in `cpu_experts_ms`). Their sum need not equal `cpu_ms` exactly
(timer overhead, work between the regions); an empty CPU expert subset reports
`cpu_experts_ms = 0` while shared work is still measured. No synchronization,
copies, compute or ordering were added to produce these fields. Overlap-arm
timing identifies the critical-path stages of this schedule only; it does not
establish total GPU utilization.

## Numerical criteria (fixed before any comparison)

The existing comparison is **`legacy-cpu-unsplit/1`**. Its formula and verdict
behavior are retained to preserve historical FAIL results. It uses a native
CPU graph as its expected output, so it is not an independent operand
reference. The separate **`moe-operand-reference/2`** is implemented as an
independent offline check with a proposed block-scoped empirical criterion.
Its physical validation and whole failing-fixture replay remain pending. See
[`numerical-reference.md`](numerical-reference.md) for source distinctions,
the precise handoff, reserved seeds, and remaining physical validation.

Use `--dump-reference-case NEW_DIR` for an untimed numerical export and
`python3 tools/moe-overlap/check_reference.py NEW_DIR --gguf ORIGINAL_SHARD`
for independently computed CPU/secondary/shared and final-arm checks. This
does not change the native legacy verdict. The new report carries its own
status and always reports `hardware_qualified: false`; it requires the native
schedule, routing, replay, error/status and shared-omission control checks.
Supported modes are explicit and unsupported subjects/shapes are rejected.

A **separate, narrower verdict** — `moe-scheduling-equivalence/1`
([`check_scheduling.py`](check_scheduling.py),
[`scheduling-contract.md`](scheduling-contract.md)) — checks only that the two
scheduling arms executed identical work with bitwise-identical outputs,
reusing the same exports. It can PASS while both numerical diagnostics stay
FAIL; it never claims backend correctness or hardware qualification, and both
arms can share a numerical defect. The retained T=1 diagnosis (one FP16
stored-scale boundary in the CPU shared branch; CUDA explanation conditional)
is documented in [`numerical-reference.md`](numerical-reference.md).

- CPU and CUDA activation operands differ at this pin. CPU Q8_0 and CUDA
  MMVQ store fp16 activation scales; CUDA MMQ's Q8_0 D4 path stores fp32
  scales. Arithmetic and integer rounding also depend on the selected kernel
  path. The shared branch remains on CPU.
- **overlapped vs serial**: must be bit-identical (same kernels, same order,
  deterministic per fixed shapes/thread counts). Any difference fails the run.
- **each arm vs the unsplit reference** (llama.cpp op order on the primary
  backend): per element `|diff| <= tol` with
  `tol = 8 · 2⁻²³ · Σᵢ|planeᵢ| + (secondary non-CPU ? 2⁻⁷ · Σᵢ|planeᵢ| : 0)`,
  where `Σᵢ|planeᵢ|` is the per-element L1 mass of the reference's ten
  weighted expert planes. These are the original empirical allowances;
  neither establishes a bound on quantization differences propagated through
  projections, cancellation, SwiGLU and another quantized projection. They
  are not a proposed acceptance criterion for the new independent reference.
  No constants are widened after a failure; the reports include
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
- `operand_reference.py` / `check_reference.py` — independent Q8 operand
  reconstruction and a block-specific offline check, reusing the repository's
  bounded GGUF index. No native backend generates the expected values.
- `check_scheduling.py` — the separately versioned scheduling-equivalence
  verdict (`moe-scheduling-equivalence/1`) over the same exports; read-only,
  no new capture (see [`scheduling-contract.md`](scheduling-contract.md)).
- `build.py` — fetches the sha256-pinned source tarball once into the user
  cache, verifies the extracted tree against selected complete-file digests
  from the accepted #299 runtime contract (an `MOE_OVERLAP_SOURCE` override
  must prove the same identity or the build refuses), and compiles the
  minimal ggml CPU closure plus the harness with a direct GCC/Clang recipe
  (no CMake, no installs). Objects carry stamps (source hash + flags +
  resolved compiler/version, including nvcc's selected host compiler) and are
  rebuilt on any change — a stale cached build cannot test
  old code. `--cuda` compiles the complete CUDA closure at this pin (every
  `ggml/src/ggml-cuda/*.cu` plus the `template-instances/*.cu` TUs the pin's
  own CMake GLOBs) with `GGML_USE_CUDA` defined at compile time for every TU
  (backend registration in `ggml-backend-reg.cpp` is gated on that define, so
  it cannot be a link-time-only flag). The recipe includes `--extended-lambda`
  and the pin's default `GGML_CUDA_FA_QUANTS` string plus all 49 explicit K/V
  combination definitions; optimization/math flags remain as previously
  tested. It needs no external nvcc wrapper or manual relink. Driver lookup
  preserves `-lcuda` for usable development libraries, otherwise links a
  validated `libcuda.so.1` path from compiler search or the loader cache.
  `MOE_OVERLAP_CUDA_DRIVER` can select an explicit real driver library;
  missing/invalid libraries and toolkit `stubs` paths are refused before
  compilation. The link probe checks the VMM dependency without running it;
  it does not establish device readiness. The repaired recipe still needs a
  separate clean CUDA build and no-model `--list-devices` check on hardware
  (see [`hardware-recipe.md`](hardware-recipe.md)). The historical full CUDA
  compile took approximately 47 minutes at two jobs; allow a separate build
  window, not a 30-minute combined build/run budget. `MOE_OVERLAP_OPT`
  overrides the host optimization level.
- `offline-validation/` — retained offline run reports (SYNTHETIC weights and
  inputs; reduced smoke + full-authentic-shape decode/prefill runs).

Additional offline controls exercised by
`tests/test_moe_overlap_prototype.py`:

- **Backend operand reference**: signed weight bytes and single scale
  application, four explicit quantizer modes (ties, zero blocks and fp16/fp32
  scales), all ten experts and shared across a small 128-token mapping fixture,
  wrong-routing-weight, missing-expert, corrupted-output and missing-shared
  controls. A complete CPU GGUF fixture tests exporter-to-checker integration
  and refusal of missing files/unknown modes. The transferred seven-expert
  frame-61 slice is development evidence only; its missing CPU/shared weights
  prevent a whole-block replay here.
- **Scalar CPU fixture operands**: a 32-element half-tie control checks F32
  multiplication before integer rounding and fp16 scale storage. Unknown,
  AVX and CUDA fixture-reference modes are rejected. A small 12-expert/top-10
  development fixture with all ten weights nonzero exercises missing-expert,
  wrong-Q8-weight and corrupted/non-finite-output controls using the existing
  fixture criterion. These tests do not add a real-weight/backend reference
  to the harness or qualify CUDA.
- **GGUF loader regression**: a small authentic-geometry fixture GGUF
  (n_expert = 12, tensors with distinct crafted contents, alphabetical file
  order deliberately different from the loader's internal order) is replayed
  with crafted activations (`--inputs-file`, quantization-exact by
  construction) and the dumped arm outputs are checked against an independent
  F64 block reference computed directly from the fixture bytes (including the
  modeled Q8_0 activation quantization of the down-projection inputs).
  Demonstrated to fail against the pre-fix sequential-append loader.
- **compute-status failure injection** (`--self-check-status-negative`): a
  failed graph compute terminates the run non-passing with the stage recorded;
  outputs are never compared on stale results, and non-finite values can never
  satisfy a tolerance comparison.
- **build-cache invalidation**: an object whose stamp no longer matches its
  source/flags/compiler is rebuilt; unchanged objects are reused.
- **CUDA recipe regression**: offline recording toolchains verify compile
  definitions, backend registration, library order, development/versioned
  driver selection, invalid/stub/missing driver refusal and cache invalidation.
  Fake libraries/toolchains establish neither CUDA compilation nor discovery.
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
- `tests/test_moe_overlap_prototype.py`: 12/12 pass, including the real-file
  GGUF fixture loader regression (verified to fail against the pre-fix
  loader) and the fresh-build/stale-cache control.

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
- The harness is a prototype: fail-closed errors and status checks are
  preferred, but it has not been through production hardening, fuzzing, or
  sanitizer campaigns. The CUDA closure is enumerated from the pin's own
  CMake GLOBs and defines. The repaired build recipe has not been compiled
  here (no nvcc on Valinor); a separate clean hardware build remains required.
