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

The repository also contains one narrow in-repo operator path
(`inferswarm/operator/`, `python -m inferswarm.operator run`), accepted under
Issue #268 for a fixed two-participant llama.cpp CUDA/RPC plan on one tested
NVIDIA topology. It launches the pinned llama.cpp runtime directly and does not
use FreeToken. FreeToken's N0 and R1-R5B work, the external Coordinator and the
dense Gemma chain remain research-internal harnesses; see the
[capability evidence matrix](../capability-evidence-matrix.md) for which results
come from which vehicle.

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
**[Issue #280 — AMD-only Vulkan same-request pooling (candidate-B-only result STOP; authorization spent)](https://github.com/Zutfen-LLC/inferswarm/issues/280)**

Issue #268 is accepted as R8K_QWEN_CUDA_ORDINARY_OPERATOR_PATH_PASS on exact reviewed head 438c09ff1f3fb0e161f0bbf6d8389554ab8a1515, merged as 4c6df96cd03e50fbb990256507eb859769536aad (https://github.com/Zutfen-LLC/inferswarm/issues/268#issuecomment-5979357776), and Issue #255 remains accepted as MVP_DISTRIBUTED_INFERENCE_PASS (https://github.com/Zutfen-LLC/inferswarm/issues/255#issuecomment-5974171991). Both are bounded to the homogeneous NVIDIA/CUDA two-host topology inferswarm01 RTX 3060 plus inferswarm04 RTX 3090, the exact Qwen3.8-Flash-Next-UD-IQ1_S release and llama.cpp b29c606e28a01b1bc8c1351026a0fa6e616bf6c4 lineage, fixed placement, and verified participant-local backing; they establish no capacity or speed advantage over the recorded single-host comparison. The Issue #188 roadmap priority of 2026-10-06 is AMD-only Vulkan same-request pooling: Issue #280 first, Issue #281 queued behind an accepted #280 result and an explicit CONTINUE decision, and Issue #279 (CUDA capacity/value proposal) open at lower priority as planning only. Issue #280 asks whether the two dies of one V340L can hold useful parts of one model and both execute one request through Vulkan. Its single-use candidate-B-only physical experiment terminated STOP: the cold request proved the same-request two-die mechanism, the warm request failed attribution admission, and the cold synchronized-copy share exceeded its frozen 20% screen. The result is bounded to one V340L, one small model that fits a single die, and one frozen placement; it is not a verdict on dual-die Vulkan execution in general.

- **Issue #280 candidate-B-only physical result observation:** [`STOP`](https://github.com/Zutfen-LLC/inferswarm/issues/280#issuecomment-6073758406).
- **Maintainer acceptance:** pending maintainer acceptance.
- **Recorded execution authorization:** blocked — No unspent physical authorization exists for Issue #280 or any other gate. The single-use candidate-B-only authorization (https://github.com/Zutfen-LLC/inferswarm/issues/280#issuecomment-6073673930) was consumed by exactly one launch and two requests and is spent; the earlier 2-launch/4-request authorization (comment 6060425902) and the eight-launch/sixteen-request campaign authority were spent before it. Living status is informational and grants no further execution authority: an observed result, a merge, or green CI never authorizes a rerun, retry, relaunch, R1 repeat, or successor, each of which requires a new explicit maintainer decision. [Authority](https://github.com/Zutfen-LLC/inferswarm/issues/280).

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

