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

FROZEN PREFIX POPULATION LAW (correction pass 3, NO-GO 5847890177
blocker 2; machine-enforced by `prefix_population_facts` in
scripts/issue250_diagnostic.py and the retained-byte reducer):
  - A condition is a COMPLETE NONDETERMINISTIC population when the
    retained units form a contiguous prefix from unit 001, at least
    two valid units exist, the first row-digest mismatch appears
    within that retained prefix, and execution STOPPED at the first
    mismatch (only already-in-flight units under the frozen batch
    rule are excused). The unexecuted planned tail is NOT missing
    evidence.
  - A DETERMINISTIC claim requires ALL predeclared units retained
    and identical (5 where the arm freezes 5). Three identical units
    are incomplete, never deterministic.
  - INVALID (fail closed): gaps inside the retained prefix (001+003),
    execution past the declared stop point, cherry-picked subsets,
    quarantined-result substitution, retained later units omitted
    from reduction, duplicates, malformed tag/index ordering.
  - For Arm-B same-process, a TRUNCATED lifecycle (authority/process/
    error loss) is an INCOMPLETE population — distinct from a valid
    mismatch-triggered stop; the reducer derives the stop reason
    mechanically from retained rows/custody and never trusts a
    producer stop claim.

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
  - NONZERO-VULKAN CONTRAST (frozen rule, correction pass 2): the
    nonzero-Vulkan side of the Arm-A comparison is the ACCEPTED #248
    RETAINED `ngl=1` case-3072 result (`d248-placement-rungs`
    units `case-3072-B-ngl1-001/002`, dispatched under PR #249 at
    head 3f36ef1a, retained under the #248 evidence root whose
    534-row SHA256SUMS self-digests to af9dfd0f…), consumed as
    READ-ONLY contrast authority with digest/provenance verification
    (scripts/issue250_terminal.verify_historical_contrast: manifest
    self-digest, per-file digest rows, unit head/namespace/PR/issue
    binding, row nondeterminism re-derived from the retained row
    bytes). At ngl=1 — the minimal nonzero Vulkan participation
    already established by #248, where only the output layer is
    GPU-resident — the retained rows VARY across fresh processes.
    This is historical authority, never fresh #250 execution and
    never represented as such; no `ngl=8` accepted-condition
    reproduction exists anywhere in Issue #250, and no fresh ngl
    comparator units are planned.
  - Interpretation (frozen): CPU-only varies ⇒ Vulkan participation
    NOT necessary ⇒ proceed to B. CPU-only deterministic (5/5) while
    the accepted ngl=1 contrast remains variable ⇒ zero-vs-nonzero
    Vulkan participation is a DEMONSTRATED boundary — but Vulkan
    itself is NOT called the root cause without a smaller mechanism;
    terminal R8I3B_REFERENCE_RUNTIME_BOUNDARY_LOCALIZED names the
    LOCALIZED FACTOR (backend participation boundary), with the
    smaller mechanism left to the follow-up issue per #250 §Decision.

