# Issue #117 — R6 successor dense full integration — methodology

Frozen before any physical correctness-bearing result. This document is the
execution plan for the gate; it is retained unmodified as physical evidence
lands. Evidence documents produced before physical work carry the disposition
`ISSUE117_IMPLEMENTATION_FREEZE_PASS`; that disposition is not the terminal
gate verdict.

## Starting state (bound)

- InferSwarm accepted base: `d37bd301a5ea361644160f92427aa75bff658b61`
  (merge of issue #115 / PR #116). Living-document synchronization happens on
  top of this base; historical evidence documents are never rewritten.
- FreeToken accepted `inferswarm-research` head:
  `b05564a7f3f7ca1b141d54842357ff2624dc6a19`, containing the accepted V5
  producers `7e5c852163afd9aadfccc406be267e8d060e79ef` (calibration) and
  `924cd22ea081f6d4ed471016faf01d427fc5b0d2` (holdout-only). Accepted V5
  execution files remain immutable comparison authority.
- Accepted V5 terminal adjudication SHA-256:
  `f024f8b3394686ff098459b657ce6dba62d7f190972663e3929ef4a574ab7a70`
  (byte hash of `docs/qualification/gemma4-12b-it-v5-campaign-110/b/holdout-adjudication.json`).
- Historical issue #65 remains `R6_DENSE_ARCHITECTURE_FALSIFICATION_FAIL`.
  This gate never reinterprets it.

## CPU/static implementation freeze (this phase)

All modules are pure stdlib and prohibited from importing torch,
transformers, Triton, CUDA, the FreeToken runtime, or performing NVIDIA
queries (house rule; enforced by review and CI).

### Modules and their contracts

- `scripts/issue117_integration_fixture.py` — builds the prospective 24-case
  integration fixture from the accepted public `c109-*` corpus: exactly one
  case per frozen mixture component, chosen by ascending
  `sha256("issue117-integration-fixture-v1\n" + case_id)` (tie: ascending
  case id). A component without a public case stops with
  `FIXTURE_CONSTRUCTION_BLOCKED` instead of changing the rule. Case bytes are
  re-verified against the accepted generator's hash rule (no tokenizer
  needed). Consumed `h109-*` material is refused by construction.
- `scripts/issue117_applicability.py` — the V5 qualification-applicability
  barrier: byte-exact pinning of the accepted V5 authority files, plus the
  closed integration-delta classification (CONTROL_ONLY,
  ARTIFACT_ACQUISITION_ONLY, PRE_MODEL_MATERIALIZATION_ONLY,
  OBSERVABILITY_ONLY, EXECUTION_MATH_AFFECTING, UNKNOWN) over the seventeen
  execution-relevant surfaces. Any math-affecting or unclassified surface
  mechanically yields `R6_SUCCESSOR_REQUALIFICATION_REQUIRED` and stops the
  gate before correctness-bearing execution.
- `scripts/issue117_gemma_strategy.py` — the strategy side of "strategy
  constrains; planner chooses": frozen subject identity (model, revision,
  checkpoint, representation, backend, execution), frozen Compute Unit
  identities from the accepted V5 evidence, legal balanced dense pipeline
  candidates for declared stage counts (1–3) as contiguous chain windows,
  exact checkpoint-catalog mapping (config + safetensors headers only; never
  weight bytes), participant-exact artifact records (tensor-scoped exact byte
  ranges; tied output head as explicitly declared shared state), and the
  opaque qualification subjects whose digests qualification evidence must
  match.
- `scripts/issue117_planner.py` — the generic planner: technical feasibility
  (operator capacity model; unknown capacity fails closed), hard operator
  policy, integrity eligibility, and the qualification-applicability gate as
  distinct, individually recorded gates; admission; per-stage locality
  ranking reusing the accepted #103 `LocalityPlanner`; deterministic
  selection with selected/lower-ranked/excluded/unranked explanations;
  `guard_participant_exact` against whole-model requirement injection; and
  the compact `ResultFence` authority (contract/session/epoch/realization/
  plan/operation/position) for serving attribution negatives. The module
  contains no model-family, product, layer-index, or campaign nouns
  (statically audited) and never imports the strategy module.
- `scripts/issue117_preflight.py` — the required physical preflight record
  and its fail-closed validator (implementation SHAs, V5 authority byte
  identity, model/backend identities, GPU UUID/product/compute-capability
  records, coordinator zero-invariants, candidate set + qualification
  applicability, applicability audit digest, integration fixture digest,
  Source descriptors, and empty dedicated-cache proofs with no
  symlink/hardlink aliasing and separate source possession).
- `scripts/issue117_proof.py` — the orchestrating CPU campaign that produced
  `evidence/` (see README). Deterministic; wall times excluded.

### CPU campaign rules

- The synthetic Gemma-shaped checkpoint proves machinery, not hardware: the
  capacity model is labeled `synthetic-scaled-capacity-v1` (usable weight
  bytes = declared fraction of the synthetic checkpoint; fractions chosen so
  a 16-layer stage fits a 3060-class CU, 24 layers do not, and the whole
  checkpoint fits only the reference 3090-class CU). Physical capacities are
  re-frozen by the physical preflight.
