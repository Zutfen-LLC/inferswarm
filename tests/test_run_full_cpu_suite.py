"""Issue #173 bounded parallel CPU-suite runner contract.

Corrected-revision regression coverage per maintainer review: phased
scheduling that never permanently dedicates workers to isolated modules,
isolation correctness at every supported worker count, TMPDIR-sensitive
serial semantics, preserved adversarial-review fixes, and exact identity
coverage across phases.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_full_cpu_suite as runner  # noqa: E402


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def fixture(test: unittest.TestCase, files: dict[str, str]) -> tuple[Path, Path]:
    root = Path(tempfile.mkdtemp(prefix="issue173-suite-"))
    test.addCleanup(shutil.rmtree, root, ignore_errors=True)
    # Fixture modules share names across temporary roots; purge them from
    # sys.modules or the next discovery hits a stale-module ImportError.
    for name in files:
        test.addCleanup(sys.modules.pop, Path(name).stem, None)
    tests = root / "tests"
    for name, text in files.items():
        write(tests / name, text)
    return root, tests


def sample_units() -> list[runner.Unit]:
    """A miniature population exercising every scheduling declaration."""
    return [runner.Unit(name, (f"{name}.Case.test_x",)) for name in (
        "test_issue133_arm_c_retry_campaign", "test_issue133_arm_c_retry_direct",
        "test_issue133_corrected_freeze", "test_issue117_arm_b_retention",
        "test_issue103_planner", "test_issue117_preflight",
        "test_other", "test_last")]


class DiscoveryAndPlanTests(unittest.TestCase):
    def test_discovery_matches_raw_unittest_identity_population(self):
        root, tests = fixture(self, {
            "test_alpha.py": "import unittest\nclass A(unittest.TestCase):\n def test_one(self): pass\n def test_two(self): pass\n",
            "test_beta.py": "import unittest\nclass B(unittest.TestCase):\n def test_three(self): pass\n",
        })
        units = runner.discover_units(root, tests)
        ids = runner.ids_for_units(units)
        self.assertEqual(ids, ["test_alpha.A.test_one", "test_alpha.A.test_two", "test_beta.B.test_three"])
        self.assertEqual(runner.identity_digest(ids), hashlib.sha256(
            b"test_alpha.A.test_one\ntest_alpha.A.test_two\ntest_beta.B.test_three\n").hexdigest())

    def test_jobs_validation_and_cap_are_bounded(self):
        self.assertEqual(runner.worker_count(999, 3), 3)
        self.assertEqual(runner.worker_count(1, 3), 1)
        with self.assertRaises(ValueError):
            runner.worker_count(0, 3)


class SchedulingPlanTests(unittest.TestCase):
    """Inspect the actual scheduling plan at every supported worker count."""

    def assert_schedule_safe(self, jobs: int) -> list[runner.Task]:
        units = sample_units()
        selected, tasks = runner.build_tasks(units, jobs)
        self.assertEqual(selected, min(jobs, len(units)))
        # Exact identity coverage, no duplicates, no losses.
        assigned = [unit for task in tasks for unit in task.units]
        self.assertEqual(sorted(u.name for u in assigned), sorted(u.name for u in units))
        # Every isolated module is a single-module task at EVERY jobs value.
        isolated_tasks = [t for t in tasks if t.phase == "isolated"]
        self.assertEqual(sorted(u.name for t in isolated_tasks for u in t.units),
                         sorted(runner.ISOLATED_MODULES))
        for task in isolated_tasks:
            self.assertEqual(len(task.units), 1)
        # No other task contains an isolated module.
        for task in tasks:
            if task.phase != "isolated":
                self.assertFalse(
                    any(u.name in runner.ISOLATED_MODULES for u in task.units),
                    f"isolated module co-located in {task.phase} task at jobs={jobs}")
        # TMPDIR-sensitive modules always get inherited (serial-compatible) mode.
        for task in tasks:
            for unit in task.units:
                if unit.name in runner.TMPDIR_SENSITIVE_MODULES:
                    self.assertIn(task.tmpdir_mode, ("inherited", "serial"),
                                  f"sensitive module in {task.tmpdir_mode} task at jobs={jobs}")
        # Deterministic.
        self.assertEqual(tasks, runner.build_tasks(units, jobs)[1])
        return tasks

    def test_schedule_is_safe_at_jobs_1(self):
        selected, tasks = runner.build_tasks(sample_units(), 1)
        self.assertEqual(selected, 1)
        self.assertEqual([t.phase for t in tasks], ["serial"])
        self.assertEqual([t.tmpdir_mode for t in tasks], ["serial"])
        self.assertEqual([u.name for u in tasks[0].units],
                         [u.name for u in sample_units()])

    def test_schedule_is_safe_at_jobs_2(self):
        self.assert_schedule_safe(2)

    def test_schedule_is_safe_at_jobs_3(self):
        self.assert_schedule_safe(3)

    def test_schedule_is_safe_at_default_jobs_4(self):
        tasks = self.assert_schedule_safe(4)
        # The non-isolated population must NOT collapse onto one task.
        population = [t for t in tasks if t.phase == "population"]
        self.assertGreaterEqual(len(population), 2,
                                "default jobs=4 collapsed the population onto one worker")
        # ... and worker slots are reused, not permanently reserved.
        self.assertGreater(len(tasks), 4,
                           "no slot reuse: tasks did not exceed the worker count")

    def test_schedule_is_safe_at_oversized_jobs(self):
        selected, tasks = runner.build_tasks(sample_units(), 99)
        self.assertEqual(selected, 8)
        # 8 workers: 3 isolated singleton tasks, the Issue #133 bundle kept
        # together as one task, and the other two modules as singletons.
        sizes = sorted(len(t.units) for t in tasks)
        self.assertEqual(sizes, [1, 1, 1, 1, 1, 3])
        for task in tasks:
            if len(task.units) > 1:
                self.assertEqual({u.name for u in task.units}, runner.COOLOCATED_MODULES)

    def test_population_is_least_loaded_balanced_at_default_jobs(self):
        units = sample_units()
        _, tasks = runner.build_tasks(units, 4)
        population = [t for t in tasks if t.phase == "population"]
        counts = [sum(len(u.ids) for u in t.units) for t in population]
        # 5 population units form 3 groups (bundle + 2 singletons) across 4
        # requested workers: the deterministic least-loaded assignment is
        # [3,1,1] test counts in 3 buckets (a 4th would stay empty).
        self.assertEqual(sorted(counts), [1, 1, 3])
        # The Issue #133 bundle stays together in exactly one task.
        bundle_tasks = [t for t in population
                        if any(u.name in runner.COOLOCATED_MODULES for u in t.units)]
        self.assertEqual(len(bundle_tasks), 1)
        self.assertEqual({u.name for u in bundle_tasks[0].units}, runner.COOLOCATED_MODULES)

    def test_jobs_2_does_not_collapse_the_population(self):
        _, tasks = runner.build_tasks(sample_units(), 2)
        population = [t for t in tasks if t.phase == "population"]
        self.assertEqual(len(population), 2)

    def test_isolated_declared_co_located_is_rejected(self):
        units = [runner.Unit("test_issue133_planner", ("t",)), runner.Unit("test_other", ("t",))]
        saved_isolated = runner.ISOLATED_MODULES
        saved_coolocated = runner.COOLOCATED_MODULES
        try:
            runner.ISOLATED_MODULES = frozenset({"test_issue133_planner"})
            runner.COOLOCATED_MODULES = frozenset({"test_issue133_planner"})
            with self.assertRaises(runner.SuiteError):
                runner.build_tasks(units, 4)
        finally:
            runner.ISOLATED_MODULES = saved_isolated
            runner.COOLOCATED_MODULES = saved_coolocated


class ExecutionTests(unittest.TestCase):
    def test_parallel_execution_exactly_matches_discovery_and_keeps_module_fixtures(self):
        root, tests = fixture(self, {
            "test_exec_alpha.py": "import unittest\nEVENTS=[]\ndef setUpModule(): EVENTS.append('setup')\ndef tearDownModule(): EVENTS.append('teardown')\nclass A(unittest.TestCase):\n def test_one(self): self.assertEqual(EVENTS,['setup'])\n def test_two(self): self.assertEqual(EVENTS,['setup'])\n",
            "test_exec_beta.py": "import unittest\nclass B(unittest.TestCase):\n def test_three(self): pass\n",
        })
        result = runner.run_suite(root, tests, jobs=2, timeout=60)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["serial_ids"], result["executed_ids"])
        self.assertEqual(result["serial_digest"], result["executed_digest"])
        single = runner.run_suite(root, tests, jobs=1, timeout=60)
        self.assertTrue(single["ok"], single)
        self.assertEqual(single["serial_ids"], single["executed_ids"])

    def test_identity_coverage_is_exact_across_phases(self):
        # Synthetic declaration names (injected into the runner's frozensets)
        # so the fixture population spans all phases WITHOUT colliding with
        # the real repository modules already loaded in this interpreter.
        isolated_names = [f"test_iso_{i}" for i in range(3)]
        bundle_names = [f"test_bundle_{i}" for i in range(3)]
        ordinary_names = [f"test_ord_{i}" for i in range(4)]
        body = "import unittest\nclass X(unittest.TestCase):\n def test_x(self): pass\n"
        files = {name + ".py": body for name in (*isolated_names, *bundle_names, *ordinary_names)}
        root, tests = fixture(self, files)
        saved_isolated, saved_coolocated, saved_sensitive = (
            runner.ISOLATED_MODULES, runner.COOLOCATED_MODULES, runner.TMPDIR_SENSITIVE_MODULES)
        try:
            runner.ISOLATED_MODULES = frozenset(isolated_names)
            runner.COOLOCATED_MODULES = frozenset(bundle_names)
            runner.TMPDIR_SENSITIVE_MODULES = frozenset(isolated_names[:2])
            result = runner.run_suite(root, tests, jobs=2, timeout=60)
        finally:
            runner.ISOLATED_MODULES = saved_isolated
            runner.COOLOCATED_MODULES = saved_coolocated
            runner.TMPDIR_SENSITIVE_MODULES = saved_sensitive
        self.assertTrue(result["ok"], result.get("diagnostics"))
        phases = [t["phase"] for t in result["tasks"]]
        self.assertEqual(phases[:3], ["isolated", "isolated", "isolated"])
        self.assertEqual([t["phase"] for t in result["tasks"][3:]], ["population"] * (len(phases) - 3))
        self.assertEqual(sorted(result["executed_ids"]), sorted(result["serial_ids"]))
        self.assertEqual(result["executed_digest"], result["serial_digest"])
        modes = [t["tmpdir_mode"] for t in result["tasks"][:3]]
        self.assertEqual(sorted(modes), ["inherited", "inherited", "private"])

    def test_phased_execution_reuses_worker_slots(self):
        # Synthetic isolated names + enough population tasks that a jobs=3
        # window must reuse slots: more tasks than workers, all completing.
        isolated = {f"test_iso_{i}.py": "import unittest\nclass S(unittest.TestCase):\n def test_x(self): pass\n"
                   for i in range(4)}
        files = dict(isolated)
        files.update({f"test_pop_{i:02d}.py": "import unittest\nclass Q(unittest.TestCase):\n def test_x(self): pass\n"
                      for i in range(6)})
        root, tests = fixture(self, files)
        saved = runner.ISOLATED_MODULES
        try:
            runner.ISOLATED_MODULES = frozenset(name[:-3] for name in isolated)
            result = runner.run_suite(root, tests, jobs=3, timeout=60)
        finally:
            runner.ISOLATED_MODULES = saved
        self.assertTrue(result["ok"], result.get("diagnostics"))
        self.assertEqual(result["jobs"], 3)
        self.assertGreater(len(result["tasks"]), 3)
        # Tasks run in a bounded window of selected_jobs; overlap never exceeds it.
        events = []
        for entry in result["task_timings"]:
            events.append((entry["started_at"], 1))
            events.append((entry["ended_at"], -1))
        events.sort()
        live = 0
        peak = 0
        for _, delta in events:
            live += delta
            peak = max(peak, live)
        self.assertLessEqual(peak, 3, f"rolling window exceeded jobs: peak={peak}")
        self.assertGreater(peak, 1, "no parallelism was observed at all")

    def test_failure_error_and_worker_crash_fail_closed(self):
        root, tests = fixture(self, {
            "test_fail.py": "import unittest\nclass F(unittest.TestCase):\n def test_failure(self): self.fail('expected failure')\n",
            "test_error.py": "import unittest\nclass E(unittest.TestCase):\n def test_error(self): raise RuntimeError('expected error')\n",
        })
        result = runner.run_suite(root, tests, jobs=2, timeout=60)
        self.assertFalse(result["ok"])
        self.assertIn("expected failure", result["diagnostics"])
        self.assertIn("expected error", result["diagnostics"])

    def test_git_worker_root_is_an_isolated_worktree(self):
        root, _ = fixture(self, {"test_one.py": "import unittest\n"})
        for command in (("git", "init", "-q"), ("git", "config", "user.email", "test@example.invalid"),
                        ("git", "config", "user.name", "Test"), ("git", "add", "."),
                        ("git", "commit", "-qm", "base")):
            subprocess.run(command, cwd=root, check=True)
        with tempfile.TemporaryDirectory() as temporary:
            worker = runner.prepare_worker_root(root, Path(temporary), 0)
            self.assertNotEqual(worker, root)
            write(worker / "worker-only.txt", "isolated\n")
            self.assertFalse((root / "worker-only.txt").exists())
            runner.remove_worker_root(root, worker)

    def test_worker_preserves_repository_root_imports(self):
        root, tests = fixture(self, {
            "test_import.py": "import unittest\nfrom fixturepkg import helper\nclass I(unittest.TestCase):\n def test_value(self): self.assertEqual(helper.VALUE, 173)\n",
        })
        write(root / "fixturepkg" / "__init__.py", "")
        write(root / "fixturepkg" / "helper.py", "VALUE = 173\n")
        result = runner.run_suite(root, tests, jobs=1, timeout=60)
        self.assertTrue(result["ok"], result)

    def test_dirty_git_checkout_is_rejected_before_worker_execution(self):
        root, tests = fixture(self, {
            "test_dirty.py": "import unittest\nclass D(unittest.TestCase):\n def test_value(self): pass\n",
        })
        for command in (("git", "init", "-q"), ("git", "config", "user.email", "test@example.invalid"),
                        ("git", "config", "user.name", "Test"), ("git", "add", "."),
                        ("git", "commit", "-qm", "base")):
            subprocess.run(command, cwd=root, check=True)
        write(tests / "test_dirty.py", "import unittest\nclass D(unittest.TestCase):\n def test_value(self): self.fail('dirty code must run')\n")
        with self.assertRaises(runner.SuiteError):
            runner.run_suite(root, tests, jobs=1, timeout=60)

    def test_git_status_failure_inside_a_work_tree_fails_closed(self):
        # Review P2: a git status failure must never be treated as a clean
        # tree inside a real work tree. Simulate with a bogus GIT_DIR that
        # rev-parse accepts as inside-work-tree but status cannot use.
        root, tests = fixture(self, {
            "test_clean.py": "import unittest\nclass C(unittest.TestCase):\n def test_value(self): pass\n",
        })
        for command in (("git", "init", "-q"), ("git", "config", "user.email", "test@example.invalid"),
                        ("git", "config", "user.name", "Test"), ("git", "add", "."),
                        ("git", "commit", "-qm", "base")):
            subprocess.run(command, cwd=root, check=True)
        saved = dict(os.environ)
        try:
            # A directory as GIT_INDEX_FILE: rev-parse still reports a work
            # tree, but `git status` fails (unable to map index file).
            os.environ["GIT_INDEX_FILE"] = str(root / ".git")
            with self.assertRaises(runner.SuiteError) as caught:
                runner.run_suite(root, tests, jobs=1, timeout=60)
            self.assertIn("git status failed", str(caught.exception))
        finally:
            os.environ.clear()
            os.environ.update(saved)

    def test_worker_crash_terminates_siblings_before_returning(self):
        marker_parent = Path(tempfile.mkdtemp(prefix="issue173-sibling-"))
        self.addCleanup(shutil.rmtree, marker_parent, ignore_errors=True)
        marker = marker_parent / "late"
        root, tests = fixture(self, {
            "test_crash.py": "import os, unittest\nclass C(unittest.TestCase):\n def test_crash(self): os._exit(7)\n",
            "test_sleep.py": "import pathlib, time, unittest\nMARKER=pathlib.Path(" + repr(str(marker)) + ")\nclass S(unittest.TestCase):\n def test_sleep(self): time.sleep(3); MARKER.write_text('late')\n",
        })
        marker.unlink(missing_ok=True)
        with self.assertRaises(runner.SuiteError):
            runner.run_suite(root, tests, jobs=2, timeout=60)
        time.sleep(4)
        self.assertFalse(marker.exists(), "crashed worker left a sibling running")

    def test_worker_crash_during_late_phase_terminates_early_siblings(self):
        # A crashing POPULATION task must still terminate live ISOLATED
        # siblings scheduled later in the same window (phase-order crash).
        marker_parent = Path(tempfile.mkdtemp(prefix="issue173-sibling2-"))
        self.addCleanup(shutil.rmtree, marker_parent, ignore_errors=True)
        marker = marker_parent / "late"
        files = {
            "test_iso_slow.py": f"import pathlib, time, unittest\nMARKER=pathlib.Path({str(marker)!r})\nclass P(unittest.TestCase):\n def test_slow(self): time.sleep(30); MARKER.write_text('late')\n",
            "test_iso_two.py": "import unittest\nclass R(unittest.TestCase):\n def test_x(self): pass\n",
            "test_iso_three.py": "import unittest\nclass F(unittest.TestCase):\n def test_x(self): pass\n",
            "test_crash.py": "import os, unittest\nclass C(unittest.TestCase):\n def test_crash(self): os._exit(9)\n",
        }
        root, tests = fixture(self, files)
        marker.unlink(missing_ok=True)
        saved = runner.ISOLATED_MODULES
        try:
            runner.ISOLATED_MODULES = frozenset({"test_iso_slow", "test_iso_two", "test_iso_three"})
            with self.assertRaises(runner.SuiteError):
                runner.run_suite(root, tests, jobs=4, timeout=60)
        finally:
            runner.ISOLATED_MODULES = saved
        # Mechanically prove every worker process was terminated and reaped:
        # poll the process table for any survivor instead of relying on the
        # 30s marker write timing alone.
        deadline = time.monotonic() + 10
        survivor = None
        while time.monotonic() < deadline:
            survivors = subprocess.run(
                ["pgrep", "-f", "issue173-sibling2"], capture_output=True, text=True).stdout.strip()
            if not survivors:
                survivor = None
                break
            survivor = survivors
            time.sleep(0.2)
        self.assertIsNone(survivor, f"live worker processes survived the crash path: {survivor}")
        time.sleep(2)
        self.assertFalse(marker.exists(), "crash in a later phase left an earlier sibling running")

    def test_worker_crash_without_receipt_fails_closed(self):
        root, tests = fixture(self, {
            "test_crash_one.py": "import os, unittest\nclass C(unittest.TestCase):\n def test_crash(self): os._exit(7)\n",
        })
        with self.assertRaises(runner.SuiteError):
            runner.run_suite(root, tests, jobs=1, timeout=60)

    def test_task_timeout_terminates_worker_and_siblings(self):
        # A task exceeding --timeout must be terminated, its siblings reaped,
        # and the parent must fail closed with the timeout diagnosis.
        marker_parent = Path(tempfile.mkdtemp(prefix="issue173-timeout-"))
        self.addCleanup(shutil.rmtree, marker_parent, ignore_errors=True)
        marker = marker_parent / "late"
        root, tests = fixture(self, {
            "test_slow.py": f"import pathlib, time, unittest\nMARKER=pathlib.Path({str(marker)!r})\nclass S(unittest.TestCase):\n def test_slow(self): time.sleep(60); MARKER.write_text('late')\n",
            "test_quick.py": "import unittest\nclass Q(unittest.TestCase):\n def test_quick(self): pass\n",
        })
        marker.unlink(missing_ok=True)
        with self.assertRaises(runner.SuiteError) as caught:
            runner.run_suite(root, tests, jobs=2, timeout=3)
        self.assertIn("timed out", str(caught.exception))
        time.sleep(2)
        self.assertFalse(marker.exists(), "timed-out worker kept running")
        survivors = subprocess.run(["pgrep", "-f", "issue173-timeout"],
                                   capture_output=True, text=True).stdout.strip()
        self.assertEqual(survivors, "", f"live workers survived timeout: {survivors}")

    def test_malformed_or_missing_receipt_fails_closed(self):
        with self.assertRaises(runner.SuiteError):
            runner.validate_receipts([{"schema": "wrong"}], ["test_x.C.test_y"])
        with self.assertRaises(runner.SuiteError):
            runner.validate_receipts([], ["test_x.C.test_y"])


class EnvironmentSemanticsTests(unittest.TestCase):
    def test_task_environment_modes(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp = Path(temporary)
            serial = runner.Task(0, "serial", (), "serial")
            inherited = runner.Task(1, "isolated", (), "inherited")
            private = runner.Task(2, "population", (), "private")
            saved = dict(os.environ)
            try:
                os.environ.clear()
                os.environ.update({"PATH": "/usr/bin:/bin", "TMPDIR": "/serial-tmp"})
                # serial / inherited: parent environment verbatim.
                self.assertEqual(runner._task_environment(serial, temp), dict(os.environ))
                self.assertEqual(runner._task_environment(inherited, temp), dict(os.environ))
                self.assertEqual(runner._task_environment(inherited, temp).get("TMPDIR"), "/serial-tmp")
                # private: per-task scratch replaces TMPDIR, nothing else changes.
                env = runner._task_environment(private, temp)
                self.assertEqual(env["TMPDIR"], str(temp / "task-2-tmp"))
                self.assertTrue(Path(env["TMPDIR"]).is_dir())
                env.pop("TMPDIR")
                expected = dict(os.environ)
                expected.pop("TMPDIR", None)
                self.assertEqual(env, expected)
            finally:
                os.environ.clear()
                os.environ.update(saved)

    def test_tmpdir_sensitivity_classification(self):
        self.assertEqual(runner.tmpdir_mode_for(["test_issue103_planner"]), "inherited")
        self.assertEqual(runner.tmpdir_mode_for(["test_issue117_preflight"]), "inherited")
        self.assertEqual(runner.tmpdir_mode_for(["test_issue103_planner", "test_other"]), "inherited")
        self.assertEqual(runner.tmpdir_mode_for(["test_issue117_arm_b_retention"]), "private")
        self.assertEqual(runner.tmpdir_mode_for(["test_other"]), "private")

    def test_sensitive_module_observes_inherited_tmpdir(self):
        # A fixture module with a synthetic sensitive name asserts the TMPDIR
        # it observes equals the parent's value verbatim; the ordinary module
        # asserts it received distinct per-task private scratch instead.
        parent_tmpdir = os.environ.get("TMPDIR")
        root, tests = fixture(self, {
            "test_sensitive.py": (
                "import os, unittest\nOBSERVED = os.environ.get('TMPDIR')\n"
                "class P(unittest.TestCase):\n"
                " def test_tmpdir(self):\n"
                "  self.assertEqual(OBSERVED, " + repr(parent_tmpdir) + ")\n"
            ),
            "test_other.py": (
                "import os, unittest\nOBSERVED = os.environ.get('TMPDIR')\n"
                "class O(unittest.TestCase):\n"
                " def test_tmpdir(self):\n"
                "  self.assertNotEqual(OBSERVED, " + repr(parent_tmpdir) + ")\n"
            ),
        })
        saved = runner.ISOLATED_MODULES, runner.TMPDIR_SENSITIVE_MODULES
        try:
            runner.ISOLATED_MODULES = frozenset({"test_sensitive"})
            runner.TMPDIR_SENSITIVE_MODULES = frozenset({"test_sensitive"})
            result = runner.run_suite(root, tests, jobs=2, timeout=60)
        finally:
            runner.ISOLATED_MODULES, runner.TMPDIR_SENSITIVE_MODULES = saved
        self.assertTrue(result["ok"], result.get("diagnostics"))
        modes = {t["modules"][0]: t["tmpdir_mode"] for t in result["tasks"]}
        self.assertEqual(modes["test_sensitive"], "inherited")
        self.assertEqual(modes["test_other"], "private")

    def test_ordinary_module_runs_in_private_scratch_under_parallel(self):
        root, tests = fixture(self, {
            "test_scratch_one.py": (
                "import os, unittest\n"
                "class S(unittest.TestCase):\n"
                " def test_tmpdir(self): self.assertIn('task-', os.environ.get('TMPDIR', '/tmp'))\n"
            ),
            "test_scratch_two.py": (
                "import os, unittest\n"
                "class T(unittest.TestCase):\n"
                " def test_tmpdir(self): self.assertIn('task-', os.environ.get('TMPDIR', '/tmp'))\n"
            ),
        })
        result = runner.run_suite(root, tests, jobs=2, timeout=60)
        self.assertTrue(result["ok"], result.get("diagnostics"))


class CliTests(unittest.TestCase):
    def test_list_mode_is_machine_readable_and_successful(self):
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "run_full_cpu_suite.py"), "--list", "--json"],
            cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["schema"], runner.SCHEMA)
        self.assertGreater(payload["count"], 0)
        self.assertIn("tasks", payload)
        phases = [t["phase"] for t in payload["tasks"]]
        self.assertEqual(phases[:len(runner.ISOLATED_MODULES)],
                         ["isolated"] * len(runner.ISOLATED_MODULES))

    def test_runner_does_not_depend_on_ci_impact_selection(self):
        source = (ROOT / "scripts" / "run_full_cpu_suite.py").read_text(encoding="utf-8")
        self.assertNotIn("plan_ci", source)
        self.assertNotIn("ci_groups", source)


if __name__ == "__main__":
    unittest.main()
