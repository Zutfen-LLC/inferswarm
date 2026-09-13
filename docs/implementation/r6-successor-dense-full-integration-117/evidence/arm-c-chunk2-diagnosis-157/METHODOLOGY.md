# Issue #157 diagnostic methodology — Arm-C chunk-2 extend-path instability

DIAGNOSTIC_ONLY. Frozen prospectively BEFORE any #157 physical
diagnostic output. This issue localizes the required `64 + remainder`
second-prefill-chunk instability (accepted #153 classification
`BACKEND_REQUIRES_MULTI_CHUNK`) to the narrowest execution-level
mechanism that can support a separately reviewed remediation. It does
NOT remediate, does NOT reinterpret or supersede the accepted
`ISSUE117_ARM_C_ORDINARY_SERVING_FAIL` terminal, does NOT create an
Arm-C qualification attempt, does NOT touch `h109-*` material, and
does NOT unblock Arm D/E.

## Accepted authority consumed (immutable)

- InferSwarm `main@e63209c0a3fd7256f527e7d2a009a688cdd66ca6` (start).
- FreeToken `inferswarm-research@55e8baaebabe67aeb967d4bd407ef26696933104`
  — the diagnostic producer VERBATIM (contains the accepted #153
  candidate source `f6133b88…`). **Zero FreeToken source changes.**
- Accepted terminals: #133 `1b83bca…` ORDINARY_SERVING_FAIL; #137
  `cdc23d0e…` REGIME4_DIAGNOSIS_PARTIAL; #153 `e63209c…`
  REMEDIATION_BLOCKED / BACKEND_REQUIRES_MULTI_CHUNK.
- Accepted #137 baseline inputs (fixture `e68dfaaf…`, environment
  `98c04387…`, chain-plan `6d9a4859…`, accepted direct-run
  `08807407…`) — byte-re-verified on the live nodes before freeze.
- Frozen subject: `google/gemma-4-12B-it` @ `707f0a3b…`, checkpoint
  sha256 `5a84cb31…ff18d` (re-verified on 01 and 03 at freeze),
  qualification subject `c6b9fe72…4ffd`, geometry 01/gpu-0 `[0,16)` +
  01/gpu-1 `[16,32)` + 03/gpu-0 `[32,48)`.

## Accepted diagnostic facts this issue begins from (not rediscovered)

The eleven facts enumerated by issue #157, bound mechanically from the
accepted #137 evidence bundle: the six divergent cases are exactly the
required multi-chunk population (lengths 65,65,66,67,67,67 → 64+1,
64+1, 64+2, 64+3, 64+3, 64+3); per-call capacity is 64 rows; stable
cases are ≤53 rows; partitioning a stable 53-row unit into 32+21 is
sufficient for instability (probe C2); for `c109-04-02-047` the first
chunk is stable, embedding stable, earliest captured variance on chunk
2 inside stage 1 at or before global layer 1; prior history is not
necessary; three cases vary within-session, three are session-stable
at a cross-session-different value; one identical mechanism for all
six is not established; #153 source inspection found no CPU-provable
metadata/state-wiring defect.

## Frozen diagnostic corpus

