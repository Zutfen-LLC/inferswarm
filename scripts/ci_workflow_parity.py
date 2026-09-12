"""Workflow-vs-registry parity model for Issue #153 CI correction.

Derives the *executable* unittest module inventory from the REAL
``.github/workflows/ci.yml`` ``run:`` commands and compares it with the
canonical registry (``scripts/plan_ci.py`` ``GROUP_TEST_MODULES`` /
``scripts/ci_groups.json``). This is a mechanical derivation from the
workflow bytes — not a hand-maintained mirror table.

Shared by ``tests/test_plan_ci.py`` (parity guard + negative controls).
Pure stdlib plus PyYAML (part of the canonical #131 test environment).
"""

from __future__ import annotations

import re

try:
    import yaml
except ImportError as exc:  # pragma: no cover - #131 env provides yaml
    raise ImportError(
        "pyyaml is required by the CI parity guard "
        "(canonical #131 test environment)") from exc

# A unittest invocation line inside a workflow `run:` command. Only
# plain `-m unittest tests.module [...]` forms count as execution;
# discovery and pytest invocations are deliberately NOT execution of a
# named registry module.
_UNITTEST_RE = re.compile(
    r"(?:^|\n)\s*(?:python3?|\.venv/bin/python)\s+"
    r"-m\s+unittest((?:\s+tests\.[A-Za-z0-9_]+)+)",
)

# Shard jobs of a sharded group all report under the bare group id.
SHARD_JOB_RE = re.compile(r"^(?P<group>[a-z0-9-]+)-s(?P<shard>\d+)$")


def parse_workflow(doc):
    """Return {job_id: set(test_module)} for every unittest-executing step."""
    jobs = {}
    for job_id, job in doc.get("jobs", {}).items():
        modules = set()
        for step in job.get("steps", []):
            run = step.get("run") or ""
            for match in _UNITTEST_RE.finditer(run):
                modules.update(
                    token.split(".", 1)[1]
                    for token in match.group(1).split())
        if modules:
            jobs[job_id] = modules
    return jobs


def group_execution_map(doc):
    """Return {group_id: set(test_module)} merging shard jobs into groups."""
    per_job = parse_workflow(doc)
    groups = {}
    for job_id, modules in per_job.items():
        m = SHARD_JOB_RE.match(job_id)
        group = m.group("group") if m else job_id
        groups.setdefault(group, set()).update(modules)
    return groups


def registry_modules():
    """Canonical registry module sets from scripts/plan_ci.py."""
    import plan_ci
    return {g: set(m) for g, m in plan_ci.GROUP_TEST_MODULES.items()}


def parity_problems(doc, registry=None):
    """Return a list of human-readable parity failures (empty == parity).

    Invariants enforced:

      1. every registered module appears in the workflow execution
         surface (union over all groups);
      2. no workflow unittest module is absent from the registry;
      3. every non-sharded group's executable set equals its registry
         set (missing AND extra both fail);
      4. the union of all shard commands equals the sharded group's
         registry set;
      5. multi-step groups (repo-integrity) union to their registry set;
      6. no registered module exists without an executable CI command;
      7. no workflow command executes an unregistered module;
      8. a module appears in two unrelated execution groups only when
         duplication is declared (no declared duplication exists today).
    """
    if registry is None:
        registry = registry_modules()
    exec_by_group = group_execution_map(doc)
    problems = []

    for group, reg_modules in sorted(registry.items()):
        exec_modules = exec_by_group.get(group)
        if exec_modules is None:
            problems.append(
                f"group '{group}' is registered but no workflow job "
                f"executes any of its modules")
            continue
        missing = reg_modules - exec_modules
        extra = exec_modules - reg_modules
        if missing:
            problems.append(
                f"group '{group}' modules registered but not executed "
                f"in the workflow: {sorted(missing)}")
        if extra:
            problems.append(
                f"group '{group}' modules executed in the workflow but "
                f"not registered: {sorted(extra)}")

    all_exec = set()
    for modules in exec_by_group.values():
        all_exec |= modules
    all_reg = set()
    for modules in registry.values():
        all_reg |= modules
    unregistered = sorted(all_exec - all_reg)
    if unregistered:
        problems.append(
            f"workflow executes unregistered modules: {unregistered}")
    never = sorted(all_reg - all_exec)
    if never:
        problems.append(
            f"registered modules with no executable CI command: {never}")

    seen = {}
    for group, modules in sorted(exec_by_group.items()):
        for module in modules:
            seen.setdefault(module, []).append(group)
    declared = set()  # no declared cross-group duplication exists today
    for module, groups in sorted(seen.items()):
        overlap = set(groups) - declared
        if len(overlap) > 1:
            problems.append(
                f"module '{module}' executes in multiple unrelated "
                f"groups without declared duplication: {sorted(overlap)}")

    return problems
