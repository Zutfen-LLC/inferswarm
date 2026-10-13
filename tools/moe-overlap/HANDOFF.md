# Handoff — resident MoE scheduling overlap prototype

Review-facing summary of this branch's deliverable. Full detail lives in
[`README.md`](README.md) (design/contract), [`hardware-recipe.md`](hardware-recipe.md)
(proposed hardware steps), and the retained offline reports under
[`offline-validation/`](offline-validation/).

## Verdict

**Backend numerical acceptance remains blocked.** The 2026-10-13 partial
offline correction fixes scalar CPU fixture operands and labels the retained
CPU-unsplit diagnostic. The full independent CPU/CUDA operand reference is
`NOT_IMPLEMENTED`, pending the portable vetted reconstruction and its minimal
capture inputs. See [`numerical-reference.md`](numerical-reference.md) for the
handoff and reserved seeds. Historical T=128 FAIL records remain FAIL; this
change establishes no hardware qualification or execution authority.

The earlier feasibility and offline results below describe the original
prototype deliverable, not acceptance under the proposed reference contract.

## Phase 1 feasibility findings (decision: proceed)

1. **Representative block**: the qwen4exp MoE FFN of the accepted Q8 subject
   (`unsloth/Qwen3.8-Flash-Next-GGUF` @ `38bb39ee`, llama.cpp pin
   `b29c606e…`), geometry from the authenticated #299 census: F32 router
   `[2560,512]`, Q8_0 expert banks `[2560,640,512]` (up/gate) and
   `[640,2560,512]` (down), 10 active experts, one Q8_0 shared expert
   (`[2560,640]`/`[640,2560]`) with its own F32 `[2560]` sigmoid gate. All
   eight tensors of `blk.2` reside in shard
   `Qwen3.8-Flash-Next-Q8_0-00004-of-00006.gguf`.
2. **Reusable execution path**: the pinned ggml CPU + CUDA backends already
   implement every operation (`MUL_MAT`, `MUL_MAT_ID` incl. the CUDA fused
   up+gate+GLU MoE path, softmax/argsort_top_k/get_rows/swiglu/sigmoid
   reductions) and the async scheduling primitives
   (`tensor_set_async` / `graph_compute_async` / `tensor_get_async` /
   `synchronize`). `gguf` header parsing enables a bounded ~2.55 GiB
   selective read. No new loader, kernel, protocol, or scheduler was needed.
3. **Genuine concurrency opportunity**: within one block, after routing, the
   CPU-owned expert subset, the GPU-owned expert subset, and the activation
   H2D/D2H transfers are mutually independent; the router and the final
   combine remain ordered dependencies. The overlapped arm enqueues the
   secondary stream work in order and runs CPU compute concurrently; the
   serial arm synchronizes every stage. Both arms perform identical work.
4. **Same-weights/same-process reuse**: weights load once per process; the
   primary backend hosts experts `[0,split)` as views over host memory, the
   secondary backend owns a resident device copy of `[split,512)` uploaded at
   load; both arms and all repetitions reuse exactly these tensors.

