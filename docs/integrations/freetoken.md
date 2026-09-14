# FreeToken integration

How InferSwarm relates to the
[Zutfen-LLC/FreeToken](https://github.com/Zutfen-LLC/FreeToken) fork of
FlashML-org/FreeToken.

Decision context:

- [ADR 0002](../adr/0002-freetoken-as-initial-integration-runtime.md)
- [ADR 0008](../adr/0008-canonical-fabric-doctrine.md)
- [Fabric Doctrine](../architecture/fabric-doctrine.md)
- [ROADMAP](../../ROADMAP.md)

FreeToken remains the initial proving/runtime integration vehicle. It is not the
canonical home of InferSwarm architecture and is not assumed to be the permanent
exclusive host runtime.

## Who owns what

- **InferSwarm ADRs and the Fabric Doctrine are canonical** for architecture.
- **InferSwarm issues and `ROADMAP.md` are canonical** for experiment questions,
  gates, methodology, and acceptance criteria.
- **The FreeToken fork carries focused implementation experiments** needed to
  prove those hypotheses against a real inference runtime.
- **Accepted evidence remains identified by exact commits and context** even when
  the tested implementation is never merged directly into FreeToken `main`.

Typical flow:

```text
InferSwarm issue / frozen methodology
        |
        v
FreeToken evidence or integration branch
        |
        v
physical correctness / performance evidence
        |
        v
InferSwarm gate review
        |
        v
archive evidence + extract/integrate the proven seam
```

Do not duplicate the full InferSwarm roadmap into FreeToken issues.

## Doctrine-shaped, API-unfrozen

Current implementations must preserve the Fabric Doctrine without prematurely
publishing a generalized resource/planner/strategy API.

A Qwen/NVIDIA experiment may use temporary structures named for layers,
experts, CUDA, or FreeToken-specific runtime details inside the bounded
strategy/backend implementation. Those names must not leak into the generic
InferSwarm ontology merely because the first proving vehicle uses them.

The generic concepts remain Swarm, Coordinator, Node, Compute Unit, Memory
Resource, Link, Logical State Unit/Materialization, Model Execution Strategy,
planner evidence/policy, and versioned Execution Plans/epochs.

## Historical runtime lineage through R4

The corrected post-Wayfinder FreeToken research line established:

- R0 / #48 — `P48_ACCELERATOR_RESIDENCY_PASS`;
- R1 / #50 — `R1_FROZEN_PLAN_REALIZATION_PASS`;
- R2 / #51 — `R2_LOCAL_SPLIT_EXECUTION_PASS`;
- #53 — `HOST_STAGING_RECLAMATION_PASS`;
- R3 / #55 — `R3_MINIMUM_AUTOMATIC_PLANNING_PASS`;
- R4 / #57 — `R4_MULTI_NODE_BOUNDARY_PASS`.

Canonical R4 provenance is:

```text
accepted R3 base:
2ac72d547b2a24a3672d1b83268865db5490084d

accepted R4 physical producer:
e97f60b7b0120a72a7cf9926cf6a5c558782c9b2

accepted corrected R4 evidence:
d5735c6b5075e835e7e8118922c44a7b0cf7439b

preservation branch head:
b2d72a36e79624028e74a2e7256f03546d4b8b5b
```

The earlier R4 evidence head `9a26fd2` is retained only as invalidated history;
it is not canonical evidence.

R4 also established the context-specific disposition
`R4_1GBE_PRIMITIVE_CAPACITY_VIABLE`. The accepted clean-arm workload peaked at
about `2.947 Mb/s` A→B against the frozen `747.12 Mb/s` 80%-margin limit on the
measured ordinary-1-GbE path. This does not imply that every model boundary or
network topology is 1-GbE viable.

## Branch policy

### `main`

FreeToken `main` tracks upstream FreeToken as cleanly as practical. Experimental
InferSwarm research must not casually accumulate there.

### Evidence branches

An **evidence branch** preserves the exact implementation that produced a
measured result. Accepted evidence commits are immutable historical inputs.
They are not rebased merely to make GitHub history prettier or to keep pace with
upstream.

For an accepted evidence branch:

1. freeze exact implementation and evidence SHAs;
2. record them in the corresponding canonical InferSwarm issue/result;
3. preserve enough source/artifacts to reproduce or audit the result;
4. invalidate and regenerate evidence if a correctness-bearing producer changes;
5. never infer that an accepted POC is automatically production runtime code.

### Long-lived integration branch

An **integration branch** carries the coherent current downstream implementation
used for continuing InferSwarm work. It is a new implementation context, not a
retroactive replacement for historical evidence.

Issue #59 established the durable integration line while preserving the
accepted R4 lineage and deliberately integrating upstream changes. Accepted
R5A/R5B execution followed on that line. The historical PR #20 lineage was not
a reason to merge experimental code directly into upstream-tracking `main`.

<!-- project-status:runtime:start -->
The [FreeToken fork](https://github.com/Zutfen-LLC/FreeToken) is the initial runtime vehicle.
Its durable integration branch is `inferswarm-research` ([established by #59](https://github.com/Zutfen-LLC/inferswarm/issues/59)).
Upstream-tracking `main` and immutable evidence branches have separate roles.
Execution uses the exact producer named by the current gate authority,
never an unreviewed branch tip. FreeToken is not the permanent product boundary.
<!-- project-status:runtime:end -->

## Current implementation direction

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

The [project capability summary](../../README.md#what-the-research-has-established)
distinguishes accepted physical serving/recovery and qualification from CPU
artifact-distribution proofs awaiting physical integration.

## Evidence branch versus integration branch versus `main`

Use these terms distinctly:

- **evidence branch** — immutable implementation/evidence lineage for a frozen
  measured result;
- **integration branch** — current coherent downstream InferSwarm implementation
  expected to receive continuing development;
- **upstream-tracking `main`** — stays close to FreeToken upstream.

A proven mechanism may be adapted/extracted from an evidence branch into the
integration branch after review. That is a deliberate integration step, not an
automatic consequence of a positive benchmark.

## Extraction boundary

The desired end state remains a narrow host-engine seam. Once multiple real
experiments establish stable resource/planner/strategy/runtime boundaries,
reusable InferSwarm components should move behind that seam rather than forcing
a permanently deep FreeToken fork.

Continuing integration must keep temporary model and backend details behind
research/strategy seams. The historical R6 attempt failed; the accepted
qualification and current successor integration preserve that result while
testing the later design. Public strategy/planner APIs remain unfrozen.

Upstream FreeToken and FlashML are not involved in InferSwarm; nothing here
implies their endorsement.

