# FreeToken integration

How InferSwarm relates to the
[Zutfen-LLC/FreeToken](https://github.com/Zutfen-LLC/FreeToken) fork of
FlashML-org/FreeToken.

Decision context:

- [ADR 0002](../adr/0002-freetoken-as-initial-integration-runtime.md)
- [ADR 0008](../adr/0008-canonical-fabric-doctrine.md)
- [Fabric Doctrine](../architecture/fabric-doctrine.md)
- [ROADMAP](../../ROADMAP.md)

FreeToken remains the initial proving/runtime integration vehicle. It is not the
canonical home of InferSwarm architecture and is not assumed to be the permanent
exclusive host runtime.

## Who owns what

- **InferSwarm ADRs and the Fabric Doctrine are canonical** for architecture.
- **InferSwarm issues and `ROADMAP.md` are canonical** for experiment questions,
  gates, methodology, and acceptance criteria.
- **The FreeToken fork carries focused implementation experiments** needed to
  prove those hypotheses against a real inference runtime.
- **Accepted evidence remains identified by exact commits and context** even when
  the tested implementation is never merged directly into FreeToken `main`.

Typical flow:

```text
InferSwarm issue / frozen methodology
        |
        v
FreeToken evidence or integration branch
        |
        v
physical correctness / performance evidence
        |
        v
InferSwarm gate review
        |
        v
archive evidence + extract/integrate the proven seam
```

Do not duplicate the full InferSwarm roadmap into FreeToken issues.

## Doctrine-shaped, API-unfrozen

Current implementations must preserve the Fabric Doctrine without prematurely
publishing a generalized resource/planner/strategy API.

A Qwen/NVIDIA experiment may use temporary structures named for layers,
experts, CUDA, or FreeToken-specific runtime details inside the bounded
strategy/backend implementation. Those names must not leak into the generic
InferSwarm ontology merely because the first proving vehicle uses them.

The generic concepts remain Swarm, Coordinator, Node, Compute Unit, Memory
Resource, Link, Logical State Unit/Materialization, Model Execution Strategy,
planner evidence/policy, and versioned Execution Plans/epochs.

## Historical runtime lineage through R4

The corrected post-Wayfinder FreeToken research line established:

- R0 / #48 — `P48_ACCELERATOR_RESIDENCY_PASS`;
- R1 / #50 — `R1_FROZEN_PLAN_REALIZATION_PASS`;
- R2 / #51 — `R2_LOCAL_SPLIT_EXECUTION_PASS`;
- #53 — `HOST_STAGING_RECLAMATION_PASS`;
- R3 / #55 — `R3_MINIMUM_AUTOMATIC_PLANNING_PASS`;
- R4 / #57 — `R4_MULTI_NODE_BOUNDARY_PASS`.

Canonical R4 provenance is:

```text
accepted R3 base:
2ac72d547b2a24a3672d1b83268865db5490084d

accepted R4 physical producer:
e97f60b7b0120a72a7cf9926cf6a5c558782c9b2

accepted corrected R4 evidence:
d5735c6b5075e835e7e8118922c44a7b0cf7439b

preservation branch head:
b2d72a36e79624028e74a2e7256f03546d4b8b5b
```

The earlier R4 evidence head `9a26fd2` is retained only as invalidated history;
it is not canonical evidence.

R4 also established the context-specific disposition
`R4_1GBE_PRIMITIVE_CAPACITY_VIABLE`. The accepted clean-arm workload peaked at
about `2.947 Mb/s` A→B against the frozen `747.12 Mb/s` 80%-margin limit on the
measured ordinary-1-GbE path. This does not imply that every model boundary or
network topology is 1-GbE viable.

## Branch policy

### `main`

FreeToken `main` tracks upstream FreeToken as cleanly as practical. Experimental
InferSwarm research must not casually accumulate there.

### Evidence branches

An **evidence branch** preserves the exact implementation that produced a
measured result. Accepted evidence commits are immutable historical inputs.
They are not rebased merely to make GitHub history prettier or to keep pace with
upstream.

For an accepted evidence branch:

1. freeze exact implementation and evidence SHAs;
2. record them in the corresponding canonical InferSwarm issue/result;
3. preserve enough source/artifacts to reproduce or audit the result;
4. invalidate and regenerate evidence if a correctness-bearing producer changes;
5. never infer that an accepted POC is automatically production runtime code.

### Long-lived integration branch

An **integration branch** carries the coherent current downstream implementation
used for continuing InferSwarm work. It is a new implementation context, not a
retroactive replacement for historical evidence.

Issue #59 established the durable integration line while preserving the
accepted R4 lineage and deliberately integrating upstream changes. Accepted
R5A/R5B execution followed on that line. The historical PR #20 lineage was not
a reason to merge experimental code directly into upstream-tracking `main`.

<!-- project-status:runtime:start -->
The [FreeToken fork](https://github.com/Zutfen-LLC/FreeToken) is the initial runtime vehicle.
Its durable integration branch is `inferswarm-research` ([established by #59](https://github.com/Zutfen-LLC/inferswarm/issues/59)).
Upstream-tracking `main` and immutable evidence branches have separate roles.
Execution uses the exact producer named by the current gate authority,
never an unreviewed branch tip. FreeToken is not the permanent product boundary.
<!-- project-status:runtime:end -->

## Current implementation direction

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
- Issue #280 is the active AMD-only Vulkan same-request physical campaign. Its observer/harness was CPU-validated and merged in PR #282 at cb907531493dd10ba32d601fe097fb6c3c559e70. The bounded eight-launch/sixteen-request/20-minute/$0 physical matrix is explicitly authorized by Issue #280 comment 6029667573; a pre-inference cooling-confirmation STOP consumed 0 launches/requests, and maintainer comment 6030829366 confirmed the unchanged cooling setup and authorized direct resume of the same frozen campaign. Under repository campaign-autonomy doctrine, unchanged established facts do not require repeated human reconfirmation: execution proceeds inside the frozen envelope unless a material anomaly, authority expansion, safety/integrity issue, or other substantive stop condition appears. This grants no #281, purchase, mixed-vendor, #239/R8-J, holdout, or production authority; #239 remains blocked. After the first completed physical run (8 launches / 16 requests, terminal STOP), Issue #284 corrects the exposed defects: the runner evaluates every frozen per-request acceptance/STOP condition synchronously before any subsequent launch (semantic task gate, required observer evidence per arm, peak-RSS retention, available health inputs; aborted slots consumed, no automatic rerun); the observer retention defect is root-caused to library-TU I280 events dropped by the common log callback's INFO-to-TRACE mapping at the default threshold (fixed by emitting at log level NONE in the five library TUs); and the formatting-sensitive JSON-only rubric is replaced by a frozen deterministic semantic checker. The corrected contract prepares, but does not authorize, a minimal 2-launch / 4-request physical rerun. Review round 2 (PR #285 comment 6035951310) removed event-name-presence admission: every admitted request now requires a structured PASS observer verdict mechanically validated from its retained raw bytes under the frozen physical #280 contract (two retained V340L BDFs, per-die ownership and completed compute, exact boundary occurrence/bytes/staging reconciliation); candidate cold must PASS before candidate warm executes. Review round 3 completed the frozen placement admission law: Baseline A = die 0000:07:00.0 with the FULL single-die placement (all model block layers 0-35 plus the output tensor on that die; no split); Candidate B = blocks 0-18 on 0000:07:00.0, blocks 19-35 plus the required output tensor on 0000:0b:00.0. Admissible named weight inventory must cover every frozen block layer and required tensor on exactly its contract die; missing or wrongly bound elements (including output on CPU or an alien backend) fail closed. 0-18 on die A is only the candidate half-split, never the baseline placement. Review round 4 completed the per-die KV/mutable-state ownership law: every PHYSICAL_280 arm declares placement required category kv_cache, activating the collector's existing fail-closed per-die check; Candidate B requires nonzero admissible KV inventory on both frozen V340L dies, Baseline A on its sole die; the kv_inventory event name alone never establishes ownership; CPU_FIXTURE semantics are unchanged.
<!-- project-status:frontier:end -->

The [project capability summary](../../README.md#what-the-research-has-established)
distinguishes accepted physical serving/recovery and qualification from CPU
artifact-distribution proofs awaiting physical integration.

## Evidence branch versus integration branch versus `main`

Use these terms distinctly:

- **evidence branch** — immutable implementation/evidence lineage for a frozen
  measured result;
- **integration branch** — current coherent downstream InferSwarm implementation
  expected to receive continuing development;
- **upstream-tracking `main`** — stays close to FreeToken upstream.

A proven mechanism may be adapted/extracted from an evidence branch into the
integration branch after review. That is a deliberate integration step, not an
automatic consequence of a positive benchmark.

## Extraction boundary

The desired end state remains a narrow host-engine seam. Once multiple real
experiments establish stable resource/planner/strategy/runtime boundaries,
reusable InferSwarm components should move behind that seam rather than forcing
a permanently deep FreeToken fork.

Continuing integration must keep temporary model and backend details behind
research/strategy seams. The historical R6 attempt failed; the accepted
qualification and current successor integration preserve that result while
testing the later design. Public strategy/planner APIs remain unfrozen.

Upstream FreeToken and FlashML are not involved in InferSwarm; nothing here
implies their endorsement.

