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


def sample_suite_config(tests_dir="tests", jobs=1,
                        plan_digest=None, timeout=1800.0, retain_dir=None):
    """A structurally valid normalized suite configuration (sample)."""
    return {
        "schema": gate.SUITE_CONFIG_SCHEMA,
        "tests_dir": tests_dir,
        "jobs": jobs,
        "plan_digest": plan_digest or "a" * 64,
        "timeout": timeout,
        "retain_dir": retain_dir,
    }


def make_receipt(sha="a" * 40, serial="f" * 64, env_hash="e" * 64,
                 result="PASS", started=None, ended=None, count=2759,
                 config=None):
    suite = {
        "runner_schema": gate.RUNNER_SCHEMA,
        "suite_command": list(gate.FULL_SUITE_COMMAND),
        "suite_config": config or sample_suite_config(),
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
                    count=2759, config=None):
    suite = {
        "runner_schema": gate.RUNNER_SCHEMA,
        "suite_command": list(gate.FULL_SUITE_COMMAND),
        "suite_config": config or sample_suite_config(),
        "serial_digest": serial,
        "executed_digest": serial,
        "count": count,
    }
    environment = {rel: env_hash for rel in gate.ENV_AUTHORITY_FILES}
    return gate.FinalHeadRequest(git_commit_sha=sha, suite=suite,
                                 environment=environment)


def runner_result(ok=True, serial="f" * 64, count=2759,
                  schema=gate.RUNNER_SCHEMA, config=None):
    return {"ok": ok, "schema": schema, "serial_digest": serial,
            "executed_digest": serial, "count": count,
            "suite_config": config or sample_suite_config()}


def canonical_result_for(identity: dict, ok: bool = True) -> dict:
    """A canonical runner result bound to a launch identity's suite."""
    suite = identity["suite"]
    executed = suite["serial_digest"] if ok else None
    return {"schema": gate.RUNNER_SCHEMA, "ok": ok,
            "serial_digest": suite["serial_digest"],
            "executed_digest": executed, "count": suite["count"],
            "suite_config": suite["suite_config"]}


_guard_repo_seq = 0


def make_guard_fixture_repo(add_cleanup) -> Path:
    """Clean committed fixture repo with tests + a tracked production file.

    Same shape as the concurrency fixture (unique module names per repo —
    discovery imports pollute ``sys.modules``), plus a tracked
    non-test/non-authority production file so production-code drift is
    distinguishable from test-body drift.
    """
    global _guard_repo_seq
    _guard_repo_seq += 1
    prefix = f"issue213g{_guard_repo_seq}"
    root = Path(tempfile.mkdtemp(prefix=f"{prefix}-root-"))
    add_cleanup(lambda: subprocess.run(["rm", "-rf", str(root)], check=False))
    repo = root / "repo"
    repo.mkdir()
    for cmd in (("git", "init", "-q"),
                ("git", "config", "user.email", "t@example.invalid"),
                ("git", "config", "user.name", "t")):
        subprocess.run(cmd, cwd=repo, check=True)
    (repo / "tests").mkdir()
    module_name = f"test_{prefix}"
    add_cleanup(sys.modules.pop, module_name, None)
    (repo / "tests" / f"{module_name}.py").write_text(
        "import unittest\nclass A(unittest.TestCase):\n"
        " def test_x(self): self.assertTrue(True)\n", encoding="utf-8")
    (repo / "tool.py").write_text("VALUE = 1\n", encoding="utf-8")
    for rel in gate.ENV_AUTHORITY_FILES:
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("authority\n", encoding="utf-8")
    subprocess.run(("git", "add", "-A"), cwd=repo, check=True)
    subprocess.run(("git", "commit", "-qm", "init"), cwd=repo, check=True)
    return repo


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
            "suite_config": sample_suite_config(),
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
        # a suite identity without the normalized configuration is
        # structurally invalid
        with self.assertRaises(gate.GateOrderingError):
            gate.FinalHeadRequest(git_commit_sha="a" * 40,
                                  suite={k: v for k, v in suite.items()
                                         if k != "suite_config"},
                                  environment=environment)
        # ...and one with a malformed configuration
        with self.assertRaises(gate.GateOrderingError):
            gate.FinalHeadRequest(
                git_commit_sha="a" * 40,
                suite=dict(suite, suite_config=sample_suite_config(jobs=0)),
                environment=environment)


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
        # canonical runner result shaped from the launch identity's own
        # suite population AND configuration (a bare {"ok": True,
        # "count": 3} is FORGED and must fail closed — see the
        # forged-completion controls)
        suite = identity["suite"]
        canonical = {"schema": gate.RUNNER_SCHEMA, "ok": True,
                     "serial_digest": suite["serial_digest"],
                     "executed_digest": suite["executed_digest"],
                     "count": suite["count"],
                     "suite_config": suite["suite_config"]}
        guard.write_completion(canonical, started_unix=1.0)
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
             "git_commit_sha": "1" * 40, "ok": True, "result": canonical,
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
        identity = gate.launch_request_identity(repo)

        def fake_suite():
            launches.append(time.time())
            release.wait(10)  # hold the "suite" so the duplicate must attach
            return canonical_result_for(identity)

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
        expected = canonical_result_for(identity)
        self.assertEqual(results["first"], expected)
        self.assertEqual(results["second"], expected,
                         "attacher must consume the owner's result")

    def test_head_drift_forces_fresh_execution(self):
        repo = self._fixture_repo()
        lock_dir = repo.parent / "locks2"
        launches = []

        def fake_suite():
            launches.append(1)
            identity = gate.launch_request_identity(repo)
            result = canonical_result_for(identity)
            result["head"] = gate.git_commit_sha(repo)
            return result

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
            return canonical_result_for(gate.launch_request_identity(repo))

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
                            "tests/test_issue184_final_closure.py",
                            # Issue #215 V2-C: additive campaign surface
                            # (evidence namespace, living hardware docs,
                            # producers, controls) pending on main.
                            "scripts/issue215_",
                            "tests/test_issue215_",
                            "docs/investigations/vulkan-v2-c-v340l-platform-stability/",
                            "docs/hardware/")
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
            "payload = run_single_head_suite(args.root, tests_dir=tests_dir,",
            source)


