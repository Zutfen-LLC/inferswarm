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
**[Issue #280 — AMD-only Vulkan same-request pooling (candidate-B-only result STOP; authorization spent)](https://github.com/Zutfen-LLC/inferswarm/issues/280)**

Issue #268 is accepted as R8K_QWEN_CUDA_ORDINARY_OPERATOR_PATH_PASS on exact reviewed head 438c09ff1f3fb0e161f0bbf6d8389554ab8a1515, merged as 4c6df96cd03e50fbb990256507eb859769536aad (https://github.com/Zutfen-LLC/inferswarm/issues/268#issuecomment-5979357776), and Issue #255 remains accepted as MVP_DISTRIBUTED_INFERENCE_PASS (https://github.com/Zutfen-LLC/inferswarm/issues/255#issuecomment-5974171991). Both are bounded to the homogeneous NVIDIA/CUDA two-host topology inferswarm01 RTX 3060 plus inferswarm04 RTX 3090, the exact Qwen3.8-Flash-Next-UD-IQ1_S release and llama.cpp b29c606e28a01b1bc8c1351026a0fa6e616bf6c4 lineage, fixed placement, and verified participant-local backing; they establish no capacity or speed advantage over the recorded single-host comparison. The Issue #188 roadmap priority of 2026-10-06 is AMD-only Vulkan same-request pooling: Issue #280 first, Issue #281 queued behind an accepted #280 result and an explicit CONTINUE decision, and Issue #279 (CUDA capacity/value proposal) open at lower priority as planning only. Issue #280 asks whether the two dies of one V340L can hold useful parts of one model and both execute one request through Vulkan. Its single-use candidate-B-only physical experiment terminated STOP: the cold request proved the same-request two-die mechanism, the warm request failed attribution admission, and the cold synchronized-copy share exceeded its frozen 20% screen. The result is bounded to one V340L, one small model that fits a single die, and one frozen placement; it is not a verdict on dual-die Vulkan execution in general.

- **Issue #280 candidate-B-only physical result observation:** [`STOP`](https://github.com/Zutfen-LLC/inferswarm/issues/280#issuecomment-6073758406).
- **Maintainer acceptance:** pending maintainer acceptance.
- **Recorded execution authorization:** blocked — Issue #280 has no unspent physical authorization; Issue #281 lacks a separately approved plan and physical execution authority, and Issue #279 remains planning-only. The single-use candidate-B-only authorization (https://github.com/Zutfen-LLC/inferswarm/issues/280#issuecomment-6073673930) was consumed by exactly one launch and two requests and is spent; the earlier 2-launch/4-request authorization (comment 6060425902) and the eight-launch/sixteen-request campaign authority were spent before it. Living status is informational and grants no further execution authority: an observed result, a merge, or green CI never authorizes a rerun, retry, relaunch, R1 repeat, or successor, each of which requires a new explicit maintainer decision. [Authority](https://github.com/Zutfen-LLC/inferswarm/issues/280).

- Issue #280 candidate-B-only result (comment 6073758406) executed authorization 6073673930 on accepted main c2f0396cbff20ac0c5c7ddda3412ffad43a6db26 with exactly one launch and two requests, B-cold then B-warm, a 10.479 s physical phase, and no R1 repeat, retry, replacement, or extra request. B-cold established the same-request two-die mechanism on the frozen placement (blocks 0–18 on die A; blocks 19–35 plus the tied output role on die B): die A weights 877,856,768 B (45.63%), KV 79,691,776 B, 445 completed commands; die B weights 1,046,089,728 B (54.37%), KV 71,303,168 B, 393 completed commands; forty graphs admitted; logical boundaries of 573,440 B and two host-staging legs totaling 1,146,880 B, which are logical and staging bytes rather than measured PCIe wire traffic. B-warm failed attribution admission (timeline completion identity does not match recorded event/value) and is not an admissible hardware result. Both responses passed the deterministic task rubric. B-cold synchronized copy time was 23.05% of request wall against the frozen 20% screen. Terminal STOP: the mechanism is proven for the cold request only, warm attribution failed, and no successor work is authorized.
- Issue #280 remains open and no maintainer disposition of the candidate-B-only STOP is recorded, so acceptance is pending and nothing is inferred from the result, the merged PR #296 engineering, or green CI. The result is bounded: one V340L on inferswarm05, Qwen2.5-3B-Instruct-Q4_K_M (which fits a single die, so this is a mechanism result and not a capacity result), the pinned llama.cpp b29c606e28a01b1bc8c1351026a0fa6e616bf6c4 Vulkan build with the PR #286 successor overlay, and one frozen placement. Custody is append-only: candidate-B-only evidence is retained at controller /home/zutfen/is280b-6073673930-evidence/ and host inferswarm05:/home/hermes/is280b-6073673930/ (TERMINAL.json, MANIFEST.sha256) and is not imported into this repository; the earlier r3 evidence at /home/zutfen/is280r3-evidence/ and inferswarm05:~/is280r3-physical/ is unchanged.
- Issue #289 and the merged PR #290 launcher and PR #296 kernel-verified serving-process identity mode are CPU and loopback engineering, not physical evidence; PR #296 does not change the pinned llama.cpp executable. The accepted PR #286 successor source identity and the frozen model, prompts, observer, thresholds, and STOP limits are unchanged.
- Issue #281 (V340L, RX 5600 XT and healthy RX580 Vulkan pooling) is queued behind an accepted #280 result and an explicit CONTINUE decision; neither exists, because the latest #280 result is STOP with acceptance pending. #281 has no recorded plan, plan approval, budget, or execution authorization, its first deliverable would be a concise plan, and no hardware relocation or purchase is assumed. One V340L result cannot establish multi-card scaling or justify a purchase.
- Issue #188 is roadmap authority and not an execution ticket. Its priority order is: #280, then #281 when queued, then #279 (CUDA capacity/value proposal, open and planning only). Mixed NVIDIA/AMD work is deferred, #239/R8-J remains blocked with its frozen contract and sealed holdout unchanged, and #244 is closed not-planned. No CUDA implementation or physical work is assigned.
- Research direction, not an authorization: the open capability question is a model or workload that is demonstrably infeasible under a declared single-resource envelope and is correctly executable when additional heterogeneous resources are added. It is a separate claim from GPU-residency expansion, where the single-resource comparison can still complete, and from performance. Issues #279 and #281 are the existing gates where this question would be scoped; this status creates no new prerequisite issue, experiment, or authority.
- The separately accepted #264 bounded pilot remains limited to its path-transition scope: four fresh-process units observed SUBGROUP/subgroup/32x1x1 to LARGE/hybrid/128x1x1 at output.weight, with both arms screening-variable; numerical root cause and H2/H3/H5 theorem closure remain open. Acceptance authority: https://github.com/Zutfen-LLC/inferswarm/issues/264#issuecomment-5969219338.
- The #250 predecessor remains accepted as the ARM_A_STOPS_LADDER localized boundary only; observation https://github.com/Zutfen-LLC/inferswarm/pull/251#issuecomment-5904093750 and acceptance https://github.com/Zutfen-LLC/inferswarm/issues/250#issuecomment-5904094070 remain preserved. This was not established as root cause.
- Issue #264's sole live minimal experimental selector is subgroup32→large128 hybrid for the output.weight MMV q4_K*f32 route; dimensions/types and frozen comparator identity are scoped to that candidate only. The cooperative-matrix candidate is dead; do not revive it.
- Four fresh-process units at the frozen execution head observed the actual path transition at all 10 output events per unit. BASE and candidate both differ across their two full-row digests and are screening-variable; matching candidate response tokens do not establish numerical stability or causality.
- The bounded pilot stopped at two units per arm; no third units or retry. Controller preservation verified the accepted #262 150-file inventory unchanged and 69 new retained files byte-identical across remote and local roots. The pure report's preservation field remains external-pending by design.
- Issue #266 is COMPLETED (closed completed), and PR #256 is MERGED to main as 442e2a02ce89e7fb42bceff1f7a47c8789c17733 (https://github.com/Zutfen-LLC/inferswarm/pull/256); the aggregate #254/#258/#260/#262/#264 stack is historical R8-I3C authority, not a pending review frontier. The bounded #264 result is accepted, and PR #265 merged into the aggregate producer branch as b3b28825d860b01b40f7b5697d5a50266ecaeb39 after exact-head review and Final CPU Validation on 28120bb57bfa9b8997d3d616c24e59a70f96a9af (run 37122285620). Those historical receipts are not validation receipts for the current #255 head. A source/CI/subagent PASS or additive report head grants no new physical authority. No automerge, R8-J, dead-control, or broad-matrix work is authorized.
- The completed #258 prospective theorem (merged PR #259) keeps historical A3 terminal-capability separate from hypothesis coverage: closure remains impossible, required_arms is empty, and A5 remains observationally capable but nonterminal. #260/#262/#264 use distinct instrumented source identities; their path observations do not reopen historical theorem closure.
- Issue #241 remains accepted as R8I3_COMPARATOR_V2_BLOCKED; #244 and #239 remain blocked on their Vulkan/comparator path. Issue #255's accepted capability is limited to its bounded tested homogeneous NVIDIA/CUDA two-host MVP; it establishes no numerical equivalence, mixed-vendor readiness, production readiness, or new R8-J/Vulkan execution authority. The #255 observation asserts the MVP_DISTRIBUTED_INFERENCE_PASS terminal only within that accepted scope.
<!-- project-status:frontier:end -->

No research frame becomes a public wire protocol merely because a physical
gate passes; the semantics above remain subordinate to the adopted doctrine.

