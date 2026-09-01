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

## Accepted runtime lineage through R4

The corrected post-Wayfinder FreeToken research line has now proven:

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

R4 exposed a real need for this distinction: FreeToken PR #20 contains a valid
R3→R4 evidence lineage, but current FreeToken `main` has diverged such that the
PR is not a sane direct long-term merge surface.

InferSwarm issue
[#59](https://github.com/Zutfen-LLC/inferswarm/issues/59) therefore establishes
a durable branch such as `inferswarm/research` before R5A. The intended method
is to preserve the accepted R4 lineage and deliberately integrate current
upstream-tracking `main`, with dependency-scoped regression/requalification,
rather than rebasing or rewriting accepted evidence.

Do **not** merge PR #20 directly into FreeToken `main` merely to close it.

## Current implementation direction

The current successor evidence gate is
[#60 — R5A: static end-to-end multi-node serving from a planner-selected
plan](https://github.com/Zutfen-LLC/inferswarm/issues/60), blocked on the #59
integration-line prerequisite.

R5A must move the accepted R0-R4 substrate out of separately invoked POC stages
and through a normal host-runtime serving request:

```text
request
  -> strategy legal candidates
  -> generic planner + applicable evidence/policy
  -> frozen Execution Plan
  -> multi-Node realization
  -> backend-native execution
  -> response
```

Accepted R4 network measurements can now be ingested as context-valid planner
evidence. The planner must still evaluate alternatives honestly; R5A must not
hard-code the network split merely because the gate is testing multi-Node
serving.

Live plan-epoch transitions, scale-up/down, and failure recovery remain R5B work
after static serving passes.

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

R5A/R5B should continue to keep temporary first-model and first-backend details
behind research/strategy seams. Before public strategy/planner APIs are treated
as stable, R6 must attempt to falsify them against a materially different model
architecture.

Upstream FreeToken and FlashML are not involved in InferSwarm; nothing here
implies their endorsement.