class DirtyWorktreeGuardTests(unittest.TestCase):
    """Controls 27-30 — clean committed worktree is a PREREQUISITE to
    launch identity derivation, completion lookup/reuse, attach, and
    launch (all would PASS on 43367f8 where a dirty tree could consume a
    prior clean-head completion)."""

    def _repo(self):
        repo = make_guard_fixture_repo(self.addCleanup)
        lock_dir = repo.parent / "guard-locks"
        launches: list[float] = []

        def fake_suite():
            launches.append(time.time())
            return canonical_result_for(gate.launch_request_identity(repo))

        return repo, lock_dir, launches, fake_suite

    def test_control27_dirty_production_code_refused(self):
        # A. clean PASS first, then uncommitted tracked production drift:
        # the second guarded request MUST be refused — not launched, and
        # the cached PASS must NOT come back out.
        repo, lock_dir, launches, fake_suite = self._repo()
        first = gate.run_single_head_suite(repo, suite_command=fake_suite,
                                           lock_dir=lock_dir)
        self.assertTrue(first["ok"])
        self.assertEqual(len(launches), 1)
        (repo / "tool.py").write_text("VALUE = 2\n", encoding="utf-8")
        with self.assertRaises(gate.GateOrderingError) as caught:
            gate.run_single_head_suite(repo, suite_command=fake_suite,
                                       lock_dir=lock_dir)
        self.assertIn("dirty Git worktree", str(caught.exception))
        # the underlying suite was NOT launched for the dirty request
        self.assertEqual(len(launches), 1)
        # identity derivation itself is refused (before any lookup)
        with self.assertRaises(gate.GateOrderingError):
            gate.launch_request_identity(repo)
        # the canonical runner seam surfaces the same refusal under the
        # runner's own error contract
        with self.assertRaises(runner.SuiteError):
            runner.run_single_head_suite(repo)

    def test_control28_dirty_test_body_same_id_refused(self):
        # B. modify an existing test's body WITHOUT changing its ID or
        # the suite count: identity stays the same, so on 43367f8 the
        # prior completion would be consumed; it MUST be refused instead.
        repo, lock_dir, launches, fake_suite = self._repo()
        gate.run_single_head_suite(repo, suite_command=fake_suite,
                                   lock_dir=lock_dir)
        self.assertEqual(len(launches), 1)
        module = next((repo / "tests").glob("test_*.py"))
        module.write_text(
            "import unittest\nclass A(unittest.TestCase):\n"
            " def test_x(self): self.assertTrue(False)\n",  # body drift
            encoding="utf-8")
        with self.assertRaises(gate.GateOrderingError):
            gate.run_single_head_suite(repo, suite_command=fake_suite,
                                       lock_dir=lock_dir)
        self.assertEqual(len(launches), 1,
                         "dirty request must not reach the suite")
        # discard the drift: SAME committed head, same test-ID population
        # — proving the refusal was driven by the dirty tree, not by an
        # identity change, and that valid reuse resumes at the same head
        subprocess.run(("git", "checkout", "--", "."), cwd=repo, check=True)
        gate.run_single_head_suite(repo, suite_command=fake_suite,
                                   lock_dir=lock_dir)
        self.assertEqual(len(launches), 1,
                         "same committed head: reuse, not relaunch")

    def test_control29_staged_uncommitted_drift_refused(self):
        # C. `git add` a tracked modification (staged, uncommitted):
        # refusal is required exactly like unstaged drift.
        repo, lock_dir, launches, fake_suite = self._repo()
        gate.run_single_head_suite(repo, suite_command=fake_suite,
                                   lock_dir=lock_dir)
        (repo / "tool.py").write_text("VALUE = 3\n", encoding="utf-8")
        subprocess.run(("git", "add", "tool.py"), cwd=repo, check=True)
        with self.assertRaises(gate.GateOrderingError):
            gate.run_single_head_suite(repo, suite_command=fake_suite,
                                       lock_dir=lock_dir)
        self.assertEqual(len(launches), 1)

    def test_control30_untracked_dirtiness_matches_runner_doctrine(self):
        # D. untracked files count as dirtiness under the SAME
        # `git status --porcelain` census the runner uses — the guard
        # must agree with the runner's own verdict on the same tree.
        repo, lock_dir, launches, fake_suite = self._repo()
        gate.run_single_head_suite(repo, suite_command=fake_suite,
                                   lock_dir=lock_dir)
        (repo / "untracked.txt").write_text("dirt\n", encoding="utf-8")
        try:
            runner.run_suite(repo)
            runner_refused = False
        except runner.SuiteError:
            runner_refused = True  # runner refuses (dirty by its census)
        try:
            gate.run_single_head_suite(repo, suite_command=fake_suite,
                                       lock_dir=lock_dir)
            guard_refused = False
        except gate.GateOrderingError:
            guard_refused = True
        self.assertIs(guard_refused, runner_refused,
                      "guard must mirror the runner's dirty verdict on "
                      "the identical tree")
        self.assertEqual(len(launches),
                         2 if not guard_refused else 1,
                         "a clean-by-census tree would reuse/launch through "
                         "the guard's own fake suite; a dirty one must "
                         "refuse before launching")


