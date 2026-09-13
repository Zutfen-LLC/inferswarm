"""Issue #173 bounded parallel CPU-suite runner contract."""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
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
    tests = root / "tests"
    for name, text in files.items():
        write(tests / name, text)
    return root, tests


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

    def test_partition_is_deterministic_complete_and_keeps_required_bundle_together(self):
        units = [runner.Unit(name, (f"{name}.Case.test_x",)) for name in (
            "test_issue133_arm_c_retry_campaign", "test_issue133_arm_c_retry_direct",
            "test_issue133_corrected_freeze", "test_issue117_arm_b_retention", "test_issue103_planner", "test_issue117_preflight", "test_other", "test_last")]
        first = runner.partition_units(units, 4)
        second = runner.partition_units(units, 4)
        self.assertEqual(first, second)
        assigned = [unit.name for bucket in first for unit in bucket]
        self.assertEqual(sorted(assigned), sorted(unit.name for unit in units))
        bundle_workers = {index for index, bucket in enumerate(first) for unit in bucket
                          if unit.name in runner.COOLOCATED_MODULES}
        self.assertEqual(bundle_workers, {next(iter(bundle_workers))})
        isolated = [bucket for bucket in first
                    if any(unit.name in runner.ISOLATED_MODULES for unit in bucket)]
        self.assertEqual([[unit.name for unit in bucket] for bucket in isolated],
                         [["test_issue117_arm_b_retention"], ["test_issue103_planner"],
                          ["test_issue117_preflight"]])

    def test_jobs_validation_and_cap_are_bounded(self):
        self.assertEqual(runner.worker_count(999, 3), 3)
        self.assertEqual(runner.worker_count(1, 3), 1)
        with self.assertRaises(ValueError):
            runner.worker_count(0, 3)


class ExecutionTests(unittest.TestCase):
    def test_parallel_execution_exactly_matches_discovery_and_keeps_module_fixtures(self):
        root, tests = fixture(self, {
            "test_exec_alpha.py": "import unittest\nEVENTS=[]\ndef setUpModule(): EVENTS.append('setup')\ndef tearDownModule(): EVENTS.append('teardown')\nclass A(unittest.TestCase):\n def test_one(self): self.assertEqual(EVENTS,['setup'])\n def test_two(self): self.assertEqual(EVENTS,['setup'])\n",
            "test_exec_beta.py": "import unittest\nclass B(unittest.TestCase):\n def test_three(self): pass\n",
        })
        result = runner.run_suite(root, tests, jobs=2, timeout=30)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["serial_ids"], result["executed_ids"])
        self.assertEqual(result["serial_digest"], result["executed_digest"])
        single = runner.run_suite(root, tests, jobs=1, timeout=30)
        self.assertTrue(single["ok"], single)
        self.assertEqual(single["serial_ids"], single["executed_ids"])

    def test_failure_error_and_worker_crash_fail_closed(self):
        root, tests = fixture(self, {
            "test_fail.py": "import unittest\nclass F(unittest.TestCase):\n def test_failure(self): self.fail('expected failure')\n",
            "test_error.py": "import unittest\nclass E(unittest.TestCase):\n def test_error(self): raise RuntimeError('expected error')\n",
        })
        result = runner.run_suite(root, tests, jobs=2, timeout=30)
        self.assertFalse(result["ok"])
        self.assertIn("expected failure", result["diagnostics"])
        self.assertIn("expected error", result["diagnostics"])

    def test_git_worker_root_is_an_isolated_worktree(self):
        root, _ = fixture(self, {"test_one.py": "import unittest\n"})
        subprocess = __import__("subprocess")
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
        result = runner.run_suite(root, tests, jobs=1, timeout=30)
        self.assertTrue(result["ok"], result)

    def test_dirty_git_checkout_is_rejected_before_worker_execution(self):
        root, tests = fixture(self, {
            "test_dirty.py": "import unittest\nclass D(unittest.TestCase):\n def test_value(self): pass\n",
        })
        subprocess = __import__("subprocess")
        for command in (("git", "init", "-q"), ("git", "config", "user.email", "test@example.invalid"),
                        ("git", "config", "user.name", "Test"), ("git", "add", "."),
                        ("git", "commit", "-qm", "base")):
            subprocess.run(command, cwd=root, check=True)
        write(tests / "test_dirty.py", "import unittest\nclass D(unittest.TestCase):\n def test_value(self): self.fail('dirty code must run')\n")
        with self.assertRaises(runner.SuiteError):
            runner.run_suite(root, tests, jobs=1, timeout=30)

    def test_worker_crash_terminates_siblings_before_returning(self):
        root, tests = fixture(self, {
            "test_crash.py": "import os, unittest\nclass C(unittest.TestCase):\n def test_crash(self): os._exit(7)\n",
            "test_sleep.py": "import pathlib, time, unittest\nMARKER=pathlib.Path(" + repr(str(Path(tempfile.gettempdir()) / "issue173-sibling-marker")) + ")\nclass S(unittest.TestCase):\n def test_sleep(self): time.sleep(3); MARKER.write_text('late')\n",
        })
        marker = Path(tempfile.gettempdir()) / "issue173-sibling-marker"
        marker.unlink(missing_ok=True)
        self.addCleanup(marker.unlink, missing_ok=True)
        with self.assertRaises(runner.SuiteError):
            runner.run_suite(root, tests, jobs=2, timeout=30)
        __import__("time").sleep(4)
        self.assertFalse(marker.exists(), "crashed worker left a sibling running")

    def test_worker_crash_without_receipt_fails_closed(self):
        root, tests = fixture(self, {
            "test_crash_one.py": "import os, unittest\nclass C(unittest.TestCase):\n def test_crash(self): os._exit(7)\n",
        })
        with self.assertRaises(runner.SuiteError):
            runner.run_suite(root, tests, jobs=1, timeout=30)

    def test_malformed_or_missing_receipt_fails_closed(self):
        with self.assertRaises(runner.SuiteError):
            runner.validate_receipts([{"schema": "wrong"}], ["test_x.C.test_y"])
        with self.assertRaises(runner.SuiteError):
            runner.validate_receipts([], ["test_x.C.test_y"])

    def test_list_mode_is_machine_readable_and_successful(self):
        completed = __import__("subprocess").run(
            [sys.executable, str(ROOT / "scripts" / "run_full_cpu_suite.py"), "--list", "--json"],
            cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["schema"], runner.SCHEMA)
        self.assertGreater(payload["count"], 0)

    def test_runner_does_not_depend_on_ci_impact_selection(self):
        source = (ROOT / "scripts" / "run_full_cpu_suite.py").read_text(encoding="utf-8")
        self.assertNotIn("plan_ci", source)
        self.assertNotIn("ci_groups", source)


if __name__ == "__main__":
    unittest.main()
