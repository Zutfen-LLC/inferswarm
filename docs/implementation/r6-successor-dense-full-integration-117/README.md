# R6 successor dense full integration — issue #117

Status: **`ISSUE117_IMPLEMENTATION_FREEZE_PASS`** (CPU/static phase).
Physical Arms A–D and the physical preflight are **pending** on the fabric;
see [METHODOLOGY.md](METHODOLOGY.md) for the frozen execution plan.

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
- the accepted-V5-geometry candidate is selected through ordinary
  feasibility / policy / evidence gates — never hard-coded — while materially
  different candidates stay `TECHNICALLY_FEASIBLE` and/or policy-eligible but
  `QUALIFICATION_NOT_APPLICABLE`. The accepted V5 qualification record binds
  the canonical candidate produced by the ordinary strategy/catalog machinery
  (`canonical_v5_candidate` over the evidence-derived authority descriptor)
  and matches exactly that candidate — no synthetic fixture subject;
  checkpoint identity is carried as two separated, explicitly named
  identities: the accepted external `checkpoint_authority_sha256`
  (evidence-bound) and the mechanical `catalog_content_digest` (drift
  binding, enforced by the byte-verified authority attestation at
  construction);
- feasibility bytes are the exact frozen participant requirements (assigned
  plus declared shared state), so the capacity proof is truthful about the
  embedding and shared tied-head state each stage must materialize;
- participant-exact cold acquisition, verified materialization, warm restart,
  and planning-only locality mutation hold every acceptance zero-invariant;
- eighteen negative controls and six fencing negatives fail closed —
  including poisoning controls proving the derived zero-invariants (fence
  counters, host-mirror/movement bytes) become nonzero when the retained
  records are forged, and the canonical-match control proving the accepted
  V5 record matches exactly the machinery-produced canonical candidate.

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
  claims the accepted Gemma checkpoint. The accepted V5 record matches
  exactly the canonical authority-descriptor candidate produced by the
  ordinary strategy machinery — and no synthetic subject.
- The accepted V5 record binds checkpoint execution equality by the retained
  accepted `checkpoint_authority_sha256`; the retained evidence records no
  canonical catalog content identity and no content-to-authority derivation
  rule, so the candidate's `catalog_content_digest` is a machinery drift
  binding — enforced at construction by the byte-verified authority
  attestation and by plan/manifest identity — not a matched record field.
  The canonical checkpoint authority attestation for the fabric-resident
  repository is generated at physical acquisition time.
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
