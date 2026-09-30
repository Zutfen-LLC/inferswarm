METHODOLOGY AMENDMENT 001 — R8-I3B (Issue #250, PR #251)

CORRECTION PASS 4 — NO-GO comment 5851078451 (blockers 2 and 3).
Implemented at the correction-pass-4 head on branch
issue-250-r8i3b-ref-runtime-boundary; base main unchanged at
bc71774dc68e7d7fddaf97bd794bbbc297e66ca5. Repository-only; zero
physical execution; the frozen METHODOLOGY.md text above is preserved
verbatim and remains the prospective methodology of record except
where explicitly amended below (dated-amendment discipline; frozen
text is never edited in place).

A. TOKEN-AUTHORITY PROCESS ATTRIBUTION (blocker 2)

Original frozen text (§D TOKEN-COUNT AUTHORITY): "the derivation
launches the accepted binary ONCE and serves ONLY /tokenize
requests" and the retained document claims
`authority = pinned_server_tokenize_endpoint`.

Defect: the pass-3 implementation verified only the binary FILE SHA
and then POSTed to http://127.0.0.1:19000/tokenize with no launch,
no PID/process attribution, no /proc/<pid>/exe digest check, no
argv/model binding, and no proof that the listener on port 19000 was
the verified binary with the accepted model. A stale or unrelated
listener could author the token counts while the receipt still
claimed pinned-server authority (proven by old-defect proof at
4becbaaf).

Amended production path (scripts/issue250_physical.py,
`launch_tokenizer_server` + `derive_ladder_token_authority`):
  exact clean head -> exact binary FILE verification -> accepted
  campaign model attestation binding (opening digest + live stat
  witness; the tokenizer authority uses the SAME accepted model
  bytes as the physical campaign) -> target port verified NOT
  occupied by any unknown listener (fail closed; no unrelated
  process is killed to obtain the port) -> ONE llama-server process
  launched under the frozen tokenization geometry
  (`tokenizer_server_argv`: accepted binary, accepted model member,
  -ngl 8, --ctx-size 8192 --batch-size 512, 127.0.0.1:19000, no
  observer hook, no argv delta) -> wait /health -> PID + process
  attribution captured and /proc/<pid>/exe SHA verified == accepted
  binary SHA -> per-prompt process re-attribution -> ONLY /tokenize
  requests (never /completion) for all six predeclared prompts ->
  raw response bytes + digests retained per prompt -> teardown.
The retained document now carries
`authority = attributed_pinned_server_tokenize_endpoint` plus a
`process_attribution` block (schema
`inferswarm.issue250.token-authority-process/1`: head, binary id/SHA,
server PID, executable SHA, exact argv, model dir + launch member,
opening attestation digest, per-member stat witness, tokenizer
semantics declaration). `load_ladder_token_authority` fails closed
on any missing/mutated binding; a synthetic HTTP endpoint alone (or
a test-seam document) is rejected as non-production authority.

B. ARM-D PREDICATE VOCABULARY (blocker 3)

Original frozen text (§D): transition predicate (b)
`midstream_ubatch_split` — "retained cumulative prompt-progress
counts show a strictly sub-batch (512) step STRICTLY BETWEEN two
continuing rungs … present at every variable length and absent at
every deterministic length."

Defect: the retained `prompt processing, n_tokens = …` lines are
~3-second wall-clock samples of one cumulative counter (pinned
server-context.cpp print_timings_pp gate), not ubatch boundary
events. A midstream sub-512 sampled delta cannot mechanically
distinguish an actual scheduler/ubatch split from ordinary
throughput variation, sampling alignment, or pauses between
samples. The methodology itself already stated the sampling law; the
predicate contradicted it.

Amendment: `midstream_ubatch_split` is REMOVED from the
terminal-bearing predicate vocabulary. `_midstream_split_signature`
is demoted to a fail-closed stub (always False) and retained
progress lines are diagnostic metadata only. No instrumentation is
added to preserve the predicate; ubatch geometry is not localizable
in Issue #250 (new instrumentation would require a prospectively
reviewed tooling/head change and fresh exact-head dispatch).

