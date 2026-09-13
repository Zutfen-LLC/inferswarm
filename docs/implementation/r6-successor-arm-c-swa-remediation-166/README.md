# Issue #166 — Issue #117 Arm-C SWA Allocation Remediation Record

Status: `ISSUE117_ARM_C_SWA_REMEDIATION_READY` (implementation remediation
only / no Arm-C requalification; CPU/static validation only, no physical
execution).

Authority: InferSwarm issue #166, required successor to the accepted
#157 / PR #159 chunk-2 cause localization
(`ISSUE117_ARM_C_CHUNK2_CAUSE_LOCALIZED`). Prior accepted authority: #133
(`ISSUE117_ARM_C_ORDINARY_SERVING_FAIL`), #153
(`ISSUE117_ARM_C_REMEDIATION_BLOCKED`, `BACKEND_REQUIRES_MULTI_CHUNK`).

## What this record is

The additive remediation record for the narrowest real-runtime correction
of the #157-localized defect: the standalone R6 stage path never reached
the scheduler's SWA slot-allocation lifecycle, so
`full_to_swa_index_mapping` stayed at the all-zero sentinel, every
SWA-layer KV store raced on swa slot 0, and every prefix read consumed
slot-0 bytes (earliest varying boundary `L0_kv_slice_post_write`).

The remediation (FreeToken branch `issue-166-swa-remediation`, producer
head `64a37a1f1a2797a190610c5adcdcb4157bce63b9` off the accepted research
head `55e8baaebabe67aeb967d4bd407ef26696933104`): the stage runtime
(`GemmaDenseStage`) itself owns the session SWA allocation lifecycle —
an incremental `alloc_swa` frontier established before each chunk's first
prefix-consuming SWA KV operation (before `prepare_metadata` translates
the page-table range), mapping persistence across chunks and decode,
wholesale ownership release on `reset_session_state` (rebuilt after the
zero loop — the #157-recorded trap where a zeroed free-list hands out
sentinel slot 0), and fail-closed exhaustion/gap semantics. Existing pool
primitives reused verbatim; no parallel allocator; no case/regime/model
special cases; frozen 64-row boundary contract, geometry, planner,
tokenizer, and thresholds untouched.

`evidence/remediation-record.json` binds: exact starting heads; the #157
authority consumed; the full Phase-0 ownership inventory (implementation,
callers, scheduler lifecycle, the standalone gap, the validity timeline,
failure behavior, chosen owner, rejected alternatives); the remediation
design; changed-file sha256s; the producer head; the causal-applicability
proof chain (the corrected lifecycle reaches the same underlying
allocation semantic as the accepted one-variable `alloc_swa` intervention
before the same boundary); the #157 diagnostic-instrumentation status
(off by default, not the production fix); and the #157 evidence
byte-preservation proof.

## What this record is NOT

- NOT a promotion of the remediation producer to qualification authority.
- NOT an Arm-C PASS/FAIL derivation: no fresh correctness-bearing model
  campaign, no Arm D/E, no `h109-*` material. Fresh Arm-C requalification
  requires a separate issue after maintainer acceptance/merge of this
  remediation.

## Tests

`tests/test_issue166_swa_remediation_record.py` (23 CPU tests) re-derives
every binding from pinned committed bytes with negative controls;
FreeToken-side lifecycle proofs (35 tests) live in the producer tree at
`tests/research/test_issue166_swa_remediation.py`.
