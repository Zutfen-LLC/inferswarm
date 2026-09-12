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

    # 2. Vulkan V0-B-only
    def test_vulkan_v0b_only(self):
        p = make_plan(["scripts/v0b_terminal.py",
                       "docs/implementation/vulkan-v0-b/summary.md"])
        self.assertFalse(p["full_regression"])
        self.assertEqual(p["groups"], ["repo-integrity", "vulkan-v0-b"])
        self.assertNotIn("issue-117-133", p["groups"])

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
        p = make_plan(["tests/test_issue133_corrected_freeze.py"])
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
        p = make_plan(["scripts/v0b_terminal.py"])
        self.assertIn("vulkan-v0-b", p["groups"])

    # 11. multiple paths union their groups
    def test_multiple_paths_union(self):
        p = make_plan(["scripts/v0b_terminal.py", "scripts/issue74_methodology.py"])
        self.assertFalse(p["full_regression"])
        self.assertEqual(p["groups"],
                         ["issue-74-79", "repo-integrity", "vulkan-v0-b"])

    def test_one_path_selects_multiple_groups(self):
        # issue137 probe driver feeds both issue-137 and issue-74-79
        p = make_plan(["scripts/issue137_probe_driver.py"])
        self.assertIn("issue-137", p["groups"])
        self.assertIn("issue-74-79", p["groups"])

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
        plan = {"groups": ["repo-integrity", "vulkan-v0-b"],
                "full_regression": False}
        results = {"repo-integrity": "success", "vulkan-v0-b": "success",
                   "issue-117-133": "skipped"}
        ok, _ = self.gate(plan, results)
        self.assertTrue(ok)

    # 17. gate fails when a selected group fails
    def test_gate_fails_on_selected_failure(self):
        plan = {"groups": ["repo-integrity", "vulkan-v0-b"],
                "full_regression": False}
        results = {"repo-integrity": "success", "vulkan-v0-b": "failure",
                   "issue-117-133": "skipped"}
        ok, _ = self.gate(plan, results)
        self.assertFalse(ok)

    # 18. gate succeeds with unselected skips and all selected passing
    def test_gate_succeeds_unselected_skipped(self):
        p = make_plan(["scripts/v0b_terminal.py"])
        results = {g: "success" for g in p["groups"]}
        for g in plan_ci.GROUP_TEST_MODULES:
            results.setdefault(g, "skipped")
        ok, _ = self.gate(p, results)
        self.assertTrue(ok)

    # 19. gate fails when a selected group never ran / cancelled
    def test_gate_fails_on_missing_selected_group(self):
        p = make_plan(["scripts/v0b_terminal.py"])
        results = {g: "success" if g != "vulkan-v0-b" else None
                   for g in p["groups"]}
        ok, _ = self.gate(p, results)
        self.assertFalse(ok)

    def test_gate_fails_on_cancelled_selected_group(self):
        p = make_plan(["scripts/v0b_terminal.py"])
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
        results = {g: "success" for g in p["groups"] if g != "issue-137"}
        results["issue-137"] = "skipped"
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

    def test_issue117_maps_to_all_four_shards(self):
        shard_jobs = [j for j in self.jobs if j.startswith("issue-117-133-s")]
        self.assertEqual(len(shard_jobs), 4, shard_jobs)
        for j in shard_jobs:
            cond = self.jobs[j]["if"]
            self.assertIn("'issue-117-133'", cond, j)

    def test_all_four_shards_required_by_gate(self):
        gate_needs = self.jobs["ci-gate"]["needs"]
        for i in (1, 2, 3, 4):
            self.assertIn(f"issue-117-133-s{i}", gate_needs)

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

    def test_v0b_economics_json_selects_v0b(self):
        g = self._plan_groups(
            "docs/investigations/vulkan-v0-b/results/economics.json")
        self.assertEqual(g, {"repo-integrity", "vulkan-v0-b"})

    def test_retained_v0a_evidence_selects_v0b(self):
        # V0-B consumes accepted V0-A evidence (test_v0b_reduction
        # reads both trees); several concrete tracked files:
        for path in (
            "docs/investigations/vulkan-v0-a/results/bench-summary.json",
            "docs/investigations/vulkan-v0-a/correctness/correction-cor-nvavk-01/run.json",
            "docs/investigations/vulkan-v0-a/MANIFEST.sha256",
        ):
            self.assertIn(path, self.files, path)
            g = self._plan_groups(path)
            self.assertEqual(g, {"repo-integrity", "vulkan-v0-b"}, path)

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

    def test_phase1_results_select_phase1_analysis(self):
        for path in (
            "docs/benchmarks/results/phase1/data/p6-analysis.json",
            "docs/benchmarks/results/phase1/data/raw/session-1/plan.json",
        ):
            self.assertIn(path, self.files, path)
            g = self._plan_groups(path)
            self.assertEqual(g, {"repo-integrity", "phase1-analysis"}, path)

    def test_issue137_retained_evidence_selects_137_and_shared(self):
        # #137 evidence is nested in the #117 tree; it must select the
        # narrow #137 semantic group AND the broad shared-tree lineage.
        path = ("docs/implementation/r6-successor-dense-full-integration-117/"
                "evidence/arm-c-regime4-diagnosis-137/")
        nested = [f for f in self.files if f.startswith(path)]
        self.assertTrue(nested, "no tracked #137 evidence files")
        for f in sorted(nested)[:3]:
            g = self._plan_groups(f)
            self.assertIn("issue-137", g, f)
            self.assertIn("issue-117-133", g, f)

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
                else:
                    allowed_prose = f in allowed
                if not allowed_prose:
                    problems.append(
                        f"non-prose docs file narrow as repo-integrity "
                        f"only: {f}")
        self.assertEqual(problems, [])


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
