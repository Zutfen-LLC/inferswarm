"""Workflow-vs-registry parity model for Issue #153 CI correction.

Derives the *executable* unittest module inventory from the REAL
``.github/workflows/ci.yml`` ``run:`` commands and compares it with the
canonical registry (``scripts/plan_ci.py`` ``GROUP_TEST_MODULES`` /
``scripts/ci_groups.json``). This is a mechanical derivation from the
workflow bytes — not a hand-maintained mirror table.

Issue #287 adds *identity* accounting on top of module parity: the
executable identity of a group is the multiset of unittest IDs its
workflow commands expand to (via the same ``unittest`` loader the
commands use), and it must equal the discovered population of the
group's registered modules exactly - no omissions, no duplicates, no
unregistered extras.  ``--identity-proof`` emits that accounting as
deterministic machine-readable JSON so a before/after equality proof can
be produced for any checkout::

    python3 scripts/ci_workflow_parity.py --identity-proof
    python3 scripts/ci_workflow_parity.py --root /path/to/other/checkout \
        --group r8i-qwen-qualification

Shared by ``tests/test_plan_ci.py`` (parity guard + negative controls).
Pure stdlib plus PyYAML (part of the canonical #131 test environment).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unittest
from collections import Counter
from pathlib import Path

try:
    import yaml
except ImportError as exc:  # pragma: no cover - #131 env provides yaml
    raise ImportError(
        "pyyaml is required by the CI parity guard "
        "(canonical #131 test environment)") from exc

REPO_ROOT = Path(__file__).resolve().parent.parent

# A unittest invocation line inside a workflow `run:` command. Only
# plain `-m unittest tests.module [...]` forms count as execution;
# discovery and pytest invocations are deliberately NOT execution of a
# named registry module.
#
# A token is ``tests.<module>`` or, for a module split across shards at test
# granularity (Issue #287), ``tests.<module>.<Class>[.<test>]``.
_UNITTEST_RE = re.compile(
    r"(?:^|\n)\s*(?:python3?|\.venv/bin/python)\s+"
    r"-m\s+unittest((?:\s+tests\.[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+){0,2})+)",
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
                    token.split(".")[1]
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


def parse_workflow_tokens(doc):
    """Return {job_id: [token, ...]} preserving order and duplicates.

    A token is ``<module>`` or a ``<module>.<Class>[.<test>]`` selector
    (the ``tests.`` prefix is stripped).
    """
    jobs = {}
    for job_id, job in doc.get("jobs", {}).items():
        modules = []
        for step in job.get("steps", []):
            run = step.get("run") or ""
            for match in _UNITTEST_RE.finditer(run):
                modules.extend(
                    token.split(".", 1)[1]
                    for token in match.group(1).split())
        if modules:
            jobs[job_id] = modules
    return jobs


class IdentityError(RuntimeError):
    """A test module does not load into real, runnable test identities."""


def _flatten(suite):
    if isinstance(suite, unittest.TestCase):
        return [suite]
    tests = []
    for child in suite:
        tests.extend(_flatten(child))
    return tests


_MODULE_IDS_CACHE = {}


def module_test_ids(module, root=None):
    """unittest IDs ``python -m unittest tests.<module>`` would run.

    Uses the same loader as the workflow commands.  A module that does not
    load (missing, import error) yields loader ``_FailedTest`` identities,
    which are rejected: a CI command that cannot name real tests is a
    failure of the identity contract, never an empty contribution.
    """
    root = Path(root).resolve() if root else REPO_ROOT
    key = (str(root), module)
    if key in _MODULE_IDS_CACHE:
        return list(_MODULE_IDS_CACHE[key])
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    suite = unittest.TestLoader().loadTestsFromName(f"tests.{module}")
    ids = [test.id() for test in _flatten(suite)]
    failed = [i for i in ids if i.startswith("unittest.loader._FailedTest")]
    if failed or not ids:
        raise IdentityError(
            f"test module 'tests.{module}' does not load into runnable "
            f"test identities: {failed or 'no tests'}")
    _MODULE_IDS_CACHE[key] = tuple(ids)
    return ids


def token_test_ids(token, root=None):
    """unittest IDs one command token (``module`` or selector) runs.

    A selector must name real, loader-discovered identities: a class
    selector expands to every test of that class, a method selector to
    exactly that test.  A selector that names nothing is an error (it
    would otherwise run nothing and silently narrow coverage).
    """
    module, *selector = token.split(".")
    ids = module_test_ids(module, root)
    if not selector:
        return ids
    prefix = f"tests.{token}"
    chosen = [i for i in ids if i == prefix or i.startswith(prefix + ".")]
    if not chosen:
        raise IdentityError(
            f"selector 'tests.{token}' names no real test identity in "
            f"'tests.{module}'")
    return chosen


def _digest(ids):
    return hashlib.sha256(
        ("\n".join(sorted(ids)) + "\n").encode("utf-8")).hexdigest()


def job_executed_ids(doc, root=None):
    """{job_id: [unittest id, ...]} expanded from each job's commands."""
    return {job: [i for t in tokens for i in token_test_ids(t, root)]
            for job, tokens in parse_workflow_tokens(doc).items()}


