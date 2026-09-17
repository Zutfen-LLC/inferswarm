R8-G — Qwen3.8-Flash-Next runtime-boundary localization
(Issue #207; bounded physical diagnostic, case-4096 primary, case-256
contrast ONLY; NO requalification, NO repair)

Terminal (machine-derived by scripts/issue207_r8g_reduce.py):

R8G_NONMONOTONIC_RUNTIME_DIVERGENCE_CHARACTERIZED

Correction round 2026-09-17 (maintainer review of PR #208): the
previous prose claimed R8G_EARLIEST_RUNTIME_BOUNDARY_LOCALIZED at
ffn_moe_out-0 while the committed terminal-reduction.json emitted
R8G_LOCALIZATION_EVIDENCE_BLOCKED (manifest digest cycle — the single
MANIFEST.sha256 listed README/terminal bytes that the reduction itself
generated). Both defects are corrected: the reduction now verifies a
dedicated evidence INPUT manifest (evidence/input-manifest.json, 4855
immutable input rows; no reducer output is ever an input row), and a
separate final closure (CLOSURE.sha256) pins README/terminal/producer
hashes/input manifest WITHOUT being a terminal input. Regeneration is
a byte-for-byte fixed point.

Why NONMONOTONIC (frozen R3 rule, applied across the COMPLETE ordered
refinement interval in frozen source order): boundary ffn_moe_out-0
differs and later boundaries INSIDE the same frozen interval —
ple_conv_out-1, linear_attn_qkv_mixed-1, conv_output_silu-1 — match
again. A later equal after an earlier differ prohibits the exact-
earliest interpretation, so monotonic/binary localization stops and
the divergence structure is characterized as non-monotonic.

DESCRIPTIVE (not an accepted exact-earliest terminal): ffn_moe_out-0
(layer-0 MoE expert-combine output, runtime node name from
src/models/qwen4exp.cpp build_layer_ffn cb() call site) is the FIRST
OBSERVED differing sub-boundary; its immediately preceding observable
boundary linear_attn_out-0 (layer-0 GDN mixer output projection) is
byte-equal under the frozen exact-f32-bytes contract. The reconver-
gence after it (layer-1 PLE conv and layer-1 mixer input boundaries
equal again) is exactly what makes the exact-earliest claim misleading
under R3 and forces the NONMONOTONIC terminal.

Accepted predecessors (immutable, consumed, never rewritten):
  R8-D  Issue #195 / PR #197  merge f142a0d9... terminal
        R8D_QWEN38_TRUE_GREEDY_NVIDIA_RPC_QUALIFICATION_FAIL
        (byte-preservation verified by the reducer on every derivation)
  R8-E  Issue #199 / PR #205  merge 8a3681b2... terminal
        R8E_DEEPER_RUNTIME_LOCALIZATION_JUSTIFIED
  R8-F  Issue #200 / PR #206  merge affa26cc... (campaign base)

## Result chain (all comparisons exact float32 bytes, target execution
bound by earliest-valid result_output occurrence + decision position)

Coarse (case-4096, frozen 18-boundary set COARSE_BOUNDARIES, 2
repeats/arm):
  model.input_embed : EQUAL (66844a5d...)
  l_last-2 .. l_last-47, result_norm : ALL DIFFER
  -> first interval (model.input_embed, l_last-2]; non-monotonic at
     the coarse level: NO (the coarse set contains no reconvergence)

Refinement (case-4096; complete frozen ordered interval = mechanically
derived layer-0..2 sublists + corrected PLE bracket ple_conv_out-1;
2 repeats/arm; every frozen boundary observable in both arms):

   1 linear_attn_qkv_mixed-0  equal
   2 conv_output_silu-0       equal
   3 final_output-0           equal
   4 linear_attn_out-0        equal
   5 ffn_moe_out-0            DIFFER   <- first observed difference
   6 ffn_out-0                differ
   7 ple_conv_out-1           EQUAL    <- reconvergence (R3 trigger)
   8 linear_attn_qkv_mixed-1  equal      (reconvergence continues)
   9 conv_output_silu-1       equal
  10 final_output-1           differ   <- divergence resumes
  11 linear_attn_out-1        differ
  12 ffn_moe_out-1            differ
  13 ffn_out-1                differ
  14 linear_attn_qkv_mixed-2  differ
  15 conv_output_silu-2       differ
  16 final_output-2           differ
  17 linear_attn_out-2        differ
  18 ffn_moe_out-2            differ
  19 ffn_out-2                differ

  Differ->equal reconvergences observed inside the frozen interval:
    ffn_moe_out-0/ffn_out-0 (differ) -> ple_conv_out-1 (equal)
    ... -> linear_attn_qkv_mixed-1 (equal), conv_output_silu-1 (equal)
  followed by re-divergence from final_output-1 onward. The layer-1
  mixer-input equal boundaries are comparable members of the frozen
  ordered interval (same target execution, same decision position,
  same comparison contract), so R3 applies and the interval is
  NON-MONOTONIC.

  Note: the corrected PLE bracket (ple_conv_out-1, from GGUF metadata
  qwen4exp.ple.layers=[1]) was frozen BEFORE observation (commit
  69ff3b4, prior to any cross-arm refinement comparison); both spec
  generations retained under refine/ and refine-ple/.

