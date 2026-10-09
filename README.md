# InferSwarm

**by Zutfen LLC**

> **Research goal: correct inference on heterogeneous, commodity hardware, to
> extend which models and workloads an operator's existing resources can run.**
> Performance is a second, operator-relative question. This is a goal under
> test, not a demonstrated general capability.

**Many machines. One model.**

*What is demonstrated, and what is not, is bound to evidence in the
[capability evidence matrix](docs/capability-evidence-matrix.md).*

```text
Status: Research / Proof of Concept
```

InferSwarm is an experimental Apache-2.0 project that asks whether resources
which do not look alike (different vendors, generations, memory sizes, links
and machines) can cooperate on one inference request, and whether that extends
what the hardware an operator already owns can run correctly. It does not
require every device to look like the same kind of worker, and it does not
assume that every available resource should take part in every plan.

There is no released production InferSwarm runtime and no general heterogeneous
planner or runtime today. The repository is the canonical home for
architecture decisions, the normative Fabric Doctrine, benchmark/evidence
records, and the current evidence-gated roadmap. Research execution has mostly
run through the
[Zutfen FreeToken fork](#current-implementation-vehicles) as research-internal
harnesses, plus one deliberately narrow in-repo
[operator path](#current-implementation-vehicles).

## Mission: extend what can run correctly

**Primary research goal: capability.** When no individual device or machine an
operator has can run a requested model and workload correctly by itself, can a
plan across their mismatched, inexpensive resources still run it? Expanding the
set of models and workloads that are feasible on existing hardware is the first
thing InferSwarm tries to demonstrate. Cheaper or faster execution of work that
a single resource already handles is not the primary goal.

**Secondary, operator-relative dimension: performance.** Throughput, latency,
energy and cost decide which *feasible* plan to prefer and what a capability
costs. They do not decide whether a correct plan is feasible unless the operator
sets an explicit service requirement. A slow, correct plan can be a valid
capability result and still be unsuitable for a given service level, and neither
statement is a verdict on the hardware or on heterogeneous inference in general.

### The planning rule is ordered

The [Fabric Doctrine](docs/architecture/fabric-doctrine.md) (section 1, and
section 4 for the feasible-plan set and ranking) and
[ADR 0008](docs/adr/0008-canonical-fabric-doctrine.md) fix the order applied to
a requested model/workload and the resources an operator contributes. This
section restates it; it does not change it.

1. **Correct and technically feasible.** Only plans that satisfy the Model
   Execution Strategy's legal boundaries, backend and representation
   compatibility, state coverage, memory fit with headroom, execution and
   communication paths, resource availability and integrity trust are
   candidates. Expected poor performance alone does not remove a plan.
2. **Hard operator constraints.** Eligibility, reservations, limits and explicit
   minimum service requirements remove plans; technical feasibility and policy
   feasibility stay distinct.
3. **Ranking.** Among the plans that remain, prefer the one expected to deliver
   the greatest useful service under current evidence: TTFT, decode rate,
   throughput, communication cost, stability, energy or budget as the operator
   weights them.

Legal distribution does not imply required distribution. A healthy compatible
resource may stay unused when adding it would add no value, and maximizing
device count or utilization is not the objective.

### Two capacity claims, kept apart

- **GPU-residency expansion.** Adding a resource lets more of a model's
  required state sit in accelerator memory than the best single-resource
  comparison can hold. That comparison may still complete, slowly, through host
  RAM, so this is a capacity gain rather than necessarily a feasibility gain,
  and it never implies a speedup.
- **Whole-model feasibility.** The model/workload cannot be run correctly at
  all under a declared single-resource envelope (one device or one host, with
  runtime, representation, context length and headroom stated in advance), but
  runs correctly when additional resources are added.

Accepted evidence supports the first claim on specific tested substrates, and
one homogeneous-NVIDIA precedent for the second. Whole-model feasibility with
heterogeneous resources is **not yet demonstrated**. The
[evidence matrix](docs/capability-evidence-matrix.md) records which result
supports which claim.

### What each kind of resource contributes

- **Compute:** GPUs and CPUs of different vendors, generations and speeds. They
  are not interchangeable, and each participates only where a plan finds it
  compatible and useful. Evidence differs by vendor today: NVIDIA has physical
  results on CUDA and Vulkan, AMD has bounded Vulkan results, and Intel GPUs
  have only been enumerated. No accepted result qualifies mixed-vendor
  numerical equivalence or serves a mixed-vendor model through the operator
  path; the one accepted mixed AMD plus NVIDIA Vulkan layer split (Issue #35)
  is a single-host link-economics characterization.
- **Memory:** GPU VRAM/HBM and system RAM are separate domains with distinct
  roles (model state, KV/recurrent state, staging, cache). The two dies of a
  dual-GPU card are two memory resources, not one pooled address space.
- **Storage:** SSD and other storage hold verified artifacts as backing and as a
  source or cache. Stored bytes are never counted as GPU memory and do not
  execute kernels. Roles for NVMe, CXL or other storage in active plans, beyond
  verified artifact backing, are future questions under the Doctrine.
- **Links:** PCIe and ordinary Ethernet carry boundary state and artifacts at a
  measured cost. A narrow link can be capacity-positive yet throughput-negative
  for one placement (accepted Issue #35 and the Phase1R D3-D7 results); that is a role-specific
  finding, not a verdict on the link or the GPU.

### What the evidence shows

The [capability evidence matrix](docs/capability-evidence-matrix.md) binds every
claim to its code, its accepted record and the scope of that record, in four
classes:

| Class | Where things stand |
|---|---|
| `IMPLEMENTED_AND_PHYSICALLY_PROVEN` | One path: the fixed-topology llama.cpp CUDA/RPC [operator path](#current-implementation-vehicles), accepted for one tested two-host NVIDIA topology. |
| `CPU_OR_FIXTURE_PROVEN` | Artifact acquisition, peer reuse and locality ranking (#99, #101, #103), and CPU/loopback launcher and observer checks. |
| `RESEARCH_INTERNAL` | Accepted physical results obtained through research harnesses whose interfaces are explicitly not public: the FreeToken N0 and R1-R5B work, the external Coordinator, R6/V5 Gemma, and the in-repo Vulkan, V340L and link characterizations. |
| `ASPIRATIONAL_OR_UNPROVEN` | Whole-model feasibility with heterogeneous resources, a general planner or runtime, mixed-vendor serving, Intel execution, pooled or cross-die memory, and general performance superiority. |

"Correct" is scoped in the accepted CUDA/RPC results: they show coherent,
repeatable generation, not numerical equivalence. The accepted R8-D record found
exact-token divergence from a non-RPC reference on two of four corpus cases, and
[ADR 0010](docs/adr/0010-heterogeneous-numerical-equivalence.md) does not define
product correctness as bitwise identity.

**FreeToken is the original research and integration vehicle, not the InferSwarm
product boundary.** The generic fabric must stay model- and vendor-independent:
model execution strategies define legal work and state boundaries, and generic
planning assigns them to available Compute Units, Memory Resources, backing
Sources and Links under measured constraints.

## Canonical docs

Repository precedence is:

> **[ADRs](docs/adr/README.md) decide; the
> [Fabric Doctrine](docs/architecture/fabric-doctrine.md) specifies;
> [ARCHITECTURE.md](ARCHITECTURE.md) explains;
> [ROADMAP.md](ROADMAP.md) sequences.**

[ADR 0008](docs/adr/0008-canonical-fabric-doctrine.md) adopts the current
resource/residency/planning model after the completed Wayfinder (#37,
decisions #38-#46).

The architecture is **doctrine-shaped, API-unfrozen**: current implementation
must preserve the doctrine's semantics, but final public planner/strategy type
names, plugins, wire protocols, and storage schemas are deliberately deferred
until real implementations prove the seam.

## What the research has established

The table lists only capabilities with a recorded maintainer acceptance, each
bounded to its stated scope. The
[capability evidence matrix](docs/capability-evidence-matrix.md) adds the
research-internal, fixture-only and unproven context around them.

<!-- project-status:capabilities:start -->
| Capability | Evidence scope | Demonstrated result |
|---|---|---|
| Automatic planning | Physical | Strategy-constrained selection among legal local plans using applicable evidence and operator policy. [Evidence](https://github.com/Zutfen-LLC/inferswarm/issues/55#issuecomment-5495529413); [acceptance](https://github.com/Zutfen-LLC/inferswarm/issues/55#issuecomment-5495529413). |
| Distributed serving | Physical | A normal request drives planning, multi-Node realization, and backend-native execution on the tested Qwen path. [Evidence](https://github.com/Zutfen-LLC/inferswarm/issues/60#issuecomment-5504161037); [acceptance](https://github.com/Zutfen-LLC/inferswarm/issues/60#issuecomment-5504161037). |
| Plan epochs and recovery | Physical | Resource changes and recovery preserve plan-epoch authority and reject retired work on the tested serving path. [Evidence](https://github.com/Zutfen-LLC/inferswarm/issues/62#issuecomment-5508822299); [acceptance](https://github.com/Zutfen-LLC/inferswarm/issues/62#issuecomment-5508822299). |
| Separate Coordinator | Physical | A CPU-only Coordinator handles ingress, planning, epoch coordination, and committed output without hosting model execution. [Evidence](https://github.com/Zutfen-LLC/inferswarm/issues/67#issuecomment-5516608982); [acceptance](https://github.com/Zutfen-LLC/inferswarm/issues/67#issuecomment-5516608982). |
| Selective artifact acquisition | CPU fixture | Participants acquire only required model artifacts in the model-independent acquisition proof. [Evidence](https://github.com/Zutfen-LLC/inferswarm/blob/53fb8f4c7ba3108a21f983712e5cbdb747a26600/docs/implementation/plan-driven-artifact-acquisition-99/README.md); [acceptance](https://github.com/Zutfen-LLC/inferswarm/commit/53fb8f4c7ba3108a21f983712e5cbdb747a26600). |
| Peer reuse and replacement deltas | CPU fixture | Verified inventory, source selection, peer publication, and replacement-plan acquisition work across participants. [Evidence](https://github.com/Zutfen-LLC/inferswarm/blob/ffbc51a85dfa492b11ff8f3b0ea31b7762d6a5da/docs/implementation/plan-driven-artifact-orchestration-101/README.md); [acceptance](https://github.com/Zutfen-LLC/inferswarm/commit/ffbc51a85dfa492b11ff8f3b0ea31b7762d6a5da). |
| Locality-aware transition planning | CPU fixture | Verified artifact locality affects transition ranking without changing technical feasibility or execution ranking. [Evidence](https://github.com/Zutfen-LLC/inferswarm/blob/47624abe14a84d27188018200a48a8652f93bfd6/docs/implementation/artifact-locality-transition-planning-103/README.md); [acceptance](https://github.com/Zutfen-LLC/inferswarm/commit/47624abe14a84d27188018200a48a8652f93bfd6). |
| Dense Gemma numerical qualification | Physical | The frozen Gemma subject passed V5 numerical and semantic qualification; applicability remains specific to that subject. [Evidence](https://github.com/Zutfen-LLC/inferswarm/blob/546ff9d44c727b6eba5abf3c8b40669b0b9b0b76/docs/qualification/gemma4-12b-it-v5-campaign-110/b/TERMINAL-REPORT.md); [acceptance](https://github.com/Zutfen-LLC/inferswarm/commit/546ff9d44c727b6eba5abf3c8b40669b0b9b0b76). |
| Bounded two-host CUDA/RPC inference | Physical | One ordinary Qwen3.8-Flash-Next-UD-IQ1_S text-generation request executed materially on two homogeneous NVIDIA/CUDA hosts using fixed/manual placement and verified participant-local backing; applies only to the tested inferswarm01 RTX 3060 + inferswarm04 RTX 3090 topology and accepted runtime/artifact lineage. The recorded single-host comparison also completed and was faster on the first requests (4.411 versus 3.925 tok/s), so no capacity or speed advantage is established. [Evidence](https://github.com/Zutfen-LLC/inferswarm/issues/255#issuecomment-5971666116); [acceptance](https://github.com/Zutfen-LLC/inferswarm/issues/255#issuecomment-5974171991). |
| Ordinary fixed-topology CUDA/RPC operator path | Physical | One ordinary run of the `inferswarm.operator` module executed an operator-supplied fixed llama.cpp CUDA/RPC plan with exactly two participants (one client, one remote), one fixed three-range layer placement, and verified participant-local backing; three bounded requests completed on the tested inferswarm01 RTX 3060 plus inferswarm04 RTX 3090 topology with the exact Qwen3.8-Flash-Next-UD-IQ1_S release and accepted llama.cpp lineage. Remote request compute is attributed by request-bracketed CUDA backend graph-log deltas plus pinned source semantics; remote sampled SM stayed zero and is not positive utilization. This is not a planner, a capacity or speed result, or a numerical-equivalence, mixed-vendor, dynamic-scheduling, production, or Vulkan claim. [Evidence](https://github.com/Zutfen-LLC/inferswarm/blob/438c09ff1f3fb0e161f0bbf6d8389554ab8a1515/docs/implementation/ordinary-operator-path-268/product-report.md); [acceptance](https://github.com/Zutfen-LLC/inferswarm/issues/268#issuecomment-5979357776). |

- Research / proof of concept; no released production runtime.
- Issue #209 R7-B derived R7B_DEEPSEEK_V41_PHYSICAL_GATE_READY at https://github.com/Zutfen-LLC/inferswarm/pull/211 from retained pinned vLLM lifecycle source; compact fixture substrate-contract only, maintainer acceptance pending, and it grants no execution authorization.
- Physical results apply to their tested model, backend, hardware, and topology. CPU fixture proofs do not establish physical integration.
- Issues #255 and #268 are accepted as MVP_DISTRIBUTED_INFERENCE_PASS (https://github.com/Zutfen-LLC/inferswarm/issues/255#issuecomment-5974171991) and R8K_QWEN_CUDA_ORDINARY_OPERATOR_PATH_PASS (https://github.com/Zutfen-LLC/inferswarm/issues/268#issuecomment-5979357776) only for the bounded tested homogeneous NVIDIA/CUDA two-host topology, exact Qwen3.8-Flash-Next-UD-IQ1_S and llama.cpp lineage, fixed placement, verified participant-local backing, and ordinary text generation. The operator path is a fixed-topology path for exactly two participants and one three-range layer placement, not a general heterogeneous planner or runtime. No numerical-equivalence, capacity or speed advantage over the recorded single-host comparison, mixed-vendor, production-readiness, dynamic-scheduling, or R8-J/Vulkan authority is implied.
- Correctness in the accepted CUDA/RPC results means coherent, repeatable generation, not numerical equivalence: the accepted R8-D record (Issue #195, PR #197) is a scoped FAIL with exact-token divergence from the non-RPC reference on two of four corpus cases (case-256 at generated position 5; case-4096 immediate EOS), and R8-G characterized the divergence as non-monotonic without identifying one cause. ADR 0010 does not define product correctness as bitwise identity.
- Whole-model feasibility expansion with heterogeneous resources is not yet demonstrated. Accepted capacity-positive evidence is GPU-residency expansion where the single-resource comparison still completed (R2 and R5A against a matched single-GPU offload or source-backed control; Issue #35 on a 14B Q4_K_M model, where the over-capacity single-device control completed at about 0.2 tok/s), plus one homogeneous NVIDIA Gemma chain whose single 12 GiB GPU-resident envelope was infeasible (R6 census, qualified for its frozen subject by V5). These are separate claims and none implies a speedup.
- Each V340L die is a distinct HBM resource of about 8 GiB. Accepted Issue #243 evidence covers independent per-die execution on one tested host, not one coherent 16 GiB pool, peer or cross-die execution, numerical qualification, or universal cooling; no accepted same-request dual-die result exists.
- Storage is verified artifact backing and a cache or Source, never GPU memory and never a kernel-executing resource; accepted physical evidence uses local SSD backing, and any NVMe, CXL, or other storage role beyond verified artifact backing remains a future question under the Fabric Doctrine.
- Public planner/strategy APIs, wire formats, and storage schemas remain unfrozen; broad vendor support remains an objective.
- Historical Phase 1 NO-GO and R6 failure remain unchanged. GLM-5.3-Flash / #13 is a later falsifier.
<!-- project-status:capabilities:end -->

Earlier work established selective loading, accelerator residency without an
unexplained persistent host mirror, and local/multi-Node execution on Qwen.
Canonical Phase 1 retained a scoped `NO-GO` performance verdict; subsequent
Phase1R experiments established topology-dependent performance and capacity
tradeoffs (a narrow link can add capacity while costing throughput). See
[ROADMAP.md](ROADMAP.md) and the
[historical Phase1R record](docs/implementation/phase1r-architecture-search-handoff.md)
for the exact experiments and immutable results.

## Current research direction

The active gates below serve a capability question rather than being the
question itself: **a model or workload that is demonstrably infeasible under a
declared single-resource envelope, and correctly executable once additional
heterogeneous resources are added**, reported separately from GPU-residency
expansion and from performance. This direction authorizes nothing and creates no
new experiment; Issues [#279](https://github.com/Zutfen-LLC/inferswarm/issues/279)
and [#281](https://github.com/Zutfen-LLC/inferswarm/issues/281) are the existing
gates where it would be scoped, each with its own approval.

<!-- project-status:frontier:start -->
**[Issue #280 — AMD-only Vulkan same-request pooling (candidate-B-only result STOP; authorization spent)](https://github.com/Zutfen-LLC/inferswarm/issues/280)**

Issue #268 is accepted as R8K_QWEN_CUDA_ORDINARY_OPERATOR_PATH_PASS on exact reviewed head 438c09ff1f3fb0e161f0bbf6d8389554ab8a1515, merged as 4c6df96cd03e50fbb990256507eb859769536aad (https://github.com/Zutfen-LLC/inferswarm/issues/268#issuecomment-5979357776), and Issue #255 remains accepted as MVP_DISTRIBUTED_INFERENCE_PASS (https://github.com/Zutfen-LLC/inferswarm/issues/255#issuecomment-5974171991). Both are bounded to the homogeneous NVIDIA/CUDA two-host topology inferswarm01 RTX 3060 plus inferswarm04 RTX 3090, the exact Qwen3.8-Flash-Next-UD-IQ1_S release and llama.cpp b29c606e28a01b1bc8c1351026a0fa6e616bf6c4 lineage, fixed placement, and verified participant-local backing; they establish no capacity or speed advantage over the recorded single-host comparison. The Issue #188 roadmap priority of 2026-10-06 is AMD-only Vulkan same-request pooling: Issue #280 first, Issue #281 queued behind an accepted #280 result and an explicit CONTINUE decision, and Issue #279 (CUDA capacity/value proposal) open at lower priority as planning only. Issue #280 asks whether the two dies of one V340L can hold useful parts of one model and both execute one request through Vulkan. Its single-use candidate-B-only physical experiment terminated STOP: the cold request proved the same-request two-die mechanism, the warm request failed attribution admission, and the cold synchronized-copy share exceeded its frozen 20% screen. The result is bounded to one V340L, one small model that fits a single die, and one frozen placement; it is not a verdict on dual-die Vulkan execution in general.

- **Issue #280 candidate-B-only physical result observation:** [`STOP`](https://github.com/Zutfen-LLC/inferswarm/issues/280#issuecomment-6073758406).
- **Maintainer acceptance:** pending maintainer acceptance.
- **Recorded execution authorization:** blocked — Issue #280 has no unspent physical authorization; Issue #281 lacks a separately approved plan and physical execution authority, and Issue #279 remains planning-only. The single-use candidate-B-only authorization (https://github.com/Zutfen-LLC/inferswarm/issues/280#issuecomment-6073673930) was consumed by exactly one launch and two requests and is spent; the earlier 2-launch/4-request authorization (comment 6060425902) and the eight-launch/sixteen-request campaign authority were spent before it. Living status is informational and grants no further execution authority: an observed result, a merge, or green CI never authorizes a rerun, retry, relaunch, R1 repeat, or successor, each of which requires a new explicit maintainer decision. [Authority](https://github.com/Zutfen-LLC/inferswarm/issues/280).

- Issue #280 candidate-B-only result (comment 6073758406) executed authorization 6073673930 on accepted main c2f0396cbff20ac0c5c7ddda3412ffad43a6db26 with exactly one launch and two requests, B-cold then B-warm, a 10.479 s physical phase, and no R1 repeat, retry, replacement, or extra request. B-cold established the same-request two-die mechanism on the frozen placement (blocks 0–18 on die A; blocks 19–35 plus the tied output role on die B): die A weights 877,856,768 B (45.63%), KV 79,691,776 B, 445 completed commands; die B weights 1,046,089,728 B (54.37%), KV 71,303,168 B, 393 completed commands; forty graphs admitted; logical boundaries of 573,440 B and two host-staging legs totaling 1,146,880 B, which are logical and staging bytes rather than measured PCIe wire traffic. B-warm failed attribution admission (timeline completion identity does not match recorded event/value) and is not an admissible hardware result. Both responses passed the deterministic task rubric. B-cold synchronized copy time was 23.05% of request wall against the frozen 20% screen. Terminal STOP: the mechanism is proven for the cold request only, warm attribution failed, and no successor work is authorized.
- Issue #280 remains open and no maintainer disposition of the candidate-B-only STOP is recorded, so acceptance is pending and nothing is inferred from the result, the merged PR #296 engineering, or green CI. The result is bounded: one V340L on inferswarm05, Qwen2.5-3B-Instruct-Q4_K_M (which fits a single die, so this is a mechanism result and not a capacity result), the pinned llama.cpp b29c606e28a01b1bc8c1351026a0fa6e616bf6c4 Vulkan build with the PR #286 successor overlay, and one frozen placement. Custody is append-only: candidate-B-only evidence is retained at controller /home/zutfen/is280b-6073673930-evidence/ and host inferswarm05:/home/hermes/is280b-6073673930/ (TERMINAL.json, MANIFEST.sha256) and is not imported into this repository; the earlier r3 evidence at /home/zutfen/is280r3-evidence/ and inferswarm05:~/is280r3-physical/ is unchanged.
- Issue #289 and the merged PR #290 launcher and PR #296 kernel-verified serving-process identity mode are CPU and loopback engineering, not physical evidence; PR #296 does not change the pinned llama.cpp executable. The accepted PR #286 successor source identity and the frozen model, prompts, observer, thresholds, and STOP limits are unchanged.
- Issue #281 (V340L, RX 5600 XT and healthy RX580 Vulkan pooling) is queued behind an accepted #280 result and an explicit CONTINUE decision; neither exists, because the latest #280 result is STOP with acceptance pending. #281 has no recorded plan, plan approval, budget, or execution authorization, its first deliverable would be a concise plan, and no hardware relocation or purchase is assumed. One V340L result cannot establish multi-card scaling or justify a purchase.
- Issue #188 is roadmap authority and not an execution ticket. Its priority order is: #280, then #281 when queued, then #279 (CUDA capacity/value proposal, open and planning only). Mixed NVIDIA/AMD work is deferred, #239/R8-J remains blocked with its frozen contract and sealed holdout unchanged, and #244 is closed not-planned. No CUDA implementation or physical work is assigned.
- Research direction, not an authorization: the open capability question is a model or workload that is demonstrably infeasible under a declared single-resource envelope and is correctly executable when additional heterogeneous resources are added. It is a separate claim from GPU-residency expansion, where the single-resource comparison can still complete, and from performance. Issues #279 and #281 are the existing gates where this question would be scoped; this status creates no new prerequisite issue, experiment, or authority.
- The separately accepted #264 bounded pilot remains limited to its path-transition scope: four fresh-process units observed SUBGROUP/subgroup/32x1x1 to LARGE/hybrid/128x1x1 at output.weight, with both arms screening-variable; numerical root cause and H2/H3/H5 theorem closure remain open. Acceptance authority: https://github.com/Zutfen-LLC/inferswarm/issues/264#issuecomment-5969219338.
- The #250 predecessor remains accepted as the ARM_A_STOPS_LADDER localized boundary only; observation https://github.com/Zutfen-LLC/inferswarm/pull/251#issuecomment-5904093750 and acceptance https://github.com/Zutfen-LLC/inferswarm/issues/250#issuecomment-5904094070 remain preserved. This was not established as root cause.
- Issue #264's sole live minimal experimental selector is subgroup32→large128 hybrid for the output.weight MMV q4_K*f32 route; dimensions/types and frozen comparator identity are scoped to that candidate only. The cooperative-matrix candidate is dead; do not revive it.
- Four fresh-process units at the frozen execution head observed the actual path transition at all 10 output events per unit. BASE and candidate both differ across their two full-row digests and are screening-variable; matching candidate response tokens do not establish numerical stability or causality.
- The bounded pilot stopped at two units per arm; no third units or retry. Controller preservation verified the accepted #262 150-file inventory unchanged and 69 new retained files byte-identical across remote and local roots. The pure report's preservation field remains external-pending by design.
- Issue #266 is COMPLETED (closed completed), and PR #256 is MERGED to main as 442e2a02ce89e7fb42bceff1f7a47c8789c17733 (https://github.com/Zutfen-LLC/inferswarm/pull/256); the aggregate #254/#258/#260/#262/#264 stack is historical R8-I3C authority, not a pending review frontier. The bounded #264 result is accepted, and PR #265 merged into the aggregate producer branch as b3b28825d860b01b40f7b5697d5a50266ecaeb39 after exact-head review and Final CPU Validation on 28120bb57bfa9b8997d3d616c24e59a70f96a9af (run 37122285620). Those historical receipts are not validation receipts for the current #255 head. A source/CI/subagent PASS or additive report head grants no new physical authority. No automerge, R8-J, dead-control, or broad-matrix work is authorized.
- The completed #258 prospective theorem (merged PR #259) keeps historical A3 terminal-capability separate from hypothesis coverage: closure remains impossible, required_arms is empty, and A5 remains observationally capable but nonterminal. #260/#262/#264 use distinct instrumented source identities; their path observations do not reopen historical theorem closure.
- Issue #241 remains accepted as R8I3_COMPARATOR_V2_BLOCKED; #244 and #239 remain blocked on their Vulkan/comparator path. Issue #255's accepted capability is limited to its bounded tested homogeneous NVIDIA/CUDA two-host MVP; it establishes no numerical equivalence, mixed-vendor readiness, production readiness, or new R8-J/Vulkan execution authority. The #255 observation asserts the MVP_DISTRIBUTED_INFERENCE_PASS terminal only within that accepted scope.
<!-- project-status:frontier:end -->

## Long-term objective

InferSwarm aims to account for, and plan across, resource classes such as:

- NVIDIA, AMD and Intel GPUs, and CPUs;
- GPU VRAM / HBM and system RAM, as separate memory domains;
- multiple GPUs with asymmetric local links;
- multiple machines connected over ordinary Ethernet;
- SSD and other storage as verified artifact backing and as sources or caches,
  never as GPU memory;
- future roles for NVMe, CXL or other memory and storage resources where
  evidence supports them;

as one logical planning domain, with decisions driven by model semantics,
measured capability, state requirements, workload demand, and operator policy
rather than assumed hardware symmetry. This lists what the fabric is intended to
handle, not what works today: see the
[evidence matrix](docs/capability-evidence-matrix.md). Not every resource takes
part in every plan.

## Design principles

These are a concise overview; the
[Fabric Doctrine](docs/architecture/fabric-doctrine.md) is normative.

1. **Heterogeneity is first-class.** Vendor, generation, memory size, compute
   speed, bus topology, and network speed may differ.
2. **Resources do not have permanent plan roles.** There is no canonical
   `primary`/`secondary` GPU or L0/L1/L2/L3 hierarchy. A GPU, CPU, RAM domain,
   or link participates according to the current plan.
3. **System RAM and CPU remain first-class.** They may provide residency,
   execution, staging, cache/replica value, or no active role depending on the
   plan; accelerators augment rather than deprecate them.
4. **State identity and physical copies are different things.** Logical state,
   materializations, backing, residency, staging, cache, replica, execution
   location, and mutable authority are distinct.
5. **Accelerator residency does not imply a host mirror.** Persistent host
   copies require an explicit purpose and accounting.
6. **Correctness and feasibility precede optimization.** Slow-but-viable is
   still viable unless an explicit operator service requirement says otherwise.
7. **Measure hardware; do not stereotype it.** Context-valid measurements drive
   economics; unknown is uncertainty; correctness failures quarantine rather
   than merely reduce a performance score.
8. **Model semantics stay behind a Model Execution Strategy.** Strategies
   define legal opaque state/execution units and boundaries; the generic
   planner chooses among them without needing concepts such as `expert`, Qwen,
   CUDA Graph, or NVFP4.
9. **Granularity is measured and plan-relative.** High-frequency/dependency-
   sensitive communication should stay on the lowest-cost measured locality
   practical, but coarse boundaries have costs too. Intra-node and inter-node
   granularities may differ.
10. **Elasticity works both directions.** Better resources may be prepared and
    folded into active sessions at safe boundaries; resource loss should fall
    back to any correct feasible surviving plan—including slower GPUs or
    CPU/RAM—before declaring outage.
11. **InferSwarm can adapt to structural demand.** Model/profile/Swarm/session
    history may inform future placement without requiring prompt/response
    retention or assigning human meanings to model parts.
12. **Commodity networking matters.** Ordinary 1 Gigabit Ethernet remains the
    baseline network target. Faster networks are welcome optimizations, not a
    mandatory project dependency.
13. **Execution fabric and management plane are distinct.** The open-source
    fabric must remain fully usable without a paid control plane.
14. **Keep the host integration seam narrow.** FreeToken is the first proving
    vehicle, not the product boundary.

## Conceptual architecture

```text
Host inference engine
        |
        v
Model Execution Strategy
        |
        | legal opaque units / state / demand /
        | representations / correctness / economics
        v
Generic InferSwarm planner
        |
        | Swarm resource graph + evidence + policy
        v
Versioned Execution Plan / epoch
        |
        +-------------------+-------------------+
        |                   |                   |
   Compute Units       Memory Resources      Links/paths
   GPU/CPU/NPU/...     RAM/VRAM/HBM/...     local/network
```

The resource graph describes what InferSwarm **has**. The Execution Plan
describes what InferSwarm **intends to do with it**.

## Historical execution strategies

MoE expert execution remains the first strategy actually researched and is
preserved by ADR 0004.

ADR 0007 remains accepted as the first **network strategy/evidence direction**:
coarse contiguous model blocks over ordinary Ethernet. It is not a permanent
rule that inter-node execution must use contiguous blocks. The current doctrine
allows the Model Execution Strategy and planner to select another legal
intra/inter-node granularity when measurements justify it.

## Current implementation vehicles

<!-- project-status:runtime:start -->
The [FreeToken fork](https://github.com/Zutfen-LLC/FreeToken) is the initial runtime vehicle.
Its durable integration branch is `inferswarm-research` ([established by #59](https://github.com/Zutfen-LLC/inferswarm/issues/59)).
Upstream-tracking `main` and immutable evidence branches have separate roles.
Execution uses the exact producer named by the current gate authority,
never an unreviewed branch tip. FreeToken is not the permanent product boundary.
<!-- project-status:runtime:end -->

FreeToken is the original research and integration vehicle. Its N0 and R1-R5B
work, the external Coordinator and the dense Gemma chain executed on real
hardware, but through research-internal structures that the code itself labels
as not public planner, scheduling, strategy or wire APIs. See
[`docs/integrations/freetoken.md`](docs/integrations/freetoken.md).

InferSwarm now also contains one deliberately narrow in-repo **operator path**
(`inferswarm/operator/`):

```sh
python -m inferswarm.operator run --config examples/ordinary-two-host.json
```

One invocation performs one non-streaming generation for an operator-written,
fixed plan. It accepts exactly two participants (one local client and one remote
RPC participant), the `llama.cpp` strategy only, and one three-range layer
placement of the tested 48-layer model: layers 0-40 on the client CPU, 41-44 on
the client GPU, and 45-47 plus the output layer on the remote GPU, with MoE
experts on the client CPU. It verifies the runtime binaries, model members and
the remote's cache ranges before launching, starts the processes over SSH, and
cleans up only what it created. It is accepted for one tested topology (see the
table above) and is not a planner, not a general runtime, and not a path for
other models, vendors, participant counts or placements. Its public interfaces
are unfrozen.

## Repository layout

```text
.github/             issue templates, pull request template, CI
inferswarm/operator/ narrow fixed-topology operator path (python -m inferswarm.operator)
examples/            operator configuration example for that path
docs/                documentation map and reading rules
docs/adr/            architecture decision records
docs/architecture/   normative Fabric Doctrine and its supplements
docs/benchmarks/     benchmark methodology/results
docs/investigations/ research inputs and feasibility work
docs/implementation/ active/historical experiment plans and handoffs
docs/protocols/      semantic-boundary and transport design notes
docs/qualification/  heterogeneous correctness-qualification lane (v1-v5)
docs/integrations/   host-engine integration notes
scripts/             CPU-only, deterministic, fail-closed evidence tooling
tools/               measurement harnesses retained from accepted campaigns
tests/               tests that guard the retained evidence
ARCHITECTURE.md      derived architecture overview
BENCHMARKING.md      benchmark/evidence contract
ROADMAP.md           evidence-gated successor roadmap
```

[`docs/README.md`](docs/README.md) maps the whole documentation tree and states
the rules for reading retained evidence. [`scripts/README.md`](scripts/README.md)
and [`tests/README.md`](tests/README.md) cover the tooling and how to verify the
repository locally.

## License

Apache License 2.0. See [LICENSE](LICENSE). Contributions are accepted under the
same license; see [CONTRIBUTING.md](CONTRIBUTING.md).

