R8-G — Qwen3.8-Flash-Next earliest runtime-boundary localization
(Issue #207; bounded physical diagnostic, case-4096 primary, case-256
contrast ONLY; NO requalification, NO repair)

Status: IN PROGRESS — coarse localization complete; refinement + contrast
phases running. Terminal emitted only by scripts/issue207_r8g_reduce.py.

Accepted predecessors (immutable, consumed):
  R8-D  Issue #195 / PR #197  merge f142a0d9... terminal
        R8D_QWEN38_TRUE_GREEDY_NVIDIA_RPC_QUALIFICATION_FAIL
  R8-E  Issue #199 / PR #205  merge 8a3681b2... terminal
        R8E_DEEPER_RUNTIME_LOCALIZATION_JUSTIFIED
  R8-F  Issue #200 / PR #206  merge affa26cc... (this campaign's base)

## Observation method (Phase 1)

Observation-only diagnostic build from the EXACT accepted source
b29c606e28a01b1bc8c1351026a0fa6e616bf6c4 (worktree r8g-obs, binary
llama-server sha256 e0125f66...; accepted binaries UNCHANGED and
re-hashed; patch reproducer REPRO_IDENTICAL):

- sampling-seam hook with the accepted R8-E semantics (token-position
  binding + exact f32 logits row) — retained for non-perturbation and
  seam-anchor cross-checks;
- NEW: the NATIVE scheduler eval-callback seam
  (ggml_backend_sched_set_eval_callback, wired via params.cb_eval —
  src/llama-context.cpp:1365) observes every named graph node
  post-compute/post-synchronize: reads the tensor bytes
  (ggml_backend_tensor_get), extracts the frozen LAST-TOKEN column along
  the token axis, retains raw f32 sidecars + sha256 rows. Observation
  only: no writes, no placement input, no split-policy change.

Non-perturbation (both arms, 2 repeats, fresh server each): instrumented
captures reproduce the accepted R8-D tokens AND the accepted R8-E pos-0
logits row byte-for-byte; the eval-callback result_output column at the
target execution equals the R8-E row independently retained by the
sampling-seam hook (two independent observation paths, identical bytes).

PHYSICAL FINDING (drift root cause, retained for the record): a stray
leftover GPU process (104 MiB, R8-F residue) changed the memory-fit ->
layer split -> kernel assignment on the reference arm, drifting the
float32 bytes while tokens stayed identical. All captures run behind a
fail-closed GPU-idle gate; the drifted first nonpert attempt was
discarded and rerun on a proven-idle machine.

## Coarse localization (Phase 2, case-4096)

Frozen 18-boundary coarse set + seam anchor; 2 repeats per arm;
byte-exact per-boundary comparison of the target-execution last-token
column:

  model.input_embed : EQUAL across arms (66844a5d...)
  l_last-2 ... l_last-47, result_norm, result_output: ALL DIFFER

First interval: (model.input_embed, l_last-2] — divergence onset is
inside layers 0-2 (PLE layer 0 + GDN layers 1-2). Non-monotonic: no.

## Refinement (Phase 3, in progress)

Frozen sublists of layers 0,1,2 (PLE conv out; qkv; conv state; gated
norm; mixer out; MoE; shared-expert) observed in order.

## Non-claims

No llama.cpp bug or fix; no production correctness; no shared
case-256/case-4096 cause claim; no AMD/Vulkan work; no serving
integration; localization identifies WHERE divergence becomes
observable, not WHY.
