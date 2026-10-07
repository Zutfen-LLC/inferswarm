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
**[Issue #268 — R8-K ordinary operator-path integration (three physical requests observed; not accepted)](https://github.com/Zutfen-LLC/inferswarm/issues/268)**

Issue #255 is accepted for its bounded homogeneous NVIDIA/CUDA two-host MVP: inferswarm01 RTX 3060 plus inferswarm04 RTX 3090, exact accepted Qwen3.8-Flash-Next-UD-IQ1_S three-part release and llama.cpp b29c606e28a01b1bc8c1351026a0fa6e616bf6c4 runtime lineage, fixed/manual whole-layer placement, verified participant-local backing, and ordinary text generation/repeatability. Issue #268 advances the frontier to integrating that accepted predecessor into a reproducible ordinary operator path. At measured product head 478eb5efc93476dc2be990ac738c7ddd40e11eab, three ordinary product-path physical requests were observed on that bounded topology with fixed CPU/local CUDA/remote RPC placement, verified participant-local backing and owned cleanup; physical-stage spec PASS and quality APPROVED are review inputs, not #268 maintainer acceptance. This does not assert #268 acceptance, numerical equivalence, mixed-vendor readiness, production readiness, dynamic scheduling, performance superiority, or R8-J/Vulkan authority. The separately accepted #264 bounded pilot remains limited to its path-transition scope: four fresh-process units observed SUBGROUP/subgroup/32x1x1 to LARGE/hybrid/128x1x1 at output.weight, with both arms screening-variable; numerical root cause and H2/H3/H5 theorem closure remain open. Acceptance authority: https://github.com/Zutfen-LLC/inferswarm/issues/264#issuecomment-5969219338.

- **Issue #255 bounded CUDA/RPC MVP (accepted predecessor) observation:** [`MVP_DISTRIBUTED_INFERENCE_PASS`](https://github.com/Zutfen-LLC/inferswarm/issues/255#issuecomment-5971666116).
- **Maintainer acceptance:** [accepted](https://github.com/Zutfen-LLC/inferswarm/issues/255#issuecomment-5974171991).
- **Recorded execution authorization:** blocked — Three ordinary Issue #268 physical product-path requests were observed at measured head 478eb5efc93476dc2be990ac738c7ddd40e11eab, with physical-stage spec PASS and quality APPROVED; ordinary CI run 37169789383 succeeded on that measured head, not necessarily on this documentation head. Issue #268 is not accepted; Final CPU Validation requires maintainer GO on the exact final head and remains REQUIRED/DEFERRED. Living status is informational and grants no execution permission. No fourth or further physical request is authorized. This status grants no further execution authority.. [Authority](https://github.com/Zutfen-LLC/inferswarm/issues/268).

- The #250 predecessor remains accepted as the ARM_A_STOPS_LADDER localized boundary only; observation https://github.com/Zutfen-LLC/inferswarm/pull/251#issuecomment-5904093750 and acceptance https://github.com/Zutfen-LLC/inferswarm/issues/250#issuecomment-5904094070 remain preserved. This was not established as root cause.
- Issue #264's sole live minimal experimental selector is subgroup32→large128 hybrid for the output.weight MMV q4_K*f32 route; dimensions/types and frozen comparator identity are scoped to that candidate only. The cooperative-matrix candidate is dead; do not revive it.
- Four fresh-process units at the frozen execution head observed the actual path transition at all 10 output events per unit. BASE and candidate both differ across their two full-row digests and are screening-variable; matching candidate response tokens do not establish numerical stability or causality.
- The bounded pilot stopped at two units per arm; no third units or retry. Controller preservation verified the accepted #262 150-file inventory unchanged and 69 new retained files byte-identical across remote and local roots. The pure report's preservation field remains external-pending by design.
- Issue #266 is COMPLETED (closed completed), and PR #256 is MERGED to main as 442e2a02ce89e7fb42bceff1f7a47c8789c17733 (https://github.com/Zutfen-LLC/inferswarm/pull/256); the aggregate #254/#258/#260/#262/#264 stack is historical R8-I3C authority, not a pending review frontier. The bounded #264 result is accepted, and PR #265 merged into the aggregate producer branch as b3b28825d860b01b40f7b5697d5a50266ecaeb39 after exact-head review and Final CPU Validation on 28120bb57bfa9b8997d3d616c24e59a70f96a9af (run 37122285620). Those historical receipts are not validation receipts for the current #255 head. A source/CI/subagent PASS or additive report head grants no new physical authority. No automerge, R8-J, dead-control, or broad-matrix work is authorized.
- The completed #258 prospective theorem (merged PR #259) keeps historical A3 terminal-capability separate from hypothesis coverage: closure remains impossible, required_arms is empty, and A5 remains observationally capable but nonterminal. #260/#262/#264 use distinct instrumented source identities; their path observations do not reopen historical theorem closure.
- Issue #241 remains accepted as R8I3_COMPARATOR_V2_BLOCKED; #244 and #239 remain blocked on their Vulkan/comparator path. Issue #255's accepted capability is limited to its bounded tested homogeneous NVIDIA/CUDA two-host MVP; it establishes no numerical equivalence, mixed-vendor readiness, production readiness, or new R8-J/Vulkan execution authority. The #255 observation asserts the MVP_DISTRIBUTED_INFERENCE_PASS terminal only within that accepted scope.
- Issue #280 is the active AMD-only Vulkan same-request physical campaign. Its observer/harness was CPU-validated and merged in PR #282 at cb907531493dd10ba32d601fe097fb6c3c559e70. The bounded eight-launch/sixteen-request/20-minute/$0 physical matrix is explicitly authorized by Issue #280 comment 6029667573; a pre-inference cooling-confirmation STOP consumed 0 launches/requests, and maintainer comment 6030829366 confirmed the unchanged cooling setup and authorized direct resume of the same frozen campaign. Under repository campaign-autonomy doctrine, unchanged established facts do not require repeated human reconfirmation: execution proceeds inside the frozen envelope unless a material anomaly, authority expansion, safety/integrity issue, or other substantive stop condition appears. This grants no #281, purchase, mixed-vendor, #239/R8-J, holdout, or production authority; #239 remains blocked. After the first completed physical run (8 launches / 16 requests, terminal STOP), Issue #284 corrects the exposed defects: the runner evaluates every frozen per-request acceptance/STOP condition synchronously before any subsequent launch (semantic task gate, required observer evidence per arm, peak-RSS retention, available health inputs; aborted slots consumed, no automatic rerun); the observer retention defect is root-caused to library-TU I280 events dropped by the common log callback's INFO-to-TRACE mapping at the default threshold (fixed by emitting at log level NONE in the five library TUs); and the formatting-sensitive JSON-only rubric is replaced by a frozen deterministic semantic checker. The corrected contract prepares, but does not authorize, a minimal 2-launch / 4-request physical rerun. Review round 2 (PR #285 comment 6035951310) removed event-name-presence admission: every admitted request now requires a structured PASS observer verdict mechanically validated from its retained raw bytes under the frozen physical #280 contract (two retained V340L BDFs, 0-18/19-35 split, per-die ownership and completed compute, exact boundary occurrence/bytes/staging reconciliation); candidate cold must PASS before candidate warm executes.
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

