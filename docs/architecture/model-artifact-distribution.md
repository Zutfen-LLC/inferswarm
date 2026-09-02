# InferSwarm Model Artifact Distribution

Status: **Normative architecture supplement**

Adopted by [ADR 0009](../adr/0009-plan-driven-model-artifact-distribution.md).
This document specifies the model-artifact acquisition/distribution semantics
that extend the current [Fabric Doctrine](fabric-doctrine.md). If this document
and an older generic implementation note disagree on artifact acquisition, ADR
0009 and this supplement control. The final storage, manifest, daemon, and wire
APIs remain intentionally unfrozen.

Repository precedence remains:

> **ADRs decide; the Fabric Doctrine and adopted normative architecture
> supplements specify; `ARCHITECTURE.md` explains; `ROADMAP.md` sequences.**

---

## 1. Purpose

InferSwarm plans **logical model/runtime state**, not copies of model
repositories.

For a frozen model/revision/representation and Execution Plan, the distribution
layer answers:

1. which immutable source state each participant actually requires;
2. which verifiable artifact/source objects can satisfy that requirement;
3. which authorized Sources currently possess those objects;
4. how required bytes reach the participant without making the Coordinator a
   bulk-data bottleneck;
5. how acquisition is verified, resumed, cached, accounted, and reconciled;
6. how optional cached state remains distinct from active RAM/VRAM residency.

The canonical flow is:

```text
model/revision + strategy
        |
        v
legal Logical State Units / shared state
        |
        v
generic planner selects frozen Execution Plan
        |
        v
participant state requirements
        |
        v
artifact/source resolution
        |
        +--------+----------------+----------------+
        |        |                |                |
        v        v                v                v
     origin   durable store   Node cache       replica
        \        |                |                /
         \_______|________________|_______________/
                         |
                         v
              verified acquisition
                         |
                         v
              staging / transform
                         |
                         v
               Materialization
                         |
                         v
              backend execution
```

Whole-model copying may still happen deliberately, but it is never the generic
correctness prerequisite for joining a plan.

---

## 2. Canonical boundaries

Four kinds of boundary must remain explicitly separate.

### 2.1 Upstream source-file boundary

This is how a publisher/provider packages the model: repository files,
safetensors shards, archives, object-store objects, etc.

It is a source concern. It does not define planning granularity.

### 2.2 Artifact / transfer boundary

This is how InferSwarm identifies, stores, verifies, chunks, resumes, or moves
immutable bytes.

A logical artifact may correspond to one complete upstream object, one range
inside an upstream object, a deterministic transform of several inputs, or an
InferSwarm-produced internal object. Transfer chunks may be finer than artifact
identity and may exist only for movement/resume economics.

### 2.3 Logical State Unit / strategy boundary

This is model-semantic state identity and legal decomposition owned by the Model
Execution Strategy. The generic planner sees opaque units/requirements and must
not learn model-family checkpoint layout merely to distribute bytes.

### 2.4 Materialization boundary

This is the physical representation retained on a Memory Resource for a
plan/runtime role: accelerator-native packed weights, CPU-native state, another
backend representation, etc.

A Materialization may require transformation from one or more acquired source
artifacts. Artifact possession alone is not Materialization residency.

### 2.5 No accidental equivalence

Implementations may choose aligned boundaries where useful, but must not encode
any of these equivalences as generic assumptions:

```text
upstream file == Logical State Unit
upstream shard == placement unit
transfer chunk == Materialization
local checkpoint file == RAM residency
whole repository present == Node ready
```

---

## 3. Required artifact set

For each participant in a frozen Execution Plan, derive a **required artifact
set** from:

- assigned immutable Logical State Units;
- explicitly required shared/global immutable state;
- the selected legal representation/transform path;
- required backend/runtime metadata whose possession is genuinely necessary for
  realization.

The required set must not silently include unrelated model state for convenience.
Convenience preloads belong to optional cache/backing accounting.

Conceptually:

```text
participant requirement
  logical_state_ids = {A, B, C}
  shared_state_ids  = {S}
        |
        v
strategy/model resolver
        |
        v
required artifacts/ranges/transforms
  {artifact:11, artifact:42, artifact:87, shared:3}
```

The exact manifest schema is unfrozen. Whatever representation is used must be
sufficient to prove exact model/revision/representation identity and complete
required-state coverage for the plan.

---

## 4. Artifact identity and provenance

Correctness-bearing immutable artifacts require verifiable identity.
Content-addressed identity is the preferred architecture because it naturally
supports integrity verification, deduplication, cache reuse, and multi-source
retrieval, but the concrete digest algorithm/API remains unfrozen.

An artifact record must conceptually preserve enough information to answer:

- what exact bytes/object/range/transform result is this?;
- from which exact model/revision/source provenance was it derived?;
- which representation/form does it encode?;
- which Logical State Unit requirements may it satisfy?;
- what transform/version produced it, if transformed?;
- has the acquired object been verified before becoming a valid Source?;
- is it authorized for this Swarm/plan/tenant/trust context?;
- is it complete or only a partial transfer/staging object?

