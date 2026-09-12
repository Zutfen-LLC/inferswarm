# Issue #153 — Issue #117 Arm-C Remediation Record

Status: `ISSUE117_ARM_C_REMEDIATION_BLOCKED` (CPU-only correction; no
physical execution).

Authority: InferSwarm issue #153, as corrected by the maintainer review
of the first implementation (PRs #33/#155 at reviewed heads 5e6bca58 /
b387e899) and the maintainer correction comment on issue #153.  Parent
integration gate: #117 (historically closed).  This record is step 1 of
the three-step remediation path the #117 docs require (remediation
authority → maintainer acceptance → separately authorized fresh Arm-C
requalification).  It is NOT acceptance, and it authorizes nothing
physical.

## Corrected classification

`BACKEND_REQUIRES_MULTI_CHUNK` (branch B), re-derived mechanically by
`scripts/issue153_phase0_inventory.py` from (a) the accepted #137
population facts, hash-pinned from
`../evidence/arm-c-regime4-diagnosis-137/phase1-inventory.json`
(sha256 369b2c81…), and (b) the frozen contract bytes:

- the six divergent Arm-C cases are exactly the multi-chunk population
  (`prompt_len > PREFILL_CHUNK=64`), all 65–67 rows; every stable case
  is ≤ 53;
- a 65–67-row single backend call is ILLEGAL under the frozen contract:
  the R4 wire rejects `token_count > max_token_count` (= 64), and the
  frozen boundary geometry sizes the boundary bytes and activation
  staging buffers at exactly 64 rows (64×3840×2); runtime capacity 256
  is session KV capacity, not per-call boundary authority;
- probe C2's 53-row control proves only that partitioning is SUFFICIENT
  for instability on a stable input — it does not legalize a 65–67-row
  single call.  The first implementation's branch A
  (`UNNECESSARY_PARTITION_POLICY`) was derived from that control's
  legality and is WITHDRAWN.

Branch B disposition: option 1 (implement/prove partition-invariant
multi-chunk semantics at the owning backend/state seam) is not
available CPU-only — source inspection of the required extend path
(`stage_runtime._make_batch` → triton `prepare_metadata` →
`extend_paged_attention`; the 1–3-row second chunk routes through the
decode kernel's `is_decode` branch with correct `prefix_len` causal
semantics) found no provable state defect: fixed tiles, no autotune, no
atomics, correct positions/KV writes.  The #137 record shows the
instability is execution-level (3/6 cases vary within a session; 3 are
per-session stable but distinct across sessions) — identifying a
defect to fix would require new physical evidence, which no open issue
authorizes.  The terminal is therefore BLOCKED.

## What the corrected candidate producer changes (and what it does not)

FreeToken PR #33, corrected head (branch
`inferswarm-153-arm-c-remediation` off the protected research head
`b05564a7`, which contains the accepted producer `924cd22e` in
ancestry):

- retained (useful, but NOT a remediation of the failing population):
  the capacity-derived ≤64 single-chunk policy
  (`python/freetoken/research/prefill_partition.py`; a legal unit is
  ONE call; over-limit units partition deterministically at the
  capacity); `stage_chain.generate` and `two_stage.generate` consume
  it with capacity from the frozen strategy `PREFILL_CHUNK`; this
  removes the unnecessary-partition defect class for legal units (the
  legacy `two_stage` hand default of 32 is gone);
- corrected capacity ownership: strategy (frozen constant owner) →
  `stage_chain`/`two_stage` (chunk policy) and strategy →
  `last_stage_service` (wire bound).  The wire service no longer
  imports the chain runtime; no runtime module imports the wire
  service; sender and receiver derive from the same frozen constant;
- timing-unit regression fixed: the `two_stage` prefill accumulator is
  restored to `perf_counter_ns` on both sides (`prefill_ns` is
  nanoseconds), with a structural AST regression contract;
- for the accepted failing population 65/66/67: the execution
  partition is the UNCHANGED accepted `64 + remainder` path, same
  requests as the accepted hand-literal loop — the canonical failing
  path's behavior did NOT change, and no remediation of its
  instability is claimed.

## Required next remediation slice (deeper authority)

Arm-C remains FAILED.  The instability is localized by #137 to the
second prefill chunk inside stage 1 at/before global layer 1 (first
64-row chunk stable; embedding stable).  Making the required
multi-chunk extend path stable requires one of:

1. a physically authorized diagnostic/remediation issue that freezes a
   producer with instrumented (or perturbed) execution of the chunk-2
   extend path on the real substrate, to identify the execution-level
   nondeterminism source (no such authority exists); or
2. a maintainer-approved frozen-contract change admitting >64-row
   single calls (boundary geometry + wire + buffers) — out of scope for
   #153 and far beyond it.

Arm D/E remain blocked behind Arm C.

## Evidence

- [`evidence/phase0-inventory.json`](evidence/phase0-inventory.json) —
  corrected Phase-0 inventory: owner, inputs, accepted #137 population
  (hash-pinned), branch-B classification with the withdrawn-branch-A
  rationale, one-call legality DISPROOF for 65–67, C2 control role.
- [`evidence/producer-delta.json`](evidence/producer-delta.json) —
  corrected producer delta: classification, terminal, exact changed
  file hashes, mechanical changed-runtime-file audit (rejects unit
  drift and out-of-scope changes), per-failing-population remediation
  answers, applicability caveat.
- [`evidence/boundary-matrix.json`](evidence/boundary-matrix.json) —
  the executed boundary matrix with the 65/66/67 failing population as
  the PRIMARY section (unchanged accepted partition, behavior_changed
  false) and the legal matrix + 53-row C2 causal control retained.

## CPU/static proof summary

Focused FreeToken suite
`tests/research/test_issue117_arm_c_remediation.py` (79 tests):

- exact accepted population 65/66/67 classified multi-chunk;
  single-call legality mechanically disproven under the frozen
  contract; branch A not derivable from 53-row legality alone;
- corrected classification and terminal bound in the module source;
- corrected partition == the accepted hand-literal loop (request
  content equality via fake stages);
- 53-row C2 retained as causal-control regression, explicitly not a
  failing-population substitute;
- coverage invariants and fail-closed negative controls;
- decode/session/plan/fencing semantics unchanged;
  `prefill_ns` nanoseconds (AST structural contract);
- capacity ownership: wire derives from strategy; no runtime module
  imports the wire service; sender/receiver mechanical agreement;
- no case IDs/regime/model nouns in the remediation seam.

Full FreeToken research suite on the corrected head: 532 passed, 1
deselected pre-existing base failure
(`test_r6_localization.py::test_stage_chain_capture_ops_are_explicit`,
present at the starting research base `b05564a7`), 72 subtests.

## Non-claims

- No GPU/model execution occurred; no InferSwarm node was contacted.
- No `ISSUE117_ARM_C_ORDINARY_SERVING_PASS`/`FAIL` is derived.
- No `h109-*` material was accessed.
- This producer is a CANDIDATE, not accepted execution authority, and
  does NOT remediate the accepted 65–67 failure.
- Fresh Arm-C requalification MUST NOT be authorized from this
  producer; it remains blocked pending the deeper remediation slice
  above AND a new authorizing issue.

## Accepted-evidence preservation

The accepted evidence bundles (#128 / #132 / #136 / #138 and the parent
#117 area) are byte-preserved: this remediation bundle is additive under
`remediation/` and outside every accepted bundle; the parent
`evidence/MANIFEST.sha256` was not reopened (enforced by
`tests/test_evidence_manifest_lifecycle.py::test_issue117_parent_is_closed_to_later_slices`
and the bundle-local manifest lifecycle tests).
