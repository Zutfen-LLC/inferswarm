# Artifact-locality transition planning — issue #103

Status: **`ARTIFACT_LOCALITY_TRANSITION_PLANNING_PASS`**.

Implementation base: `ffbc51a85dfa492b11ff8f3b0ea31b7762d6a5da`.

This CPU-only proof extends the accepted issue #99 acquisition and issue #101
orchestration seams. It does not define a public planner, artifact, path, or
wire schema.

## Frozen proof

The strategy exposes three legal candidates: A, B, and C. Each candidate has
the same technical resource capacity, policy result, and integrity result. The
strategy resolves one exact participant requirement set containing three
opaque artifacts. Each artifact has four bytes.

The Coordinator resolves each candidate through the existing exact delta and
authorization path. Verified local possession comes from a reverified Node
inventory. Missing artifacts use the exact authorized Source selected by the
issue #101 rule. Source advertisements are not local possession.

Arm A seeds two artifacts on A, one artifact on B, and no artifact on C.
Path evidence gives A and B eight bytes per second. It gives C four bytes per
second. The serialized first-order costs are 0.5, 1.0, and 3.0 seconds.

Arm B adds all three artifacts to C's verified cache. It does not change the
strategy, plan, requirements, capacity, policy, integrity, path evidence, or
execution evidence. The costs become 0.5, 1.0, and 0.0 seconds.

Execution evidence gives candidate scores of 10, 20, and 15. The declared
execution objective selects B in both inventory arms. The locality objective
selects A in Arm A and C in Arm B.

## Cost boundary

The transition objective sums `artifact.length / bandwidth` for nonlocal
artifacts. It treats each transfer as serialized. It does not model
concurrency, striping, congestion, queueing, retries, protocol behavior, or
dynamic load. Transform and materialization cost is zero because the fixture
uses one identical contract for every candidate.

Every nonzero ranking input contains source, target, path, bandwidth, version,
digest, applicability, artifact, plan, and Participant identity. Missing,
invalid, stale, or mismatched ranking evidence keeps a technically feasible
candidate as `FEASIBLE_UNRANKED`.

## Controls and custody

The campaign retains controls for unverified and corrupt local state, stale
peer advertisements, unauthorized and drifted Source descriptors, missing and
invalid bandwidth, wrong target applicability, input permutation, locality
feasibility mutation, objective contamination, and unexplained transfer bytes.

The planner module has a static purity audit. The audit rejects listed
model-family and runtime-specific nouns. The campaign uses standard-library
CPU operations only. An audit hook records file operations and rejects network
and process activity. The campaign does not access physical qualification
hosts, FreeToken, or issue #97 evidence.

The retained descriptors contain temporary paths. Those paths and timing data
are not correctness-bearing. Regeneration checks must normalize them before
comparison. The manifest covers the retained evidence and live producers.
