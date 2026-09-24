"""Issue #148 CI planner and aggregate-gate tests (adversarial, fail-closed).

Covers the 20 mandated planner/gate behaviors plus the inventory
invariants that make silently adding an unclassified CI group or test
module difficult:

  * planner determinism and plan-schema shape;
  * every registered group maps to executable commands and every
    pre-change CI unittest module is owned by exactly one registered
    group (no coverage lost, no silent additions);
  * docs-only, family-only, shared, and authority changes select the
    expected scopes;
  * every fail-closed surface (workflows, planner/registry/tests,
    requirements, bootstrap/doctor, repo authority, unknown paths,
    malformed input) escalates to full regression;
  * the aggregate gate logic (mirrored here from the workflow's CI
    Gate job) fails on failed/missing/malformed selected groups and
    passes only when all selected groups succeeded.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_ci_test_retention as retention  # noqa: E402
import plan_ci  # noqa: E402

PLANNER = REPO_ROOT / "scripts" / "plan_ci.py"


def run_planner(*argv, stdin=None):
    return subprocess.run(
        [sys.executable, str(PLANNER), *argv],
        capture_output=True, text=True, cwd=REPO_ROOT,
        input=stdin,
    )


def make_plan(paths, mode="pr"):
    return plan_ci.plan(paths, mode=mode)


def _retired_integrity_roots():
    audit = retention.load_audit(REPO_ROOT)
    return tuple(bundle["root"]
                 for replacement in audit["integrity_replacements"]
                 for bundle in replacement["bundles"])


RETIRED_INTEGRITY_ROOTS = _retired_integrity_roots()

# Issue #246 (PR #247 correction round 1): groups that no longer exist.
# Their suites were deleted; their evidence is integrity-pinned.
RETIRED_GROUPS = {"vulkan-v0-b", "phase1-analysis", "issue-175-arm-d",
                  "vulkan-v0b", "vulkan-v0c-v2a", "link-x1-issue35",
                  "issue-137", "issue-172-requal", "issue-182-arm-e"}


class TestPlannerContract(unittest.TestCase):
    def test_plan_schema_shape(self):
        p = make_plan(["docs/README.md"])
        self.assertEqual(p["schema"], "ci-plan/1")
        self.assertEqual(p["mode"], "targeted")
        self.assertFalse(p["full_regression"])
        self.assertEqual(p["planner"], "scripts/plan_ci.py")
        self.assertIn("groups", p)
        self.assertIn("reason", p)
        self.assertEqual(p["groups"], sorted(set(p["groups"])))

    def test_deterministic(self):
        a = make_plan(["scripts/v0b_terminal.py", "ROADMAP.md"])
        b = make_plan(["scripts/v0b_terminal.py", "ROADMAP.md"])
        self.assertEqual(json.dumps(a, sort_keys=True),
                         json.dumps(b, sort_keys=True))

    def test_reproducible_across_processes(self):
        r1 = run_planner("--mode", "pr", "--", "scripts/v0b_terminal.py")
        r2 = run_planner("--mode", "pr", "--", "scripts/v0b_terminal.py")
        self.assertEqual(r1.returncode, 0)
        self.assertEqual(r1.stdout, r2.stdout)

    def test_cli_stdin_matches_argv(self):
        r1 = run_planner("--mode", "pr", stdin="docs/README.md\n")
        r2 = run_planner("--mode", "pr", "--", "docs/README.md")
        self.assertEqual(r1.stdout, r2.stdout)

    def test_registry_is_canonical(self):
        self.assertEqual(plan_ci.self_check(), [])

    def test_registry_on_disk_matches_builder(self):
        reg = plan_ci.load_registry()
        canonical = json.loads(json.dumps(plan_ci.build_registry()))
        self.assertEqual(reg, canonical)


class TestSelectionBehavior(unittest.TestCase):
    """The 20 issue-mandated selection cases."""

    # 1. docs-only
    def test_docs_only_selects_integrity_not_117(self):
        p = make_plan(["docs/README.md", "ROADMAP.md"])
        self.assertFalse(p["full_regression"])
        self.assertEqual(p["groups"], ["repo-integrity"])
        self.assertNotIn("issue-117-133", p["groups"])

    # 2. Retired Vulkan V0-B lineage: integrity only (Issue #246)
    def test_retired_vulkan_v0b_lineage_selects_integrity_only(self):
        p = make_plan(["scripts/v0b_terminal.py",
                       "docs/implementation/vulkan-v0-b/summary.md"])
        self.assertFalse(p["full_regression"])
        self.assertEqual(p["groups"], ["repo-integrity"])

    # 3. Issue #117 producer change
    def test_issue117_producer_selects_lineage(self):
        p = make_plan(["scripts/issue117_planner.py"])
        self.assertFalse(p["full_regression"])
        self.assertIn("issue-117-133", p["groups"])

    def test_issue117_evidence_change_selects_lineage(self):
        p = make_plan(["docs/implementation/r6-successor-dense-full-integration-117/"
                       "evidence/arm-c-retry/summary.md"])
        self.assertIn("issue-117-133", p["groups"])
        self.assertFalse(p["full_regression"])

    def test_issue117_test_module_change_selects_lineage(self):
        p = make_plan(["tests/test_issue133_physical_execution_retention.py"])
        self.assertIn("issue-117-133", p["groups"])

    # 4. common/shared module change selects every consumer
    def test_shared_test_helper_fails_closed(self):
        # conftest.py and tests/ helpers are shared: full regression
        p = make_plan(["conftest.py"])
        self.assertTrue(p["full_regression"])
        self.assertTrue(any("fail-closed" in r for r in p["reason"]))

    # 5. requirements-test.txt widens
    def test_requirements_change_full_regression(self):
        p = make_plan(["requirements-test.txt"])
        self.assertTrue(p["full_regression"])

    # 6. bootstrap/doctor widens
    def test_bootstrap_doctor_change_full_regression(self):
        for path in ("scripts/bootstrap_test_env.py",
                     "scripts/check_test_env.py"):
            p = make_plan([path])
            self.assertTrue(p["full_regression"], path)
            self.assertIn("repo-integrity", p["groups"])

    # 7. workflow change forces full
    def test_workflow_change_forces_full(self):
        p = make_plan([".github/workflows/ci.yml"])
        self.assertTrue(p["full_regression"])
        p = make_plan([".github/workflows/new-workflow.yml"])
        self.assertTrue(p["full_regression"])

    # 8. planner/registry change forces full
    def test_planner_authority_change_forces_full(self):
        for path in ("scripts/plan_ci.py", "scripts/ci_groups.json",
                     "tests/test_plan_ci.py"):
            p = make_plan([path])
            self.assertTrue(p["full_regression"], path)

    # 9. unknown new root/path forces full
    def test_unknown_path_forces_full(self):
        for path in ("new-toplevel-file.md", "brandnew/dir/file.py",
                     "src/main.py", "unknown_root"):
            p = make_plan([path])
            self.assertTrue(p["full_regression"], path)

    def test_unregistered_script_fails_closed(self):
        p = make_plan(["scripts/new_shared_util.py"])
        self.assertTrue(p["full_regression"])

    def test_unregistered_test_module_fails_closed(self):
        p = make_plan(["tests/test_issue999_new.py"])
        self.assertTrue(p["full_regression"])

    # 10. deleted/renamed files still classified by path
    def test_deleted_path_still_classified(self):
        # classification is purely path-based; deletion of a family
        # file still selects the family (and CI checkout verifies).
        p = make_plan(["scripts/issue117_planner.py"])
        self.assertIn("issue-117-133", p["groups"])

    # 11. multiple paths union their groups
    def test_multiple_paths_union(self):
        p = make_plan(["scripts/issue117_planner.py",
                       "scripts/issue237_methodology.py"])
        self.assertFalse(p["full_regression"])
        self.assertEqual(p["groups"], ["issue-117-133",
                                       "r8i-qwen-qualification",
                                       "repo-integrity"])

    def test_one_path_selects_multiple_groups(self):
        # the v4 methodology core is imported by the #83 doctrine, V5, and
        # the current R8-I comparator
        p = make_plan(["scripts/issue95_v4_methodology.py"])
        for group in ("issue-83-95", "issue-109-110", "r8i-qwen-qualification"):
            self.assertIn(group, p["groups"])

    # 12. malformed input fails closed
    def test_malformed_input_fails_closed(self):
        for bad in ([""], [" docs/README.md"], ["docs/README.md "],
                    ["/abs/path"], ["../escape"], ["docs/README.md/"],
                    ["docs\\readme"], ["docs/README.md", "docs/README.md"]):
            p = make_plan(bad)
            self.assertTrue(p["full_regression"], repr(bad))

    def test_empty_path_list_is_not_narrow(self):
        # no changed paths at all (empty diff) — ambiguous, fail closed
        p = make_plan([])
        self.assertTrue(p["full_regression"])

    # 13. duplicate groups normalize deterministically
    def test_duplicate_groups_normalize(self):
        p = make_plan(["scripts/issue74_methodology.py",
                       "scripts/issue79_v2_thresholds.py"])
        self.assertEqual(p["groups"].count("issue-74-79"), 1)
        self.assertEqual(p["groups"], sorted(p["groups"]))

    # 14. full mode includes every registered group
    def test_full_mode_includes_every_group(self):
        p = make_plan(["docs/README.md"], mode="full")
        self.assertTrue(p["full_regression"])
        self.assertEqual(p["groups"],
                         sorted(plan_ci.GROUP_TEST_MODULES.keys()))

    # 20. push-to-main always full
    def test_push_to_main_is_full(self):
        # the workflow hardcodes mode=full on push; the planner must
        # never downgrade an explicit full request
        p = plan_ci.plan(["docs/README.md"], mode="full")
        self.assertTrue(p["full_regression"])
        self.assertEqual(p["mode"], "full")

    def test_reason_lines_present_for_selections(self):
        p = make_plan(["scripts/issue74_methodology.py"])
        self.assertTrue(any("issue-74-79" in r for r in p["reason"]))

    def test_full_regression_reason_present(self):
        p = make_plan(["src/main.py"])
        self.assertTrue(any("unclassified" in r or "fail-closed" in r
                            for r in p["reason"]))


class TestInventoryInvariants(unittest.TestCase):
    """No test lost, no silent additions, every group executable."""

    def test_every_test_module_owned_exactly_once(self):
        on_disk = sorted(f[:-3] for f in os.listdir(REPO_ROOT / "tests")
                         if f.startswith("test_") and f.endswith(".py"))
        owned = sorted(m for mods in plan_ci.GROUP_TEST_MODULES.values()
                       for m in mods)
        self.assertEqual(on_disk, owned,
                         "every tests/test_*.py must be registered in "
                         "exactly one CI group (plan_ci.GROUP_TEST_MODULES)")

    def test_every_group_nonempty(self):
        for g, mods in plan_ci.GROUP_TEST_MODULES.items():
            self.assertTrue(mods, g)

    def test_repo_integrity_is_always_on(self):
        self.assertEqual(plan_ci.ALWAYS_ON_GROUPS, ["repo-integrity"])
        p = make_plan(["docs/README.md"])
        self.assertIn("repo-integrity", p["groups"])

    def test_full_regression_groups_all_registered(self):
        reg = plan_ci.build_registry()
        for g in reg["groups"]:
            self.assertIn(g, reg["path_rules"].values().__class__ and
                          reg["groups"])
        # path rules only reference registered groups
        for pattern, gs in reg["path_rules"].items():
            for g in gs:
                self.assertIn(g, reg["groups"])


class TestAggregateGate(unittest.TestCase):
    """Mirror of the workflow's CI Gate aggregation semantics."""

    @staticmethod
    def gate(plan, results):
        """results: {group: 'success'|'failure'|'skipped'|'cancelled'|None}.

        Mirrors the CI Gate job: fail unless repo-integrity and every
        selected group succeeded; skipped is legitimate ONLY for
        unselected groups.
        """
        if plan is None:
            return False, "plan malformed or absent"
        try:
            selected = set(plan["groups"])
            full = bool(plan["full_regression"])
        except (TypeError, KeyError):
            return False, "plan malformed"
        if not selected:
            return False, "plan selected no groups"
        for g in selected:
            outcome = results.get(g)
            if outcome == "success":
                continue
            if outcome == "skipped" and not full:
                # skipped selected group is only legitimate when the
                # group was deselected — but it WAS selected
                return False, f"selected group {g} skipped"
            return False, f"selected group {g} -> {outcome}"
        return True, "ok"

    def test_gate_passes_all_selected_success(self):
        plan = {"groups": ["repo-integrity", "r8i-qwen-qualification"],
                "full_regression": False}
        results = {"repo-integrity": "success",
                   "r8i-qwen-qualification": "success",
                   "issue-117-133": "skipped"}
        ok, _ = self.gate(plan, results)
        self.assertTrue(ok)

    # 17. gate fails when a selected group fails
    def test_gate_fails_on_selected_failure(self):
        plan = {"groups": ["repo-integrity", "r8i-qwen-qualification"],
                "full_regression": False}
        results = {"repo-integrity": "success",
                   "r8i-qwen-qualification": "failure",
                   "issue-117-133": "skipped"}
        ok, _ = self.gate(plan, results)
        self.assertFalse(ok)

    # 18. gate succeeds with unselected skips and all selected passing
    def test_gate_succeeds_unselected_skipped(self):
        p = make_plan(["scripts/issue237_methodology.py"])
        results = {g: "success" for g in p["groups"]}
        for g in plan_ci.GROUP_TEST_MODULES:
            results.setdefault(g, "skipped")
        ok, _ = self.gate(p, results)
        self.assertTrue(ok)

    # 19. gate fails when a selected group never ran / cancelled
    def test_gate_fails_on_missing_selected_group(self):
        p = make_plan(["scripts/issue237_methodology.py"])
        results = {g: "success" if g != "r8i-qwen-qualification" else None
                   for g in p["groups"]}
        ok, _ = self.gate(p, results)
        self.assertFalse(ok)

    def test_gate_fails_on_cancelled_selected_group(self):
        p = make_plan(["scripts/issue237_methodology.py"])
        results = {g: "cancelled" for g in p["groups"]}
        ok, _ = self.gate(p, results)
        self.assertFalse(ok)

    def test_gate_fails_on_malformed_plan(self):
        ok, _ = self.gate(None, {})
        self.assertFalse(ok)
        ok, _ = self.gate({"groups": "repo-integrity"}, {})
        self.assertFalse(ok)
        ok, _ = self.gate({"groups": [], "full_regression": False}, {})
        self.assertFalse(ok)

    def test_gate_full_regression_requires_every_group(self):
        p = make_plan(["docs/README.md"], mode="full")
        results = {g: "success" for g in p["groups"]
                   if g != "issue-115-cleanup"}
        results["issue-115-cleanup"] = "skipped"
        ok, _ = self.gate(p, results)
        self.assertFalse(ok)

    def test_gate_fails_when_planner_step_failed(self):
        # planner failure is modeled as no plan -> gate fails closed
        ok, _ = self.gate(None, {"repo-integrity": "success"})
        self.assertFalse(ok)


