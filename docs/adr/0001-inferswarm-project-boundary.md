# 0001. InferSwarm project boundary

Date: 2026-08-26
Status: Accepted

> **Current doctrine clarification (2026-08-31):** references below to an
> InferSwarm Agent/worker and worker protocol describe possible runtime roles
> inside the open-source execution fabric. Under ADR 0008/Fabric Doctrine,
> `Worker` is not a physical resource class; Nodes, Compute Units, Memory
> Resources, Links, Model Execution Strategies, and Execution Plans carry the
> canonical resource/planning semantics.

## Context

InferSwarm needs a canonical home and an explicit boundary between the
open-source project and any future commercial Zutfen offerings, before
implementation work makes the boundary ambiguous. Precedent matters here:
without a written boundary, "we'll keep the good part for the paid version"
creeps in one commit at a time — or, the opposite failure, the open-source
project accumulates enterprise fleet-management machinery that serves no
research goal.

Related context: the initial experimental work happens in the
[Zutfen-LLC/FreeToken](https://github.com/Zutfen-LLC/FreeToken) fork (ADR
0002), so the project home can start as architecture, roadmap, and
conventions without premature runtime code.

## Decision

InferSwarm lives at `Zutfen-LLC/inferswarm` as an Apache-2.0 public
repository, and is the canonical home for the project's architecture,
roadmap, decisions, and (eventually) runtime code.

The intended open-source boundary includes:

- InferSwarm Runtime
- InferSwarm Agent (worker)
- worker protocol
- transport implementations
- hardware profiling
- scheduling/placement primitives

Commercial management/orchestration capabilities (e.g. a future "InferSwarm
Control" or "InferSwarm Enterprise": zero-friction enrollment, fleet
governance, SSO/RBAC, monitoring, support) may later exist separately as
Zutfen products.

The boundary rule: **the execution fabric must remain fully usable without
any paid control plane.** Commercial offerings may add convenience and
management; they must not remove capability, and the open-source project will
not be artificially crippled to enforce a commercial tier.

## Consequences

- Distributed-execution functionality proven in the FreeToken fork is
destined for extraction into this repository (ROADMAP Phase 5), because the
runtime belongs inside the boundary.
- This repository stays deliberately free of speculative package trees until
implementation establishes real boundaries; the boundary above describes
*intent*, not present contents.
- Commercial/control-plane code never lands in this repository.
- Zutfen retains no special technical chokepoint: contributions are accepted
under Apache-2.0 and the fabric's usability is not license-gated.

## Hypotheses distinguished from decisions

- **Decided:** the boundary itself, the license, and the no-crippling rule.
- **Not decided:** the exact product shape of any commercial offering, or
whether one will exist at all. "InferSwarm Control / Enterprise" are
placeholders describing where management tooling would live, not
announcements.
- **Not decided by this ADR:** whether the fabric's performance goals are
achievable — that is the ROADMAP's business, not the boundary's.
