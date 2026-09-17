R8-G — Qwen3.8-Flash-Next earliest runtime-boundary localization
(Issue #207; bounded physical diagnostic, case-4096 primary, case-256
contrast ONLY; NO requalification, NO repair)

Terminal (machine-derived by scripts/issue207_r8g_reduce.py):

R8G_EARLIEST_RUNTIME_BOUNDARY_LOCALIZED

Earliest divergent boundary: ffn_moe_out-0 (layer-0 MoE expert-combine
output, runtime node name from src/models/qwen4exp.cpp build_layer_ffn
cb() call site). Immediately preceding observable boundary
linear_attn_out-0 (layer-0 GDN mixer output projection) proven
byte-equal under the frozen exact-f32-bytes comparison contract.

Accepted predecessors (immutable, consumed, never rewritten):
  R8-D  Issue #195 / PR #197  merge f142a0d9... terminal
        R8D_QWEN38_TRUE_GREEDY_NVIDIA_RPC_QUALIFICATION_FAIL
        (byte-preservation verified by the reducer on every derivation)
  R8-E  Issue #199 / PR #205  merge 8a3681b2... terminal
        R8E_DEEPER_RUNTIME_LOCALIZATION_JUSTIFIED
  R8-F  Issue #200 / PR #206  merge affa26cc... (campaign base)

## Result chain (all comparisons exact float32 bytes, target execution
bound by earliest-valid result_output occurrence + decision position)

Coarse (case-4096, frozen 18-boundary set, 2 repeats/arm):
  model.input_embed : EQUAL (66844a5d...)
  l_last-2 .. l_last-47, result_norm, result_output : ALL DIFFER
  -> first interval (model.input_embed, l_last-2]; non-monotonic: NO

Refinement (case-4096, frozen layer-0/1/2 sublists + corrected PLE
bracket, 2 repeats/arm):
  layer-0 GDN mixer: linear_attn_qkv_mixed-0, conv_output_silu-0,
    final_output-0, linear_attn_out-0 : ALL EQUAL
  ffn_moe_out-0 : FIRST DIFFER  <- earliest divergent boundary
  ffn_out-0, ple_conv_out-1(equal), linear_attn_qkv_mixed-1(equal),
    final_output-1 onwards : differ as indicated (see
    terminal-reduction.json refinement.observations for every verdict)

  Note: ple_conv_out-1 EQUAL is bracket evidence from the corrected PLE
  pass (the initial authority draft wrongly froze PLE_LAYER=0; the GGUF
  metadata qwen4exp.ple.layers=[1] correction was applied BEFORE any
  cross-arm refinement comparison was observed; both spec generations
  retained under refine/ and refine-ple/).

case-256 contrast (frozen contrast set, 2 repeats/arm):
  SAME earliest observed boundary: linear_attn_out-0 EQUAL,
  ffn_moe_out-0 DIFFER; downstream differing. Classification: same
  earliest observed boundary. NOT a common-root-cause claim.

Seam anchor validations: every capture's result_output column at the
bound execution byte-matches the accepted R8-E pos-0/pos-5 rows for the
respective case/arm (nonpert + coarse + refine + contrast phases).

## Observation method (Phase 1)

Observation-only diagnostic build from the EXACT accepted source
b29c606e28a01b1bc8c1351026a0fa6e616bf6c4 (worktree r8g-obs, binary
llama-server sha256 e0125f66...; accepted binaries UNCHANGED and
re-hashed; apply_hook.py reproducer REPRO_IDENTICAL):

- sampling-seam hook with accepted R8-E semantics (token-position
  binding + exact f32 logits row);
- NEW: the NATIVE scheduler eval-callback seam
  (ggml_backend_sched_set_eval_callback via params.cb_eval) observes
  named graph nodes post-compute/post-synchronize: reads tensor bytes
  (ggml_backend_tensor_get), retains the frozen LAST-TOKEN column raw
  f32 sidecars + sha256 rows. No writes, no placement input, no
  split-policy change, no execution-math change.

Non-perturbation: instrumented captures reproduce the accepted R8-D
tokens AND accepted R8-E logits-row bytes on both arms (2 repeats each,
fresh server per capture, GPU-idle gated).

## Physical findings retained (drift incidents, both root-caused)

1. A stray leftover GPU process (104 MiB) changed the memory-fit ->
   layer split -> kernel assignment on the reference arm: float32 bytes
   drifted while tokens stayed identical. ALL captures now run behind a
   fail-closed GPU-idle gate (run-driver.sh gpu_idle_gate).
2. RPC backend flakiness after mid-run kill/restart produced drifted
   candidate rows and one aborted request; fresh-backend reruns match
   accepted bytes. Both observation hooks agreed on every drifted row
   (drift is real state, not instrumentation).

## Fail-closed controls

12 synthetic reducer-level controls (issue207_r8g_negative_controls.py),
all rejecting: predecessor manifest tamper, wrong prompt identity,
case substitution, token-position binding removal, boundary identity
blanked (boundary_state_strict), sidecar same-size tamper, symlink
substitution, instrumented token drift, post-hoc checkpoint insertion,
earliest-without-preceding-match, reconvergence-after-differ,
frozen-set insertion.

## Non-claims

No llama.cpp bug or fix; no production Qwen3.8 correctness; no shared
case-256/case-4096 cause claim; no AMD/Vulkan work; no serving
integration; localization identifies WHERE divergence becomes
observable (layer-0 MoE expert combine), not WHY. No R8-D
requalification; no runtime repair; no topology/sampler change.
