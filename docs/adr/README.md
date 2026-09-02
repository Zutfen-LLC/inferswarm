# Architecture Decision Records

ADRs record **genuinely consequential architecture decisions** for InferSwarm:
choices that constrain future work, set boundaries, or commit the project to
a direction. They are not a log of implementation details — "which linter we
use" is not an ADR; "what the project's open-source boundary is" is.

## Canonical documentation hierarchy

Following ADR 0008 and the completed resource/residency/planner Wayfinder:

> **ADRs decide; the [Fabric Doctrine](../architecture/fabric-doctrine.md)
> specifies; `ARCHITECTURE.md` explains; `ROADMAP.md` sequences.**

ADRs record durable decisions and supersession. The Fabric Doctrine is the
normative detailed synthesis of the current resource/residency/planning model.
Derived overview/roadmap prose must not silently override either.

ADR 0009 additionally adopts
[`docs/architecture/model-artifact-distribution.md`](../architecture/model-artifact-distribution.md)
as a normative Fabric Doctrine supplement for model artifact acquisition and
distribution semantics. It remains subordinate to ADR decisions and should be
consolidated into the main doctrine if/when that structure is next revised.

## Convention

- One Markdown file per decision, named `NNNN-short-title.md`, numbered from
  `0001` and monotonically increasing.
- New ADRs are added, never renumbered. An ADR that replaces an earlier one
  marks the old one `Superseded by NNNN` and links forward.
- ADRs are immutable once Accepted except for the status line and
  clarifications that do not change the decision. Changes that alter the
  decision get a new ADR.

## Structure

```markdown
# NNNN. Short title

Date: YYYY-MM-DD
Status: Proposed | Accepted | Superseded by NNNN | Rejected

## Context
What problem or force made a decision necessary.

## Decision
The choice, stated plainly.

## Consequences
What this commits us to, costs included.

## Hypotheses distinguished from decisions
Anything this ADR explicitly does NOT decide — claims that remain to be
validated by experiment, with a pointer to where that happens.
```

The final section is mandatory when an ADR touches claims that could be
mistaken for proven facts. An ADR may *decide* a target while explicitly not
deciding whether the target is achievable — that distinction is the point.

## Index

| ADR | Title | Status |
|-----|-------|--------|
| [0001](0001-inferswarm-project-boundary.md) | InferSwarm project boundary | Accepted |
| [0002](0002-freetoken-as-initial-integration-runtime.md) | FreeToken as initial integration runtime | Accepted |
| [0003](0003-1gbe-baseline-network-target.md) | 1 GbE baseline network target | Accepted |
| [0004](0004-moe-as-first-execution-strategy.md) | MoE as first execution strategy | Accepted |
| [0005](0005-ram-remains-first-class-tier.md) | System RAM remains a first-class tier | **Superseded by 0008** |
| [0006](0006-backend-independent-worker-and-representation-boundary.md) | Backend-independent worker and representation boundary | **Superseded by 0008** |
| [0007](0007-coarse-model-block-partitioning-as-first-network-strategy.md) | Coarse model-block partitioning as first network strategy | Accepted |
| [0008](0008-canonical-fabric-doctrine.md) | Canonical Fabric Doctrine | **Accepted** |
| [0009](0009-plan-driven-model-artifact-distribution.md) | Plan-driven model artifact acquisition and distribution | **Accepted** |