**Strata resolution** (the bundle's missing identity): `Niko1221/Strata` @
`7695859aa13afb248bdb4d36f9b2e95707db079d` (MIT) is a complete custom engine
for this model family (VRAM expert cache + CPU expert processing + batched
async pinned DMA uploads; `robertkarl/UnbiasedStrata` @ `46c46ecf…` is a
stripped fork). Inspected as mechanism evidence only — its kernels target its
own quant packs, so adoption would be exactly the kernel/format adaptation
this prototype is scoped to avoid. Nothing here depends on Strata code.

## What was built (this branch)

- `moe_overlap_harness.cpp` (~900 lines, single TU) — serial and overlapped
  arms over the same resident block; SYNTHETIC or GGUF (bounded selective
  read) weights; per-repetition fresh inputs/outputs; fail-closed routed-work
  assertion; JSON report with per-rep stage timings, correctness gates,
  padding accounting, load timing and resource release.
- `build.py` — sha256-pinned source fetch + direct-GCC/Clang CPU closure
  (CMake-free, mirroring the #301 recipe approach), `--cuda` for the
  hardware host; `MOE_OVERLAP_OPT` for CI compile-speed tradeoffs.
- `tests/test_moe_overlap_prototype.py` — 7 unittest tests (workflow-run
  style): two-device split correctness, prefill padding accounting,
  single-device and all-secondary bitwise identity, CUDA fail-closed,
  error propagation, isolation.
- CI registration: planner group `moe-overlap-prototype`
  (`scripts/plan_ci.py` regenerated `scripts/ci_groups.json`), retention
  record, workflow job + gate mapping.
- `offline-validation/` — retained SYNTHETIC full-shape reports.

## Offline validation results (SYNTHETIC; no performance claim)

Dev container (CPU-only; secondary = second CPU backend, so overlap timing is
meaningless by construction and is never reported as a result):

- 7/7 offline tests pass (`python3 -m unittest tests.test_moe_overlap_prototype`).
- Full-authentic decode (`--tokens 1 --split 256 --reps 5`) and prefill
  (`--tokens 128 --split 256 --reps 5`): every gate passes; the overlapped
  arm is bit-identical to the serial arm in every repetition; the
  single-device serial arm is bit-identical to the unsplit llama.cpp-order
  reference; serial-vs-reference deviations stay within the pre-declared
  derived tolerance with ≥2× margin (max ratio ≤ 0.48); determinism recheck
  bit-exact; negative control (shared branch omitted) rejected at ≈2.8×10⁶
  times tolerance; routed counts exactly `10 × n_tokens` everywhere
  (prefill rep 0: 612+668 = 1280).

## Documentation-impact determination (per AGENTS.md / status-maintenance)

This change adds a self-contained prototype tool, its tests and its CI group.
It changes no capability, architecture decision, integration branch, gate
result, acceptance, or execution authority, so no living-status update is
warranted; this handoff plus the directory README/recipe carry the
documentation. `hardware-recipe.md` is explicitly a proposal that grants no
execution authority; issue #300 remains open and untouched.

## Review corrections (PR #307, second head)

The maintainer's exact-head review of `cb2ad082` returned NO-GO with five
findings and two test-contract issues. All are addressed in this head:

1. **P1 GGUF loader byte-to-tensor assignment** (router/shared-gate bytes were
   read into expert-bank storage): the loader now reads each tensor's bytes
   directly into its own tensor storage, independent of file order. A new
   offline fixture GGUF (distinct contents per tensor, alphabetical file
   order, authentic geometry) with an independent F64 block reference now
   guards this: **demonstrated to fail against the pre-fix loader** (both
   fixture tests fail with the reverted sequential-append assignment, pass
   with the fix).
2. **P1 CUDA build completeness**: `--cuda` now compiles every
   `ggml/src/ggml-cuda/*.cu` plus the 120 `template-instances/*.cu` TUs the
   pin's own CMake GLOBs enumerate, and `GGML_USE_CUDA` is defined at compile
   time for every TU (registration in `ggml-backend-reg.cpp` is compile-gated).
   No nvcc exists in the offline container, so this remains
   compile-verified-on-hardware-host only — stated in the README.
3. **Overlap defeat via pageable D2H**: the D2H read-back is now issued only
   after the CPU-side work completes (CUDA documents that async copies with
   pageable destinations may block the host). Stage reporting now exposes
   `d2h_ms` for the deferred read-back/join.
4. **P2 stale cached builds**: objects carry stamps (source hash + flags +
   compiler); mismatches rebuild. `MOE_OVERLAP_SOURCE` overrides are verified
   against selected complete-file digests from the accepted #299 runtime
   contract — a tree claiming the pin identity with different bytes is
   refused (demonstrated). A test proves reuse-when-unchanged and
   rebuild-on-stamp-mismatch.
5. **P2 ignored compute statuses**: every graph compute is status-checked; a
   failure aborts before any output comparison (no stale-output use), and
   non-finite outputs can never satisfy a tolerance comparison. A
   failure-injection control (`--self-check-status-negative`) proves the
   refusal path end-to-end.
6. **Test contracts**: `--warmup N` now runs N warmup repetitions (reported as
   `verdict.warmup_runs` and asserted), and repeated `--inputs-file`
   repetitions no longer demand distinct outputs (identical captured inputs
   are expected; the bitwise determinism recheck still applies).

Offline results at this head: 12/12 tests pass; retained full-shape SYNTHETIC
decode/prefill reports regenerated with all gates green.

## For the reviewer

- Focused diff: `git diff main -- tools/moe-overlap tests/test_moe_overlap_prototype.py scripts/plan_ci.py scripts/ci_groups.json docs/ci/test-retention-audit.json .github/workflows/ci.yml`.
- Cheap gates already run locally: `plan_ci.py --self-check` OK;
  `check_ci_test_retention.py` OK; `tests.test_moe_overlap_prototype` 7/7 OK;
  planner test deltas vs baseline: zero new failures (the remaining local
  planner failures are pre-existing environment artifacts — missing frozen
  tokenizer deps in this dev container, not in the canonical CI venv).
- Per campaign gate ordering, the hosted Final CPU Validation and exact-head
  CI run are for the maintainer to dispatch on the reviewed head.