A filename or filesystem path is not sufficient identity.

A peer advertising that it has an artifact is evidence of availability, not
proof of integrity. Verification happens before the artifact becomes a trusted
correctness-bearing Source/materialization input.

---

## 5. Source resolution

A **Source** retains the Fabric Doctrine meaning: a currently valid origin from
which another Materialization may be made.

For immutable model artifacts, source resolution may consider:

- original provider/repository;
- operator-managed storage;
- Node-local durable artifact cache;
- another Node's verified cache;
- deliberate replica/recovery store;
- future content/object stores.

Source selection may use generic evidence such as:

- availability;
- integrity/trust status;
- authorization;
- measured/estimated path bandwidth and latency;
- current congestion/load;
- artifact locality;
- resumability;
- expected transfer/transform cost;
- operator policy.

It must not introduce model-specific placement nouns into the generic resolver.

A participant may acquire different required artifacts from different Sources.
No architectural rule requires one origin per realization.

---

## 6. Coordinator and Node responsibilities

### Coordinator / control authority

The Coordinator or current authoritative control context conceptually owns:

- the frozen Execution Plan and realization authorization;
- the participant requirement set derived from that plan;
- the trusted source/availability view used for orchestration as applicable;
- policy determining which Sources are eligible;
- audit/reconciliation of the artifacts used to satisfy the realization;
- fail-closed response to identity/provenance/authorization mismatch.

The Coordinator need not store or relay model bytes.

### Node / local agent authority

A Node-local agent/runtime may conceptually own:

- local durable cache inventory;
- local free-space/cache-eviction policy within operator limits;
- source fetching authorized by the Coordinator/control context;
- transfer resume state;
- byte/digest verification;
- staging and backend-specific transforms;
- publication of newly verified local artifact availability;
- realization into Memory Resources assigned by the plan;
- observed-state reporting for reconciliation.

The exact daemon/process/API split remains unfrozen.

---

## 7. Data-plane rule

The default architectural shape is control-plane authorization with direct
source-to-participant data movement:

```text
Coordinator
   |
   | plan + required artifact authorization
   v
Node B  <----------------------- Node A cache
   ^                                  |
   |                                  |
   +----------- origin/store ---------+
```

The Coordinator may itself be a valid Source if deliberately provisioned that
way, but that is not implied by the Coordinator role.

This preserves the external-Coordinator invariant proven by issue #67: control
authority does not require model-weight materialization or GPU dependencies on
the Coordinator.

---

## 8. Peer-assisted distribution

Torrent-like behavior is permitted and desirable where measurements support it:

- verified peers may advertise artifact availability;
- transfers may be chunked and resumable;
- different chunks/artifacts may come from different authorized Sources;
- a Node that completed verification may become a Source for another Node;
- transfer concurrency should respect path/resource/operator budgets;
- corrupted or mismatched chunks fail verification and never become trusted
  source state.

InferSwarm does not require a public DHT, public tracker, public peer discovery,
or BitTorrent-compatible protocol. Swarm membership/control already provides a
private authority context, and implementation should not add internet-P2P
complexity unless evidence requires it.

The first compliant implementation may therefore be much simpler than a torrent
client.

---

## 9. Cache semantics

A Node is **required** to retain only artifacts needed by active plans or
explicit recovery/replica policy. It may retain additional verified immutable
artifacts as optional cache state.

Optional artifact caches:

- may outlive the plan that first caused acquisition;
- are freely evictable unless explicitly promoted to a stronger replica role;
- may become valid Sources for later plans;
- may reduce future realization/reconfiguration cost;
- count against real durable-storage capacity;
- must not be confused with active RAM/VRAM residency;
- must not silently become mandatory for correctness.

Future planners may use artifact locality as evidence. For example, if two
otherwise equivalent placements exist and one already possesses all required
artifacts, lower transition/materialization cost may make it preferable. That is
an economic conclusion, not an intrinsic hardware role.

---

## 10. Transform and representation semantics

InferSwarm does not require one universal canonical packed model format.

A source artifact may be transformed into backend-native forms such as:

```text
provider checkpoint bytes
        |
        v
selected tensors/ranges
        |
        v
bounded host staging
        |
        +--> NVIDIA-native packed Materialization
        |
        +--> AMD/Vulkan-native Materialization
        |
        +--> CPU-native Materialization
```

Transforms require a correctness/provenance contract. Where useful, a transformed
immutable object may itself be retained as a cacheable artifact/source so later
realization avoids repeating conversion.

Backend-native artifact caching is legal only when compatibility context is
explicit enough that stale/incompatible packed objects cannot be reused after a
material backend/runtime/representation change.

---

## 11. Replanning and recovery

When a replacement Execution Plan introduces new participants or new state
requirements:

