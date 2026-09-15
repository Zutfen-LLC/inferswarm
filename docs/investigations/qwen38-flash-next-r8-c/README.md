R8-C — Qwen3.8-Flash-Next UD-IQ1_S deterministic RPC divergence diagnosis (Issue #193)
=======================================================================================

Terminal (machine-derived by scripts/issue193_terminal_reduction.py):
R8C_QWEN38_RPC_DIVERGENCE_CAUSE_LOCALIZED

Starting point: origin/main 3448cc7d63853079fff2520952c2b65d586ae3e4 (accepted
R8-B merge, verified ancestral; it was main's head at freeze). Branch:
issue-193-r8c-qwen38-rpc-divergence-diagnosis.

Cause (see terminal-reduction.json for the machine-checked chain)
------------------------------------------------------------------
The accepted R8-B exact-token FAIL is NOT RPC transport or state corruption.
It is causally localized to the request-level sampler chain:

1. The R8-B protocol sent samplers=["greedy"]. At llama.cpp b29c606e the
   name "greedy" does not resolve to any sampler (there is no greedy entry in
   common_sampler_types_from_names). The accepted R8-B reference-server.log
   retains the warning "unable to match sampler by name 'greedy'" (16x) and
   the actually-built chain "logits -> dist" (2x per launch). Both accepted
   arms therefore ran SEEDED DISTRIBUTION SAMPLING (mt19937, seed 0), not
   greedy argmax.
2. Distribution sampling amplifies lawful cross-backend numerical-path logit
   differences into token-level divergence: any sub-logit-noise difference
   moves the cumulative-sum crossing point of the seeded uniform draw. The
   reference arm's backbone ran ~41.3 GiB CPU-side (load-log retained) while
   the candidate's ran across five CUDA devices — large numerical-path
   difference, deterministic per arm.
3. Rank proof from retained full-vocab logits (Phase 4 tool, R arm): the
   accepted reference stream contains tokens at full-vocab rank 1 (pos 1),
   ~154k (pos 2), ~1.6k (pos 3), ~42k (pos 4) of the emitted distribution —
   impossible under true greedy; expected under dist sampling.
4. Single-factor intervention (Phase 5, request field ONLY: samplers=["top_k"],
   top_k=1 = true greedy; binaries/model/topology/protocol otherwise exact):
   the same five-device RPC candidate vs the reference becomes token-identical
   on case-1024 and case-3072, agrees through position 5 (of 8) on case-256.
   The historical case-4096 immediate-EOS persists in the candidate arm.

Wedge controls (Phase 2, all on the case-256 sentinel, pinned blk.0-7 subset
~6936.10 MiB, identical placement retained from load logs):
- Wedge A (same physical GPU 01-CUDA0): direct CUDA [561,40554,32039,51358,...]
  vs loopback RPC [561,40554,32039,30581,...] — deterministic in both arms,
  divergence without any network or remote host: the execution-path variable
  alone suffices under dist sampling.
- Wedge B: loopback RPC (01 GPU0) vs remote RPC (03 GPU0, matched 3060,
  driver 610.57.04): streams byte-identical, top-20 logprobs identical to 4
  decimals — cross-host transport exonerated.
- Wedge C (Phase 1): the accepted five-device topology reproduced its exact
  accepted outputs (and placement) under the exact pinned authority.

Observation-surface findings (retained, evidence/phase3-*):
- The pinned server's n_probs logprob rows are row-misaligned relative to the
  sampled decision row (emitted token != reported-distribution argmax in every
  arm including the reference; stable across n_predict shapes; reproduces with
  -np 1). Near-tie margin claims from that surface are therefore NOT used.
  Requesting n_probs itself perturbs the dist-sampled stream (R arm pos3
  28056 -> 19577), consistent with the dist-amplification mechanism.
- The Phase 4 diagnostic tool (tools/dump_logits.cpp, compiled against the
  pinned build's .so set; source + build log retained) dumps full-vocab fp32
  logits rows and reproduces argmax chains; its heap stability is fragile
  under the fit lambda (two crashes retained honestly in dl-R-full.log); the
  one complete capture (R arm, 8 rows x 248320) is the rank-evidence source.

Negative controls / fail-closed proofs retained in tests +
terminal reduction: wrong-token mutation, placement mismatch, missing chain
step, non-derived terminal — each rejected.

Historical integrity
--------------------
The accepted R8-B bundle is byte-preserved (re-verified against its own
MANIFEST at Phase 0; evidence/r8b-bundle-reverification.json). The R8-B FAIL
remains valid under its own frozen comparator and is NOT reinterpreted as
PASS here. R8-C claims no repair, no requalification, no general llama.cpp
RPC conclusion, no AMD/Vulkan evidence.

Recommended successor (NOT created, per issue boundaries)
---------------------------------------------------------
One narrowly scoped requalification issue: re-run the R8-A/R8-B qualification
ladder with a sampler chain that actually resolves (e.g. top_k=1) or a
validated exact-token greedy contract, and with a corrected logit-row
observation surface if margins are needed.
