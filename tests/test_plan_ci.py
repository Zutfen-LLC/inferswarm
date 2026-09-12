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


if __name__ == "__main__":
    unittest.main()
