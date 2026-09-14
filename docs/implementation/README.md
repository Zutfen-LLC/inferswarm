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
**[Issue #117 — R6 successor dense full integration](https://github.com/Zutfen-LLC/inferswarm/issues/117)**

Integrate V5-qualified dense Gemma with automatic planning, participant-exact artifact acquisition, selective materialization, and ordinary fenced serving.

- **Arm E — verified-inventory locality mutation (planning-only) observation:** [`ISSUE117_ARM_E_LOCALITY_MUTATION_PASS`](https://github.com/Zutfen-LLC/inferswarm/pull/183).
- **Maintainer acceptance:** [accepted](https://github.com/Zutfen-LLC/inferswarm/commit/1149a8ad9576ac25dfa2e474b9142c9c903ced77).
- **Recorded execution authorization:** blocked — Issue #117 planned Arm A-E integration sequence COMPLETE/ACCEPTED for the frozen dense-Gemma subject and RTX-3060-class proving topology (final closure Issue #184, CPU/docs only): Arm A execution-equivalence PASS, Arm B cold realization PASS, Arm C fail-then-remediate-then-PASS lineage, Arm D warm-restart cache-reuse PASS, Arm E locality-mutation PASS. No successor campaign, remediation, requalification, or holdout access is authorized by this closure; a successor requires a new issue and fresh authority..

- The accepted historical Arm-C result remains ISSUE117_ARM_C_EVIDENCE_BLOCKER (PR #128, merge 718efbf5770b31c6e44eb3a8c4d0b81fd1dc9c22); it is preserved as the correct result of the original inadmissible campaign.
- The corrected fresh Arm-C campaign is accepted as ISSUE117_ARM_C_ORDINARY_SERVING_FAIL (PR #136, merge 1b83bcab0a5e682a438ca0554f71dd0ace15be55): 18/24 exact equality and six regime-4 committed-token divergences under complete pre-divergence invocation equivalence.
- Issue #137 diagnosis is accepted as ISSUE117_ARM_C_REGIME4_DIAGNOSIS_PARTIAL (PR #138, merge cdc23d0e8fa9d3b1b27bab5749939a5ad69b9610): multi-chunk extend-prefill is sufficient for instability on a stable control, and the earliest captured divergence is inside stage 1 at or before global layer 1, but one identical numerical mechanism for all six cases is not established.
- Issue #153 corrected remediation is ISSUE117_ARM_C_REMEDIATION_BLOCKED (BACKEND_REQUIRES_MULTI_CHUNK): the accepted 65-67-row failing units must remain multi-chunk under the frozen 64-row boundary/wire contract, the required extend path's instability is not remediated, and the at-or-below-64 single-call policy cleanup is useful but not a remediation of the failing population; fresh Arm-C requalification MUST NOT be authorized from the candidate producer.
- Issue #157 chunk-2 extend-path diagnosis delivered ISSUE117_ARM_C_CHUNK2_CAUSE_LOCALIZED under its physically authorized diagnostic-only scope: the R6 standalone stage path never performs SWA slot allocation, so full-to-swa index mapping stays at the all-zero sentinel and every SWA-layer chunk-2 store and prefix read resolves to swa slot 0; a single-factor alloc_swa intervention makes chunk-2 byte-deterministic on both anchors while the paired control varies. This is a diagnostic localization only: remediation and requalification still require separate authority.
- No h109-* holdout material may be opened, generated, copied, or used; the planned Arm A-E sequence is complete and accepted: Arm D through Issue #175 / PR #181 / merge d4d50b20205e455a195a908ee9d5ea72bc5d8d04 as ISSUE117_ARM_D_WARM_RESTART_CACHE_REUSE_PASS, Arm E through Issue #182 / PR #183 / merge 1149a8ad9576ac25dfa2e474b9142c9c903ced77 as ISSUE117_ARM_E_LOCALITY_MUTATION_PASS.
- Issue #166 SWA allocation remediation delivered ISSUE117_ARM_C_SWA_REMEDIATION_READY under its implementation-remediation-only scope: the standalone R6 stage runtime now owns the session SWA allocation lifecycle (incremental alloc_swa frontier before each chunk's first prefix-consuming SWA KV operation, mapping persistence across chunks/decode, wholesale release on reset, fail-closed exhaustion/gaps), reaching the same underlying allocation semantic as the accepted #157 intervention and the scheduler path; proven CPU-only with lifecycle/negative-control tests, no model execution. The remediation producer was NOT promoted to qualification authority at delivery; the separately authorized requalification was later executed (#172) and accepted (PR #174).
- Issue #170 froze the prospective Arm-C long-remainder public generalization corpus with ISSUE117_ARM_C_LONG_REMAINDER_CORPUS_FROZEN (CPU-only; later accepted): 16 new public g170-* cases generated deterministically from the frozen public seed with the accepted #74/#109 prompt machinery and the accepted #129/#133 frozen tokenizer/render semantics (24/24 accepted #133 fixture renders reproduced byte-exact as preflight), hitting the exact target rendered lengths 65,67,69,72,73,78,83,88,89,96,104,112,113,118,123,128 — exactly four cases per original second-chunk-remainder bucket (1-8/9-24/25-48/49-64), all six accepted content classes at least twice, disjoint from all public c109-*/p109-*/#133-fixture/#157-anchor identities. No physical execution; no h109 access; no Arm-C verdict; the corpus was subsequently accepted and consumed unchanged by the #172 requalification campaign (accepted PR #174).
- #168 Phase 1B fresh-arm corpus census (pinned frozen tokenizer, all 1416 public c109 cases rendered) proved buckets 25-48 and 49-64 EMPTY under every defensible two-chunk reading (corpus regimes cap raw prompts at 56 tokens; max rendered length 69), so the mandated 4x4 fresh multi-chunk arm is corpus-insufficient; issue forbids bucket adaptation and mandates the pre-observation terminal ISSUE117_ARM_C_REQUALIFICATION_EVIDENCE_BLOCKED (campaign issue168-arm-c-post-swa-requal-v1). No physical execution in #168 itself; resolved by maintainer authorization of the #170 long-regime corpus, which the accepted #172 requalification consumed.
- Issue #172 post-remediation physical requalification derived ISSUE117_ARM_C_ORDINARY_SERVING_PASS mechanically from retained bytes (docs/implementation/r6-successor-arm-c-requalification-172/); accepted through PR #174 / merge 52c3b560d560f69d0f009ed5772c1a70efc01ba2. The historical pre-remediation #133 FAIL remains immutable historical truth; this PASS does not rewrite it.
- Issue #184 final closure (CPU/docs only, no physical execution): the planned Issue #117 Arm A-E sequence is COMPLETE for the frozen tested subject/topology. Arm A accepted PASS (PR #122, merge 6774474941d7ce2a0252c8c1e148f8bce61a8d6d); Arm B accepted ISSUE117_ARM_B_COLD_REALIZATION_PASS (PR #127, merge fed87d1b71a0794374dd58c921e31606a56a242f); historical Arm C FAIL lineage preserved; post-remediation Arm C PASS accepted (PR #174); Arm D accepted (PR #181); Arm E accepted (PR #183). No remaining Issue #117 execution slice; closure-summary at docs/implementation/r6-successor-dense-full-integration-117/FINAL-STATUS.md.
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

