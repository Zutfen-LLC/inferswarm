# Protocols and semantic execution boundaries

InferSwarm's final wire protocol does not exist yet and is **not invented
here**. These notes record constraints learned from experiments and the current
Fabric Doctrine so a future protocol is extracted from real strategy/runtime
requirements rather than frozen around one FreeToken/Qwen mechanism.

Canonical architecture:

- [ADR 0008](../adr/0008-canonical-fabric-doctrine.md)
- [Fabric Doctrine](../architecture/fabric-doctrine.md)
- [ROADMAP](../../ROADMAP.md)

## Core rule

There is no universal InferSwarm model-work message.

> **Cross-resource execution boundaries carry strategy-specific semantic
> work/state. The generic planner understands their legality and normalized
> economics, not one universal payload schema.**

A routed sparse/MoE contribution boundary, a coarse hidden-state model-stage
boundary, and a future recurrent/dense boundary may therefore use different
payloads while participating in the same resource/planning architecture.

## Execution-plan epoch requirement

Any future correctness-bearing distributed protocol must preserve the semantic
ability to associate work/results/state transitions with the Execution Plan
epoch that authorized them.

After a replacement epoch becomes authoritative for a serving scope, late work
from a retired epoch cannot mutate current state or contribute to current
outputs.

This does not freeze an `epoch_id` field name or wire encoding; it is a
correctness requirement the eventual protocol must satisfy. R5B / issue #62 was
the first physical execution of these epoch/recovery semantics and terminated
`R5B_PLAN_EPOCH_RECOVERY_PASS`, preserving epoch attribution and retired-work
fencing without freezing a public encoding.

## State authority and recovery

Protocol/runtime design must make mutable-state authority unambiguous.

A transport-visible copy of bytes does not automatically become an authoritative
replica. If a plan claims failover/recovery, freshness/coherence and the covered
failure domain must be explicit under the strategy/state contract.

A resource loss may trigger a replacement plan that uses another path, Node,
GPU, CPU/RAM, or granularity. That is a new epoch, not a silent rewrite of the
old plan's resource identity.

## Common transport goals

Where a particular semantic boundary uses an explicit transport protocol, it
will generally benefit from being:

- **versioned** — incompatible semantics/configuration fail explicitly;
- **binary-friendly** — tensor/state payloads do not traverse hot-path JSON/text
  serialization unless a bounded control message genuinely warrants it;
- **persistent where economically useful** — avoid avoidable connection/process
  setup on repeated hot boundaries;
- **compact** — framing overhead should remain small relative to semantic work;
- **correctness-aware** — model/revision/strategy/representation state cannot
  silently drift into an incompatible execution path;
- **epoch-aware** — stale work cannot mutate the active plan scope;
- **transport-independent at the semantic layer where practical** — changing
  TCP/shared-memory/P2P/etc. must not silently change what the work means;
- **measurable** — payload bytes, frequency, latency, bandwidth, contention,
  staging, and end-to-end contribution can be captured with provenance.

These are design goals, not a frozen common header.

## Historical strategy example A — fine-grained resident sparse/MoE execution

Phase1R physically proved one same-host strategy in which selected routed work
was dispatched to resident remote expert execution and contributions were
returned for deterministic reconstruction/reduction.

Its semantic information included, as applicable:

- activation state;
- selected route/execution identities;
- weights/positions required for reconstruction;
- returned contributions.

D5/D6 showed that physical work and transport should scale with actual active
routes where the backend permits it, and that fixed/dummy work can be a real
performance tax.

These facts remain valuable strategy evidence. They do **not** define a
universal `ExpertRequest` or worker protocol.

## Strategy example B — coarse contiguous model blocks

[ADR 0007](../adr/0007-coarse-model-block-partitioning-as-first-network-strategy.md)
remains accepted as InferSwarm's first network strategy/evidence direction.

R4 / issue #57 physically proved the first two-Node instance of this shape. The
accepted `[0,19) / [19,40)` Qwen split kept each region's model/runtime state
resident and exchanged two plane-major contiguous bf16 tensors (`hidden` and
`residual`) at the semantic block boundary.

The accepted R4 research transport used one persistent ordinary-TCP connection
with a bounded versioned frame and binary activation payload. That wire shape is
**evidence**, not a public protocol contract.

ADR 0008/Fabric Doctrine continues to define the scope:

- coarse blocks are a legitimate measured network strategy;
- `inter-node = contiguous block` is **not** permanent architecture;
- the strategy defines legal boundaries and the planner chooses granularity
  from measured communication/state/execution/demand economics;
