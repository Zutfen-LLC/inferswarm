# Issue #277 — reference-first execution and byte-derived determinism (R8-I6A)

Parent: #273. Dependency: #276 admitted-row interface (`scripts/issue276_reader.py`,
`admit_staged_276` / `admit_pair_276`), accepted through round 3 at PR #274.

## What was built

`scripts/issue277_orchestrator.py` (additive; no protected module touched):

- `orchestrate_277(staged_root, custody_root, executor, pair_comparison=None)` —
  the production entry point. Determinism is derived only from #276-admitted
  row bytes: every unit (arm × repeat × case) is independently admitted through
  the real reader with `custody_root` byte binding, and per-arm determinism is
  recomputed as primary-vs-repeat `row_sha256` map equality. No caller boolean
  or verdict dictionary exists anywhere in the API.
- Reference-first ordering is structural: the executor call site sits after the
  complete reference-admission loop and both blocked returns. All three frozen
  required cases (case-256, case-1024, case-3072 — pinned in the module, with a
  fail-closed check that live `C.FIXTURE_CASES` covers exactly that set) must
  admit and be deterministic before any candidate launch.
- Blocked outcomes stay in the #273 vocabulary: `TERMINAL_REFERENCE_NONDETERMINISTIC_273`
  is reserved for two validly admitted reference captures whose rows differ;
  missing/invalid evidence and candidate-side failures block with
  `TERMINAL_RUNTIME_BLOCKED_273` and distinct problem text. Candidate
  nondeterminism blocks before pair comparison. Success is marked
  `"candidate gate reached"` — a fixture gate, never a #273 physical PASS; the
  public `derive_terminal_273` still fails closed on any in-memory record.
- Executor and pair-comparison callbacks receive no authority: executor return
  values are discarded; comparison callbacks get copy dicts, never live record
  maps.

## Evidence

`tests/test_issue277_reference_first.py` — 13 CPU-fixture tests driving the
production entry point with the #276 bundle machinery and a recording executor:
matching fixture reaches the candidate gate (3 launches, 3 comparisons);
case-3072 reference mismatch → zero launches, REFERENCE_NONDETERMINISTIC;
missing evidence, missing rows, repeat substitution, candidate drift, forged
pair verdicts, mutated/shortened/empty case lists, raising callbacks, and
comparison-callback mutation all fail closed. The first demonstration
(matching + mismatch fixtures) is a registered CI test.

RED-first: `12974d3` (import-level RED), `4820f7b` (behavioral RED for the
spec-gap regressions; the reducer entry-point coverage test was green at
parent because `derive_terminal_273` already fails closed — coverage addition,
not a regression).

## Reviews

- SPEC review round 1 at `369a429`: FAIL — 3 gaps (mutable `C.FIXTURE_CASES`
  bypass, no reducer entry-point attack, live record maps aliased into
  comparison callbacks). All closed in `6f965d9`/`266b6cb` (RED→GREEN).
- SPEC re-review at `f0bc10c`: PASS. Residual: patching both
  `C.FIXTURE_CASES` and the orchestrator's own frozen tuple in-process admits
  a one-case fixture gate — same trust level as replacing the admission
  function itself (trusted module code), documented here as the observed
  boundary.
- EVIDENCE-QUALITY review at `f0bc10c`: behavioral claims, digests, and diff
  containment verified empirically; one honesty finding (RED commit message
  overclaim) fixed by rewording to `4820f7b` before push. Both RED commits
  verified to fail at their parents.

## Observed boundary (fixture level)

Same class as #276: an in-process attacker who can replace trusted module code
(reader, orchestrator constants) can forge anything — fixture-level tests
cannot defend against edits to the trusted computing base itself. Physical
origin and determinism remain properties of the future physical campaign's
capture window; this issue claims no physical result.

Registration: all four CI surfaces (workflow unittest line, `plan_ci.py`
mapping + group list, `ci_groups.json` via `--emit-registry`, retention audit
record). Self-check OK, retention audit OK, `tests.test_ci_test_retention` 67/67.

Exclusions honored: no hardware/model execution, holdout access,
numerical-agreement evidence selection, historical-evidence edits, merge, or
physical dispatch authority changes.