class CompletionHardeningTests(unittest.TestCase):
    """Controls 31-37 — a completion receipt mechanically validated
    against the launch identity; malformed/forged/inconsistent records
    can never suppress a fresh suite launch (all fail on 43367f8)."""

    def _identity_and_guard(self):
        guard_dir = Path(tempfile.mkdtemp(prefix="issue213-hard-"))
        self.addCleanup(lambda: subprocess.run(
            ["rm", "-rf", str(guard_dir)], check=False))
        identity = make_final_head(sha="3" * 40).to_dict() | {
            "schema": gate.LAUNCH_IDENTITY_SCHEMA}
        guard = gate.LaunchGuard(identity, lock_dir=guard_dir)
        return identity, guard

    def _forge(self, guard, *, result, ok=True, sha="3" * 40):
        guard.completion_path().write_text(json.dumps(
            {"schema": gate.COMPLETION_SCHEMA, "key": guard.key,
             "git_commit_sha": sha, "ok": ok, "result": result,
             "started_unix": 1.0, "ended_unix": 2.0}), encoding="utf-8")

    def test_control31_forged_minimal_result_fails_closed(self):
        # E. correct key + correct SHA + {"ok": true} (or any incomplete
        # result) MUST fail closed, never authorize reuse.
        identity, guard = self._identity_and_guard()
        for forged in ({"ok": True}, {"ok": True, "count": 3},
                       {}, "not-a-dict"):
            self._forge(guard, result=forged)
            with self.assertRaises(gate.GateOrderingError):
                guard.find_valid_completion()

    def test_control32_wrong_result_count_rejected(self):
        # F. correct key/SHA but a runner-result count differing from the
        # launch identity suite count => reject.
        identity, guard = self._identity_and_guard()
        suite = identity["suite"]
        result = {"schema": gate.RUNNER_SCHEMA, "ok": True,
                  "serial_digest": suite["serial_digest"],
                  "executed_digest": suite["executed_digest"],
                  "count": suite["count"] + 5}
        self._forge(guard, result=result)
        with self.assertRaises(gate.GateOrderingError):
            guard.find_valid_completion()

    def test_control33_wrong_or_malformed_digests_rejected(self):
        # G. malformed, unequal, or launch-identity-mismatched digests.
        identity, guard = self._identity_and_guard()
        suite = identity["suite"]
        other = "a" * 64
        cases = [
            # malformed shape
            {"schema": gate.RUNNER_SCHEMA, "ok": True,
             "serial_digest": "not-hex", "executed_digest": "not-hex",
             "count": suite["count"]},
            # serial != executed on a PASS
            {"schema": gate.RUNNER_SCHEMA, "ok": True,
             "serial_digest": suite["serial_digest"],
             "executed_digest": other, "count": suite["count"]},
            # well-formed but bound to a DIFFERENT population than the
            # launch identity's
            {"schema": gate.RUNNER_SCHEMA, "ok": True,
             "serial_digest": other, "executed_digest": other,
             "count": suite["count"]},
        ]
        for result in cases:
            self._forge(guard, result=result)
            with self.assertRaises(gate.GateOrderingError):
                guard.find_valid_completion()

    def test_control34_outcome_flag_inconsistency_fails_closed(self):
        # H. top-level success + runner-result failure, and vice versa.
        identity, guard = self._identity_and_guard()
        suite = identity["suite"]
        pass_result = {"schema": gate.RUNNER_SCHEMA, "ok": True,
                       "serial_digest": suite["serial_digest"],
                       "executed_digest": suite["executed_digest"],
                       "count": suite["count"]}
        fail_result = dict(pass_result, ok=False, executed_digest=None)
        # completion says ok=True, runner result says ok=False
        self._forge(guard, result=fail_result, ok=True)
        with self.assertRaises(gate.GateOrderingError):
            guard.find_valid_completion()
        # completion says ok=False, runner result says ok=True
        self._forge(guard, result=pass_result, ok=False)
        with self.assertRaises(gate.GateOrderingError):
            guard.find_valid_completion(allow_fail=True)

    def test_control35_completed_fail_policy(self):
        # A completed FAIL is structurally valid (deliverable to a
        # concurrent ATTACHER via allow_fail=True) but is NEVER a
        # reusable PASS: the default reuse path ignores it, so a later
        # independent invocation launches a fresh suite.
        identity, guard = self._identity_and_guard()
        fail_result = canonical_result_for(identity, ok=False)
        self._forge(guard, result=fail_result, ok=False)
        # attacher path may consume the bounded completed failure
        record = guard.find_valid_completion(allow_fail=True)
        self.assertIsNotNone(record)
        self.assertFalse(record["ok"])
        # reuse path must NOT consume it
        self.assertIsNone(guard.find_valid_completion())

    def test_control36_fail_completion_never_suppresses_fresh_launch(self):
        # The documented policy, proven end to end: after a suite FAIL on
        # a clean exact head, a later independent identical invocation
        # RERUNS the suite (two real launches), while a concurrent
        # attacher would have consumed the one bounded FAIL result.
        repo = make_guard_fixture_repo(self.addCleanup)
        lock_dir = repo.parent / "policy-locks"
        launches = []

        def failing_suite():
            launches.append(1)
            return canonical_result_for(
                gate.launch_request_identity(repo), ok=False)

        first = gate.run_single_head_suite(repo, suite_command=failing_suite,
                                           lock_dir=lock_dir)
        self.assertFalse(first["ok"])
        second = gate.run_single_head_suite(repo, suite_command=failing_suite,
                                            lock_dir=lock_dir)
        self.assertFalse(second["ok"])
        self.assertEqual(len(launches), 2,
                         "a completed FAIL must be rerun by a later "
                         "independent invocation, never reused as "
                         "launch suppression")

    def test_control37_canonical_pass_completion_round_trip(self):
        # Positive control: a canonical PASS completion bound to the
        # launch identity IS reusable (find_valid_completion returns it).
        identity, guard = self._identity_and_guard()
        guard.write_completion(canonical_result_for(identity),
                               started_unix=1.0)
        record = guard.find_valid_completion()
        self.assertIsNotNone(record)
        self.assertTrue(record["ok"])
        self.assertEqual(record["result"]["count"],
                         identity["suite"]["count"])


