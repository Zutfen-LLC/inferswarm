# Issue #101 CPU orchestration methodology

Status: Frozen before canonical execution.
Implementation base: `53fb8f4c7ba3108a21f983712e5cbdb747a26600`.

This proof implements the internal lifecycle in ADR 0009.
It uses the unchanged issue #99 acquisition core.
No public API, protocol, digest algorithm, or storage layout is frozen.

## Fixture and execution

A deterministic integer fixture stores six coefficients in one upstream object.
Each Logical State Unit resolves to one four-byte range through the strategy.
Artifact IDs include exact content and provenance.
Node A starts with coefficients 1 and 2. Node B starts with 2 and 3.
Node C starts empty. The origin has all six coefficients.

Epoch 1 assigns coefficients 1, 3, and 4 to Node C.
Sources must be A, B, and origin respectively.
Epoch 2 assigns coefficients 1, 4, and 5 to Nodes A and C.
Realize A first. A must reuse 1 locally, acquire 4 from C, and acquire 5
from origin. After A publishes, C must reuse 1 and 4 locally and acquire
5 from A. C must retain optional coefficient 3. A must retain coefficient 2.
Each participant evaluates its three coefficients at input 2.
Independent reference literals are 23 for epoch 1 and 29 for epoch 2.
Materialization reads only verified cache objects and reconciles all requirements.

## Control and publication

Use complete Node inventory snapshots with artifact-specific attribution.
A trusted in-process receipt binds each snapshot to its verified publication.
The receipt is an internal capability, not a wire authentication protocol.
The Coordinator accepts only registered exact Node descriptors.
It replaces the previous snapshot and rejects snapshot sequence rollback.
It selects the first eligible peer under canonical JSON descriptor ordering.
If no peer is available, it selects the authorized origin.
Local verified cache hits take precedence.

Authorize one exact source per artifact attempt.
Bind each attempt to the frozen plan, participant, requirement, and delta.
A replacement freeze invalidates all previous attempts.
After a source failure, retain the failure and request fresh authorization.
The Coordinator may exclude that exact artifact/source pair for that plan.
No Node can authorize fallback. Interrupted data uses issue #99 resume rules.
Only successful verification and cache publication permit inventory publication.

## Required controls

Run each control in a separate temporary fixture:

1. Stale advertised object: reject the read, then explicitly authorize origin.
2. Same source ID with a drifted endpoint: reject before source reads.
3. Corrupt peer response: reject the digest and publish no object.
4. Partial transfer offered as verified inventory: reject before indexing.
5. Unapproved fallback after failure: reject before fallback reads.
6. Epoch-1 authorization after epoch-2 freeze: reject before reads.
7. Unrequired artifact: reject before reads.
8. Raw bytes and bytearray at control entry points: reject before processing.
9. Corrupt local object after inventory: reject without a cache-hit event.
10. Altered replacement requirement or delta: reject before reads.

Use only the closed issue #99 reason taxonomy.
Record failure reasons, transfer bytes, publication, and fallback authorization.

## Acceptance and custody

Derive unrequired acquisition bytes from frozen requirements and transfer events.
Derive Coordinator byte observations from the guards on valid control instances.
Derive replacement reacquisition from acquired events and pre-epoch inventory.
Derive unverified advertisement count from receipt validation and publication audit.
Retain exact descriptors, source reads, lifecycle events, cache-hit bytes,
per-epoch deltas, inventories, authorizations, and execution comparisons.
Retain producer hashes and a manifest over all evidence and local producers.
Retain exact temporary paths in exported descriptors.
For regeneration comparison, normalize the temporary root and exclude only
the authorization and attempt digests that depend on that root.
Validate all retained self-identities separately.
Exclude acquisition wall time from deterministic campaign identities.

The producer uses Python standard-library CPU operations in temporary paths.
An audit hook records file writes, network connections, and process launches.
Reject operations outside the temporary campaign paths during execution.
Do not access physical hosts, the FreeToken tree, or issue #97 evidence.
CI may read the existing frozen methodology for its required regression checks.
It must not change historical methodology or qualification evidence.
If CI changes a living file covered by an old review manifest, refresh only
that file's hash. Preserve all frozen evidence hashes.

## Verification

Run focused tests at inventory, authorization, acquisition, and delta boundaries.
Run issue #99 regression tests. Run static generic-boundary and isolation tests.
Compare regenerated evidence with retained evidence and verify manifest coverage.
Run the full repository CI in workflow order after implementation and review.
