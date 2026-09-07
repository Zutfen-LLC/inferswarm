# R6 successor dense full integration — issue #117

Status: **`ISSUE117_IMPLEMENTATION_FREEZE_PASS`** (CPU/static phase).
Physical Arms A–D and the physical preflight are **pending** on the fabric;
see [METHODOLOGY.md](methodology.md) for the frozen execution plan.

This phase proves, before any physical correctness-bearing execution, that
the accepted architecture seams compose exactly as the #117 gate requires —
on a Gemma-shaped synthetic checkpoint at fixture scale, with the accepted
#99/#101/#103 machinery doing the real acquisition, orchestration, and
ranking work:

- the generic admission planner extends the accepted R3 rule with the #117
  qualification-applicability barrier as a distinct recorded gate;
- the exact V5 candidate is selected through ordinary feasibility / policy /
  evidence gates — never hard-coded — while materially different candidates
  stay `TECHNICALLY_FEASIBLE` and/or policy-eligible but
  `QUALIFICATION_NOT_APPLICABLE`;
- participant-exact cold acquisition, verified materialization, warm restart,
  and planning-only locality mutation hold every acceptance zero-invariant;
- twelve negative controls and six fencing negatives fail closed, proving the
  gates are non-vacuous.

| CPU fixture accounting | Value |
|---|---:|
| Frozen fixture cases | 24 (one per mixture component) |
| Legal candidates enumerated | 9 |
| Admissible + selected (the exact V5 candidate) | 1 |
| Excluded: capacity-infeasible | 4 |
| Excluded: hard policy (reference-reserved path) | 2 |
| Excluded: qualification not applicable (also policy-excluded) | included above |
| Cold transferred bytes (stage-1 / stage-2 / stage-3) | 98,660 / 65,536 / 98,724 |
| Cold cache-hit bytes (declared shared state, acquired once) | 356 |
| Coordinator bulk artifact bytes observed | 0 |
| Warm restart model-weight transfer bytes | 0 |
| Fenced committed results / rejected fence violations | 48 / 6 |
| Derived zero-invariants | 21, all mechanically zero |
| Negative controls | 12 + 6, all fail closed |

The integration-delta audit classifies all seventeen execution-relevant
surfaces as control-plane, artifact-acquisition, pre-materialization, or
observability only. The thirteen accepted V5 authority files are pinned
byte-exact; drift is a hard stop. The 24-case integration fixture is frozen
with digest `sha256:180185cd5c6a5dcd77b2c65979bd2c9aef4d1c7ea9fb4850a64f4508b2ba36f2`.

## Non-claims

- No physical execution, transfer, serving, or performance claim. The fabric
  arms require the orchestrator and inferswarm01/03/04; this phase was
  produced without fabric access by design (CPU/static freeze first).
- No statistical qualification claim; no V5 threshold is reused or relaxed.
- The synthetic capacity model proves planner machinery, not hardware
  limits; the physical preflight re-freezes real capacities.
- No public planner, artifact, path, or wire schema is frozen.
- No consumed `h109-*` material is used; the fixture uses only public
  `c109-*` cases and the fixture manifest commits no model weights.

## Evidence

Reproduce everything with `python3 scripts/issue117_proof.py` (deterministic;
wall times excluded).

- [Frozen methodology](methodology.md)
- [Canonical summary](evidence/canonical-summary.json)
- [Integration fixture](evidence/integration-fixture.json)
- [Strategy: legal candidates, feasibility, subjects](evidence/strategy.json)
- [Qualification record binding V5](evidence/qualification-record.json)
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
