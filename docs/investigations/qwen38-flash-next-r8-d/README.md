R8-D — Qwen3.8-Flash-Next UD-IQ1_S true-greedy NVIDIA cross-host RPC
requalification (Issue #195)

Terminal: R8D_QWEN38_TRUE_GREEDY_NVIDIA_RPC_QUALIFICATION_FAIL
(machine-derived by scripts/issue195_terminal_reduction.py)

Summary
-------
Reran the R8-B NVIDIA cross-host RPC qualification under a sampler
contract mechanically proven to be true greedy (argmax) before candidate
output. The R8-C root cause — samplers=["greedy"] never resolving at
llama.cpp b29c606e, silently degrading both arms to seeded distribution
sampling — is now impossible to repeat silently: the canonical request
samplers=["top_k"], top_k=1 was proven live on BOTH arms (chain
"logits -> top-k -> dist", zero unresolved-sampler warnings), with
negative controls proving legacy "greedy" is rejected as noncanonical
(unresolved-name warning reproduced) and top_k>1 can never be labeled
true greedy.

Result: the corrected sampler contract materially improved agreement —
cases 1024 and 3077 became exact-token/exact-stop PASSes (both were FAILs
under seeded dist in R8-B) — but two cases still diverge:

- case-256: common prefix positions 0-4, divergence at position 5
  (candidate 34227 vs reference 271). Deterministic 3x, restart-stable.
- case-4096 (4097 prompt tokens): candidate emits immediate EOS
  (token 248046 = <|im_end|>, stop_type=eos after complete prefill of
  all 4097 prompt tokens, ~26-28 s) while the reference generates the
  full 8-token continuation. Deterministic 3x, restart-stable.

This is a valid FAIL under the frozen comparator: no repair, no
comparator weakening, no selective rerun, no runtime change after
output. The accepted R8-B FAIL remains immutable; nothing here
retroactively converts it.

Mechanical true-greedy proof (Phase 1)
--------------------------------------
Source proof at pinned b29c606e (see AUTHORITY-FREEZE.md):
common_sampler_types_from_names resolves "top_k" (canonical map);
common_sampler_chain_init builds [top_k(k), dist(seed)] and adds nothing
else; top_k apply with k=1 descending-partial-sorts and sets size=1
before the terminal draw; dist apply with size==1 deterministically
selects element 0 (RNG drawn once only for state alignment;
probabilities not consulted). The server parses top_k via field_num
(limits [0, INT32_MAX]) — value 1 preserved exactly.
Live proof (retained probe JSONs + server logs): reference, candidate,
AND post-restart candidate all classify canonical=TRUE_GREEDY_PROVEN,
legacy=NONCANONICAL_LEGACY_GREEDY (warning reproduced), wide=NOT_TRUE_GREEDY.
The server n_probs surface was never used as a decision oracle (R8-C
limitation).

Arms
----
Reference (frozen before candidate output): accepted R8-B placement —
single-host llama-server on inferswarm01 (local CUDA0+CUDA1 auto-fit +
CPU spill, PLE lazy host-side 27465.95 MiB), port 8321. 4 cases x 3
repeats, byte-identical tokens+stops; frozen-reference.json retained.

Candidate: accepted 5-device topology — llama-server client on
inferswarm01 (2x RTX 3060) + ggml-rpc-server on inferswarm03 (2x RTX
3060, ports 50052/50053) + inferswarm04 (RTX 3090, port 50052). RPC
buffer placement from load log: 6796.90 + 7761.99 + 6796.90 (03) +
13493.79 (04) + 6518.70 + 6796.90 (01 local CUDA; see
candidate/cand-server.log) = 41368 MiB backbone across 5 devices; PLE
host-resident client-side (lazy read enabled, both arms). 4 cases x 3
repeats, deterministic; restart control: processes killed by exact PID,
relaunched same binaries/config, sampler contract re-proven, sentinels
(case-256, case-4096) restart-identical.

Frozen request contract (both arms, all cases)
----------------------------------------------
{"samplers": ["top_k"], "top_k": 1, "temperature": 0.0, "seed": 0,
 "cache_prompt": false, "stream": false, "return_tokens": true,
 "n_predict": 8} + prompt = exact accepted R8-B token IDs (fixture
ladder sha256 419bde66...822db, byte-identical on the executing host,
proven in reducer check fixture_identity_exact).

Identity (re-verified fresh at freeze)
--------------------------------------
- llama.cpp b29c606e28a01b1bc8c1351026a0fa6e616bf6c4 (v0.4.1);
  binaries byte-identical on 01/03/04 and to accepted R8-B/R8-C pins.
- UD-IQ1_S 3-member split: full sha256 == accepted R8-A pins; total
  72,546,461,344 bytes.
- 5 GPU UUID/BDF identities identical to accepted topology; driver
  drift on inferswarm03 (610.57.04 -> 615.71.09) recorded in fresh raw
  host inventory and applicability-audited (reference arm executes
  wholly on unchanged-driver 01; 03 hosts RPC backends only — no
  sampler logic executes there; sampling runs in the client process).
- Fresh raw host inventory retained per host (nvidia-smi -q + XML,
  uname, ip, process census, binary hashes) — the R8-B retention gap
  is not repeated.

Accounting (Phase 5)
--------------------
Client RSS 25.4 GB dominated by file-backed Private_Clean 25.1 GB
(mmap of the GGUF members) — NOT an anonymous persistent host mirror;
Anonymous only ~244 MB. Per-device GPU residency: 01 CUDA0 6911 MiB /
CUDA1 6633 MiB; 03 GPU0 7875 MiB / GPU1 6911 MiB; 04 13760 MiB.
RPC-server host RSS 0.3-0.8 GB each (compute/staging buffers only).
Raw observations retained under evidence/accounting/. Network figures
(descriptive only): candidate load window ~5.3 min (log-timestamp
derived; the RPC-resident backbone ~41.4 GiB is what crosses the
network — no byte-count or link-speed observation was retained, so no
transfer-volume figure is claimed); steady-state per-case wall times
retained in run JSONs (e.g. case-4096 ~28 s prefill-dominated).

Negative controls
-----------------
13 controls, all fail-closed (evidence/negative-controls/): candidate
token mutation, GGUF member hash change, binary hash change, GPU UUID
change, missing sampler-chain evidence, top_k>1 mislabel, legacy
'greedy' mislabel, request mutation after freeze, restart drift,
post-hoc reference rewrite, authored-PASS contradiction (structural),
predecessor MANIFEST mutation (structural), bare-constant composer
trap (AST). The server n_probs surface is not consumed by any
correctness-bearing check.

Non-claims
----------
No AMD/Vulkan/mixed-vendor execution; no llama.cpp repair or revision
change; no InferSwarm planner/ordinary-serving integration; no
production readiness; no inference from this FAIL to all llama.cpp RPC
configurations; the FAIL is scoped to the pinned build b29c606e, pinned
UD-IQ1_S bytes, frozen 5-device NVIDIA topology, text-only, single
slot, exact fixture ladder, true-greedy contract. Successor work
(residual near-tie divergence, local model backing) requires fresh
issues.

Evidence layout
---------------
AUTHORITY-FREEZE.md  (frozen before any Phase 2+ output)
terminal-reduction.json, MANIFEST.sha256, producer-hashes.json
evidence/host-inventory/   (3 raw inventories + 3 nvidia-smi XML)
evidence/split-identity/    (raw sha256sum + split-rehash.json)
evidence/sampler-contract/  (sampler-probe-ref.json)
evidence/reference/         (ref-server.log, ref-run-{1,2,3}.json,
                             frozen-reference.json)
evidence/candidate/         (cand-server.log, cand-run-{1,2,3}.json,
                             cand-server-restart.log,
                             cand-restart-case-{256,4096}.json,
                             sampler-probe-cand{,-restart}.json)
evidence/accounting/        (raw residency captures, rpc logs,
                             launch scripts)
evidence/negative-controls/ (negative-controls.json)