class SuiteConfigurationIdentityTests(unittest.TestCase):
    """Controls 38-46 (Issue #213 configuration-identity correction) —
    REAL invocation-path configuration drift, all of which FAIL on the
    pre-correction head 376e978 where the launch identity ignored the
    requested configuration and `--tests-dir` never reached the guarded
    execution path."""

    def _repo(self, add_cleanup, *, tree_b=False, default_tree=True,
              module_count=1):
        """Clean committed fixture with default tree A and optional tree B."""
        global _guard_repo_seq
        _guard_repo_seq += 1
        prefix = f"issue213k{_guard_repo_seq}"
        root = Path(tempfile.mkdtemp(prefix=f"{prefix}-root-"))
        add_cleanup(lambda: subprocess.run(["rm", "-rf", str(root)], check=False))
        repo = root / "repo"
        repo.mkdir()
        for cmd in (("git", "init", "-q"),
                    ("git", "config", "user.email", "t@example.invalid"),
                    ("git", "config", "user.name", "t")):
            subprocess.run(cmd, cwd=repo, check=True)
        if default_tree:
            (repo / "tests").mkdir()
            for extra in range(max(0, module_count - 1)):
                module_extra = f"test_{prefix}a{extra}"
                add_cleanup(sys.modules.pop, module_extra, None)
                (repo / "tests" / f"{module_extra}.py").write_text(
                    "import unittest\nclass A(unittest.TestCase):\n"
                    f" def test_tree_a{extra}(self): pass\n", encoding="utf-8")
            module_a = f"test_{prefix}a"
            add_cleanup(sys.modules.pop, module_a, None)
            (repo / "tests" / f"{module_a}.py").write_text(
                "import unittest\nclass A(unittest.TestCase):\n"
                " def test_tree_a(self): pass\n", encoding="utf-8")
        if tree_b:
            (repo / "tree_b").mkdir()
            module_b = f"test_{prefix}b"
            add_cleanup(sys.modules.pop, module_b, None)
            (repo / "tree_b" / f"{module_b}.py").write_text(
                "import unittest\nclass B(unittest.TestCase):\n"
                " def test_tree_b(self): pass\n", encoding="utf-8")
        for rel in gate.ENV_AUTHORITY_FILES:
            path = repo / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("authority\n", encoding="utf-8")
        subprocess.run(("git", "add", "-A"), cwd=repo, check=True)
        subprocess.run(("git", "commit", "-qm", "init"), cwd=repo, check=True)
        return repo

    def _patched_runner(self, repo):
        """Patch runner.run_suite to record (root, tests_dir, jobs, timeout,
        retain_dir) per launch and delegate to the real implementation."""
        calls = []
        original = runner.run_suite

        def recording(root, tests_dir=None, **kwargs):
            calls.append({"root": str(root),
                          "tests_dir": str(tests_dir or Path(root) / "tests"),
                          "jobs": kwargs.get("jobs"),
                          "timeout": kwargs.get("timeout"),
                          "retain_dir": kwargs.get("retain_dir")})
            return original(Path(root), tests_dir, **kwargs)

        runner.run_suite = recording
        self.addCleanup(setattr, runner, "run_suite", original)
        return calls

    def _scrub_pycache(self, repo: Path) -> None:
        """Remove untracked __pycache__ left by direct run_suite imports.

        Guarded identity derivation imports discovery under
        ``dont_write_bytecode``, but a bare ``runner.run_suite`` call
        imports first and writes bytecode into the fixture tree.
        """
        subprocess.run(["find", str(repo), "-name", "__pycache__",
                        "-type", "d", "-exec", "rm", "-rf", "{}", "+"],
                       check=False)

    # A. jobs drift: guarded run with jobs=1 then jobs=2 on the same
    # head/environment requires a SECOND underlying launch, and each
    # returned result's jobs matches its request.
    def test_control38_jobs_drift_requires_second_launch(self):
        repo = self._repo(self.addCleanup, module_count=4)
        lock_dir = repo.parent / "locks"
        calls = self._patched_runner(repo)
        first = gate.run_single_head_suite(repo, jobs=1, lock_dir=lock_dir)
        self.assertTrue(first["ok"])
        self.assertEqual(first["jobs"], 1)
        second = gate.run_single_head_suite(repo, jobs=2, lock_dir=lock_dir)
        self.assertTrue(second["ok"])
        self.assertEqual(second["jobs"], 2,
                         "returned jobs must correspond to each request")
        self.assertEqual(len(calls), 2,
                         "jobs drift must require a second underlying launch")
        self.assertEqual([c["jobs"] for c in calls], [1, 2])

    # A2. explicit jobs=1 vs jobs=3 (different task plans) also distinct.
    def test_control38_explicit_jobs_distinguishable(self):
        repo = self._repo(self.addCleanup, module_count=4)
        lock_dir = repo.parent / "locks"
        calls = self._patched_runner(repo)
        gate.run_single_head_suite(repo, jobs=1, lock_dir=lock_dir)
        gate.run_single_head_suite(repo, jobs=3, lock_dir=lock_dir)
        self.assertEqual(len(calls), 2)

    # B. reverse jobs drift: default/cached run first; an explicit jobs=1
    # request must NOT consume the default run's completion.
    def test_control39_reverse_jobs_drift_no_reuse(self):
        repo = self._repo(self.addCleanup, module_count=4)
        lock_dir = repo.parent / "locks"
        calls = self._patched_runner(repo)
        default = gate.run_single_head_suite(repo, lock_dir=lock_dir)
        self.assertTrue(default["ok"])
        self.assertGreater(default["jobs"], 1,
                           "fixture must give the default schedule more "
                           "than one worker")
        second = gate.run_single_head_suite(repo, jobs=1, lock_dir=lock_dir)
        self.assertTrue(second["ok"])
        self.assertEqual(len(calls), 2,
                         "default-run completion must not satisfy a "
                         "jobs=1 request")
        self.assertEqual(second["jobs"], 1)

    # C. timeout drift: materially different timeout => distinct execution
    # identity / fresh launch.
    def test_control40_timeout_drift_requires_fresh_launch(self):
        repo = self._repo(self.addCleanup)
        lock_dir = repo.parent / "locks"
        calls = self._patched_runner(repo)
        first = gate.run_single_head_suite(repo, timeout=600.0,
                                           lock_dir=lock_dir)
        self.assertTrue(first["ok"])
        second = gate.run_single_head_suite(repo, timeout=3600.0,
                                            lock_dir=lock_dir)
        self.assertTrue(second["ok"])
        self.assertEqual(len(calls), 2,
                         "timeout drift must force a fresh launch — a "
                         "long-timeout PASS may not masquerade under a "
                         "shorter timeout")
        self.assertEqual([c["timeout"] for c in calls], [600.0, 3600.0])
        # distinct launch identities record distinct suite configurations
        id_a = gate.launch_request_identity(repo, timeout=600.0)
        id_b = gate.launch_request_identity(repo, timeout=3600.0)
        self.assertNotEqual(id_a["suite"]["suite_config"],
                            id_b["suite"]["suite_config"])

    # D. custom tests directory honored: guarded invocation with
    # tests_dir=B executes B, not A.
    def test_control41_custom_tests_dir_executes_tree_b(self):
        repo = self._repo(self.addCleanup, tree_b=True)
        lock_dir = repo.parent / "locks"
        calls = self._patched_runner(repo)
        result = gate.run_single_head_suite(repo, tests_dir=repo / "tree_b",
                                            lock_dir=lock_dir)
        self.assertTrue(result["ok"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(Path(calls[0]["tests_dir"]).name, "tree_b",
                         "the guarded path must execute the requested "
                         "tests tree, not the default")
        executed = result["serial_ids"]
        self.assertTrue(any("tree_b" in test_id for test_id in executed),
                        f"expected tree B population, got {executed}")
        self.assertFalse(any("tree_a" in test_id for test_id in executed))

    # E. default-cache cannot satisfy a custom tests directory: fresh
    # execution and custom population result.
    def test_control42_default_run_cannot_satisfy_custom_tree(self):
        repo = self._repo(self.addCleanup, tree_b=True)
        lock_dir = repo.parent / "locks"
        calls = self._patched_runner(repo)
        default = gate.run_single_head_suite(repo, lock_dir=lock_dir)
        self.assertTrue(default["ok"])
        self.assertFalse(any("tree_b" in t for t in default["serial_ids"]))
        custom = gate.run_single_head_suite(repo, tests_dir=repo / "tree_b",
                                            lock_dir=lock_dir)
        self.assertTrue(custom["ok"])
        self.assertEqual(len(calls), 2,
                         "a default-tree completion must never satisfy a "
                         "custom tests-directory request")
        self.assertTrue(any("tree_b" in t for t in custom["serial_ids"]))
        self.assertNotEqual(default["serial_digest"],
                            custom["serial_digest"])

    # E2. fail-closed: a tests directory outside the repository root is
    # refused for a Git-backed guarded request, never cached.
    def test_control42_external_tests_dir_fails_closed(self):
        repo = self._repo(self.addCleanup)
        calls = self._patched_runner(repo)
        external = repo.parent / "external-tests"
        external.mkdir(exist_ok=True)
        (external / "test_external_probe.py").write_text(
            "import unittest\nclass X(unittest.TestCase):\n"
            " def test_x(self): pass\n", encoding="utf-8")
        self.addCleanup(sys.modules.pop, "test_external_probe", None)
        with self.assertRaises(gate.GateOrderingError) as caught:
            gate.run_single_head_suite(repo, tests_dir=external,
                                       lock_dir=repo.parent / "locks")
        self.assertIn("inside the repository root", str(caught.exception))
        self.assertEqual(len(calls), 0,
                         "no underlying launch may occur for an unprovable "
                         "external tests tree")

    # F. retain-dir after a non-retained PASS: the documented retained
    # per-task artifacts must be produced, not the old cached payload.
    def test_control43_retain_dir_after_non_retained_pass(self):
        repo = self._repo(self.addCleanup)
        lock_dir = repo.parent / "locks"
        calls = self._patched_runner(repo)
        first = gate.run_single_head_suite(repo, lock_dir=lock_dir)
        self.assertTrue(first["ok"])
        self.assertEqual(len(calls), 1)
        retain_dir = repo.parent / "retained"
        second = gate.run_single_head_suite(repo, retain_dir=retain_dir,
                                            lock_dir=lock_dir)
        self.assertTrue(second["ok"])
        self.assertEqual(len(calls), 2,
                         "a non-retained PASS must be rerun to produce the "
                         "requested retained artifacts")
        task_count = len(second["tasks"])
        self.assertGreaterEqual(task_count, 1)
        for index in range(task_count):
            for suffix in ("-modules.json", "-expected.json", ".json",
                           "-stdout.txt", "-stderr.txt"):
                self.assertTrue(
                    (retain_dir / f"task-{index}{suffix}").is_file(),
                    f"missing documented retained artifact task-{index}"
                    f"{suffix}")
        # The CLI produces the full documented retained set INCLUDING
        # summary.json (the seam produces the per-task artifacts; the CLI
        # adds the summary) — proven through a real CLI invocation on a
        # fresh retain directory.
        cli_retain = repo.parent / "retained-cli"
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "run_full_cpu_suite.py"),
             "--root", str(repo), "--retain-dir", str(cli_retain),
             "--json"],
            capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue((cli_retain / "summary.json").is_file(),
                        "the CLI must produce summary.json alongside the "
                        "per-task retained artifacts")

    # F2. concurrent identical requests WITH the same retention request
    # still deduplicate (exactly-one launch + attach).
    def test_control44_concurrent_retained_requests_deduplicate(self):
        repo = self._repo(self.addCleanup)
        lock_dir = repo.parent / "locks"
        calls = self._patched_runner(repo)
        retain_dir = repo.parent / "retained-conc"
        launches = []
        release = threading.Event()
        original = runner.run_suite

        def slow_suite(root, tests_dir=None, **kwargs):
            launches.append(time.time())
            release.wait(10)
            return original(Path(root), tests_dir, **kwargs)

        runner.run_suite = slow_suite
        self.addCleanup(setattr, runner, "run_suite", original)
        results = {}

        def starter(name):
            try:
                results[name] = gate.run_single_head_suite(
                    repo, retain_dir=retain_dir, lock_dir=lock_dir)
            except BaseException as error:  # noqa: BLE001
                results[name] = error

        first = threading.Thread(target=starter, args=("first",))
        first.start()
        deadline = time.monotonic() + 10
        while not launches and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(len(launches), 1)
        second = threading.Thread(target=starter, args=("second",))
        second.start()
        time.sleep(0.3)
        self.assertEqual(len(launches), 1,
                         "concurrent identical retained requests must "
                         "deduplicate, not relaunch")
        release.set()
        first.join(30)
        second.join(30)
        self.assertEqual(len(launches), 1)
        self.assertTrue(results["first"]["ok"])
        self.assertTrue(results["second"]["ok"])

    # G. identical full configuration: sequential PASS reuse preserved.
    def test_control45_identical_config_reuses(self):
        repo = self._repo(self.addCleanup)
        lock_dir = repo.parent / "locks"
        calls = self._patched_runner(repo)
        first = gate.run_single_head_suite(repo, jobs=1, timeout=900.0,
                                           lock_dir=lock_dir)
        self.assertTrue(first["ok"])
        second = gate.run_single_head_suite(repo, jobs=1, timeout=900.0,
                                            lock_dir=lock_dir)
        self.assertTrue(second["ok"])
        self.assertEqual(len(calls), 1,
                         "identical full configuration must reuse the "
                         "sequential PASS")

    # H. default-vs-explicit jobs equivalence when schedules coincide:
    # default jobs on a one-module population IS jobs=1 — requests whose
    # EFFECTIVE schedules and configurations coincide may attach/reuse.
    def test_control46_equivalent_default_and_explicit_jobs(self):
        repo = self._repo(self.addCleanup)
        lock_dir = repo.parent / "locks"
        calls = self._patched_runner(repo)
        default = gate.run_single_head_suite(repo, lock_dir=lock_dir)
        self.assertTrue(default["ok"])
        explicit = gate.run_single_head_suite(repo, jobs=1,
                                              lock_dir=lock_dir)
        self.assertTrue(explicit["ok"])
        self.assertEqual(len(calls), 1,
                         "requests with the SAME effective jobs/config "
                         "must deduplicate normally")

    # I. receipt configuration drift: a receipt under configuration A
    # cannot satisfy an independently derived request under configuration
    # B even with identical serial IDs/count.
    def test_control47_receipt_config_drift_rejected(self):
        repo = self._repo(self.addCleanup, module_count=4)
        # Build a receipt under configuration A (jobs=2 schedule).  A bare
        # run_suite import writes fixture bytecode; scrub it so the tree
        # is clean for receipt derivation exactly as the guarded path
        # guarantees (dont_write_bytecode) for its own imports.
        result_a = runner.run_suite(repo, jobs=2)
        self.assertTrue(result_a["ok"])
        self._scrub_pycache(repo)
        receipt_a = gate.build_receipt(
            repo, result_a, started_unix=1.0, ended_unix=2.0)
        # Independently derive request B: default configuration.
        request_b = gate.current_final_head_request(repo)
        self.assertFalse(
            gate.validate_receipt(receipt_a.to_dict(), request_b.to_dict()),
            "a receipt produced under jobs=2 must not satisfy the default "
            "configuration request even with identical test IDs/count")
        self.assertEqual(receipt_a.suite["count"], request_b.suite["count"])
        self.assertEqual(receipt_a.suite["serial_digest"],
                         request_b.suite["serial_digest"])
        # and the reverse: a default-configuration receipt vs a jobs=2
        # request
        result_default = runner.run_suite(repo)
        self.assertTrue(result_default["ok"])
        self._scrub_pycache(repo)
        receipt_default = gate.build_receipt(
            repo, result_default, started_unix=3.0, ended_unix=4.0)
        request_a = gate.current_final_head_request(repo, jobs=2)
        self.assertFalse(
            gate.validate_receipt(receipt_default.to_dict(),
                                  request_a.to_dict()))