- intra-node and inter-node granularities may differ;
- later strategies may expose different semantic payloads without changing the
  generic resource ontology.

## Accepted R4 transport evidence

R4 established these context-specific facts for the frozen candidate:

- physical Nodes: `inferswarm01` ↔ `inferswarm03`;
- ordinary TCP over mechanically verified negotiated 1 GbE full-duplex,
  MTU 1500, direct LAN;
- persistent connection reused across workload/session re-establishment;
- decode semantic payload: `8,192` bytes;
- max 64-row prefill semantic payload: `524,288` bytes;
- diagnostic boundary checksum equality on every checked transfer;
- clean serving-like arm excluded full-logit diagnostic transfer;
- no model-state materialization crossed the steady-state network boundary;
- fail-closed handling for protocol/session/length/layout/checksum/drift errors;
- backend-native resident execution remained active on both Nodes.

The temporary R4 header included enough identity/operation/layout/session
metadata to make the POC fail closed. Its names and encoding are not canonized.

## 1 GbE baseline

ADR 0003 remains accepted:

> ordinary **1 Gigabit Ethernet** is the baseline network target; faster
> networking may improve performance but must not be required by architecture.

R4 now provides the first accepted physical capacity evidence. Corrected
methodology measured actual clean-arm workload application demand rather than
mistaking socket-buffer timing or transport-microbenchmark capability for
demand.

For the exact R4 context:

- lower sustainable TCP direction: `933.9 Mb/s`;
- frozen 80% margin: `747.12 Mb/s`;
- peak clean-arm demand: about `2.947 Mb/s` A→B and `0.0769 Mb/s` B→A;
- retransmits: `0`;
- disposition: `R4_1GBE_PRIMITIVE_CAPACITY_VIABLE`.

That result means network **capacity** is comfortably sufficient for this exact
coarse semantic boundary. It does not guarantee acceptable latency or serving
economics for every strategy/model/concurrency level.

For retained network/serving experiments continue to measure rather than
assume:

- semantic and protocol bytes;
- boundary frequency/cadence;
- latency/RTT for the actual payload/work pattern;
- sustainable bandwidth and contention;
- serialization/copy/staging cost;
- node-local execution time;
- end-to-end service impact.

## Capability and strategy negotiation

The old issue #8 plan to freeze a universal worker/node capability contract was
retired by the resource/residency/planner Wayfinder. Do not revive it as a
protocol requirement.

A future protocol may need to negotiate enough information to establish a
specific Execution Plan/strategy implementation safely, for example:

- model/revision/strategy compatibility;
- backend/representation legality;
- relevant resource/capacity constraints;
- semantic boundary version;
- state/authority/recovery requirements;
- correctness/equivalence contract;
- transport/runtime compatibility.

The exact schema remains deliberately unfrozen. R5A reused the smallest proven
research seams necessary for static serving and did not promote the R4 wire
frame into a product protocol; the same restraint applies to the issue #117
integration.

## Transport is subordinate to semantics

Possible substrates include:

- same-host staging/device copies;
- shared memory;
- backend/device IPC or P2P;
- ordinary TCP over Ethernet;
- RDMA-style/faster network transports where measurement justifies them;
- future transport mechanisms.

A transport optimization must not become a semantic requirement for every
strategy or resource type.

Same-backend local fusion may bypass an explicit message protocol entirely while
still realizing the same higher-level Execution Plan semantics.

## Anti-patterns

Avoid treating any of the following as universal architecture:

- HTTP/JSON tensor RPC on a latency-critical hot path;
- connection/process setup per repeated execution boundary when persistence is
  available and useful;
- one network request per expert merely because the first sparse strategy used
  experts;
- moving large immutable weights as normal per-token work when useful residency
  is possible;
- moving mutable state unnecessarily when it can remain with its legal owner;
- shared-process globals masquerading as an explicit distributed boundary;
- per-operation host orchestration that destroys backend-native fast execution;
- defining generic protocol fields around CUDA/NVFP4/Qwen-specific structures;
- assuming duplicate state implies coherent failover;
- accepting late retired-epoch results;
- inventing one physical `Worker` capability schema before the runtime seam is
  supported by evidence.

## Current roadmap relationship

R4 / #57 is complete. The physical network primitive is correct, resident,
measured, and explainable.

