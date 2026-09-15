R8-D v2 — Qwen3.8-Flash-Next UD-IQ1_S true-greedy NVIDIA cross-host RPC
requalification, corrected campaign (Issue #195, PR #197 correction)

Terminal (machine-derived by scripts/issue195_v2_terminal_reduction.py):

R8D_QWEN38_TRUE_GREEDY_NVIDIA_RPC_QUALIFICATION_FAIL

Why v2 supersedes v1
--------------------
The maintainer review of PR #197 (reviewed head 699cd364) found the v1
evidence contract could not mechanically prove (a) the exact
prompts/requests executed — the v1 producer retained parsed fields
only, not request/response bytes — and (b) that the reference was
frozen before candidate execution — v1 relied on an authored
`frozen_before_candidate_output: true` boolean. Because correcting the
execution/evidence producer changes correctness-bearing machinery after
candidate output, v1 is superseded by this fresh additive campaign with
a fresh authority freeze. v1 evidence bytes remain byte-for-byte under
../qwen38-flash-next-r8-d/ (MANIFEST-verified by the v2 reducer's
v1_evidence_byte_preserved check); the v1 terminal remains the record
of the v1 attempt and is never rewritten.

Mechanical prospective reference freeze (the v1 defect, corrected)
------------------------------------------------------------------
1. v2 authority freeze commit 5f64ca7 (producers, authority, tests,
   fresh identity evidence) pushed BEFORE any v2 model output.
2. Reference arm executed 3x; sampler contract proven on the reference
   BEFORE the freeze.
3. Reference-freeze commit 00f334a (reference runs + frozen-reference
   + manifest) PUSHED before any candidate process existed.
4. REFREEZE.json pin (commit 4eb9d43) records refreeze commit
   00f334a + frozen-reference sha256
   494715b986cd372a75434f0d54b33eb8c285a75e75beff22295e78aea1f31a30.
5. The candidate producer fails closed unless: worktree clean; HEAD ==
   pin/refreeze commit or descendant with no correctness-bearing diffs
   (only the REFREEZE.json pin path exempted); frozen-reference digest
   == pin; producer pins green. Every candidate execution record
   embeds refreeze_commit + frozen_reference_sha256.
6. The reducer re-proves from retained history: refreeze commit tree
   contains exactly the pinned frozen-reference bytes; refreeze commit
   is an ancestor of every candidate run's recorded git_head; gate
   fields equal the pin; executing producer sha equals the repo pin.
An intra-v2 supersession occurred BEFORE any candidate output: the
first reference attempt (freeze 7cfc261, pin dbac601) was superseded
when the gate needed a pin-file exemption amendment; the reference arm
was re-executed under the amended producers (history preserved).

Execution evidence (the v1 defect, corrected)
---------------------------------------------
Every case record (reference, candidate, restart) retains: exact
case_id; complete prompt token ID array; prompt count + sha256;
fixture-ladder sha256 observed at execution; exact serialized request
body bytes (base64) + sha256 (deterministic: sorted keys, compact
separators, ASCII); exact raw HTTP response body bytes (base64) +
sha256; comparator fields parsed FROM the retained bytes; UTC
start/end; campaign; producer sha256; git HEAD + clean state. No
forbidden keys (n_probs/probs/min_p/top_p/typical_p) in any request.

Physical result (v2, machine-derived)
-------------------------------------
Frozen reference (4 cases x 3 repeats, byte-identical) vs distributed
5-device candidate (4 cases x 3 repeats, deterministic):
- case-1024 (1022 tokens): EXACT token + stop equality.
- case-3072 (3077 tokens): EXACT token + stop equality.
- case-256: common prefix positions 0-4; divergence at position 5
  (candidate 34227 vs reference 271). Restart-stable, deterministic.
- case-4096 (4097 tokens): candidate emits immediate EOS (248046 =
  <|im_end|>) after complete prefill of all 4097 tokens (~28 s) while
  the reference generates the full 8-token continuation. Restart-
  stable, deterministic.
This is a valid FAIL under the frozen comparator: no repair, no
comparator weakening, no selective rerun, no runtime change after
output. (v1 observed the same qualitative pattern; v2 did not assume
it — case-4096 was re-executed fresh.)

Sampler contract (both arms, before any correctness output)
-----------------------------------------------------------
canonical (top_k=1): TRUE_GREEDY_PROVEN — chain "logits -> top-k ->
dist", zero unresolved-sampler warnings, on reference, candidate, AND
post-restart candidate. legacy (samplers=["greedy"]):
NONCANONICAL_LEGACY_GREEDY — the R8-B defect class: unresolved-name
warning reproduced, never accepted. wide (top_k=4): NOT_TRUE_GREEDY.
Server n_probs never used as a decision-row oracle (R8-C limitation).

Restart control
---------------
4 processes (candidate client + 3 RPC backends) terminated by exact
PID; death proven before relaunch (restart-pid-proof.json); same
binaries/config relaunch; sampler contract re-proven; sentinels
(case-256, case-4096) restart-identical to pre-restart candidate
outputs.

Terminal semantics (corrected per review)
-----------------------------------------
BLOCKED only when a group-A prerequisite prevents valid distributed
correctness execution (e.g. missing pre-output sampler contract). Once
a valid candidate correctness run exists, ANY failed invariant —
token/stop, placement, topology, restart, sampler reproof, accounting,
or post-hoc freeze/evidence tampering — is QUALIFICATION_FAIL. A
generated candidate mismatch can never be relabeled BLOCKED. Proven by
dedicated semantics tests (tests/test_issue195_r8d_v2.py) and
differential controls NC-17..NC-20.

Negative controls (22, all valid)
---------------------------------
Differential method: unmodified baseline first; assert expected
pre-mutation state; exactly one mutation; intended check/terminal must
move; baseline-red invariants rejected unless a purpose-built
synthetic green baseline is used. Correction (PR #197 final pass,
2026-09-15): the control harness now ENFORCES the synthetic-green
precondition — before any mutation is applied to a synthetic-green
campaign the baseline reduction must derive TERMINAL_PASS with every
check green, else the control is invalid and the suite fails
(scripts/issue195_v2_negative_controls.py, control(baseline_must_be_green)).
The sandbox also materializes every repo path referenced by the r8-a/b/c
predecessor manifests AND the superseded v1 manifest, so predecessor
and v1-manifest verification exercise real bytes inside the sandbox.
NC-1 predecessor identity / NC-2 GGUF hash / NC-3 binary hash /
NC-4 GPU UUID / NC-5 legacy-greedy mislabel / NC-6 top_k>1 mislabel /
NC-7 missing chain => BLOCKED / NC-8 request mutation after freeze /
NC-9 wrong prompt IDs / NC-10 topology drift / NC-11 stale PID /
NC-12 frozen-reference token mutation / NC-13 authored PASS ignored /
NC-14 n_probs in request / NC-15 R8-B manifest mutation / NC-16 v1
evidence mutation / NC-17 token mismatch => FAIL (not BLOCKED) /
NC-18 restart failure => FAIL / NC-19 reproof failure => FAIL /
NC-20 placement failure => FAIL / NC-S1 bare-True trap / NC-S2
authored-verdict-never-read.
Baseline terminals of record (regenerated negative-controls.json):
NC-10/NC-12/NC-13/NC-17/NC-18/NC-19/NC-20 run on synthetic PASS
baselines (baseline_terminal == ...QUALIFICATION_PASS, machine-verified
by the precondition assert); NC-17..NC-20 each demonstrate a true
PASS -> FAIL terminal transition; all other controls run on the real
retained FAIL campaign bytes.

Identity (re-verified fresh at v2 freeze, 2026-09-15)
-----------------------------------------------------
- llama.cpp b29c606e28a01b1bc8c1351026a0fa6e616bf6c4 (v0.4.1);
  binaries byte-identical on 01/03/04 and to R8-B/R8-C/v1 pins
  (llama-server de3a8a54..., ggml-rpc-server a897f908...).
- UD-IQ1_S 3-member split re-hashed fresh: all match R8-A pins;
  total 72,546,461,344 bytes (evidence/split-identity/).
- 5 GPU UUID/BDF identities identical to accepted topology; driver
  drift on inferswarm03 (615.71.09) recorded + applicability-audited.
- Fresh host inventories per host (raw + nvidia-smi XML).

Accounting (Phase 5, retained under evidence/accounting/)
---------------------------------------------------------
Candidate client RSS ~1.7 GB (post-restart steady state; dominated by
compute buffers; PLE 27465.95 MiB lazy host-resident), Private_Clean
~289 MB (mmap) — no anomalous anonymous mirror. Per-device GPU
residency: 01 CUDA0 7523 / CUDA1 7233 MiB; 03 GPU0 8321 / GPU1 7473
MiB; 04 14464 MiB. RPC-server host RSS 0.76-0.89 GB each. Backbone
41.4 GiB across the 5 intended devices (RPC buffers 13493.79 + 7761.99
+ 6796.90 + CUDA 6796.90 + 6518.70 from load logs). No wrong-device
or CPU-only fallback.

Non-claims
----------
Unchanged from v1: no AMD/Vulkan, no llama.cpp repair/revision change,
no serving integration, no production readiness, FAIL scoped to the
pinned build/model/topology/fixtures/contract. Successor work requires
fresh issues.

Mainline reconciliation during the campaign (2026-09-15)
-------------------------------------------------------
origin/main advanced AFTER the R8-D v2 campaign's accepted ancestor:
- accepted R8-C ancestor (campaign base): f65b709
  (merge of PR #194, 2026-09-15)
- main advanced to 264aa7e0d428fbdbc37c38fbaa242da804f9155d
  (merge of PR #198 "hardware(#196): refresh living GPU/PCIe inventory
  for Valinor and inferswarm02", committed 2026-09-15T12:48:10-04:00;
  content commit 9cb1970016cacea8a48dcbc68fc8621678892305,
  2026-09-15T12:01:40-04:00).
Changed paths in f65b709..264aa7e (complete set):
  docs/hardware/README.md
  docs/hardware/current-inventory/2026-09-15/README.md
  docs/hardware/current-inventory/2026-09-15/raw/inferswarm02-console.txt
  docs/hardware/current-inventory/2026-09-15/raw/inv-inferswarm01.txt
  docs/hardware/current-inventory/2026-09-15/raw/inv-inferswarm03.txt
  docs/hardware/current-inventory/2026-09-15/raw/inv-inferswarm04.txt
  docs/hardware/current-inventory/2026-09-15/raw/valinor-console.txt
  docs/hardware/pcie-slot-ledger.md
  scripts/ci_groups.json
  scripts/plan_ci.py
  tests/test_plan_ci.py
Applicability disposition: NON-EXECUTION-BEARING. The delta is living
hardware inventory documentation/receipts (read-only scan captures,
deliberately superseded by later refreshes) plus CI planner/test
registration for those receipts. It touches no R8-D execution path,
llama.cpp/model authority, physical topology authority, request
producer, sampler contract, comparator, or retained v2 evidence. The
v2 reducer's topology/identity checks bind to the campaign's own
frozen host inventories under evidence/host-inventory/ (which remain
byte-frozen), not to docs/hardware/current-inventory/. Therefore no
physical rerun is required and none was performed. Reconciled by a
normal merge commit (no rebase; refreeze/candidate git ancestry
preserved); the merge retains both the #195 CI registration and the
mainline #196 registration.
No main commit later than 264aa7e existed at reconciliation time.

Evidence layout
---------------
AUTHORITY-FREEZE-V2.md   (freeze + intra-v2 supersession record)
producer-hashes.json, MANIFEST.sha256, terminal-reduction.json
evidence/host-inventory/   3 raw inventories + 3 nvidia-smi XML
evidence/split-identity/   raw sha256sum + split-rehash.json
evidence/sampler-contract/ sampler-probe-ref.json
evidence/reference/        ref-run-{1,2,3}.json, ref-server.log,
                           frozen-reference.json, REFREEZE.json
evidence/candidate/        cand-run-{1,2,3}.json, cand-server{,-restart}.log,
                           cand-restart-case-{256,4096}.json,
                           sampler-probe-cand{,-restart}.json,
                           restart-pid-proof.json, launch-candidate.sh
evidence/accounting/       client/rpc residency captures, rpc logs
evidence/negative-controls/ negative-controls.json (22 controls)
