# Issue #153 — Issue #117 Arm-C Remediation Record

Status: `ISSUE117_ARM_C_REMEDIATION_READY` (CPU-only remediation; no
physical execution).

Authority: InferSwarm issue #153.  Parent integration gate: #117
(historically closed).  This record is step 1 of the three-step
remediation path the #117 docs require (remediation authority →
maintainer acceptance → separately authorized fresh Arm-C
requalification).  It is NOT acceptance, and it authorizes nothing
physical.

## Classification

`UNNECESSARY_PARTITION_POLICY` (branch A), decided from the Phase-0
inventory before any behavioral edit, and re-derived mechanically by
`scripts/issue153_phase0_inventory.py` from pinned producer bytes:

- the chunk-policy owner is `GemmaStageChainRuntime.generate`
  (`benchmarks/inferswarm_r6/stage_chain.py`);
- the accepted producer's chunk boundaries came from a call-site hand
  literal (`chunk = 64`), not from the frozen execution contract;
- the legacy `two_stage.py` path still carried a hand default of
  `chunk = 32` — a legal 53-row logical unit becomes `32 + 21` exactly
  as the accepted #137 probe C2 intervention demonstrated;
- one 53-row call is legal under the backend contract (wire bound
  `0 < token_count <= 64`; frozen boundary geometry
  `prefill_chunk_rows: 64`; runtime capacity 256 tokens);
- therefore the subdivision was policy, not backend necessity.

## Remediation (FreeToken candidate producer)

FreeToken PR (branch `inferswarm-153-arm-c-remediation` off the
protected research head `b05564a7`, which contains the accepted
producer `924cd22e` in ancestry):

- new generic CPU-pure policy module
  `python/freetoken/research/prefill_partition.py`:
  `plan_prefill_partitions(total_rows, admitted_max_rows)` keeps a
  legal unit as ONE backend call, partitions over-limit units
  deterministically at the admitted capacity, and
  `assert_partition_invariants` polices ordered / complete /
  non-overlapping / exactly-once coverage; zero/negative/non-integer
  inputs fail closed;
- `stage_chain.generate` and `two_stage.generate` consume the policy,
  with capacity `admitted_prefill_rows()` derived from the frozen
  strategy `PREFILL_CHUNK` boundary-geometry constant (no new magic
  constants);
- `last_stage_service.MAX_TOKEN_COUNT` derives from the same source, so
  the wire contract admits exactly what the chain sends;
- decode path, session/plan identity, fencing, commit semantics,
  planner semantics, and all frozen geometry are unchanged
  (machine-checked; see the producer-delta record's
  `explicitly_unchanged` list and the MUST_BE_IDENTICAL surface).

## Evidence

- [`evidence/phase0-inventory.json`](evidence/phase0-inventory.json) —
  mechanically derived Phase-0 code-path inventory (owner, inputs,
  53→32+21 explanation, one-call legality, path coverage, downstream
  dependents), pinned to accepted and remediation producer bytes.
- [`evidence/producer-delta.json`](evidence/producer-delta.json) —
  additive remediation record: classification, exact changed-file
  hashes, behavioral delta (chunk-selection only), explicitly
  unchanged surfaces, no-case-tuning proof, applicability caveat.
- [`evidence/boundary-matrix.json`](evidence/boundary-matrix.json) —
  the executed boundary-test matrix (1/31/32/33/53/63/64 single-chunk;
  65+ over-limit controls) and the focused FreeToken suite results,
  derived from the FreeToken remediation worktree.

## CPU/static proof summary

58 focused tests in FreeToken
`tests/research/test_issue117_arm_c_remediation.py`:

- boundary matrix: 1, 31, 32, 33, 53, 63, 64 → one chunk; 65 → 64+1,
  85 → 64+21, 128, 129 → deterministic partitions, each legal per call;
- #137 causal-control regression: policy selects `single_chunk_53`,
  never `multi_chunk_32_21` (policy-selection proof only — no claim
  about the GPU numerical result);
- path equality: direct and ordinary paths share the single
  `generate()` seam; the wire service admits exactly the policy
  capacity;
- coverage invariants and fail-closed negative controls (zero/negative
  rows and capacities, non-integer inputs, reordered / overlapping /
  gapped / incomplete / zero-row partitions, missing contract field);
- semantic preservation via fake stages: PREFILL requests byte-identical
  to the accepted loop for legal units, decode unchanged, every logical
  row consumed exactly once, session identity surfaces untouched;
- AST no-case-tuning audit: no case IDs, no regime nouns, no row-count
  nouns (53/32/21/64) as constants in the generic policy.

FreeToken research suite on the remediation head: 511 passed, 1
deselected pre-existing base failure
(`test_r6_localization.py::test_stage_chain_capture_ops_are_explicit`,
asserting an op removed by d4d1608 — present at the starting research
base `b05564a7`, unrelated to this remediation), 72 subtests passed.

## Non-claims

- No GPU/model execution occurred; no InferSwarm node was contacted.
- No `ISSUE117_ARM_C_ORDINARY_SERVING_PASS`/`FAIL` is derived.
- No `h109-*` material was accessed.
- This producer is a CANDIDATE, not accepted execution authority.
- A fresh Arm-C requalification campaign remains separately blocked
  pending maintainer acceptance of this remediation AND a new
  authorizing issue that freezes the remediation producer, audits its
  delta against the accepted subject, and authorizes physical
  execution.

## Accepted-evidence preservation

The accepted evidence bundles (#128 / #132 / #136 / #138 and the parent
#117 area) are byte-preserved: this remediation bundle is additive under
`remediation/` and outside every accepted bundle; the parent
`evidence/MANIFEST.sha256` was not reopened (enforced by
`tests/test_evidence_manifest_lifecycle.py::test_issue117_parent_is_closed_to_later_slices`
and the bundle-local manifest lifecycle tests).
