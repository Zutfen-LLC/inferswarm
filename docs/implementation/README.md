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

## Completed tracks

| Track | Record | State |
|---|---|---|
| Phase 0 — baseline and instrumentation | [phase0-baseline.md](phase0-baseline.md) | **Complete.** Canonical baseline, correctness, routing, and residency evidence. |
| Phase 1 — two-GPU local POC | [phase1-two-gpu-poc.md](phase1-two-gpu-poc.md) | **Complete.** Exact tested candidate `NO-GO`; methodology/results remain immutable historical evidence. |
| Phase1R — post-NO-GO architecture search | [phase1r-architecture-search-handoff.md](phase1r-architecture-search-handoff.md) | **Complete through D7.** Canonical chronological local architecture-search record. |
| Phase1R disposition | [phase1r-final-disposition.md](phase1r-final-disposition.md) | **Frozen historical conclusion.** Summarizes the tested topology and pivot that led toward coarse network research. |
| N0 — selective block loading | issue #31 and retained N0 artifacts | **Complete: `N0_SELECTIVE_BLOCK_PASS`.** |
| R0 — accelerator residency | issue #48 | **Complete: `P48_ACCELERATOR_RESIDENCY_PASS`.** |
| R1 — frozen-plan realization | issue #50 | **Complete: `R1_FROZEN_PLAN_REALIZATION_PASS`.** |
| R2 — local split execution | issue #51 | **Complete: `R2_LOCAL_SPLIT_EXECUTION_PASS`.** |
| Host staging reclamation | issue #53 | **Complete: `HOST_STAGING_RECLAMATION_PASS`.** |
| R3 — minimum automatic planning | issue #55 | **Complete: `R3_MINIMUM_AUTOMATIC_PLANNING_PASS`.** |
| R4 — physical two-Node boundary | issue #57 | **Complete: `R4_MULTI_NODE_BOUNDARY_PASS`; 1-GbE arm `R4_1GBE_PRIMITIVE_CAPACITY_VIABLE`.** |

The Phase-1 placement/correctness correction documents and retired N-series
records remain historical methodology/provenance.

## Retired planning record — old N-series

[distributed-node-poc.md](distributed-node-poc.md) records the earlier N0-N3
coarse distributed-node plan established around ADR 0007.

It is **historical/superseded planning scaffolding**:

- N0 completed and remains valid within its measured scope;
- N1 was intentionally stopped and its partial run is non-canonical;
- issues #32-#34 are retired rather than active blocked work;
- the plan must not be followed verbatim as the current implementation order.

ADR 0007 remains accepted as the first coarse-block-over-Ethernet network
evidence direction, but R4/#57—not the retired N1-N3 sequence—is the accepted
physical two-Node proof.

## Current implementation work

### Pre-R5 integration-line prerequisite — issue #59

Before R5A, establish a durable FreeToken InferSwarm integration line that
preserves the accepted R0-R4 evidence lineage while deliberately integrating
current upstream-tracking FreeToken `main`.

Issue [#59](https://github.com/Zutfen-LLC/inferswarm/issues/59) is an
implementation-line prerequisite, not a new architecture gate.

Do not rebase/rewrite accepted evidence merely to obtain a cleaner branch graph,
and do not merge FreeToken PR #20 directly into upstream-tracking `main` merely
to close the PR.

### R5A — static end-to-end multi-node serving — issue #60

Issue [#60](https://github.com/Zutfen-LLC/inferswarm/issues/60) is the current
successor evidence gate, blocked by #59.

R5A must integrate the separately proven R0-R4 seams through a normal serving
request rather than a benchmark-only manual split runner:

```text
request
  -> Model Execution Strategy legal candidates
  -> generic planner + current applicable evidence/policy
  -> frozen Execution Plan
  -> multi-Node realization
  -> backend-native distributed execution
  -> response
```

Accepted R4 evidence may now participate in planner ranking when its frozen
context matches. The network candidate must not be hard-coded as preferred just
because the gate tests multi-Node serving.

R5A measures correctness, TTFT, prefill, decode, complete request wall time,
network contribution, memory/materialization lifecycle, plan explanation, and a
bounded concurrency arm.

Live plan transitions, scale-up/down, and failure recovery are intentionally
**R5B**, not R5A.

## Successor planning rule

Do not pre-write a speculative implementation ladder beyond what predecessor
evidence makes concrete.

The current intended order is:

1. #59 — establish the durable FreeToken integration implementation base;
2. R5A / #60 — static planner-selected end-to-end multi-Node serving;
3. R5B — real execution-plan epochs, scale-up/down, and truthful recovery under
   the semantics already decided by #43;
4. R6 — materially different model architecture validation before stabilizing
   public planner/strategy APIs.

GLM-5.3-Flash remains a later large heterogeneous-capacity validation target
under issue #13, not a prerequisite for R5A.

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
- Preserve accepted evidence commits immutably and preserve negative results.
- Revalidate evidence dependency-scoped when the integration/runtime context
  changes.
- Do not freeze a public interface merely because a POC needs a temporary
  internal descriptor.
