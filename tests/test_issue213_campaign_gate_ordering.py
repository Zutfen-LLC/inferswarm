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

Correction-pass controls (would FAIL on the pre-correction head 0e5695b):

13. handoff requires an independently derived final-head identity — a
    receipt can never validate against identity extracted from itself;
14. stale suite receipt SHA + current CI + finalizer -> handoff FALSE;
15. current suite receipt + stale CI SHA -> handoff FALSE;
16. suite/CI bound to different SHAs -> handoff FALSE;
17. hosted CI must present a structured exact-head status; a bare boolean
    cannot complete handoff;
18. malformed nested suite receipt identity (unknown schema/command/
    digest-shape/count/unknown env key) -> rejected structurally;
19. omitting a mandatory final gate (full suite or hosted CI), including
    the empty final-head plan -> plan rejected;
20. review-critical full suite + no review mutation -> valid plan with ONE
    physical suite execution (validated reuse), not two;
21. review-critical full suite + review mutation -> TWO physical suite
    executions on different heads;
22. execution counts are distinct from final validation cycle counts;
23. two genuinely concurrent identical full-suite requests through the
    canonical invocation seam -> exactly ONE underlying suite launch, the
    concurrent request attaches to the owner's result;
24. head/config/environment drift -> distinct launch identities -> fresh
    execution;
25. an arbitrary caller-supplied lock key cannot bypass deduplication
    (identity must be mechanically derived);
26. the canonical runner CLI path is guarded (direct legitimate invocation
    cannot bypass single-launch behavior).
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import issue213_gate_orchestration as gate  # noqa: E402
import run_full_cpu_suite as runner  # noqa: E402


def make_receipt(sha="a" * 40, serial="f" * 64, env_hash="e" * 64,
                 result="PASS", started=None, ended=None, count=2759):
    suite = {
        "runner_schema": gate.RUNNER_SCHEMA,
        "suite_command": list(gate.FULL_SUITE_COMMAND),
        "serial_digest": serial,
        "executed_digest": serial,
        "count": count,
    }
    environment = {rel: env_hash for rel in gate.ENV_AUTHORITY_FILES}
    return {
        "schema": gate.RECEIPT_SCHEMA,
        "git_commit_sha": sha,
        "suite": suite,
        "environment": environment,
        "result": result,
        "count": count,
        "started_unix": started if started is not None else 1000.0,
        "ended_unix": ended if ended is not None else 1000.5,
    }


def make_final_head(sha="b" * 40, serial="f" * 64, env_hash="e" * 64,
                    count=2759):
    suite = {
        "runner_schema": gate.RUNNER_SCHEMA,
        "suite_command": list(gate.FULL_SUITE_COMMAND),
        "serial_digest": serial,
        "executed_digest": serial,
        "count": count,
    }
    environment = {rel: env_hash for rel in gate.ENV_AUTHORITY_FILES}
    return gate.FinalHeadRequest(git_commit_sha=sha, suite=suite,
                                 environment=environment)


def runner_result(ok=True, serial="f" * 64, count=2759,
                  schema=gate.RUNNER_SCHEMA):
    return {"ok": ok, "schema": schema, "serial_digest": serial,
            "executed_digest": serial, "count": count}


