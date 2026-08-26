# FreeToken integration

How InferSwarm relates to the [Zutfen-LLC/FreeToken](https://github.com/Zutfen-LLC/FreeToken)
fork (a fork of [FlashML-org/FreeToken](https://github.com/FlashML-org/FreeToken)).
Decision context: [ADR 0002](../adr/0002-freetoken-as-initial-integration-runtime.md).

## Who owns what

- **InferSwarm issues are canonical** for InferSwarm architecture, roadmap,
  and acceptance criteria.
- **The FreeToken fork carries implementation PRs** needed to prove the
  current hypotheses.

The typical flow:

```
Zutfen-LLC/inferswarm issue
        │
        ▼
Zutfen-LLC/FreeToken implementation PR
        │
        ▼
benchmark / evidence
        │
        ▼
InferSwarm architectural decision
```

Do not duplicate the full InferSwarm roadmap into FreeToken issues. When
appropriate, FreeToken PRs link back to the canonical InferSwarm issue.

## Branch policy

As of 2026-08-26 the fork contains only `main`, which tracks upstream
`FlashML-org/FreeToken` main. The recommended policy when POC implementation
begins:

```
main
    tracks FlashML-org/FreeToken main

inferswarm
    downstream InferSwarm integration

poc/*
    focused experimental branches
```

- `main` stays clean of InferSwarm work so upstream merges stay trivial.
- `inferswarm` is the long-lived downstream integration branch: rebased or
  merged from `main` regularly, and kept as shallow as the narrow-seam
  principle allows (everything that can live behind the execution seam
  eventually moves to `Zutfen-LLC/inferswarm` at ROADMAP Phase 5).
- `poc/*` branches are short-lived experiments; they die or merge to
  `inferswarm`, and do not linger.

## End state

The point of the policy is the ending: once the runtime extraction (ROADMAP
Phase 5) lands, the fork's persistent divergence should shrink to a thin
adapter, and ideally to plain upstream tracking with no downstream branch at
all. A permanently divergent fork is a failure mode, not a plan.

Upstream FreeToken and FlashML are not involved in InferSwarm; nothing here
implies their endorsement.