case-256 contrast (authorized set ONLY, mechanically derived from the
accepted case-4096 result: refined interval boundaries + adjacent
coarse anchors model.input_embed/l_last-2 + one frozen checkpoint
l_last-23; 22 boundaries; 2 repeats/arm):
  model.input_embed, layer-0 mixer sub-boundaries through
  linear_attn_out-0 : EQUAL
  ffn_moe_out-0 : DIFFER  <- first authorized-set difference
  ffn_out-0 : differ
  ple_conv_out-1 : DIFFER (unlike case-4096, where it is equal)
  linear_attn_qkv_mixed-1, conv_output_silu-1 : EQUAL (reconvergence,
    same structure as case-4096)
  final_output-1 onward through ffn_out-2, l_last-2, l_last-23 :
    differ

  Bounded classification (authorized set only): case-256 shows the
  same first observed difference at ffn_moe_out-0 AND the same
  reconvergence pattern (later equal boundaries inside the interval),
  i.e. a case-4096-consistent NON-MONOTONIC divergence structure —
  NOT a "same exact-earliest boundary" claim (the exact-earliest
  interpretation is prohibited for case-4096, so it cannot be claimed
  for case-256 either). Extra retained rows outside the authorized
  set (layer-2 sub-boundaries in contrast-ple captures, result_output
  seam rows) are incidental evidence and expand no acceptance claim.

Seam anchor validations: every capture's accepted-token reproduction,
prompt identity, and arm-anchored seam identity verify against the
accepted R8-E rows (case-4096 pos-0 rows via the sampling-seam hook
bytes; case-256 pos-5 rows via the boundary observer's result_output
column at the decision execution — the contrast driver ran
LLAMA_OBSERVE_POS=0, so the hook row bytes are absent there and the
observer column is the retained anchor; both anchor derivations
byte-match the accepted R8-E rows for all 24 captures).

## Observation method (Phase 1)

Observation-only diagnostic build from the EXACT accepted source
b29c606e28a01b1bc8c1351026a0fa6e616bf6c4 (worktree r8g-obs, binary
llama-server sha256 e0125f66...; accepted binaries UNCHANGED and
re-hashed; apply_hook.py reproducer REPRO_IDENTICAL):

- sampling-seam hook with accepted R8-E semantics (token-position
  binding + exact f32 logits row);
- the NATIVE scheduler eval-callback seam
  (ggml_backend_sched_set_eval_callback via params.cb_eval) observes
  named graph nodes post-compute/post-synchronize: reads tensor bytes
  (ggml_backend_tensor_get), retains the frozen LAST-TOKEN column raw
  f32 sidecars + sha256 rows. No writes, no placement input, no
  split-policy change, no execution-math change.

Non-perturbation: instrumented captures reproduce the accepted R8-D
tokens AND accepted R8-E logits-row bytes on both arms (2 repeats
each, fresh server per capture, GPU-idle gated).

## Physical findings retained (drift incidents, both root-caused;
kept truthful, separated from accepted captures)

1. A stray leftover GPU process (104 MiB) changed the memory-fit ->
   layer split -> kernel assignment on the reference arm: float32 bytes
   drifted while tokens stayed identical. ALL captures now run behind a
   fail-closed GPU-idle gate (run-driver.sh gpu_idle_gate).
2. RPC backend flakiness after mid-run kill/restart produced drifted
   candidate rows and one aborted request; fresh-backend reruns match
   accepted bytes. Both observation hooks agreed on every drifted row
   (drift is real state, not instrumentation).

## Manifest / closure architecture (correction item 4)

  evidence/input-manifest.json  INPUT manifest — 4855 rows covering
      ONLY immutable reduction inputs (captures, raw f32 sidecars,
      hook JSONLs, anchor rows, instrumentation, run driver). The
      terminal reduction verifies every row + file-set equality; a
      reducer-output row listed here fails closed (digest-cycle
      prevention).
  CLOSURE.sha256                FINAL closure — 4 rows (README.md,
      terminal-reduction.json, producer-hashes.json,
      evidence/input-manifest.json). NOT a reducer input; regenerated
      after reduction; pinned at fixed point.
  producer-hashes.json          pins the six R8-G producer scripts.
  Deterministic fixed point: reduce -> inputs -> producers -> closure,
      repeated, changes zero bytes (verified).

## Fail-closed controls

21 controls (issue207_r8g_negative_controls.py; 15 Issue #207 classes
+ baseline + variants + one positive control), every attack executed
against the production reduction path in an isolated sandbox:
predecessor manifest tamper (R8-D row, R8-E row), instrumentation/
binary identity tamper, wrong prompt, case substitution, arm
placement swap, token-position binding removal, boundary identity
blanked, stale cross-arm sidecar substitution, authored-digest-vs-
bytes contradiction, same-byte symlink (CORRECT expected bytes through
a symlink — rejected), path-alias through a symlinked directory
(rejected), same-size bit-flip with consistently re-forged row sha +
input-manifest rows (repeat-stability breaks), accepted-token drift,
post-hoc checkpoint insertion (l_last-1 row + sidecar + manifest all
consistent — terminal input set unchanged), earliest-without-
preceding-match (blocked), first-boundary-differs-with-later-equal
(reconvergence -> NONMONOTONIC), LOCALIZED-after-reconvergence
(forced to NONMONOTONIC), monotonic positive control (localizes),
case-256 extra rows beyond the authorized set (classification
unchanged).

## Non-claims

No llama.cpp bug or fix; no production Qwen3.8 correctness; no shared
case-256/case-4096 cause claim; no AMD/Vulkan work; no serving
integration; localization characterizes WHERE divergence becomes
observable and that the structure is non-monotonic (first observed at
the layer-0 MoE expert combine, reconverging at layer-1 mixer inputs,
re-diverging from layer-1 gated output onward), not WHY. No exact-
earliest-boundary acceptance. No R8-D requalification; no runtime
repair; no topology/sampler change; no automatic bandwidth policy.