class GatePlanTests(unittest.TestCase):
    """Controls 1, 2, 10, 11, 19, 20, 21, 22 — ordering and fail-closed
    plan semantics, mandatory final gates, and execution vs cycle counts."""

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
        self.assertEqual(plan["final_validation_cycles"], 1)
        self.assertEqual(plan["expensive_gate_executions"],
                         {"full-cpu-suite": 1, "hosted-exact-head-ci": 1})

    def test_review_fix_path_still_schedules_one_final_cycle(self):
        # review mutates the head; canonical ordering still schedules the
        # expensive gates exactly once (on the corrected final head).
        plan = gate.plan_campaign_gates(
            gate.CampaignFlow("issue-X"), review_mutates_head=True)
        scheduled = [g for phase in plan["phases"] for g in phase["gates"]]
        self.assertEqual(scheduled.count("full-cpu-suite"), 1)
        self.assertEqual(scheduled.count("hosted-exact-head-ci"), 1)
        old = gate.trace_campaign(True, review_mutates_head=True)
        new = gate.trace_campaign(False)
        self.assertEqual(old["total_expensive_executions"], 4)
        self.assertEqual(new["total_expensive_executions"], 2)
        self.assertEqual(new["final_validation_cycles"], 1)

    def test_control20_review_critical_no_mutation_reuses(self):
        # Review-critical full suite ran pre-review; review did NOT mutate
        # the head: the exact-head result satisfies the final requirement
        # through mechanically validated reuse — ONE physical execution,
        # never two, and no duplicate-phase-occurrence error.
        flow = gate.CampaignFlow(
            "issue-Y",
            pre_review=("focused-changed-surface-tests",),
            review_critical=("full-cpu-suite",),
        )
        plan = gate.plan_campaign_gates(flow, review_mutates_head=False)
        self.assertIn("full-cpu-suite", plan["phases"][0]["gates"])
        # the final-head REQUIREMENT still names the full suite...
        self.assertIn("full-cpu-suite", plan["phases"][3]["requirements"])
        # ...but it is satisfied by validated reuse, not a second physical
        # execution (it must NOT appear twice among physical executions).
        self.assertNotIn("full-cpu-suite", plan["phases"][3]["gates"])
        self.assertEqual(plan["expensive_gate_executions"]["full-cpu-suite"], 1)
        self.assertIn("full-cpu-suite", plan["reuse_satisfied_final"])
        self.assertEqual(plan["final_validation_cycles"], 1)
        trace = gate.trace_campaign(False, False, ("full-cpu-suite",))
        self.assertEqual(trace["expensive_gate_executions"]["full-cpu-suite"], 1)

    def test_control21_review_critical_mutation_reruns_on_new_head(self):
        flow = gate.CampaignFlow(
            "issue-Y",
            pre_review=("focused-changed-surface-tests",),
            review_critical=("full-cpu-suite",),
        )
        plan = gate.plan_campaign_gates(flow, review_mutates_head=True)
        self.assertIn("full-cpu-suite", plan["phases"][0]["gates"])
        self.assertIn("full-cpu-suite", plan["phases"][3]["gates"])
        # TWO physical suite executions: pre-review head + mutated final head.
        self.assertEqual(plan["expensive_gate_executions"]["full-cpu-suite"], 2)
        self.assertEqual(plan["reuse_satisfied_final"], [])
        # Still exactly ONE final validation cycle on the final head.
        self.assertEqual(plan["final_validation_cycles"], 1)
        trace = gate.trace_campaign(False, True, ("full-cpu-suite",))
        self.assertEqual(trace["expensive_gate_executions"]["full-cpu-suite"], 2)
        self.assertEqual(trace["final_validation_cycles"], 1)

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

    def test_control19_omitted_mandatory_full_suite_rejected(self):
        # full-suite-only-minus / hosted-CI-only plans are invalid.
        with self.assertRaises(gate.GateOrderingError):
            gate.CampaignFlow("issue-X", final_head=("hosted-exact-head-ci",
                                                     "finalizer-status-fixed-point-checks"))

    def test_control19_omitted_mandatory_hosted_ci_rejected(self):
        with self.assertRaises(gate.GateOrderingError):
            gate.CampaignFlow("issue-X", final_head=("full-cpu-suite",
                                                     "finalizer-status-fixed-point-checks"))

    def test_control19_empty_final_head_rejected(self):
        with self.assertRaises(gate.GateOrderingError):
            gate.CampaignFlow("issue-X", final_head=())

    def test_finalizer_only_plan_rejected(self):
        with self.assertRaises(gate.GateOrderingError):
            gate.CampaignFlow("issue-X",
                              final_head=("finalizer-status-fixed-point-checks",))


