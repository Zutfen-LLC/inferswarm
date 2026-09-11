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

- **Arm C — ordinary external-Coordinator serving (methodology/evidence-blocked) observation:** [`ISSUE117_ARM_C_EVIDENCE_BLOCKER`](https://github.com/Zutfen-LLC/inferswarm/pull/128).
- **Maintainer acceptance:** [accepted](https://github.com/Zutfen-LLC/inferswarm/commit/718efbf5770b31c6e44eb3a8c4d0b81fd1dc9c22).
- **Recorded execution authorization:** blocked — Issue #133 — physical Arm-C retry campaign TERMINAL observed: ISSUE117_ARM_C_ORDINARY_SERVING_FAIL (attempt armc-retry-physical-1, campaign armc-retry-afcdc4428f95d50c, execution freeze 88389598ac485f82aa3ec00caadcebcb3cafb56cf967751262e8ab5bc9bf9a1c; 18/24 exact equality, six regime-4 committed-token divergences re-observed on freshly executed arms with mechanically derived first-divergence positions (c109-04-01-026:4, c109-04-02-047:0, c109-04-03-040:2, c109-04-04-024:3, c109-04-05-043:0, c109-04-06-074:0) and complete pre-divergence invocation-equivalence proof; the four regime-4 HTTP-content discrepancies are retained as non-prefix-stable incremental decoding, byte-reproducible from the frozen coordinator; all Coordinator-zero, fencing, participant data-path, and deployment-identity invariants mechanically derived under the review-5172615768 fail-closed correction /2); maintainer review required — Arm D blocked by terminal FAIL. [Authority](https://github.com/Zutfen-LLC/inferswarm/issues/133).

- The accepted Arm-C historical result remains ISSUE117_ARM_C_EVIDENCE_BLOCKER (PR #128, merge 718efbf5770b31c6e44eb3a8c4d0b81fd1dc9c22); the retry is a fresh campaign that does not erase, reinterpret, or continue it.
- Physical retry is authorized only for the fresh campaign bound by Issue #133's authority record (new campaign_id, physical_authorization_id, lineage root), reviewed and committed to accepted history before the first correctness-bearing physical attempt; the authority document must satisfy the schema/loader frozen by Issue #129.
- The corrected comparator contract is mandatory: per committed position the direct arm replays prompt+committed ids with the frozen controller session allocation, calls the runtime with max_new_tokens=2, commits step zero, discards the speculative second token; single-shot max_new_tokens=8 is forbidden.
- Frozen identities: producer 924cd22ea081f6d4ed471016faf01d427fc5b0d2, checkpoint 5a84cb313260ac447237b890387116dfa8682e49a6b44bc585ae8353abbff18d, qualification subject sha256:c6b9fe721103fb041be3a5b980e73ee148f2304c8572bc50e971f7f1d7994ffd, candidate dense.6171f32b4413, geometry 01/gpu-0 [0,16) 01/gpu-1 [16,32) 03/gpu-0 [32,48), execution-plan digest sha256:8646e00ce53e3aac4c163ca35231fa82471815386d71266a0d0962eea565bdad, participant identity sha256:ee845188d3328bdec29bf4b09d71f7ccda0701ff5758cb1d8a70460a40fecfb1.
- The 24 c109-* cases with fixture digest sha256:180185cd5c6a5dcd77b2c65979bd2c9aef4d1c7ea9fb4850a64f4508b2ba36f2 are used exactly as accepted; the six historical regime-4 divergences remain diagnostic only and must not be inspected or tuned against before the terminal comparison is derived.
- The retry starts from the accepted Arm-B participant materialization/cache state; it may not be cleaned, reset, reacquired, rematerialized, or repaired to make the retry pass; material drift is a pre-execution STOP for maintainer review.
- Coordinator on inferswarm00 stays CPU-only (zero CUDA init, zero weight bytes received/materialized, zero bulk artifact bytes; frozen tokenizer/config assets at a non-Source path are the only exception and are accounted separately).
- Any correctness-bearing result emitted or committed without verified frozen deployment identity (pre-launch AND post-run byte verification) fires the campaign's permanent mandatory STOP; a blocked campaign can never produce PASS/FAIL authority and a retry needs a new maintainer authorization.
- No h109-* holdout material may be used or created; Arm D and Arm E are not authorized by this issue.
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
