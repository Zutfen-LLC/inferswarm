#!/usr/bin/env python3
"""Issue #323 — verified ordinary CI on the exact final PR head.

Before this change ``handoff_gate_status`` accepted a
``hosted-ci-exact-head-status/1`` object after checking only its shape.  A
caller-written ``{"schema": ..., "git_commit_sha": <head>, "run_id": "x",
"result": "SUCCESS"}`` therefore satisfied the ordinary-CI half of the
final-head gate even when no ordinary CI run had ever executed — and
``[skip ci]`` produces exactly that situation (authentic example: Final CPU
Validation run #23, head ``0e78097b``: zero ``ci.yml`` runs).  A check inside
``ci.yml`` cannot close this (the workflow may never start), so the
repository-owned enforcement point is the handoff boundary, which now
re-authenticates ordinary CI against read-only GitHub Actions data
(``scripts/hosted_ci_verification.py``).

Control map (the numbers follow the task's required adversarial list):

* C01..C15 — every rejection fails for its INTENDED reason code.
* P — positive controls: genuine PR CI, a dispatched ordinary CI run,
  determinism/read-only behaviour, rerun semantics.
* H — the authoritative handoff boundary: a forged/unauthenticated claim,
  an absent ordinary CI run, a missing Final CPU Validation proof, and the
  unchanged two-gate requirement.
* T — the read-only HTTP surface and the CLIs.
* D — workflow-identity pins and the documented operator recovery.

All API data is an in-memory fake (``tests/hosted_ci_fakes.py``, built from
authentic read-only run metadata); no test calls GitHub.
"""
from __future__ import annotations

import copy
import inspect
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import issue213_gate_orchestration as gate  # noqa: E402
import hosted_ci_verification as hci  # noqa: E402
from tests import hosted_ci_fakes as fakes  # noqa: E402
from tests.hosted_ci_fakes import FakeCiApi, REPO, REAL_SHA, REAL_RUN_ID  # noqa: E402
from tests.test_issue226_final_validation_ci import (  # noqa: E402
    make_envelope, make_suite)

CI_YML = ROOT / ".github" / "workflows" / "ci.yml"
FCV_YML = ROOT / ".github" / "workflows" / "final-cpu-validation.yml"
DOC = ROOT / "docs" / "campaign-gate-ordering.md"
HEAD = "a" * 40
ENV = {rel: "e" * 64 for rel in gate.ENV_AUTHORITY_FILES}
TOKEN = "ghs_SUPERSECRETTOKENVALUE"


def verify(api, sha=REAL_SHA, *, pr_number=None, pinned_run_id=None):
    return hci.HostedCiVerifier(api, REPO, pr_number=pr_number).verify(
        sha, pinned_run_id=pinned_run_id)


def world_for(sha: str, branch: str = "feature/x", run_id: int = 9001):
    """A genuine-shaped CI world for an arbitrary head."""
    api = FakeCiApi()
    api.add_run(fakes.ci_run(run_id, sha, branch))
    api.pulls = {7: fakes.pull(7, sha, branch)}
    return api


class _Base(unittest.TestCase):
    def assertBlocked(self, verdict, code):
        self.assertEqual(verdict["schema"], hci.VERDICT_SCHEMA)
        self.assertEqual(verdict["verdict"], "BLOCKED", verdict)
        self.assertEqual(verdict["reason_code"], code, verdict)

    def assertPass(self, verdict):
        self.assertEqual(verdict["verdict"], "PASS", verdict)
        self.assertIsNone(verdict["reason_code"])


# ---------------------------------------------------------------------------
# C — adversarial controls
# ---------------------------------------------------------------------------

