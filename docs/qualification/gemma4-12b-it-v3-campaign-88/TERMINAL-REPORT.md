# Issue #88 — Gemma v3 physical qualification: terminal report

## Verdict

```
V3_HOLDOUT_FAIL
```

One valid holdout envelope exceedance (case `h86-03-05-01`,
`final-normalized-hidden-state:rms-difference` observed 2.6800369574218053 vs
frozen limit 2.6131138414325275, +2.56%). Per the frozen contract this is
terminal for the campaign: no threshold tuning after holdout, no
valid-failure rerun, no methodology change. The semantic decision-stability
gates themselves passed everywhere (calibration 4672/4672, holdout
192/192 SEMANTIC_PASS; zero DECISION_DOMAIN_ESCAPE; zero
DECISION_LOCAL_BOUND_EXCEEDED; zero NaN/Inf).

## Identities

- InferSwarm methodology: `a8ec98a9fb9b673c93de5100d784ea772395efdb`
  (issue #86 / PR #87, accepted; issue #88 authorizes execution)
- InferSwarm evidence branch: `issue-88-v3-campaign`
  - Phase B barrier commit `884d31b2bf7a39efd300ac5d83f58f29ce40cf92`
    (margins + selected-eight)
  - Phase C barrier commit `4e2f7bf84fd1364a48a013833d508ee0b0dd229f`
    (decision-domain manifest, 4672 rows)
  - Phase E/F commit `e4e7bfe7fb75c697a12c9d8b193be03382dc0753`
    (calibration summary + threshold manifest, file sha
    `251c4b7a8127e086001cc59e96cf7f61c17c59fa3bd120a15b5c4678fa9f5e5d`)
  - Phase G commit `8e7d13af956d26322d620eeb91242f8071500c15`
    (semantic adjudication PASS)
- FreeToken base: `d4d16089165917704a87f4e2f0c4a09969646f95`
- Physical producer: `560bb7e833ad4ca9386eb87799bb0aafb82b3e59`
  (branch `issue-88-v3-qualification`, PR Zutfen-LLC/FreeToken#30,
  accepted and merged to `inferswarm-research` as
  `5e44be50cd9ed322366a01cd5d80d958950d1ac5`). Producer lineage:
  `cc0680a` (initial freeze) → `906d9e3` (phaseC-1 capture-defect fix) →
  `560bb7e` (phaseD-stress-1 all-8-decisions fix); both fixes landed BEFORE
  any qualification-bearing candidate evidence; the affected attempts are
  retained as invalid (below).
- Subject: google/gemma-4-12B-it @ 707f0a3b…, checkpoint sha256
  `5a84cb313260ac447237b890387116dfa8682e49a6b44bc585ae8353abbff18d`
  (verified byte-identical on 01/03/04)
- Roles: reference = inferswarm04 RTX 3090 (GPU-ecda1aaa…); candidate =
  3-stage RTX 3060 chain (01 GPU-1fc28f83 [0,16) + 01 GPU-d5c05739
  [16,32) + 03 GPU-e1f2f90c [32,48) via tcp/18485 R4 wire)
- Stack (all nodes): driver 610.57.04, torch 2.11.0+cu130, CUDA 13.0,
  nvcc 13.1, triton 3.6.0, transformers 5.16.1, flashinfer 0.6.17,
  python 3.13.5. Native ext .so: 01==03 byte-identical; 04 differs by
  build-path metadata (recorded honestly, #81 precedent).

## Phase record

- **P** Producer frozen (28 CPU-pure tests), pushed, clean trees on all
  nodes; PR #30 opened against `inferswarm-research` and later accepted/merged
  after terminal campaign adjudication.
- **A** Preflight/applicability recorded; no drift. Chain plan = frozen
  R6 plan sha256 `a91e3f71…` with EXPLICIT_OVERRIDE_ISSUE88_EXECUTION.
- **B** 48/48 p86 reference margins: 0 nonfinite, 0 negative, 7 exact
  zero-ties (eligible). Selected-eight (4 zero + 4 largest incl. 3.875)
  committed and re-fetched byte-identical BEFORE candidate execution.
  margin summary sha `8d13d5bb…`, selected-eight sha `9866e4f1…`.
- **C** 576 c86 + 8 selected p86 reference cases; stress re-run
  bit-identical to Phase B (reference determinism proven). Decision-domain
  manifest (4672 rows) re-derived CPU-side from retained row bytes with
  every sha/hash/winner re-verified; committed + re-fetched
  (sha `df446d71…`).
- **D** Teacher-forced chain candidate over all 584 cases: prefix
  identity proven BEFORE each decision execution; 4672 candidate FP32
  rows retained; all rule proofs pass. Stress-arm observation: 2/64
  candidate winner flips vs reference (later adjudicated
  ambiguity-admissible).
- **E** 15 envelopes per case via the frozen #76 reducer (584/584, zero
  integrity failures). decision_local_error per decision (584 cases,
  every row/domain/prefix hash re-verified). Calibration summary sha
  `81bbd737…`.
- **F** Thresholds derived by the accepted tool (selector replay
  verified): E_D = `0x1.af00000000000p+4` (26.9375, statistical arm);
  15 limits = max(statistical, stress). Threshold file committed, pushed,
  re-fetched byte-identical (`251c4b7a…`).
- **G** Semantic calibration adjudication: 4672/4672 SEMANTIC_PASS;
  zero envelope exceedances (by construction of the limits); the 2
  stress flips were m_D <= 2E_D ambiguity-admissible.
- **H** Unseal preflight via `verify_issue86_v3_unseal.py` with actual
  file bytes: UNSEAL_PRECONDITIONS_PASS_DECRYPT_NOT_PERFORMED. One
  explicit decrypt performed with the verified custodian key
  (orchestrator custodian; key sha `e6daaf45…`). 24 h86 cases
  identity-verified (case/prompt/token hashes). The historical #74
  holdout was never touched (sha `23311c55…` unchanged).
- **I** Holdout executed reference+candidate under the identical frozen
  procedure: semantic gates 192/192 SEMANTIC_PASS, zero NaN/Inf, all
  teacher-forcing/rule/domain checks pass; ONE envelope exceedance on
  h86-03-05-01 (final-normalized-hidden-state:rms-difference 2.6800 vs
  2.6131; next-highest holdout case 1.1518). Independently re-derived
  from the retained capture bundles — the measurement is valid.
  **Terminal: V3_HOLDOUT_FAIL.** Holdout plaintext sha256
  `263180b9346ad6d4c4de0e96db0983a3bd5f7ae0cdc525f6123bd2128abae04f`.

## Invalid attempts (retained)

1. `phaseC-1` (inferswarm04): producer capture defect (arm_full_capture
   chained per case → duplicated records) + disk exhaustion at case 225.
   Fixed by producer commit `906d9e3`; attempt retained at
   inferswarm04 `/srv/inferswarm/state/i88/invalid/`.
2. `phaseD-stress-1` (01/03): chain runner forwarded capture_step only
   at envelope positions → 4/8 decision rows per case. Fixed by producer
   commit `560bb7e`; attempt retained in the same invalid/ area.

## Evidence index

- inferswarm04 `/srv/inferswarm/state/i88/`: phaseB-reference (48 cases),
  phaseC-reference (576), phaseC-reference-stress (8), phaseI-reference
  (24), invalid/, reference-margin-summary.json
- inferswarm01 `/srv/inferswarm/state/i88/`: phaseD-chain (576),
  phaseD-chain-stress (8), phaseI-chain (24), envelopes.json,
  decision-local-errors.json, calibration-summary.json,
  phaseG-semantic-adjudication.json, phaseI-failures.json,
  phaseI-holdout-verdict.json (not written — terminal failure path),
  v3-tooling/
- inferswarm03 `/srv/inferswarm/state/i88/`: phaseD-chain-stage3 (584
  cases, 4672 decision rows + captures), phaseI-chain-stage3 (24 cases),
  phaseD-laststage-final-report.json
- inferswarm01 `/srv/models/i88-scratch/`: overflow spillover of the
  stage3 evidence (disk-headroom measure; same bytes)
- Committed compact artifacts: inferswarm
  `docs/qualification/gemma4-12b-it-v3-campaign-88/` (phaseB/, phaseC/,
  phaseEF/, phaseG/, preflight-applicability.json, this report)

## Historical preservation

- R6 `R6_DENSE_ARCHITECTURE_FALSIFICATION_FAIL`: unchanged.
- #76 stopped v1 qualification: unchanged.
- #81 terminal `CALIBRATION_SEMANTIC_FAIL` (strict exact-token profile):
  unchanged and not reinterpreted — the v3 decision-stability profile is
  a different, weaker contract and its holdout failure does not alter
  #81.
- #74 holdout: permanently sealed, never reused (sha asserted unchanged).
- `EXACT_TOKENS_REQUIRED` / `BIT_EXACT_REQUIRED`: unchanged, not
  satisfied by this campaign.

## Disposition note for the maintainer

The failure is a numerical-envelope family exceedance
(final-normalized-hidden-state:rms), NOT a semantic decision-stability
failure: every semantic gate passed on all arms including the failing
case. The v3 contract treats all 15 envelopes as mandatory and
conjunctive, so the honest verdict is V3_HOLDOUT_FAIL. A failure is
evidence, not permission to change the method; any successor
methodology (e.g. a distributionally-derived envelope family) is a new
gate issue, not an amendment of this one.