class ReceiptTests(unittest.TestCase):
    """Controls 3, 4, 5, 7, 8, 11, 18 — exact-head receipt fail-closed
    reuse and STRUCTURAL validation (never nested-dict equality alone)."""

    def test_control3_head_change_rejects_reuse(self):
        receipt = make_receipt(sha="a" * 40)
        request = make_final_head(sha="b" * 40)
        decision = gate.reuse_or_rerun(receipt, request.to_dict())
        self.assertEqual(decision["action"], "run")
        self.assertFalse(gate.validate_receipt(receipt, request.to_dict()))

    def test_control4_suite_config_change_rejects_reuse(self):
        receipt = make_receipt(serial="f" * 64)
        request = make_final_head(serial="0" * 64)
        self.assertFalse(gate.validate_receipt(receipt, request.to_dict()))

    def test_control4_count_and_command_are_identity(self):
        receipt = make_receipt()
        mutated = make_receipt(count=1)
        self.assertFalse(
            gate.validate_receipt(receipt, make_final_head(count=1).to_dict()))
        mutated2 = make_receipt()
        mutated2["suite"]["suite_command"] = ["python", "other.py"]
        request = make_final_head()
        request_dict = request.to_dict()
        request_dict["suite"]["suite_command"] = ["python", "other.py"]
        # the forged request itself is structurally invalid
        with self.assertRaises(gate.GateOrderingError):
            gate.request_identity(request_dict)

    def test_control5_environment_change_rejects_reuse(self):
        receipt = make_receipt(env_hash="e" * 64)
        request = make_final_head(env_hash="d" * 64)
        self.assertFalse(gate.validate_receipt(receipt, request.to_dict()))
        # an incomplete request environment (missing authority file) is
        # structurally invalid and can never become comparison authority
        request_dict = make_final_head().to_dict()
        request_dict["environment"].pop("requirements-test.txt")
        with self.assertRaises(gate.GateOrderingError):
            gate.validate_receipt(make_receipt(), request_dict)
        # a receipt with an incomplete environment is rejected too
        dropped = make_receipt()
        dropped["environment"].pop("requirements-test.txt")
        with self.assertRaises(gate.GateOrderingError):
            gate.validate_receipt(dropped, make_final_head().to_dict())

    def test_control7_full_match_reuses(self):
        receipt = make_receipt(sha="a" * 40)
        request = make_final_head(sha="a" * 40)
        self.assertTrue(gate.validate_receipt(receipt, request.to_dict()))
        self.assertEqual(
            gate.reuse_or_rerun(receipt, request.to_dict())["action"], "reuse")
        self.assertEqual(
            gate.reuse_or_rerun(None, request.to_dict())["action"], "run")

    def test_control8_failed_cancelled_incomplete_receipts_rejected(self):
        request = make_final_head().to_dict()
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
        request = make_final_head().to_dict()
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

    def test_control18_malformed_nested_suite_identity_rejected(self):
        """Arbitrary nested dictionaries never compare equal into
        authority: every structural violation of the suite identity is
        rejected even when the outer comparison would have matched."""
        request = make_final_head().to_dict()
        cases = []
        # unknown runner schema
        r = make_receipt(); r["suite"]["runner_schema"] = "other-runner/2"
        cases.append(r)
        # non-canonical command
        r = make_receipt(); r["suite"]["suite_command"] = ["python", "x.py"]
        cases.append(r)
        # malformed serial digest shape
        r = make_receipt(); r["suite"]["serial_digest"] = "not-hex"
        cases.append(r)
        # malformed executed digest shape
        r = make_receipt(); r["suite"]["executed_digest"] = "XYZ"
        cases.append(r)
        # serial/executed inequality
        r = make_receipt(); r["suite"]["executed_digest"] = "0" * 64
        cases.append(r)
        # non-positive count
        r = make_receipt(); r["suite"]["count"] = 0; r["count"] = 0
        cases.append(r)
        # non-integer count
        r = make_receipt(); r["suite"]["count"] = "2759"; r["count"] = "2759"
        cases.append(r)
        # top-level count inconsistent with suite count
        r = make_receipt(); r["count"] = 2758
        cases.append(r)
        # missing suite key
        r = make_receipt(); r["suite"].pop("serial_digest")
        cases.append(r)
        # malformed git SHA shape
        r = make_receipt(); r["git_commit_sha"] = "short"
        cases.append(r)
        # boolean count
        r = make_receipt(); r["suite"]["count"] = True; r["count"] = True
        cases.append(r)
        for receipt in cases:
            with self.assertRaises(gate.GateOrderingError,
                                   msg=json.dumps(receipt, default=str)):
                gate.validate_receipt(receipt, request)
            self.assertEqual(
                gate.reuse_or_rerun(receipt, request)["action"], "run")

    def test_control18_unknown_or_missing_env_authority_rejected(self):
        request = make_final_head().to_dict()
        # unknown extra authority file
        r = make_receipt()
        r["environment"]["scripts/rogue.py"] = "a" * 64
        with self.assertRaises(gate.GateOrderingError):
            gate.validate_receipt(r, request)
        # missing required authority file
        r = make_receipt()
        r["environment"].pop("scripts/check_test_env.py")
        with self.assertRaises(gate.GateOrderingError):
            gate.validate_receipt(r, request)
        # malformed digest value
        r = make_receipt()
        r["environment"]["requirements-test.txt"] = "digest"
        with self.assertRaises(gate.GateOrderingError):
            gate.validate_receipt(r, request)

    def test_request_identity_requires_all_fields(self):
        with self.assertRaises(gate.GateOrderingError):
            gate.request_identity({"git_commit_sha": "a" * 40})

    def test_request_identity_structurally_validates(self):
        # a structurally malformed request never becomes authority
        bad = make_receipt()
        bad["suite"]["count"] = -5
        with self.assertRaises(gate.GateOrderingError):
            gate.request_identity(bad)
        bad2 = make_receipt()
        bad2["git_commit_sha"] = "nope"
        with self.assertRaises(gate.GateOrderingError):
            gate.request_identity(bad2)

    def test_suite_identity_requires_success_and_digest_equality(self):
        with self.assertRaises(gate.GateOrderingError):
            gate.suite_identity(runner_result(ok=False))
        unequal = runner_result()
        unequal["executed_digest"] = "0" * 64
        with self.assertRaises(gate.GateOrderingError):
            gate.suite_identity(unequal)
        identity = gate.suite_identity(runner_result())
        self.assertEqual(identity["count"], 2759)
        self.assertEqual(identity["suite_command"],
                         list(gate.FULL_SUITE_COMMAND))


