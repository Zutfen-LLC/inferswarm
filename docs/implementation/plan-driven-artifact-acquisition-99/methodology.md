# Plan-Driven Model Artifact Acquisition — Issue #99 Proof Methodology

Status: **Complete** — terminal disposition
`PLAN_DRIVEN_ARTIFACT_ACQUISITION_PASS`

This directory retains the implementation/proof record for the minimum
end-to-end plan-driven model artifact acquisition path required by
[ADR 0009](../../adr/0009-plan-driven-model-artifact-distribution.md) and
the [Model Artifact Distribution](../../architecture/model-artifact-distribution.md)
supplement. It is the ADR 0009 successor acquisition proof (§15.3); it is
deliberately **not** another model qualification campaign and makes no
numerical-qualification claim.

Machine-readable evidence lives in [evidence/](evidence/); integrity is
anchored by [evidence/MANIFEST.sha256](evidence/MANIFEST.sha256).

## Research question

> For a frozen Execution Plan, can a participant that begins **without a
> complete local model repository** realize and execute its assignment by
> acquiring only the plan-required immutable artifacts — verified for exact
> identity/provenance, resumable across interruption, cache-reusable, and
> fail-closed against wrong/corrupt/unauthorized/unrelated bytes — through a
> generic, model-independent control plane?

## Architecture under test

```text
frozen Execution Plan (R1-shaped, internal schema)
      |
      v
participant-required Logical State Units + declared shared/global state
      |                                    (generic core; model-opaque)
      v
Model Execution Strategy resolver  -----> frozen artifact records
      |                                    (byte ranges / whole objects /
      v                                     transform inputs; the ONLY place
authorized Source set (Coordinator)        with model-specific knowledge)
      |
      v
verified acquisition (direct Source -> Node; loopback HTTP with Range)
      |
      v
node-local content-addressed durable cache (verified / partial states)
      |
      v
bounded staging / transform into planned Materializations (allow-list)
      |
      v
chained execution + Coordinator reconciliation / accounting
```

Components:

- `scripts/issue99_artifact_core.py` — generic, model-independent seam:
  artifact identity/provenance records, plan-driven requirement derivation,
  CPU-only Coordinator authorization (bulk bytes mechanically rejected),
  authorized Sources, node-local content-addressed cache with
  identity-bound resumable partials, acquisition engine, accounting ledger.
- `scripts/issue99_mini_model.py` — the strategy boundary: the compact
  fixture model (`issue99/mini-lm-8l`, real safetensors-format bytes via a
  pure-stdlib codec), the LSU→artifact resolver, and the participant runtime
  that stages/executes only from verified cached artifacts.
- `scripts/issue99_proof.py` — the canonical campaign producer and evidence
  writer.

## Fixture

A deterministic compact model (frozen seed) with two safetensors shards, an
explicitly **unrelated** vision adapter and MTP head, six unassigned layers,
and a genuinely required runtime config. `model.shared.final` deliberately
resolves to **two** artifacts (non-contiguous tensors) to keep upstream-file,
artifact, and Logical State Unit boundaries distinct. The oracle execution
digest is computed by operator scaffolding reading the complete repository
(legal under ADR 0009 rule 11); canonical participants never receive it.

## Canonical arms

1. freeze exact model/revision/representation identity and the plan;
2. derive plan-driven participant requirements (coverage, provenance, no
   undeclared state);
3. the canonical participant (`exec.a`) starts with an **empty durable cache**
   and a runtime that structurally has no repository path;
4. resolve only required artifacts/ranges;
5. acquire missing bytes directly from the one authorized loopback HTTP
   Source (Range requests, 4 KiB chunks);
6. verify exact digest/provenance before publication;
7. bounded staging/transform into planned Materializations;
8. execute the chained two-partition workload (exact f32 boundary contract)
   and reconcile through the Coordinator;
9. prove `unrelated_model_bytes_acquired_for_realization == 0` and
   `unexplained_full_model_dependency == 0` mechanically from the ledger;
10. second participant (`exec.b`, same node): verified cache hits satisfy
    shared state; only its own missing state is acquired;
11. restart arm: `exec.a` re-realizes entirely from verified cache hits;
12. recovery replica (`exec.c`): controlled mid-transfer interruption, legal
    resume from the identity-bound retained prefix;
13. eleven fail-closed negative controls (see below).

## Negative controls (all must fail closed)

| Control | Expected reason |
|---|---|
| corrupt transfer data (flipped byte in flight) | `INTEGRITY_DIGEST_MISMATCH` |
| wrong model/revision provenance at derivation | `PROVENANCE_IDENTITY_MISMATCH` |
| missing required artifact at authorized Source | `SOURCE_OBJECT_UNAVAILABLE` |
| present-but-ineligible Source (zero bytes move) | `SOURCE_UNAUTHORIZED` |
| partial state bound to another artifact (discard+restart) | `PARTIAL_STATE_IDENTITY_MISMATCH` |
| reading an unverified partial as a trusted Source | `UNVERIFIED_SOURCE_READ_REFUSED` |
| publishing wrong-digest bytes as a trusted Source | `INTEGRITY_DIGEST_MISMATCH` |
| incomplete required LSU coverage at derivation | `REQUIRED_STATE_COVERAGE_INCOMPLETE` |
| unrelated whole-model requirement injection (plan- and acquisition-layer) | `UNDECLARED_REQUIREMENT_ARTIFACT` |
| unplanned staging fetch from a verified cache | `STAGING_UNPLANNED_KEY` |
| structural absence of any `has_complete_model_repository` feasibility gate | `STRUCTURAL_ABSENCE` |

Unit-level equivalents are additionally covered by
`tests/test_issue99_artifact_core.py`; the campaign records the end-to-end
arm of each control.

## Coordinator / Node boundary

The Coordinator freezes plan/requirement/Source authorization and reconciles
observed usage. Every control-plane entry point mechanically rejects `bytes`
payloads (`bytes_observed == 0` is retained evidence); bulk model bytes move
only Source → Node directly. The Coordinator is CPU-only.

## Accounting

The retained ledger distinguishes: required source bytes, verified cache-hit
bytes, newly acquired bytes (per Source), resume-reused prefix bytes,
resume-transfer bytes, temporary partial/staging bytes, integrity failures,
final optional cache bytes per node, materializations created from acquired
artifacts, boundary transfer bytes, per-participant hit/acquire splits, and
the two zero invariants. Wall-time fields are retained per arm but are not
regression identities.

## Non-claims

See `non_claims` in [evidence/canonical-summary.json](evidence/canonical-summary.json).
In brief: compact CPU fixture (no physical/GPU or serving-performance claim);
no FreeToken runtime integration in this proof (the seam is validated against
the R1-shaped plan/materialization contract with the same allow-list staging
discipline); internal schemas/digests/layouts unfrozen; one authorized Source
per artifact; no P2P/CAS/eviction/planner-locality work; issue #97 untouched
(no FreeToken tree changes, no physical hosts, no #97 evidence paths).

## Reproduction

```bash
python3 scripts/issue99_proof.py            # writes docs/.../evidence/
python3 -m unittest tests.test_issue99_artifact_core tests.test_issue99_proof -v
```

Frozen byte-identical documents across runs: `source-catalog.json`,
`frozen-plan.json`, `participant-requirements.json`. Documents carrying live
endpoints (ephemeral loopback ports) or wall times are structurally compared
after stripping those fields; tests enforce both properties.
