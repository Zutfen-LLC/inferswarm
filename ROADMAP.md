# InferSwarm Roadmap

This roadmap tracks **evidence-gated research and implementation**, not feature
shipping. Results follow [BENCHMARKING.md](BENCHMARKING.md): if an experiment
fails, the roadmap changes rather than the thresholds or the numbers.

## Documentation authority

Repository precedence is:

> **[ADRs](docs/adr/README.md) decide; the
> [Fabric Doctrine](docs/architecture/fabric-doctrine.md) specifies;
> `ARCHITECTURE.md` explains; `ROADMAP.md` sequences.**

[ADR 0008](docs/adr/0008-canonical-fabric-doctrine.md) and the completed
resource/residency/planner Wayfinder (#37, decisions #38-#46) define the
architecture this roadmap must implement.

The current posture is **doctrine-shaped, API-unfrozen**. Each gate should
implement only enough internal structure to prove its question; no gate is an
excuse to invent the final planner, strategy plugin API, control plane, wire
protocol, or telemetry schema prematurely.

---

## Completed foundation

### Phase 0 — baseline and routing evidence — COMPLETE

Phase 0 established the reproducible single-GPU baseline, correctness reference,
and initial Qwen3.6 routing/cache-pressure evidence.

Primary records include:

- [`docs/benchmarks/results/phase0/`](docs/benchmarks/results/phase0/)
- [`docs/investigations/p0i-qwen36-routing-residency.md`](docs/investigations/p0i-qwen36-routing-residency.md)

Phase 0 remains historical evidence; its first-strategy terminology does not
constrain the current resource ontology.

### Phase 1 — two-GPU local candidate — COMPLETE / canonical `NO-GO`

Canonical Phase 1 proved resident remote expert execution correct but was
materially slower than the matched baseline. The immutable verdict for that
**exact tested candidate** is:

`NO-GO`

This is not a blanket rejection of distributed inference, multi-GPU execution,
or remote resident state.

Canonical report:

- [`docs/benchmarks/results/phase1/phase1-go-no-go-report.md`](docs/benchmarks/results/phase1/phase1-go-no-go-report.md)

### Phase1R — local architecture search D1-D7 — COMPLETE

Phase1R investigated why Phase 1 failed and whether a backend-fast-path local
resident architecture could still be useful.

Canonical handoff:

- [`docs/implementation/phase1r-architecture-search-handoff.md`](docs/implementation/phase1r-architecture-search-handoff.md)

Durable evidence includes:

- leaving the current FreeToken/CUDA captured path was catastrophically
  expensive on the tested stack;
- graph-compatible resident remote execution can be performance-positive;
- topology, physical work, transport volume, fan-in, and placement materially
  affect service cost;
- a healthy Gen3 x16 RTX 3060 was performance-positive on the tested path;
- the available Gen2 x1 RTX 3060 was capacity-positive but throughput-negative
  on that tested path;
- this is hardware/topology/runtime-specific evidence, not a universal PCIe
  cutoff or a permanent device class.

Issue #35 remains an independent hardware-causality retest opportunity and does
not block the successor roadmap.

### N0 — selective model-block loading — COMPLETE

Issue #31 completed with:

`N0_SELECTIVE_BLOCK_PASS`

N0 proved, on the pinned Qwen3.6 proving ground:

- checkpoint selection before materialization;
- loading only assigned block state instead of the full model/expert bank;
- bounded block-scoped loading/staging;
- exact isolated-block correctness for prefill/decode fixtures;
- explicit block-local KV/recurrent ownership and complete/disjoint state
  coverage for the frozen split.

N0 **did not** prove that final accelerator-resident state releases all
equivalent persistent CPU backing. The retained `expert_bank_final_host_bytes`
exposed that separate requirement when the next experiment was attempted.

The aborted N1 partial run is non-canonical evidence.

### Resource/residency/planner Wayfinder — COMPLETE

Issue #37 and decisions #38-#46 resolved the foundational doctrine before
further implementation:

- canonical Swarm/Coordinator/Node/Compute Unit/Memory Resource/Link graph;
- Logical State Units, Materializations, residency/staging/cache/replica and
  mutable authority;
- correctness/feasibility-first planning and plan-relative roles;
- measured evidence, baselines, degradation, and quarantine;
- generic planner / Model Execution Strategy boundary;
- immutable Execution Plan epochs, seamless scale-up, and degraded recovery;
- Adaptive Demand Profiles;
- measured distribution-granularity selection;
- documentation/roadmap handoff.

The normative synthesis is
[`docs/architecture/fabric-doctrine.md`](docs/architecture/fabric-doctrine.md).

### Documentation synchronization — issue #47 — COMPLETE

Issue #47 synchronized ADR 0008 and the Fabric Doctrine into the top-level
architecture/roadmap hierarchy, ADR forward/supersession notes, and current
repository guidance. Historical measurements remain unchanged except for
explicit forward scope notes where needed.

### Retired N1-N3 sequence — HISTORICAL SCAFFOLDING

Issues #32-#34 and
[`docs/implementation/distributed-node-poc.md`](docs/implementation/distributed-node-poc.md)
record the earlier coarse-block sequence. They are preserved for reasoning and
provenance but are **not** the active roadmap.

In particular, no work should resume merely by reopening N1, N2, or N3
verbatim. Successor experiments must satisfy the doctrine/evidence gates below.

---

## Completed post-Wayfinder runtime gates

### Runtime Gate R0 — accelerator residency without implicit host mirrors — issue #48 — COMPLETE

Accepted result:

`P48_ACCELERATOR_RESIDENCY_PASS`

Starting from the valid N0 selective-loader substrate, R0 proved that retaining
the tested accelerator materialization does not inherently require retaining an
equivalent persistent host-RAM materialization after bounded staging has
completed.

The accepted evidence established final accelerator-native correctness,
component/materialization accounting, released live host source-bank
materializations, repeated resident execution without lazy rematerialization,
and `unexplained_persistent_host_mirror_bytes == 0` for the proven path.

R0 deliberately did **not** establish OS-level physical host-page reclamation;
that stronger capacity property was later resolved by issue #53.

### R1 — doctrine-shaped frozen-plan realization — issue #50 — COMPLETE

Accepted result:

`R1_FROZEN_PLAN_REALIZATION_PASS`

R1 proved that one explicitly frozen, versioned doctrine-shaped plan can drive
validation, realization, observed-state reconciliation, authority accounting,
staging release, and execution without introducing a generalized optimizer or
freezing public planner/strategy APIs.

The accepted frozen plan preserved correctness, clean intended-vs-observed
reconciliation, backend-fast-path compatibility, zero unplanned persistent
model-state bytes, and zero unexplained persistent host-mirror bytes.

### R2 — local heterogeneous/split execution — issue #51 — COMPLETE

Accepted result:

`R2_LOCAL_SPLIT_EXECUTION_PASS`

R2 proved one nontrivial doctrine-shaped local plan across two independently
identified Compute Units using the frozen contiguous `[0,19) / [19,40)` Qwen3.6
candidate. Under the methodology frozen by issue #52, the split was byte-exact
to the canonical matched reference for W1-W4 generated sequences and selected
logits, with explicit/disjoint state ownership and mutable authority, an exact
measured activation boundary, captured backend-native execution on both sides,
zero steady-state model-state movement, clean reconciliation, and zero
unexplained persistent host model-mirror bytes.

The matched placement evidence remains separate from the architectural pass:
this exact measured two-GPU placement is `PERFORMANCE_NEGATIVE` for decode
throughput (median split/baseline ratio about `0.9122`) while the resident split
showed dramatically lower TTFT. This is candidate/topology evidence, not a
universal device or PCIe rule.

Canonical FreeToken R2 implementation/evidence merged as PR #17, merge commit
`8627f441c880398389042ce8c0a604f6c4321dfa`.

### Pre-R3 host-staging retention and physical reclamation — issue #53 — COMPLETE

Accepted result:

`HOST_STAGING_RECLAMATION_PASS`

Issue #53 resolved the capacity-accounting ambiguity left visible after R2. The
retained pages were anonymous mmap HostBank allocations pinned with
`cudaHostRegister` and held past their useful lifetime by a process-lifetime
retention owner. The accepted RELEASE path physically reclaimed `99.974%`
combined of the known Block A/B staging bytes while both workers and accelerator
banks remained alive; W2/W4 remained byte-exact, and host fetch/source access,
rematerialization, model-state movement, fallback, and graph recapture remained
zero.

This establishes a critical planner-accounting distinction:

- logical source/materialization release;
- intentionally retained host cache/materialization;
- physically available/reclaimed host capacity;

are separate facts.

The current RETAIN path is **not** a proven live-evictable post-finalization
cache and there is no proven post-finalization rematerialization API. Until that
lifecycle is separately demonstrated, `reclaimable_host_cache_bytes` is a
plan-time/lifecycle-policy opportunity, not an on-demand runtime-eviction
capability.

Canonical FreeToken host-reclamation work merged as PR #18, merge commit
`2fc64ae7c79bdc494a52468da329ddafd0adb8ba`.

### R3 — minimum automatic planning — issue #55 — COMPLETE

Accepted result:

`R3_MINIMUM_AUTOMATIC_PLANNING_PASS`

R3 proved the minimum doctrine-shaped automatic-planning seam:

> **strategy constrains; planner chooses.**

Using multiple legal local candidates, a generic planner independently applied
technical feasibility, hard operator policy/integrity eligibility, evidence
applicability, objective ranking, and deterministic tie-breaking without
branching on Qwen/MoE/backend nouns. It selected the evidence-backed
single-resource candidate for warm decode throughput and the resident two-GPU
split for warm TTFT, while preserving technically feasible but lower-ranked
alternatives and explaining unused/excluded resources.

The planner decision and its inputs were frozen and hashed before heavyweight
realization. Selected candidates compiled through the existing strategy/runtime
seam and executed correctly under the accepted reference methodology; R3 did
not become a production scheduler or freeze a public planner/strategy API.

Accepted FreeToken R3 PR #19 merged as
`2ac72d547b2a24a3672d1b83268865db5490084d`. The accepted implementation
producer was `f2ea03738a0162f1f26c57a90e548e2d22119a3b`; the retained evidence head
was `c4b78bc993c549d055a8695e78537ff52bc7033e`.

### R4 — measured multi-node boundary primitive — issue #57 — COMPLETE

Accepted results:

`R4_MULTI_NODE_BOUNDARY_PASS`

`R4_1GBE_PRIMITIVE_CAPACITY_VIABLE`

R4 moved the accepted R2/R3 contiguous `[0,19) / [19,40)` Qwen split from
same-host transport to two physical Nodes (`inferswarm01` and `inferswarm03`)
over one persistent research-internal ordinary-TCP connection. It preserved
byte-exact generated-token correctness and frozen selected-logit identity,
strategy-semantic boundary checksums, backend-native resident execution,
disjoint state ownership/authority, clean reconciliation, #53 RELEASE, and zero
steady-state model-state movement/fallback/recapture/source fetches.

The canonical link was mechanically verified as negotiated 1000 Mb/s full
duplex, MTU 1500, direct LAN. Corrected accepted capacity evidence compares the
actual clean-arm workload wire demand—not socket-buffer timing or transport
microbenchmark capability—against the frozen 80% path margin. Peak measured
application demand was about `2.947 Mb/s` A→B and `0.0769 Mb/s` B→A versus a
`747.12 Mb/s` applicable limit derived from the lower measured sustainable TCP
direction (`933.9 Mb/s`), with zero retransmits.

Canonical provenance:

- accepted R4 physical producer:
  `e97f60b7b0120a72a7cf9926cf6a5c558782c9b2`;
- accepted corrected evidence:
  `d5735c6b5075e835e7e8118922c44a7b0cf7439b`;
- preservation branch head:
  `b2d72a36e79624028e74a2e7256f03546d4b8b5b`.

The earlier R4 evidence head `9a26fd2` is invalidated and retained only as
historical ancestry. FreeToken PR #20 is evidence-bearing but was not a sane
direct merge surface against the then-current upstream-tracking `main`; issue
#59 resolved that integration problem without rewriting accepted R4 history.

R4 establishes a measured viable **primitive capacity result** for this exact
boundary/context. It does not establish production serving, concurrency,
elasticity, failover, a permanent contiguous-block strategy, or a public wire
protocol.

---

## Current correctness-qualification sequence

R0-R5B, the pre-R3 host-capacity prerequisite, Pre-R6 integration (#64), and
external-Coordinator separation (#67) are accepted. FreeToken PR #24 merged
normally into protected `inferswarm-research` as
`84ebd2b7ae56c60292f7b9c7ca256f41f64d8b11`, preserving the final physical
producer `2bcf33f6d6e5dc9fc5c13e37e7110833cbad0fcd` and retained evidence head
`603a63bf44728814d3182191dcd87e21229e5370` in ancestry.

Historical R6 / issue #65 executed from the accepted line and remains
permanently `R6_DENSE_ARCHITECTURE_FALSIFICATION_FAIL`. Issue #71 localized the
first single-versus-distributed difference to legal backend execution on
different devices. Its accepted classification is `BACKEND_EXECUTION_LOCAL`.
The exact state and transport proofs remained intact. The localization did not
set a tolerance and did not convert R6 into a pass.

ADR 0010 / issue #72 defines the three-layer heterogeneous correctness contract:
exact integrity, qualified numerical execution equivalence, and
strategy-declared semantic output correctness. Issues #74, #77, and #79 are
complete: they froze the first prospective Gemma numerical methodology, repaired
the stress-selection semantics without changing the pre-registered margin
definition, and completed the versioned calibration/threshold/unseal tooling.

Issue #76 remains the stopped v1 qualification attempt at
`PHASE0_REFERENCE_COMPLETE / STRESS_SELECTION_BLOCKED`. Issue #81 is also
complete and remains a valid terminal `CALIBRATION_SEMANTIC_FAIL`: all 584
Phase-D cases completed on both arms with exact case identity and zero NaN/Inf,
but the strict exact-token semantic profile changed at least one greedy token in
236/576 statistical cases and 4/8 stress cases. Threshold derivation never
started, and the retained sealed holdout was never opened. PR #82 merged the
immutable #81 evidence record at
`46a5d6da6ed63722c2d43dc49edfbac6c91fd915`.

Issue #83 is complete: the semantic contract for heterogeneous greedy
decoding was accepted at
`d60b8f6c4490c91312e8d073b4ac55794bf68841` (PR #85). It prospectively
defines semantic correctness — canonical-prefix numerical replay separated
from free-running behavior, decision stability near argmax ties, the
mandatory full-vocabulary `E_full` envelope, the supplemental decision-local
`E_D` bound with fail-closed `DECISION_LOCAL_BOUND_EXCEEDED` /
`DECISION_DOMAIN_ESCAPE` gates, and preservation of the strict exact-token /
`BIT_EXACT_REQUIRED` profile.

Issue #86 is complete. It prospectively froze the first Gemma v3
implementation of the #83 decision-stability contract: fresh c86/p86/h86
corpora, `reference-top-1024-with-cutoff-ties/1`, the supplemental `E_D`, the
16-family simultaneous statistical design, frozen `ARGMAX_FIRST_MAX` semantics,
CPU-only derivation/evaluation/unseal-preflight tooling, and a fresh sealed v3
holdout. PR #87 was accepted at methodology head
`a8ec98a9fb9b673c93de5100d784ea772395efdb`.

Issue #88 is complete with immutable terminal verdict:

`V3_HOLDOUT_FAIL`

The physical campaign passed exact integrity and the new decision-stability
semantic layer throughout: 4672/4672 calibration decisions and 192/192 holdout
decisions were `SEMANTIC_PASS`, with zero `DECISION_DOMAIN_ESCAPE`, zero
`DECISION_LOCAL_BOUND_EXCEEDED`, and zero NaN/Inf. One mandatory inherited
numerical envelope nevertheless exceeded its frozen holdout limit:
`h86-03-05-01` `final-normalized-hidden-state:rms-difference` observed
`2.6800369574218053` versus limit `2.6131138414325275` (+2.56%). Under ADR 0010
and the frozen v3 conjunction, matching semantic output cannot waive that
numerical failure.

Accepted provenance:

- InferSwarm evidence PR #89 merged as
  `dc00dd933fcbdcaddffc0c9fd4fd25baf5b70da5`;
- FreeToken physical producer PR #30 merged to `inferswarm-research` as
  `5e44be50cd9ed322366a01cd5d80d958950d1ac5`;
- physical producer `560bb7e833ad4ca9386eb87799bb0aafb82b3e59`.

Issue #90 is the **CURRENT correctness-qualification gate**. It diagnoses the
post-v3 numerical-envelope failure from retained #88 evidence before any
successor methodology is frozen. It must distinguish ordinary tail behavior,
a pre-observable applicability split, metric/envelope mismatch, and an actual
execution anomaly; reconstruct the failing value from retained bytes; trace its
propagation through `E_full`, `E_D`, and semantic decisions; and audit the v3
statistical claim against the separate zero-exceedance holdout rule. It does not
authorize a v3 rerun, post-hoc threshold change, successor threshold, fresh
holdout, or physical v4 campaign.

Issue [#59](https://github.com/Zutfen-LLC/inferswarm/issues/59) is complete. It
established the durable FreeToken `inferswarm-research` implementation line
without rewriting accepted R4 history.

### R5A — static end-to-end multi-node serving — issue #60 — COMPLETE

Issue [#60](https://github.com/Zutfen-LLC/inferswarm/issues/60) is complete with
accepted result:

`R5A_STATIC_MULTI_NODE_SERVING_PASS`

Canonical FreeToken provenance:

- physical implementation producer:
  `60ea7bd9841a636a26bfe7f140dba04b0a562f03`;
- accepted evidence head: `136fc6385afaa0864e289746484b211f3a1fcdd8`;
- merged protected `inferswarm-research` head:
  `d9f45a9ef7b5f89800f96c54397202a7d43beb52`.

R5A proved that the pieces established separately by R0-R4 operate as one
static serving path:

```text
normal host-runtime request
  -> strategy legal candidates
  -> generic planner + current evidence/policy
  -> frozen Execution Plan
  -> multi-Node realization
  -> backend-native distributed execution
  -> correct response
```

Unlike R4, applicable network performance evidence existed. The generic
evidence/applicability rules ingested or rejected that evidence honestly, and
the planner did not hard-code a network preference simply because R5A was a
network-serving test.

Accepted retained evidence includes, under matched controls and a frozen
objective/methodology:

- request-level correctness and session isolation;
- planner candidates, evidence applicability, ranking, selected plan, and
  explanations for unused/excluded/lower-ranked resources;
- TTFT;
- prefill wall/throughput;
- decode tok/s and inter-token latency;
- complete request wall time;
- network application bytes/contribution;
- realization/startup cost;
- RAM/VRAM/materialization and staging-release accounting;
- paging/swap evidence;
- capture/replay/fallback/recapture/source-fetch invariants;
- a bounded multi-request/session concurrency arm.

R5A is **static serving**. It did not claim live plan changes, failover, or
resource joins/leaves. Its accepted context-specific median TTFT measurements
were approximately `373.6 ms` for the same-Node resident plan, `1877.5 ms` for
the two-Node resident plan, and `2630.6 ms` for the source-backed control. These
historical benchmark claims remain scoped to their frozen context.

That prerequisite unblocked R5B; R5A itself made no live
elasticity/recovery claim.

---

## Successor evidence gates

The names below describe intended sequence and questions. Concrete methodology
should be frozen only when predecessor evidence makes it knowable.

### R5B — plan epochs, scale-up/down, and recovery — issue #62 — COMPLETE

Issue [#62](https://github.com/Zutfen-LLC/inferswarm/issues/62) is complete with
accepted result:

`R5B_PLAN_EPOCH_RECOVERY_PASS`

Canonical FreeToken provenance:

- physical implementation producer:
  `7dd945a67c04198ec2d9afe782a39c90e8141f5e`;
- accepted evidence head: `b6f674b5bf0f76b9b40bd2f79e36cfc18cb6f7e6`;
- merged protected `inferswarm-research` head:
  `00ccd01fede8d2ad21ee83104f3b998c89ff9d1f`.

Exercise the execution-plan epoch and failure semantics already decided by #43
through a real serving path.

#### Scale up

Add a beneficial resource/Node while serving, characterize it, prepare a better
replacement epoch while the current epoch remains valid, and activate it at a
strategy-safe boundary when the measured benefit and policy justify the switch.

#### Scale down

Remove a required resource/Node and prove InferSwarm searches the surviving
trusted graph for the best correct feasible recovery plan—even when it must use
slower/smaller GPUs, CPU/RAM, caches/replicas, or a different legal granularity.

Service should fail only when no feasible plan exists or required authoritative
mutable state cannot be safely recovered under the declared state contract.

#### Scale back up

Return/add useful resources and demonstrate a later optimization epoch where
expected benefit warrants it.

Transparent zero-downtime failover is not a universal acceptance criterion;
correct epoch ownership, authority continuity, truthful recovery semantics, and
late-work rejection are.

R5B satisfied the resource/planner/epoch prerequisite under real changes. Its
accepted evidence remains immutable.

### Pre-R6 integration refresh — issue #64 — COMPLETE

Issue [#64](https://github.com/Zutfen-LLC/inferswarm/issues/64) refreshed the
durable FreeToken `inferswarm-research` line with the explicitly integrated
and requalified upstream target. Accepted disposition:
`PRE_R6_INTEGRATION_REQUALIFICATION_PASS` at accepted research head
`8cfcda4c44065ceba4230dc548a12696093d5177`.

### Pre-R6 external Coordinator separation — issue #67 — COMPLETE

Issue [#67](https://github.com/Zutfen-LLC/inferswarm/issues/67) proved the
Coordinator is a replaceable control-plane role rather than an implicit
compute-host role: ordinary request ingress, session identity, generic
planning, frozen Execution Plan authority, epoch coordination, and
committed-output accounting physically executed on the CPU-only VM
`inferswarm00` (no NVIDIA driver, CUDA, torch, triton, native execution
extensions, or model weights), while all model materialization and
correctness-bearing inference executed on `inferswarm01`/`inferswarm03`
over a bounded research-internal realization wire.

Accepted disposition: `EXTERNAL_COORDINATOR_SEPARATION_PASS`.

Canonical FreeToken provenance:

- final physical implementation producer:
  `2bcf33f6d6e5dc9fc5c13e37e7110833cbad0fcd`;
- accepted retained evidence head:
  `603a63bf44728814d3182191dcd87e21229e5370`;
- normal merge of FreeToken PR #24 into protected `inferswarm-research`:
  `84ebd2b7ae56c60292f7b9c7ca256f41f64d8b11`.

Evidence is retained in FreeToken `docs/inferswarm_external_coordinator/`.
The earlier physical producers `df8a429e9110…` and `84e531971d6c…` remain in
history as explicitly superseded evidence and are not the canonical gate proof.

### R6 — architecture falsification with Gemma 4 12B — issue #65 — FAILED

Historical R6 ran on its frozen FreeToken ancestry and produced
`R6_DENSE_ARCHITECTURE_FALSIFICATION_FAIL`. This result is permanent.

Before declaring a public Model Execution Strategy/planner interface stable,
validate the doctrine against a model architecture materially different from
the first Qwen sparse proving ground.

A dense model is especially useful because it removes expert sparsity as an
easy decomposition assumption.

The purpose is not necessarily to beat the Qwen benchmark. It is to ask:

- can the strategy expose legal opaque units without changing the generic
  resource ontology?
- can the planner reason without expert/router assumptions?
- do state/residency/authority semantics remain sufficient?
- does granularity remain a measured strategy choice?
- which internal interfaces were accidental first-model artifacts?

Revise internal APIs freely if the falsification test exposes a better seam;
change doctrine only if a foundational invariant itself is disproven.

Issue #71 later localized the observed numerical difference as
`BACKEND_EXECUTION_LOCAL`. It preserved byte-exact model state, inputs, and
transport. This diagnosis does not relax the historical R6 comparator.

### Heterogeneous correctness contract — issue #72 / ADR 0010 — COMPLETE

ADR 0010 defines correctness as the conjunction of exact integrity, qualified
numerical equivalence, and strategy-declared semantic output. The Model
Execution Strategy owns the comparator and semantic contract. The generic
planner consumes applicable qualification evidence before performance ranking.

### First numerical-equivalence methodology freeze — issue #74 — COMPLETE

Issue #74 prospectively froze the first Gemma/FreeToken qualification method:
576 balanced calibration prompts, reference-only stress selection, 15 numerical
envelopes, distribution-free threshold derivation, a sealed 24-case holdout,
evidence schemas, and invalid-run rules. Historical v1 artifacts remain
immutable.

### Methodology-v2 and executable tooling — issues #77 / #79 — COMPLETE

Issue #77 prospectively repaired the stress-pool eligibility semantics after the
stopped #76 attempt without changing the pre-registered min-over-8 margin
definition. Issue #79 then bound the v2 `p76-*` stress artifacts to versioned
calibration-summary, threshold-freeze, and holdout-unseal tooling while
preserving the unchanged 576-case `c74-*` statistical corpus and threshold math.

### Qualification execution — issues #76 / #81 — COMPLETE / FAILED

Issue #76 stopped before candidate execution because its v1 selector could not
handle genuine zero-margin ties. Issue #81 completed the v2 physical campaign
through full calibration and stopped correctly at `CALIBRATION_SEMANTIC_FAIL`:
236/576 statistical cases and 4/8 selected stress cases changed at least one
greedy token under the strict exact-token profile. Exact integrity passed,
NaN/Inf remained zero, thresholds were never derived, and the retained holdout
remains sealed.

### Heterogeneous greedy semantic contract — issue #83 — COMPLETE

Issue #83 accepted the prospective decision-stability semantic contract at
`d60b8f6c4490c91312e8d073b4ac55794bf68841` (PR #85). It separates
canonical-prefix numerical replay from free-running post-branch behavior,
preserves the mandatory full-vocabulary `E_full` numerical envelope, adds the
supplemental decision-local `E_D`/domain-containment/stability theorem, freezes
deterministic argmax/tie semantics, and preserves strict exact-token /
`BIT_EXACT_REQUIRED` as a separate stronger profile.

#81 remains `CALIBRATION_SEMANTIC_FAIL`; #83 did not reinterpret it.

### Gemma v3 methodology and physical qualification — issues #86 / #88 — COMPLETE / FAILED

Issue #86 froze the first executable Gemma v3 decision-stability methodology
before physical execution. Issue #88 then executed it end to end under the
frozen topology and terminated honestly with:

`V3_HOLDOUT_FAIL`

The semantic objective itself passed everywhere, including the fresh holdout,
but one mandatory `final-normalized-hidden-state:rms-difference` envelope
exceeded its frozen limit by 2.56%. Evidence PR #89 and FreeToken producer PR
#30 are merged; the failure is immutable and does not authorize threshold
tuning or rerun.

### Post-v3 numerical-envelope diagnosis — issue #90 — CURRENT

Issue #90 is the next active gate. Using retained #88 evidence only, determine
whether the single holdout exceedance is best explained by ordinary tail
behavior, a real pre-observable applicability regime, a metric/envelope mismatch,
an execution anomaly, or a mixed/inconclusive result.

The gate must reconstruct the exact failure, characterize the full failing-family
distribution, test applicability splits, trace propagation into `E_full`, `E_D`,
and semantic decisions, and audit the v3 distribution-free tolerance claim
against its separate zero-exceedance holdout acceptance rule.

No v4 methodology, threshold, fresh holdout, or physical campaign may be frozen
from this gate. A successor method becomes eligible only after #90 makes the
remaining statistical/correctness question concrete.

### R6 successor full integration attempt — future independent gate

A new dense full-integration attempt remains blocked on applicable successor
qualification evidence. Do not reuse the historical R6 verdict, back-fit new
limits to R6/#81/#88 evidence, or treat any failed campaign as a pass.

---

## Deferred validation targets

### GLM-5.3-Flash — issue #13

GLM-5.3-Flash remains a valuable **large heterogeneous-capacity** validation
target, not an assumption baked into the substrate.

Resume its investigation after the model-strategy and heterogeneous-capacity
foundation is strong enough to evaluate the exact pinned model honestly.

The investigation should census its real state/architecture and evaluate any
strategy authorized by the doctrine—coarse stages, local sparse placement,
mixed accelerator/RAM residency, caches/replicas, or combinations—rather than
forcing Qwen or ADR 0007 semantics onto it.

### Heterogeneous vendors

AMD/ROCm, Intel XPU/Arc, CPU-native paths, and future accelerators remain
long-term product goals.

Near-term Qwen/NVIDIA/FreeToken-specific code is acceptable when isolated
inside a research strategy/backend implementation. Vendor abstraction should be
extracted when real evidence identifies the stable seam, not invented ahead of
proof.

#### Portable accelerator backend hypothesis

InferSwarm should explicitly evaluate Vulkan as a common portable accelerator
execution substrate across NVIDIA, AMD, Intel, and other Vulkan-capable
hardware. The architectural hypothesis is that a portable Vulkan path may
provide sufficient inference performance—particularly for decode and
strategy-specific distributed workloads—to serve as a default execution
substrate, while vendor-native CUDA, HIP/ROCm, SYCL, or other backends remain
optional performance optimizations beneath the same backend-independent
resource/planner semantics.

This is **not yet a decision that Vulkan is the preferred backend**. Promotion
of Vulkan to a preferred/default backend policy requires matched InferSwarm
correctness and performance evidence, including native-versus-Vulkan comparison
on at least NVIDIA and AMD hardware and cross-vendor execution where practical.
The comparison should measure workload-relevant decode and prefill behavior,
materialization/representation cost, memory use, correctness/equivalence, and
mixed-device operation rather than relying on generic GEMM results alone.

The generic resource graph and planner must not encode CUDA, ROCm, Vulkan,
SYCL, or another execution API as hardware identity. Backend availability,
representation support, correctness qualification, and measured economics are
capabilities/evidence associated with a resource and execution strategy. A
future ADR may establish a portable baseline backend policy only after this
evidence identifies the stable execution seam and demonstrates that the
simplicity/coverage benefit is worth any measured performance cost.

### Adaptive Demand Profiles

Demand-profile learning from model-wide, profile/Swarm history, and live
structural demand is doctrine-approved but does not block the completed R0-R4
gates or current R5A.

Introduce it only when a strategy exposes a meaningful demand signal and there
are enough legal placement alternatives for adaptation to matter. It should be
possible without persistent raw prompt/response retention.

### Cache/promotion and progressive materialization

The doctrine permits executing against valid caches, streaming/progressive
promotion, and prepared materializations where strategy/backend semantics allow
it. Concrete policies should be introduced only when measured economics justify
them.

Issue #53 does not establish the current RETAIN source banks as a live-evictable
post-finalization cache; do not use that unproven lifecycle as planner capacity.

### Future NVMe/CXL/storage roles

Do not block future backing/storage resources, but do not predefine an intrinsic
NVMe tier or assume it belongs on the latency-critical hot path.

### Local topology follow-up — issue #35

The Gen3 x8 third-GPU retest remains useful hardware-causality evidence. Its
result can refine applicable resource/path evidence but does not define a
universal link-class policy or block the current R5A serving gate.

---

## Evidence and issue discipline

- InferSwarm issues are canonical for experiment questions, gates, and
  acceptance criteria.
- FreeToken carries focused implementation experiments and links back to the
  corresponding InferSwarm issue.
- Exact tested commits/model revisions/hardware/topology/runtime geometry are
  frozen with retained results.
- Every numeric claim follows `BENCHMARKING.md` evidence labels:
  `MEASURED`, `CALCULATED`, `ESTIMATED`, or `SPECULATIVE`.
- Microbenchmarks diagnose; end-to-end inference concludes end-to-end claims.
- A fast-but-wrong path is a bug, not a result.
- Negative results are preserved. A failed experiment changes the roadmap; it
  does not disappear from project history.
- New downstream issues should be created when prior evidence makes their
  concrete methodology/acceptance criteria knowable, rather than precreating a
  long speculative implementation ladder.