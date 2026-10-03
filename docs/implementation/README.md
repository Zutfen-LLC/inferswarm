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
| R6 successor dense full integration | issue #117 (closed by #184) | **Complete: planned Arm A–E sequence accepted.** Arm A execution-equivalence, Arm B cold realization, Arm C fail→diagnosis→remediation→PASS lineage, Arm D warm-restart cache-reuse, Arm E locality-mutation; [final status](r6-successor-dense-full-integration-117/FINAL-STATUS.md). |

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

