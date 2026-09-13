# Issue #157 evidence bundle — Arm-C chunk-2 extend-path diagnosis

DIAGNOSTIC_ONLY. Terminal: **`ISSUE117_ARM_C_CHUNK2_CAUSE_LOCALIZED`**
(reduced by `scripts/issue157_conclusions.py` from the retained bytes;
see `diagnostic-conclusions.json`).

## What was localized

Starting from byte-equivalent post-chunk-1 state, the required 1–3-row
second extend-prefill chunk on stage 1 ceases to be deterministic
because **the R6 standalone stage path never performs SWA slot
allocation**: `alloc_swa` is called only by the scheduler's cache
manager (`python/freetoken/scheduler/cache.py`), which the R6 stage
runtime does not use. `full_to_swa_index_mapping` therefore stays at
its all-zero sentinel, and for every SWA attention layer:

1. `store_kv` translates the chunk's full-pool `out_loc` through the
   zero mapping → **all chunk rows target swa slot 0** — chunk-2's 2–3
   rows are racing store warps overwriting one slot, so the slot's
   surviving bytes vary per execution;
2. the extend kernel's prefix read (`swa_indices` = translate(page
   table) = all 0) resolves the 64-row prefix to **slot 0 repeated** —
   it consumes the just-raced bytes, so the earliest varying operation
   is the layer-0 attention kernel result (`L0_attention_output`;
   qkv/norms/rotary/backend inputs all byte-stable before it);
3. chunk-1 is deterministic because with `prefix_len = 0` the split
   extend kernel reads `k_extend`/`v_extend` directly — the pool is
   never read.

This is consistent with every accepted #133/#137/#153 fact (explanatory consistency, not a coverage proof for all six cases): the 18 stable
single-chunk cases never read a prefix; the six multi-chunk cases do;
#137's C2 probe destabilized a stable 53-row case exactly by
introducing a second chunk (a prefix read); the divergence localizes
to stage-1 SWA layers 0–1.

## Causal demonstration (prospective one-variable intervention)

`alloc_swa` over the used full slots, performed after
`reset_session_state` and before chunk execution — the single changed
factor vs the paired control:

- Anchor A `c109-04-02-047` (64+3, in-session-variable family):
  treatment chunk-2 byte-deterministic 6/6; paired control 3 distinct
  digests / 6 trials; chunk-1 unchanged.
- Anchor B `c109-04-06-074` (64+2, session-stable family): treatment
  deterministic 6/6; control 6 distinct / 6.

Rejected hypotheses (same paired design): execution-order/
synchronization (device-wide sync before every attention call — still
varies); kernel-route (alternate legal paged route — also varies);
Triton pointer-alignment specialization (all captured pointers
0 mod 16 across varying trials); decode-scratch initialization (not on
the anchors' extend-route path — intervention not legal per Phase 4-B).

## Bundle contents

- `METHODOLOGY.md` — frozen before physical output (commit c11fa00).
- `physical-diagnostic-authority.json` — starting SHAs, subject,
  topology, anchors/control binding, intervention matrix, non-claims.
- `baseline-reproduction.json` — Phase 2 (BASE run i157-BASE-1789261211).
- `exact-state-replay.json` — Phase 3 (run i157-REPLAY-1789262629) +
  superseded first attempt (no-op-restore harness bug, retained).
- `interventions.json` — Phase 4 arms incl. rejected hypotheses and
  superseded attempts (tooling incidents retained honestly).
- `instrumentation-manifest.json` — run-record hashes, retained JSONL
  hashes, off-by-default proofs, retention gaps.
- `launch-ledger.json` — every diagnostic launch with run/attempt IDs.
- `diagnostic-conclusions.json` — reduced conclusions + terminal.
- `MANIFEST.sha256` — fail-closed bundle manifest.

## Correction pass 1 (adversarial-review)

Two exact-head adversarial reviews returned GO-WITH-FIXES. All P1s
resolved: (a) the evidence-bearing arms were RERUN under tool bytes
committed at 2611ee1 (node bytes sha256-verified equal before launch) —
all results confirmed (REPLAY varies 6/6; SYNC and ROUTE rejected;
SWA-ALLOC stabilizes both anchors); (b) the reducer now selects the
earliest varying checkpoint by execution order (the racing SWA store,
not the downstream attention read), never reports a legally-skipped
intervention as executed, and the reproduction gate is
non-tautological; (c) the checkpoint matrix is derived from the
retained raw JSONLs of the correction-pass runs (94 checkpoints,
including the direct full_to_swa_index_mapping observation); (d) the
authority record re-freezes the final tool hashes with the drift
history recorded; (e) the launch ledger is complete (19 entries,
including previously-unledgered confirmation runs).

## Raw run artifacts

Correction-pass (authoritative): `~/i157/pull-corr1/` (all JSONLs
retained) + node-local `/srv/inferswarm/state/issue157/out-corr1/`.
Original (superseded, retained): node-local `/srv/inferswarm/state/issue157/out/`
(driver records + replay results), `/tmp/issue157-harness/` (per-call
JSONL; partially wiped by inter-probe harness cleaning — see retention
gaps in `instrumentation-manifest.json`). Orchestrator pull copy:
retained at `~/i157/pull` during review.

## Correction pass 2 (post-evidence reduction correction)

Maintainer NO-GO review found the conclusions reducer still carried
numeric literals in prose (Anchor-B control described as "5 distinct
chunk-2 digests / 6 trials" while the retained control is mechanically
6 distinct / 6, plus similar literals elsewhere). Fixed generically:
every trial/distinct count, control-varies flag, treatment-determinism
flag, and chunk-1 pairing fact is now COMPUTED from the retained
evidence bytes and retained as structured machine-readable fields
(`interventions.swa_alloc.detail.per_anchor.*`), with all prose
formatting those computed fields — no numeric literals remain in the
reducer's observational prose. Adversarial mutation tests added in
`tests/test_issue157_chunk2_diagnosis.py` (TestDerivedCountsFollowEvidence)
prove the summary follows mutated inputs mechanically, and that the
committed `diagnostic-conclusions.json` regenerates byte-identically.

Provenance (authority record `instrumentation` section): the
execution-bearing tool hashes used for the committed physical reruns
(2611ee1) are preserved verbatim under `execution_bearing_files`;
`scripts/issue157_conclusions.py` is classified explicitly as
`post_processing_files` (post-evidence reduction only — never executed
inside, and never influencing, any physical diagnostic process); an
additive `post_evidence_reducer_amendments` entry records the prior and
corrected reducer hashes with proof that no physical observation,
execution-bearing instrumentation byte, or FreeToken producer byte
changed. No GPU/model rerun was performed or required for this
correction. Terminal re-derived from unchanged evidence:
`ISSUE117_ARM_C_CHUNK2_CAUSE_LOCALIZED`.

## Non-claims

Per `METHODOLOGY.md`: no claim that this mechanism is proven for all
six accepted cases (two anchors cover both behavioral families and
both chunk-2 shapes 2/3 rows; the 1-row decode-route chunk-2 was
stable at call-0 in accepted evidence and was not separately
exercised); no Arm-C PASS/FAIL reinterpretation; no h109 access; no
contract change; no remediation landed (a separate remediation issue
must be opened after this PR is accepted).
