# Issue #110 — Gemma v5 pre-execution custody handoff (tooling repair)

Status markers, in order:

- SECOND_INDEPENDENT_CUSTODY_VERIFIED
- PRE_EXECUTION_CUSTODY_HANDOFF_TOOLING_REPAIR

Physical qualification has NOT begun. This area exists solely to make the
accepted #109 methodology operationally reachable after the already-planned
second-custody transition.

## Background

The accepted #109 threshold tooling (`scripts/issue109_v5_thresholds.py`)
requires both:

1. the supplied custody record to hash exactly to the accepted incomplete
   baseline `6adaa4e5…a23b46` (one custodian,
   `SEALED_CUSTODY_INCOMPLETE`), and
2. `custody_is_satisfied(record)` to be true (two verified independent
   custodians).

No completed custody record can ever pass the frozen deriver: completing it
changes its hash. This is a tooling defect in the handoff seam only. It is
not permission to reopen any statistical, comparator, corpus, semantic,
threshold, or holdout design decision.

## What this area contains

- `preflight/holdout-custody-completion.json` — additive, non-secret metadata
  documenting the verified second independent custodian (canonical hosts
  `inferswarm01` and `hermes`, distinct storage boundaries, matched private
  key / normalized seed / public-DER identities, verified permissions,
  `decrypt_performed: false`, `private_material_in_repository: false`).
  An additional copy on `inferswarm00` is recorded but is not relied upon for
  the correctness-bearing two-custodian proof.
- `preflight/schemas/v5-custody-completion-record.schema.json` — versioned
  schema for the completion record.
- `preflight/effective-holdout-custody-record.json` — deterministic
  construction (canonical JSON bytes) reusing the frozen
  `inferswarm.issue109.v5-holdout-custody-record/1` schema with exactly the
  two correctness-bearing custodians, `holdout_state:
  SEALED_NOT_CONSUMED`, `unseal_authorized: false`. It does not replace the
  historical #109 record, which is retained unmodified.
- `scripts/issue110_v5_custody.py` — CPU/static validation and deterministic
  effective-record construction. Never reads private files; never decrypts.
- `scripts/build_issue110_v5_threshold_adapter.py` — deterministic builder
  that reads the accepted #109 thresholds tool (exact SHA-256 required) and
  performs exactly one semantic transformation: replacing the historical
  custody-record hash constant with the effective record's SHA-256.
- `scripts/issue110_v5_thresholds.py` — the generated adapter, provably the
  accepted #109 deriver with only the custody identity substitution.

## Scope prohibitions (enforced by tests)

CPU/static only. This PR does not and must not: SSH to GPU nodes for model
execution, load torch models, initialize CUDA, execute Triton, run
calibration or stress reference execution, execute candidates, or decrypt the
holdout. No statistical, comparator, corpus, threshold, or telemetry constant
differs from accepted #109 — mechanically proven by
`tests/test_issue110_v5_custody_handoff.py` (one-line diff proof, bytecode
identity of every function, constant-by-constant equality).

## Identities

| Artifact | SHA-256 |
|---|---|
| accepted #109 merge | `bc6f0ec657d025702d5928771bf8f51aa563a8be` |
| accepted baseline custody record | `6adaa4e5743cdee65f659806d81039dca499c7997cf0240ce92d48cfc2a23b46` |
| #110 effective custody record | `5a1a8756a2330e7ef6658dd9114a599d165741fc7e951482a630811b755e8b6c` |
| #109 thresholds tool (accepted) | `41904b3297e06656bad8b0776f75ca42f7a05635b48fe3afe0b7330071bb0e25` |
| #110 threshold adapter (generated) | `99e449185c7fb96efa5a594dcfcfda01656b51d67e7136dcdb01b34d66887622` |