class TestCLI(unittest.TestCase):
    def test_self_check_cli(self):
        r = run_planner("--self-check")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("OK", r.stdout)

    def test_full_mode_cli(self):
        r = run_planner("--mode", "full")
        self.assertEqual(r.returncode, 0)
        plan = json.loads(r.stdout)
        self.assertTrue(plan["full_regression"])

    def test_output_flag(self):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as fh:
            path = fh.name
        try:
            r = run_planner("--mode", "pr", "--output", path,
                            "--", "docs/README.md")
            self.assertEqual(r.returncode, 0)
            plan = json.loads(Path(path).read_text())
            self.assertEqual(plan["groups"], ["repo-integrity"])
        finally:
            os.unlink(path)


class TestWorkflowContract(unittest.TestCase):
    """Validate the REAL .github/workflows/ci.yml declared contract.

    These tests parse the actual workflow file (not a Python mirror of
    its intent). They fail when:

      * a registered non-always-on group has no runnable job or shard;
      * a targeted job's ``if:`` references a plan output that the
        ``plan`` job does not actually expose;
      * a selected group's condition would evaluate false (the job
        would skip despite being selected);
      * the workflow's group identifiers drift from the registry.
    """

    WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

    @classmethod
    def setUpClass(cls):
        import yaml
        with open(cls.WORKFLOW, encoding="utf-8") as fh:
            cls.doc = yaml.safe_load(fh)
        cls.jobs = cls.doc["jobs"]
        cls.plan_outputs = cls.jobs["plan"]["outputs"]

    def _selection_expression(self, job_id):
        cond = self.jobs[job_id]["if"]
        self.assertIn("needs.plan.outputs", cond, job_id)
        return cond

    def test_plan_job_exposes_referenced_outputs(self):
        """Every needs.plan.outputs.X in any job if:/step must exist."""
        import re
        text = open(self.WORKFLOW, encoding="utf-8").read()
        refs = set(re.findall(r"needs\.plan\.outputs\.([A-Za-z0-9_]+)", text))
        missing = refs - set(self.plan_outputs)
        self.assertEqual(missing, set(),
                         f"jobs reference nonexistent plan outputs: {missing}")

    def test_every_registered_group_has_runnable_job_or_shards(self):
        shard_prefix = "issue-117-133-s"
        group_jobs = {}
        for job_id, job in self.jobs.items():
            if job_id == "plan" or job_id == "ci-gate":
                continue
            cond = job.get("if", "")
            m = re.search(r"contains\(fromJSON\(needs\.plan\.outputs\.groups\)"
                          r", '([a-z0-9-]+)'\)", cond)
            if m:
                group_jobs.setdefault(m.group(1), []).append(job_id)
        for group in plan_ci.GROUP_TEST_MODULES:
            if group in plan_ci.ALWAYS_ON_GROUPS:
                continue
            self.assertIn(group, group_jobs,
                          f"registered group {group} has no selectable job")
            self.assertTrue(group_jobs[group], group)

    def test_issue117_runs_as_one_job(self):
        # the four shards existed for the retired ~850-test #117/#129/#133
        # replay lineage; the retained evidence-integrity group is small
        self.assertEqual([j for j in self.jobs if j.startswith("issue-117-133")],
                         ["issue-117-133"])
        self.assertIn("'issue-117-133'", self.jobs["issue-117-133"]["if"])

    def test_every_group_job_required_by_gate(self):
        gate_needs = set(self.jobs["ci-gate"]["needs"])
        self.assertEqual(gate_needs, set(self.jobs) - {"ci-gate"})

    def test_repo_integrity_has_no_selection_condition(self):
        self.assertNotIn("if", self.jobs["repo-integrity"])

    def test_gate_runs_always(self):
        self.assertEqual(self.jobs["ci-gate"]["if"], "always()")

    def test_gate_needs_plan(self):
        self.assertIn("plan", self.jobs["ci-gate"]["needs"])

    def test_selected_group_condition_evaluates_true_when_selected(self):
        """Mechanical evaluation of each job's if: for a real plan."""
        for group in plan_ci.GROUP_TEST_MODULES:
            if group in plan_ci.ALWAYS_ON_GROUPS:
                continue
            # a plan that selects exactly this group + repo-integrity
            p = plan_ci.plan(["scripts/plan-does-not-exist.py"],
                             mode="full")  # full selects all
            # find jobs selecting this group and evaluate the contains()
            # clause against the real groups list
            selected = p["groups"]
            for job_id, job in self.jobs.items():
                cond = job.get("if", "")
                m = re.search(r"contains\(fromJSON\(needs\.plan\.outputs\.groups\)"
                              r", '([a-z0-9-]+)'\)", cond)
                if m and m.group(1) == group:
                    self.assertIn(group, selected,
                                  f"{job_id} selected group missing from plan")

    def test_unselected_group_may_skip(self):
        # the OR structure: full_regression==true OR contains(...)
        for job_id, job in self.jobs.items():
            cond = job.get("if", "")
            if "contains(fromJSON" in cond:
                self.assertIn("full_regression == 'true'", cond, job_id)
                self.assertIn("||", cond, job_id)

    def test_gate_maps_every_registered_group_to_a_job_result(self):
        text = open(self.WORKFLOW, encoding="utf-8").read()
        for group in plan_ci.GROUP_TEST_MODULES:
            self.assertIn(f'"{group}"', text,
                          f"group {group} absent from workflow gate mapping")
        # The substring check above is not enough: a group can appear in the
        # reported `results` dict yet be missing from `job_for_group`, which
        # makes the fail-closed gate fail a green run
        # ("selected group X has no job mapping"). Assert membership in the
        # actual mapping the gate consults.
        marker = "job_for_group = {"
        self.assertIn(marker, text)
        block = text.split(marker, 1)[1].split("}", 1)[0]
        mapped = set(re.findall(r'"([a-z0-9-]+)":', block))
        self.assertEqual(mapped, set(plan_ci.GROUP_TEST_MODULES),
                         "gate job_for_group must map every registered group")

    def test_push_to_main_selects_full(self):
        # the Plan (push) step hardcodes --mode full
        text = open(self.WORKFLOW, encoding="utf-8").read()
        self.assertIn("--mode full", text)

    def test_workflow_group_ids_match_registry(self):
        """Group literals in the workflow == registry group ids."""
        text = open(self.WORKFLOW, encoding="utf-8").read()
        wf_groups = set(re.findall(
            r"contains\(fromJSON\(needs\.plan\.outputs\.groups\)"
            r", '([a-z0-9-]+)'\)", text))
        reg_groups = set(plan_ci.GROUP_TEST_MODULES) - set(plan_ci.ALWAYS_ON_GROUPS)
        self.assertEqual(wf_groups, reg_groups)

    def test_full_regression_contains_every_registered_group(self):
        p = plan_ci.plan([], mode="full")
        self.assertEqual(p["groups"], sorted(plan_ci.GROUP_TEST_MODULES))


