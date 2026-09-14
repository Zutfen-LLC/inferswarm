# PROPOSED replacement body for Issue #117 — COMPLETE/ACCEPTED

Status: **DRAFT — maintainer applies after the Issue #184 closure PR merges.**
Do NOT edit Issue #117 from the agent lane; this file is the exact proposed
replacement body, prepared by Issue #184.

---

## Status

**COMPLETE / ACCEPTED — PLANNED ARM A–E SEQUENCE CLOSED**

The planned Issue #117 R6 successor dense full integration sequence is
complete and accepted for the frozen tested subject and topology. There is
no remaining Issue #117 execution slice. This issue is closed; the final
administrative closure is Issue #184 (CPU/docs only).

Canonical closure summary:
[`docs/implementation/r6-successor-dense-full-integration-117/FINAL-STATUS.md`](https://github.com/Zutfen-LLC/inferswarm/blob/main/docs/implementation/r6-successor-dense-full-integration-117/FINAL-STATUS.md)

## Accepted Arm A–E terminals

- **Arm A** — `ISSUE117_ARM_A_EXECUTION_EQUIVALENCE_PASS`
  (PR #122, merge `6774474941d7ce2a0252c8c1e148f8bce61a8d6d`):
  192/192 exact FP32 consumer-row identities on the frozen public fixture.
- **Arm B** — `ISSUE117_ARM_B_COLD_REALIZATION_PASS`
  (PR #127, merge `fed87d1b71a0794374dd58c921e31606a56a242f`):
  canonical cold acquisition + realization, all 15 mandatory zero
  invariants zero.
- **Arm C** — historical fail → diagnosis → remediation → PASS lineage:
  - original campaign `ISSUE117_ARM_C_EVIDENCE_BLOCKER`
    (PR #128, merge `718efbf5770b31c6e44eb3a8c4d0b81fd1dc9c22`) —
    immutable historical truth;
  - corrected fresh campaign `ISSUE117_ARM_C_ORDINARY_SERVING_FAIL`
    (PR #136, merge `1b83bcab0a5e682a438ca0554f71dd0ace15be55`) —
    immutable historical truth;
  - diagnosis chain #137 (`ISSUE117_ARM_C_REGIME4_DIAGNOSIS_PARTIAL`),
    #153 (`ISSUE117_ARM_C_REMEDIATION_BLOCKED`), #157
    (`ISSUE117_ARM_C_CHUNK2_CAUSE_LOCALIZED`), #166
    (`ISSUE117_ARM_C_SWA_REMEDIATION_READY`);
  - post-remediation requalification `ISSUE117_ARM_C_ORDINARY_SERVING_PASS`
    (Issue #172; accepted PR #174, merge
    `52c3b560d560f69d0f009ed5772c1a70efc01ba2`): 40/40 exact
    direct-vs-ordinary on committed ids, stopping, decoded bytes, and the
    per-call invocation seam.
- **Arm D** — `ISSUE117_ARM_D_WARM_RESTART_CACHE_REUSE_PASS`
  (Issue #175; accepted PR #181, merge
  `d4d50b20205e455a195a908ee9d5ea72bc5d8d04`).
- **Arm E** — `ISSUE117_ARM_E_LOCALITY_MUTATION_PASS`
  (Issue #182; accepted PR #183, merge
  `1149a8ad9576ac25dfa2e474b9142c9c903ced77`).

## Frozen subject

Model `google/gemma-4-12B-it` @ `707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7`;
checkpoint authority
`5a84cb313260ac447237b890387116dfa8682e49a6b44bc585ae8353abbff18d`;
qualification subject
`sha256:c6b9fe721103fb041be3a5b980e73ee148f2304c8572bc50e971f7f1d7994ffd`;
candidate `dense.6171f32b4413`; geometry inferswarm01/gpu-0 [0,16),
inferswarm01/gpu-1 [16,32), inferswarm03/gpu-0 [32,48).

## Non-claims

Closure is scoped to this frozen subject and the tested RTX-3060-class
proving topology. It claims no production readiness, no public API
stability, no arbitrary model/vendor/topology generalization, no dynamic
scheduler quality, no broader restart semantics, and no new statistical
qualification. No `h109-*` holdout material was used. Historical FAIL
records remain the correct results of their campaigns.

## Successors

Any successor work (new model/vendor, new topology, dynamic scheduling,
productionization) requires a NEW issue with fresh authority. Nothing in
this issue authorizes execution.