Issues [#59](https://github.com/Zutfen-LLC/inferswarm/issues/59) and
[#60](https://github.com/Zutfen-LLC/inferswarm/issues/60) are complete. R5A
proved static end-to-end multi-Node serving through a normal host-runtime
request path with generic evidence-aware planning and an immutable selected
plan. The accepted FreeToken merge head is
`d9f45a9ef7b5f89800f96c54397202a7d43beb52`.

Issue [#62](https://github.com/Zutfen-LLC/inferswarm/issues/62) is complete with
accepted disposition `R5B_PLAN_EPOCH_RECOVERY_PASS` and accepted FreeToken
merge head `00ccd01fede8d2ad21ee83104f3b998c89ff9d1f`. It preserved
protocol-level epoch attribution and retired-work fencing without freezing a
public universal wire protocol or `epoch_id` encoding.

Issues [#64](https://github.com/Zutfen-LLC/inferswarm/issues/64) and #67 are
complete; #67 additionally proved the Coordinator is a replaceable
control-plane role rather than an implicit compute host, over a bounded
research-internal realization wire. Historical R6 / issue
[#65](https://github.com/Zutfen-LLC/inferswarm/issues/65) remains
`R6_DENSE_ARCHITECTURE_FALSIFICATION_FAIL`. Issue #71 localized the observed
numerical difference as `BACKEND_EXECUTION_LOCAL` without changing that verdict.

ADR 0010 defines the correctness contract that followed. The
[qualification lane](../qualification/README.md) then ran v1 through v5 and
terminated `V5_QUALIFICATION_PASS` at issue #110, with the single-use holdout
consumed exactly once and the #115 cleanup completed. That closed the
correctness prerequisite; it froze no protocol.

<!-- project-status:frontier:start -->
**[Issue #268 — R8-K ordinary operator-path integration (three physical requests observed; not accepted)](https://github.com/Zutfen-LLC/inferswarm/issues/268)**

Issue #255 is accepted for its bounded homogeneous NVIDIA/CUDA two-host MVP: inferswarm01 RTX 3060 plus inferswarm04 RTX 3090, exact accepted Qwen3.8-Flash-Next-UD-IQ1_S three-part release and llama.cpp b29c606e28a01b1bc8c1351026a0fa6e616bf6c4 runtime lineage, fixed/manual whole-layer placement, verified participant-local backing, and ordinary text generation/repeatability. Issue #268 advances the frontier to integrating that accepted predecessor into a reproducible ordinary operator path. At measured product head 478eb5efc93476dc2be990ac738c7ddd40e11eab, three ordinary product-path physical requests were observed on that bounded topology with fixed CPU/local CUDA/remote RPC placement, verified participant-local backing and owned cleanup; physical-stage spec PASS and quality APPROVED are review inputs, not #268 maintainer acceptance. This does not assert #268 acceptance, numerical equivalence, mixed-vendor readiness, production readiness, dynamic scheduling, performance superiority, or R8-J/Vulkan authority. The separately accepted #264 bounded pilot remains limited to its path-transition scope: four fresh-process units observed SUBGROUP/subgroup/32x1x1 to LARGE/hybrid/128x1x1 at output.weight, with both arms screening-variable; numerical root cause and H2/H3/H5 theorem closure remain open. Acceptance authority: https://github.com/Zutfen-LLC/inferswarm/issues/264#issuecomment-5969219338.

- **Issue #255 bounded CUDA/RPC MVP (accepted predecessor) observation:** [`MVP_DISTRIBUTED_INFERENCE_PASS`](https://github.com/Zutfen-LLC/inferswarm/issues/255#issuecomment-5971666116).
- **Maintainer acceptance:** [accepted](https://github.com/Zutfen-LLC/inferswarm/issues/255#issuecomment-5974171991).
- **Recorded execution authorization:** blocked — Three ordinary Issue #268 physical product-path requests were observed at measured head 478eb5efc93476dc2be990ac738c7ddd40e11eab, with physical-stage spec PASS and quality APPROVED; ordinary CI run 37169789383 succeeded on that measured head, not necessarily on this documentation head. Issue #268 is not accepted; Final CPU Validation requires maintainer GO on the exact final head and remains REQUIRED/DEFERRED. Living status is informational and grants no execution permission. No fourth or further physical request is authorized. This status grants no further execution authority.. [Authority](https://github.com/Zutfen-LLC/inferswarm/issues/268).

- The #250 predecessor remains accepted as the ARM_A_STOPS_LADDER localized boundary only; observation https://github.com/Zutfen-LLC/inferswarm/pull/251#issuecomment-5904093750 and acceptance https://github.com/Zutfen-LLC/inferswarm/issues/250#issuecomment-5904094070 remain preserved. This was not established as root cause.
- Issue #264's sole live minimal experimental selector is subgroup32→large128 hybrid for the output.weight MMV q4_K*f32 route; dimensions/types and frozen comparator identity are scoped to that candidate only. The cooperative-matrix candidate is dead; do not revive it.
- Four fresh-process units at the frozen execution head observed the actual path transition at all 10 output events per unit. BASE and candidate both differ across their two full-row digests and are screening-variable; matching candidate response tokens do not establish numerical stability or causality.
- The bounded pilot stopped at two units per arm; no third units or retry. Controller preservation verified the accepted #262 150-file inventory unchanged and 69 new retained files byte-identical across remote and local roots. The pure report's preservation field remains external-pending by design.
- Issue #266 is COMPLETED (closed completed), and PR #256 is MERGED to main as 442e2a02ce89e7fb42bceff1f7a47c8789c17733 (https://github.com/Zutfen-LLC/inferswarm/pull/256); the aggregate #254/#258/#260/#262/#264 stack is historical R8-I3C authority, not a pending review frontier. The bounded #264 result is accepted, and PR #265 merged into the aggregate producer branch as b3b28825d860b01b40f7b5697d5a50266ecaeb39 after exact-head review and Final CPU Validation on 28120bb57bfa9b8997d3d616c24e59a70f96a9af (run 37122285620). Those historical receipts are not validation receipts for the current #255 head. A source/CI/subagent PASS or additive report head grants no new physical authority. No automerge, R8-J, dead-control, or broad-matrix work is authorized.
- The completed #258 prospective theorem (merged PR #259) keeps historical A3 terminal-capability separate from hypothesis coverage: closure remains impossible, required_arms is empty, and A5 remains observationally capable but nonterminal. #260/#262/#264 use distinct instrumented source identities; their path observations do not reopen historical theorem closure.
- Issue #241 remains accepted as R8I3_COMPARATOR_V2_BLOCKED; #244 and #239 remain blocked on their Vulkan/comparator path. Issue #255's accepted capability is limited to its bounded tested homogeneous NVIDIA/CUDA two-host MVP; it establishes no numerical equivalence, mixed-vendor readiness, production readiness, or new R8-J/Vulkan execution authority. The #255 observation asserts the MVP_DISTRIBUTED_INFERENCE_PASS terminal only within that accepted scope.
- Issue #280 remains the active AMD-only Vulkan same-request gate. The historical eight-launch/sixteen-request campaign terminated STOP and its authority is spent. Issue #284 was completed via merged PR #285; accepted main is 832a9f4adcba2bebfa66f0ed5f1e004cba7fb16d. The separately authorized corrected two-launch/four-request verification also terminated STOP at R1-cold after exactly one launch and one request: semantic check PASS, observer admission FAIL; R1-warm, R2-cold and R2-warm were not_attempted. The real capture is retained unchanged, SHA256 b1fa13966a715d2009efdde4fa602a5a6f0b70d93c3884ceef0d14426bfcc796. This bounded repository correction addresses sequence-layout versus unique logical sequence identity, explicit CPU_Mapped host-buffer ownership, and Qwen2.5 tied logical-output execution evidence. Offline compatibility and adversarial tests are review inputs, not physical acceptance, performance evidence, or a new launch authorization. A synthetic-fixture PASS alone cannot authorize a campaign: the exact producer/model evidence shape requires offline compatibility proof, and the retained real R1 capture is the #280 authority. PR #286 review round 2 binds the historical legacy single-sequence inference to the exact retained capture bytes through a single-use compatibility-gate authority; projection equivalence alone never transfers it, and production runner admission requires the successor direct sequence metadata. Review round 3 closes the remaining polymorphic seams: the authority is consumed only through a non-virtual compatibility-module helper requiring exact type identity (never isinstance), an independent retained-byte SHA-256 recheck and single use, so subclasses, duck types, foreign-module instances and fabricated objects confer nothing; production admission never forwards the capability. The corrected 2-launch/4-request verification remains ON HOLD pending fresh maintainer exact-head review and explicit physical authorization. No automatic rerun, #281, #239/R8-J, holdout, mixed-vendor, purchase, hardware modification, or successor work is authorized.
<!-- project-status:frontier:end -->

No research frame becomes a public wire protocol merely because a physical
gate passes; the semantics above remain subordinate to the adopted doctrine.