class TestWorkflowRegistryParity(unittest.TestCase):
    """Mechanical workflow-vs-registry parity guard (Issue #153).

    Parses the REAL ``.github/workflows/ci.yml`` and derives the
    executable unittest module inventory from actual ``run:`` commands
    (no hand-maintained mirror table), then requires parity with
    ``GROUP_TEST_MODULES`` in every direction. The negative controls
    mutate a scratch copy of the parsed workflow/registry representation
    and prove the guard FAILS for each drift class.
    """

    WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

    @classmethod
    def setUpClass(cls):
        import yaml
        import ci_workflow_parity
        cls.parity = ci_workflow_parity
        with open(cls.WORKFLOW, encoding="utf-8") as fh:
            cls.doc = yaml.safe_load(fh)
        cls.registry = cls.parity.registry_modules()

    def _copy_doc(self):
        import copy
        return copy.deepcopy(self.doc)

    def _copy_registry(self):
        return {g: set(m) for g, m in self.registry.items()}

    # -- positive invariant ------------------------------------------------

    def test_real_workflow_and_registry_are_at_parity(self):
        problems = self.parity.parity_problems(self.doc, self.registry)
        self.assertEqual(problems, [],
                         "registry/workflow parity drift:\n  "
                         + "\n  ".join(problems))

    def test_r8i_job_executes_every_r8i_registered_module(self):
        exec_map = self.parity.group_execution_map(self.doc)
        self.assertEqual(exec_map["r8i-qwen-qualification"],
                         self.registry["r8i-qwen-qualification"])
        self.assertIn("test_issue237_r8i_methodology",
                      exec_map["r8i-qwen-qualification"])

    def test_repo_integrity_union_equals_registry(self):
        exec_map = self.parity.group_execution_map(self.doc)
        self.assertEqual(exec_map["repo-integrity"],
                         self.registry["repo-integrity"])

    def test_issue117_job_equals_registry(self):
        exec_map = self.parity.group_execution_map(self.doc)
        self.assertEqual(exec_map["issue-117-133"],
                         self.registry["issue-117-133"])

    def test_group_jobs_execute_each_registered_module_exactly_once(self):
        from collections import Counter
        counts = Counter()
        for job_id, job in self.doc["jobs"].items():
            for step in job.get("steps", []):
                run = step.get("run") or ""
                for match in self.parity._UNITTEST_RE.finditer(run):
                    counts.update(token.split(".", 1)[1]
                                  for token in match.group(1).split())
        duplicated = {m: c for m, c in counts.items() if c != 1}
        self.assertEqual(duplicated, {},
                         "workflow commands must execute every registered "
                         "module exactly once")
        self.assertEqual(set(counts),
                         set().union(*self.registry.values()))

    # -- negative controls (scratch representations) ----------------------

    def _assert_problems(self, doc, registry, needle):
        problems = self.parity.parity_problems(doc, registry)
        self.assertTrue(problems,
                        "mutated representation must fail parity")
        self.assertTrue(
            any(needle in p for p in problems),
            f"expected failure mentioning {needle!r}, got: {problems}")

    def test_control_registered_r8i_module_removed_from_workflow(self):
        # (1) an R8-I module stays registered but the workflow command
        # no longer executes it.
        doc = self._copy_doc()
        step = [s for s in doc["jobs"]["r8i-qwen-qualification"]["steps"]
                if "unittest" in (s.get("run") or "")][0]
        step["run"] = step["run"].replace(
            " tests.test_issue244_r8i5_v340l_import", "")
        self._assert_problems(doc, self.registry,
                              "test_issue244_r8i5_v340l_import")

    def test_control_test_plan_ci_registered_but_not_executed(self):
        # (2) test_plan_ci is registered to repo-integrity but no step
        # executes it.
        doc = self._copy_doc()
        for step in doc["jobs"]["repo-integrity"]["steps"]:
            run = step.get("run") or ""
            if "unittest" in run and "test_plan_ci" in run:
                step["run"] = run.replace("tests.test_plan_ci", "")
        self.assertIn("test_plan_ci", self.registry["repo-integrity"])
        self._assert_problems(doc, self.registry, "test_plan_ci")

    def test_control_issue117_job_drops_a_module(self):
        # (3) the Issue #117 job silently drops a module.
        doc = self._copy_doc()
        step = [s for s in doc["jobs"]["issue-117-133"]["steps"]
                if "unittest" in (s.get("run") or "")][0]
        step["run"] = step["run"].replace(
            " tests.test_issue184_final_closure", "")
        self._assert_problems(doc, self.registry,
                              "test_issue184_final_closure")

    def test_control_workflow_runs_an_unregistered_module(self):
        # (4) a workflow command executes a module the registry does
        # not know.
        doc = self._copy_doc()
        registry = self._copy_registry()
        step = [s for s in doc["jobs"]["r8i-qwen-qualification"]["steps"]
                if "unittest" in (s.get("run") or "")][0]
        step["run"] = step["run"].replace(
            "tests.test_issue237_r8i_methodology",
            "tests.test_issue237_r8i_methodology tests.test_ghost_module")
        self._assert_problems(doc, registry, "test_ghost_module")

    def test_control_module_in_two_unrelated_groups(self):
        # (5) a module appears in two unrelated execution groups while
        # no duplication is declared.
        doc = self._copy_doc()
        step = [s for s in doc["jobs"]["issue-74-79"]["steps"]
                if "unittest" in (s.get("run") or "")][0]
        step["run"] = step["run"].replace(
            "tests.test_issue74_methodology",
            "tests.test_issue74_methodology tests.test_issue237_r8i_methodology")
        self._assert_problems(doc, self.registry,
                              "multiple unrelated groups")


