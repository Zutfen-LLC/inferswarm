# FreeToken integration

How InferSwarm relates to the
[Zutfen-LLC/FreeToken](https://github.com/Zutfen-LLC/FreeToken) fork of
FlashML-org/FreeToken.

Decision context: [ADR 0002](../adr/0002-freetoken-as-initial-integration-runtime.md).

## Who owns what

- **InferSwarm issues are canonical** for architecture, roadmap, and acceptance
  criteria.
- **The FreeToken fork carries focused implementation experiments** needed to
  prove those hypotheses against a real inference runtime.
- **InferSwarm records accepted evidence/provenance** even when the
  implementation remains experimental and is not merged into a long-lived
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
InferSwarm handoff / artifact / ADR
        |
        v
archive, extract, iterate, or discard experiment
```

Do not duplicate the full InferSwarm roadmap into FreeToken issues.

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
2. record the SHA and result in the canonical InferSwarm handoff/issue;
3. preserve any committed derivation/artifact required for reproducibility in
   InferSwarm;
4. optionally create a tag/archive ref when long-term exact source access is
   important;
5. only then delete/retire a branch if doing so improves repository hygiene.

A research branch being preserved does **not** mean it is approved production
runtime code.

The current Phase1R D2-D7 branches are evidence-bearing research history. They
should not be merged wholesale into FreeToken `main` or a permanent integration
branch merely because they produced useful results.

## Current development direction

The next primary workstream is coarse distributed model-block execution, tracked
by InferSwarm issues #31-#34 and
[`docs/implementation/distributed-node-poc.md`](../implementation/distributed-node-poc.md).

Initial implementation may again live in focused FreeToken `poc/*` branches:

- selective model-block loading;
- explicit block execution boundaries;
- persistent local/remote block execution;
- end-to-end two-node measurement.

The public/stable InferSwarm abstraction remains deferred until those
experiments establish the seam.

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

## End state

The desired ending is still a narrow host-engine seam. Once experiments prove
stable boundaries, reusable InferSwarm runtime components should move behind
that seam rather than forcing a permanently deep FreeToken fork.

Upstream FreeToken and FlashML are not involved in InferSwarm; nothing here
implies their endorsement.