def group_executed_ids(doc, root=None):
    """{group_id: [unittest id, ...]} merging shard jobs into their group."""
    groups = {}
    for job_id, ids in job_executed_ids(doc, root).items():
        m = SHARD_JOB_RE.match(job_id)
        groups.setdefault(m.group("group") if m else job_id, []).extend(ids)
    return groups


def _modules_of(ids):
    return sorted({i.split(".")[1] for i in ids})


def _identity_accounting(doc, registry, root=None):
    """Per group: discovered vs executed multisets and their differences."""
    executed_by_group = group_executed_ids(doc, root)
    accounting = {}
    for group, reg_modules in sorted(registry.items()):
        discovered = [i for m in sorted(reg_modules)
                      for i in module_test_ids(m, root)]
        executed = executed_by_group.get(group, [])
        counts = Counter(executed)
        accounting[group] = {
            "discovered": discovered,
            "executed": executed,
            "missing": sorted(set(discovered) - set(counts)),
            "unregistered": sorted(set(counts) - set(discovered)),
            "duplicates": sorted(i for i, c in counts.items() if c > 1),
        }
    return accounting


def identity_problems(doc, registry=None, root=None):
    """Return exact test-identity failures (empty list == identity parity).

    For every registered group the multiset of unittest IDs executed by
    the group's workflow jobs must equal the loader-discovered population
    of its registered modules.  Count equality alone is never accepted.
    """
    if registry is None:
        registry = registry_modules()
    try:
        accounting = _identity_accounting(doc, registry, root)
    except IdentityError as exc:
        return [str(exc)]
    problems = []
    for group, acc in accounting.items():
        for key, text in (
                ("missing", "identities discovered but not executed"),
                ("duplicates", "identities executed more than once"),
                ("unregistered", "identities executed but not registered")):
            if acc[key]:
                problems.append(
                    f"group '{group}' {text} ({len(acc[key])}): modules "
                    f"{_modules_of(acc[key])}")
    return problems


def identity_proof(doc, registry=None, groups=None, root=None):
    """Deterministic machine-readable identity accounting for ``groups``."""
    if registry is None:
        registry = registry_modules()
    accounting = _identity_accounting(doc, registry, root)
    per_job = job_executed_ids(doc, root)
    proof = {"schema": "inferswarm.ci.identity-proof/1", "groups": {}}
    for group, acc in accounting.items():
        if groups and group not in groups:
            continue
        jobs = {}
        for job, ids in sorted(per_job.items()):
            m = SHARD_JOB_RE.match(job)
            if (m.group("group") if m else job) != group:
                continue
            jobs[job] = {"tokens": parse_workflow_tokens(doc)[job],
                         "count": len(ids), "ids_sha256": _digest(ids)}
        proof["groups"][group] = {
            "registered_modules": len(registry[group]),
            "jobs": jobs,
            "discovered_count": len(acc["discovered"]),
            "discovered_sha256": _digest(acc["discovered"]),
            "executed_count": len(acc["executed"]),
            "executed_sha256": _digest(acc["executed"]),
            "missing_ids": acc["missing"],
            "unregistered_ids": acc["unregistered"],
            "duplicate_ids": acc["duplicates"],
        }
    return proof


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


def _registry_from_json(root):
    reg = json.loads((Path(root) / "scripts" / "ci_groups.json")
                     .read_text(encoding="utf-8"))
    return {g: set(info["test_modules"]) for g, info in reg["groups"].items()}


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Workflow-vs-registry test-identity proof (Issue #287)")
    ap.add_argument("--identity-proof", action="store_true",
                    help="print the identity accounting as JSON (default)")
    ap.add_argument("--root", default=str(REPO_ROOT),
                    help="checkout whose workflow/registry/tests to analyze")
    ap.add_argument("--group", action="append",
                    help="restrict the proof to this group (repeatable)")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    with open(root / ".github" / "workflows" / "ci.yml",
              encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    registry = _registry_from_json(root)
    proof = identity_proof(doc, registry, groups=args.group, root=root)
    sys.stdout.write(json.dumps(proof, indent=1, sort_keys=True) + "\n")
    problems = identity_problems(doc, registry, root=root)
    for problem in problems:
        print(f"ERROR: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
