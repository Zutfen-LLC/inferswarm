# Issue #117 — R6 successor dense full integration — methodology

Blocked before any physical correctness-bearing result. See
[CHECKPOINT-AUTHORITY-BLOCKER.md](CHECKPOINT-AUTHORITY-BLOCKER.md). The
previous CPU/static freeze claim does not establish a non-forgeable
checkpoint-to-authority binding. Physical preflight and Arms A-E remain
pending and were not executed.

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
- `scripts/issue117_applicability.py` — the producer-bound V5
  qualification-applicability barrier. The audit applies to exactly ONE
  FreeToken integration producer SHA (`FROZEN_INTEGRATION_PRODUCER`; while no
  #117 integration producer exists, the accepted holdout producer). Its
  verdict is derived from mechanically collected delta evidence
  (`evidence/producer-delta.json`, committed input): the transitive import
  closure of the accepted V5 runner entrypoints — the correctness-bearing
  execution zone — is computed by AST parsing at both the accepted execution
  authority producer (`7e5c8521`) and the integration producer; every zone
  file is hashed at both refs; the whole tree is compared for out-of-zone
  changes. Each of the seventeen execution-relevant surfaces is classified
  from the observed per-file deltas of the files bound to it. Every dynamic
  import mechanism on the zone is statically classified: resolved
  in-repository targets (the `_pinned_tensor` extension build source, the
  in-tree `freetoken_kernel_cache` subpackage, the model registry's literal
  module paths) join the zone and are hashed at both refs; external module
  imports (`torch`, `time`) are bound to accepted runtime identities;
  `find_spec` probes are limited to the allowlisted availability probes
  (`flashinfer`, `sgl_kernel`, `vllm`) that execute no target bytes; plain
  symbol imports are distinguished from module imports and recorded as
  telemetry; declared-optional imports (`try`/`ModuleNotFoundError`) are
  telemetry; and any unresolved dynamic target or actual unresolved
  in-repository module import fails the closure. Any changed, missing,
  extra, or unprovable execution-math surface — or any zone file matching no
  surface binding — mechanically yields
  `R6_SUCCESSOR_REQUALIFICATION_REQUIRED` and stops the gate before
  correctness-bearing execution. Only the holdout admission wrappers
  (`benchmarks/inferswarm_110b/`, accepted as "admission wiring ONLY, zero
  execution/model math") and the InferSwarm-side control plane are admissible
  change surfaces. The module also byte-pins the retained physical-identity
  evidence files, freezes the exact per-Compute-Unit GPU identities
  (node, index, UUID, product, measured compute capability, role) that the
  physical preflight must match, and provides
  `accepted_checkpoint_authority_from_evidence` — the only admissible source
  of the canonical checkpoint authority identity, loaded from the byte-pinned
  retained V5 authority evidence files.
- `scripts/issue117_gemma_strategy.py` — the strategy side of "strategy
  constrains; planner chooses". Responsibilities are split by role:
  the SOURCE side (`catalog_from_repository`, `build_source_manifest`) is the
  only component that reads or hashes model bytes — whole-object hashing for
  the catalog, exact tensor ranges for artifact records — and its output is
  the small immutable descriptor manifest. The catalog carries two
  explicitly separated checkpoint identities: `checkpoint_authority_sha256`
  (the accepted external/model checkpoint identity; for canonical Gemma
  exactly the retained accepted value `5a84cb31…`, bound through the
  repository's byte-verified `checkpoint-authority.json` attestation and
  cross-checked against `accepted_checkpoint_authority_from_evidence` — never
  an unchecked config field) and `catalog_content_digest` (mechanically
  derived from the exact observed content: object digests, lengths, tensor
  layout, config). A repository claiming the canonical Gemma identity is
  additionally refused unless the attested object set matches the observed
  bytes exactly and the observed structure matches the accepted native-BF16
  48-layer tied-embedding representation. The planning waist
  (`GemmaDenseStrategy`) consumes catalog + subject + manifest and has no
  byte-access path at all; a candidate's qualification subject is derived
  mechanically from the exact catalog/plan identity and binds BOTH checkpoint
  identities, and constructing a strategy whose subject disagrees with its
  catalog fails closed — so a synthetic fixture catalog (with its own
  synthetic authority identity) can never produce an authority subject. The
  V5-shaped candidate from `canonical_v5_candidate` is a construction
  diagnostic only. The descriptor catalog is evidence-derived and
  descriptor-only. It refuses the byte-level planning surface. The shared
  execution-equality subject convention
  (`issue117_subject_identity.subject_digest`) projects the machinery-local
  `catalog_content_digest` out of the candidate digest. The retained V5
  evidence repeats a SHA but does not provide an independent checkpoint
  derivation or a complete qualification subject. The evaluator therefore
  derives `QUALIFICATION_NOT_APPLICABLE` for every physical candidate. It
  cannot admit a candidate until the checkpoint-authority blocker is resolved.
- `scripts/issue117_planner.py` — the generic planner: technical feasibility
  (operator capacity model; unknown capacity fails closed; stage bytes
  derived from the exact frozen participant requirements), hard operator
  policy, integrity eligibility, and the qualification-applicability gate as
  distinct, individually recorded gates; admission; per-stage locality
  ranking reusing the accepted #103 `LocalityPlanner`; deterministic
  selection with selected/lower-ranked/excluded/unranked explanations;
  `guard_participant_exact` against whole-model requirement injection; and
  the compact `ResultFence` authority (contract/session/epoch/realization/
  plan/operation/position) whose invalid-commit counters are derived from
  the retained committed-result ledger, never asserted. The qualification
  gate recomputes every subject digest from its own subject over the shared
  execution-equality convention (a lying caller-supplied digest is
  control-plane misuse, and machinery-local subject keys declared by the
  policy must be present on the candidate subject), validates each trusted
  record against its own subject, and binds trusted records to the policy's
  accepted terminal adjudication identity; malformed or self-inconsistent
  records are counted and never promoted. The module contains no
  model-family, product, layer-index, or campaign nouns (statically audited)
  and never imports the strategy module.
- `scripts/issue117_preflight.py` — the required physical preflight record
  and its fail-closed validator. Repository identities are mechanically
  collected Git evidence (`collect_repository_identity`: `git rev-parse
  HEAD`, `git status --porcelain`, branch telemetry only), never caller
  booleans; the validator re-checks the InferSwarm record against the actual
  checkout and the FreeToken record against its repository when supplied,
  requires the FreeToken HEAD to equal the EXACT producer the frozen
  applicability audit was built for (a random syntactically valid SHA cannot
  pass), and refuses edited records (self-identity), dirty worktrees, and
  heads that merely look valid but do not equal the observed checkout. The
  record binds one Compute Unit record per GPU — never one per node —
  carrying node, GPU index, the exact retained V5 GPU UUID, exact product,
  exact measured compute capability, role, and runtime identity, all from
  the accepted retained evidence; plus the digest-bound source descriptor
  set (each descriptor declaring an explicit local/remote source-kind) and
  candidate set, full validation (not merely digest equality) of the
  committed fixture, and mechanically collected cold-cache proofs: walked
  entry listings with lstat facts (count, bytes, symlink and hardlink
  aliases) whose aggregates the validator re-derives. Qualification
  applicability is derived, never trusted: the validator recomputes every
  candidate's execution-equality subject digest and compares it against the
  accepted V5 qualification subject independently reconstructed from
  byte-pinned historical evidence
  (`V5_QUALIFICATION_SUBJECT_PROVENANCE_RECOVERED`), deriving
  `QUALIFICATION_APPLICABLE` only on ordinary subject-digest equality. It
  refuses any retained record that disagrees with the independently derived
  verdict and fails closed whenever the evidence is missing or drifted.
  Additionally (P0 correction), the physical preflight REQUIRES the
  qualification authority: the candidate set must contain exactly one
  V5-geometry candidate, that candidate must independently derive
  `QUALIFICATION_APPLICABLE` with reason
  `MATCHED_ACCEPTED_QUALIFICATION_RECORD` against exactly the accepted
  evidence-derived record, no other candidate may claim that record without
  full execution-equality subject-digest equality, and missing, drifted,
  contradictory, or invalid accepted-subject evidence fails the preflight
  regardless of what the stored applicability records honestly say —
  `QUALIFICATION_NOT_APPLICABLE` for the V5 candidate is never a preflight
  success state. Source possession is proven, not asserted:
  every local (`file://`) Source must carry a mechanically collected
  possession record whose root exists, is not a symlink, and is disjoint
  from every participant cache and materialized root; an empty possession
  set with local Sources present cannot pass, and remote Sources must carry
  an explicit remote source-kind identity.
- `scripts/issue117_proof.py` — the orchestrating CPU campaign that produced
  `evidence/` (see README). Deterministic; wall times excluded.

### CPU campaign rules

- The synthetic Gemma-shaped checkpoint proves machinery, not hardware: the
  capacity model is labeled `synthetic-scaled-capacity-v2` (usable weight
  bytes = declared fraction of the synthetic checkpoint). The fractions are
  chosen against the exact participant-requirement accounting — a 16-layer
  stage with its embedding/shared-head state needs 42.9% of the checkpoint,
  a 24-layer stage 57.1%, and the 3060-class fraction 0.50 lies strictly
  between — so the accepted geometry is feasible and every 24-layer stage is
  infeasible through the ordinary gates. Physical capacities are re-frozen
  by the physical preflight.
- Stage feasibility bytes are the exact frozen participant requirements:
  assigned state plus declared shared state, excluding only declared
  metadata, deduplicated only by content identity within a participant.
  The legacy layers-only accounting (which missed the embedding and shared
  head) is gone; the proof cannot select a candidate whose true materialized
  bytes exceed its declared usable capacity.
- Candidate enumeration is one balanced-size contiguous window per stage
  count over the frozen CU chain — nine candidates on the frozen identity.
  The accepted V5 geometry must be present (`accepted_v5_candidate` fails
  closed otherwise) and wins only through the ordinary gates.
- Qualification evidence in the CPU campaign is a fixture-scoped record: it
  binds `V5_QUALIFICATION_PASS` to the exact synthetic subject with a
  fixture-scoped adjudication identity, and is labeled as fixture evidence.
  The V5-shaped candidate is a diagnostic. It does not establish an accepted
  qualification subject. Retained evidence lacks an independent checkpoint
  derivation and complete subject identity. Physical applicability therefore
  derives `QUALIFICATION_NOT_APPLICABLE` for every candidate. Any record that
  claims `QUALIFICATION_APPLICABLE` fails closed.
- Cold acquisition uses the accepted #99/#101 machinery with one authorized
  file Source, empty dedicated per-node caches, exact-range artifact
  records, verify-then-publish, planned materializations, and Coordinator
  reconciliation. Content-identical declared shared state is a verified
  cache hit, not a transfer. Source-side model bytes (catalog hashing plus
  manifest building) are accounted separately and never labeled as
  Coordinator traffic; Coordinator/control-plane documents are walked for
  raw byte payloads and the count is a derived zero-invariant.
- Warm restart binds fresh Node/Coordinator objects to the same durable
  cache roots: zero ACQUIRED weight bytes, all CACHE_HIT, identical witness
  digests.
- The locality-mutation arm is planning-only: after realization, verified
  inventory changes the selected candidate's transition economics while the
  complete gate ledger stays identical. No unqualified candidate is ever
  executed.
- Every acceptance zero-invariant is derived from retained records
  (ledger events, requirements, coverage unions, inventories, decisions,
  committed-result ledger, staging records) and must be exactly zero;
  negative controls poison those records and prove the derivations are
  non-vacuous (a forged wrong-session committed result derives a nonzero
  counter; poisoned host-mirror/movement records derive nonzero bytes; a
  changed execution-bearing producer stops the audit with
  `R6_SUCCESSOR_REQUALIFICATION_REQUIRED`).

## Physical execution plan (pending; fabric side)

Executed from the orchestrator with node access, in this order, each arm
gated on the previous:

0. **Preflight.** Freeze the physical preflight record: mechanically
   collected InferSwarm repository identity (HEAD `rev-parse` equal to the
   accepted implementation SHA, clean `status --porcelain`) and FreeToken
   repository identity (HEAD equal to the exact integration producer SHA the
   applicability audit was rebuilt for, clean worktree — the audit must be
   mechanically re-earned for that producer first); V5 authority + physical
   identity byte pins via
   `issue117_applicability.verify_v5_authority`; exact per-CU GPU UUID/
   product/compute-capability/role/runtime records; torch 2.11.0+cu130 /
   CUDA 13.0 / driver 610.57.04 / Triton 3.6.0 / flashinfer 0.6.17;
   digest-bound candidate set with independently derived qualification
   applicability (retained records must equal the derived verdicts); Source
   descriptors with explicit source kinds and mechanically collected source
   possession disjoint from every cold root; mechanically collected empty
   `/srv/inferswarm/{cache,materialized}/issue117/` root proofs with no
   symlink/hardlink aliasing; full fixture validation; producer-bound
   applicability audit. Validate with
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

# producer-delta evidence (requires the FreeToken repository; re-collect
# whenever the integration producer changes, then re-earn the audit)
python3 scripts/issue117_applicability.py --collect-producer-delta \
  --freetoken-root /path/to/FreeToken

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