- Candidate enumeration is one balanced-size contiguous window per stage
  count over the frozen CU chain — nine candidates on the frozen identity.
  The accepted V5 geometry must be present (`accepted_v5_candidate` fails
  closed otherwise) and wins only through the ordinary gates.
- Qualification evidence is a deterministic record binding
  `V5_QUALIFICATION_PASS` to the exact accepted subject digest. Applicability
  is pure digest equality plus terminal-pass authority: any material subject
  change (geometry, device, backend, weights, representation) mechanically
  breaks it.
- Cold acquisition uses the accepted #99/#101 machinery with one authorized
  file Source, empty dedicated per-node caches, exact-range artifact
  records, verify-then-publish, planned materializations, and Coordinator
  reconciliation. Content-identical declared shared state is a verified
  cache hit, not a transfer.
- Warm restart binds fresh Node/Coordinator objects to the same durable
  cache roots: zero ACQUIRED weight bytes, all CACHE_HIT, identical witness
  digests.
- The locality-mutation arm is planning-only: after realization, verified
  inventory changes the selected candidate's transition economics while the
  complete gate ledger stays identical. No unqualified candidate is ever
  executed.
- Every acceptance zero-invariant is derived from retained records
  (ledger events, requirements, coverage unions, inventories, decisions) and
  must be exactly zero; negative controls prove the gates are non-vacuous.

## Physical execution plan (pending; fabric side)

Executed from the orchestrator with node access, in this order, each arm
gated on the previous:

0. **Preflight.** Freeze the physical preflight record (exact InferSwarm
   implementation SHA and clean worktree; exact FreeToken integration
   producer SHA and clean worktree; V5 authority byte identity via
   `issue117_applicability.verify_v5_authority`; exact GPU UUID/product/
   compute capability per node; torch 2.11.0+cu130 / CUDA 13.0 / driver
   610.57.04 / Triton 3.6.0 / flashinfer 0.6.17; candidate set; qualification
   applicability; Source descriptors; empty Issue #117 cache proofs;
   fixture digest; applicability audit). Validate with
   `scripts/issue117_preflight.py`. Any identity drift stops the gate.
1. **Fixture binding.** The 24-case fixture manifest is committed here
   (`evidence/integration-fixture.json`, digest
   `sha256:180185cd5c6a5dcd77b2c65979bd2c9aef4d1c7ea9fb4850a64f4508b2ba36f2`)
   before physical correctness execution; the fabric side re-fetches and
   byte-verifies it.
2. **Arm A — V5 execution-math bridge.** The integrated FreeToken producer
   executes the fixture on the accepted three-stage candidate. Compare
   against the frozen V5 authority: case identity, canonical prefix identity
   at all 8 decisions, trajectory identity where applicable, full-vocabulary
   FP32 consumer row SHA-256 at all 8 decisions, argmax/tie outputs, finite
   outputs, stage/boundary identities. Expected accounting: 24 × 8 = 192
   integrated candidate rows, 192/192 identities. Any valid mismatch is
   `R6_SUCCESSOR_EXECUTION_EQUIVALENCE_FAIL`; stop, no tuning.
3. **Arm B — canonical cold acquisition + realization.** From one frozen
   planner decision, on empty `/srv/inferswarm/{cache,materialized}/issue117/`
   roots: derive requirements, authorize exact Sources, acquire only missing
   exact artifacts Source→Node, verify/publish, materialize only planned
   state, release/reclaim staging per #53, reconcile, prove all zero
   invariants, and record exact bytes per artifact/participant/source plus
   measured wall times (kept out of hash-bound evidence until frozen).
   Manual model distribution is prohibited.
4. **Arm C — ordinary external-Coordinator serving.** The same 24 prompts
   through `client → inferswarm00 → strategy → planner → frozen plan/epoch/
   realization → Compute Nodes → attributed results → committed output`,
   compared for exact token/text/position identity against a direct-control
   invocation of the same integrated substrate. Fencing totals retained.
5. **Arm D — physical warm restart.** Restart the realization on durable
   verified caches: `warm_restart_model_weight_transfer_bytes == 0`, bounded
   fixture subset preserves Arm-C outputs.
6. **Arm E — locality mutation (planning-only).** Same as the CPU analog:
   inventory-only change, economics-only movement, gate ledger unchanged.

Terminal dispositions and invalid-run discipline follow the issue text
exactly: narrowest applicable stop state, invalid attempts retained with
reasons, no weakening after a valid unfavorable result.

## Reproduce

```sh
# fixture (from accepted corpus)
python3 scripts/issue117_integration_fixture.py \
  --corpus docs/qualification/gemma4-12b-it-v5/manifests/calibration-corpus.json \
  --out docs/implementation/r6-successor-dense-full-integration-117/evidence/integration-fixture.json

# CPU campaign (regenerates all evidence/ documents deterministically)
python3 scripts/issue117_proof.py

# applicability audit + V5 authority byte identity
python3 scripts/issue117_applicability.py --verify-authority

# focused tests
python3 -m unittest tests.test_issue117_integration_fixture \
  tests.test_issue117_applicability tests.test_issue117_gemma_strategy \
  tests.test_issue117_planner tests.test_issue117_preflight \
  tests.test_issue117_proof -v
```
