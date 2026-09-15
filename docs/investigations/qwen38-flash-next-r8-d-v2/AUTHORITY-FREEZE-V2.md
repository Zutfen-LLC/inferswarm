R8-D v2 authority freeze (corrected campaign)
=============================================

Frozen: 2026-09-15, BEFORE any v2 Phase-2+ correctness-bearing model
output (Issue #195 Phase 0, corrected campaign v2).

Why v2 exists
-------------
v1 (campaign issue195-r8d-true-greedy-requal-v1, terminal
R8D_QWEN38_TRUE_GREEDY_NVIDIA_RPC_QUALIFICATION_FAIL) was superseded:
the maintainer review of PR #197 found (a) the v1 producer retained no
per-case exact request/response bytes, so the exact prompts/requests
executed cannot be mechanically proven, and (b) the v1 reference freeze
relied on an authored `frozen_before_candidate_output: true` boolean
instead of a prospective mechanical freeze. Because correcting the
execution/evidence producer changes correctness-bearing machinery after
candidate output, Issue #195 requires a fresh additive campaign with a
fresh authority freeze before any new correctness-bearing output.

v1 evidence bytes are preserved byte-for-byte under the v1 namespace
(../evidence/, ../MANIFEST.sha256) and are never rewritten. The v1
terminal remains the record of the v1 attempt; the authoritative PR
result is the v2 machine-derived terminal.

Starting point
--------------
- origin/main = f65b70970a9a10bf57bd58a902fe6e08b588c619 (accepted
  R8-C merge, PR #194) — re-verified ancestral at v2 freeze (it is
  still the main head; no applicability audit was triggered).
- Branch: issue-195-r8d-true-greedy-requal.
- v2 correction base: 4e553404bc15fbd6069cdc09a8f3cf70a7d88de1
  (reviewed head 699cd364 + one docs-only commit; reconciled, no
  correctness-bearing delta).

Accepted predecessors (consumed, never rewritten)
-------------------------------------------------
- Issue #191 / PR #192 terminal R8B_QWEN38_NVIDIA_RPC_RUNTIME_QUALIFICATION_FAIL.
- Issue #193 / PR #194 terminal R8C_QWEN38_RPC_DIVERGENCE_CAUSE_LOCALIZED.
- R8-A/B/C MANIFESTs verified byte-exact at v2 freeze.

Runtime/model authority (re-verified fresh at v2 freeze, 2026-09-15)
--------------------------------------------------------------------
- llama.cpp b29c606e28a01b1bc8c1351026a0fa6e616bf6c4 (v0.4.1); binaries
  at /home/hermes/llama.cpp/build-v041/bin re-hashed fresh on
  inferswarm01/03/04 (see evidence/host-inventory/): llama-cli
  3f6b0ed4..., llama-server de3a8a54..., ggml-rpc-server a897f908... —
  byte-identical to the accepted R8-B/R8-C/v1 pins.
- Model: /srv/models/qwen38-ud-iq1-s on inferswarm01; all three GGUF
  member sha256 re-hashed fresh at v2 freeze
  (evidence/split-identity/raw-sha256sum.txt + split-rehash.json);
  all match R8-A pins; total 72,546,461,344 bytes asserted.

Fresh raw host inventory (retained verbatim, evidence/host-inventory/)
----------------------------------------------------------------------
Per host: hostname, UTC timestamp, uname, ip addr, llama/rpc process
census (clean on all three hosts), the three binary hashes, full
nvidia-smi -q (+ XML), and CSV uuid/BDF/mem/driver/link query.
- GPU UUID/BDF set on all three hosts IDENTICAL to the accepted R8-B
  topology (5 CUDA devices). GPUs idle at freeze.
- Driver drift on inferswarm03 (615.71.09 vs 610.57.04 elsewhere)
  recorded; same applicability audit as v1 applies (reference arm
  executes wholly on inferswarm01, driver unchanged; 03 hosts RPC
  backends only — sampling runs in the client llama-server process).

Sampler contract (unchanged semantics from v1 Phase 1; frozen)
--------------------------------------------------------------
Canonical request (both arms, all cases), deterministically serialized
(sorted keys, compact separators, ASCII) by the v2 producer:
  {"samplers":["top_k"],"top_k":1,"temperature":0.0,"seed":0,
   "cache_prompt":false,"stream":false,"return_tokens":true,
   "n_predict":8}  + prompt = exact accepted R8-B token IDs per case.
Forbidden keys (never present in any correctness-bearing request):
n_probs, probs, min_p, top_p, typical_p.
Source proof at pinned b29c606e is unchanged from the accepted v1
AUTHORITY-FREEZE.md (top_k resolves canonically; chain top-k(1) reduces
support to one token before the terminal dist draw; server field_num
parsing preserves top_k=1). Live probes are re-executed per arm for v2.

v2 producer set (pinned at this freeze; producer-hashes.json)
-------------------------------------------------------------
scripts/issue195_v2_authority.py        frozen constants (this freeze)
scripts/issue195_v2_run_ladder.py       byte-exact ladder producer
scripts/issue195_v2_freeze_reference.py prospective reference freeze
scripts/issue195_v2_terminal_reduction.py machine terminal reduction
scripts/issue195_v2_negative_controls.py differential controls
scripts/issue195_v2_manifest.py         v2 manifest builder
scripts/issue195_v2_launch.py           launch/pid-proof helper
scripts/issue195_sampler_probe.py       probe (unchanged v1 producer,
                                         byte-identical, reused)

Evidence contract (v2, per case and repeat)
-------------------------------------------
Every run record retains: exact case_id; complete prompt token ID array
sent; prompt token count; sha256 of the prompt-token representation;
fixture-ladder sha256 observed at execution; exact serialized request
body bytes (base64) + sha256; exact raw response body bytes (base64) +
sha256; comparator fields parsed FROM the retained raw bytes; UTC
start/end timestamps; campaign ID; producer sha256; git HEAD and
clean/dirty state. Response parsing uses only the retained raw bytes
(no second stream).

Reference-freeze contract (prospective, mechanical)
---------------------------------------------------
1. reference arm runs 3x (4 cases each) with the v2 producer;
2. issue195_v2_freeze_reference.py freeze validates + writes
   frozen-reference.json (captured request/response digests per repeat,
   parsed outputs, run-file digests, determinism proof);
3. the reference-freeze commit adds ONLY reference evidence +
   frozen-reference.json (+ v2 manifest) and is PUSHED;
4. issue195_v2_freeze_reference.py pin writes REFREEZE.json recording
   the pushed refreeze commit and frozen-reference sha256;
5. the candidate producer fails closed unless: worktree clean; HEAD ==
   refreeze commit or a descendant with no correctness-bearing diffs;
   frozen-reference digest == pin; producer pins green. Every candidate
   execution record embeds refreeze_commit + frozen_reference_sha256.
The reducer independently re-proves: refreeze commit tree contains the
pinned frozen-reference bytes; refreeze commit is an ancestor of every
candidate run's recorded git_head; gate fields match the pin.

Restart contract: sentinels case-256 + case-4096; candidate PIDs (and
RPC backend PIDs) terminated by exact PID; death proven before
relaunch (restart-pid-proof.json); same binaries/config relaunch;
sampler contract re-proven; sentinels re-run; exact equality to
pre-restart candidate outputs required.

Experiment matrix, STOP conditions, terminals, and non-goals are
unchanged from the accepted v1 freeze (see ../AUTHORITY-FREEZE.md).
Terminal semantics correction (v2): BLOCKED only when a group-A
prerequisite prevents valid distributed correctness execution; once a
valid candidate correctness run exists, any failed invariant
(token/stop/placement/topology/restart/sampler/accounting/freeze) is a
qualification FAIL; a generated mismatch may never be relabeled BLOCKED.

Pin-file exemption (freeze amendment, pre-candidate)
----------------------------------------------------
The REFREEZE.json pin file is by contract authored in the commit
immediately AFTER the pushed reference-freeze commit (it records that
commit's SHA, which cannot be known before pushing). Both the candidate
fail-closed gate and the reducer's ancestry check therefore exempt
exactly one path — v2/evidence/reference/REFREEZE.json — from the
"no correctness-bearing changes after the reference freeze" rule. Every
other correctness-bearing path remains fail-closed. The reference arm
was re-run under the amended producers before the amended freeze (the
producer bytes changed after the first v2 authority freeze, so the
first v2 reference attempt was superseded intra-v2; no candidate output
existed at any point during that supersession).