class CustomTestsTreeHeadBindingTests(unittest.TestCase):
    """Controls 48-51 (Issue #213 custom tests-tree HEAD-binding
    correction) — REAL invocation-path proof that a custom ``--tests-dir``
    is mechanically bound to the exact committed head.  Controls 48 and 49
    FAIL on the pre-correction head 749c921, where "inside the repository
    root + clean ``git status --porcelain``" was incorrectly accepted as
    proof that every file below an arbitrary in-repo directory is tracked
    — false for ignored in-repo trees such as ``scratch/``."""

    def _repo(self, add_cleanup, *, tracked_tree=None,
              gitignore=("__pycache__/", "scratch/"),
              ignored_custom_tree=False):
        """Clean committed fixture repo with an InferSwarm-equivalent
        ignore rule set, an optional COMMITTED custom tests tree, and an
        optional UNCOMMITTED custom tests tree inside the ignored
        ``scratch/`` tree."""
        global _guard_repo_seq
        _guard_repo_seq += 1
        prefix = f"issue213h{_guard_repo_seq}"
        root = Path(tempfile.mkdtemp(prefix=f"{prefix}-root-"))
        add_cleanup(lambda: subprocess.run(["rm", "-rf", str(root)], check=False))
        repo = root / "repo"
        repo.mkdir()
        for cmd in (("git", "init", "-q"),
                    ("git", "config", "user.email", "t@example.invalid"),
                    ("git", "config", "user.name", "t")):
            subprocess.run(cmd, cwd=repo, check=True)
        (repo / ".gitignore").write_text(
            "\n".join(gitignore) + "\n", encoding="utf-8")
        (repo / "tests").mkdir()
        module_default = f"test_{prefix}d"
        add_cleanup(sys.modules.pop, module_default, None)
        (repo / "tests" / f"{module_default}.py").write_text(
            "import unittest\nclass A(unittest.TestCase):\n"
            " def test_default(self): pass\n", encoding="utf-8")
        if tracked_tree is not None:
            tree = repo / tracked_tree
            tree.mkdir()
            module_t = f"test_{prefix}t"
            add_cleanup(sys.modules.pop, module_t, None)
            (tree / f"{module_t}.py").write_text(
                "import unittest\nclass T(unittest.TestCase):\n"
                " def test_tracked(self): self.assertTrue(True)\n",
                encoding="utf-8")
        if ignored_custom_tree:
            scratch_tree = repo / "scratch" / "custom-tests"
            scratch_tree.mkdir(parents=True)
            module_i = f"test_{prefix}i"
            add_cleanup(sys.modules.pop, module_i, None)
            (scratch_tree / f"{module_i}.py").write_text(
                "import unittest\nclass I(unittest.TestCase):\n"
                " def test_ignored(self): self.assertTrue(True)\n",
                encoding="utf-8")
        for rel in gate.ENV_AUTHORITY_FILES:
            path = repo / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("authority\n", encoding="utf-8")
        subprocess.run(("git", "add", "-A"), cwd=repo, check=True)
        subprocess.run(("git", "commit", "-qm", "init"), cwd=repo, check=True)
        return repo

    def _patched_runner(self):
        calls = []
        original = runner.run_suite

        def recording(root, tests_dir=None, **kwargs):
            calls.append({"root": str(root),
                          "tests_dir": str(tests_dir or Path(root) / "tests")})
            return original(Path(root), tests_dir, **kwargs)

        runner.run_suite = recording
        self.addCleanup(setattr, runner, "run_suite", original)
        return calls

    def _porcelain(self, repo: Path) -> str:
        proc = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                              capture_output=True, text=True)
        return proc.stdout

    # A. ignored in-repo custom tree: the uncommitted ignored module is
    # invisible to the ordinary clean-worktree census, yet the guarded
    # request must fail closed before any underlying launch.
    def test_control48_ignored_custom_tree_fails_closed(self):
        repo = self._repo(self.addCleanup, ignored_custom_tree=True)
        calls = self._patched_runner()
        # Mechanical premise: the ignored in-repo tree leaves the ordinary
        # census CLEAN — this is exactly what fooled the pre-fix proof.
        self.assertEqual(self._porcelain(repo), "",
                         "fixture premise: an ignored in-repo tree is "
                         "invisible to git status --porcelain")
        self.assertTrue((repo / "scratch" / "custom-tests").is_dir())
        with self.assertRaises(gate.GateOrderingError) as caught:
            gate.run_single_head_suite(
                repo, tests_dir=repo / "scratch" / "custom-tests",
                lock_dir=repo.parent / "locks")
        self.assertIn("ignored by Git", str(caught.exception))
        self.assertEqual(len(calls), 0,
                         "fail-closed must precede the underlying launch")

    # B. ignored-body mutation cannot reuse: mechanically reproduces the
    # pre-fix vulnerability (pass-3 _require_head_bound_tests_dir body),
    # then proves the corrected guard refuses the ignored tree so no
    # cached PASS can ever be returned for mutated ignored content.
    #
    # The pre-fix defect is that the launch identity itself was derived
    # from unproven (ignored, HEAD-invisible) content: the guard claimed
    # "every file under the tree is tracked and byte-identical to HEAD"
    # without any tracked-tree proof.  Once ANY execution produces a
    # completion for that identity (modeled here through the module's own
    # suite_command seam — e.g. an execution path not covered by the
    # runner's detached-worktree doctrine), a body mutation that keeps
    # the test ID and count invisible to git status leaves the identity
    # UNCHANGED, and the mutated request silently consumes the cached
    # PASS.  The corrected code refuses the ignored tree BEFORE identity
    # derivation and completion lookup, so no cached PASS can be returned.
    def test_control49_ignored_body_mutation_cannot_reuse(self):
        repo = self._repo(self.addCleanup, ignored_custom_tree=True)
        scratch_tree = repo / "scratch" / "custom-tests"
        ignored_module = next(scratch_tree.glob("test_*.py"))
        lock_dir = repo.parent / "locks"
        launches = []

        # Pre-fix behavior, reproduced mechanically: the 749c921 proof
        # (inside-root + not-.git + is-dir + clean ordinary status).
        real_guard = gate._require_head_bound_tests_dir

        def pre_fix_proof(root, tests_dir):
            root, tests_dir = Path(root).resolve(), Path(tests_dir).resolve()
            relative = tests_dir.relative_to(root)
            assert relative.parts[0] != ".git" and tests_dir.is_dir()

        def fake_execution():
            launches.append(time.time())
            return dict(pre_fix_pass_result)  # canonical PASS payload

        gate._require_head_bound_tests_dir = pre_fix_proof
        try:
            # "First execution exists": the pre-fix guard accepted the
            # ignored tree and derived its identity from the LIVE tree's
            # discovery (ignored content hashed into the identity).
            identity = gate.launch_request_identity(repo,
                                                    tests_dir=scratch_tree)
            pre_fix_pass_result = {
                "schema": gate.RUNNER_SCHEMA, "ok": True,
                "serial_digest": identity["suite"]["serial_digest"],
                "executed_digest": identity["suite"]["executed_digest"],
                "count": identity["suite"]["count"],
                "suite_config": identity["suite"]["suite_config"],
            }
            first = gate.run_single_head_suite(repo, tests_dir=scratch_tree,
                                               lock_dir=lock_dir,
                                               suite_command=fake_execution)
            self.assertTrue(first["ok"])
            self.assertEqual(len(launches), 1)
            # Stable test ID, same count: mutate ONLY the ignored body.
            ignored_module.write_text(
                ignored_module.read_text(encoding="utf-8").replace(
                    "assertTrue(True)", "assertTrue(False)"),
                encoding="utf-8")
            self.assertEqual(self._porcelain(repo), "",
                             "ignored-body mutation stays invisible to the "
                             "ordinary census — the pre-fix identity would "
                             "remain reusable")
            second = gate.run_single_head_suite(repo, tests_dir=scratch_tree,
                                                lock_dir=lock_dir,
                                                suite_command=fake_execution)
            # THE VULNERABILITY: the mutated (now failing) body's request
            # consumed the first body's cached PASS without a new launch.
            self.assertTrue(second["ok"])
            self.assertEqual(len(launches), 1,
                             "pre-fix proof reused the completion across an "
                             "invisible ignored-body mutation")
        finally:
            gate._require_head_bound_tests_dir = real_guard
        # Corrected code: the ignored tree is rejected BEFORE identity
        # derivation, completion lookup, reuse, or launch — no cached
        # PASS can be returned.
        self.assertEqual(self._porcelain(repo), "")
        with self.assertRaises(gate.GateOrderingError) as caught:
            gate.run_single_head_suite(repo, tests_dir=scratch_tree,
                                       lock_dir=lock_dir,
                                       suite_command=fake_execution)
        self.assertIn("ignored by Git", str(caught.exception))
        self.assertEqual(len(launches), 1,
                         "corrected guard must refuse before any new launch")

    # C. tracked custom tree remains valid: guarded execution succeeds and
    # sequential exact-config reuse still works; ignored __pycache__ noise
    # inside the tracked custom tree does not over-reject.
    def test_control50_tracked_custom_tree_valid_and_reuses(self):
        repo = self._repo(self.addCleanup, tracked_tree="tree_c")
        calls = self._patched_runner()
        lock_dir = repo.parent / "locks"
        first = gate.run_single_head_suite(repo, tests_dir=repo / "tree_c",
                                           lock_dir=lock_dir)
        self.assertTrue(first["ok"])
        self.assertTrue(any("test_tracked" in t for t in first["serial_ids"]))
        self.assertEqual(Path(calls[0]["tests_dir"]).name, "tree_c")
        # Ordinary ignored bytecode noise inside the custom tree must not
        # turn the scoped HEAD-binding proof into a rejection.
        pycache = repo / "tree_c" / "__pycache__"
        pycache.mkdir()
        (pycache / "noise.cpython-312.pyc").write_bytes(b"\x00noise")
        self.assertEqual(self._porcelain(repo), "")
        second = gate.run_single_head_suite(repo, tests_dir=repo / "tree_c",
                                            lock_dir=lock_dir)
        self.assertTrue(second["ok"])
        self.assertEqual(len(calls), 1,
                         "identical exact-config request on a tracked custom "
                         "tree must reuse the sequential PASS")

    # D. tracked custom tree modification: an uncommitted body change in
    # the tracked custom tree is refused by the existing dirty-worktree
    # doctrine BEFORE reuse or launch, even with a live completion present.
    def test_control51_tracked_custom_tree_modification_refused(self):
        repo = self._repo(self.addCleanup, tracked_tree="tree_c")
        calls = self._patched_runner()
        lock_dir = repo.parent / "locks"
        first = gate.run_single_head_suite(repo, tests_dir=repo / "tree_c",
                                           lock_dir=lock_dir)
        self.assertTrue(first["ok"])
        self.assertEqual(len(calls), 1)
        tracked_module = next((repo / "tree_c").glob("test_*.py"))
        tracked_module.write_text(
            tracked_module.read_text(encoding="utf-8").replace(
                "assertTrue(True)", "assertTrue(False)"),
            encoding="utf-8")
        with self.assertRaises(gate.GateOrderingError) as caught:
            gate.run_single_head_suite(repo, tests_dir=repo / "tree_c",
                                       lock_dir=lock_dir)
        self.assertIn("dirty Git worktree", str(caught.exception))
        self.assertEqual(len(calls), 1,
                         "dirty tracked-body refusal must precede both "
                         "reuse and launch")