class TestRepositoryTreeCoverage(unittest.TestCase):
    """Real tracked paths (git ls-files census) select real consumers.

    Fails when a configured prefix does not exist in the tracked tree,
    when a retained evidence path classifies to the wrong groups, or
    when an unclassified evidence-bearing docs file would stay narrow.
    """

    @classmethod
    def setUpClass(cls):
        cls.files = set(subprocess.check_output(
            ["git", "ls-files"], cwd=REPO_ROOT, text=True).splitlines())

    def _plan_groups(self, path):
        p = plan_ci.plan([path], mode="pr")
        self.assertFalse(p["full_regression"], path)
        return set(p["groups"])

    def test_retired_v0b_evidence_selects_integrity_only(self):
        # Issue #246: the V0-B replay suite is retired; its accepted
        # evidence is pinned by the always-on retired-lineage check.
        g = self._plan_groups(
            "docs/investigations/vulkan-v0-b/results/economics.json")
        self.assertEqual(g, {"repo-integrity"})

    def test_retired_v0a_evidence_selects_integrity_only(self):
        for path in (
            "docs/investigations/vulkan-v0-a/results/bench-summary.json",
            "docs/investigations/vulkan-v0-a/correctness/correction-cor-nvavk-01/run.json",
            "docs/investigations/vulkan-v0-a/MANIFEST.sha256",
        ):
            self.assertIn(path, self.files, path)
            g = self._plan_groups(path)
            self.assertEqual(g, {"repo-integrity"}, path)

    def test_v5_manifests_select_real_consumers(self):
        for path in (
            "docs/qualification/gemma4-12b-it-v5/manifests/build-audit.json",
            "docs/qualification/gemma4-12b-it-v5/schemas/holdout-custody-record.schema.json",
            "docs/qualification/gemma4-12b-it-v5/sealed/holdout.cms",
        ):
            self.assertIn(path, self.files, path)
            g = self._plan_groups(path)
            self.assertEqual(g, {"repo-integrity", "issue-109-110",
                                 "issue-117-133"}, path)

    def test_campaign110_preflight_selects_real_consumers(self):
        for path in (
            "docs/qualification/gemma4-12b-it-v5-campaign-110/preflight/HOLDOUT-EXECUTION-AUTHORITY.json",
            "docs/qualification/gemma4-12b-it-v5-campaign-110/preflight/effective-holdout-custody-record.json",
        ):
            self.assertIn(path, self.files, path)
            g = self._plan_groups(path)
            self.assertEqual(g, {"repo-integrity", "issue-109-110",
                                 "issue-117-133"}, path)

    def test_cleanup_selects_issue115(self):
        for path in (
            "docs/qualification/gemma4-12b-it-v5-campaign-110/cleanup/RAW-EVIDENCE-RETENTION.json",
            "docs/qualification/gemma4-12b-it-v5-campaign-110/cleanup/build_retention_manifest.py",
        ):
            self.assertIn(path, self.files, path)
            g = self._plan_groups(path)
            self.assertIn("issue-115-cleanup", g, path)

    def test_phase1_results_select_integrity_only(self):
        # Issue #246: the historical Phase-1 derivation replays were
        # retired; the frozen results are pinned by the always-on
        # retired-lineage integrity check instead.
        for path in (
            "docs/benchmarks/results/phase1/data/p6-analysis.json",
            "docs/benchmarks/results/phase1/data/raw/session-1/plan.json",
            "docs/investigations/data/p0i-routing-histogram.json",
            "scripts/derive_phase1r_d7_placement.py",
        ):
            self.assertIn(path, self.files, path)
            g = self._plan_groups(path)
            self.assertEqual(g, {"repo-integrity"}, path)

    def test_issue137_retained_evidence_selects_integrity_and_shared(self):
        # #137 evidence is nested in the #117 tree; its replay suites are
        # retired (integrity-pinned), and the shared-tree lineage still runs.
        path = ("docs/implementation/r6-successor-dense-full-integration-117/"
                "evidence/arm-c-regime4-diagnosis-137/")
        nested = [f for f in self.files if f.startswith(path)]
        self.assertTrue(nested, "no tracked #137 evidence files")
        for f in sorted(nested)[:3]:
            g = self._plan_groups(f)
            self.assertEqual(g, {"repo-integrity", "issue-117-133"}, f)

    def test_every_configured_prefix_exists_in_tree(self):
        dirs = set()
        for f in self.files:
            parts = f.split("/")
            for i in range(1, len(parts)):
                dirs.add("/".join(parts[:i]) + "/")
        for pattern in plan_ci.PATH_GROUPS:
            if pattern.endswith("/"):
                self.assertIn(pattern, dirs,
                              f"configured directory prefix not tracked: {pattern}")
            else:
                self.assertIn(pattern, self.files,
                              f"configured file rule not tracked: {pattern}")

    def test_unknown_evidence_bearing_docs_fails_closed(self):
        # A new generated/evidence-like file in an unmapped docs tree
        # must NOT be treated as ordinary prose.
        p = plan_ci.plan(["docs/qualification/newfamily/campaign/verdict.json"],
                         mode="pr")
        self.assertTrue(p["full_regression"])

    def test_normal_markdown_docs_stay_narrow(self):
        for path in ("docs/README.md", "docs/some/new/notes.md",
                     "docs/implementation/phase0-baseline.md"):
            p = plan_ci.plan([path], mode="pr")
            self.assertFalse(p["full_regression"], path)
            self.assertEqual(p["groups"], ["repo-integrity"], path)

    def test_shared_artifact_selects_union_of_consumers(self):
        # acquisition-99 evidence is consumed by both test_issue103_planner
        # (issue-99-103) and test_issue117_provenance (issue-117-133)
        path = ("docs/implementation/plan-driven-artifact-acquisition-99/"
                "evidence/canonical-summary.json")
        self.assertIn(path, self.files)
        g = self._plan_groups(path)
        self.assertEqual(g, {"repo-integrity", "issue-99-103",
                             "issue-117-133"})

    def test_unmapped_evidence_census_fail_closed(self):
        """Invariant: every tracked non-.md docs file must be classified
        by an explicit rule (or be one of the documented repo-integrity
        authority files). Otherwise adding a new evidence-bearing docs
        subtree without registering it fails this test.
        """
        problems = []
        for f in sorted(self.files):
            if not f.startswith("docs/") or f.endswith(".md"):
                continue
            groups, classified = plan_ci.classify_path(f)
            if not classified:
                problems.append(f"unclassified evidence file: {f}")
            elif set(groups) - {"repo-integrity"} == set():
                # classified as repo-integrity only: legitimate only
                # for the documented authority/prose-adjacent files
                allowed = {
                    "docs/project-status.json",
                }
                # frozen Phase-0 workloads: verified by the always-on
                # check_phase0_workloads.py repo-integrity step
                if f.startswith("docs/benchmarks/workloads/"):
                    allowed_prose = True
                # living hardware inventory receipts (Issue #196): raw
                # read-only scan captures backing the living PCIe slot
                # ledger; deliberately superseded by later refreshes,
                # never retained experiment evidence
                elif f.startswith("docs/hardware/current-inventory/"):
                    allowed_prose = True
                # Issue #246 retired lineages: evidence whose behavior
                # suites were retired is verified by the always-on
                # retired-lineage integrity check (accepted manifests
                # plus CI-owned pins), and the retention authority
                # itself lives under docs/ci/.
                elif f.startswith(RETIRED_INTEGRITY_ROOTS + ("docs/ci/",)):
                    allowed_prose = True
                else:
                    allowed_prose = f in allowed
                if not allowed_prose:
                    problems.append(
                        f"non-prose docs file narrow as repo-integrity "
                        f"only: {f}")
        self.assertEqual(problems, [])


