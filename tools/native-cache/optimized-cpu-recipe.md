# Hermes: bounded optimized CPU prerequisite

Coding base: fetched main `02e00ac5eb465257bbc2d124bf84773770260967`.
This is a later-execution recipe, NOT hardware or full-model authorization.
PR #332 supplied this build recipe. The subsequent candidate identity review
is recorded in [the additive build-pair note](optimized-cpu-build-pair/README.md).
No speedup or physical qualification is claimed. Historical identities and
evidence remain unchanged.

## Intended delta

Use the unchanged `operator-build.py` composer and its retained archive:
llama.cpp `b29c606e28a01b1bc8c1351026a0fa6e616bf6c4`, archive SHA-256
`03fb04316eb32a7b7347004a79a8dd60531c02f5a064d853fed3b53828951723`.
The historical recipe's bytes contribute to patch identity and must not change.
The candidate retains native patch SHA-256
`df52ba458ad8c6758de9084b2cc56d4dcdae9683f97405f1a4b17f88e738bfd4`.

Only compiler-option changes:

- `CMAKE_C_FLAGS_DEBUG`: `-O0 -g0` -> `-O3 -g0`.
- `CMAKE_CXX_FLAGS_DEBUG`: `-O0 -g0` -> `-O3 -g0`.

Keep `CMAKE_BUILD_TYPE=Debug` (assertions remain enabled), static linkage,
RPC ON, CUDA/Vulkan/OpenMP/BLAS/GGML_NATIVE OFF and all other historical options.
`CMAKE_EXPORT_COMPILE_COMMANDS=ON` adds inspection metadata only. No CPU ISA,
threading, fast-math or backend tuning, dependencies, tolerance or CUDA rebuild.
Use the same provisioned C/C++ toolchain as the accepted CPU05 build (recorded
C++ banner `c++ (Debian 14.2.0-19) 14.2.0`); stop on unexplained toolchain or
environment-flag drift rather than folding a second variable into this comparison.

## A. Candidate build on inferswarm05; bounded checks; STOP for identity review

Under separate build/check authority, use the retained archive, installed tools,
and a fresh owned absolute output path. Never reuse an accepted build directory.
The recipe bounds each configure/build command to 3600 seconds, two build jobs,
the historical 3 GiB address-space limit and no core dumps. Freeze an outer
90-minute preparation budget including checks and cleanup; an actual timeout is
a STOP, not permission to rebuild with changed flags. No host03 operations.

```bash
python3 tools/native-cache/operator-build-cpu-optimized.py \
  --archive /absolute/retained/pin.tar.gz \
  --output /absolute/fresh/optimized-cpu-candidate \
  --cmake /absolute/provisioned/cmake
```

1. Retain `CMakeCache.txt`, `compile_commands.json`, `effective-flags.json`,
   both build logs, `optimized-cpu-receipt.json` and both complete
   `*.build-manifest.json` files. The receipt includes actual configured C/C++
   compiler paths/full version outputs, CMake version, recipe digest, options,
   command lines, native/archive/patch/composite identity, executable and static
   library closure hashes, plus the separate `is311-loader` executable hash.
   The unused CPU RPC worker is built only to preserve the existing compact
   CPU fixture target set; it is NOT the proposed worker for the comparison.
2. Inspect actual generated commands, not only requested options. The recipe
   refuses cache drift, missing commands, a last effective optimization other
   than `-O3` (including trailing `-O0`), or `NDEBUG`, before native compilation.
   Compare the remaining effective flags, backend settings and compiler banner
   with the retained CPU05 build. Retain path-derived composite differences:
   the unchanged composer embeds absolute paths, so a new directory need not
   reproduce the old composite. Do not edit hashes or rebuild until they match.
3. Perform no-model CPU CLI smoke only, saving stdout/stderr and exit status:
   `timeout 30 <candidate>/build/bin/llama-server --version` and
   `timeout 30 <candidate>/build/bin/llama-server --list-devices`.
   Require successful exits and CPU-only discovery. No model load or GPU access.
   Reuse the existing offline qualification checks:
   `python3 -m unittest tests.test_issue311_cuda_backing tests.test_issue311_preparation -v`.
   These checks plus CLI discovery are bounded functional observations, not
   numerical qualification or a full-model certificate. Do not point
   `NATIVE_ASSIGNED_BUILD` at the candidate: that historical native fixture
   intentionally pins the old CPU pair and would refuse a new identity.
4. STOP and hand off the actual client manifest, receipt, effective flags,
   toolchain comparison and check logs for maintainer review. Only after that
   review, record the complete real client manifest additively at
   `tools/native-cache/optimized-cpu-build-pair/cpu05-llama-server.build-manifest.json`.
   The actual reviewed candidate now occupies this path. Future replacements
   require their own identity review. Do not insert placeholders, copy a
   synthetic test identity, mutate the historical tables/manifests, or promote
   a caller-supplied hash. The recipe never installs or records approval itself.

