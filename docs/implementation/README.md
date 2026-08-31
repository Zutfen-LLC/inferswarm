# Implementation plans

These documents turn InferSwarm's evidence-gated roadmap into bounded
engineering/experiment sequences. They are subordinate to the canonical
architecture hierarchy:

> **ADRs decide; the [Fabric Doctrine](../architecture/fabric-doctrine.md)
> specifies; `ARCHITECTURE.md` explains; `ROADMAP.md` sequences.**

A concrete implementation plan answers one research question. It must not
silently become architecture simply because it contains a convenient temporary
API or model-specific structure.

## Historical evidence versus active plans

Completed plans remain in the repository because their methodology/results are
provenance. Historical planning records may also remain when they explain why a
later direction changed.

Terms such as `primary`, `secondary`, `worker`, L0/L1/L2/L3, expert-specific
placement, or a fixed block boundary may therefore appear in historical files.
Those terms are not current generic doctrine unless reaffirmed by ADR
0008/Fabric Doctrine.

## Completed historical tracks

| Track | Record | State |
|---|---|---|
| Phase 0 — baseline and instrumentation | [phase0-baseline.md](phase0-baseline.md) | **Complete.** Canonical baseline, correctness, routing, and residency evidence. |
| Phase 1 — two-GPU local POC | [phase1-two-gpu-poc.md](phase1-two-gpu-poc.md) | **Complete.** Exact tested candidate `NO-GO`; methodology/results remain immutable historical evidence. |
| Phase1R — post-NO-GO architecture search | [phase1r-architecture-search-handoff.md](phase1r-architecture-search-handoff.md) | **Complete through D7.** Canonical chronological local architecture-search record. |
| Phase1R disposition | [phase1r-final-disposition.md](phase1r-final-disposition.md) | **Frozen historical conclusion.** Summarizes the tested topology and pivot that led toward coarse network research. |
| N0 — selective block loading | issue #31 and retained N0 artifacts | **Complete: `N0_SELECTIVE_BLOCK_PASS`.** Selective loading/block ownership/correctness proven; persistent host-shadow release not proven. |

The Phase-1 placement/correctness correction documents remain historical
methodology records.

## Retired planning record — old N-series

[distributed-node-poc.md](distributed-node-poc.md) records the earlier N0-N3
coarse distributed-node plan established around ADR 0007.

It is now **historical/superseded planning scaffolding**:

- N0 completed and remains valid within its measured scope;
- N1 was intentionally stopped and its partial run is non-canonical;
- issues #32-#34 are retired rather than active blocked work;
- the plan must not be followed verbatim as the current implementation order.

ADR 0007 itself remains accepted as the first coarse-block-over-Ethernet
network strategy/evidence direction, while the Fabric Doctrine now governs
resource semantics and granularity selection.

## Active implementation gate

### R0 — accelerator residency without implicit persistent host mirrors — issue #48

This is the first corrected post-Wayfinder runtime gate.

Starting from the valid N0 selective-loading substrate, prove that the tested
accelerator-native materialization can release equivalent persistent host
materializations whose only purpose was staging/materialization.

The result must separately account:

- persistent required state;
- persistent optional caches/replicas;
- transient staging/packing/transfer peak;
- unexplained persistent duplication.

The target for the proven path is:

```text
deliberate accelerator bytes:       X
deliberate persistent host bytes:   Y  (explicit roles)
bounded transient host overlap:     Z
unexplained persistent host mirror: 0
```

Correctness remains a hard gate. Passing by falling back to a different/slower
semantic execution path is not acceptable.

## Successor planning rule

Do **not** pre-write a complete R1-R6 implementation stack in this directory.
The current [ROADMAP](../../ROADMAP.md) describes the intended evidence gates,
but concrete implementation-plan documents/issues should be created when the
preceding result makes the methodology knowable.

The intended order after #48 is:

1. doctrine-shaped frozen-plan realization;
2. local heterogeneous/split execution correctness + matched A/B evidence;
3. minimum automatic planning (`strategy constrains; planner chooses`);
4. measured multi-node boundary primitive;
5. end-to-end multi-node serving + elasticity/recovery;
6. materially different model architecture validation before stabilizing public
   planner/strategy APIs.

GLM-5.3-Flash remains a later large heterogeneous-capacity validation target
under issue #13, not a prerequisite for the current residency gate.

## Planning discipline

- Keep each experiment bounded to one question and precommit success criteria
  before retained performance measurement.
- Preserve backend-native fast execution; do not accidentally replace a
  meaningful path with host-orchestrated eager execution merely to make an
  abstraction look portable.
- Keep model-specific semantics behind the strategy experiment rather than
  teaching the generic planner model nouns.
- Record exact resource/model/runtime provenance and memory accounting.
- Treat caches/replicas/backing/residency/staging/authority as distinct.
- Preserve negative results.
- Do not freeze a public interface merely because a POC needs a temporary
  internal descriptor.
