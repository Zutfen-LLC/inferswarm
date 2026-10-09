# CI impact planning

How InferSwarm CI decides which checks run for a change (Issue #148).
The canonical selection authority is repository-owned:
[`scripts/plan_ci.py`](../scripts/plan_ci.py) plus its generated registry
[`scripts/ci_groups.json`](../scripts/ci_groups.json). This document
explains the model; it does not duplicate the registry — the planner
output is always the source of truth.

## Model

```text
PR            -> plan_ci.py --mode pr  -> repo-integrity (always-on)
                                            + selected impact groups
                                        -> CI Gate
main / manual -> plan_ci.py --mode full -> every group -> CI Gate
unknown / shared / authority change -> planner fails closed to full regression
```

No third-party action decides which correctness suites run. The planner
is deterministic (same changed-path set produces a byte-identical plan),
pure standard library, and unit-tested in
[`tests/test_plan_ci.py`](../tests/test_plan_ci.py).

## Asking the planner locally

What CI groups would a change select:

```bash
python3 scripts/plan_ci.py --mode pr -- path/to/file another/path
# or from a diff:
git diff --name-only origin/main...HEAD | python3 scripts/plan_ci.py --mode pr
```

Output is `ci-plan/1` JSON: `mode`, `groups`, `full_regression`,
`reason` (one line per selection or fail-closed escalation).

How to run one group: the group's exact unittest command is visible in
[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) (one job per
group, same name; the R8-I group runs as numbered shard jobs, see
[Sharded groups](#sharded-groups-issue-287)), and the module list per group is in
[`scripts/ci_groups.json`](../scripts/ci_groups.json). Locally, after
bootstrapping the canonical CPU environment:

```bash
python3 scripts/bootstrap_test_env.py
.venv/bin/python -m unittest <modules-for-group> -v
```

How to run full regression locally (independent of impact selection):

```bash
.venv/bin/python scripts/run_full_cpu_suite.py
.venv/bin/python scripts/run_full_cpu_suite.py --jobs 1
.venv/bin/python scripts/run_full_cpu_suite.py --list --json
```

The runner discovers the raw serial population, uses bounded isolated worker
processes, and fails closed unless the worker-executed identity set exactly
matches that discovery. Use raw `unittest discover -s tests -p 'test_*.py'`
for direct single-process debugging or the final serial equivalence check.

How to force full CI in GitHub Actions: use `workflow_dispatch` on the
CI workflow (full regression is the default), or push to `main` — every
push to `main` runs the complete CPU regression contract regardless of
the changed paths.

## Hosted Final CPU Validation (Issue #226)

Ordinary PR CI above stays impact-selected and never runs the full
suite on a PR push. The canonical full CPU suite runs HOSTED exactly
once, explicitly, on the maintainer-reviewed PR head:
[`final-cpu-validation.yml`](../.github/workflows/final-cpu-validation.yml)
(`workflow_dispatch` with the required 40-hex `expected_sha`; the
dispatch ref is transport only). It executes the canonical
`scripts/run_full_cpu_suite.py --json` plus the finalizer/status checks
on that exact SHA and retains a structured exact-head receipt. Campaign
handoff requires the ordinary `CI Gate` AND the `Final CPU Validation
Gate` on the same exact head; see
[campaign gate ordering](campaign-gate-ordering.md). A duplicate dispatch for a
head that already has a verified successful hosted execution does not re-run
the suite: it records `verified_prior_execution` against the independently
verified source receipt, and any doubt runs the full suite (Issue #291).

## Groups

Registered group ids live in `scripts/ci_groups.json` (`groups` key);
each group records the current invariant it protects (`invariant`,
from `GROUP_INVARIANTS` in the planner). `repo-integrity` is
always-on: the canonical CPU environment bootstrap/doctor, YAML
syntax, generated project status, deterministic finalization
`--check`, evidence manifest lifecycle, frozen Phase-0 workload
integrity, the planner self-check, the test-retention audit and
retired-lineage integrity check, Markdown links, repository hygiene,
and project naming. All other groups are impact-selected families
(e.g. `issue-117-133`, `r8i-qwen-qualification`) mapped from owned
paths by the registry's `path_rules`.

Groups follow current dependency and authority boundaries, not issue
chronology. Issue #246 split the former `vulkan-v0-b` catch-all
(46 modules spanning V0, V1, V2, R8, and #35) by dependency boundary
and then retired every historical-only suite:

- `r8i-qwen-qualification` — the current R8-I authority (#237, #244).
  Current R8/Qwen work (for example Issue #241) registers its modules
  here;
- `r8-qwen-lineage` — R8-A (the living frontier reference) and the
  R8-B evidence that R8-I consumes;
- the V0-B, V0-C/V1/V2-A, #35, and R8-D replay suites are deleted;
  their accepted evidence is protected by the always-on retired-lineage
  integrity check.

There is no historical group: a registered group holds only current
contracts, current regressions, or current evidence integrity.

A script change selects every group whose test modules import it,
directly or transitively (`tests/test_plan_ci.py`,
`TestImportClosureFanout`, enforces this). Evidence that a retained
test reads fans out to that test's group.

## Sharded groups (Issue #287)

A registered group is a *selection and ownership* unit; a workflow job is a
*scheduling* unit. They are one-to-one except where measured wall time says a
group must be spread across runners. `r8i-qwen-qualification` is the one such
group: it stays **one** registered group (one registry entry, one retention
audit group, one impact-selection target) and the workflow executes it as
numbered shard jobs `r8i-qwen-qualification-s1` … `-s5`.

What this keeps, by construction:

- **Selection.** Every shard carries the same `if:` expression, so any change
  that selects `r8i-qwen-qualification` (R8-I source, tests, evidence, a
  transitive import) selects *all* shards, and full regression on
  `main`/manual/authority escalation runs them all. A shard is never
  selected on its own.
- **The CI Gate.** The gate maps each group to *all* of its executing jobs.
  A selected group passes only if every shard succeeded. A shard that
  failed, was cancelled, was skipped, or reported no result fails the gate;
  so does a missing or malformed result for any job, selected or not. Each
  shard job also carries a `timeout-minutes` bound so a hung worker fails
  instead of holding the gate open.
- **Isolation.** Shards are separate runners with their own checkout and
  canonical environment; there is no shared mutable state, no in-job
  parallelism, and no retry.
- **Identity.** Every registered module runs, and every unittest identity
  runs exactly once. Modules run whole in one shard, with one declared
  exception: `test_issue278_integration`, the single hosted bottleneck
  module (14 fully independent per-test-fixture tests, one test alone about
  two minutes), is split across two shards by explicit
  `tests.<module>.<Class>.<test>` selectors.

The partition is derived from measured per-test wall time on a hosted
`ubuntu-latest` runner (largest unit first into the least-loaded shard), not
from module counts. It is a scheduling choice, not a contract: re-balance by
moving a module between shard commands; nothing else changes.

Equality is proved on test *identities*, never on counts alone.
`scripts/ci_workflow_parity.py` expands each job's real `unittest` command
through the same loader the command uses and compares the multiset of IDs to
the loader-discovered population of the group's registered modules:

```bash
# deterministic identity accounting for this checkout (exit 1 on any drift)
python3 scripts/ci_workflow_parity.py --group r8i-qwen-qualification
# the same, for another checkout (for example the base of a CI change)
python3 scripts/ci_workflow_parity.py --root /path/to/checkout
```

`tests/test_plan_ci.py` (`TestIdentityAccounting`, `TestSelectorTokens`,
`TestShardedGroupWorkflow`) fails on an omitted module or test, a duplicated
module or test, an unregistered module, a selector that names no real test,
a module split without being declared, and a count-preserving swap. It also
executes the **real** gate script from `ci.yml` against synthetic job results
(`TestRealGateScript`) and evaluates every job's real `if:` against real
planner output (`TestJobSelectionEvaluation`).

When adding a module to the sharded group, register it as usual (below); the
identity check then fails with `identities discovered but not executed` until
the module is added to exactly one shard command in `ci.yml`. Add it to the
least-loaded shard. Do not add it to two shards. Splitting another module
across shards additionally requires listing it in `SPLIT_MODULES` in
`tests/test_plan_ci.py` with a measured justification.

## Test lifecycle (Issue #246)

> CI tests are retained because they protect current contracts,
> reachable regressions, or current evidence integrity. Historical
> issue provenance alone is not a retention criterion.

Git history is the archive. An accepted manifest, a producer-hash
ledger, a historical script, or an old issue that names a test path
never keeps that test alive.

Every canonical test module (`tests/test_*.py`) has a record in
[`docs/ci/test-retention-audit.json`](ci/test-retention-audit.json)
with exactly one category, a disposition, the current invariant it
protects, and its rationale. A discovered or CI-registered module must
be `CURRENT_CONTRACT`, `CURRENT_REGRESSION`, or `EVIDENCE_INTEGRITY`;
`HISTORICAL_ONLY` and `OBSOLETE` records exist only for removed units.
Mixed modules add `overrides` at class or test-method granularity, and
a retained unit must itself be current.
[`scripts/check_ci_test_retention.py`](../scripts/check_ci_test_retention.py)
runs in `repo-integrity` and fails when:

- a discovered module has no record (a new module must declare its
  owner and current invariant);
- a discovered or registered module is `HISTORICAL_ONLY` or `OBSOLETE`;
- a retained module's audit group differs from its planner group;
- an accepted `MANIFEST.sha256` lists a retained test file, or a script
  imports or names a test module, and the record omits it
  (`pinned_by_evidence`, `referenced_by_scripts`);
- a removed module is still discovered or registered, is not
  `HISTORICAL_ONLY`/`OBSOLETE`, names nothing that protects its
  evidence, or its accepted rows are not exactly tombstoned;
- any script imports a removed test module, or a current (unpinned)
  script names one.

### Retired test rows

An accepted manifest that names a deleted test file keeps its bytes.
[`docs/ci/retired-test-rows.json`](ci/retired-test-rows.json) records
one exact tombstone per retired row, binding:

- the accepted manifest path and the SHA-256 of its accepted bytes;
- the retired target path and the SHA-256 the manifest stores for it;
- the retirement reason and the Issue #246 authority.

Row verification — the evidence-manifest lifecycle test, the
retired-lineage integrity check, and the finalizer's closed-bundle
stage — passes a missing target only when one tombstone matches all
four identities. A changed manifest, a changed stored digest, a
missing, duplicate, or conflicting tombstone, a wildcard or prefix
target, and a tombstone for a target that still exists all fail, and
every unrelated missing row still fails.

### Retiring or replacing tests when an implementation is superseded

1. Classify the module (or its classes/tests) against current
   reachability: which current source path can make it fail, and which
   current invariant that failure represents. Completion of the issue
   alone is not evidence of obsolescence.
2. If a still-current guard (for example a holdout, custody, or
   predictive-contamination rule) lives inside a historical suite,
   extract only that minimal guard into a `CURRENT_CONTRACT` module of
   the active authority, then retire the rest. Do not invent a current
   invariant to keep historical code.
3. If a current script imports or hashes the test module, move the
   authority it consumes into a non-test module or data artifact. If
   the script is itself historical, retire it too (pin it as a frozen
   producer when accepted evidence names it, otherwise delete it).
4. Protect the evidence it guarded with an integrity
   replacement instead of reducer replay: add an
   `integrity_replacements` entry naming the evidence bundles (root plus
   accepted row files such as `MANIFEST.sha256` or a `json-map`
   producer-hash ledger; `pin_uncovered` pins bundle files the accepted
   rows do not cover, and `excluded_subtrees` leaves nested bundles to
   their own authority) and the retired producers, then pin them with
   `python3 scripts/check_ci_test_retention.py --write-pins`. The pin
   file ([`docs/ci/retired-lineage-pins.sha256`](ci/retired-lineage-pins.sha256))
   pins the manifests themselves, so evidence cannot be rewritten
   together with its manifest. Pinned retired producers are frozen:
   editing one, even cosmetically, fails `repo-integrity` until a
   maintainer-authorized re-pin.
5. Tombstone every accepted row that names the deleted test file in
   `docs/ci/retired-test-rows.json`.
6. Delete the module and any test-only helpers, unregister them from
   the planner and workflow, map the retired paths to `repo-integrity`
   (plus any retained consumer group), and set the record's disposition
   to `integrity-replacement` or `delete`.

Do not keep a permanent historical-tests bucket, and do not add
machinery only to preserve old test code. Changing the audit, the pin
file, the retired-row tombstones, or the checker fails the planner
closed to full regression.

## Fail-closed surfaces

The planner escalates to full regression when:

- a changed path is unclassified (unknown new file, unregistered
  `scripts/` or `tests/` path, shared test infrastructure);
- an unmapped **non-prose** `docs/**` file changes (generated evidence,
  retained data, manifests, schemas, producer files, `.json`/`.jsonl`/
  `.sha256`/...): only ordinary Markdown prose may classify as
  repo-integrity-only; evidence-bearing documentation without an
  explicit registry rule fails closed;
- `.github/workflows/**` changes;
- the planner itself, its registry, or its tests change;
- the canonical dependency authority changes (`requirements-test.txt`,
  `scripts/bootstrap_test_env.py`, `scripts/check_test_env.py`);
- repository authority surfaces change (finalizer, status syncer,
  evidence manifest tooling and their docs, `docs/project-status.json`,
  the Issue #246 retention audit, retired-lineage pins, retired-test-row
  tombstones, and their checker);
- the changed-path input is malformed (duplicates, whitespace,
  absolute paths, `..` traversal, **blank lines**) or empty.

When in doubt the plan widens; it never narrows silently.

Path rules use the repository's real retained trees. Each registered
family prefix must exist in the tracked tree, and shared evidence trees
fan out to the union of their mechanically demonstrated consumers
(e.g. `docs/qualification/gemma4-12b-it-v5/` selects both
`issue-109-110` and `issue-117-133`). `tests/test_plan_ci.py` enforces
this with a `git ls-files` census: every configured prefix must exist,
and every tracked non-Markdown docs file must be explicitly classified.

## CI Gate

Branch protection should require exactly the **CI Gate** check (job
`ci-gate` in `.github/workflows/ci.yml`). It runs `if: always()` and
fails closed unless the planner job succeeded with a well-formed plan,
`repo-integrity` succeeded, and every job of every selected group succeeded
(cancelled or never-run selected jobs are failures, as is any job that
reports no result or a result outside `success`/`failure`/`cancelled`/
`skipped`; legitimately unselected groups are skipped by design). A sharded
group is selected as a unit and passes only if all of its shards passed.

## Adding a group or test module

Register it: add the test modules to `GROUP_TEST_MODULES`, a new group's
current invariant to `GROUP_INVARIANTS`, and the owned paths to
`PATH_GROUPS` in `scripts/plan_ci.py`, run
`python3 scripts/plan_ci.py --emit-registry`, add a matching job to the
workflow, and add the module's record to
`docs/ci/test-retention-audit.json`. `tests/test_plan_ci.py` fails if
any `tests/test_*.py` module is not owned by exactly one registered
group, and `scripts/check_ci_test_retention.py` fails if it has no
retention record, so an unregistered or unowned suite cannot slip
through silently. For a sharded group, also place the module in exactly one
shard command (see [Sharded groups](#sharded-groups-issue-287)).

## Adding an evidence-bearing docs subtree

A new `docs/**` subtree holding generated/retained evidence (anything
that is not ordinary Markdown prose) must be registered in
`PATH_GROUPS` mapped to the groups whose tests actually consume it, or
— if it is deliberately repo-integrity-only — added to the documented
allowlist in `tests/test_plan_ci.py`
(`TestRepositoryTreeCoverage.test_unmapped_evidence_census_fail_closed`)
with the reason. The census test fails otherwise, so an unclassified
evidence subtree cannot fall through to the prose rule. Bundle roots
declared in a retention-audit integrity replacement may classify as
`repo-integrity` only, because the always-on retired-lineage check
verifies them.

## Workflow wiring contract

Each impact job's `if:` selects on real plan-job outputs only:
`needs.plan.outputs.full_regression == 'true' || contains(fromJSON(needs.plan.outputs.groups), '<group-id>')`.
The `plan` job exposes exactly `mode`, `full_regression`, and `groups`;
there is no duplicated per-group flag surface. `tests/test_plan_ci.py`
(`TestWorkflowContract`) parses `.github/workflows/ci.yml` itself and
fails if any job references a plan output that does not exist, if a
registered group has no selectable job, or if workflow group ids drift
from the registry. A sharded group's jobs are named `<group>-s<K>`, share
one selection expression, and report under the bare group id.
