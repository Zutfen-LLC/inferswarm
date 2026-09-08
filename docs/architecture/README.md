# Architecture (normative)

This directory holds the **normative** architecture layer. It specifies
semantics; it does not decide them and does not sequence work.

> **[ADRs](../adr/README.md) decide; the
> [Fabric Doctrine](fabric-doctrine.md) specifies;
> [ARCHITECTURE.md](../../ARCHITECTURE.md) explains;
> [ROADMAP.md](../../ROADMAP.md) sequences.**

[ARCHITECTURE.md](../../ARCHITECTURE.md) at the repository root is a *derived
overview*. Where the two differ in detail, this directory governs; where this
directory and an ADR differ, the ADR governs.

## Documents

| Document | Adopted by | Scope |
|---|---|---|
| [fabric-doctrine.md](fabric-doctrine.md) | [ADR 0008](../adr/0008-canonical-fabric-doctrine.md) | The canonical resource/residency/planning model: Swarm, Coordinator, Node, Compute Unit, Memory Resource, Link; Logical State Units and Materializations; residency, staging, cache, replica, and mutable authority; correctness-and-feasibility-first planning; evidence, baselines, degradation, and quarantine; the generic planner / Model Execution Strategy boundary; immutable Execution Plan epochs; Adaptive Demand Profiles; measured distribution granularity. |
| [model-artifact-distribution.md](model-artifact-distribution.md) | [ADR 0009](../adr/0009-plan-driven-model-artifact-distribution.md) | Plan-driven model artifact acquisition and distribution semantics. |
| [numerical-equivalence-contract.md](numerical-equivalence-contract.md) | [ADR 0010](../adr/0010-heterogeneous-numerical-equivalence.md) | The three-layer heterogeneous correctness contract: exact integrity, qualified numerical execution equivalence, and strategy-declared semantic output correctness. Refined by [ADR 0011](../adr/0011-two-tier-numerical-core-and-telemetry.md) (acceptance-bearing core versus mandatory telemetry) and [ADR 0012](../adr/0012-statistical-qualification-and-consumer-metric-doctrine.md) (prospective statistical claims and consumer-metric classification). |

The two supplements are subordinate to ADR decisions and remain separate
files. They should be consolidated into the Fabric Doctrine if and when that
document is next structurally revised.

## Changing anything here

A material doctrine change requires an ADR. It must not arrive through
`ROADMAP.md`, an implementation plan, or prose in the derived overview.

ADR 0011 and ADR 0012 are the worked example of the intended shape: each
refines the numerical layer **prospectively**, and neither reinterprets a
historical frozen verdict. Doctrine may change what the next comparator must
prove; it never re-adjudicates a campaign that already terminated.

## Where the doctrine has been tested

The doctrine is not aspirational. [ROADMAP.md](../../ROADMAP.md) records which
parts have physical evidence behind them — the R0-R5B runtime gates, the
plan-driven distribution proofs (#99/#101/#103), and the correctness-
qualification lane that terminated `V5_QUALIFICATION_PASS`. The current
architecture-integration frontier is issue #117.

Deliberately unfrozen, per the **doctrine-shaped, API-unfrozen** posture:
public planner/strategy type names, plugin/extension APIs, wire protocols,
telemetry schemas, and storage layouts. See the closing section of
[ARCHITECTURE.md](../../ARCHITECTURE.md).
