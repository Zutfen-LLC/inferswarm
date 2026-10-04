# R8-I6A — corrective requalification of the comparator/2 authority (Issue #273)

**Status: REPOSITORY/CPU-ONLY — corrective admission law + tests
complete; STOP for maintainer exact-head review. NO physical
execution authorized or performed.**

Successor to #270 (whose terminal
`R8I6_V340_COMPARATOR2_PHYSICAL_AUTHORITY_PASS` is INVALID as
consumable physical authority — pre-execution audit
`~/is239-a1-audit/AA-AUDIT-20261004.md`). Supersedes the unfinished
#272 tooling follow-up (folded in here).

## What was wrong (Phase 0 findings, mechanically confirmed)

1. `issue270_comparator` pinned `SELECTED_PLACEMENT_NGL = 7` for BOTH
   arms and required reference ngl == candidate ngl. The physically
   accepted reference placement is **ngl=8** — genuine RTX 3060
   receipts can never pass the frozen validator. Root cause of the
   executor substitution.
2. Arm identity was admitted from receipt LABELS (host/bdf/icd/
   subject_identity) the executor writes; process attribution (the
   only execution-bound evidence) was checked only against the
   receipt's own labels. The staged "reference" receipts carry
   `VK_ICD_FILENAMES=radeon_icd.json`, `GGML_VK_VISIBLE_DEVICES=0`,
   ngl=7 — a V340L process relabeled RTX 3060.
3. No staged→source immutable binding: identity-bearing fields were
   rewritten after capture (bdf 07:00.0→03:00.0, ICD→nvidia) without
   breaking admission.
4. No cross-arm anti-aliasing: staged reference rows were
   byte-identical to candidate rows (24/24).

## Corrections (scripts/issue273_admission.py, issue273_reducer.py)

- **Per-arm placement contract**: reference ngl=8, candidate ngl=7
  (`ARM_PLACEMENT`); a shared ngl rule is structurally invalid.
- **Arm identity from process facts**: reference must resolve through
  the NVIDIA ICD, candidate through RADV — mutually exclusive; env
  ICD/selector/host/argv cross-checked against the claimed arm;
  identity strings alone can never satisfy admission.
- **Immutable staged→source binding**: `staged_source` block (path +
  receipt digest + per-row digests); all IDENTITY_FIELDS must be
  identical between staged and source receipts; digests independently
  recomputable from retained source bytes.
- **Cross-arm anti-aliasing**: distinct server pids/argv per arm; no
  row-byte aliasing across arms (or repeats); no shared source run.
- **Per-arm determinism before pair**: `admit_pair` consumes
  reference/candidate determinism verdicts (None fails closed);
  `derive_terminal_273` returns
  `R8I6A_REFERENCE_NONDETERMINISTIC_BLOCKED` on any reference
  determinism failure regardless of candidate state.
- **#272 fold-in**: `observe_v340_host` now captures
  `mem_info_vram_total` (required by `derive_v340_identity`).
- **Corrective dispatch law**: namespace family `c273-*`
  (`c270-*` refused outright), phrase `R8I6A CORRECTIVE PHYSICAL
  DISPATCH`, merged-tooling assertion required; the full R8-I6A
  terminal vocabulary with no #270 terminal reuse.

Historical #270 evidence is preserved byte-for-byte (manifest
re-verified 280/280) and is never reclassified as valid: the
corrected law rejects the retained staged receipts mechanically
(`RetainedEvidenceFingerprintTests`).

## Phase 0 record

`phase0-forensic-reconciliation.json` — evidence digests (remote 05 +
local archive + genuine-01 reference units), holdout
SEALED_NOT_CONSUMED verification, zero-c237 proof, fresh GPU census
(reference host topology CHANGED: second 3060 gone, RX 580 co-resident
at 02:00.0; GTX 1060 bystander on 05).

## Test/CI surface

- `tests/test_issue273_admission.py` — RED-first defect record
  (against merged tooling) + corrected-law GREEN suites + reducer
  dispatch/terminal law (29 tests).
- Registered in `r8i-qwen-qualification` (plan_ci, ci_groups.json,
  ci.yml workflow, retention audit).

## Prohibitions honored

No `c237-*`, no R8-J calibration, no threshold work, no holdout
access, no historical-evidence rewrite, no relabeling of existing
outputs, no evidence choice on numerical agreement.