class AdversarialControls(_Base):
    def test_c01_skip_ci_authentic_no_run_is_blocked(self):
        api = FakeCiApi.skip_ci()
        verdict = verify(api, fakes.SKIP_CI_SHA, pr_number=304)
        self.assertBlocked(verdict, "no_ci_run")
        self.assertEqual(verdict["expected_sha"], fakes.SKIP_CI_SHA)
        self.assertEqual(verdict["considered_runs"], [])
        self.assertIn("list_workflow_runs", api.called())

    def test_c02_pending_or_queued_is_blocked(self):
        for status in ("queued", "in_progress", "waiting", "requested",
                       "pending"):
            api = FakeCiApi.genuine()
            api.runs[0].update(status=status, conclusion=None)
            self.assertBlocked(verify(api), "ci_pending")

    def test_c03_cancelled_is_blocked(self):
        api = FakeCiApi.genuine()
        api.runs[0]["conclusion"] = "cancelled"
        self.assertBlocked(verify(api), "ci_cancelled")

    def test_c04_failed_is_blocked(self):
        for conclusion in ("failure", "timed_out", "startup_failure"):
            api = FakeCiApi.genuine()
            api.runs[0]["conclusion"] = conclusion
            self.assertBlocked(verify(api), "ci_failed")
        for conclusion in ("skipped", "neutral", "action_required",
                           "stale", None):
            api = FakeCiApi.genuine()
            api.runs[0]["conclusion"] = conclusion
            self.assertBlocked(verify(api), "ci_not_success")

    def test_c05_workflow_success_but_ci_gate_not_success(self):
        for conclusion in ("failure", "skipped", "cancelled", None):
            api = FakeCiApi.genuine()
            api.job("CI Gate")["conclusion"] = conclusion
            self.assertBlocked(verify(api), "gate_job_not_success")
        api = FakeCiApi.genuine()
        api.job("CI Gate")["status"] = "in_progress"
        self.assertBlocked(verify(api), "gate_job_not_success")
        api = FakeCiApi.genuine()
        api.jobs[REAL_RUN_ID] = [j for j in api.jobs[REAL_RUN_ID]
                                 if j["name"] != "CI Gate"]
        self.assertBlocked(verify(api), "gate_job_missing")

    def test_c05b_gate_job_cannot_hide_failed_or_missing_required_jobs(self):
        for name in ("Plan CI (impact selection)",
                     "Group repo-integrity (always-on)"):
            api = FakeCiApi.genuine()
            api.job(name)["conclusion"] = "failure"
            self.assertBlocked(verify(api), "required_job_not_success")
            api = FakeCiApi.genuine()
            api.jobs[REAL_RUN_ID] = [j for j in api.jobs[REAL_RUN_ID]
                                     if j["name"] != name]
            self.assertBlocked(verify(api), "required_job_not_success")
        api = FakeCiApi.genuine()
        api.job("Group issue-74-79")["conclusion"] = "failure"
        self.assertBlocked(verify(api), "job_not_success")
        # A legitimately skipped (unselected) group is fine.
        api = FakeCiApi.genuine()
        api.job("Group issue-74-79")["conclusion"] = "skipped"
        self.assertPass(verify(api))

    def test_c06_success_on_previous_sha_is_blocked(self):
        api = FakeCiApi()
        api.add_run(fakes.ci_run(sha=fakes.OTHER_SHA))
        self.assertBlocked(verify(api, REAL_SHA), "no_ci_run")
        # A misbehaving server that ignores the head_sha filter and hands
        # back an old-SHA run is inconsistent evidence, not a pass.
        api.ignore_head_filter = True
        self.assertBlocked(verify(api, REAL_SHA), "inconsistent_metadata")

    def test_c07_different_branch_or_repository_is_blocked(self):
        api = FakeCiApi.genuine()
        api.pulls[322] = fakes.pull(322, REAL_SHA, "some/other-branch")
        self.assertBlocked(verify(api, pr_number=322), "branch_mismatch")
        api = FakeCiApi.genuine()
        api.runs[0]["repository"] = {"full_name": "evil/inferswarm"}
        self.assertBlocked(verify(api), "foreign_repository")
        api = FakeCiApi.genuine()
        api.runs[0]["head_repository"] = {"full_name": "fork/inferswarm"}
        self.assertBlocked(verify(api), "foreign_repository")
        api = FakeCiApi.genuine()
        api.pulls[322] = fakes.pull(322, REAL_SHA, repo="fork/inferswarm")
        self.assertBlocked(verify(api, pr_number=322), "foreign_repository")

    def test_c08_forged_run_identity_cannot_be_pinned(self):
        api = FakeCiApi.genuine()
        self.assertBlocked(verify(api, pinned_run_id=999999999),
                           "pinned_run_not_found")
        for bad in ("run-ci", True, 0, -3, 1.5, ""):
            self.assertBlocked(verify(FakeCiApi.genuine(),
                                      pinned_run_id=bad), "malformed_input")

    def test_c09_valid_looking_run_id_with_inconsistent_metadata(self):
        def mutate(**fields):
            def mutator(call, run):
                run.update(fields)
                return run
            return mutator
        for fields in ({"head_sha": fakes.OTHER_SHA}, {"id": 12345},
                       {"conclusion": "failure"}, {"run_attempt": 2},
                       {"event": "workflow_dispatch"},
                       {"head_branch": "different"}):
            api = FakeCiApi.genuine()
            api.get_run_mutator = mutate(**fields)
            self.assertBlocked(verify(api), "inconsistent_metadata")
        api = FakeCiApi.genuine()
        api.job("CI Gate")["run_id"] = 1
        self.assertBlocked(verify(api), "inconsistent_metadata")
        api = FakeCiApi.genuine()
        api.job("CI Gate")["head_sha"] = fakes.OTHER_SHA
        self.assertBlocked(verify(api), "inconsistent_metadata")

    def test_c10_wrong_workflow_identity(self):
        api = FakeCiApi.genuine()
        api.workflow["path"] = ".github/workflows/final-cpu-validation.yml"
        self.assertBlocked(verify(api), "workflow_identity_mismatch")
        api = FakeCiApi.genuine()
        api.workflow["name"] = "Final CPU Validation"
        self.assertBlocked(verify(api), "workflow_identity_mismatch")
        api = FakeCiApi.genuine()
        api.workflow["state"] = "disabled_manually"
        self.assertBlocked(verify(api), "workflow_identity_mismatch")
        api = FakeCiApi.genuine()
        api.runs[0]["workflow_id"] = fakes.FCV_WORKFLOW_ID
        self.assertBlocked(verify(api), "workflow_identity_mismatch")
        api = FakeCiApi.genuine()
        api.runs[0]["path"] = ".github/workflows/final-cpu-validation.yml"
        self.assertBlocked(verify(api), "workflow_identity_mismatch")
        api = FakeCiApi.genuine()
        api.runs[0]["name"] = "Final CPU Validation"
        self.assertBlocked(verify(api), "workflow_identity_mismatch")

    def test_c10b_final_cpu_validation_run_is_not_ordinary_ci(self):
        # Authentic run-#23 head: the only hosted run the API knows is the
        # Final CPU Validation dispatch.  Even if it is offered to the
        # verifier as a CI run it is rejected by workflow identity.
        api = FakeCiApi.skip_ci()
        fcv = fakes.ci_run(fakes.SKIP_CI_FCV_RUN_ID, fakes.SKIP_CI_SHA,
                           fakes.SKIP_CI_BRANCH, event="workflow_dispatch")
        fcv.update(name="Final CPU Validation",
                   path=".github/workflows/final-cpu-validation.yml",
                   workflow_id=fakes.FCV_WORKFLOW_ID)
        api.add_run(fcv)
        self.assertBlocked(verify(api, fakes.SKIP_CI_SHA),
                           "workflow_identity_mismatch")

    def test_c11_malformed_or_incomplete_api_responses(self):
        def case(label, mutate):
            api = FakeCiApi.genuine()
            mutate(api)
            self.assertBlocked(verify(api), "malformed_response")
        case("workflow not object", lambda a: setattr(a, "workflow", []))
        case("workflow no path", lambda a: a.workflow.pop("path"))
        case("workflow id bool", lambda a: a.workflow.update(id=True))
        case("run no id", lambda a: a.runs[0].pop("id"))
        case("run id bool", lambda a: a.runs[0].update(id=True))
        case("run no status", lambda a: a.runs[0].pop("status"))
        case("run attempt str", lambda a: a.runs[0].update(run_attempt="1"))
        case("run no head_sha", lambda a: a.runs[0].pop("head_sha"))
        case("run no repository", lambda a: a.runs[0].pop("repository"))
        case("job no name", lambda a: a.jobs[REAL_RUN_ID][0].pop("name"))
        case("job no run_id", lambda a: a.jobs[REAL_RUN_ID][0].pop("run_id"))
        case("job attempt str", lambda a: a.jobs[REAL_RUN_ID][0].update(
            run_attempt="1"))
        api = FakeCiApi.genuine()
        api.list_workflow_runs = lambda *a: []
        self.assertBlocked(verify(api), "malformed_response")
        api = FakeCiApi.genuine()
        api.list_workflow_runs = lambda *a: {"total_count": "1",
                                             "workflow_runs": []}
        self.assertBlocked(verify(api), "malformed_response")
        api = FakeCiApi.genuine()
        api.list_workflow_runs = lambda *a: {"total_count": 1}
        self.assertBlocked(verify(api), "malformed_response")
        api = FakeCiApi.genuine()
        api.list_run_jobs = lambda *a: {"total_count": 20}
        self.assertBlocked(verify(api), "malformed_response")
        api = FakeCiApi.genuine()
        api.get_run = lambda run_id: None
        self.assertBlocked(verify(api), "malformed_response")
        api = FakeCiApi.genuine()
        api.get_pull = lambda number: {"head": {}}
        self.assertBlocked(verify(api, pr_number=322), "malformed_response")

    def test_c12_api_unavailable_denied_or_rate_limited(self):
        for method in ("get_workflow", "list_workflow_runs", "get_run",
                       "list_run_jobs", "get_pull"):
            for message in ("HTTP 403", "HTTP 429", "HTTP 503",
                            "transport error: timed out"):
                api = FakeCiApi.genuine()
                api.errors[method] = hci.ApiUnavailable(message)
                verdict = verify(api, pr_number=322)
                self.assertBlocked(verdict, "api_unavailable")
                self.assertIn(message, verdict["detail"])

    def test_c13_stale_attempt_and_ambiguous_rerun_evidence(self):
        # Jobs of an earlier attempt can never prove the latest attempt.
        api = FakeCiApi.genuine()
        api.runs[0]["run_attempt"] = 2
        self.assertBlocked(verify(api), "stale_attempt")
        # A genuine rerun (all evidence on the latest attempt) is fine.
        api = FakeCiApi.genuine()
        api.runs[0]["run_attempt"] = 2
        api.jobs[REAL_RUN_ID] = fakes.ci_jobs(attempt=2)
        self.assertPass(verify(api))
        # The run is re-run while it is being read: the two run reads
        # disagree => ambiguous, never a pass.
        api = FakeCiApi.genuine()

        def rerun(call, run):
            if call >= 2:
                run.update(run_attempt=2, status="in_progress",
                           conclusion=None)
            return run
        api.get_run_mutator = rerun
        self.assertBlocked(verify(api), "ambiguous_evidence")
        # Two aggregate gates in one run is ambiguous.
        api = FakeCiApi.genuine()
        api.jobs[REAL_RUN_ID].append(dict(api.job("CI Gate"), id=1))
        self.assertBlocked(verify(api), "ambiguous_evidence")

    def test_c13b_pagination_uncertainty_is_blocked(self):
        api = FakeCiApi.genuine()
        api.total_count_override = 500
        self.assertBlocked(verify(api), "pagination_uncertain")
        api = FakeCiApi.genuine()
        api.jobs_total_override = 500
        self.assertBlocked(verify(api), "pagination_uncertain")

    def test_c15_pr_head_mutation_after_ci_completion(self):
        api = FakeCiApi.genuine()
        api.pulls[322] = fakes.pull(322, fakes.OTHER_SHA)
        self.assertBlocked(verify(api, pr_number=322), "pr_head_moved")
        # The new head has no CI of its own: the old success is stale.
        api = FakeCiApi.genuine()
        self.assertBlocked(verify(api, fakes.OTHER_SHA), "no_ci_run")