- **Anchor A** = `c109-04-02-047` (issue-mandated; in-session-variable
  family; 67 rows → 64+3; first committed divergence at position 0;
  the only case with retained #137 D/D2 layer evidence).
- **Anchor B** = `c109-04-06-074` (bound BEFORE execution from the
  accepted #137 per-case causal families: session-stable-within-session
  at 107, matches no accepted value, cross-campaign all-four-distinct;
  66 rows → 64+2; position-0 divergence — the chunk-2 prefill call
  itself, same call shape as Anchor A).
- **Stable control** = `c109-03-04-003` (the exact stable control
  identity from accepted #137 probe C2 — bound from the retained
  `i137-diag-C2-1789141057.json` case field and its deterministic
  single-chunk arm; never re-selected).
- **Expansion rule**: the remaining accepted divergent cases run only
  if the anchors localize to different mechanisms or a proposed
  mechanism needs coverage evidence; the reason is recorded before
  each expansion.

## Chunk-2 route facts (source-derived, verified at runtime in Phase 2)

Under the remediated 64-row policy the anchors' first-divergent
chunk-2 calls carry 2–3 rows (extend-route via
`extend_paged_attention` for head_dim 256 SWA layers / generic
`paged_attention` for head_dim 512 full-attention layers). A 1-row
chunk-2 (the 65-row cases' call-0) dispatches to the decode split-k
route (`is_decode = max(seqlens_q) == 1`) with fp32 scratch from
`torch.empty` (`_ensure_decode_scratch`). Both routes' kernels are
correctly masked in source; runtime observation is therefore required
(no source-only defect is claimed).

## Phases (frozen order and design)

### Phase 0 — authority freeze (this document)

Bundle: `docs/implementation/r6-successor-dense-full-integration-117/
evidence/arm-c-chunk2-diagnosis-157/`. Every diagnostic launch gets a
fresh run/attempt ID and `DIAGNOSTIC_ONLY` classification; the binding
verifier (`scripts/issue157_binding.py`) fails closed before GPU work
on producer/tree/module/inputs/interpreter/numerical-mode/GPU drift.

### Phase 1 — instrumentation (observational, off by default)

`scripts/issue157_instrumentation.py` + env-gated installation
(`ISSUE157_STAGE_INSTRUMENT=1`, set ONLY by the #157 probe driver in
spawned stage processes). Ordinary execution imports neither file; the
producer tree is byte-identical to `55e8baa` (zero source changes,
proven by the binding verifier's per-module pins). Capture surface for
the target chunk-2 call on stage 1: call/state identity (tokens,
positions, rows, page-table identity, stream, allocator state),
first-chunk-end KV state hash, earliest-operation checkpoints (qkv
projection, per-head norms, rotary, KV slice pre/post write, attention
output, o_proj, after-layer-0/1 residual), actual dispatch route
observed at the backend call, decode-route scratch identity. Byte
digests + non-finite counts + dtype/shape/stride/device per tensor;
complete per-call records; no trial selection.

### Phase 2 — baseline reproduction (BASE)

Anchor A, Anchor B, stable control. 3 fresh realizations × 3
within-realization repeats (both dimensions mattered in #137). The
baseline must establish: stable 64-row first chunk (byte digest per
call), required 1–3-row chunk 2, Anchor A within-session behavior,
Anchor B cross-session behavior (compared against the accepted #137
in-session values), stable control behavior. Non-reproduction is
retained honestly with exact identity comparison vs #137 and
classified as an evidence/lifecycle finding; no environment tuning;
no later intervention erases the baseline observation.

### Phase 3 — exact-state chunk-2 replay (REPLAY)

Dedicated gpu-0 process, role-first runtime materialized exactly as
the chain does; chunk 1 executed fresh (repeatability control: two
additional fresh executions must be byte-identical — accepted fact);
post-chunk-1 state (owned-layer KV pool bytes) frozen; per trial the
live pool is restored from the frozen capture (restore-return proof
afterwards: restore must return live bytes to the frozen digests, and
the post-trials live bytes must differ from frozen — proving trials
mutate and restores replace, never reuse). 6 trials minimum. If the
standalone exact-state replay varies, localization continues inside
that replay path; if it is stable while full serving varies, causal
search shifts to lifecycle/order/allocator/stream context before the
operation.

### Phase 4 — one-variable intervention ladder (prospective)

Only after baseline + replay. One factor per intervention, paired
against the unchanged control from identical diagnostic state,
counterbalanced order where order could confound, fresh substrate
between paired trials:

- **IV-SYNC (A)**: explicit `torch.cuda.synchronize()` immediately
  before the earliest unstable operation. Stabilization implicates
  ordering/dependency/lifetime; no effect rejects only that narrow
  synchronization hypothesis. No global "deterministic mode".
- **IV-SCRATCH (B)**: deterministic zero-init of the concrete decode
  scratch buffers (`attn_logits`/`attn_lse`) — only buffers proven by
  source+capture to participate in the target op; paired normal-
  allocation control.
- **IV-ROUTE (C)**: mechanical route verification at runtime first;
  then paired comparison of the same captured pre-chunk state through
  the alternate semantically valid route (generic `paged_attention`
  for extend chunks) WITHOUT changing logical inputs/KV semantics.
  If forcing would change semantics → record `INTERVENTION_NOT_LEGAL`.
- **IV-BISECT (D)**: op-level bisection within the earliest varying
  layer using the frozen checkpoints (only if A–C do not localize).

### Phase 5 — perturbation controls

Instrumentation-disabled path == uninstrumented baseline behavior
(the producer is byte-identical; instrumentation installs only under
the driver's env); capture-enabled-but-no-extra-checkpoint control;
exact source/runtime identity per run; counterbalanced intervention
order; fresh diagnostic substrate between paired trials; complete
trial distributions reported (no cherry-picking); any intervention
changing model inputs/checkpoint/geometry/frozen subject is out of
scope.

### Phase 6 — conclusions

Machine-readable per-family conclusions reduced by
`scripts/issue157_conclusions.py` from retained bytes only; terminal
from the issue's four-value ladder, derived from measured conditions
(never a constant).

## Stop/escalation rules

- Stop on any binding-verifier failure (no GPU work).
- Stop and retain honestly on non-reproduction (no environment tuning
  until it reproduces).
- Stop once the first varying operation AND a causal/necessary
  intervention class are demonstrated strongly enough to define a
  bounded remediation issue.
- Physical/tooling prerequisite blocker after an actual attempt →
  `ISSUE117_ARM_C_CHUNK2_EVIDENCE_BLOCKED` (never for incomplete
  implementation).
- If a concrete fix is demonstrated: open a SEPARATE remediation issue
  after this PR is accepted; no behavioral fix lands here.

## Explicit non-claims

- No claim that one mechanism explains all six accepted cases.
- No PASS/FAIL reinterpretation of the accepted Arm-C terminal; no run
  under this issue may derive `ISSUE117_ARM_C_ORDINARY_SERVING_PASS`
  or supersede the accepted FAIL.
- No `h109-*` access in any form.
- No change to the frozen model/checkpoint/geometry or the 64-row
  wire/boundary contract.
- No promotion of `f6133b88…`/`55e8baa…` to qualification authority.
- Diagnostic execution uses fresh isolated materializations/caches and
  never mutates accepted Arm-B/#133 participant-state directories or
  accepted evidence directories.

## Fresh-vs-same-substrate policy

Baseline realizations are FRESH chains (stage processes respawned; the
remote last stage is relaunched per realization by a ledger-bound
launcher loop). Replay/intervention trials reconstruct state from the
frozen capture within one dedicated process (proving no mutated-state
reuse). Paired intervention trials use identical pre-state and
counterbalanced order.