class HandoffTests(unittest.TestCase):
    """Controls 9, 13-17 — independently bound final handoff."""

    def _valid_final_head(self):
        return make_final_head(sha="b" * 40)

    def test_control13_handoff_requires_independent_final_head(self):
        # No final-head argument at all: rejected (a receipt may never be
        # validated against identity extracted from itself).
        with self.assertRaises(gate.GateOrderingError):
            gate.handoff_gate_status(None, None, None, finalizer_ok=True)
        with self.assertRaises(TypeError):
            # positional misuse (old signature) must not silently work
            gate.handoff_gate_status(make_receipt(), True, True)
        # a plain dict is not an independently derived identity either
        with self.assertRaises(gate.GateOrderingError):
            gate.handoff_gate_status(make_final_head().to_dict(),  # type: ignore[arg-type]
                                     None, None, finalizer_ok=True)

    def test_control9_review_verdicts_insufficient_without_final_gates(self):
        head = self._valid_final_head()
        status = gate.handoff_gate_status(head, None, None,
                                          finalizer_ok=True)
        self.assertFalse(status["handoff_complete"])
        self.assertFalse(status["hosted_ci_success"])
        # a stale/drifted receipt is as good as none
        stale = make_receipt(sha="a" * 40)
        status = gate.handoff_gate_status(head, stale, None,
                                          finalizer_ok=True)
        self.assertFalse(status["handoff_complete"])
        self.assertIn("never sufficient", status["note"])

    def test_control14_stale_suite_sha_current_ci_finalizer_false(self):
        head = self._valid_final_head()          # final head = bbbb
        stale_suite = make_receipt(sha="a" * 40)  # suite from SHA aaaa
        ci = gate.build_hosted_ci_status("b" * 40, "run-77")
        status = gate.handoff_gate_status(head, stale_suite, ci,
                                          finalizer_ok=True)
        self.assertFalse(status["handoff_complete"])
        self.assertFalse(status["full_suite_receipt_valid"])
        self.assertTrue(status["hosted_ci_success"])

    def test_control15_current_suite_stale_ci_false(self):
        head = self._valid_final_head()                          # bbbb
        suite = make_receipt(sha="b" * 40)                       # bbbb
        stale_ci = gate.build_hosted_ci_status("a" * 40, "run-77")
        status = gate.handoff_gate_status(head, suite, stale_ci,
                                          finalizer_ok=True)
        self.assertFalse(status["handoff_complete"])
        self.assertTrue(status["full_suite_receipt_valid"])
        self.assertFalse(status["hosted_ci_success"])

    def test_control16_suite_and_ci_different_shas_false(self):
        # each individually valid, bound to different SHAs
        suite = make_receipt(sha="a" * 40)
        ci = gate.build_hosted_ci_status("c" * 40, "run-78")
        for head_sha in ("a" * 40, "c" * 40, "b" * 40):
            head = make_final_head(sha=head_sha)
            status = gate.handoff_gate_status(head, suite, ci,
                                              finalizer_ok=True)
            self.assertFalse(status["handoff_complete"],
                             f"handoff wrongly complete for {head_sha}")

    def test_control17_bare_boolean_ci_cannot_complete(self):
        head = self._valid_final_head()
        suite = make_receipt(sha="b" * 40)
        with self.assertRaises(gate.GateOrderingError):
            gate.handoff_gate_status(head, suite, True,  # type: ignore[arg-type]
                                     finalizer_ok=True)

    def test_valid_receipt_plus_structured_ci_plus_finalizer_completes(self):
        head = self._valid_final_head()
        suite = make_receipt(sha="b" * 40)
        ci = gate.build_hosted_ci_status("b" * 40, "run-79",
                                         run_url="https://ci.example/79")
        status = gate.handoff_gate_status(head, suite, ci, finalizer_ok=True)
        self.assertTrue(status["handoff_complete"])
        self.assertEqual(status["final_head_sha"], "b" * 40)

    def test_malformed_ci_status_fails_closed(self):
        head = self._valid_final_head()
        suite = make_receipt(sha="b" * 40)
        for bad in (
            {"schema": "other/1", "git_commit_sha": "b" * 40,
             "result": "SUCCESS", "run_id": "r1"},
            {"schema": gate.CI_STATUS_SCHEMA, "git_commit_sha": "b" * 40,
             "result": "FAILURE", "run_id": "r1"},
            {"schema": gate.CI_STATUS_SCHEMA, "git_commit_sha": "b" * 40,
             "result": "SUCCESS", "run_id": ""},
            {"schema": gate.CI_STATUS_SCHEMA, "git_commit_sha": "b" * 40,
             "result": "SUCCESS"},
            {"schema": gate.CI_STATUS_SCHEMA, "git_commit_sha": "zzz",
             "result": "SUCCESS", "run_id": "r1"},
            {"schema": gate.CI_STATUS_SCHEMA, "git_commit_sha": "b" * 40,
             "result": "SUCCESS", "run_id": "r1", "run_url": "  "},
        ):
            with self.assertRaises(gate.GateOrderingError,
                                   msg=json.dumps(bad, default=str)):
                gate.handoff_gate_status(head, suite, bad, finalizer_ok=True)

    def test_build_hosted_ci_status_rejects_bad_inputs(self):
        with self.assertRaises(gate.GateOrderingError):
            gate.build_hosted_ci_status("nope", "run-1")
        with self.assertRaises(gate.GateOrderingError):
            gate.build_hosted_ci_status("a" * 40, "run-1", result="FAILURE")


