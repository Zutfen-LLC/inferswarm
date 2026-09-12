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
main / manual -> plan_ci.py --mode full -> every group (sharded) -> CI Gate
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
group, same name), and the module list per group is in
[`scripts/ci_groups.json`](../scripts/ci_groups.json). Locally, after
bootstrapping the canonical CPU environment:

```bash
python3 scripts/bootstrap_test_env.py
.venv/bin/python -m unittest <modules-for-group> -v
```

How to run full regression locally:

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

How to force full CI in GitHub Actions: use `workflow_dispatch` on the
CI workflow (full regression is the default), or push to `main` — every
push to `main` runs the complete CPU regression contract regardless of
the changed paths.

## Groups

Registered group ids live in `scripts/ci_groups.json` (`groups` key).
`repo-integrity` is always-on: the canonical CPU environment
bootstrap/doctor, YAML syntax, generated project status, deterministic
finalization `--check`, evidence manifest lifecycle, frozen Phase-0
workload integrity, the planner self-check, Markdown links, repository
hygiene, and project naming. All other groups are impact-selected
families (e.g. `issue-117-133`, `vulkan-v0-b`) mapped from owned paths
by the registry's `path_rules`.

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
  evidence manifest tooling and their docs, `docs/project-status.json`);
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
`repo-integrity` succeeded, and every selected group succeeded
(cancelled or never-run selected groups are failures; legitimately
unselected groups are skipped by design).

## Adding a group or test module

Register it: add the test modules to `GROUP_TEST_MODULES` and the owned
paths to `PATH_GROUPS` in `scripts/plan_ci.py`, run
`python3 scripts/plan_ci.py --emit-registry`, and add a matching job to
the workflow. `tests/test_plan_ci.py` fails if any `tests/test_*.py`
module is not owned by exactly one registered group, so an unregistered
suite cannot slip through silently.

## Adding an evidence-bearing docs subtree

A new `docs/**` subtree holding generated/retained evidence (anything
that is not ordinary Markdown prose) must be registered in
`PATH_GROUPS` mapped to the groups whose tests actually consume it, or
— if it is deliberately repo-integrity-only — added to the documented
allowlist in `tests/test_plan_ci.py`
(`TestRepositoryTreeCoverage.test_unmapped_evidence_census_fail_closed`)
with the reason. The census test fails otherwise, so an unclassified
evidence subtree cannot fall through to the prose rule.

## Workflow wiring contract

Each impact job's `if:` selects on real plan-job outputs only:
`needs.plan.outputs.full_regression == 'true' || contains(fromJSON(needs.plan.outputs.groups), '<group-id>')`.
The `plan` job exposes exactly `mode`, `full_regression`, and `groups`;
there is no duplicated per-group flag surface. `tests/test_plan_ci.py`
(`TestWorkflowContract`) parses `.github/workflows/ci.yml` itself and
fails if any job references a plan output that does not exist, if a
registered group has no selectable job, or if workflow group ids drift
from the registry.