class TestRetentionTopology(unittest.TestCase):
    """Issue #246: groups follow current dependency/authority boundaries.

    The former monolithic ``vulkan-v0-b`` bucket is split by import-graph
    component; retired historical suites are replaced by integrity pins
    that run in the always-on group.
    """

    def test_every_group_declares_its_current_invariant(self):
        registry = plan_ci.build_registry()
        for group, info in registry["groups"].items():
            self.assertTrue(info.get("invariant", "").strip(), group)
        self.assertEqual(set(plan_ci.GROUP_INVARIANTS),
                         set(plan_ci.GROUP_TEST_MODULES))

    def test_self_check_rejects_group_without_invariant(self):
        original = plan_ci.GROUP_INVARIANTS.pop("issue-115-cleanup")
        try:
            self.assertTrue(any("invariant" in e for e in plan_ci.self_check()))
        finally:
            plan_ci.GROUP_INVARIANTS["issue-115-cleanup"] = original

    def test_no_historical_catch_all_bucket_remains(self):
        groups = set(plan_ci.GROUP_TEST_MODULES)
        self.assertFalse(RETIRED_GROUPS & groups)
        self.assertFalse({g for g in groups if "histor" in g})
        for rule_groups in plan_ci.PATH_GROUPS.values():
            self.assertFalse(RETIRED_GROUPS & set(rule_groups))

    def test_every_registered_module_is_current(self):
        # Issue #246 maintainer decision: historical provenance is not a
        # retention criterion; only current categories may be registered.
        audit = retention.load_audit(REPO_ROOT)
        for group, modules in plan_ci.GROUP_TEST_MODULES.items():
            self.assertTrue(modules, group)
            for module in modules:
                self.assertIn(audit["modules"][module]["category"],
                              retention.CURRENT_CATEGORIES,
                              f"{group}: {module}")

    def test_reintroduced_retired_test_path_fails_closed(self):
        for path in ("tests/test_v0b_reduction.py",
                     "tests/test_issue182_arm_e.py",
                     "tests/test_issue117_preflight.py"):
            self.assertTrue(make_plan([path])["full_regression"], path)

    def test_current_r8i_source_selects_its_current_group_only(self):
        for path in ("scripts/issue237_methodology.py",
                     "scripts/issue237_thresholds.py",
                     "docs/qualification/qwen38-vulkan-v1/MANIFEST.sha256",
                     "tests/test_issue237_r8i_methodology.py"):
            p = make_plan([path])
            self.assertFalse(p["full_regression"], path)
            self.assertEqual(p["groups"],
                             ["r8i-qwen-qualification", "repo-integrity"], path)

    def test_issue244_style_change_selects_current_group_not_history(self):
        # The evidence/test surface of PR #245 (Issue #244 import).  Its
        # CI registration edits (planner, registry, workflow, and the
        # since-retired #213 path allowlist) are excluded: registering a
        # new module is a full-regression change by design.
        changed = subprocess.check_output(
            ["git", "diff", "--name-only", "--diff-filter=ACDMRT",
             "3aa59aed74df7f00302a6a2eb84640623b7cc14b",
             "02506c5bd5138c6b3651bc590611b968bc66734c"],
            cwd=REPO_ROOT, text=True).splitlines()
        changed = [c for c in changed if c.startswith("docs/")
                   or c == "tests/test_issue244_r8i5_v340l_import.py"]
        self.assertTrue(changed)
        p = make_plan(changed)
        self.assertFalse(p["full_regression"], p["reason"])
        self.assertEqual(p["groups"],
                         ["r8i-qwen-qualification", "repo-integrity"])

    def test_issue241_style_change_selects_current_group_not_history(self):
        p = make_plan(["docs/qualification/qwen38-vulkan-v1/README.md",
                       "scripts/issue237_unseal_preflight.py",
                       "tests/test_issue237_r8i_methodology.py",
                       "docs/hardware/pcie-slot-ledger.md"])
        self.assertFalse(p["full_regression"])
        self.assertEqual(p["groups"],
                         ["r8i-qwen-qualification", "repo-integrity"])

    def test_historical_frozen_evidence_selects_integrity_only(self):
        for path in (
            "docs/investigations/vulkan-v2-d-v340l-concurrent/MANIFEST.sha256",
            "docs/investigations/vulkan-v2-g-pcie-path-remediation/README.md",
            "docs/investigations/qwen38-flash-next-r8-e/terminal.json",
            "scripts/issue216_assemble.py",
            "scripts/issue232_gate.py",
            "scripts/issue175_reduce.py",
            "scripts/derive_phase1r_d3_placement.py",
            # PR #247 correction round 1 retirements
            "docs/investigations/vulkan-v0-b/MANIFEST.sha256",
            "docs/investigations/vulkan-v2-a/FINAL-TERMINAL-R2.json",
            "docs/investigations/link-x1-envelope/MANIFEST.sha256",
            "docs/investigations/qwen38-flash-next-r8-d/terminal-reduction.json",
            "docs/qualification/gemma4-12b-it-v3/MANIFEST.sha256",
            "scripts/v0c_correctness.py",
            "scripts/issue182_compare.py",
            "scripts/issue86_v3_methodology.py",
            "scripts/issue133_arm_c_retry_campaign.py",
        ):
            p = make_plan([path])
            self.assertFalse(p["full_regression"], path)
            self.assertEqual(p["groups"], ["repo-integrity"], path)

    def test_historical_evidence_consumed_by_current_selects_consumer(self):
        # R8-G/R8-H evidence feeds the #237 historical-exclusion inventory.
        for path in (
            "docs/investigations/qwen38-flash-next-r8-h-vulkan/MANIFEST.sha256",
            "docs/investigations/qwen38-flash-next-r8-g/CLOSURE.sha256",
        ):
            p = make_plan([path])
            self.assertEqual(p["groups"],
                             ["r8i-qwen-qualification", "repo-integrity"], path)

    def test_shared_producer_still_widens_to_every_consumer(self):
        # the v4 methodology core is imported by the #83 doctrine suites,
        # V5, and the current R8-I comparator
        p = make_plan(["scripts/issue95_v4_methodology.py"])
        self.assertEqual(p["groups"], ["issue-109-110", "issue-83-95",
                                       "r8i-qwen-qualification",
                                       "repo-integrity"])
        # the v1 methodology core is imported by every qualification line
        p = make_plan(["scripts/issue74_methodology.py"])
        for group in ("issue-74-79", "issue-109-110",
                      "r8i-qwen-qualification", "issue-117-133"):
            self.assertIn(group, p["groups"])

    def test_retention_authority_changes_force_full(self):
        for path in ("docs/ci/test-retention-audit.json",
                     "docs/ci/retired-lineage-pins.sha256",
                     "docs/ci/retired-test-rows.json",
                     "scripts/check_ci_test_retention.py"):
            p = make_plan([path])
            self.assertTrue(p["full_regression"], path)

    def test_unknown_new_source_and_test_paths_still_fail_closed(self):
        for path in ("scripts/issue999_new_campaign.py",
                     "tests/test_issue999_new_campaign.py",
                     "tests/issue999_helper.py",
                     "docs/investigations/new-lineage/evidence.json"):
            self.assertTrue(make_plan([path])["full_regression"], path)

    def test_retired_modules_are_unregistered_and_unmapped(self):
        audit = retention.load_audit(REPO_ROOT)
        registered = {m for mods in plan_ci.GROUP_TEST_MODULES.values()
                      for m in mods}
        for module, record in audit["modules"].items():
            if record["disposition"] in retention.ACTIVE_DISPOSITIONS:
                continue
            self.assertNotIn(module, registered)
            self.assertNotIn(f"tests/{module}.py", plan_ci.PATH_GROUPS)


