# FreeToken integration

How InferSwarm relates to the
[Zutfen-LLC/FreeToken](https://github.com/Zutfen-LLC/FreeToken) fork of
FlashML-org/FreeToken.

Decision context:

- [ADR 0002](../adr/0002-freetoken-as-initial-integration-runtime.md)
- [ADR 0008](../adr/0008-canonical-fabric-doctrine.md)
- [Fabric Doctrine](../architecture/fabric-doctrine.md)

FreeToken remains the initial proving/runtime integration vehicle. It is not the
canonical home of InferSwarm architecture and is not assumed to be the permanent
exclusive host runtime.

## Who owns what

- **InferSwarm ADRs and the Fabric Doctrine are canonical** for architecture.
- **InferSwarm issues and `ROADMAP.md` are canonical** for current experiment
  questions, gates, and acceptance criteria.
- **The FreeToken fork carries focused implementation experiments** needed to
  prove those hypotheses against a real inference runtime.
- **InferSwarm records accepted evidence/provenance** even when the tested
  implementation remains experimental and is never merged into a long-lived
  FreeToken integration branch.

Typical flow:

```text
InferSwarm issue / frozen methodology
        |
        v
FreeToken poc/* implementation
        |
        v
physical benchmark / correctness evidence
        |
        v
InferSwarm result / handoff / architecture decision
        |
        v
archive, extract, iterate, or discard experiment
```

Do not duplicate the full InferSwarm roadmap into FreeToken issues.

## Doctrine-shaped, API-unfrozen

Current POCs must preserve the semantics in the Fabric Doctrine without
prematurely publishing a generalized resource/planner/strategy API.

For example, a Qwen/NVIDIA experiment may use temporary structures that are
explicitly named for experts, CUDA, or the FreeToken loader. That is acceptable
inside the bounded strategy/backend experiment.

What is not acceptable is treating those names as generic InferSwarm ontology
merely because they exist in the POC. The generic concepts remain Nodes,
Compute Units, Memory Resources, Links, Logical State Units/Materializations,
Model Execution Strategy legality, and Execution Plans/epochs.

## Branch policy

### `main`

Tracks upstream FreeToken as cleanly as practical. Experimental InferSwarm work
must not casually accumulate here.

### Long-lived integration branch

A long-lived InferSwarm integration branch may exist when there is a coherent
set of proven changes worth carrying downstream. It should remain much thinner
than the collection of historical experiments.

Do **not** merge an experimental branch merely to make the branch list tidy.

### `poc/*`

Focused research branches answer one bounded question. Phase1R established that
some accepted experiments need to remain addressable after completion because
later evidence depends on exact implementation heads.

Therefore completed `poc/*` branches follow this lifecycle:

1. freeze the exact tested commit SHA;
2. record the SHA and result in the canonical InferSwarm issue/handoff;
3. preserve any committed derivation/artifact required for reproducibility in
   InferSwarm;
4. optionally create a tag/archive ref when long-term exact source access is
   important;
5. only then delete/retire a branch if doing so improves repository hygiene.

A research branch being preserved does **not** mean it is approved production
runtime code.

The Phase1R D2-D7 branches are evidence-bearing research history. They should
not be merged wholesale into FreeToken `main` or a permanent integration branch
merely because they produced useful results.

## Current implementation direction

The old N1-N3 coarse distributed-node sequence is retired as historical
scaffolding after N0 exposed the unresolved persistent host-shadow-copy
requirement and the resource/residency/planner Wayfinder re-derived the broader
architecture.

The first corrected post-Wayfinder runtime gate is:

> **[#48 — Prove accelerator residency without implicit persistent host
> mirrors](https://github.com/Zutfen-LLC/inferswarm/issues/48)**

The likely implementation vehicle remains a focused FreeToken `poc/*` branch.
The experiment starts from the valid N0 selective-loading substrate and must
prove that final accelerator-native residency can release equivalent host
materializations whose only purpose was staging/materialization, while
preserving correctness and exact component-level memory accounting.

The next local split/heterogeneous experiment is intentionally **not specified
until #48 passes**. Later experiments are derived from the current
[ROADMAP](../../ROADMAP.md), not by reopening N1-N3 verbatim.

## Relationship to N0

`N0_SELECTIVE_BLOCK_PASS` remains canonical for what it actually proved:

- selective checkpoint loading before materialization;
- block-only model/state ownership;
- bounded block-scoped loading/staging;
- exact isolated-block correctness.

It did **not** prove release of all persistent block-scoped CPU backing after
final accelerator residency. The retained `expert_bank_final_host_bytes`
exposed the successor requirement now tracked by #48.

The intentionally stopped N1 partial run is non-canonical evidence.

## Evidence branch versus product branch

Use these terms distinctly:

- **evidence branch** — preserves the exact implementation that produced a
  measured research result;
- **integration branch** — carries a coherent current downstream implementation
  expected to receive continuing development;
- **upstream-tracking main** — stays close to FreeToken upstream.

One commit may eventually graduate from an evidence branch into the integration
branch after review/refactoring. That is a deliberate extraction step, not an
automatic consequence of a positive benchmark.

## Extraction boundary

The desired end state remains a narrow host-engine seam. Once multiple real
experiments establish stable resource/planner/strategy/runtime boundaries,
reusable InferSwarm components should move behind that seam rather than forcing
a permanently deep FreeToken fork.

A material abstraction should not be extracted merely because one Qwen/NVIDIA
POC needs it. Before public APIs are considered stable, the roadmap includes a
materially different model-architecture validation intended to falsify/refine
the first-model seam.

Upstream FreeToken and FlashML are not involved in InferSwarm; nothing here
implies their endorsement.
