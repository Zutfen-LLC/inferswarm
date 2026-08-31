# 0002. FreeToken as initial integration runtime

Date: 2026-08-26
Status: Accepted

> **Current doctrine clarification (2026-08-31):** FreeToken remains the
> initial proving/integration vehicle and extraction remains the goal. The old
> `ROADMAP Phase 5` sequencing and `heterogeneous workers` diagram below are
> historical framing; current implementation order and resource semantics are
> defined by ADR 0008, the Fabric Doctrine, and the current `ROADMAP.md`.

## Context

InferSwarm's first proofs of concept need a host inference engine that
already supports the target model family, MoE offload machinery, and
measurement tooling — building one from scratch would spend the POC budget on
the wrong thing. FreeToken (upstream: FlashML-org/FreeToken) is the engine
whose MoE expert-offload cache is the object of study; the Zutfen fork
(`Zutfen-LLC/FreeToken`) exists for this work.

A fork is a means, not a home: a deeply divergent fork becomes unmaintainable
and would strand InferSwarm's runtime inside someone else's project. The
choice of initial runtime therefore has to be made *together with* a rule
about how the relationship ends.

## Decision

The [Zutfen-LLC/FreeToken](https://github.com/Zutfen-LLC/FreeToken) fork is
the initial host/runtime integration vehicle for InferSwarm POCs. All POC
implementation work happens there until ROADMAP Phase 5.

The intended relationship:

```
FreeToken
    transformer/runtime integration
            │
            ▼
InferSwarm execution abstraction
            │
     heterogeneous workers
```

The fork is operated to keep divergence shallow and extraction feasible:

- `main` tracks upstream `FlashML-org/FreeToken` main;
- downstream integration work happens on an `inferswarm` integration branch
  (created when POC implementation begins; see
  [docs/integrations/freetoken.md](../integrations/freetoken.md));
- focused experiments happen on short-lived `poc/*` branches.

The long-term intent is explicit: **the novel distributed-execution
functionality becomes cleanly separable from FreeToken** rather than
permanently maintaining a deeply divergent fork. InferSwarm is not "a
FreeToken fork project"; FreeToken is a host being integrated with, not
extended permanently.

## Consequences

- InferSwarm issues (architecture, roadmap, criteria) are canonical; the
  fork carries implementation PRs that link back to them. The full roadmap is
  never duplicated into FreeToken issues.
- Early InferSwarm architectural decisions will be shaped by FreeToken's
  internals — that is acceptable for POC purposes but must not silently
  become permanent. Decisions smelling of "whatever FreeToken's cache does"
  get scrutinized at Phase 5 extraction time.
- Upstream FreeToken/FlashML is used with appreciation but has no involvement
  in, or endorsement of, InferSwarm.
- If a different host engine becomes primary later, the narrow execution seam
  (ARCHITECTURE.md, principle 10) is what makes that survivable.

## Hypotheses distinguished from decisions

- **Decided:** FreeToken is the initial vehicle; the branch policy; the
  extraction intent and its Phase 5 placement.
- **Not decided:** that FreeToken is the *permanent* runtime — "initial"
  is load-bearing. Also not decided: that the extraction will be clean; that
  is a goal the POC work must earn, and difficulty encountered will be
  recorded, not papered over.
- **Not a claim:** that any integration has demonstrated performance results
  yet. None has.
