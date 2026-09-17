#!/usr/bin/env python3
"""Issue #213 — campaign gate ordering / exact-head receipt negative controls.

Focused orchestration tests (pure standard library, no network, no GPU):

1.  review with no code/evidence mutation -> ONE final full-suite execution;
2.  review produces a fix before final validation -> still ONE final
    full-suite execution on the corrected head;
3.  completed receipt + head change -> reuse rejected, fresh run required;
4.  same head but suite identity change -> reuse rejected;
5.  same head/suite but environment authority change -> reuse rejected;
6.  duplicate orchestration request while a suite is running -> attaches
    rather than launching a second process;
7.  completed exact-head receipt reused ONLY on full identity match;
8.  failed/cancelled/incomplete receipt cannot satisfy the gate;
9.  adversarial review alone cannot complete final handoff;
10. pre-review full suite remains possible via an explicit review-critical
    declaration;
11. unknown workflow/gate state fails closed;
12. historical evidence/manifest bytes are not modified (the orchestration
    module writes nothing into docs/; proven by import-surface and
    contract tests).
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import issue213_gate_orchestration as gate  # noqa: E402


def make_receipt(sha="a" * 40, serial="f" * 64, env_hash="e" * 64,
                 result="PASS", started=None, ended=None):
    suite = {
        "runner_schema": "parallel-full-cpu-suite/1",
        "suite_command": [".venv/bin/python",
                          "scripts/run_full_cpu_suite.py", "--json"],
        "serial_digest": serial,
        "executed_digest": serial,
        "count": 2759,
    }
    environment = {rel: env_hash for rel in gate.ENV_AUTHORITY_FILES}
    return {
        "schema": gate.RECEIPT_SCHEMA,
        "git_commit_sha": sha,
        "suite": suite,
        "environment": environment,
        "result": result,
        "count": 2759,
        "started_unix": started if started is not None else 1000.0,
        "ended_unix": ended if ended is not None else 1000.5,
    }


def runner_result(ok=True, serial="f" * 64, count=2759, schema="parallel-full-cpu-suite/1"):
    return {"ok": ok, "schema": schema, "serial_digest": serial,
            "executed_digest": serial, "count": count}


class GatePlanTests(unittest.TestCase):
    """Controls 1, 2, 10, 11 — ordering and fail-closed plan semantics."""

    def test_no_mutation_path_schedules_one_expensive_cycle(self):
        plan = gate.plan_campaign_gates(
            gate.CampaignFlow("issue-X",
                              pre_review=("focused-changed-surface-tests",
                                          "evidence-manifest-checks")),
            review_mutates_head=False)
        full = [g for phase in plan["phases"] for g in phase["gates"]
                if g in gate.REVIEW_CRITICAL_EXCEPTIONS]
        self.assertEqual(full.count("full-cpu-suite"), 1)
        self.assertEqual(full.count("hosted-exact-head-ci"), 1)
        self.assertEqual(plan["expensive_validation_cycles"], 2)

    def test_review_fix_path_still_schedules_one_final_cycle(self):
        # review mutates the head; canonical ordering still schedules the
        # expensive gates exactly once (on the corrected final head).
        plan = gate.plan_campaign_gates(
            gate.CampaignFlow("issue-X"),
            review_mutates_head=True)
        scheduled = [g for phase in plan["phases"] for g in phase["gates"]]
        self.assertEqual(scheduled.count("full-cpu-suite"), 1)
        self.assertEqual(scheduled.count("hosted-exact-head-ci"), 1)
        old = gate.trace_campaign(True, review_mutates_head=True)
        new = gate.trace_campaign(False)
        self.assertEqual(old["total"], 4)
        self.assertEqual(new["total"], 2)

    def test_pre_review_full_suite_possible_via_review_critical_declaration(self):
        flow = gate.CampaignFlow(
            "issue-Y",
            pre_review=("focused-changed-surface-tests",),
            review_critical=("full-cpu-suite",),
        )
        plan = gate.plan_campaign_gates(flow, review_mutates_head=True)
        self.assertIn("full-cpu-suite", plan["phases"][0]["gates"])
        # declared review-critical AND head mutated -> re-run on final head
        self.assertIn("full-cpu-suite", plan["phases"][3]["gates"])
        self.assertEqual(plan["expensive_validation_cycles"], 3)

    def test_unknown_gate_fails_closed(self):
        with self.assertRaises(gate.GateOrderingError):
            gate.CampaignFlow("issue-X", pre_review=("mystery-gate",))
        with self.assertRaises(gate.GateOrderingError):
            gate.CampaignFlow("issue-X", final_head=("full-cpu-suite",
                                                     "mystery-gate"))
        with self.assertRaises(gate.GateOrderingError):
            gate.CampaignFlow("issue-X", review_critical=("mystery-gate",))

    def test_gate_in_both_phases_fails_closed(self):
        with self.assertRaises(gate.GateOrderingError):
            gate.CampaignFlow("issue-X",
                              pre_review=("ci-planner-self-check",),
                              final_head=("ci-planner-self-check",
                                          "full-cpu-suite"))

    def test_review_critical_without_expensive_gate_fails_closed(self):
        # a cheap gate cannot be declared review-critical
        with self.assertRaises(gate.GateOrderingError):
            gate.CampaignFlow("issue-X",
                              review_critical=("ci-planner-self-check",))


class ReceiptTests(unittest.TestCase):
    """Controls 3, 4, 5, 7, 8, 11 — exact-head receipt fail-closed reuse."""

    def test_control3_head_change_rejects_reuse(self):
        receipt = make_receipt(sha="a" * 40)
        request = gate.request_identity(make_receipt(sha="b" * 40))
        decision = gate.reuse_or_rerun(receipt, request)
        self.assertEqual(decision["action"], "run")
        self.assertFalse(gate.validate_receipt(receipt, request))

    def test_control4_suite_config_change_rejects_reuse(self):
        receipt = make_receipt(serial="f" * 64)
        other = make_receipt(serial="0" * 64)
        request = gate.request_identity(other)
        self.assertFalse(gate.validate_receipt(receipt, request))

    def test_control4_count_and_command_are_identity(self):
        receipt = make_receipt()
        mutated = make_receipt()
        mutated["suite"]["count"] = 1
        self.assertFalse(
            gate.validate_receipt(receipt, gate.request_identity(mutated)))
        mutated2 = make_receipt()
        mutated2["suite"]["suite_command"] = ["python", "other.py"]
        self.assertFalse(
            gate.validate_receipt(receipt, gate.request_identity(mutated2)))

    def test_control5_environment_change_rejects_reuse(self):
        receipt = make_receipt(env_hash="e" * 64)
        other = make_receipt(env_hash="d" * 64)
        request = gate.request_identity(other)
        self.assertFalse(gate.validate_receipt(receipt, request))
        # removing one authority file from the identity is drift too
        dropped = make_receipt()
        dropped["environment"].pop("requirements-test.txt")
        self.assertFalse(
            gate.validate_receipt(receipt, gate.request_identity(dropped)))

    def test_control7_full_match_reuses(self):
        receipt = make_receipt()
        request = gate.request_identity(make_receipt())
        self.assertTrue(gate.validate_receipt(receipt, request))
        self.assertEqual(gate.reuse_or_rerun(receipt, request)["action"],
                         "reuse")
        self.assertEqual(gate.reuse_or_rerun(None, request)["action"], "run")

    def test_control8_failed_cancelled_incomplete_receipts_rejected(self):
        request = gate.request_identity(make_receipt())
        for bad in ("FAIL", "CANCELLED", "INCOMPLETE", None):
            receipt = make_receipt(result=bad)
            with self.assertRaises(gate.GateOrderingError):
                gate.validate_receipt(receipt, request)
            self.assertEqual(
                gate.reuse_or_rerun(receipt, request)["action"], "run")
        # missing result field entirely
        receipt = make_receipt()
        del receipt["result"]
        with self.assertRaises(gate.GateOrderingError):
            gate.validate_receipt(receipt, request)

    def test_malformed_receipt_fails_closed(self):
        request = gate.request_identity(make_receipt())
        for mutate in (
            lambda r: r.update(schema="unknown/9"),
            lambda r: r.update(started_unix=1001.0, ended_unix=1000.0),
            lambda r: r.update(ended_unix=1000.0),
            lambda r: r.pop("suite"),
            lambda r: r.pop("git_commit_sha"),
        ):
            receipt = make_receipt()
            mutate(receipt)
            with self.assertRaises(gate.GateOrderingError):
                gate.validate_receipt(receipt, request)

    def test_request_identity_requires_all_fields(self):
        with self.assertRaises(gate.GateOrderingError):
            gate.request_identity({"git_commit_sha": "a" * 40})

    def test_suite_identity_requires_success_and_digest_equality(self):
        with self.assertRaises(gate.GateOrderingError):
            gate.suite_identity(runner_result(ok=False), ROOT)
        unequal = runner_result()
        unequal["executed_digest"] = "0" * 64
        with self.assertRaises(gate.GateOrderingError):
            gate.suite_identity(unequal, ROOT)
        identity = gate.suite_identity(runner_result(), ROOT)
        self.assertEqual(identity["count"], 2759)


class HandoffTests(unittest.TestCase):
    """Control 9 — review alone never completes handoff."""

    def test_review_verdicts_insufficient_without_final_gates(self):
        status = gate.handoff_gate_status(None, hosted_ci_success=False,
                                          finalizer_ok=True)
        self.assertFalse(status["handoff_complete"])
        # a stale/drifted receipt is as good as none
        stale = make_receipt(sha="a" * 40)
        request = gate.request_identity(make_receipt(sha="b" * 40))
        status = gate.handoff_gate_status(stale, hosted_ci_success=False,
                                          finalizer_ok=True)
        self.assertFalse(status["handoff_complete"])
        self.assertIn("never sufficient", status["note"])

    def test_valid_receipt_plus_ci_plus_finalizer_completes(self):
        receipt = make_receipt()
        request = gate.request_identity(make_receipt())
        status = gate.handoff_gate_status(receipt, hosted_ci_success=True,
                                          finalizer_ok=True)
        self.assertTrue(status["handoff_complete"])


class LaunchLockTests(unittest.TestCase):
    """Control 6 — duplicate requests attach instead of relaunching."""

    def _sleep_process_command(self):
        return [sys.executable, "-c", "import time; time.sleep(30)"]

    def test_duplicate_request_attaches_to_running_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = gate.LaunchLock(Path(tmp), "head1-config1")
            command = self._sleep_process_command()
            proc = subprocess.Popen(command,
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
            try:
                # simulate the owner having registered the launch
                lock.root.mkdir(parents=True, exist_ok=True)
                lock.path().write_text(json.dumps(
                    {"schema": "suite-launch-lock/1", "pid": proc.pid,
                     "command": command, "acquired_unix": time.time()}),
                    encoding="utf-8")
                duplicate = gate.LaunchLock(Path(tmp), "head1-config1")
                outcome = duplicate.acquire_or_attach(command)
                self.assertTrue(outcome["attached"])
                self.assertEqual(outcome["pid"], proc.pid)
            finally:
                proc.kill()
                proc.wait()

    def test_first_request_acquires_and_releases(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = gate.LaunchLock(Path(tmp), "head2-config1")
            outcome = lock.acquire_or_attach(["suite", "--json"])
            self.assertFalse(outcome["attached"])
            self.assertTrue(lock.path().exists())
            lock.release()
            self.assertFalse(lock.path().exists())

    def test_stale_lock_pruned_and_retaken(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = gate.LaunchLock(Path(tmp), "head3")
            # a PID that definitely does not exist
            lock.path().write_text(json.dumps(
                {"schema": "suite-launch-lock/1", "pid": 2 ** 30,
                 "command": ["suite"], "acquired_unix": time.time()}),
                encoding="utf-8")
            outcome = lock.acquire_or_attach(["suite"])
            self.assertFalse(outcome["attached"])

    def test_malformed_lock_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = gate.LaunchLock(Path(tmp), "head4")
            lock.path().write_text("not json", encoding="utf-8")
            with self.assertRaises(gate.GateOrderingError):
                lock.acquire_or_attach(["suite"])

    def test_live_lock_with_different_config_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            command = self._sleep_process_command()
            proc = subprocess.Popen(command,
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
            try:
                lock = gate.LaunchLock(Path(tmp), "head5")
                lock.path().write_text(json.dumps(
                    {"schema": "suite-launch-lock/1", "pid": proc.pid,
                     "command": command, "acquired_unix": time.time()}),
                    encoding="utf-8")
                other = gate.LaunchLock(Path(tmp), "head5")
                with self.assertRaises(gate.GateOrderingError):
                    other.acquire_or_attach(["different", "--config"])
            finally:
                proc.kill()
                proc.wait()

    def test_distinct_keys_do_not_collide(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = gate.LaunchLock(Path(tmp), "headA")
            b = gate.LaunchLock(Path(tmp), "headB")
            self.assertNotEqual(a.path(), b.path())
            self.assertFalse(a.acquire_or_attach(["s"])["attached"])
            self.assertFalse(b.acquire_or_attach(["s"])["attached"])


class BuildReceiptTests(unittest.TestCase):
    """Receipt construction binds a real clean git checkout."""

    def _git_repo(self, tmp: Path) -> Path:
        repo = tmp / "repo"
        repo.mkdir()
        subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(repo), "config",
                        "user.email", "t@example.com"], check=True)
        subprocess.run(["git", "-C", str(repo), "config",
                        "user.name", "t"], check=True)
        for rel in gate.ENV_AUTHORITY_FILES:
            path = repo / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("authority\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init"],
                       check=True)
        return repo

    def test_build_receipt_binds_sha_and_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._git_repo(Path(tmp))
            receipt = gate.build_receipt(
                repo, runner_result(), started_unix=1.0, ended_unix=2.0)
            self.assertEqual(receipt.result, "PASS")
            self.assertEqual(receipt.git_commit_sha,
                             gate.git_commit_sha(repo))
            self.assertIn("requirements-test.txt", receipt.environment)
            # round trip through dict and validate
            payload = receipt.to_dict()
            self.assertTrue(gate.validate_receipt(
                payload, gate.request_identity(payload)))

    def test_build_receipt_refuses_dirty_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._git_repo(Path(tmp))
            (repo / "requirements-test.txt").write_text("drift\n",
                                                       encoding="utf-8")
            with self.assertRaises(gate.GateOrderingError):
                gate.build_receipt(repo, runner_result(), 1.0, 2.0)

    def test_environment_identity_fails_closed_on_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._git_repo(Path(tmp))
            (repo / "requirements-test.txt").unlink()
            with self.assertRaises(gate.GateOrderingError):
                gate.environment_identity(repo)


class PreservationTests(unittest.TestCase):
    """Control 12 — orchestration touches no historical evidence bytes."""

    def test_module_writes_no_docs_and_declares_no_cache(self):
        source = (ROOT / "scripts" / "issue213_gate_orchestration.py").read_text(
            encoding="utf-8")
        self.assertNotIn("docs/qualification", source)
        self.assertNotIn("docs/implementation", source)
        self.assertNotIn("docs/investigations", source)
        self.assertNotIn("shelve", source)
        self.assertNotIn("dbm", source)

    def test_historical_trees_untouched_by_this_change(self):
        # every tracked file outside this issue's own surface is identical
        # to origin/main (the branch base); prove via git diff name-only.
        proc = subprocess.run(
            ["git", "-C", str(ROOT), "diff", "--name-only", "origin/main"],
            capture_output=True, text=True)
        changed = [line for line in proc.stdout.splitlines() if line.strip()]
        allowed_prefixes = ("scripts/issue213_", "tests/test_issue213_",
                            "docs/campaign-gate-ordering.md", "docs/README.md",
                            "CONTRIBUTING.md", "AGENTS.md",
                            "scripts/plan_ci.py", "scripts/ci_groups.json",
                            ".github/workflows/ci.yml",
                            "tests/test_issue184_final_closure.py")
        for path in changed:
            self.assertTrue(path.startswith(allowed_prefixes),
                            f"unexpected changed path: {path}")

    def test_planner_semantics_preserved(self):
        # the #148 planner still selects repo-integrity + fail-closed for
        # this change's paths and its self-test module list is intact.
        proc = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, 'scripts'); "
             "import plan_ci, json; "
             "print(json.dumps(plan_ci.plan(['CONTRIBUTING.md'], 'pr')))"],
            capture_output=True, text=True, cwd=str(ROOT))
        payload = json.loads(proc.stdout)
        self.assertIn("repo-integrity", payload["groups"])
        self.assertFalse(payload["full_regression"])


if __name__ == "__main__":
    unittest.main()
