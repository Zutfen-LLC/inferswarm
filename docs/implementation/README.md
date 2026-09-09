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
| Plan-driven artifact acquisition | issue #99 | **Complete: `PLAN_DRIVEN_ARTIFACT_ACQUISITION_PASS`.** Minimum ADR 0009 acquisition seam; record under [plan-driven-artifact-acquisition-99/](plan-driven-artifact-acquisition-99/). |
| Plan-driven artifact orchestration | issue #101 | **Complete: `PLAN_DRIVEN_ARTIFACT_ORCHESTRATION_PASS`.** CPU inventory, peer reuse, and replacement deltas; [retained record](plan-driven-artifact-orchestration-101/README.md). |
| Artifact-locality transition planning | issue #103 | **Complete: `ARTIFACT_LOCALITY_TRANSITION_PLANNING_PASS`.** Locality as ranking evidence, not a feasibility rule; [retained record](artifact-locality-transition-planning-103/README.md). |
| R5A — static end-to-end multi-node serving | issue #60 | **Complete: `R5A_STATIC_MULTI_NODE_SERVING_PASS`.** One static serving path through strategy, planner, frozen plan, multi-Node realization, and backend-native execution. |
| R5B — plan epochs, scale-up/down, recovery | issue #62 | **Complete: `R5B_PLAN_EPOCH_RECOVERY_PASS`.** |
| Pre-R6 integration refresh | issue #64 | **Complete: `PRE_R6_INTEGRATION_REQUALIFICATION_PASS`.** |
| Pre-R6 external Coordinator separation | issue #67 | **Complete: `EXTERNAL_COORDINATOR_SEPARATION_PASS`.** |
| Correctness-qualification lane | issues #72-#115 | **Complete: `V5_QUALIFICATION_PASS`** on the dense Gemma subject, after terminal v2/v3/v4 failures. Lane index: [`../qualification/README.md`](../qualification/README.md). |

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

<!-- project-status:frontier:start -->
**[Issue #117 — R6 successor dense full integration](https://github.com/Zutfen-LLC/inferswarm/issues/117)**

Integrate V5-qualified dense Gemma with automatic planning, participant-exact artifact acquisition, selective materialization, and ordinary fenced serving.

- **Arm B — canonical cold acquisition + realization observation:** [`ISSUE117_ARM_B_COLD_REALIZATION_PASS`](https://github.com/Zutfen-LLC/inferswarm/pull/127).
- **Maintainer acceptance:** [accepted](https://github.com/Zutfen-LLC/inferswarm/commit/fed87d1b71a0794374dd58c921e31606a56a242f).
- **Recorded execution authorization:** authorized — Arm C — ordinary external-Coordinator serving. [Authority](https://github.com/Zutfen-LLC/inferswarm/issues/117).

- Arm B is accepted at merge fed87d1b71a0794374dd58c921e31606a56a242f (ISSUE117_ARM_B_COLD_REALIZATION_PASS, PR #127).
- Arm C — ordinary external-Coordinator serving — is the only authorized physical frontier.
- Do not rerun the accepted physical preflight, Arm A, or the accepted Arm-B campaign.
- Arm D must not begin before Arm-C maintainer acceptance.
- Preserve the exact frozen producer 924cd22ea081f6d4ed471016faf01d427fc5b0d2, checkpoint 5a84cb313260ac447237b890387116dfa8682e49a6b44bc585ae8353abbff18d, canonical candidate geometry dense.6171f32b4413, and the accepted Arm-B participant materialized state; do not clean, reset, or reacquire it.
- No consumed h109-* holdout material may be used as new evidence.
<!-- project-status:frontier:end -->

The [retained #117 record](r6-successor-dense-full-integration-117/README.md)
preserves the CPU fixture, earlier blocked implementation freeze, additive
provenance recoveries, and accepted physical preflight.

## Successor planning rule

Do not pre-write a speculative implementation ladder beyond what predecessor
evidence makes concrete. Follow the current gate's explicit review stops;
completion of one arm does not authorize the next arm. Public interfaces remain
unfrozen until real integration establishes their boundaries.

See [ROADMAP.md](../../ROADMAP.md) for the gate sequence and accepted results.

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