class RetainedArtifactCompletionRaceTests(unittest.TestCase):
    """Controls 52-54 (Issue #213 retained-artifact completion-race
    correction) — REAL invocation-path proof that a successful retained
    completion is never observable before the exact retained artifact
    contract (every per-task file plus ``summary.json``) is complete.
    Controls 52 and 53 FAIL on the pre-correction head a59d8e9, where
    ``run_single_head_suite`` published the completion and released the
    launch lock BEFORE the CLI wrote ``summary.json``: a second identical
    retained request in that window observed a completion over an
    incomplete retained set, disabled reuse, and attempted a fresh launch
    that the runner refuses ("retain directory is not empty")."""

    def _repo(self, add_cleanup):
        global _guard_repo_seq
        _guard_repo_seq += 1
        prefix = f"issue213r{_guard_repo_seq}"
        root = Path(tempfile.mkdtemp(prefix=f"{prefix}-root-"))
        add_cleanup(lambda: subprocess.run(
            ["rm", "-rf", str(root)], check=False))
        repo = root / "repo"
        repo.mkdir()
        for cmd in (("git", "init", "-q"),
                    ("git", "config", "user.email", "t@example.invalid"),
                    ("git", "config", "user.name", "t")):
            subprocess.run(cmd, cwd=repo, check=True)
        (repo / "tests").mkdir()
        module = f"test_{prefix}"
        add_cleanup(sys.modules.pop, module, None)
        (repo / "tests" / f"{module}.py").write_text(
            "import unittest\nclass A(unittest.TestCase):\n"
            " def test_x(self): pass\n", encoding="utf-8")
        for rel in gate.ENV_AUTHORITY_FILES:
            path = repo / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("authority\n", encoding="utf-8")
        subprocess.run(("git", "add", "-A"), cwd=repo, check=True)
        subprocess.run(("git", "commit", "-qm", "init"), cwd=repo,
                       check=True)
        return repo

    def _patched_runner(self):
        calls = []
        original = runner.run_suite

        def recording(root, tests_dir=None, **kwargs):
            calls.append({"root": str(root),
                          "retain_dir": kwargs.get("retain_dir")})
            return original(Path(root), tests_dir, **kwargs)

        runner.run_suite = recording
        self.addCleanup(setattr, runner, "run_suite", original)
        return calls

    # CONTROL 52 — post-suite/pre-summary concurrent retain request.
    # Deterministically force the first retained logical request into the
    # previous vulnerable timing point (underlying suite finished,
    # per-task artifacts on disk, summary.json not yet written — on the
    # corrected head that point lies INSIDE the guarded logical request)
    # and issue a second identical request there.
    def test_control52_post_suite_pre_summary_concurrent_retain(self):
        repo = self._repo(self.addCleanup)
        lock_dir = repo.parent / "locks"
        calls = self._patched_runner()
        retain_dir = repo.parent / "retained"
        suite_done = threading.Event()   # per-task set on disk, no summary
        release = threading.Event()

        original = runner.run_suite

        def pausing_suite(root, tests_dir=None, **kwargs):
            result = original(Path(root), tests_dir, **kwargs)
            suite_done.set()              # the vulnerable timing point
            release.wait(30)
            return result

        runner.run_suite = pausing_suite
        self.addCleanup(setattr, runner, "run_suite", original)

        outcomes = {}

        def request(name):
            try:
                started = time.monotonic()
                result = gate.run_single_head_suite(
                    repo, retain_dir=retain_dir, lock_dir=lock_dir)
                outcomes[name] = {
                    "result": result,
                    "summary_present_at_return":
                        (retain_dir / "summary.json").is_file(),
                    "waited": time.monotonic() - started}
            except BaseException as error:  # noqa: BLE001
                outcomes[name] = {"error": error}

        first = threading.Thread(target=request, args=("first",))
        first.start()
        deadline = time.monotonic() + 30
        while not suite_done.is_set() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(suite_done.is_set(), "first request never ran")
        self.assertEqual(len(calls), 1)
        # The vulnerable point: per-task artifacts exist, summary does NOT.
        self.assertFalse((retain_dir / "summary.json").is_file(),
                         "fixture must pause BEFORE summary finalization")
        second = threading.Thread(target=request, args=("second",))
        second.start()
        time.sleep(0.5)
        # While the owner sits in the window, the duplicate must neither
        # launch nor fail: it attaches behind the live owner.
        self.assertTrue(second.is_alive(),
                        "second request must attach and wait, not fail")
        self.assertEqual(len(calls), 1,
                         "second request started another suite inside the "
                         "post-suite/pre-summary window")
        release.set()
        first.join(120)
        second.join(120)
        # Exactly one underlying suite launch for the whole scenario.
        self.assertEqual(len(calls), 1,
                         "exactly ONE underlying suite launch required")
        for name in ("first", "second"):
            self.assertNotIn("error", outcomes[name],
                             f"{name} request failed: "
                             f"{outcomes[name].get('error')!r}")
            self.assertTrue(outcomes[name]["result"]["ok"])
            # The complete retained contract (per-task set + summary) was
            # available before this request returned a successful result.
            self.assertTrue(
                outcomes[name]["summary_present_at_return"],
                f"{name} request observed a completion before "
                f"summary.json existed")
        self.assertTrue((retain_dir / "summary.json").is_file())
        task_count = len(outcomes["first"]["result"]["tasks"])
        for index in range(task_count):
            for suffix in gate.RETAINED_TASK_SUFFIXES:
                self.assertTrue(
                    (retain_dir / f"task-{index}{suffix}").is_file(),
                    f"missing retained artifact task-{index}{suffix}")

    # CONTROL 52 (sequential form): after the first retained request has
    # fully returned (the old CLI timing point), an identical request
    # reuses the validation — zero second launch, and NEVER the runner's
    # "retain directory is not empty" secondary failure.
    def test_control52_sequential_reuse_no_nonempty_failure(self):
        repo = self._repo(self.addCleanup)
        lock_dir = repo.parent / "locks"
        calls = self._patched_runner()
        retain_dir = repo.parent / "retained-seq"
        first = gate.run_single_head_suite(repo, retain_dir=retain_dir,
                                           lock_dir=lock_dir)
        self.assertTrue(first["ok"])
        self.assertEqual(len(calls), 1)
        # The retained contract was complete BEFORE the first request
        # returned (the corrected ordering); on a59d8e9 the seam returned
        # with no summary.json and the second request below died with a
        # fresh-launch attempt into the non-empty directory.
        self.assertTrue((retain_dir / "summary.json").is_file(),
                        "summary.json must be finalized inside the "
                        "guarded logical request, before it returns")
        second = gate.run_single_head_suite(repo, retain_dir=retain_dir,
                                            lock_dir=lock_dir)
        self.assertTrue(second["ok"])
        self.assertEqual(second, first,
                         "the reused completion must be the exact result")
        self.assertEqual(len(calls), 1,
                         "identical retained request must reuse, not "
                         "relaunch")

    # CONTROL 53 — partial retained set: a valid same-identity completion
    # plus a deliberately incomplete non-empty retain directory fails
    # closed with the documented precise error BEFORE any launch; no
    # hidden fresh launch into the non-empty directory occurs.
    def test_control53_partial_retained_set_fails_closed(self):
        repo = self._repo(self.addCleanup)
        lock_dir = repo.parent / "locks"
        calls = self._patched_runner()
        retain_dir = repo.parent / "retained-partial"
        first = gate.run_single_head_suite(repo, retain_dir=retain_dir,
                                           lock_dir=lock_dir)
        self.assertTrue(first["ok"])
        self.assertEqual(len(calls), 1)
        # Deliberately incomplete: remove one per-task artifact while
        # keeping the directory non-empty.
        (retain_dir / "task-0-stdout.txt").unlink()
        with self.assertRaises(gate.GateOrderingError) as caught:
            gate.run_single_head_suite(repo, retain_dir=retain_dir,
                                       lock_dir=lock_dir)
        message = str(caught.exception)
        self.assertIn("fail closed", message)
        self.assertIn("non-empty", message)
        self.assertEqual(len(calls), 1,
                         "a partial retained set must NOT trigger a "
                         "hidden fresh launch")
        # The complementary partial shape (summary removed, per-task set
        # present) fails closed identically.
        (retain_dir / "summary.json").unlink()
        with self.assertRaises(gate.GateOrderingError) as caught2:
            gate.run_single_head_suite(repo, retain_dir=retain_dir,
                                       lock_dir=lock_dir)
        self.assertIn("fail closed", str(caught2.exception))
        self.assertEqual(len(calls), 1)

    # CONTROL 54 — complete retained set: a complete, mechanically valid
    # retained set permits sequential exact-config reuse with zero
    # second launch.
    def test_control54_complete_retained_set_reuses(self):
        repo = self._repo(self.addCleanup)
        lock_dir = repo.parent / "locks"
        calls = self._patched_runner()
        retain_dir = repo.parent / "retained-complete"
        first = gate.run_single_head_suite(repo, retain_dir=retain_dir,
                                           lock_dir=lock_dir)
        self.assertTrue(first["ok"])
        self.assertEqual(len(calls), 1)
        task_count = len(first["tasks"])
        for index in range(task_count):
            for suffix in gate.RETAINED_TASK_SUFFIXES:
                self.assertTrue(
                    (retain_dir / f"task-{index}{suffix}").is_file())
        self.assertTrue((retain_dir / "summary.json").is_file())
        summary_before = (retain_dir / "summary.json").read_bytes()
        second = gate.run_single_head_suite(repo, retain_dir=retain_dir,
                                            lock_dir=lock_dir)
        self.assertTrue(second["ok"])
        self.assertEqual(second, first)
        self.assertEqual(len(calls), 1,
                         "complete retained set must permit sequential "
                         "exact-config reuse with zero second launch")
        self.assertEqual(
            (retain_dir / "summary.json").read_bytes(), summary_before,
            "reuse must not rewrite the retained summary")


if __name__ == "__main__":
    unittest.main()