class FinalHeadRequestTests(unittest.TestCase):
    """The independently derived identity is itself structurally guarded."""

    def test_structurally_invalid_final_head_rejected(self):
        suite = {
            "runner_schema": gate.RUNNER_SCHEMA,
            "suite_command": list(gate.FULL_SUITE_COMMAND),
            "serial_digest": "f" * 64, "executed_digest": "f" * 64,
            "count": 2759,
        }
        environment = {rel: "e" * 64 for rel in gate.ENV_AUTHORITY_FILES}
        with self.assertRaises(gate.GateOrderingError):
            gate.FinalHeadRequest(git_commit_sha="bad", suite=suite,
                                  environment=environment)
        bad_suite = dict(suite, count=0)
        with self.assertRaises(gate.GateOrderingError):
            gate.FinalHeadRequest(git_commit_sha="a" * 40, suite=bad_suite,
                                  environment=environment)
        bad_env = dict(environment)
        bad_env.pop("requirements-test.txt")
        with self.assertRaises(gate.GateOrderingError):
            gate.FinalHeadRequest(git_commit_sha="a" * 40, suite=suite,
                                  environment=bad_env)


class LaunchGuardTests(unittest.TestCase):
    """Controls 6, 23-26 — duplicate-launch prevention mechanics."""

    def _guard_dir(self):
        temporary = tempfile.mkdtemp(prefix="issue213-guard-")
        self.addCleanup(lambda: subprocess.run(
            ["rm", "-rf", temporary], check=False))
        return Path(temporary)

    def test_duplicate_request_attaches_to_running_process(self):
        guard_dir = self._guard_dir()
        with tempfile.TemporaryDirectory() as tmp:
            command = [sys.executable, "-c", "import time; time.sleep(30)"]
            proc = subprocess.Popen(command, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
            try:
                identity = make_final_head(sha="d" * 40).to_dict() | {
                    "schema": gate.LAUNCH_IDENTITY_SCHEMA}
                owner = gate.LaunchGuard(identity, lock_dir=guard_dir)
                outcome = owner.acquire_or_attach()
                self.assertFalse(outcome["attached"])
                duplicate = gate.LaunchGuard(identity, lock_dir=guard_dir)
                outcome = duplicate.acquire_or_attach()
                self.assertTrue(outcome["attached"])
                self.assertFalse(outcome["completed"])
                self.assertEqual(outcome["pid"], os.getpid())
            finally:
                proc.kill()
                proc.wait()

    def test_first_request_acquires_and_releases(self):
        guard_dir = self._guard_dir()
        identity = make_final_head(sha="d" * 40).to_dict() | {
            "schema": gate.LAUNCH_IDENTITY_SCHEMA}
        lock = gate.LaunchGuard(identity, lock_dir=guard_dir)
        outcome = lock.acquire_or_attach()
        self.assertFalse(outcome["attached"])
        self.assertTrue(lock.lock_path().exists())
        lock.release()
        self.assertFalse(lock.lock_path().exists())

    def test_stale_lock_proven_dead_pruned_and_retaken(self):
        guard_dir = self._guard_dir()
        identity = make_final_head(sha="e" * 40).to_dict() | {
            "schema": gate.LAUNCH_IDENTITY_SCHEMA}
        lock = gate.LaunchGuard(identity, lock_dir=guard_dir)
        lock.lock_path().write_text(json.dumps(
            {"schema": gate.LAUNCH_LOCK_SCHEMA, "key": lock.key,
             "pid": 2 ** 30, "command": ["suite"],
             "acquired_unix": time.time()}), encoding="utf-8")
        outcome = lock.acquire_or_attach()
        self.assertFalse(outcome["attached"])

    def test_malformed_lock_fails_closed(self):
        guard_dir = self._guard_dir()
        identity = make_final_head(sha="f" * 40).to_dict() | {
            "schema": gate.LAUNCH_IDENTITY_SCHEMA}
        lock = gate.LaunchGuard(identity, lock_dir=guard_dir)
        lock.lock_path().write_text("not json", encoding="utf-8")
        with self.assertRaises(gate.GateOrderingError):
            lock.acquire_or_attach()

    def test_live_lock_key_mismatch_fails_closed(self):
        guard_dir = self._guard_dir()
        identity = make_final_head(sha="9" * 40).to_dict() | {
            "schema": gate.LAUNCH_IDENTITY_SCHEMA}
        lock = gate.LaunchGuard(identity, lock_dir=guard_dir)
        lock.lock_path().write_text(json.dumps(
            {"schema": gate.LAUNCH_LOCK_SCHEMA, "key": "a" * 64,
             "pid": os.getpid(), "command": ["suite"],
             "acquired_unix": time.time()}), encoding="utf-8")
        with self.assertRaises(gate.GateOrderingError):
            lock.acquire_or_attach()

    def test_distinct_identities_do_not_collide(self):
        guard_dir = self._guard_dir()
        a = gate.LaunchGuard(make_final_head(sha="a" * 40).to_dict() | {
            "schema": gate.LAUNCH_IDENTITY_SCHEMA}, lock_dir=guard_dir)
        b = gate.LaunchGuard(make_final_head(sha="b" * 40).to_dict() | {
            "schema": gate.LAUNCH_IDENTITY_SCHEMA}, lock_dir=guard_dir)
        self.assertNotEqual(a.lock_path(), b.lock_path())
        self.assertNotEqual(a.key, b.key)
        self.assertFalse(a.acquire_or_attach()["attached"])
        self.assertFalse(b.acquire_or_attach()["attached"])

    def test_control25_arbitrary_lock_key_is_not_authority(self):
        # an arbitrary caller-supplied key can never construct a guard
        with self.assertRaises(gate.GateOrderingError):
            gate.launch_request_key({"schema": "attacker/1",
                                     "git_commit_sha": "a" * 40})
        with self.assertRaises(gate.GateOrderingError):
            gate.launch_request_key("just-a-string")  # type: ignore[arg-type]
        # and a forged identity without proper shape fails key derivation
        with self.assertRaises(gate.GateOrderingError):
            gate.launch_request_key({"schema": gate.LAUNCH_IDENTITY_SCHEMA,
                                     "git_commit_sha": "a" * 40,
                                     "suite": {"runner_schema": "rogue/1"},
                                     "environment": {}})

    def test_completion_receipt_validation(self):
        guard_dir = self._guard_dir()
        identity = make_final_head(sha="1" * 40).to_dict() | {
            "schema": gate.LAUNCH_IDENTITY_SCHEMA}
        guard = gate.LaunchGuard(identity, lock_dir=guard_dir)
        guard.write_completion({"ok": True, "count": 3}, started_unix=1.0)
        record = guard.find_valid_completion()
        self.assertIsNotNone(record)
        self.assertTrue(record["ok"])
        # a malformed completion fails closed rather than being consumed
        guard.completion_path().write_text(json.dumps(
            {"schema": "bogus/9", "key": guard.key}), encoding="utf-8")
        with self.assertRaises(gate.GateOrderingError):
            guard.find_valid_completion()
        # a completion for a different identity key fails closed
        guard.completion_path().write_text(json.dumps(
            {"schema": gate.COMPLETION_SCHEMA, "key": "c" * 64,
             "git_commit_sha": "1" * 40, "ok": True, "result": {},
             "started_unix": 1.0, "ended_unix": 2.0}), encoding="utf-8")
        with self.assertRaises(gate.GateOrderingError):
            guard.find_valid_completion()

    def test_owner_exception_writes_no_completion(self):
        guard_dir = self._guard_dir()
        identity = make_final_head(sha="2" * 40).to_dict() | {
            "schema": gate.LAUNCH_IDENTITY_SCHEMA}
        calls = []

        def exploding():
            calls.append(1)
            raise RuntimeError("suite crashed")

        with self.assertRaises(RuntimeError):
            gate.run_single_head_suite(
                Path("/nonexistent-root"), suite_command=exploding,
                lock_dir=guard_dir)
        # no completion receipt exists for the next waiter to consume
        guard = gate.LaunchGuard(identity, lock_dir=guard_dir)
        self.assertFalse(guard.completion_path().exists())


class ConcurrencyTests(unittest.TestCase):
    """Control 23 — genuinely concurrent identical requests through the
    canonical invocation seam: exactly ONE underlying suite launch."""

    _repo_seq = 0

    def _fixture_repo(self) -> Path:
        # Unique fixture module names per repo: discovery imports pollute
        # sys.modules and a stale module makes the next repo's discovery
        # fail (the runner's own contract tests purge for the same reason).
        ConcurrencyTests._repo_seq += 1
        prefix = f"issue213c{ConcurrencyTests._repo_seq}"
        root = Path(tempfile.mkdtemp(prefix=f"{prefix}-root-"))
        self.addCleanup(lambda: subprocess.run(
            ["rm", "-rf", str(root)], check=False))
        repo = root / "repo"
        repo.mkdir()
        for cmd in (("git", "init", "-q"),
                    ("git", "config", "user.email", "t@example.invalid"),
                    ("git", "config", "user.name", "t")):
            subprocess.run(cmd, cwd=repo, check=True)
        (repo / "tests").mkdir()
        module_name = f"test_{prefix}"
        self.addCleanup(sys.modules.pop, module_name, None)
        (repo / "tests" / f"{module_name}.py").write_text(
            "import unittest\nclass A(unittest.TestCase):\n"
            " def test_x(self): pass\n", encoding="utf-8")
        for rel in gate.ENV_AUTHORITY_FILES:
            path = repo / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("authority\n", encoding="utf-8")
        subprocess.run(("git", "add", "-A"), cwd=repo, check=True)
        subprocess.run(("git", "commit", "-qm", "init"), cwd=repo, check=True)
        return repo

    def test_control23_concurrent_identical_requests_single_launch(self):
        repo = self._fixture_repo()
        lock_dir = repo.parent / "locks"
        launches = []
        release = threading.Event()

        def fake_suite():
            launches.append(time.time())
            release.wait(10)  # hold the "suite" so the duplicate must attach
            return {"ok": True, "count": 1, "fake": True}

        results = {}

        def starter(name):
            try:
                results[name] = gate.run_single_head_suite(
                    repo, suite_command=fake_suite, lock_dir=lock_dir)
            except BaseException as error:  # noqa: BLE001
                results[name] = error

        first = threading.Thread(target=starter, args=("first",))
        first.start()
        # wait until the owner is inside the fake suite
        deadline = time.monotonic() + 10
        while not launches and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(len(launches), 1, "owner never launched")
        second = threading.Thread(target=starter, args=("second",))
        second.start()
        time.sleep(0.3)  # the duplicate must attach, not launch
        self.assertEqual(len(launches), 1,
                         "duplicate request started a second suite")
        release.set()
        first.join(30)
        second.join(30)
        self.assertEqual(len(launches), 1,
                         "exactly ONE underlying suite launch required")
        self.assertEqual(results["first"], {"ok": True, "count": 1,
                                            "fake": True})
        self.assertEqual(results["second"], {"ok": True, "count": 1,
                                             "fake": True},
                         "attacher must consume the owner's result")

    def test_head_drift_forces_fresh_execution(self):
        repo = self._fixture_repo()
        lock_dir = repo.parent / "locks2"
        launches = []

        def fake_suite():
            launches.append(1)
            return {"ok": True, "count": 1, "head": gate.git_commit_sha(repo)}

        first = gate.run_single_head_suite(repo, suite_command=fake_suite,
                                           lock_dir=lock_dir)
        self.assertEqual(len(launches), 1)
        # mutate the head: new commit -> new identity -> fresh execution
        new_module = f"test_b{ConcurrencyTests._repo_seq}"
        self.addCleanup(sys.modules.pop, new_module, None)
        (repo / "tests" / f"{new_module}.py").write_text(
            "import unittest\nclass B(unittest.TestCase):\n"
            " def test_y(self): pass\n", encoding="utf-8")
        subprocess.run(("git", "add", "-A"), cwd=repo, check=True)
        subprocess.run(("git", "commit", "-qm", "second"), cwd=repo,
                       check=True)
        second = gate.run_single_head_suite(repo, suite_command=fake_suite,
                                            lock_dir=lock_dir)
        self.assertEqual(len(launches), 2,
                         "head drift must force a distinct fresh execution")
        self.assertNotEqual(first["head"], second["head"])

    def test_environment_drift_forces_fresh_execution(self):
        repo = self._fixture_repo()
        lock_dir = repo.parent / "locks3"
        launches = []

        def fake_suite():
            launches.append(1)
            return {"ok": True, "count": 1}

        gate.run_single_head_suite(repo, suite_command=fake_suite,
                                   lock_dir=lock_dir)
        self.assertEqual(len(launches), 1)
        # environment authority drift: change the requirements file
        (repo / "requirements-test.txt").write_text("drifted\n",
                                                    encoding="utf-8")
        subprocess.run(("git", "add", "-A"), cwd=repo, check=True)
        subprocess.run(("git", "commit", "-qm", "env drift"), cwd=repo,
                       check=True)
        gate.run_single_head_suite(repo, suite_command=fake_suite,
                                   lock_dir=lock_dir)
        self.assertEqual(len(launches), 2,
                         "environment drift must force a fresh execution")

    def test_control26_canonical_runner_cli_is_guarded(self):
        # The runner's own canonical entry delegates through the guard:
        # two sequential identical CLI-shaped calls launch the underlying
        # suite exactly once (the second consumes the completion receipt).
        repo = self._fixture_repo()
        real_launches = []

        original = runner.run_suite

        def counting_run_suite(root, tests_dir=None, **kwargs):
            real_launches.append(1)
            return original(Path(root), tests_dir or Path(root) / "tests",
                            **kwargs)

        runner.run_suite = counting_run_suite
        self.addCleanup(setattr, runner, "run_suite", original)
        result = runner.run_single_head_suite(repo)
        self.assertTrue(result["ok"])
        self.assertEqual(len(real_launches), 1)
        result2 = runner.run_single_head_suite(repo)
        self.assertTrue(result2["ok"])
        self.assertEqual(len(real_launches), 1,
                         "identical request must reuse, not relaunch")


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

    def test_current_final_head_request_derives_independently(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._git_repo(Path(tmp))
            (repo / "tests").mkdir(exist_ok=True)
            fixture_module = f"test_finalhead{ConcurrencyTests._repo_seq}"
            self.addCleanup(sys.modules.pop, fixture_module, None)
            (repo / "tests" / f"{fixture_module}.py").write_text(
                "import unittest\nclass A(unittest.TestCase):\n"
                " def test_x(self): pass\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "t"],
                           check=True)
            head = gate.current_final_head_request(repo)
            self.assertEqual(head.git_commit_sha,
                             gate.git_commit_sha(repo))
            self.assertEqual(head.suite["count"], 1)
            self.assertEqual(head.suite["serial_digest"],
                             head.suite["executed_digest"])
            # dirty tree refuses identity derivation
            (repo / "requirements-test.txt").write_text("dirty\n",
                                                        encoding="utf-8")
            with self.assertRaises(gate.GateOrderingError):
                gate.current_final_head_request(repo)


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
                            "scripts/run_full_cpu_suite.py",
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

    def test_planner_maps_runner_and_orchestration_paths(self):
        # The runner maps to repo-integrity (unchanged #148 semantics, no
        # second planner) and the orchestration module to its own group;
        # the orchestration paths alone do NOT trigger full regression.
        proc = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, 'scripts'); "
             "import plan_ci, json; "
             "print(json.dumps(plan_ci.plan(['scripts/run_full_cpu_suite.py',"
             " 'scripts/issue213_gate_orchestration.py'], 'pr')))"],
            capture_output=True, text=True, cwd=str(ROOT))
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["full_regression"])
        self.assertIn("repo-integrity", payload["groups"])
        self.assertIn("issue-213-gate-ordering", payload["groups"])
        # and the group registry stays wired through ci_groups.json
        registry = json.loads(
            (ROOT / "scripts" / "ci_groups.json").read_text(encoding="utf-8"))
        self.assertIn("test_issue213_campaign_gate_ordering",
                      registry["groups"]["issue-213-gate-ordering"]["test_modules"])

    def test_runner_public_surface_unchanged(self):
        # #148 semantics: no second CI planner; the runner's canonical
        # execution helpers keep their signatures and the single-launch
        # seam is wired into main()'s invocation path.
        import inspect
        self.assertTrue(callable(runner.run_suite))
        self.assertTrue(callable(runner.run_single_head_suite))
        source = (ROOT / "scripts" / "run_full_cpu_suite.py").read_text(
            encoding="utf-8")
        self.assertIn(
            "payload = run_single_head_suite(args.root, jobs=args.jobs,",
            source)


if __name__ == "__main__":
    unittest.main()
