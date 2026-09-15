R8-E — Qwen3.8-Flash-Next residual true-greedy divergence characterization
(Issue #199; bounded two-case diagnostic, NO requalification)

Terminal (machine-derived by scripts/issue199_r8e_terminal_reduction.py):

R8E_RESIDUAL_DIVERGENCE_CHARACTERIZED | R8E_DEEPER_RUNTIME_LOCALIZATION_JUSTIFIED | R8E_EVIDENCE_BLOCKED
(filled after reduction)

Accepted predecessor (immutable, consumed, never rewritten)
-----------------------------------------------------------
Issue #195 / PR #197 merged as f142a0d9b693f999685960c641b2a8fe362c4e1e
(reviewed head ca7e159929190a04cabd059042def1b6bd4c2467), terminal
R8D_QWEN38_TRUE_GREEDY_NVIDIA_RPC_QUALIFICATION_FAIL. R8-D v2 evidence
byte-preserved (verified by the R8-E reducer's
r8d_v2_evidence_byte_preserved check on every derivation).

Objective (diagnostic, not adjudicative)
----------------------------------------
Characterize what the two residual true-greedy branches look like
immediately before token choice:
  1. case-256, generated position 5 (reference 271 vs candidate 34227)
  2. case-4096, generated position 0 (reference 328 vs candidate EOS
     248046)
and answer per case: margin-sensitive winner inversion, or materially
different next-token score structure.

Observation method (Phase 1)
----------------------------
No native llama.cpp output exposes the exact pre-sampler logits for the
current position (the pinned server's n_probs surface is
known-misaligned and forbidden as an oracle). An OBSERVATION-ONLY
diagnostic build was therefore created from the exact accepted source
b29c606e28a01b1bc8c1351026a0fa6e616bf6c4:

- patch: 85 added lines in tools/server/server-context.cpp; the hook is
  INERT unless LLAMA_OBSERVE_LOGITS is set; it reads (via
  llama_get_logits_ith) the same logits row the sampler just consumed
  at the sampling seam (immediately after common_sampler_sample in
  update_slots, bound to slot.stats.n_gen for token-position binding),
  performs NO llama/ggml state writes, changes no tensor placement,
  execution, sampling, precision, or state lifetime;
- byte-identity proof: apply_hook.py applied to a pristine b29c606e
  checkout reproduces the built source byte-for-byte;
- binary: build-obs/bin/llama-server sha256 c2d06193... (separately
  named path; the accepted llama-server/ggml-rpc-server binaries are
  unchanged and re-hashed);
- all digests/statistics over the retained exact float32 logits-row
  bytes are computed by the Python producer from the bytes; the C++
  emits only ids/ranks/values.

Non-perturbation proof: for both arms and both cases the UNINSTRUMENTED
accepted binary reproduced the accepted R8-D next token (fresh server
process per request), and the INSTRUMENTED binary's sampled token at
the observed position equals the accepted R8-D token for the
incremental state class (2 repeats each; see nonperturbation/ and
observations/).

State classes (physical finding)
--------------------------------
- incremental (decision-faithful): the original accepted prompt with
  n_predict=8; the hook observes every generated position; execution is
  byte-identical to the accepted R8-D request. This is the class the
  terminal derives from.
- tf (Issue #199 Phase-2 teacher-forced construction): prompt + accepted
  common prefix prefilled; first sampled position observed. PRE-FREEZE
  PHYSICAL FINDING: under tf prefill the case-256 REFERENCE emits
  34227 at the observed position, NOT the accepted 271 — the fixture
  prompt is a repeating pattern and the accepted 271 arises from
  incremental-decode numerics (prefill vs decode kernels). tf rows are
  retained as a separate state class and never substitute for
  incremental rows. (For case-4096 position 0, tf and incremental
  coincide by construction: first token after full prefill.)

Evidence layout
---------------
producer-hashes.json, MANIFEST.sha256, terminal-reduction.json
evidence/instrumentation/  apply_hook.py, applied-source.patch,
                          r8e-build.sh, instrumentation.json
evidence/run/             run-driver.sh, wait_backends.sh,
                          stop_rpc_backends.sh
evidence/nonperturbation/ 8 records (2 cases x 2 arms x 2 repeats,
                          accepted binary)
evidence/observations/    8 records + float32 rows (2 cases x 2 arms x
                          2 repeats, diagnostic binary, incremental)
evidence/observations-tf/ 8 records + float32 rows (tf state class)
evidence/negative-controls/ negative-controls.json (9 controls)

Non-claims
----------
No repair of llama.cpp; no revision/quantization/topology change; no
requalification of R8-D (its FAIL stands unchanged); no serving
integration; no production readiness; characterization scoped to the
pinned build/model/topology and the two decision points; no successor
issue created or executed in this campaign.
