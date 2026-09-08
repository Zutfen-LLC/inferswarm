# R6 successor dense full integration — issue #117

Current state: **`ISSUE117_ARM_A_EXECUTION_EQUIVALENCE_PASS`** (retained
Arm A evidence: `evidence/arm-a/`, bounded by `evidence/MANIFEST.sha256`;
see `evidence/arm-a/run-record.json`). Arm A executed 2026-09-08 on the
fabric from accepted main `51c8adee` with the frozen integration producer
`924cd22e`: the 24-case public fixture ran through BOTH the accepted V5
control authority (FreeToken `7e5c8521`: reference on inferswarm04 RTX
3090 + teacher-forced three-stage chain 01 GPU-0/GPU-1 → 03) AND the
integrated producer `924cd22e` (same topology), and all
**192/192 FP32 consumer-row identities matched exactly** — plus prefix
identity at every decision, trajectory identity, argmax/tie rule outputs
and rule proofs, stage-boundary capture-record identities, finite-output
accounting (0 NaN/Inf both arms both paths), and byte-identical raw
decision rows re-verified on the nodes (192/192 last-stage, 192/192
reference, summary-SHA-bound). Two invalid launch attempts (staging
error; dead last-stage service) produced no correctness-bearing
observation and are retained with reasons. Arm B was NOT executed; the
dedicated cold roots remain empty and untouched. No holdout material was
used.  Arm A is ACCEPTED by the maintainer via merge
`6774474941d7ce2a0252c8c1e148f8bce61a8d6d` (PR #122); the current
authorized gate is Arm B — canonical cold acquisition + realization
(authority: Issue #117) — and it is not yet executed.

Retention/provenance correction (PR #122, same day, no physical execution):
the terminal classification is now INDEPENDENTLY re-derivable from low-level
retained records by `scripts/issue117_arm_a_evidence.py` (the Arm-A evidence
reducer — pure stdlib, fails closed). New retained evidence under
`evidence/arm-a/`: `paired-decision-records.json` (independently sourced
control/integrated values for all 192 candidate + 192 reference decisions —
prefix length/SHA, emitted token, argmax rule, rule proof, row SHA, element
count; equality is only ever DERIVED from the two retained sides),
`capture-manifest-records.json` (the full frozen stage-boundary
capture-record lists for all 24 cases, both arms, stages 1-3),
`raw-row-manifest-laststage03.json` and `raw-row-manifest-reference04.json`
(per-decision raw FP32 byte verification: paths, sizes, SHA-256s, byte
identity, and mechanical binding to the decision-table row SHAs and the
reference summaries), `attempt-lineage.json` (distinct retained logical
identities for the two invalid integrated launches and the valid run, with
digest-bound transcript excerpts, harness-semantics termination proofs,
mechanically derived zero-correctness counts, and honest cleanup lineage),
and `prerun-revalidation.json` (the pre-Arm-A fabric/repository revalidation
as a digest-bound machine record with exact observed timestamps, replacing
the prior prose summary). 33 mutation negative-controls exercise every trust
boundary against the reducer. The historical Arm-A evidence bytes (witness,
decision table, run indexes, fixture, verify-rows aggregates) are unchanged;
`run-record.json` gained pointers to the mechanical records and exact
timestamps. Accepted #118 canonical-summary and physical-preflight bytes are
pinned unchanged.

Prior state: **`ISSUE117_PHYSICAL_PREFLIGHT_PASS`** (retained physical
preflight record: `evidence/physical-preflight.json` and
`evidence/physical-preflight-record.json`). Both retained-evidence blockers
were recovered — `V5_CHECKPOINT_AUTHORITY_PROVENANCE_RECOVERED` (PR #119)
and `V5_QUALIFICATION_SUBJECT_PROVENANCE_RECOVERED` (PR #120; see
[CHECKPOINT-AUTHORITY-BLOCKER.md](CHECKPOINT-AUTHORITY-BLOCKER.md) for both
resolution sections). The accepted #118 terminal evidence
(`evidence/canonical-summary.json`, `ISSUE117_IMPLEMENTATION_FREEZE_BLOCKED`)
is preserved byte-for-byte as the accurate historical record of the state
when #118 was accepted; it is never rewritten. The physical preflight was
executed on the real fabric (inferswarm00/01/03/04) at the exact accepted
base `d127879a` with FreeToken at the frozen integration producer
`924cd22e` and observed `PREFLIGHT_VALID` with zero failures; Arms A-E were
NOT executed. The physical execution gate is not unblocked until this
preflight PASS is reviewed/accepted by the maintainer.

This phase proves, before any physical correctness-bearing execution, that
the accepted architecture seams compose exactly as the #117 gate requires —
on a Gemma-shaped synthetic checkpoint at fixture scale, with the accepted
#99/#101/#103 machinery doing the real acquisition, orchestration, and
ranking work:

- the producer-bound applicability audit covers exactly one FreeToken
  integration producer SHA, derived from mechanically collected per-file
  delta evidence over the import-closed correctness-bearing execution zone
  (`evidence/producer-delta.json`): all fifteen execution-bearing surfaces
  are provably byte-identical, every dynamic import mechanism on the zone is
  statically classified (resolved in-repository targets are zone members
  hashed at both producers; external module imports are bound to accepted
  runtime identities; `find_spec` probes are allowlisted availability
  probes), and the only observed zone delta is the accepted holdout admission
  wrappers; any changed, missing, extra, unknown, or dynamically unresolved
  execution-math surface mechanically yields
  `R6_SUCCESSOR_REQUALIFICATION_REQUIRED`;
- the generic admission planner extends the accepted R3 rule with the #117
  qualification-applicability barrier as a distinct recorded gate; every
  subject digest is recomputed from its own subject over the shared
  execution-equality convention and every trusted record is bound to the
  accepted terminal adjudication identity;
- the accepted V5 qualification subject is independently reconstructed
  from byte-pinned historical evidence
  (`V5_QUALIFICATION_SUBJECT_PROVENANCE_RECOVERED`;
  `evidence/accepted-v5-qualification-subject.json`,
  `scripts/issue117_accepted_subject.py`). The canonical V5 candidate is
  `QUALIFICATION_APPLICABLE` through ordinary subject-digest equality with
  that recovered subject — not candidate ID, geometry name, or hard-coded
  selection — and every materially different candidate stays
  `QUALIFICATION_NOT_APPLICABLE`. Checkpoint identity keeps its two named
  values: the accepted external `checkpoint_authority_sha256` (bound by the
  retained evidence + PR #119 recovery) and the machinery-local
  `catalog_content_digest`;
- feasibility bytes are the exact frozen participant requirements (assigned
  plus declared shared state), so the capacity proof is truthful about the
  embedding and shared tied-head state each stage must materialize;
- participant-exact cold acquisition, verified materialization, warm restart,
  and planning-only locality mutation hold every acceptance zero-invariant;
- physical preflight (P0 correction) mechanically REQUIRES the canonical
  V5-geometry candidate to independently derive `QUALIFICATION_APPLICABLE`
  with reason `MATCHED_ACCEPTED_QUALIFICATION_RECORD` against exactly the
  accepted evidence-derived record: an honestly regenerated
  `QUALIFICATION_NOT_APPLICABLE` for the V5 candidate, missing/drifted
  subject evidence, zero or duplicate V5-geometry candidates, and foreign
  record-id claims all fail the preflight;
- nineteen negative controls and six fencing negatives fail closed —
  including poisoning controls proving the derived zero-invariants (fence
  counters, host-mirror/movement bytes) become nonzero when the retained
  records are forged, the subject-provenance-recovered control proving the
  accepted subject loads from byte-pinned evidence with no candidate
  machinery, and the subject-evidence-tampering control proving drifted
  evidence fails closed.

| CPU fixture accounting | Value |
|---|---:|
| Frozen fixture cases | 24 (one per mixture component) |
| Legal candidates enumerated | 9 |
| Admissible + selected (the accepted-V5-geometry candidate, fixture-scoped record) | 1 |
| Excluded: capacity-infeasible (exact participant-requirement bytes) | 6 |
| Excluded: hard policy (reference-reserved path) | 3 |
| Excluded: qualification not applicable (subject-digest mismatch) | 8 (overlaps above) |
| Cold transferred bytes (stage-1 / stage-2 / stage-3) | 98,668 / 65,536 / 98,732 |
| Cold cache-hit bytes (declared shared state, acquired once) | 364 |
| Source-side model bytes read for catalog/manifest building | 498,604 |
| Coordinator bulk artifact bytes observed | 0 |
| Warm restart model-weight transfer bytes | 0 |
| Fenced committed results / rejected fence violations | 48 / 6 |
| Derived zero-invariants | 25, all mechanically zero |
| Negative controls | 18 + 6, all fail closed |

The applicability audit is bound to `FROZEN_INTEGRATION_PRODUCER`
(`924cd22ea081f6d4ed471016faf01d427fc5b0d2`, the terminal accepted producer
state); any future #117 integration producer requires mechanically
re-collecting the producer-delta evidence and re-earning the audit for that
exact SHA before the physical preflight can pass. The thirteen accepted V5
authority files and the three retained physical-identity evidence files are
pinned byte-exact; drift is a hard stop. The 24-case integration fixture is
frozen with digest
`sha256:180185cd5c6a5dcd77b2c65979bd2c9aef4d1c7ea9fb4850a64f4508b2ba36f2`.

## Non-claims

- No physical execution, transfer, serving, or performance claim. The fabric
  arms require the orchestrator and inferswarm01/03/04; this phase was
  produced without fabric access by design (CPU/static freeze first).
- No statistical qualification claim; no V5 threshold is reused or relaxed.
- The CPU qualification record is fixture-scoped: it binds the synthetic
  fixture subject with a fixture-scoped adjudication identity and never
  claims the accepted Gemma checkpoint. The V5-shaped diagnostic candidate
  does not supply qualification authority.
- The retained `checkpoint_authority_sha256` has a recovered independent
  content-to-authority derivation rule (PR #119:
  `V5_CHECKPOINT_AUTHORITY_PROVENANCE_RECOVERED`): the authority is exactly
  `sha256(model.safetensors bytes)` at the checkpoint repository root,
  mechanically derived by `scripts/issue117_checkpoint_authority.py` over
  the actual bytes. The candidate's `catalog_content_digest` remains a
  machinery-local drift binding over the exact bytes the machinery observed
  — a different identity that must never be presented as, or substituted
  for, the recovered external checkpoint authority.
- The synthetic capacity model proves planner machinery, not hardware
  limits; the physical preflight re-freezes real capacities.
- Source-side catalog/manifest building reads and hashes model bytes by
  design; that accounting is kept separate and is never Coordinator
  traffic. Coordinator/control-plane documents carry descriptors only.
- The producer-delta zone closure statically resolves every dynamic import
  mechanism: resolved in-repository targets are zone members hashed at both
  producers; external module imports are bound to accepted runtime
  identities; `find_spec` probes are allowlisted availability probes that
  execute no target bytes; unresolved dynamic targets or actual unresolved
  in-repository module imports fail the closure closed. Residual non-claim:
  probe-gated backend selection (`sgl_kernel`/`vllm`) is admission logic;
  the accepted V5 dense path selects none of the probed backends.
- No public planner, artifact, path, or wire schema is frozen.
- No consumed `h109-*` material is used; the fixture uses only public
  `c109-*` cases and the fixture manifest commits no model weights.

## Evidence

Reproduce everything with `python3 scripts/issue117_proof.py` (deterministic;
wall times excluded).

- [Frozen methodology](METHODOLOGY.md)
- [Canonical summary](evidence/canonical-summary.json)
- [Integration fixture](evidence/integration-fixture.json)
- [Producer delta (mechanically collected)](evidence/producer-delta.json)
- [Strategy: legal candidates, feasibility, subjects](evidence/strategy.json)
- [Qualification record binding the fixture subject](evidence/qualification-record.json)
- [Documentation synchronization record](evidence/documentation-synchronization.json)
- [Applicability audit](evidence/applicability-audit.json)
- [Planner decision and explanations](evidence/planner-decision.json)
- [Frozen requirements](evidence/requirements.json)
- [Cold acquisition + accounting](evidence/cold-acquisition.json)
- [Materialization witnesses](evidence/materialization-witnesses.json)
- [Warm restart](evidence/warm-restart.json)
- [Locality mutation (planning-only)](evidence/locality-mutation.json)
- [Fencing record](evidence/fencing.json)
- [Negative controls](evidence/negative-controls.json)
- [Zero-invariants](evidence/zero-invariants.json)
- [Planner purity audit](evidence/purity-audit.json)
- [Producer hashes](evidence/producer-hashes.json)
- [Integrity manifest](evidence/MANIFEST.sha256)

Internal record, digest, cache-layout, and descriptor choices remain
unfrozen and implementation details.