1. freeze the replacement plan/requirements;
2. resolve required artifacts against surviving authorized Sources;
3. reuse verified local cache hits where valid;
4. acquire missing artifacts only;
5. verify and materialize them;
6. reconcile observed state;
7. activate at the strategy-safe plan boundary under existing epoch/authority
   rules.

The recovery planner must not assume that every surviving Node owns a full model
repository.

Likewise, resource removal does not require immediately deleting cached model
artifacts from the departed plan's surviving Nodes. Cache eviction is a storage
economic/policy decision.

---

## 12. Accounting and evidence

Artifact-distribution evidence must distinguish at least:

- exact model/revision/representation identity;
- required Logical State Units per participant;
- required artifact/source set;
- bytes already present as verified local cache hits;
- bytes acquired from each Source/path;
- transfer/retry/resume bytes;
- temporary partial/staging bytes;
- final retained optional cache bytes;
- final required replica/backing bytes;
- transform/packing cost where relevant;
- RAM/VRAM Materializations created from those artifacts;
- unexplained/unplanned whole-model bytes;
- integrity failures and source quarantine/rejection;
- acquisition wall time and contribution to realization/transition time.

A future selective-acquisition proof should be able to state mechanically:

```text
participant required model-source bytes: X
participant acquired missing bytes: Y
unrelated model bytes acquired for realization: 0
unexplained full-model dependency: 0
```

where all quantities are derived from frozen manifests/evidence rather than
estimated from filenames.

---

## 13. Failure and quarantine

Artifact movement is correctness-bearing before materialization.

Digest mismatch, unexpected object identity, incompatible representation, or
untrusted provenance must fail closed. Quarantine should use the narrowest
supported scope: specific artifact/source advertisement, source Node/cache,
path, representation transform, or broader scope only when evidence supports
it.

A slow Source is not corrupt merely because it is slow. Performance affects
source economics; integrity failure affects source eligibility.

Interrupted transfers may resume only when the partial-state protocol proves
that already retained chunks/bytes correspond to the same immutable artifact
identity. Otherwise discard/restart the affected partial object rather than
stitching uncertain bytes together.

---

## 14. Security and authorization

Peer availability does not imply universal read permission.

A future implementation must preserve:

- Swarm/tenant/operator authorization for artifact acquisition;
- source provenance and exact model-license/access context where applicable;
- no accidental cross-scope exposure through peer advertisement;
- bounded resource consumption and cache quotas;
- fail-closed validation before publishing a downloaded object as a Source;
- auditability of which source supplied correctness-bearing immutable state.

This document does not select credential distribution, PKI, TLS, signed
manifests, or secret-storage mechanisms.

---

## 15. Current research posture

### Existing SCP behavior

Downloading a complete checkpoint and copying it to every proving Node remains
allowed as **temporary research/bootstrap source scaffolding**. It is not a
production recommendation and not an architectural requirement.

Generic planner/runtime code should not add new assumptions such as:

```text
assert node.has_complete_model_repository(model_id)
```

as a prerequisite for participant feasibility.

### R6

R6 continues to test selective **materialization** and dense-model generality.
It is intentionally not expanded into this distribution subsystem.

A complete frozen Gemma checkpoint may exist on participating Node-local storage
for R6, while only plan-assigned immutable state plus explicit shared/global
state is materialized. That does not violate ADR 0009 because selective network
acquisition is a separate successor proof.

### Successor proof

After R6 makes the generic state/strategy seams sufficiently trustworthy, a
separate evidence gate should prove the minimum end-to-end artifact path:

1. exact model/revision manifest;
2. frozen plan determines participant requirements;
3. participant starts without a complete local model repository;
4. resolver identifies only required artifacts/source ranges;
5. agent acquires them from one or more authorized Sources;
6. exact integrity/provenance verification;
7. bounded staging/transform into correct Materializations;
8. ordinary serving through the accepted Coordinator/plan/epoch path;
9. no unrelated model bytes acquired for realization;
10. retained cache/source accounting and restart/reuse proof;
11. controlled interrupted-transfer or corrupt-source negative arm;
12. no public protocol/CAS API frozen prematurely.

Peer-to-peer multi-source swarming should be a later optimization unless the
first proof shows that it is necessary to establish the architecture.

---

## 16. Non-decisions

This specification intentionally leaves open:

- CAS implementation and on-disk layout;
- artifact/chunk size;
- digest/hash algorithm;
- manifest schema and public API;
- whether source providers are accessed with HTTP range requests;
- whether transformed backend-native artifacts are persisted;
- peer discovery/advertisement protocol;
- transport protocol;
- concurrent source-count limits;
- cache eviction algorithm;
- replication factor/recovery policy;
- whether a dedicated artifact-store service ever exists;
- planner weighting for artifact locality;
- licensing/authentication mechanisms for upstream gated repositories.

Those choices should be extracted from evidence and real runtime needs rather
than frozen around today's SCP scripts.