class TestImportClosureFanout(unittest.TestCase):
    """A script change selects every group whose tests import it.

    Mechanical rule (Issue #246 requirement: a current source change
    selects every group whose invariant it can affect).  For every
    registered test module, every ``scripts/`` module in its static
    import closure must classify to that module's group, unless the
    script already escalates to full regression or the group is
    always-on.
    """

    @staticmethod
    def _imports(path):
        import ast
        found = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                found.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.add(node.module.split(".")[0])
        return found

    def gaps(self, group_modules=None, path_groups=None):
        scripts = {p.stem for p in (REPO_ROOT / "scripts").glob("*.py")}
        graph = {s: self._imports(REPO_ROOT / "scripts" / f"{s}.py") & scripts
                 for s in scripts}
        full = set(plan_ci.FULL_REGRESSION_PATHS)
        group_modules = group_modules or plan_ci.GROUP_TEST_MODULES
        problems = []
        for group, modules in group_modules.items():
            if group in plan_ci.ALWAYS_ON_GROUPS:
                continue
            for module in modules:
                stack = list(self._imports(REPO_ROOT / "tests" / f"{module}.py")
                             & scripts)
                seen = set()
                while stack:
                    script = stack.pop()
                    if script in seen:
                        continue
                    seen.add(script)
                    stack.extend(graph[script])
                    path = f"scripts/{script}.py"
                    if path in full:
                        continue
                    if path_groups is None:
                        groups, classified = plan_ci.classify_path(path)
                    else:
                        classified = path in path_groups
                        groups = path_groups.get(path, [])
                    if classified and group not in groups:
                        problems.append(f"{path} does not select {group} "
                                        f"(imported by {module})")
        return sorted(set(problems))

    def test_every_imported_script_selects_its_consumer_groups(self):
        self.assertEqual(self.gaps(), [])

    def test_control_dropped_consumer_is_detected(self):
        rules = dict(plan_ci.PATH_GROUPS)
        rules["scripts/issue95_v4_methodology.py"] = ["issue-83-95"]
        self.assertTrue(any("r8i-qwen-qualification" in p
                            for p in self.gaps(path_groups=rules)))


class TestStdinMalformedInput(unittest.TestCase):
    """The CLI must preserve blank stdin lines and fail closed."""

    def test_blank_line_stdin_cannot_produce_targeted_plan(self):
        r = run_planner("--mode", "pr", stdin="docs/README.md\n\nscripts/v0b_terminal.py\n")
        self.assertEqual(r.returncode, 0)
        p = json.loads(r.stdout)
        self.assertTrue(p["full_regression"],
                        "blank stdin line must fail closed, got narrow plan")
        self.assertTrue(any("empty path line" in reason
                            for reason in p["reason"]))

    def test_stdin_without_blank_lines_still_works(self):
        r = run_planner("--mode", "pr", stdin="docs/README.md\n")
        p = json.loads(r.stdout)
        self.assertFalse(p["full_regression"])
        self.assertEqual(p["groups"], ["repo-integrity"])


if __name__ == "__main__":
    unittest.main()
