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
- `.github/workflows/**` changes;
- the planner itself, its registry, or its tests change;
- the canonical dependency authority changes (`requirements-test.txt`,
  `scripts/bootstrap_test_env.py`, `scripts/check_test_env.py`);
- repository authority surfaces change (finalizer, status syncer,
  evidence manifest tooling and their docs, `docs/project-status.json`);
- the changed-path input is malformed (duplicates, whitespace,
  absolute paths, `..` traversal) or empty.

When in doubt the plan widens; it never narrows silently.

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
