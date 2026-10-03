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
**[Issue #266 — aggregate R8-I3C mainline review; bounded #264 H5 result accepted](https://github.com/Zutfen-LLC/inferswarm/issues/266)**

The #264 pilot at execution head 3040a92ccdf278d816a0324ff8fd8317f84d2d34 observed a bounded output.weight MMV path transition in four fresh-process units: SUBGROUP/subgroup/32x1x1 to LARGE/hybrid/128x1x1, with both arms screening-variable. The maintainer accepted for the bounded scope at https://github.com/Zutfen-LLC/inferswarm/issues/264#issuecomment-5969219338; numerical root cause, general H5 capability, and H2/H3/H5 theorem closure remain open. Issue #266 reviews the aggregate #254/#258/#260/#262/#264 stack against main without new experiments.

- **Accepted #250 predecessor anchor: Arm-A localized boundary (preserved, not root-cause evidence) observation:** [`ARM_A_STOPS_LADDER`](https://github.com/Zutfen-LLC/inferswarm/pull/251#issuecomment-5904093750).
- **Maintainer acceptance:** [accepted](https://github.com/Zutfen-LLC/inferswarm/issues/250#issuecomment-5904094070).
- **Recorded execution authorization:** blocked — No further physical work is authorized under #250; no B/C/C1/C2/D work is required or authorized under that predecessor. The bounded #264 pilot at exact execution head 3040a92ccdf278d816a0324ff8fd8317f84d2d34 is completed and accepted for its path-transition scope only. No further physical execution is authorized. Issue #266 is repository/CPU-only aggregate finalization; PR #256 remains OPEN / UNMERGED for maintainer exact-head review, and this status grants no further execution authority. [Authority](https://github.com/Zutfen-LLC/inferswarm/issues/266).

- The #250 predecessor remains accepted as the ARM_A_STOPS_LADDER localized boundary only; preserve its observation and acceptance anchors, and retain that this was not established as root cause.
- Issue #264's sole live minimal experimental selector is subgroup32→large128 hybrid for the output.weight MMV q4_K*f32 route; dimensions/types and frozen comparator identity are scoped to that candidate only. The cooperative-matrix candidate is dead; do not revive it.
- Four fresh-process units at the frozen execution head observed the actual path transition at all 10 output events per unit. BASE and candidate both differ across their two full-row digests and are screening-variable; matching candidate response tokens do not establish numerical stability or causality.
- The bounded pilot stopped at two units per arm; no third units or retry. Controller preservation verified the accepted #262 150-file inventory unchanged and 69 new retained files byte-identical across remote and local roots. The pure report's preservation field remains external-pending by design.
- The bounded #264 result is accepted, and PR #265 merged into the aggregate producer branch as b3b28825d860b01b40f7b5697d5a50266ecaeb39 after exact-head review and Final CPU Validation on 28120bb57bfa9b8997d3d616c24e59a70f96a9af (run 37122285620). Issue #266 requires aggregate exact-head CI and Full CPU Validation of the final mainline candidate; the child result is not a validation receipt for a different aggregate head. PR #256 remains OPEN / UNMERGED pending maintainer exact-head review. A source/CI/subagent PASS or additive report head grants no new physical authority. No automerge, R8-J, dead-control, or broad-matrix work is authorized.
- The completed #258 prospective theorem (merged PR #259) keeps historical A3 terminal-capability separate from hypothesis coverage: closure remains impossible, required_arms is empty, and A5 remains observationally capable but nonterminal. #260/#262/#264 use distinct instrumented source identities; their path observations do not reopen historical theorem closure.
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

