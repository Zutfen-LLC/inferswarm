# Issue #117 final A–E closure status (Issue #184)

Campaign: `issue184-final-closure-117` (CPU/docs only — no physical execution)
Issue: https://github.com/Zutfen-LLC/inferswarm/issues/184
Starting InferSwarm `main`: `1149a8ad9576ac25dfa2e474b9142c9c903ced77`
(PR #183 merge — the accepted Arm-E terminal merge)
Accepted FreeToken execution producer (unchanged, reference only):
`6202eeebcdf63e7bc8bb3498dd3c364ae42ee469`

This is the final administrative closure of the planned Issue #117 Arm A–E
sequence. It authorizes no model/GPU/CUDA execution, node access, artifact
acquisition/mutation, holdout access, remediation, requalification, or
successor campaign. It invents no new umbrella correctness terminal; every
arm-specific terminal below is the accepted terminal of record.

## Tested subject (frozen)

- Model: `google/gemma-4-12B-it`, revision
  `707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7`;
- checkpoint authority SHA-256
  `5a84cb313260ac447237b890387116dfa8682e49a6b44bc585ae8353abbff18d`;
- accepted qualification subject
  `sha256:c6b9fe721103fb041be3a5b980e73ee148f2304c8572bc50e971f7f1d7994ffd`;
- canonical candidate `dense.6171f32b4413`;
- geometry: inferswarm01/gpu-0 [0,16), inferswarm01/gpu-1 [16,32),
  inferswarm03/gpu-0 [32,48).

## Accepted Arm A–E terminals

| Arm | Terminal | Evidence PR | Acceptance merge |
|---|---|---|---|
| A | `ISSUE117_ARM_A_EXECUTION_EQUIVALENCE_PASS` | #122 | `6774474941d7ce2a0252c8c1e148f8bce61a8d6d` |
| B | `ISSUE117_ARM_B_COLD_REALIZATION_PASS` | #127 | `fed87d1b71a0794374dd58c921e31606a56a242f` |
| C (historical) | `ISSUE117_ARM_C_EVIDENCE_BLOCKER` | #128 | `718efbf5770b31c6e44eb3a8c4d0b81fd1dc9c22` |
| C (fresh, pre-remediation) | `ISSUE117_ARM_C_ORDINARY_SERVING_FAIL` | #136 | `1b83bcab0a5e682a438ca0554f71dd0ace15be55` |
| C (post-remediation) | `ISSUE117_ARM_C_ORDINARY_SERVING_PASS` | #174 | `52c3b560d560f69d0f009ed5772c1a70efc01ba2` |
| D | `ISSUE117_ARM_D_WARM_RESTART_CACHE_REUSE_PASS` | #181 | `d4d50b20205e455a195a908ee9d5ea72bc5d8d04` |
| E | `ISSUE117_ARM_E_LOCALITY_MUTATION_PASS` | #183 | `1149a8ad9576ac25dfa2e474b9142c9c903ced77` |

Supporting accepted lineage (all additive, none rewritten):

- Issue #137 diagnosis `ISSUE117_ARM_C_REGIME4_DIAGNOSIS_PARTIAL`
  (PR #138, merge `cdc23d0e8fa9d3b1b27bab5749939a5ad69b9610`);
- Issue #153 corrected remediation classification
  `ISSUE117_ARM_C_REMEDIATION_BLOCKED` (`BACKEND_REQUIRES_MULTI_CHUNK`);
- Issue #157 chunk-2 diagnosis `ISSUE117_ARM_C_CHUNK2_CAUSE_LOCALIZED`;
- Issue #166 SWA allocation remediation
  `ISSUE117_ARM_C_SWA_REMEDIATION_READY`;
- Issue #168 corpus census
  `ISSUE117_ARM_C_REQUALIFICATION_EVIDENCE_BLOCKED` (resolved by the
  #170 long-regime corpus authorization);
- Issue #170 long-remainder corpus freeze
  `ISSUE117_ARM_C_LONG_REMAINDER_CORPUS_FROZEN`.

## Arm-C fail → diagnosis → remediation → PASS history

1. The original Arm-C campaign terminated `ISSUE117_ARM_C_EVIDENCE_BLOCKER`
   (PR #128): a post-correctness-bearing methodology/evidence-admissibility
   failure (frozen comparator arms differed in runtime invocation semantics
   by design). Immutable historical truth.
2. The corrected fresh campaign (PR #136) is the accepted
   pre-remediation ordinary-serving result:
   `ISSUE117_ARM_C_ORDINARY_SERVING_FAIL` — 18/24 exact equality, six
   regime-4 committed-token divergences under complete pre-divergence
   invocation equivalence. Immutable historical truth.
3. Issue #137 localized the divergence (multi-chunk extend-prefill
   sufficiency; earliest divergence inside stage 1); Issue #157 localized
   the chunk-2 mechanism (standalone stage path never allocates SWA slots;
   all-zero sentinel mapping); Issue #166 implemented the session SWA
   allocation lifecycle remediation (CPU-proven).
4. The post-remediation requalification (Issue #172, 40-case canonical
   campaign = accepted 24-case #133 fixture + accepted #170 16-case corpus,
   producer `6202eee` verified on every participant) derived
   `ISSUE117_ARM_C_ORDINARY_SERVING_PASS` mechanically from retained bytes
   — 40/40 exact direct-vs-ordinary — accepted through PR #174. The
   historical FAILs are preserved; the PASS does not rewrite them.

## Current accepted heads

- InferSwarm `main`: `1149a8ad9576ac25dfa2e474b9142c9c903ced77` (PR #183
  merge; this closure builds on it — see the PR head for the closure
  commit).
- FreeToken accepted execution producer for the #117 lineage physical
  campaigns: `6202eeebcdf63e7bc8bb3498dd3c364ae42ee469` (the accepted #166
  remediation bytes, verified on every participant by #172; unchanged by
  this closure).

## Living status changes made by this closure

- `docs/project-status.json`: frontier prerequisite is now the accepted
  Arm-E observation/acceptance; execution state records the sequence as
  COMPLETE with no remaining execution slice; the stale Arm-D/E blocked
  and #172/#170/#168 pending-acceptance claims were corrected (history
  preserved additively).
- README.md / ROADMAP.md / ARCHITECTURE.md / docs/implementation/README.md
  / docs/protocols/README.md / docs/integrations/freetoken.md: generated
  status sections regenerated via `scripts/sync_project_status.py --write`.
- Area README stale living claims corrected (see below).
- Proposed replacement body for the closed GitHub Issue #117 retained at
  [ISSUE-117-REPLACEMENT-BODY.md](ISSUE-117-REPLACEMENT-BODY.md); Issue
  #117 itself is NOT mutated by this PR — the maintainer applies the
  replacement after merge.

## Explicit non-claims

- Closure means the planned #117 integration sequence is accepted for this
  frozen dense-Gemma subject and proving topology ONLY. It does NOT claim:
  production readiness; public API stability; generalization to arbitrary
  models, vendors, device classes, or topologies; dynamic scheduler
  quality; broader restart semantics than the tested warm-restart
  scenarios; or any new statistical qualification.
- No `h109-*` holdout material was opened, generated, copied, or used.
- No model/GPU/CUDA execution, node access, or artifact mutation occurred
  in this closure.
- The accepted historical Arm-C FAIL records remain the correct results of
  their pre-remediation campaigns; nothing in this closure rewrites
  accepted evidence.
- No successor campaign, remediation, requalification, or execution
  authorization is granted by this record; any successor requires a new
  issue and fresh authority.

## Preservation proof obligations

The focused closure test suite (`tests/test_issue184_final_closure.py`)
proves, from the working tree and git:

- every Arm A–E acceptance merge above is an ancestor of the starting head
  `1149a8a…` and its commit subject names the accepted PR;
- the retained evidence trees (`evidence/arm-a/`, `evidence/arm-b/`,
  `evidence/arm-c/`, the #137/#157 bundles, `remediation/`, the #172/#175/
  #182 areas) are byte-identical to the starting head `1149a8a…`;
- no file under any accepted evidence namespace changed in this PR;
- the closed-parent bindings (`scripts/issue117_proof.py`,
  `evidence/purity-audit.json`, `evidence/producer-hashes.json`,
  `evidence/MANIFEST.sha256`) are byte-unchanged;
- the working status record renders the accepted Arm-E prerequisite and
  contains no live "Arm D/E blocked"/"pending maintainer acceptance"
  claim;
- this closure PR touches no FreeToken path and no execution-bearing
  InferSwarm producer script.