Surviving predicate: `indexer_top_k_boundary` — RETAINED but
RE-BOUND to the source-proven execution-path transition rather than
the bare metadata constant. Pinned-source audit (llama.cpp tree
950999fe, the phase-0 LLAMA_PIN_TREE; src/models/qwen4exp.cpp
`llama_model_qwen4exp::graph::build_qsa_top_k`):
  - controlling runtime condition:
    `width = std::min<int64_t>(n_kv, hparams.indexer_top_k + r - 1)`
    (src/models/qwen4exp.cpp:665) where r is the per-layer compress
    ratio; this model's GGUF carries
    `qwen4exp.attention.compress_ratios` with r = 4 on every QSA
    layer (retained reference-server.log kv 34) and
    `qwen4exp.attention.indexer.top_k = 2048` (kv 33);
  - actual observed retained values: threshold = 2048 + 4 - 1 =
    2051 KV cells; for the single-sequence frozen launch shape the
    KV-cell count at the decision-0 row equals the ACTUAL retained
    prompt token count (retained tokenizer-authority receipts; the
    reducer never uses nominal labels);
  - why the condition changes execution behavior: through 2051
    cells, ggml_top_k's selection covers every KV cell (width ==
    n_kv: the selected-cell mask unmasks everything — dense
    attention, identical numerics to no selection); starting at
    2052 cells the capped width is smaller than the population
    (min(2052, 2051) = 2051 < 2052) and the top-k tensor actively
    shapes the KQ mask via ggml_set_rows
    (src/models/qwen4exp.cpp:724-737) — attention in the 12 QSA
    layers runs over the selected cells only, a genuinely different
    computation graph (GGML_OP_TOP_K + partial_sort +
    set_rows-against-mask path, ggml/src/ggml-cpu/ops.cpp:8548+);
  - why ordinary timing/batching cannot mimic the signal: the width
    is a pure function of the retained token COUNT (n_kv), not of
    wall-clock scheduling; no sampling cadence, ubatch boundary, or
    thread interleaving changes which side of the 2051/2052
    execution boundary a given retained prompt falls on.
  The frozen reducer boundary pair is `INDEXER_ALL_CELLS_MAX = 2051`
  (= `INDEXER_TOP_K + INDEXER_COMPRESS_RATIO - 1` =
  `INDEXER_TOPK_WIDTH`) and `INDEXER_SELECTIVE_MIN = 2052`
  (`INDEXER_ALL_CELLS_MAX + 1`). The predicate may fire only when
  every deterministic-side ACTUAL count is <= 2051 and every
  variable-side ACTUAL count is >= 2052. A variable-side actual
  count of exactly 2051 is NOT selective (width = min(2051, 2051) =
  2051 = the full population), so a boundary whose variable side is
  <= 2051 or whose deterministic side is >= 2052 does not fire the
  predicate and D ends
  R8I3B_REFERENCE_RUNTIME_UNRESOLVED. (The pass-4 text here
  originally stated the dense/selective split as "below vs
  at/above 2051" with a `>= 2051` variable-side rule — an
  off-by-one at equality corrected by AMENDMENT-002; see
  METHODOLOGY-AMENDMENT-002.md.)

D unchanged in all other respects: nominal labels remain generation
parameters only; actual token counts come from the tokenizer
authority; runtime prompt-eval counts must equal it; the screening
pair is not deterministic authority; the boundary deterministic
side requires 5 identical; the confirmation extension is
prospectively frozen; first mismatch establishes variability; no
retrospective length selection.

C. ARM-B DRIFT-PREFIX CUSTODY (blocker 1)

Original METHODOLOGY §B text stands: "A drift before request N
stops the lifecycle BEFORE request N issues: no later request
executes, the completed prefix stays retained append-only, and the
lifecycle is marked incomplete (fail-closed)."

Defect: the pass-3 producer raised on gate-accounting shape
(`request_gate_calls == list(range(len(per_request)))`) BEFORE
writing any custody, so the promised retained prefix was never
produced on drift (proven by old-defect proof at 4becbaaf).

Amended producer semantics (mechanically enforced +
mutation-tested): gate ATTEMPTS, successful authority OBSERVATIONS,
completed REQUESTS, and the FAILED gate index are separate
concepts; a failed gate attempt never corresponds to a completed
request. On authority failure before request N the producer
retains and finalizes every completed request 0..N-1 (unit
directories, rows, observer metadata, raw responses, task-bound log
slices, unit receipts with their successful per-request authority
blocks, shared identity/health custody) and writes lifecycle.json
with stop_kind="truncated", complete=false, planned/completed
request counts, successful gate count, failed gate index (no
authority block is manufactured for the failed request), and the
stop reason. No unit directory/receipt exists for request N or
later. Reducer semantics: a truncated lifecycle is NEVER
terminal-complete even if the retained prefix happens to contain a
row mismatch — the truncation cause dominates; a normal
mismatch_stop remains distinct (authority current, current request
completed, mismatch mechanically derived, stop because the
discriminator was answered) and its prefix may progress to the
next arm.
