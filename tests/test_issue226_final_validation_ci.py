#!/usr/bin/env python3
"""Issue #226 — hosted Final CPU Validation (CI) negative controls.

Machine-checked controls for the hosted final-validation path introduced
by Issue #226 (workflow ``.github/workflows/final-cpu-validation.yml``,
envelope schema ``hosted-final-validation-receipt/1``, orchestration
seams ``build_final_validation_receipt`` /
``validate_final_validation_receipt`` / the evolved
``handoff_gate_status``).  Pure standard library plus PyYAML (canonical
#131 environment); every control parses the REAL workflow file rather
than a prose mirror of its intent.

Control map (issue §Required controls):

* 1-2, 20 — ordinary PR CI stays impact-selected and never invokes the
  canonical full-suite runner (plan_ci targeted plan for a narrow change;
  the ordinary workflow contains no run_full_cpu_suite invocation; the
  new workflow's ONLY trigger is workflow_dispatch).
* 3-6 — the final-validation workflow cannot run without a syntactically
  valid expected SHA; it checks out and mechanically requires the exact
  expected SHA (actions/checkout pinned to the input SHA + explicit
  ``rev-parse HEAD == expected_sha`` step) before any suite execution;
  a moving branch ref cannot change the validated subject.
* 7 — the canonical suite runner/command (scripts/run_full_cpu_suite.py
  under the canonical configuration) is what the workflow executes.
* 8 — the suite step propagates the runner's exit code (FAIL fails the
  gate).
* 9-10 — the composition requires PASS + serial/executed digest equality
  and re-derives the head's canonical plan; a malformed or
  identity-mismatched suite result fails closed (module-level envelope
  tests; the workflow binds the same seams).
* 11-12 — finalizer and project-status checks run as explicit steps
  before the receipt is composed and retained.
* 13 — the envelope binds GitHub run identity + exact SHA + full suite
  identity (embedded #213 receipt, canonical configuration, environment).
* 14 — a result from SHA A cannot satisfy a final request for SHA B
  (envelope and handoff both fail closed).
* 15-16, 17 — ordinary CI success alone cannot satisfy handoff; a hosted
  final-validation receipt alone cannot satisfy handoff (no hosted-CI
  status); ordinary exact-head CI + exact-head final validation together
  satisfy the mechanical final gates.
* 18 — no local full-suite receipt is separately required when the hosted
  final-validation receipt proves the same identity (either proof,
  exactly one — both is a competing-contract error).
* 19 — no pull_request_target / untrusted elevated execution path.
"""
from __future__ import annotations

import copy
import inspect
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import issue213_gate_orchestration as gate  # noqa: E402

WORKFLOW = ROOT / ".github" / "workflows" / "final-cpu-validation.yml"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
PINNED_CHECKOUT = ("actions/checkout@"
                   "11bd71901bbe5b1630ceea73d27597364c9af683")


def _load_workflow(path: Path) -> dict:
    import yaml
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def make_suite(serial: str = "f" * 64, count: int = 2759,
               config: dict | None = None) -> dict:
    return {
        "runner_schema": gate.RUNNER_SCHEMA,
        "suite_command": list(gate.FULL_SUITE_COMMAND),
        "suite_config": config or {
            "schema": gate.SUITE_CONFIG_SCHEMA, "tests_dir": "tests",
            "jobs": 1, "plan_digest": "a" * 64, "timeout": 1800.0,
            "retain_dir": None},
        "serial_digest": serial, "executed_digest": serial, "count": count,
    }


def make_envelope(sha: str = "a" * 40, serial: str = "f" * 64,
                  receipt: dict | None = None, **overrides) -> dict:
    receipt = receipt or {
        "schema": gate.RECEIPT_SCHEMA, "git_commit_sha": sha,
        "suite": make_suite(serial), "environment":
            {rel: "e" * 64 for rel in gate.ENV_AUTHORITY_FILES},
        "result": "PASS", "count": 2759,
        "started_unix": 1000.0, "ended_unix": 1000.5,
    }
    envelope = gate.build_final_validation_receipt(
        sha, receipt, github_run_id="run-226", github_run_attempt=1,
        finalizer_check=True, project_status_check=True)
    envelope.update(overrides)
    return envelope


