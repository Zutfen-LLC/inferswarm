# Issue #110 — Gemma v5 physical qualification — TERMINAL REPORT

## Terminal verdict

`V5_QUALIFICATION_PASS`

The single-use h109 holdout was consumed exactly once under explicit
maintainer authorization (`V5_HOLDOUT_UNSEAL_AUTHORIZED`, PR #114 comment
2026-09-07T12:14:41Z) and produced a fully passing terminal observation.
No thresholds, reducers, capture rules, statistical construction, alpha
allocation, E_D, semantic rules, domain construction, telemetry tiering,
corpus/holdout definitions, or model/runtime subject changed at any point
after the freeze.

## Execution identities

- InferSwarm authority head at maintainer authorization: `fc62c4323f1f4dbea55f83a3bb17e3c00c46dad7` (PR #114, OPEN)
- Accepted v5 methodology: `bc6f0ec657d025702d5928771bf8f51aa563a8be` (#109 merge)
- FreeToken calibration producer: `7e5c852163afd9aadfccc406be267e8d060e79ef` (PR #32, OPEN, byte-unchanged)
- FreeToken holdout producer: `924cd22ea081f6d4ed471016faf01d427fc5b0d2` (PR #32; adds `benchmarks/inferswarm_110b/` — h109-only admission wrappers over the frozen runners, admission wiring ONLY, zero execution/model math; 14-test equivalence suite green on orchestrator + all three nodes)
- Execution-authority record: `preflight/HOLDOUT-EXECUTION-AUTHORITY.json` (this branch)

## h109 unseal

- Decrypt count: exactly 1, 2026-09-07, `openssl cms -decrypt -inform DER`
  through the verified orchestrator custodian path, immediately after the
  frozen non-decrypting preflight re-passed twice (byte-identical).
- Commitment verification before any model execution: ALL PASS — 24 cases,
  every per-case hash (prompt/token_ids/case sha256) recomputed against the
  frozen public commitment; seed/generator/tokenizer/historical-exclusion
  identities bound. Record: `b/h109-unseal-record.json`.
- h109 is now CONSUMED. Plaintext never entered either repository.

## Execution accounting

- Reference (inferswarm04 RTX 3090, tag `href109`): 24/24 h109 cases, 0
  NaN/Inf, 192 decision rows with sha-recorded FP32 rows (`B1-ref-holdout-1`).
- Candidate (three-stage RTX 3060 chain 01 GPU-0/GPU-1 + 03, tag `hcand109`):
  24/24 h109 cases teacher-forced on the exact reference canonical prefix at
  all eight decisions (192/192 prefix identities verified), 0 NaN/Inf
  (`B1-cand-holdout-1`).
- Invalid attempts: ZERO. Both arms completed rc=0 on the first launch.
- Runtime/backend identity verified on all three nodes before execution:
  torch 2.11.0+cu130, CUDA 13.0, triton 3.6.0, flashinfer-python 0.6.17,
  driver 610.57.04, checkpoint `5a84cb31…ff18d` identical.

## Terminal adjudication (frozen limits only)

Core observed maxima vs frozen limits (inclusive `observed <= limit`):

| family | observed | limit | margin | verdict |
|---|---|---|---|---|
| fp32-consumer-logits:max-absolute-difference | 0x1.b48p+3 (14.28125) | 0x1.d2p+4 (14.625) | 2.4% | PASS |
| fp32-consumer-logits:rms-difference | 0x1.44dcfa4242a7ap+1 (2.5564) | 0x1.7790ef6766a33p+3 (11.879) | 78% | PASS |
| decision_local_E_D | 0x1.49p+3 (10.28125) | 0x1.d2p+4 (14.625) | 30% | PASS |

Semantic adjudication (192 decisions, frozen v5 gate order, frozen GLOBAL
calibration E_D = 0x1.d2p+4):

- SEMANTIC_PASS 192/192 (all UNSTABLE-admissible under the frozen contract,
  consistent with the calibration arms)
- STABLE_DECISION_MISMATCH 0; UNSTABLE_DECISION_INADMISSIBLE 0
- DECISION_LOCAL_BOUND_EXCEEDED 0; DECISION_DOMAIN_ESCAPE 0

Telemetry (TELEMETRY_ALERT_NOT_QUALIFICATION_FAILURE tier): **0 alerts**
across all 12 band families plus the mandatory p99 consumer-logit
telemetry family.

Integrity: exact-integrity PASS 24/24, finite-output PASS 24/24
(zero NaN/Inf across all rows both arms).

Adjudicator determinism: two independent runs produced byte-identical
`holdout-adjudication.json` (sha256 `f024f8b3…b7a70`).

## Evidence completeness and retention

Committed (this directory):

- `b/h109-unseal-record.json` — unseal + commitment verification record
- `b/holdout-adjudication.json` — terminal adjudication (all families)
- `b/holdout-rows.json` — all 24 case rows: 15 envelopes, observed core,
  semantic verdicts per decision
- `b/holdout-assembly-index.json` — 24/24 assembly, zero failures
- `preflight/HOLDOUT-EXECUTION-AUTHORITY.json` — holdout producer binding

Node-local raw evidence (retained until post-adjudication disposition per
the #105/#107-style process; not committed, plaintext-free):

- inferswarm04 `/srv/inferswarm/state/issue110/holdout-reference/` — 2.0 GB (24 reference case bundles incl. FP32 rows)
- inferswarm01 `/srv/models/issue110/holdout-candidate/` — 2.4 GB (stages 1–2 + reference copy, byte-verified)
- inferswarm03 `/srv/models/issue110/holdout-candidate-laststage/` — 3.6 GB (last-stage captures + candidate FP32 rows)
- inferswarm01 `/srv/models/issue110/holdout-adjudication/` — observations + adjudication (deterministic)

Calibration raw evidence (unchanged from the a2 freeze, retained):

- inferswarm04 `/srv/inferswarm/state/issue110/reference/` — 134 GB, verified copy on inferswarm01 `/srv/models/issue110/reference/`
- inferswarm01 `/srv/models/issue110/candidate/` + inferswarm03 `/srv/models/issue110/candidate-laststage/` — ~270 GB

Proposed post-adjudication retention/expungement (PROSPECTIVE, maintainer
decision; nothing expunged before terminal acceptance): apply the
#105/#107-style RAW-EVIDENCE-RETENTION process to the calibration and
holdout raw trees — retain compact adjudication/rows/index artifacts in
repo (done), retain a minimal durable set (per-case summaries + FP32
decision rows of any maintainer-designated cases) in the diagnosis area,
expunge the ~409 GB of capture bundles after acceptance with a committed
audit record.

## PR state

Both PRs remain OPEN and unmerged pending maintainer adjudication, per
the frozen contract. Do not merge before maintainer review.
