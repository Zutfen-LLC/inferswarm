# Plan-driven artifact orchestration — issue #101

Status: **`PLAN_DRIVEN_ARTIFACT_ORCHESTRATION_PASS`**.
Implementation base: `53fb8f4c7ba3108a21f983712e5cbdb747a26600`.

This internal CPU proof extends the accepted issue #99 acquisition core.
It implements verified Node inventory, deterministic source selection,
exact acquisition authorization, peer publication, and replacement-plan deltas.
It follows [ADR 0009](../../adr/0009-plan-driven-model-artifact-distribution.md)
and the [distribution supplement](../../architecture/model-artifact-distribution.md).

The three-Node fixture uses two frozen plan epochs.
Node C first acquires state from Nodes A and B and the origin.
Node A then acquires newly published state from C.
Node C later acquires newly published state from A.
The independent execution references match in both epochs.

| Measured CPU fixture accounting | Bytes |
|---|---:|
| Peer-cache acquisition | 16 |
| Origin acquisition | 8 |
| Verified local cache hits | 12 |
| Optional cache retained across replacement | 8 |
| Unrequired acquisition | 0 |
| Coordinator bulk-byte observations in the valid campaign | 0 |
| Replacement acquisition of already verified required state | 0 |

All ten required negative controls fail closed.
No unverified state enters advertised inventory.
The retained operation audit confines campaign file operations to temporary
paths. It records no network access or process execution.
The campaign does not access issue #97 evidence or the FreeToken tree.
This result makes no physical runtime or performance claim.
The internal receipt, descriptor, digest, storage, and API choices remain unfrozen.

- [Frozen methodology](methodology.md)
- [Canonical summary](evidence/canonical-summary.json)
- [Frozen plans, requirements, deltas, and executions](evidence/epochs.json)
- [Inventory snapshots](evidence/inventories.json)
- [Source index](evidence/source-index.json)
- [Exact authorizations](evidence/authorizations.json)
- [Acquisition and lifecycle ledger](evidence/acquisition-ledger.json)
- [Peer reuse](evidence/peer-reuse.json)
- [Negative controls](evidence/negative-controls.json)
- [Isolation audit](evidence/isolation.json)
- [Producer hashes](evidence/producer-hashes.json)
- [Integrity manifest](evidence/MANIFEST.sha256)

Reproduce the evidence with:

```bash
python3 scripts/issue101_proof.py
python3 -m unittest tests.test_issue101_orchestration tests.test_issue101_proof -v
```

Retained descriptors contain the exact temporary paths used in the campaign.
Regeneration checks normalize those paths and exclude the authorization and
attempt digests that depend on them. Separate tests validate those digests.
Plans, participant requirements, deltas, artifact identities, and accounting
remain deterministic. Acquisition wall times are excluded from this proof.

The existing issue #74 and #99 review manifests cover living CI and index files.
Only the hashes for those changed living files are refreshed.
Historical methodology and evidence files remain unchanged.