class FinalValidationWorkflowTests(unittest.TestCase):
    """Structural controls on the REAL final-cpu-validation.yml."""

    @classmethod
    def setUpClass(cls):
        cls.doc = _load_workflow(WORKFLOW)
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_workflow_exists_and_single_job_name(self):
        self.assertEqual(self.doc["name"], "Final CPU Validation")
        jobs = self.doc["jobs"]
        self.assertEqual(list(jobs), ["final-cpu-validation"])
        self.assertEqual(
            jobs["final-cpu-validation"]["name"], "Final CPU Validation Gate")

    def test_control1_ordinary_pr_plan_stays_targeted_for_narrow_change(self):
        import plan_ci
        plan = plan_ci.plan(["docs/campaign-gate-ordering.md"],
                            mode="pr")
        self.assertEqual(plan["mode"], "targeted")
        self.assertIn("repo-integrity", plan["groups"])
        self.assertIn("issue-213-gate-ordering", plan["groups"])
        self.assertFalse(plan["full_regression"])
        # and the workflow-touching PR itself legitimately fails closed
        # to full regression (CI_WORKFLOW_PREFIXES), which is the
        # ordinary workflow-change doctrine, unchanged by #226.
        wf_plan = plan_ci.plan(
            [".github/workflows/final-cpu-validation.yml"], mode="pr")
        self.assertTrue(wf_plan["full_regression"])

    def test_control2_ordinary_workflow_never_runs_full_suite(self):
        text = CI_WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn("scripts/run_full_cpu_suite.py", text,
                         "ordinary PR CI must not invoke the canonical "
                         "full-suite runner (tests.test_run_full_cpu_suite "
                         "is the runner's contract module, not a suite "
                         "execution)")

    def test_control3_workflow_dispatch_only_with_required_sha(self):
        triggers = self.doc.get(True, self.doc.get("on", {}))
        self.assertEqual(list(triggers), ["workflow_dispatch"],
                         "the only trigger must be workflow_dispatch")
        dispatch = triggers["workflow_dispatch"]
        sha_input = dispatch["inputs"]["expected_sha"]
        self.assertIs(sha_input["required"], True)
        self.assertEqual(sha_input["type"], "string")

    def test_control4_first_step_validates_sha_shape(self):
        steps = self.doc["jobs"]["final-cpu-validation"]["steps"]
        first = steps[0]
        self.assertIn("expected_sha", first["run"])
        self.assertIn("fullmatch", first["run"])

    def test_control5_checkout_is_sha_bound_and_mechanically_required(self):
        steps = self.doc["jobs"]["final-cpu-validation"]["steps"]
        checkout = steps[1]
        self.assertEqual(checkout["uses"], PINNED_CHECKOUT)
        self.assertEqual(checkout["with"]["ref"],
                         "${{ inputs.expected_sha }}")
        require = steps[2]
        self.assertIn("rev-parse HEAD", require["run"])
        self.assertIn("expected_sha", require["run"])
        # the shape check, the checkout binding, and the HEAD==SHA proof
        # all precede the Python setup / suite execution steps.
        names = [step.get("name", "") for step in steps]
        self.assertLess(names.index("Set up Python"), names.index(
            "Run canonical full CPU suite (serial/executed identity "
            "required)"))

    def test_control6_branch_ref_is_transport_only(self):
        # the validated subject is the dispatched expected_sha: the
        # checkout ref is inputs.expected_sha, never github.ref / a
        # branch name.
        self.assertNotIn("github.ref", self.text)
        for step in self.doc["jobs"]["final-cpu-validation"]["steps"]:
            if "uses" in step and "checkout" in step["uses"]:
                self.assertNotIn("ref: ${{ github.", step.get("with", {}))

    def test_control7_canonical_runner_and_configuration(self):
        steps = self.doc["jobs"]["final-cpu-validation"]["steps"]
        suite_steps = [s for s in steps if "run_full_cpu_suite" in
                       s.get("run", "")]
        self.assertTrue(suite_steps, "workflow must run the canonical "
                                     "runner")
        run = suite_steps[0]["run"]
        self.assertIn("scripts/run_full_cpu_suite.py --json", run)
        self.assertNotIn("--jobs", run,
                         "the canonical configuration is the runner's "
                         "default schedule — no ad-hoc overrides")
        self.assertNotIn("--tests-dir", run)
        self.assertNotIn("--timeout", run)
        self.assertNotIn("--retain-dir", run)

    def test_control8_suite_failure_fails_the_gate(self):
        steps = self.doc["jobs"]["final-cpu-validation"]["steps"]
        suite_steps = [s for s in steps if "run_full_cpu_suite" in
                       s.get("run", "")]
        run = suite_steps[0]["run"]
        self.assertIn("exit $suite_rc", run,
                      "the runner's exit code must fail the job")

    def test_control11_12_finalizer_and_status_checks_present(self):
        steps = self.doc["jobs"]["final-cpu-validation"]["steps"]
        names = [step.get("name", "") for step in steps]
        finalizer = next(n for n in names if "finalizer" in n.lower())
        status = next(n for n in names if "project-status" in n.lower())
        compose = next(n for n in names if "receipt" in n.lower()
                       and "Compose" in n)
        self.assertLess(names.index(finalizer), names.index(compose))
        self.assertLess(names.index(status), names.index(compose))

    def test_control13_receipt_binds_run_identity_and_sha(self):
        compose = next(s for s in
                       self.doc["jobs"]["final-cpu-validation"]["steps"]
                       if "Compose" in s.get("name", ""))
        run = compose["run"]
        for binding in ("github.run_id", "github.run_attempt",
                        "inputs.expected_sha", "suite_identity",
                        "build_receipt", "validate_receipt"):
            self.assertIn(binding, run)

    def test_control19_no_pull_request_target_or_elevated_execution(self):
        # No pull_request_target TRIGGER (the only trigger is
        # workflow_dispatch, proven structurally by control3); the raw
        # text may legitimately mention the term in comments.
        triggers = self.doc[True] if True in self.doc else self.doc["on"]
        for key in triggers:
            self.assertNotIn("pull_request", key)
        permissions = self.doc["permissions"]
        self.assertEqual(permissions, {"contents": "read"})

    def test_control20_main_push_full_regression_unchanged(self):
        # The ordinary workflow keeps --mode full on push-to-main and the
        # planner's full mode still selects every registered group.
        import plan_ci
        ci_text = CI_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("--mode full", ci_text)
        plan = plan_ci.plan([], mode="full")
        self.assertEqual(plan["groups"],
                         sorted(plan_ci.GROUP_TEST_MODULES))


