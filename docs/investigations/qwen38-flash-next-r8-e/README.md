R8-E — Qwen3.8-Flash-Next residual true-greedy divergence characterization
(Issue #199; bounded two-case diagnostic, NO requalification)

Terminal (machine-derived by scripts/issue199_r8e_terminal_reduction.py):

R8E_RESIDUAL_DIVERGENCE_CHARACTERIZED

Result (raw values, no post-hoc threshold)
------------------------------------------
case-256, generated position 5 (incremental state class, decision-faithful):
  reference : winner 271 (logit 16.706398), runner-up 34227 (16.0985374),
              top1-top2 margin +0.6079
  candidate : winner 34227 (16.3057117), runner-up 271 (16.000248),
              margin +0.3055
  top-16 overlap 14/16; the two competing tokens are the TOP-2 in BOTH
  arms; rank 3+ tokens agree closely (31347 13.81/13.92, 25292
  13.65/13.64). Consistent with a narrow numerical-margin inversion
  between otherwise coherent distributions.
  Cross-arm logit deltas: 271: -0.706 (ref 16.706 -> cand 16.000);
  34227: +0.207 (16.099 -> 16.306).
  tf-state cross-check: under teacher-forced prefill the arms MIRROR
  (reference emits 34227, candidate emits 271) — both arms sit close to
  the 271/34227 decision boundary from opposite sides.

case-4096, generated position 0 (4097-token prompt, first token):
  reference : winner 328 (15.0245876), 561 (14.5521736), 359
  (14.0666008), 271 (13.8466511), EOS 248046 rank 5 (13.2554426);
              margin +0.4724
  candidate : winner EOS 248046 (16.6363716), 328 rank 2 (15.4173584),
              271 (14.860343), 561 (14.6030521), 359 (13.6044436);
              margin +1.2190
  top-16 overlap 13/16. EOS IS candidate argmax before sampling (rank 1
  vs reference rank 5); reference winner 328 is candidate rank 2. The
  EOS win is accompanied by a moderate top-K reorder (overlap 13/16,
  EOS +3.38 logits cross-arm) — but the reference winner remains the
  candidate runner-up and the familiar-token structure (328/561/359/
  271) persists in both top-5s: consistent with a margin inversion
  riding on a moderately shifted, still-coherent distribution rather
  than a qualitatively different score structure.

Per the frozen reducer rule (materially different score structure iff
top-16 overlap < 12/16, or non-finite logits, or loser missing from
the other arm's top-16 with a large gap), BOTH cases classify as
margin-sensitive winner inversions. Deeper runtime localization is NOT
justified by this evidence: no separately-authorized layer/state
boundary localization issue is motivated by these two decision points.

Repeat stability: every arm/case pair reproduced byte-identical float32
logits rows (f32_row_sha256 equal across repeats) and identical token
sequences. Non-finite counts: 0 everywhere.

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

Local full-suite runner isolation anomaly (documented, pre-existing)
-------------------------------------------------------------------
scripts/run_full_cpu_suite.py on BOTH the campaign head and origin/main
f142a0d (verified in a scratch worktree, same .venv) reports the same
three test_issue193_r8c.TestNegativeControls errors in the parallel
population task (task 5). The identical module set runs green in a
single process (626 tests OK) and the modules pass under the hosted
vulkan-v0-b CI group on the exact final head. This is the known local
parallel-runner isolation anomaly class, pre-existing on main, not a
regression of this campaign; no test was weakened.
