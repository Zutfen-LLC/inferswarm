R8-D authority freeze (Phase 0)
===============================

Frozen: 2026-09-15, BEFORE any Phase 2+ correctness-bearing model output
(Issue #195 Phase 0). Authority module:
scripts/issue195_r8d_authority.py (this freeze's constant source).

Starting point
--------------
- origin/main = f65b70970a9a10bf57bd58a902fe6e08b588c619 (accepted R8-C
  merge, PR #194) — verified ancestral (it is the main head at freeze).
- Branch: issue-195-r8d-true-greedy-requal.

Accepted predecessors (consumed, never rewritten)
-------------------------------------------------
- Issue #191 / PR #192, terminal R8B_QWEN38_NVIDIA_RPC_RUNTIME_QUALIFICATION_FAIL.
- Issue #193 / PR #194, terminal R8C_QWEN38_RPC_DIVERGENCE_CAUSE_LOCALIZED.
- All three evidence bundles (r8-a 18 rows, r8-b 23, r8-c 70) verified
  byte-exact against their MANIFEST.sha256 at this main head before freeze.

Runtime/model authority (re-verified fresh at R8-D freeze)
----------------------------------------------------------
- llama.cpp b29c606e28a01b1bc8c1351026a0fa6e616bf6c4 (v0.4.1); binaries at
  /home/hermes/llama.cpp/build-v041/bin re-hashed on inferswarm01/03/04:
  llama-cli 3f6b0ed4..., llama-server de3a8a54..., ggml-rpc-server
  a897f908... — byte-identical to the accepted R8-B/R8-C pins.
- Source checkout at /home/hermes/llama.cpp verified at exactly b29c606e
  (rev-parse) for the Phase 1 sampler-contract source proof.
- Model: /srv/models/qwen38-ud-iq1-s on inferswarm01; all three member
  sha256 re-hashed against accepted R8-A pins at freeze
  (evidence/split-identity/; total 72,546,461,344 bytes asserted).

Fresh raw host inventory (retained verbatim, evidence/host-inventory/)
----------------------------------------------------------------------
Per host: hostname, UTC timestamp, uname, ip addr, full nvidia-smi -q,
CSV query (uuid/BDF/mem/driver/link), nvcc, llama/rpc process census
(none on all three hosts), and the three binary hashes.
- GPU UUID/BDF set on all three hosts IDENTICAL to the accepted R8-B
  topology (5 CUDA devices). GPUs idle.
- DRIVER DRIFT, recorded not assumed: inferswarm03 driver is now 615.71.09
  (was 610.57.04 at R8-B/R8-C freeze); 01/04 remain 610.57.04.
  Applicability audit: the candidate comparison is reference-vs-candidate
  under the SAME binaries/model bytes, and the reference arm executes
  entirely on inferswarm01 (driver 610.57.04 unchanged); the changed
  variable remains the RPC execution path. 03 hosts ggml-rpc-server
  backends only (no sampler/argmax logic executes there — sampling runs in
  the client llama-server process). The driver version on an RPC-backend
  host does not participate in the sampler contract or the comparator; it
  is recorded as a fresh mutable identity per Issue #195 Phase 0 item 5.
- inferswarm03 GPU1 (GPU-a57bd3fb) PCIe link still 4x width (max 16x);
  inferswarm04 3090 max link gen 2 — same as R8-C observation.

Sampler contract (Phase 1 — frozen before any distributed output)
-----------------------------------------------------------------
Canonical request (both arms, all cases):
  {"samplers": ["top_k"], "top_k": 1, "temperature": 0.0, "seed": 0,
   "cache_prompt": false, "stream": false, "return_tokens": true,
   "n_predict": 8}   (+ prompt = exact accepted token IDs per case)

Mechanical source proof at b29c606e (see evidence/sampler-contract/):
1. "top_k" resolves in common_sampler_types_from_names canonical map
   (common/sampling.cpp:835); "greedy" is absent — the R8-B defect class.
2. common_sampler_chain_init builds [top_k(k=params.top_k), dist(seed)]
   and adds NOTHING else for this request (no implicit penalties/
   temperature/grammar; the default-chain fallback is not taken because
   the samplers list resolves non-empty).
3. llama_sampler_top_k_apply with k=1: k=min(1,size); descending
   partial_sort; cur_p->size = 1 — support reduced to exactly the argmax
   token BEFORE the terminal draw.
4. llama_sampler_dist_apply with cur_p->size==1: selected=0
   deterministically; the RNG is drawn once only to keep state aligned
   with backend sampling; probabilities are NOT consulted. The terminal
   dist therefore cannot widen or randomize the single-admissible-token
   support. Terminal chain "logits -> top-k -> dist" is TRUE GREEDY.
5. tools/server/server-schema.cpp parses top_k as field_num with limits
   [0, INT32_MAX] — request value 1 preserved exactly; samplers[] parsed
   via common_sampler_types_from_names.
6. The server n_probs surface is NOT used as a decision oracle (R8-C
   limitation honored; no n_probs in any R8-D correctness-bearing request).

Experiment matrix (frozen)
--------------------------
Phase 1  sampler-contract proof: live-server log evidence on the pinned
         build (no unresolved-sampler warning; chain "logits -> top-k ->
         dist"), negative controls: samplers=["greedy"] (must reproduce
         the unresolved-name warning and be classified noncanonical),
         top_k>1 (must be classified NOT true-greedy), missing chain
         evidence (BLOCKED).
Phase 2  reference: single-host non-RPC llama-server on inferswarm01
         (accepted R8-B reference placement: local CUDA0+CUDA1 + CPU
         spill, PLE lazy host-side), 4 cases x >=3 clean repeats,
         byte-identical token IDs + stop semantics required before freeze.
Phase 3  candidate: accepted 5-device topology (client 01 + RPC 03 x2 +
         04), same frozen request, 4 cases; exact equality vs frozen
         reference required per case; first divergence retained for
         diagnostics only.
Phase 4  restart: sentinels case-256 + case-4096; >=3 candidate repeats;
         terminate client+RPC processes; prove PIDs gone; relaunch same
         binaries/config; mechanically re-prove sampler contract; rerun;
         exact equality to pre-restart candidate outputs (and to reference
         for PASS).
Phase 5  accounting: reuse R8-B contract (mmap/RSS, PLE placement,
         device-local weights, KV/GDN/QSA/recurrent state, workspace,
         RPC client/server memory, GPU before/ready/during, transfer
         bytes/time, steady-state network, anomalous mirrors,
         fallback/wrong-device/source anomalies). File-backed mmap is NOT
         an anonymous mirror.

STOP conditions
---------------
- Sampler contract unprovable on the pinned build -> R8D_EVIDENCE_BLOCKED
  before distributed output.
- Reference non-deterministic under true greedy -> R8D_EVIDENCE_BLOCKED;
  no after-the-fact comparator.
- Valid candidate mismatch -> R8D_..._QUALIFICATION_FAIL; no repair/tune/
  rerun under the same authority to convert FAIL to PASS.

Non-goals (Issue #195 explicit): no llama.cpp revision change/repair, no
AMD/Vulkan/mixed-vendor, no Qwen serving integration, no planner change,
no quantization change, no MTP/multimodal, no local-model-backing
optimization, no production-readiness claim, no weakening exact-token
equality after observing divergence.