Namespace d250-arm-b (fresh-process/runtime-initialization; §B):
  - Only if CPU-only still varies (correction pass 2: B INHERITS
    Arm A's CPU-only condition). Both conditions run `-dev none`;
    no Vulkan device backend is reintroduced. The only conceptual
    factor changed is process/runtime lifetime:
    (1) independent fresh CPU-only processes (5 units,
        `case-3072-B-cpu-fresh-00N`);
    (2) ONE controlled CPU-only process, 5 repeated equivalent
        requests with request/cache-history semantics PROVEN
        equivalent: the pinned server honors per-request `id_slot`;
        requests carry id_slot=3 (the LRU-selected slot of every
        accepted unit) and the accepted cache_prompt=false
        (source-verified to force n_past=0, keep_first(0), full
        seq_rm(0,-1) wipe → full recompute from position 0). The
        id_slot extension is the one DECLARED contract deviation,
        reviewed here; every other key is byte-exact accepted.
        Executed by the dedicated same-process lifecycle producer
        (`scripts/issue250_physical.run_same_process_lifecycle`):
        one server launch, one shared PID, per-request rows/
        responses/log slices, one shared identity/health record;
        five separate processes CANNOT satisfy this arm.
  - PER-REQUEST LIVE AUTHORITY GATE (correction pass 3, NO-GO
    5847890177 blocker 1): every completion request begins under
    CURRENT authority — a live revalidation runs through the
    canonical #250 fetch path immediately before EACH request, and
    every observation must cross-bind to the SAME original dispatch
    generation (same comment ID, head, namespace, arm, author
    association, created-at, body digest). A drift before request N
    stops the lifecycle BEFORE request N issues: no later request
    executes, the completed prefix stays retained append-only, and
    the lifecycle is marked incomplete (fail-closed); the server
    process being already running NEVER excuses a failed gate.
  - Reset-equivalence proof retained per request (re-derived by the
    reducer from the retained log slice), TASK-BOUND to the current
    request (correction pass 3, NO-GO 5847890177 blocker 3): the
    proof must show slot 3 selected BY ID, exactly ONE fresh task
    launched on slot 3 after that selection (task id not consumed by
    any earlier request of this lifecycle), and a `prompt eval` line
    for THAT task covering the full 3077 tokens (no cache reuse).
    Delayed evidence from request N−1's task can never certify
    request N. Grammar basis: pinned SLT_INF log prefixes
    (`slot <fn>: id N | task M |`), where selection lines carry the
    structural `task -1` and launch/timing lines carry the real task
    id; task ids come from the pinned monotonic counter and are NOT
    request-index-equal (health/next-response tasks consume the same
    counter), so the producer DISCOVERS the task id from the log and
    the reducer re-derives it.
  - Interpretation: fresh varies + same-process deterministic ⇒
    process/runtime initialization is a necessary boundary; both vary
    ⇒ C. If fresh-process CPU-only evidence turns deterministic in
    Arm B after Arm A varied, the cross-arm contradiction fails
    closed to R8I3B_REDUCER_BLOCKED_INCOMPLETE (frozen rule).

Namespace d250-arm-c (CPU-parallelism; §C):
  - Only if CPU-only remains variable after B. INHERITS the CPU-only
    `-dev none` condition (correction pass 2: no Vulkan device
    backend is reintroduced). ONE conceptual threading regime
    intervention: `-t 1 -tb 1` (serial CPU regime covering prefill
    AND generation), 5 units (`case-3072-B-cpu-thr1-00N`), against
    the default 14-thread CPU-only regime (2 reproduction units,
    `case-3072-B-cpu-thr-default-00N`; the default condition's
    VARIATION is already established by the A/B fresh CPU-only
    units of the same geometry). No batch/ubatch/NUMA/affinity/
    polling/priority/warmup/request/model changes. If serial ALSO
    varies ⇒ D. (Serial deterministic + default varying localizes
    CPU parallel execution/order as a necessary boundary.)

Namespace d250-arm-d (long-context transition; §D):
  - Only if A–C do not localize. Predeclared length ladder, SAME
    fixture derivation rule as the accepted ladder (repeated
    sentence block, identical prologue/suffix; lengths 1024, 1536,
    2048, 2304, 2560, 3072 rendered lengths, accepted placement).
    The ladder is frozen in scripts/issue250_diagnostic.py BEFORE
    any execution.
  - TOKEN-COUNT AUTHORITY (correction pass 3, NO-GO 5847890177
    blocker 4A): the ladder labels are TEXT GENERATION PARAMETERS
    (sentence-repeat counts), NOT token lengths. BEFORE any physical
    Arm-D execution, every predeclared prompt is tokenized through
    the pinned-server `/tokenize` authority (the same tokenizer the
    pinned /completion path uses; the derivation launches the
    accepted binary ONCE and serves ONLY /tokenize requests —
    tokenization is not diagnostic execution), and the receipt is
    retained append-only per length: nominal label, sentence-repeat
    count, prompt text digest, token ids (or authoritative
    token-count receipt), actual token count. The producer binds
    the runtime/server prompt-eval count to that actual count; the
    reducer uses the ACTUAL token count (never the nominal label)
    for any token-count mechanism (indexer top_k = 2048), and BLOCKS
    a length whose runtime prompt-eval count disagrees with the
    retained tokenizer authority. If the actual counts do not
    bracket/cross a frozen mechanism threshold as intended, the D
    predicate is reported unavailable/unresolved — no retrospective
    length retrofit after observing outcomes (a prospective frozen
    amendment requires review before execution).
  - SCREENING + ADAPTIVE CONFIRMATION (correction pass 3, NO-GO
    5847890177 blocker 4C): 2 screening repeats per length are a
    bracketing observation ONLY — two equal rows are
    `pair_identical`, NOT a deterministic condition. A D LOCALIZED
    claim whose deterministic side is the last deterministic length
    requires the frozen deterministic-confirmation count (5 total
    identical repeats) for exactly that boundary-adjacent condition,
    obtained through the PREDECLARED confirm-extension units
    (`-003-confirm`..`-005-confirm`, frozen in the plan before any
    execution); unrelated ladder points are never extended. A first
    mismatch at ANY point (including inside the confirmation
    extension) immediately establishes variability.
  - Goal: earliest repeatable deterministic→variable transition;
    then map that transition to a source-proven mechanism. A length
    threshold without an identified execution transition is
    reported as unresolved, never claimed as causal. The frozen
    transition predicates (blocker 4B) are:
    (a) `indexer_top_k_boundary` — the boundary between the last
        deterministic and first variable length, measured in ACTUAL
        token counts, equals the qwen4exp indexer top_k crossing
        (model-architecture fact, phase0 MODEL_ARCH_FACTS);
    (b) `midstream_ubatch_split` — retained cumulative prompt-
        progress counts show a strictly sub-batch (512) step
        STRICTLY BETWEEN two continuing rungs (the hybrid-memory
        rollback-tail grouping signature; an ordinary final
        remainder terminates the sequence and cannot satisfy it),
        present at every variable length and absent at every
        deterministic length.
    The retired `checkpoint_resegmentation` and
    `ubatch_geometry_split`/non-uniform-progress predicates are
    UNSOUND from pinned source (checkpoint evidence logs at DBG
    only — absent under the frozen non-verbose launch shape;
    progress lines are 3s wall-clock samples, not ubatch
    boundaries) and are removed from the vocabulary.

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
scripts/issue250_terminal.derive_terminal(evidence_root, head) — the
retained-byte reducer (correction pass 2): re-derives every
conclusion from retained unit receipts, raw responses, observer
rows/metadata, server logs, identity pre/post, platform-health
receipts, campaign attestations, and the live dispatch-authority
binding. Caller-supplied determinism/factor/terminal/condition
values are not inputs. The sequential A→B→C→D reachability law and
the frozen Arm-D transition predicates are enforced mechanically;
incomplete/ambiguous evidence fails closed to
R8I3B_REDUCER_BLOCKED_INCOMPLETE. Neither terminal qualifies
comparator/2.

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
