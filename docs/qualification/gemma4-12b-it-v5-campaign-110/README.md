# Issue #110 — Gemma v5 physical qualification campaign

Terminal verdict: **`V5_QUALIFICATION_PASS`**.

Status markers, in order:

- `SECOND_INDEPENDENT_CUSTODY_VERIFIED`
- `PRE_EXECUTION_CUSTODY_HANDOFF_TOOLING_REPAIR`
- `V5_QUALIFICATION_PASS` (accepted merge `546ff9d`)
- issue #115 post-campaign retention and audited cleanup (accepted merge
  `d37bd30`)

This area holds the whole campaign, in the order it happened. It opens with
the pre-execution custody handoff because that is what had to be repaired
before the accepted #109 methodology was operationally reachable; the sections
below it record the physical execution and the cleanup that followed.

For the lane this campaign sits in — and why v1 through v4 did not get here —
see [`../README.md`](../README.md).

## Contents

| Area | What it holds |
|---|---|
| `preflight/` | the custody completion record, the effective custody record, its schema, and `HOLDOUT-EXECUTION-AUTHORITY.json` |
| `a1/` | the decision-domain manifest, margin summary, selected stress eighth, and storage preflight |
| `a2/` | the calibration summary, derived core threshold manifest, `h109-unseal-preflight.json`, semantic accounting, and telemetry reference bands |
| `b/` | [`TERMINAL-REPORT.md`](b/TERMINAL-REPORT.md), the h109 unseal record, holdout adjudication, assembly index, and holdout rows |
| `cleanup/` | the issue #115 retention manifest, executed expungement audit, and its two builders |

## Phase 1 — pre-execution custody handoff

At the point this phase began, physical qualification had not started. The
phase existed solely to repair the handoff seam described below.

### Background

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

### What this phase added

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

### Scope prohibitions for this phase (enforced by tests)

CPU/static only. The custody-handoff change did not and must not: SSH to GPU nodes for model
execution, load torch models, initialize CUDA, execute Triton, run
calibration or stress reference execution, execute candidates, or decrypt the
holdout. No statistical, comparator, corpus, threshold, or telemetry constant
differs from accepted #109 — mechanically proven by
`tests/test_issue110_v5_custody_handoff.py` (one-line diff proof, bytecode
identity of every function, constant-by-constant equality).

### Phase 1 identities

| Artifact | SHA-256 |
|---|---|
| accepted #109 merge | `bc6f0ec657d025702d5928771bf8f51aa563a8be` |
| accepted baseline custody record | `6adaa4e5743cdee65f659806d81039dca499c7997cf0240ce92d48cfc2a23b46` |
| #110 effective custody record | `5a1a8756a2330e7ef6658dd9114a599d165741fc7e951482a630811b755e8b6c` |
| #109 thresholds tool (accepted) | `41904b3297e06656bad8b0776f75ca42f7a05635b48fe3afe0b7330071bb0e25` |
| #110 threshold adapter (generated) | `99e449185c7fb96efa5a594dcfcfda01656b51d67e7136dcdb01b34d66887622` |

## Phase 2 — physical execution — `V5_QUALIFICATION_PASS`

The full record is [`b/TERMINAL-REPORT.md`](b/TERMINAL-REPORT.md). In summary:

- **Phase A (calibration).** Reference and candidate arms completed on the
  frozen subject; `a2/core-threshold-manifest.json` was derived from
  calibration evidence only, through the generated
  `scripts/issue110_v5_thresholds.py` adapter.
- **Unseal.** After explicit maintainer authorization
  (`V5_HOLDOUT_UNSEAL_AUTHORIZED`, PR #114), the frozen non-decrypting
  preflight re-passed twice byte-identically, every per-case commitment hash
  was recomputed against the frozen public commitment, and the single-use
  h109 holdout was decrypted **exactly once**. Its plaintext never entered
  either repository. `h109` is now `CONSUMED`. Record:
  [`b/h109-unseal-record.json`](b/h109-unseal-record.json).
- **Phase B (holdout).** 24/24 reference cases (`inferswarm04`, RTX 3090) and
  24/24 candidate cases (three-stage RTX 3060 chain) completed with zero
  NaN/Inf and 192/192 verified canonical-prefix decision identities. Invalid
  attempts: **zero** — both arms completed `rc=0` on first launch.
- **Adjudication.** All three acceptance-bearing families passed inside the
  frozen #109 limits, with 53.17%, 78.38%, and 64.70% headroom respectively.
  Adjudication SHA-256
  `f024f8b3394686ff098459b657ce6dba62d7f190972663e3929ef4a574ab7a70`.

Nothing was changed after the freeze: no threshold, reducer, capture rule,
statistical construction, alpha allocation, `E_D`, semantic rule, domain
construction, telemetry tier, corpus or holdout definition, or model/runtime
subject.

The terminal report carries one dated correction, marked as
evidence-documentation only: decimal conversions and headroom percentages in
its original table were mistranscribed from the authoritative hexadecimal
values. The hexadecimal values, the frozen limits, and the verdict are
unchanged, and `tests/test_issue110_terminal_report_decimals.py` now derives
those decimals mechanically.

## Phase 3 — issue #115 retention and audited cleanup

Storage cleanup only, on the already-accepted immutable campaign. It retained
a hash-bound two-copy durable archive of every acceptance-bearing raw object —
516 objects, 460,854,709 bytes, on two physically independent disks
(`inferswarm01` and `inferswarm03`), including all 384 full-vocabulary FP32
consumer-logit rows — and expunged roughly 729 GiB of node-local campaign
scratch.

No model execution, CUDA, evidence regeneration, threshold change, verdict
change, or methodology change of any kind. See
[`cleanup/README.md`](cleanup/README.md),
[`cleanup/RAW-EVIDENCE-RETENTION.json`](cleanup/RAW-EVIDENCE-RETENTION.json),
and
[`cleanup/RAW-EVIDENCE-EXPUNGEMENT.json`](cleanup/RAW-EVIDENCE-EXPUNGEMENT.json).

## What this campaign does not authorize

`V5_QUALIFICATION_PASS` applies to the exact frozen subject and nothing else.
Applicability downstream is decided by exact subject-digest equality; a
different model, revision, representation, backend, or stage geometry derives
`QUALIFICATION_NOT_APPLICABLE`. The consumed `h109` observations are
permanently diagnostic-only and can never become successor calibration,
stress, or holdout inputs.
