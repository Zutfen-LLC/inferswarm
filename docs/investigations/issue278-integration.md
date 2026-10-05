# Issue #278 — integrated exact-head tooling validation (R8-I6A)

Parent: #273. Dependencies: accepted #275 collector
(`scripts/issue275_collector.py`), reviewed #276 retained-byte admission
(`scripts/issue276_reader.py`, round 3 custody binding), reviewed #277
reference-first orchestration (`scripts/issue277_orchestrator.py`), all on
PR #274.

## What was built

`scripts/issue278_integration.py` (additive; no protected module touched) —
one production entry point that composes the three child capabilities into a
single CPU-fixture chain and records every stage:

- `run_integration_278(source_root, staged_root, producer, executor,
  pair_comparison)` — the integrated chain. Six recorded stages:
  **capture** (the injected producer drives the REAL `capture_execution_273`;
  each capture is cross-checked against the collector-custody layout
  `source/<case>/<tag>/` and censused with a per-unit canonical inventory
  digest), **originals** (a no-follow retained-originals census with a
  population digest; every unit must match its capture-time census —
  custody drift between capture and staging fails closed here),
  **staging** (the #276 production stager, verbatim append-only copies),
  **admission** (the #276 production reader with mandatory
  `custody_root` byte binding; identity re-derived from bytes),
  **determinism** (the #277 production orchestrator: all references admitted
  and deterministic before any candidate launch), and **reduction** (the
  #273 public `derive_terminal_273` applied to the in-memory fixture record —
  it must fail closed, proving the integrated chain cannot mint physical
  terminal authority).
- `evaluate_278(staged_root, custody_root, executor, pair_comparison)` —
  re-runs admission → determinism → reduction over an already-staged
  population; used by the post-run tamper regressions.
- The producer/executor/comparison callbacks carry no authority: producer
  results are cross-checked against the custody layout, executor returns are
  discarded by the orchestrator, and comparison callbacks receive copies.
  No caller boolean or verdict parameter exists in either signature.

## Evidence

`tests/test_issue278_integration.py` — 9 CPU-fixture tests (RED-first,
committed failing before the implementation): the matching fixture completes
all six stages with every unit admitted (`backend=vulkan`, derived
`used_bdf`, complete row digests), 3 candidate launches and 3 comparisons,
and a fail-closed reduction; stage linkage binds retained bytes (per-unit
inventory digests match between capture and originals stages); a capture
landing outside collector custody fails closed BEFORE any staging write;
custody tamper between capture and staging fails closed at the originals
cross-check; a collector-custody reference row drift (authored before
staging, so it is a validly-admitted mismatch) blocks reference-first with
zero candidate launches; post-run staged-side AND custody-side tamper both
fail closed at reevaluation; forged admissions/determinism dictionaries
cannot mint a terminal through the public reducer; and the entry-point
signature admits no authored verdict parameters. The first demonstration
(registered test) prints the compact per-stage linkage for a matching
fixture and a fail-closed fixture.

All of it is labeled `evidence_class: tooling/fixture validation` — no
fresh physical authority, no #270 historical edits, no holdout access.

## Observed boundary

- The chain proves composition and fail-closed behavior of the reviewed
  tooling at this exact head. It does not (and cannot, on CPU fixtures)
  prove physical origin, physical determinism, or any #273 phase-3+
  qualification. That authority remains exclusively behind the merged-head
  `R8I6A CORRECTIVE PHYSICAL DISPATCH` gate in #273.
- The trust boundary is unchanged from #276: reviewed collector code plus
  contemporaneous OS/runtime observations. The integration layer adds
  custody-layout and census cross-checks but confers no new origin
  authority.

## Registration

CI surfaces (workflow unittest line, `plan_ci.py` group list + file map,
`ci_groups.json` via `--emit-registry`, retention audit record): self-check
OK; retention audit OK (`tests.test_ci_test_retention` 67/67); workflow
parity OK.