# ---------------------------------------------------------------------------
# P — positive controls
# ---------------------------------------------------------------------------

class PositiveControls(_Base):
    def test_p01_genuine_pr_ci_on_exact_head_is_accepted(self):
        api = FakeCiApi.genuine()
        verdict = verify(api, pr_number=322)
        self.assertPass(verdict)
        self.assertEqual(verdict["expected_sha"], REAL_SHA)
        self.assertEqual(verdict["repository"], REPO)
        self.assertEqual(verdict["workflow"],
                         {"id": fakes.CI_WORKFLOW_ID, "name": "CI",
                          "path": ".github/workflows/ci.yml"})
        run = verdict["run"]
        self.assertEqual((run["id"], run["attempt"], run["event"],
                          run["head_sha"], run["head_branch"],
                          run["conclusion"]),
                         (REAL_RUN_ID, 1, "pull_request", REAL_SHA,
                          fakes.REAL_BRANCH, "success"))
        self.assertTrue(run["html_url"].endswith(f"/runs/{REAL_RUN_ID}"))
        self.assertEqual(verdict["gate_job"]["id"], fakes.GATE_JOB_ID)
        self.assertEqual(verdict["gate_job"]["conclusion"], "success")
        self.assertEqual(verdict["pull_request"]["number"], 322)
        self.assertIn("github-actions-api", verdict["evidence_source"])

    def test_p02_legitimately_dispatched_ci_run_is_accepted(self):
        api = FakeCiApi.skip_ci()
        api.add_run(fakes.ci_run(555, fakes.SKIP_CI_SHA,
                                 fakes.SKIP_CI_BRANCH,
                                 event="workflow_dispatch"))
        verdict = verify(api, fakes.SKIP_CI_SHA, pr_number=304,
                         pinned_run_id=555)
        self.assertPass(verdict)
        self.assertEqual(verdict["run"]["event"], "workflow_dispatch")
        # The same dispatched run under a different PR branch name is not
        # accepted merely because it ran the same bytes.
        api.pulls[304] = fakes.pull(304, fakes.SKIP_CI_SHA, "other-branch")
        self.assertBlocked(verify(api, fakes.SKIP_CI_SHA, pr_number=304),
                           "branch_mismatch")

    def test_p03_deterministic_read_only_and_secret_free(self):
        api = FakeCiApi.genuine()
        first = verify(api, pr_number=322)
        calls_first = list(api.calls)
        api.calls.clear()
        second = verify(api, pr_number=322)
        self.assertEqual(first, second)
        self.assertEqual(calls_first, api.calls)
        self.assertTrue(all(name.startswith(("get_", "list_"))
                            for name in api.called()))
        blob = json.dumps(first, sort_keys=True)
        self.assertNotIn("Bearer", blob)
        self.assertNotIn("token", blob.lower())

    def test_p04_same_head_reruns_newest_run_decides(self):
        api = FakeCiApi.genuine()
        api.runs[0]["conclusion"] = "failure"
        api.jobs[REAL_RUN_ID][-1]["conclusion"] = "failure"
        api.add_run(fakes.ci_run(REAL_RUN_ID + 1, event="workflow_dispatch"))
        verdict = verify(api)
        self.assertPass(verdict)
        self.assertEqual(verdict["run"]["id"], REAL_RUN_ID + 1)
        self.assertEqual([r["id"] for r in verdict["considered_runs"]],
                         [REAL_RUN_ID, REAL_RUN_ID + 1])
        # A newer failing run overrides an older success.
        api = FakeCiApi.genuine()
        api.add_run(fakes.ci_run(REAL_RUN_ID + 1, event="workflow_dispatch",
                                 conclusion="failure"))
        self.assertBlocked(verify(api), "ci_failed")
        # Pinning an older success when a newer run exists is stale.
        api = FakeCiApi.genuine()
        api.add_run(fakes.ci_run(REAL_RUN_ID + 1, event="workflow_dispatch"))
        self.assertBlocked(verify(api, pinned_run_id=REAL_RUN_ID),
                           "stale_run")
        self.assertPass(verify(api, pinned_run_id=REAL_RUN_ID + 1))

    def test_p05_push_event_runs_are_not_pr_ci(self):
        api = FakeCiApi()
        api.add_run(fakes.ci_run(event="push", branch="main"))
        verdict = verify(api)
        self.assertBlocked(verdict, "no_ci_run")
        self.assertEqual([r["event"] for r in verdict["considered_runs"]],
                         ["push"])
        self.assertTrue(verdict["considered_runs"][0]["ignored"])


