METHODOLOGY — R8-I3B runtime-boundary localization diagnostic (Issue #250)
===========================================================================

FROZEN 2026-09-25, BEFORE any Issue #250 physical execution. This
document freezes the discriminator methodology prospectively. The
accepted #241 terminal `R8I3_COMPARATOR_V2_BLOCKED` and the accepted
#248 terminal `R8I3_REF_NONDETERMINISM_UNRESOLVED` are READ-ONLY
inputs; comparator/2 methodology is NOT changed by anything here.

0. Subject, authority, and inputs (exact, read-only)
----------------------------------------------------
- Accepted main authority: bc71774dc68e7d7fddaf97bd794bbbc297e66ca5
  (merge of PR #249).
- Accepted #248 result head: a2cf9f33d1a056f2eef062b4186c078262e66f63;
  adjudication comment 5838156612; terminal
  R8I3_REF_NONDETERMINISM_UNRESOLVED.
- Accepted #248 external evidence root:
  inferswarm01:/home/hermes/is248-campaign/evidence/ (534-row
  SHA256SUMS, self-digest af9dfd0f08e9d3c4cbeb8fe164f781bc64b488ad
  4aba23954f5893ac980ab3bc). Consumed as-is; never re-executed.
- Host: inferswarm01. Reference arm B: NVIDIA RTX 3060, BDF
  00000000:03:00.0, GPU-UUID GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55,
  driver 610.57.04, nvidia ICD, Vulkan 1.4.341.
- Model: /srv/models/qwen38-ud-iq1-s/ (three split GGUF members;
  frozen sha256 set identical to #241/#248 authority).
- llama.cpp pin b29c606e28a01b1bc8c1351026a0fae616bf6c4; accepted
  binaries: canonical 21707f25…, r8e-obs dcee5bcf…, comparator
  6f8b56bd… (the comparator build is the diagnostic default; the
  observer seam is already proven non-perturbing by #248).
- Cases: accepted historical excluded fixture ladder (sha 419bde66…):
  case-256, case-1024, case-3072. case-4096 is OUT OF SCOPE for #250
  (no preauthorization path exists in the tooling; refused outright).
- Request contract: BYTE-EXACT accepted #241 contract
  (scripts/issue250_diagnostic.py REQUEST_CONTRACT). One DECLARED
  extension exists for Arm B only: `id_slot: 3` (see §B).
- Launch shape (unchanged from accepted): one fresh llama-server
  process per request unit; --ctx-size 8192 --batch-size 512; ngl per
  arm; port 19000 (B); CUDA_VISIBLE_DEVICES=-1; nvidia ICD; observer
  env identical to the accepted #248 units.

1. Phase-0 (offline, complete) — source/runtime reconstruction
--------------------------------------------------------------
scripts/issue250_phase0.py (stdlib-only, deterministic) derives, from
the pinned source tree + accepted binaries + retained #248 logs +
read-only host identity observations:
  R1 prompt ingestion (slotting, cache_prompt=false full reset, batch/
     ubatch geometry; server-context.cpp:3288/3444,
     llama-memory-hybrid.cpp:67-99);
  R2 first generation step (decision-0 row = last prompt ubatch
     product; d1–d7 are single-token eval decodes, graphs reused = 7);
  R3 threadpool/threads (OpenMP build; 14-thread default =
     hardware_concurrency()/2 on the 28-LPU host; batched vs
     generation thread selection; per-op chunk claiming with disjoint
     writes; SSM_SCAN head partitioning);
  R4 CPU kernels for non-offloaded layers (IQ1_S IQP panel GEMM,
     q8_K activation quantization with fixed-block K partition,
     per-thread panels; CPU non-flash attention path);
  R5 Vulkan at ngl=1 (i_gpu_start arithmetic: at EVERY tested rung
     1/2/4/6/8 the OUTPUT layer — the full-vocab projection feeding
     every decision row — is the GPU-resident layer; input embedding
     always CPU);
  R6 process init (backend registry enumeration, 14-thread threadpool
     creation, warmup BOS/EOS decode + memory clear + sampler RNG
     reset, empty graph cache; same-process repeats reuse threadpool/
     graph cache/buffers).
Proven runtime controls of the PINNED build (source + --help, never
upstream docs): -dev none (TRUE CPU-only: no GPU backend in the
scheduler at all), -ngl 0 (zero layers offloaded but Vulkan backend
STILL in scheduler with op_offload/KV-offload possible — NOT a pure
CPU control), -t/-tb, -C/--cpu-mask/-Cr, --prio/--poll, --numa,
--no-op-offload, --no-kv-offload, --no-warmup, -b/-u, -ctxcp, -np.

Committed result: evidence/phase0/phase0-analysis.json (re-run is
byte-identical; deterministic, no timestamps).

2. Hypothesis matrix (predeclared, from #248 retained evidence)
---------------------------------------------------------------
H1 Vulkan output-layer GEMM nondeterminism (present at every rung;
   needs length dependence to survive the 256/1024 controls).
H2 CPU-side prefill computation nondeterminism (14-thread OpenMP,
   per-process layout/state; decision-0 row is a prefill product).
H3 Fresh-process initialization variance (layout/ASLR/registry
   order), with same-process repeats deterministic.
H4 Long-context execution-path transition (hybrid-memory ubatch
   geometry/checkpointing/indexer top-k 2048; threshold between 1022
   deterministic and 3077 variable).
H5 Host memory-timing effects — excluded by accepted platform-health
   evidence unless A–D all fail; then report unresolved, never H5.

3. Discriminator arms (minimum geometry, one factor each)
---------------------------------------------------------
Execution order is A → (B if CPU-only varies) → (C if CPU-only still
varies) → (D only if A–C do not localize). Stop early when a boundary
is mechanically localized; never burn repeats to reconfirm a mismatch
(first row mismatch suffices for "nondeterministic"); a DETERMINISTIC
claim requires the predeclared 5 identical repeats.

Namespace d250-arm-a (Vulkan-necessity discriminator; §A):
  - Condition "cpu-only-devnone": the exact accepted case-3072
    workload, binary, model, request, and observation seam, with
    `-dev none` appended to the accepted argv (the PROVEN true
    CPU-only control; -ngl 0 is explicitly NOT used because the
    Vulkan backend remains in the scheduler). ngl token retained as 0
    in receipts for clarity (no layers offloaded).
  - Units: fresh process per unit; 3 repeats minimum; extend to 5
    before calling the condition deterministic; retained full rows
    through the same observer seam.
  - Interpretation (frozen): CPU-only varies ⇒ Vulkan participation
    NOT necessary ⇒ proceed to B. CPU-only deterministic (5/5) while
    the accepted ngl=8 condition remains variable (established by
    #248 5/5 varying fresh pairs; the arm re-establishes 2 fresh
    accepted-condition units only to confirm continued variation
    under today's runtime) ⇒ zero-vs-nonzero Vulkan participation is
    a DEMONSTRATED boundary — but Vulkan itself is NOT called the
    root cause without a smaller mechanism; terminal
    R8I3B_REFERENCE_RUNTIME_BOUNDARY_LOCALIZED names the LOCALIZED
    FACTOR (backend participation boundary), with the smaller
    mechanism left to the follow-up issue per #250 §Decision.

Namespace d250-arm-b (fresh-process/runtime-initialization; §B):
  - Only if CPU-only still varies. Two conditions compared:
    (1) independent fresh processes (5 units, accepted condition);
    (2) ONE controlled process, 5 repeated equivalent requests with
        request/cache-history semantics PROVEN equivalent: the
        pinned server honors per-request `id_slot`; requests carry
        id_slot=3 (the LRU-selected slot of every accepted unit) and
        the accepted cache_prompt=false (source-verified to force
        n_past=0, keep_first(0), full seq_rm(0,-1) wipe → full
        recompute from position 0). The id_slot extension is the one
        DECLARED contract deviation, reviewed here; every other key
        is byte-exact accepted.
  - Reset-equivalence proof retained per unit: server log must show
    slot 3 selected by id, `prompt eval` 3077 tokens each repeat (no
    cache reuse), graphs-reused count increments only within-decode.
  - Interpretation: fresh varies + same-process deterministic ⇒
    process/runtime initialization is a necessary boundary; both vary
    ⇒ C.

Namespace d250-arm-c (CPU-parallelism; §C):
  - Only if CPU-only remains variable. ONE conceptual threading
    regime intervention: `-t 1 -tb 1` (serial CPU regime covering
    prefill AND generation), 5 units, against the accepted/default
    14-thread regime (2 units, same-day reproduction). No other
    batch/NUMA/affinity/scheduling changes. If serial ALSO varies ⇒
    D. (A serial deterministic + default varying result localizes
    CPU parallel execution/order as a necessary boundary.)

Namespace d250-arm-d (long-context transition; §D):
  - Only if A–C do not localize. Predeclared length ladder, SAME
    fixture derivation rule as the accepted ladder (repeated
    sentence block, identical prologue/suffix; lengths 1024, 1536,
    2048, 2304, 2560, 3072 rendered lengths, 2 repeats each,
    accepted placement). The ladder is frozen in
    scripts/issue250_diagnostic.py BEFORE any execution.
  - Goal: earliest repeatable deterministic→variable transition;
    then map that transition to a source/log-identified mechanism
    (graph shape, chunking, kernel/path selection, allocation/init
    boundary). A length threshold without an identified execution
    transition is reported as unresolved, never claimed as causal.

4. Unit retention and custody (unchanged from #248 discipline)
--------------------------------------------------------------
Per unit: full row bytes (8 decisions) via the observer seam, observer
meta, raw HTTP response, server log, identity pre/post, device
samples, process attribution (argv/env/pid), authority snapshot, wall
time (metadata only). Append-only; failed units quarantined as
`-quarantined` siblings before any re-run at the same label. Model
attestation: campaign-level open/close full hashes + cheap per-unit
stat witnesses (never per-unit 72.5 GiB re-hashing). Never select a
favorable repeat; retain failed units.

5. Terminal derivation (mechanical)
-----------------------------------
scripts/issue250_diagnostic.derive_terminal over the retained
reduction; the decision tree is frozen above; incomplete/ambiguous
evidence fails closed to R8I3B_REDUCER_BLOCKED_INCOMPLETE. Neither
terminal qualifies comparator/2.

6. Hard prohibitions (enforced by tooling + tests)
--------------------------------------------------
- no comparator/2 tolerance or acceptance-law change;
- no statistical reference-repeat/noise model implementation;
- no winner-only acceptance; no candidate-tolerance relaxation;
- no predictive c237-* work; no selected-stress threshold work;
- no holdout plaintext/decrypt/secret access; no threshold derivation;
- no R8-J dispatch; no #239 subject binding;
- no rewrite of #241/#248 accepted evidence;
- no candidate GPU qualification; no case-4096 (refused outright);
- no backend substitution AS accepted reference authority (the
  -dev none arm is a DIAGNOSTIC control, explicitly not a new
  reference authority);
- no "try settings until deterministic" (only the frozen arms above);
- no physical execution before maintainer exact-head dispatch.