The finite `optimized-cpu05-cuda03` selector binds that reviewed client manifest
and refuses BOTH roles if it is absent. It always uses the
unchanged complete Step A CUDA worker manifest, executable
`46345f6c4df4f229aa11e76514c6c6eff9c9a148257f9232a505c8173d2ebf73`.
Omission/`historical-cpu` and `step-a-cpu05-cuda03` keep their prior meanings.
Mixed/unknown pairs refuse; ordinary unknown-allocation/physical gates remain.

## B. Controlled follow-through (describe only; separately authorized)

After the real-build identity handoff, use the existing
[q8 load-once recipe](q8-load-once-recipe.md) and
[two-CUDA supervision/preparation](q8-two-cuda-recipe.md), not a new qualifier.
Change only the CPU client runtime/manifest paths, its reviewed executable hash,
explicit `strategy_options.build_pair: optimized-cpu05-cuda03`, and dependent
profile/config/envelope bindings. Preserve model/revision/representation, source
pin, native patches, threads/batch/context and all remaining runtime settings.
Rebind profiles honestly; do not carry an old config hash over changed bytes.

- Same 05 CPU / 03 two-GPU placement: CPU layers 0–40, CUDA0 layers 41–44,
  CUDA1 layers 45–47 plus output. Same accepted CUDA worker on both listeners;
  no CUDA rebuild, placement search or observer redesign.
- Reuse verified assigned backing, both disjoint listener guards, and the
  established opt-in `--source-digest-cache`. Existing verification must still
  authenticate both banks; missing/drifted backing is STOP, not reacquisition.
  Permit compilation of the checked-in invocation-local FNV helper as routine
  preparation: the runner requires it. This is not a runtime rebuild.
- One model load. Copy the actual retained prior session's warmup and short
  decode request objects/settings without changes, preserving their frozen
  serialization/digests; verify against those retained inputs, not a newly
  typed approximation. If the prior bytes are unavailable, STOP the direct
  comparison. No extra warmups, retries, hidden requests or reloads.
- Replace ONLY the oversized prefill with a separately labeled frozen smaller
  workload, for example 12 numbered color records and the existing color-only
  question (change the queried row to one present). Target roughly 128–256
  prompt tokens, retain `n_predict:16`, greedy settings, `cache_prompt:false`
  and the existing 900-second HTTP timeout. Keep it distinct from the historical
  prefill; it is NOT an A/B result against the timed-out larger request.
  Before execution, use an already available model-compatible tokenizer/counting
  facility if present, retaining its identity, prompt bytes, count and settings.
  Do not install/download a tokenizer or add a model load to obtain a count.
  Without such a facility, label the target approximate, freeze the smaller
  prompt anyway and report returned `tokens_evaluated`/`timings.prompt_n` (and
  `cache_n`) as actual observations; never infer exact tokens from characters.
  Never adapt the prompt after seeing candidate timing or answer results.
- Freeze the ordered session with existing `validate_session`, retain exact
  bytes/digest and label mapping, and bind its digest in the new envelope.
  Invoke the existing `experimental-q8-two-cuda --config ... --envelope ...
  --session ... --source-digest-cache ... --evidence-root ...` once. Retain
  the existing outer 180-minute budget, 160-minute execution STOP, 20-minute
  cleanup reserve, host/swap/VRAM/disk limits and per-request timeout unchanged.
- Report verification time, load time, each request's wall/native timings and
  returned counts separately. Exclude warmup from measured summaries but not
  budget accounting. Apply the existing offline decode-cycle/color-answer
  checks; distinguish wrong answer, cap truncation, execution error and timeout.
  Missing native timing stays missing; nonstreaming wall time is not TTFT.
- Preserve observer saturation/refusal as a diagnostic limitation, raw responses,
  partial failures and cleanup receipts. Do not repair saturation, change
  tolerances or infer owned kernel execution from sampled GPU use. Keep
  `output_accepted:false` and `physical_qualified:false`. Stop after the one
  session and verified owned cleanup; no speedup is assumed in advance.

## Coding/merge readiness

Focused offline tests extend the already registered `test_issue311_cuda_backing`
module; no separate certification or CI population is introduced. No accepted
capability, physical result or execution authority changes, so generated project
status remains unchanged. The additive build-pair note records identity review
only; the later controlled follow-through still requires separate authorization.
After separate publication authorization and exact-head review, batch the final
changes and use the existing authenticated ordinary-CI reuse path in
`docs/campaign-gate-ordering.md` at merge readiness. Do not repeatedly run full
suites during development, infer a CI receipt or dispatch hardware from CI.