# ---------------------------------------------------------------------------
# H — the authoritative handoff boundary
# ---------------------------------------------------------------------------

def make_head(sha: str = HEAD) -> gate.FinalHeadRequest:
    return gate.FinalHeadRequest(git_commit_sha=sha, suite=make_suite(),
                                 environment=dict(ENV))


def make_fcv(sha: str = HEAD) -> dict:
    envelope = make_envelope(sha=sha)
    envelope["suite_receipt"]["suite"] = make_suite()
    return envelope


def passing_verifier(sha: str = HEAD, pr_number: int | None = None):
    return hci.HostedCiVerifier(world_for(sha), REPO, pr_number=pr_number)


class HandoffBoundary(_Base):
    def test_h01_forged_claim_without_authentication_cannot_complete(self):
        forged = gate.build_hosted_ci_status(HEAD, "123456789")
        result = gate.handoff_gate_status(
            make_head(), None, forged, True,
            final_validation_receipt=make_fcv())
        self.assertFalse(result["handoff_complete"])
        self.assertFalse(result["hosted_ci_success"])
        self.assertTrue(result["full_suite_receipt_valid"])
        self.assertEqual(result["hosted_ci_verdict"]["verdict"], "BLOCKED")
        self.assertEqual(result["hosted_ci_verdict"]["reason_code"],
                         "unauthenticated_claim")

    def test_h02_no_claim_and_no_verifier_cannot_complete(self):
        result = gate.handoff_gate_status(
            make_head(), None, None, True,
            final_validation_receipt=make_fcv())
        self.assertFalse(result["handoff_complete"])
        self.assertEqual(result["hosted_ci_verdict"]["reason_code"],
                         "no_ci_verification")

    def test_h03_forged_claim_against_empty_authenticated_world(self):
        forged = gate.build_hosted_ci_status(HEAD, "123456789")
        verifier = hci.HostedCiVerifier(FakeCiApi(), REPO)
        result = gate.handoff_gate_status(
            make_head(), None, forged, True,
            final_validation_receipt=make_fcv(), ci_verifier=verifier)
        self.assertFalse(result["handoff_complete"])
        self.assertEqual(result["hosted_ci_verdict"]["reason_code"],
                         "pinned_run_not_found")

    def test_h04_fcv_green_but_ordinary_ci_absent_skip_ci(self):
        head = make_head(fakes.SKIP_CI_SHA)
        verifier = hci.HostedCiVerifier(FakeCiApi.skip_ci(), REPO,
                                        pr_number=304)
        result = gate.handoff_gate_status(
            head, None, None, True,
            final_validation_receipt=make_fcv(fakes.SKIP_CI_SHA),
            ci_verifier=verifier)
        self.assertFalse(result["handoff_complete"])
        self.assertTrue(result["full_suite_receipt_valid"])
        self.assertEqual(result["full_suite_proof"], "hosted-final-validation")
        self.assertFalse(result["hosted_ci_success"])
        self.assertEqual(result["hosted_ci_verdict"]["reason_code"],
                         "no_ci_run")

    def test_h05_both_existing_gates_complete_the_handoff(self):
        result = gate.handoff_gate_status(
            make_head(), None, None, True,
            final_validation_receipt=make_fcv(),
            ci_verifier=passing_verifier(pr_number=7))
        self.assertTrue(result["handoff_complete"])
        self.assertTrue(result["hosted_ci_success"])
        self.assertEqual(result["hosted_ci_verdict"]["verdict"], "PASS")
        self.assertEqual(result["hosted_ci_verdict"]["expected_sha"], HEAD)
        self.assertEqual(result["full_suite_proof"], "hosted-final-validation")

    def test_h06_ordinary_ci_alone_still_cannot_complete(self):
        result = gate.handoff_gate_status(
            make_head(), None, None, True, ci_verifier=passing_verifier())
        self.assertTrue(result["hosted_ci_success"])
        self.assertFalse(result["full_suite_receipt_valid"])
        self.assertFalse(result["handoff_complete"])

    def test_h07_finalizer_failure_still_blocks(self):
        result = gate.handoff_gate_status(
            make_head(), None, None, False,
            final_validation_receipt=make_fcv(),
            ci_verifier=passing_verifier())
        self.assertFalse(result["handoff_complete"])

    def test_h08_claim_for_other_sha_or_malformed_run_id(self):
        other = gate.build_hosted_ci_status("b" * 40, "123")
        result = gate.handoff_gate_status(
            make_head(), None, other, True,
            final_validation_receipt=make_fcv(),
            ci_verifier=passing_verifier())
        self.assertFalse(result["handoff_complete"])
        self.assertEqual(result["hosted_ci_verdict"]["reason_code"],
                         "claim_sha_mismatch")
        textual = gate.build_hosted_ci_status(HEAD, "run-ci")
        result = gate.handoff_gate_status(
            make_head(), None, textual, True,
            final_validation_receipt=make_fcv(),
            ci_verifier=passing_verifier())
        self.assertFalse(result["handoff_complete"])
        self.assertEqual(result["hosted_ci_verdict"]["reason_code"],
                         "claim_malformed")
        with self.assertRaises(gate.GateOrderingError):
            gate.handoff_gate_status(
                make_head(), None, {"schema": "x"}, True,
                final_validation_receipt=make_fcv(),
                ci_verifier=passing_verifier())

    def test_h09_a_claim_may_pin_the_run_but_the_api_decides(self):
        claim = gate.build_hosted_ci_status(HEAD, "9001")
        result = gate.handoff_gate_status(
            make_head(), None, claim, True,
            final_validation_receipt=make_fcv(),
            ci_verifier=passing_verifier())
        self.assertTrue(result["handoff_complete"])
        self.assertEqual(result["hosted_ci_verdict"]["run"]["id"], 9001)
        claim = gate.build_hosted_ci_status(HEAD, "9002")
        result = gate.handoff_gate_status(
            make_head(), None, claim, True,
            final_validation_receipt=make_fcv(),
            ci_verifier=passing_verifier())
        self.assertFalse(result["handoff_complete"])

    def test_h10_a_stub_or_foreign_verdict_cannot_satisfy_the_gate(self):
        with self.assertRaises(gate.GateOrderingError):
            gate.handoff_gate_status(
                make_head(), None, None, True,
                final_validation_receipt=make_fcv(),
                ci_verifier=lambda sha: {"verdict": "PASS"})

        class Liar(hci.HostedCiVerifier):
            def verify(self, expected_sha, *, pinned_run_id=None):
                return {"schema": hci.VERDICT_SCHEMA, "verdict": "PASS",
                        "reason_code": None, "expected_sha": "b" * 40}
        result = gate.handoff_gate_status(
            make_head(), None, None, True,
            final_validation_receipt=make_fcv(),
            ci_verifier=Liar(FakeCiApi(), REPO))
        self.assertFalse(result["handoff_complete"])
        self.assertEqual(result["hosted_ci_verdict"]["reason_code"],
                         "verdict_mismatch")

    def test_h11_pr_head_mutation_after_ci_blocks_the_handoff(self):
        verifier = passing_verifier(pr_number=7)
        verifier.api.pulls[7] = fakes.pull(7, "c" * 40, "feature/x")
        result = gate.handoff_gate_status(
            make_head(), None, None, True,
            final_validation_receipt=make_fcv(), ci_verifier=verifier)
        self.assertFalse(result["handoff_complete"])
        self.assertEqual(result["hosted_ci_verdict"]["reason_code"],
                         "pr_head_moved")

    def test_h12_local_suite_receipt_path_keeps_its_semantics(self):
        suite = make_suite()
        local = {"schema": gate.RECEIPT_SCHEMA, "git_commit_sha": HEAD,
                 "suite": copy.deepcopy(suite), "environment": dict(ENV),
                 "result": "PASS", "count": suite["count"],
                 "started_unix": 1.0, "ended_unix": 2.0}
        result = gate.handoff_gate_status(
            make_head(), local, None, True,
            ci_verifier=passing_verifier())
        self.assertTrue(result["handoff_complete"])
        self.assertEqual(result["full_suite_proof"], "exact-head-suite-receipt")
        with self.assertRaises(gate.GateOrderingError):
            gate.handoff_gate_status(
                make_head(), local, None, True,
                final_validation_receipt=make_fcv(),
                ci_verifier=passing_verifier())

    def test_h13_signature_is_backward_compatible(self):
        params = list(inspect.signature(gate.handoff_gate_status)
                      .parameters.values())
        self.assertEqual([p.name for p in params[:5]],
                         ["final_head", "suite_receipt", "hosted_ci_status",
                          "finalizer_ok", "final_validation_receipt"])
        verifier = [p for p in params if p.name == "ci_verifier"][0]
        self.assertEqual(verifier.kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertIsNone(verifier.default)


# ---------------------------------------------------------------------------
# T — HTTP surface and CLIs
# ---------------------------------------------------------------------------

class HttpSurface(unittest.TestCase):
    def test_read_only_endpoints(self):
        import final_validation_reuse as reuse
        api = reuse.HttpActionsApi("https://api.github.com", REPO, TOKEN)
        seen = []
        api._get_json = lambda path: seen.append(path) or {}
        api.get_workflow("ci.yml")
        api.list_workflow_runs(342883623, REAL_SHA, 2, 100)
        api.list_run_jobs(77, 3, 100)
        api.get_pull(322)
        self.assertEqual(seen, [
            f"/repos/{REPO}/actions/workflows/ci.yml",
            f"/repos/{REPO}/actions/workflows/342883623/runs"
            f"?head_sha={REAL_SHA}&per_page=100&page=2",
            f"/repos/{REPO}/actions/runs/77/jobs"
            "?filter=latest&per_page=100&page=3",
            f"/repos/{REPO}/pulls/322",
        ])


class Clis(unittest.TestCase):
    def _run(self, argv, api, environ=None):
        out = Path(tempfile.mkdtemp()) / "verdict.json"
        env = {"GITHUB_TOKEN": TOKEN} if environ is None else environ
        rc = hci.main(argv + ["--out", str(out)], environ=env,
                      api_factory=lambda *a, **k: api)
        return rc, out

    def test_verify_cli_pass_blocked_and_secret_free(self):
        rc, out = self._run(["verify", "--repo", REPO, "--sha", REAL_SHA,
                             "--pr", "322"], FakeCiApi.genuine())
        self.assertEqual(rc, 0)
        data = json.loads(out.read_text())
        self.assertEqual(data["verdict"], "PASS")
        self.assertNotIn(TOKEN, out.read_text())
        rc, out = self._run(["verify", "--repo", REPO, "--sha",
                             fakes.SKIP_CI_SHA], FakeCiApi.skip_ci())
        self.assertEqual(rc, 3)
        self.assertEqual(json.loads(out.read_text())["reason_code"],
                         "no_ci_run")

    def test_verify_cli_rejects_bad_input_and_missing_credentials(self):
        rc, out = self._run(["verify", "--repo", REPO, "--sha", "abc"],
                            FakeCiApi.genuine())
        self.assertEqual(rc, 2)
        rc, out = self._run(["verify", "--repo", REPO, "--sha", REAL_SHA],
                            FakeCiApi.genuine(), environ={})
        self.assertEqual(rc, 2)
        self.assertFalse(out.exists())

    def test_handoff_cli_is_the_executable_authoritative_gate(self):
        tmp = Path(tempfile.mkdtemp())
        receipt = tmp / "fcv.json"
        receipt.write_text(json.dumps(make_fcv()))
        argv = ["handoff", "--final-validation-receipt", str(receipt),
                "--finalizer-ok", "--repo", REPO, "--pr", "7",
                "--out", str(tmp / "handoff.json")]
        rc = gate.main(argv, environ={"GITHUB_TOKEN": TOKEN},
                       api_factory=lambda *a, **k: world_for(HEAD),
                       request_factory=lambda root: make_head())
        self.assertEqual(rc, 0)
        data = json.loads((tmp / "handoff.json").read_text())
        self.assertTrue(data["handoff_complete"])
        self.assertNotIn(TOKEN, json.dumps(data))
        rc = gate.main(argv, environ={"GITHUB_TOKEN": TOKEN},
                       api_factory=lambda *a, **k: FakeCiApi(),
                       request_factory=lambda root: make_head())
        self.assertEqual(rc, 1)
        data = json.loads((tmp / "handoff.json").read_text())
        self.assertFalse(data["handoff_complete"])
        self.assertEqual(data["hosted_ci_verdict"]["reason_code"],
                         "no_ci_run")


# ---------------------------------------------------------------------------
# D — workflow-identity pins and documented recovery
# ---------------------------------------------------------------------------

class WorkflowAndDocs(unittest.TestCase):
    def test_verifier_constants_track_the_real_ci_workflow(self):
        import yaml
        workflow = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
        self.assertEqual(workflow["name"], hci.CI_WORKFLOW_NAME)
        self.assertEqual(workflow["jobs"]["ci-gate"]["name"],
                         hci.CI_GATE_JOB_NAME)
        self.assertEqual(workflow["jobs"]["plan"]["name"],
                         hci.REQUIRED_SUCCESS_JOBS[0])
        self.assertEqual(workflow["jobs"]["repo-integrity"]["name"],
                         hci.REQUIRED_SUCCESS_JOBS[1])
        triggers = workflow.get("on", workflow.get(True))
        for event in hci.ALLOWED_EVENTS:
            self.assertIn(event, triggers)
        self.assertEqual(hci.CI_WORKFLOW_PATH, ".github/workflows/ci.yml")

    def test_authentic_fixture_job_names_match_the_workflow(self):
        import yaml
        workflow = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
        names = {job["name"] for job in workflow["jobs"].values()}
        self.assertIn("CI Gate", names)
        self.assertIn("Plan CI (impact selection)", names)
        self.assertIn("Group repo-integrity (always-on)", names)

    def test_final_cpu_validation_stays_dispatch_only(self):
        import yaml
        workflow = yaml.safe_load(FCV_YML.read_text(encoding="utf-8"))
        triggers = workflow.get("on", workflow.get(True))
        self.assertEqual(list(triggers), ["workflow_dispatch"])

    def test_doc_describes_enforcement_and_skip_ci_recovery(self):
        text = DOC.read_text(encoding="utf-8")
        for needle in ("hosted_ci_verification.py", "[skip ci]",
                       "workflow_dispatch", "gh workflow run ci.yml",
                       "pr_head_moved", "Required status checks",
                       "ruleset", "CI Gate",
                       "Issue #323"):
            self.assertIn(needle, text, needle)


if __name__ == "__main__":
    unittest.main()