class FinalValidationEnvelopeTests(unittest.TestCase):
    """Module-level controls on the envelope contract (fail closed)."""

    def test_control9_serial_executed_mismatch_fails(self):
        suite = make_suite()
        suite["executed_digest"] = "0" * 64
        receipt = {
            "schema": gate.RECEIPT_SCHEMA, "git_commit_sha": "a" * 40,
            "suite": suite, "environment":
                {rel: "e" * 64 for rel in gate.ENV_AUTHORITY_FILES},
            "result": "PASS", "count": 2759,
            "started_unix": 1.0, "ended_unix": 2.0,
        }
        with self.assertRaises(gate.GateOrderingError):
            gate.suite_identity({"ok": True, **suite})

    def test_control10_malformed_receipt_fails_closed(self):
        envelope = make_envelope()
        for mutation in (
            lambda e: e.pop("suite_receipt"),
            lambda e: e.update({"suite_receipt": {"schema": "x"}}),
            lambda e: e.update({"schema": "hosted-final-validation/0"}),
            lambda e: e.update({"github_run_id": ""}),
            lambda e: e.update({"github_run_attempt": 0}),
            lambda e: e.pop("github_run_attempt"),
            lambda e: e.update({"finalizer_check": False}),
            lambda e: e.update({"project_status_check": "yes"}),
            lambda e: e.update({"git_commit_sha": "zz"}),
            lambda e: e["suite_receipt"].update({"result": "FAIL"}),
        ):
            broken = copy.deepcopy(envelope)
            mutation(broken)
            with self.assertRaises(gate.GateOrderingError):
                gate.validate_final_validation_receipt(broken, "a" * 40)

    def test_control10b_embedded_receipt_from_other_head_rejected(self):
        receipt = {
            "schema": gate.RECEIPT_SCHEMA, "git_commit_sha": "b" * 40,
            "suite": make_suite(), "environment":
                {rel: "e" * 64 for rel in gate.ENV_AUTHORITY_FILES},
            "result": "PASS", "count": 2759,
            "started_unix": 1.0, "ended_unix": 2.0,
        }
        with self.assertRaises(gate.GateOrderingError):
            gate.build_final_validation_receipt("a" * 40, receipt,
                                                github_run_id="r",
                                                github_run_attempt=1,
                                                finalizer_check=True,
                                                project_status_check=True)

    def test_control14_sha_a_cannot_satisfy_sha_b(self):
        envelope = make_envelope(sha="a" * 40)
        self.assertFalse(
            gate.validate_final_validation_receipt(envelope, "b" * 40))
        head = gate.FinalHeadRequest(
            git_commit_sha="b" * 40, suite=make_suite(),
            environment={rel: "e" * 64
                         for rel in gate.ENV_AUTHORITY_FILES})
        ci = gate.build_hosted_ci_status("b" * 40, "run-ci")
        with self.assertRaises(gate.GateOrderingError):
            gate.handoff_gate_status(head, None, ci, True,
                                     final_validation_receipt=envelope)

    def test_control14b_non_canonical_configuration_rejected(self):
        # Same SHA but a different suite configuration: the envelope can
        # never satisfy the canonical final-head request.
        config = {"schema": gate.SUITE_CONFIG_SCHEMA, "tests_dir": "tests",
                  "jobs": 4, "plan_digest": "a" * 64, "timeout": 1800.0,
                  "retain_dir": None}
        envelope = make_envelope(config=None)  # jobs=1 canonical sample
        head = gate.FinalHeadRequest(
            git_commit_sha="a" * 40, suite=make_suite(config=config),
            environment={rel: "e" * 64
                         for rel in gate.ENV_AUTHORITY_FILES})
        ci = gate.build_hosted_ci_status("a" * 40, "run-ci")
        with self.assertRaises(gate.GateOrderingError):
            gate.handoff_gate_status(head, None, ci, True,
                                     final_validation_receipt=envelope)

    def test_control15_ordinary_ci_alone_cannot_satisfy_handoff(self):
        sha = "a" * 40
        head = gate.FinalHeadRequest(
            git_commit_sha=sha, suite=make_suite(),
            environment={rel: "e" * 64
                         for rel in gate.ENV_AUTHORITY_FILES})
        ci = gate.build_hosted_ci_status(sha, "run-ci")
        status = gate.handoff_gate_status(head, None, ci, True)
        self.assertFalse(status["handoff_complete"])
        self.assertFalse(status["full_suite_receipt_valid"])

    def test_control16_final_validation_alone_cannot_satisfy_handoff(self):
        sha = "a" * 40
        head = gate.FinalHeadRequest(
            git_commit_sha=sha, suite=make_suite(),
            environment={rel: "e" * 64
                         for rel in gate.ENV_AUTHORITY_FILES})
        envelope = make_envelope(sha=sha)
        status = gate.handoff_gate_status(head, None, None, True,
                                          final_validation_receipt=envelope)
        self.assertFalse(status["handoff_complete"])
        self.assertTrue(status["full_suite_receipt_valid"],
                        "the envelope proves the full-suite requirement")
        self.assertFalse(status["hosted_ci_success"])

    def test_control17_ci_plus_final_validation_satisfy_mechanical_gates(self):
        sha = "a" * 40
        suite = make_suite()
        head = gate.FinalHeadRequest(
            git_commit_sha=sha, suite=suite,
            environment={rel: "e" * 64
                         for rel in gate.ENV_AUTHORITY_FILES})
        envelope = make_envelope(sha=sha)
        # The envelope's embedded suite must match the final head suite.
        envelope["suite_receipt"]["suite"] = copy.deepcopy(suite)
        ci = gate.build_hosted_ci_status(sha, "run-ci")
        status = gate.handoff_gate_status(head, None, ci, True,
                                          final_validation_receipt=envelope)
        self.assertTrue(status["handoff_complete"])
        self.assertEqual(status["full_suite_proof"],
                         "hosted-final-validation")

    def test_control18_local_receipt_not_separately_required(self):
        sha = "a" * 40
        head = gate.FinalHeadRequest(
            git_commit_sha=sha, suite=make_suite(),
            environment={rel: "e" * 64
                         for rel in gate.ENV_AUTHORITY_FILES})
        envelope = make_envelope(sha=sha)
        envelope["suite_receipt"]["suite"] = make_suite()
        ci = gate.build_hosted_ci_status(sha, "run-ci")
        status = gate.handoff_gate_status(head, None, ci, True,
                                          final_validation_receipt=envelope)
        self.assertTrue(status["handoff_complete"],
                        "hosted proof alone completes the mechanical "
                        "gates — no separate local suite receipt")

    def test_control18b_both_proofs_is_competing_contract_error(self):
        sha = "a" * 40
        suite = make_suite()
        head = gate.FinalHeadRequest(
            git_commit_sha=sha, suite=suite,
            environment={rel: "e" * 64
                         for rel in gate.ENV_AUTHORITY_FILES})
        local = {
            "schema": gate.RECEIPT_SCHEMA, "git_commit_sha": sha,
            "suite": copy.deepcopy(suite), "environment":
                {rel: "e" * 64 for rel in gate.ENV_AUTHORITY_FILES},
            "result": "PASS", "count": suite["count"],
            "started_unix": 1.0, "ended_unix": 2.0,
        }
        envelope = make_envelope(sha=sha)
        envelope["suite_receipt"]["suite"] = copy.deepcopy(suite)
        ci = gate.build_hosted_ci_status(sha, "run-ci")
        with self.assertRaises(gate.GateOrderingError):
            gate.handoff_gate_status(head, local, ci, True,
                                     final_validation_receipt=envelope)

    def test_legacy_call_shape_preserved_fail_closed(self):
        # Pre-#226 positional call keeps exact semantics; the new
        # parameter is optional, and signature order is unchanged.
        signature = inspect.signature(gate.handoff_gate_status)
        self.assertEqual(
            list(signature.parameters),
            ["final_head", "suite_receipt", "hosted_ci_status",
             "finalizer_ok", "final_validation_receipt"])
        self.assertEqual(
            signature.parameters["final_validation_receipt"].default, None)
        sha = "a" * 40
        suite = make_suite()
        head = gate.FinalHeadRequest(
            git_commit_sha=sha, suite=suite,
            environment={rel: "e" * 64
                         for rel in gate.ENV_AUTHORITY_FILES})
        local = {
            "schema": gate.RECEIPT_SCHEMA, "git_commit_sha": sha,
            "suite": copy.deepcopy(suite), "environment":
                {rel: "e" * 64 for rel in gate.ENV_AUTHORITY_FILES},
            "result": "PASS", "count": suite["count"],
            "started_unix": 1.0, "ended_unix": 2.0,
        }
        ci = gate.build_hosted_ci_status(sha, "run-ci")
        status = gate.handoff_gate_status(head, local, ci, True)
        self.assertTrue(status["handoff_complete"])
        self.assertEqual(status["full_suite_proof"],
                         "exact-head-suite-receipt")

    def test_build_rejects_bad_inputs(self):
        sha = "a" * 40
        receipt = {
            "schema": gate.RECEIPT_SCHEMA, "git_commit_sha": sha,
            "suite": make_suite(), "environment":
                {rel: "e" * 64 for rel in gate.ENV_AUTHORITY_FILES},
            "result": "PASS", "count": 2759,
            "started_unix": 1.0, "ended_unix": 2.0,
        }
        base = dict(github_run_id="r", github_run_attempt=1,
                    finalizer_check=True, project_status_check=True)
        for kwargs in (
            {"github_run_id": ""}, {"github_run_id": 7},
            {"github_run_attempt": 0}, {"github_run_attempt": True},
            {"workflow": " "}, {"pr_number": 0},
            {"finalizer_check": "true"},
            {"project_status_check": None},
        ):
            merged = {**base, **kwargs}
            with self.assertRaises(gate.GateOrderingError):
                gate.build_final_validation_receipt(
                    sha, copy.deepcopy(receipt), **merged)
        with self.assertRaises(gate.GateOrderingError):
            gate.build_final_validation_receipt(
                "nothex", copy.deepcopy(receipt), **base)


class FinalValidationDoctrineTests(unittest.TestCase):
    """Canonical doctrine names the hosted final-validation gate."""

    def test_control_doctrine_names_hosted_final_validation(self):
        text = (ROOT / "docs" / "campaign-gate-ordering.md").read_text(
            encoding="utf-8")
        for phrase in ("Final CPU Validation", "expected_sha",
                       "final-cpu-validation.yml",
                       "workflow_dispatch"):
            self.assertIn(phrase, text)
        self.assertIn(
            "not run on every PR push", text)

    def test_ci_impact_planning_documents_the_final_validation_workflow(self):
        text = (ROOT / "docs" / "ci-impact-planning.md").read_text(
            encoding="utf-8")
        self.assertIn("final-cpu-validation.yml", text)
        self.assertIn("expected_sha", text)


if __name__ == "__main__":
    unittest.main()
