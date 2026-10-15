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

Review correction (maintainer review of the first head, P1-A/B/C): the
repository, the API origin and the PR are TRUST ANCHORS, not caller input.

* A — the repository: only ``Zutfen-LLC/inferswarm`` is ever authorized; a
  caller-supplied ``--repo`` cannot authorize another repository, even one
  that holds the identical commit SHA and internally consistent records.
* B — the API origin: only ``https://api.github.com`` is ever contacted with
  the bearer token; a spoofed HTTPS ``GITHUB_API_URL`` is rejected before
  any request.  Offline fakes stay injectable from Python only.
* C — the current PR: the authoritative handoff requires ``--pr``; the PR is
  read before verification and again after the CI run/jobs checks and any
  head/branch/state/identity drift between the reads is BLOCKED.

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

import contextlib
import copy
import inspect
import io
import json
import os
import subprocess
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


def world_for(sha: str, branch: str = "feature/x", run_id: int = 9001,
              repo: str = REPO):
    """A genuine-shaped CI world for an arbitrary head (in ``repo``)."""
    api = FakeCiApi(repo)
    api.add_run(fakes.ci_run(run_id, sha, branch, repo=repo, pr=7))
    api.pulls = {7: fakes.pull(7, sha, branch, repo=repo, base_repo=repo)}
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
        case("run no head_sha", lambda a: (
            a.runs[0].pop("head_sha"),
            setattr(a, "ignore_head_filter", True)))
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


def passing_verifier(sha: str = HEAD, pr_number: int | None = 7):
    """A verifier bound to the head's PR (7): the authoritative shape."""
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
        empty = FakeCiApi()
        empty.pulls = {7: fakes.pull(7, HEAD, "feature/x")}
        verifier = hci.HostedCiVerifier(empty, REPO, pr_number=7)
        result = gate.handoff_gate_status(
            make_head(), None, forged, True,
            final_validation_receipt=make_fcv(), ci_verifier=verifier)
        self.assertFalse(result["handoff_complete"])
        # No ordinary CI exists at all: the forged run id is not even
        # consulted as a possible source of success.
        self.assertEqual(result["hosted_ci_verdict"]["reason_code"],
                         "no_ci_run")

    def test_h03b_forged_run_id_cannot_borrow_a_real_run(self):
        forged = gate.build_hosted_ci_status(HEAD, "424242")
        result = gate.handoff_gate_status(
            make_head(), None, forged, True,
            final_validation_receipt=make_fcv(),
            ci_verifier=passing_verifier())
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
            ci_verifier=Liar(FakeCiApi(), REPO, pr_number=7))
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
        empty = FakeCiApi()
        empty.pulls = {7: fakes.pull(7, HEAD, "feature/x")}
        rc = gate.main(argv, environ={"GITHUB_TOKEN": TOKEN},
                       api_factory=lambda *a, **k: empty,
                       request_factory=lambda root: make_head())
        self.assertEqual(rc, 1)
        data = json.loads((tmp / "handoff.json").read_text())
        self.assertFalse(data["handoff_complete"])
        self.assertEqual(data["hosted_ci_verdict"]["reason_code"],
                         "no_ci_run")

# ---------------------------------------------------------------------------
# Review correction — trust anchors (P1-A repository, P1-B origin, P1-C PR)
# ---------------------------------------------------------------------------

# Literals on purpose: the anchors are pinned independently of the module
# constants they test.
CANONICAL = "Zutfen-LLC/inferswarm"
EVIL_REPO = "evil/inferswarm"
OFFICIAL_API = "https://api.github.com"
EVIL_API = "https://evil.example"


def run_cli(main, argv, **kwargs):
    """Run a CLI ``main`` capturing stdout: ``(return code, stdout)``."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        rc = main(argv, **kwargs)
    return rc, buffer.getvalue()


def cli_env(**extra):
    env = {"GITHUB_TOKEN": TOKEN}
    env.update(extra)
    return env


def verify_argv(out, *, repo=REPO, pr="322", sha=REAL_SHA):
    argv = ["verify", "--repo", repo, "--sha", sha, "--out", str(out)]
    return argv + (["--pr", pr] if pr is not None else [])


def handoff_argv(tmp, *, repo=REPO, pr="7"):
    receipt = Path(tmp) / "fcv.json"
    receipt.write_text(json.dumps(make_fcv()))
    argv = ["handoff", "--final-validation-receipt", str(receipt),
            "--finalizer-ok", "--repo", repo,
            "--out", str(Path(tmp) / "handoff.json")]
    return argv + (["--pr", pr] if pr is not None else [])


class RepositoryTrustAnchor(_Base):
    """P1-A: a caller-supplied ``--repo`` must not authorize a repository."""

    def test_a01_foreign_repo_with_identical_sha_and_consistent_records(self):
        # The attack: another repository holds the IDENTICAL commit SHA and
        # supplies internally consistent successful workflow, run, job and PR
        # records, and the caller names that repository.
        evil = FakeCiApi.genuine(EVIL_REPO)
        self.assertEqual(evil.runs[0]["head_sha"], REAL_SHA)
        self.assertEqual(evil.runs[0]["repository"]["full_name"], EVIL_REPO)
        with self.assertRaises(ValueError):
            hci.HostedCiVerifier(evil, EVIL_REPO, pr_number=322)

    def test_a02_forged_records_cannot_vouch_for_the_canonical_repo(self):
        # A client that LIES about its binding but serves evil-repo records
        # is still rejected by the record-level repository checks.
        evil = FakeCiApi.genuine(EVIL_REPO)
        evil.repository = CANONICAL
        self.assertBlocked(verify(evil, pr_number=322), "foreign_repository")

    def test_a03_handoff_rejects_a_verifier_retargeted_at_a_foreign_repo(self):
        verifier = passing_verifier()
        verifier.api = world_for(HEAD, repo=EVIL_REPO)
        verifier.repository = EVIL_REPO
        result = gate.handoff_gate_status(
            make_head(), None, None, True,
            final_validation_receipt=make_fcv(), ci_verifier=verifier)
        self.assertFalse(result["handoff_complete"])
        self.assertFalse(result["hosted_ci_success"])
        self.assertEqual(result["hosted_ci_verdict"]["reason_code"],
                         "repository_not_canonical")
        self.assertEqual(verifier.api.calls, [])

    def test_a04_verify_cli_rejects_a_foreign_repo_before_any_request(self):
        out = Path(tempfile.mkdtemp()) / "verdict.json"
        built = []
        rc, text = run_cli(
            hci.main, verify_argv(out, repo=EVIL_REPO),
            environ=cli_env(),
            api_factory=lambda *a, **k: built.append(a)
            or FakeCiApi.genuine(EVIL_REPO))
        self.assertEqual(rc, 2, text)
        self.assertEqual(built, [])
        self.assertFalse(out.exists())
        self.assertNotIn(TOKEN, text)

    def test_a05_handoff_cli_rejects_a_foreign_repo(self):
        tmp = tempfile.mkdtemp()
        built = []
        rc, text = run_cli(
            gate.main, handoff_argv(tmp, repo=EVIL_REPO),
            environ=cli_env(),
            api_factory=lambda *a, **k: built.append(a)
            or world_for(HEAD, repo=EVIL_REPO),
            request_factory=lambda root: make_head())
        self.assertEqual(rc, 2, text)
        self.assertEqual(built, [])
        self.assertFalse((Path(tmp) / "handoff.json").exists())

    def test_a06_near_miss_repository_spellings_are_rejected(self):
        for variant in ("zutfen-llc/inferswarm", "Zutfen-LLC/inferswarm-evil",
                        "Zutfen-LLC-evil/inferswarm", "evil/Zutfen-LLC",
                        "Zutfen-LLC/inferswarm.git", "Zutfen-LLC/Inferswarm",
                        "Zutfen-LLC/inferswarm/", " Zutfen-LLC/inferswarm",
                        "Zutfen-LLC/inferswarm\n", ""):
            with self.assertRaises(ValueError, msg=repr(variant)):
                hci.HostedCiVerifier(FakeCiApi(), variant)

    def test_a07_api_client_bound_to_another_repository_is_rejected(self):
        with self.assertRaises(ValueError):
            hci.HostedCiVerifier(FakeCiApi(repository=EVIL_REPO), REPO)

    def test_a08_the_anchors_are_pinned_literals(self):
        self.assertEqual(getattr(hci, "CANONICAL_REPOSITORY", None),
                         CANONICAL)
        self.assertEqual(getattr(hci, "OFFICIAL_API_ORIGIN", None),
                         OFFICIAL_API)

    def test_a09_canonical_repository_positive_control(self):
        tmp = tempfile.mkdtemp()
        out = Path(tmp) / "verdict.json"
        rc, text = run_cli(hci.main, verify_argv(out, repo=CANONICAL),
                           environ=cli_env(),
                           api_factory=lambda *a, **k: FakeCiApi.genuine())
        self.assertEqual(rc, 0, text)
        self.assertEqual(json.loads(out.read_text())["repository"], CANONICAL)
        rc, text = run_cli(
            gate.main, handoff_argv(tmp, repo=CANONICAL),
            environ=cli_env(), api_factory=lambda *a, **k: world_for(HEAD),
            request_factory=lambda root: make_head())
        self.assertEqual(rc, 0, text)
        self.assertTrue(json.loads(
            (Path(tmp) / "handoff.json").read_text())["handoff_complete"])


class ApiOriginAuthentication(unittest.TestCase):
    """P1-B: the bearer token goes ONLY to the official GitHub API origin.

    ``HttpEmulator`` runs the REAL ``HttpActionsApi`` and answers any origin
    with internally consistent successful records, exactly like a spoofed
    HTTPS endpoint would; it records every request and its credential.
    """

    def _verify(self, env, *, world=None, pr="322"):
        out = Path(tempfile.mkdtemp()) / "verdict.json"
        with fakes.HttpEmulator(world or FakeCiApi.genuine()) as http:
            rc, text = run_cli(hci.main, verify_argv(out, pr=pr),
                               environ=env)
        return rc, text, http, out

    def test_b01_official_origin_end_to_end_token_only_to_official(self):
        for env in (cli_env(), cli_env(GITHUB_API_URL=OFFICIAL_API)):
            rc, text, http, out = self._verify(env)
            self.assertEqual(rc, 0, text)
            self.assertEqual(json.loads(out.read_text())["verdict"], "PASS")
            self.assertTrue(http.requests)
            self.assertEqual(http.hosts(), ["api.github.com"])
            for url, authorization in http.requests:
                self.assertTrue(url.startswith(
                    f"{OFFICIAL_API}/repos/{CANONICAL}/"), url)
                self.assertEqual(authorization, f"Bearer {TOKEN}")
            self.assertNotIn(TOKEN, out.read_text() + text)

    def test_b02_spoofed_https_origin_is_rejected_before_any_request(self):
        rc, text, http, out = self._verify(
            cli_env(GITHUB_API_URL=EVIL_API))
        # Baseline: the spoofed endpoint received the bearer token and its
        # consistent forged records produced a PASS.
        self.assertEqual(rc, 2, text)
        self.assertEqual(http.requests, [])
        self.assertFalse(out.exists())
        self.assertNotIn(TOKEN, text)

    def test_b03_lookalike_and_malformed_origins_are_rejected(self):
        for origin in ("https://api.github.com.evil.example",
                       "https://api.github.com@evil.example",
                       "https://api.github.com\\@evil.example",
                       "https://evil.example/api.github.com",
                       "https://evil.example#api.github.com",
                       "https://api.github.com:8443",
                       "https://api.github.com/evil",
                       "https://api.github.com/",
                       "https://api.github.com?x=1",
                       "https://api.github.com#x",
                       "https://api.github.com.",
                       "https://API.GITHUB.COM",
                       "HTTPS://api.github.com",
                       " https://api.github.com",
                       "https://github.com/api/v3",
                       "http://api.github.com",
                       "http://127.0.0.1:8080",
                       "ftp://api.github.com",
                       "api.github.com",
                       ""):
            rc, text, http, out = self._verify(
                cli_env(GITHUB_API_URL=origin))
            self.assertEqual(rc, 2, (origin, text))
            self.assertEqual(http.requests, [], origin)
            self.assertFalse(out.exists(), origin)

    def test_b04_default_factory_pins_origin_and_repository(self):
        with self.assertRaises(ValueError):
            hci.default_api_factory(EVIL_API, REPO, TOKEN)
        with self.assertRaises(ValueError):
            hci.default_api_factory(OFFICIAL_API, EVIL_REPO, TOKEN)
        client = hci.default_api_factory(OFFICIAL_API, REPO, TOKEN)
        self.assertEqual((client.api_url, client.repository),
                         (OFFICIAL_API, CANONICAL))
        self.assertFalse(client._insecure_ok)

    def test_b05_a_client_aimed_elsewhere_cannot_back_the_verifier(self):
        import final_validation_reuse as reuse
        with fakes.HttpEmulator(FakeCiApi.genuine()) as http:
            for client in (
                    reuse.HttpActionsApi(EVIL_API, REPO, TOKEN),
                    reuse.HttpActionsApi("http://127.0.0.1:1", REPO, TOKEN,
                                         _allow_insecure_loopback=True),
                    reuse.HttpActionsApi(OFFICIAL_API, EVIL_REPO, TOKEN),
                    # official URL, but the test-only mode that also bypasses
                    # proxies: never a production client
                    reuse.HttpActionsApi(OFFICIAL_API, REPO, TOKEN,
                                         _allow_insecure_loopback=True)):
                with self.assertRaises(ValueError):
                    hci.HostedCiVerifier(client, REPO, pr_number=322)
            self.assertEqual(http.requests, [])
        hci.HostedCiVerifier(
            reuse.HttpActionsApi(OFFICIAL_API, REPO, TOKEN), REPO,
            pr_number=322)

    def test_b06_handoff_cli_origin_pin_and_official_positive_control(self):
        for env, expect_rc in ((cli_env(GITHUB_API_URL=EVIL_API), 2),
                               (cli_env(GITHUB_API_URL=OFFICIAL_API), 0)):
            tmp = tempfile.mkdtemp()
            with fakes.HttpEmulator(world_for(HEAD)) as http:
                rc, text = run_cli(gate.main, handoff_argv(tmp),
                                   environ=env,
                                   request_factory=lambda root: make_head())
            self.assertEqual(rc, expect_rc, text)
            if expect_rc:
                self.assertEqual(http.requests, [])
                self.assertFalse((Path(tmp) / "handoff.json").exists())
            else:
                self.assertEqual(http.hosts(), ["api.github.com"])
                self.assertTrue(all(auth == f"Bearer {TOKEN}"
                                    for _, auth in http.requests))
                self.assertNotIn(
                    TOKEN, (Path(tmp) / "handoff.json").read_text())

    def test_b07_a_redirect_is_never_followed_with_the_token(self):
        world = FakeCiApi.genuine()
        out = Path(tempfile.mkdtemp()) / "verdict.json"
        with fakes.HttpEmulator(world) as http:
            http.redirect_to = EVIL_API + "/steal"
            rc, text = run_cli(hci.main, verify_argv(out), environ=cli_env())
        self.assertEqual(rc, 3, text)
        self.assertEqual(json.loads(out.read_text())["reason_code"],
                         "api_unavailable")
        self.assertEqual(http.hosts(), ["api.github.com"])

    def test_b08_injection_is_python_only_never_cli_or_env(self):
        self.assertEqual(
            inspect.signature(hci.main).parameters["api_factory"].kind,
            inspect.Parameter.KEYWORD_ONLY)
        tmp = tempfile.mkdtemp()
        for main, argv in (
                (hci.main, verify_argv(Path(tmp) / "v.json")),
                (gate.main, handoff_argv(tmp))):
            for flag in ("--api-url", "--api-factory", "--insecure"):
                with self.assertRaises(SystemExit) as caught, \
                        contextlib.redirect_stderr(io.StringIO()):
                    main(argv + [flag, EVIL_API], environ=cli_env())
                self.assertEqual(caught.exception.code, 2, flag)

    def test_b09_real_entrypoints_reject_a_spoofed_origin(self):
        tmp = Path(tempfile.mkdtemp())
        env = {"PATH": os.environ.get("PATH", ""), "GITHUB_TOKEN": TOKEN,
               "GITHUB_API_URL": "https://evil.invalid"}
        for script, argv in (
                ("hosted_ci_verification.py",
                 verify_argv(tmp / "verdict.json")),
                ("issue213_gate_orchestration.py",
                 ["handoff", "--finalizer-ok", "--suite-receipt",
                  str(tmp / "none.json"), "--repo", REPO, "--pr", "7",
                  "--out", str(tmp / "handoff.json")])):
            proc = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / script)] + argv,
                env=env, capture_output=True, text=True, timeout=120,
                cwd=str(tmp))
            blob = proc.stdout + proc.stderr
            self.assertEqual(proc.returncode, 2, (script, blob))
            self.assertNotIn(TOKEN, blob)
        self.assertEqual(sorted(p.name for p in tmp.iterdir()), [])


class CurrentPrBinding(_Base):
    """P1-C: the authoritative handoff is bound to the CURRENT open PR head."""

    @staticmethod
    def later(change):
        """Mutate the PR on the FINAL read only (call 2 onwards)."""
        def mutator(call, pull):
            if call >= 2:
                change(pull)
            return pull
        return mutator

    def test_c20_pr_is_read_first_and_again_after_the_jobs(self):
        api = FakeCiApi.genuine()
        self.assertPass(verify(api, pr_number=322))
        names = api.called()
        self.assertEqual(names.count("get_pull"), 2, names)
        self.assertEqual(names[0], "get_pull", names)
        self.assertEqual(names[-1], "get_pull", names)
        last_ci_read = max(i for i, n in enumerate(names)
                           if n in ("get_run", "list_run_jobs"))
        self.assertLess(last_ci_read, len(names) - 1)

    def test_c21_pr_drift_between_the_first_and_final_read_is_blocked(self):
        cases = (
            ("head moved", lambda p: p["head"].update(sha=fakes.OTHER_SHA),
             "pr_head_moved"),
            ("branch renamed", lambda p: p["head"].update(ref="renamed"),
             "pr_branch_drift"),
            ("closed", lambda p: p.update(state="closed"), "pr_not_open"),
            ("head repo became a fork",
             lambda p: p["head"]["repo"].update(full_name="fork/inferswarm"),
             "foreign_repository"),
            ("base repo foreign",
             lambda p: p["base"]["repo"].update(full_name=EVIL_REPO),
             "foreign_repository"),
            ("other PR", lambda p: p.update(number=999),
             "inconsistent_metadata"),
            ("retargeted", lambda p: p["base"].update(ref="release"),
             "pr_identity_drift"),
            ("head vanished", lambda p: p.pop("head"), "malformed_response"),
        )
        for label, change, code in cases:
            api = FakeCiApi.genuine()
            api.get_pull_mutator = self.later(change)
            self.assertBlocked(verify(api, pr_number=322), code)
            self.assertEqual(api.get_pull_calls, 2, label)

    def test_c21b_api_failure_on_the_final_read_is_blocked(self):
        api = FakeCiApi.genuine()

        def fail(call, pull):
            if call >= 2:
                raise hci.ApiUnavailable("HTTP 502")
            return pull
        api.get_pull_mutator = fail
        self.assertBlocked(verify(api, pr_number=322), "api_unavailable")

    def test_c22_pr_must_be_open_and_in_the_canonical_repo_on_first_read(self):
        api = FakeCiApi.genuine()
        api.pulls[322] = fakes.pull(322, state="closed")
        self.assertBlocked(verify(api, pr_number=322), "pr_not_open")
        api = FakeCiApi.genuine()
        api.pulls[322] = fakes.pull(322, base_repo=EVIL_REPO)
        self.assertBlocked(verify(api, pr_number=322), "foreign_repository")

    def test_c23_pass_verdict_records_the_pr_binding(self):
        verdict = verify(FakeCiApi.genuine(), pr_number=322)
        self.assertPass(verdict)
        self.assertIs(verdict["pr_bound"], True)
        pull = verdict["pull_request"]
        self.assertEqual((pull["number"], pull["state"], pull["head_sha"],
                          pull["head_ref"], pull["reads"]),
                         (322, "open", REAL_SHA, fakes.REAL_BRANCH, 2))
        self.assertEqual((pull["head_repository"], pull["base_repository"]),
                         (CANONICAL, CANONICAL))

    def test_c24_unbound_verifier_cannot_complete_the_handoff(self):
        world = world_for(HEAD)
        verifier = hci.HostedCiVerifier(world, REPO)  # diagnostic shape
        result = gate.handoff_gate_status(
            make_head(), None, None, True,
            final_validation_receipt=make_fcv(), ci_verifier=verifier)
        self.assertFalse(result["handoff_complete"])
        self.assertFalse(result["hosted_ci_success"])
        self.assertEqual(result["hosted_ci_verdict"]["reason_code"],
                         "pr_binding_missing")
        self.assertEqual(world.calls, [])  # rejected before any request

    def test_c25_handoff_rejects_a_verdict_not_bound_to_the_pr(self):
        class Unbound(hci.HostedCiVerifier):
            def verify(self, expected_sha, *, pinned_run_id=None):
                verdict = super().verify(expected_sha,
                                         pinned_run_id=pinned_run_id)
                verdict["pr_bound"] = False
                return verdict

        class OtherPr(hci.HostedCiVerifier):
            def verify(self, expected_sha, *, pinned_run_id=None):
                verdict = super().verify(expected_sha,
                                         pinned_run_id=pinned_run_id)
                verdict["pull_request"]["number"] = 8
                return verdict

        for cls in (Unbound, OtherPr):
            result = gate.handoff_gate_status(
                make_head(), None, None, True,
                final_validation_receipt=make_fcv(),
                ci_verifier=cls(world_for(HEAD), REPO, pr_number=7))
            self.assertFalse(result["handoff_complete"], cls)
            self.assertEqual(result["hosted_ci_verdict"]["reason_code"],
                             "verdict_mismatch", cls)

    def test_c25b_handoff_revalidates_pr_and_repository_in_the_verdict(self):
        def tamper(change):
            class Tampered(hci.HostedCiVerifier):
                def verify(self, expected_sha, *, pinned_run_id=None):
                    verdict = super().verify(expected_sha,
                                             pinned_run_id=pinned_run_id)
                    change(verdict)
                    return verdict
            return Tampered(world_for(HEAD), REPO, pr_number=7)

        for label, change in (
                ("PR closed", lambda v: v["pull_request"].update(
                    state="closed")),
                ("PR at another head", lambda v: v["pull_request"].update(
                    head_sha="c" * 40)),
                ("foreign repository", lambda v: v.update(
                    repository=EVIL_REPO)),
                ("no PR evidence", lambda v: v.update(pull_request=None))):
            result = gate.handoff_gate_status(
                make_head(), None, None, True,
                final_validation_receipt=make_fcv(),
                ci_verifier=tamper(change))
            self.assertFalse(result["handoff_complete"], label)
            self.assertEqual(result["hosted_ci_verdict"]["reason_code"],
                             "verdict_mismatch", label)
        # control: the untampered verdict completes
        self.assertTrue(gate.handoff_gate_status(
            make_head(), None, None, True,
            final_validation_receipt=make_fcv(),
            ci_verifier=tamper(lambda v: None))["handoff_complete"])

    def test_c26_handoff_blocks_on_pr_mutation_between_reads(self):
        for label, change, code in (
                ("moved", lambda p: p["head"].update(sha="c" * 40),
                 "pr_head_moved"),
                ("closed", lambda p: p.update(state="closed"),
                 "pr_not_open"),
                ("branch", lambda p: p["head"].update(ref="other"),
                 "pr_branch_drift")):
            verifier = passing_verifier()
            verifier.api.get_pull_mutator = self.later(change)
            result = gate.handoff_gate_status(
                make_head(), None, None, True,
                final_validation_receipt=make_fcv(), ci_verifier=verifier)
            self.assertFalse(result["handoff_complete"], label)
            self.assertEqual(result["hosted_ci_verdict"]["reason_code"],
                             code, label)

    def test_c27_handoff_cli_requires_a_current_pr(self):
        for pr in (None, "0", "-3"):
            tmp = tempfile.mkdtemp()
            built = []
            rc, text = run_cli(
                gate.main, handoff_argv(tmp, pr=pr), environ=cli_env(),
                api_factory=lambda *a, **k: built.append(a)
                or world_for(HEAD),
                request_factory=lambda root: make_head())
            self.assertEqual(rc, 2, (pr, text))
            self.assertEqual(built, [], pr)
            self.assertFalse((Path(tmp) / "handoff.json").exists(), pr)
            self.assertIn("--pr", text)

    def test_c27b_verify_cli_rejects_a_nonpositive_pr(self):
        for pr in ("0", "-3"):
            out = Path(tempfile.mkdtemp()) / "verdict.json"
            built = []
            rc, text = run_cli(
                hci.main, verify_argv(out, pr=pr), environ=cli_env(),
                api_factory=lambda *a, **k: built.append(a)
                or FakeCiApi.genuine())
            self.assertEqual(rc, 2, (pr, text))
            self.assertEqual(built, [], pr)
            self.assertFalse(out.exists(), pr)

    def test_c28_standalone_verify_stays_flexible_but_is_marked_unbound(self):
        out = Path(tempfile.mkdtemp()) / "verdict.json"
        rc, text = run_cli(hci.main, verify_argv(out, pr=None),
                           environ=cli_env(),
                           api_factory=lambda *a, **k: FakeCiApi.genuine())
        self.assertEqual(rc, 0, text)
        verdict = json.loads(out.read_text())
        self.assertEqual(verdict["verdict"], "PASS")
        self.assertIs(verdict["pr_bound"], False)
        self.assertIn("diagnostic", text.lower())
        self.assertIn("handoff", text.lower())


# ---------------------------------------------------------------------------
# R — run -> PR association (maintainer review of 280ebb43, P1)
# ---------------------------------------------------------------------------

_DROP = object()  # marker: remove this key from a record
PR_A, PR_B = 322, 401
BASE_A, BASE_B = "main", "release/0.9"
BRANCH = fakes.REAL_BRANCH


def run_for(pr: int, run_id: int, **kwargs) -> dict:
    """A ``pull_request`` CI run of ``pr`` (PR A -> main, PR B -> release)."""
    return fakes.ci_run(run_id, REAL_SHA, BRANCH, pr=pr,
                        base_ref=BASE_A if pr == PR_A else BASE_B, **kwargs)


def two_prs(*runs: dict) -> FakeCiApi:
    """Two OPEN PRs: same repository, head SHA and head branch, DIFFERENT
    base branches — the review's scenario — and the given CI runs."""
    api = FakeCiApi()
    api.pulls = {PR_A: fakes.pull(PR_A, REAL_SHA, BRANCH, base_ref=BASE_A),
                 PR_B: fakes.pull(PR_B, REAL_SHA, BRANCH, base_ref=BASE_B)}
    for run in runs:
        api.add_run(run)
    return api


def both_associations() -> list:
    return [fakes.pr_association(PR_A, REAL_SHA, BRANCH, BASE_A),
            fakes.pr_association(PR_B, REAL_SHA, BRANCH, BASE_B)]


def handoff(verifier_cls, api, pr, sha=REAL_SHA):
    return gate.handoff_gate_status(
        make_head(sha), None, None, True,
        final_validation_receipt=make_fcv(sha),
        ci_verifier=verifier_cls(api, REPO, pr_number=pr))


class RunToPrAssociation(_Base):
    """A ``pull_request`` CI run authorizes ONLY the PR GitHub associates it
    with.  Before the correction ``_run()`` discarded ``pull_requests`` and
    any run with the right ``head_sha`` / branch name counted, so PR A's
    green CI satisfied the handoff of PR B (same head, different base)."""

    # -- the attack ------------------------------------------------------
    def test_r01_pr_a_success_cannot_authorize_pr_b(self):
        api = two_prs(run_for(PR_A, 100))
        # control: PR A's own CI authorizes PR A
        ok = verify(api, pr_number=PR_A)
        self.assertPass(ok)
        self.assertEqual((ok["run"]["id"], ok["pull_request"]["number"]),
                         (100, PR_A))
        # the attack: PR B has no qualifying run of its own
        blocked = verify(api, pr_number=PR_B)
        self.assertBlocked(blocked, "no_ci_run")
        self.assertIsNone(blocked["run"])
        self.assertIs(blocked["pr_bound"], False)
        [considered] = blocked["considered_runs"]
        self.assertTrue(considered["ignored"])
        self.assertEqual(considered["ignored_reason"], "other_pr")
        self.assertEqual(considered["pull_requests"], [PR_A])

    def test_r02_empty_association_cannot_authorize_a_pr_bound_verdict(self):
        api = FakeCiApi.genuine()
        api.runs[0]["pull_requests"] = []
        self.assertBlocked(verify(api, pr_number=322),
                           "pr_association_missing")
        # the unbound diagnostic keeps its flexibility but is never bound
        diagnostic = verify(api)
        self.assertPass(diagnostic)
        self.assertIs(diagnostic["pr_bound"], False)

    def test_r03_run_associated_with_another_pr_number_is_not_this_prs(self):
        for other in (1, 323, 999):
            api = FakeCiApi.genuine()
            api.runs[0]["pull_requests"] = [
                fakes.pr_association(other, REAL_SHA, fakes.REAL_BRANCH)]
            self.assertBlocked(verify(api, pr_number=322), "no_ci_run")

    def test_r04_ambiguous_association_never_authorizes(self):
        api = two_prs(run_for(PR_A, 100, pull_requests=both_associations()))
        for pr in (PR_A, PR_B):
            self.assertBlocked(verify(api, pr_number=pr),
                               "pr_association_ambiguous")
        # the same PR listed twice is equally ambiguous
        api = FakeCiApi.genuine()
        api.runs[0]["pull_requests"] *= 2
        self.assertBlocked(verify(api, pr_number=322),
                           "pr_association_ambiguous")

    def test_r05_contradictory_association_metadata_blocks(self):
        cases = (
            ("base branch is not the PR's",
             lambda e: e["base"].update(ref=BASE_B)),
            ("head branch is not the run's / PR's",
             lambda e: e["head"].update(ref="other/branch")),
            ("head sha is not the run's",
             lambda e: e["head"].update(sha=fakes.OTHER_SHA)),
            ("head repository is a fork",
             lambda e: e["head"].update(repo=fakes.repo_ref("fork/inferswarm"))),
            ("base repository is foreign",
             lambda e: e["base"].update(repo=fakes.repo_ref(EVIL_REPO))),
        )
        for label, change in cases:
            api = FakeCiApi.genuine()
            change(api.runs[0]["pull_requests"][0])
            self.assertBlocked(verify(api, pr_number=322),
                               "pr_association_mismatch")

    def test_r05b_a_pr_retargeted_after_its_ci_cannot_borrow_that_run(self):
        # The run's association names base main; the PR now targets release.
        api = FakeCiApi.genuine()
        api.pulls[322] = fakes.pull(322, REAL_SHA, BRANCH, base_ref=BASE_B)
        self.assertBlocked(verify(api, pr_number=322),
                           "pr_association_mismatch")

    def test_r06_malformed_association_blocks(self):
        def entry(**changes):
            def build(run):
                run["pull_requests"] = [fakes.pr_association(
                    322, REAL_SHA, fakes.REAL_BRANCH)]
                for key, value in changes.items():
                    if value is _DROP:
                        run["pull_requests"][0].pop(key)
                    else:
                        run["pull_requests"][0][key] = value
            return build

        def top(value):
            def build(run):
                if value is _DROP:
                    run.pop("pull_requests")
                else:
                    run["pull_requests"] = value
            return build
        cases = {
            "key missing": top(_DROP),
            "null": top(None),
            "a string": top("322"),
            "an object": top({"number": 322}),
            "an empty object": top({}),
            "an empty string": top(""),
            "bare numbers (a trimmed view, not the REST object)": top([322]),
            "empty object entry": top([{}]),
            "number missing": entry(number=_DROP),
            "number is a bool": entry(number=True),
            "number is a string": entry(number="322"),
            "number is zero": entry(number=0),
            "head missing": entry(head=_DROP),
            "head not an object": entry(head="main"),
            "base missing": entry(base=_DROP),
            "head sha malformed": entry(
                head={"ref": fakes.REAL_BRANCH, "sha": "abc",
                      "repo": fakes.repo_ref(REPO)}),
            "head ref empty": entry(
                head={"ref": "", "sha": REAL_SHA,
                      "repo": fakes.repo_ref(REPO)}),
            "head repo missing": entry(
                head={"ref": fakes.REAL_BRANCH, "sha": REAL_SHA}),
            "base repo url garbage": entry(
                base={"ref": "main", "sha": fakes.BASE_SHA,
                      "repo": {"id": 1, "url": "not a url", "name": "x"}}),
            "base repo url with a trailing path": entry(
                base={"ref": "main", "sha": fakes.BASE_SHA,
                      "repo": {"id": 1, "name": "inferswarm",
                               "url": f"{OFFICIAL_API}/repos/{CANONICAL}"
                                      "/pulls/322"}}),
            "base repo url on another origin": entry(
                base={"ref": "main", "sha": fakes.BASE_SHA,
                      "repo": {"id": 1, "name": "inferswarm",
                               "url": f"{EVIL_API}/repos/{CANONICAL}"}}),
        }
        for label, build in cases.items():
            api = FakeCiApi.genuine()
            build(api.runs[0])
            verdict = verify(api, pr_number=322)
            self.assertBlocked(verdict, "malformed_response")
            self.assertFalse(verdict["pr_bound"], label)

    def test_r06b_other_events_need_no_readable_association(self):
        # ``pull_requests`` is nullable/absent for some events: an unrelated
        # push run on the same SHA, or a dispatch recovery run, must neither
        # block nor be judged by it.
        for value in (None, _DROP, "x"):
            api = two_prs(run_for(PR_B, 100))
            for run_id, event in ((50, "push"), (200, "workflow_dispatch")):
                extra = fakes.ci_run(run_id, REAL_SHA, BRANCH, event=event)
                if value is _DROP:
                    extra.pop("pull_requests")
                else:
                    extra["pull_requests"] = value
                api.add_run(extra)
            verdict = verify(api, pr_number=PR_B)
            self.assertPass(verdict)
            self.assertEqual(verdict["run"]["id"], 200)  # newest dispatch
            # ...and the pull_request run is still judged on its own
            api.runs[:] = [r for r in api.runs if r["event"] != "workflow_dispatch"]
            self.assertEqual(verify(api, pr_number=PR_B)["run"]["id"], 100)

    # -- selection -------------------------------------------------------
    def test_r07_a_foreign_prs_run_never_supersedes_or_rescues(self):
        # B's legitimate run is older; A's newer run FAILED: it does not
        # supersede B's success...
        api = two_prs(run_for(PR_B, 100),
                      run_for(PR_A, 200, conclusion="failure"))
        api.job("CI Gate", 200).update(conclusion="failure")
        verdict = verify(api, pr_number=PR_B)
        self.assertPass(verdict)
        self.assertEqual(verdict["run"]["id"], 100)
        self.assertEqual([(r["id"], r["ignored"])
                          for r in verdict["considered_runs"]],
                         [(100, False), (200, True)])
        self.assertBlocked(verify(api, pr_number=PR_A), "ci_failed")
        # ...and A's newer SUCCESS cannot rescue B's failed run.
        api = two_prs(run_for(PR_B, 100, conclusion="failure"),
                      run_for(PR_A, 200))
        self.assertBlocked(verify(api, pr_number=PR_B), "ci_failed")
        self.assertPass(verify(api, pr_number=PR_A))

    def test_r07b_newest_run_of_the_same_pr_still_decides(self):
        api = two_prs(run_for(PR_B, 100), run_for(PR_A, 200),
                      run_for(PR_B, 300, conclusion="failure"))
        self.assertBlocked(verify(api, pr_number=PR_B), "ci_failed")
        api = two_prs(run_for(PR_B, 100, conclusion="failure"),
                      run_for(PR_A, 200),
                      run_for(PR_B, 300))
        verdict = verify(api, pr_number=PR_B)
        self.assertPass(verdict)
        self.assertEqual(verdict["run"]["id"], 300)

    def test_r07c_latest_attempt_semantics_are_preserved(self):
        api = two_prs(run_for(PR_B, 100, attempt=2))
        # jobs of the previous attempt are stale for the latest attempt
        api.jobs[100] = fakes.ci_jobs(100, REAL_SHA, attempt=1)
        self.assertBlocked(verify(api, pr_number=PR_B), "stale_attempt")
        api = two_prs(run_for(PR_B, 100, attempt=2))
        self.assertPass(verify(api, pr_number=PR_B))

    def test_r07d_a_pin_can_only_name_a_run_of_this_pr(self):
        api = two_prs(run_for(PR_A, 100), run_for(PR_B, 150))
        self.assertBlocked(verify(api, pr_number=PR_B, pinned_run_id=100),
                           "pinned_run_not_found")
        self.assertPass(verify(api, pr_number=PR_B, pinned_run_id=150))
        self.assertPass(verify(api, pr_number=PR_A, pinned_run_id=100))

    def test_r08_an_unclassifiable_newer_run_blocks_but_dispatch_recovers(self):
        # A newer pull_request run with an empty association might BE this
        # PR's newer run: the older success may not decide over it...
        api = two_prs(run_for(PR_B, 100),
                      run_for(PR_B, 200, pull_requests=[]))
        self.assertBlocked(verify(api, pr_number=PR_B),
                           "pr_association_missing")
        # ...but an unclassifiable run OLDER than the deciding run is
        # superseded, so the documented dispatch recovery still works.
        api.add_run(fakes.ci_run(300, REAL_SHA, BRANCH,
                                 event="workflow_dispatch"))
        verdict = verify(api, pr_number=PR_B)
        self.assertPass(verdict)
        self.assertEqual(verdict["run"]["id"], 300)
        # an unattributable run can never be pinned as the deciding run
        self.assertBlocked(verify(api, pr_number=PR_B, pinned_run_id=200),
                           "pinned_run_not_found")
        self.assertPass(verify(api, pr_number=PR_B, pinned_run_id=300))

    # -- workflow_dispatch recovery -------------------------------------------
    def test_r09_dispatch_recovery_needs_no_association(self):
        # PR B has no CI of its own; PR A does.  A dispatched run on the
        # exact head and branch is the documented recovery.
        api = two_prs(run_for(PR_A, 100))
        api.add_run(fakes.ci_run(200, REAL_SHA, BRANCH,
                                 event="workflow_dispatch"))
        self.assertEqual(api.runs[1]["pull_requests"], [])
        verdict = verify(api, pr_number=PR_B)
        self.assertPass(verdict)
        self.assertEqual((verdict["run"]["id"], verdict["run"]["event"]),
                         (200, "workflow_dispatch"))
        self.assertIs(verdict["pr_bound"], True)
        self.assertIsNone(verdict["run"]["pr_association"])

    def test_r09b_dispatch_must_still_match_the_prs_head_and_branch(self):
        api = two_prs()
        api.add_run(fakes.ci_run(200, REAL_SHA, "some/other-branch",
                                 event="workflow_dispatch"))
        self.assertBlocked(verify(api, pr_number=PR_B), "branch_mismatch")
        # a dispatch on another head is not even listed for this head
        api = two_prs()
        api.add_run(fakes.ci_run(200, fakes.OTHER_SHA, BRANCH,
                                 event="workflow_dispatch"))
        self.assertBlocked(verify(api, pr_number=PR_B), "no_ci_run")

    def test_r09c_a_dispatch_run_is_not_judged_by_advisory_associations(self):
        # GitHub documents ``pull_requests`` as the PRs open for the branch,
        # "not necessarily" the trigger; a dispatch run is anchored by head
        # SHA + branch only, so a listed PR neither helps nor hurts it.
        api = two_prs()
        api.add_run(fakes.ci_run(200, REAL_SHA, BRANCH,
                                 event="workflow_dispatch",
                                 pull_requests=both_associations()))
        self.assertPass(verify(api, pr_number=PR_B))

    # -- consistency across the re-reads --------------------------------------
    def test_r10_association_must_be_stable_across_the_run_rereads(self):
        def flip(call_no, change):
            def mutator(call, run):
                if call == call_no:
                    change(run)
                return run
            return mutator
        for change in (
                lambda r: r["pull_requests"][0]["base"].update(ref=BASE_B),
                lambda r: r["pull_requests"][0].update(number=PR_B),
                lambda r: r.update(pull_requests=[])):
            api = FakeCiApi.genuine()
            api.get_run_mutator = flip(1, change)
            self.assertBlocked(verify(api, pr_number=322),
                               "inconsistent_metadata")
            api = FakeCiApi.genuine()
            api.get_run_mutator = flip(2, change)
            self.assertBlocked(verify(api, pr_number=322),
                               "ambiguous_evidence")

    def test_r10b_pr_retarget_between_the_reads_still_blocks(self):
        api = two_prs(run_for(PR_B, 100))

        def retarget(call, pull):
            if call >= 2:
                pull["base"]["ref"] = BASE_A
            return pull
        api.get_pull_mutator = retarget
        self.assertBlocked(verify(api, pr_number=PR_B), "pr_identity_drift")

    # -- the verdict and the handoff ------------------------------------------
    def test_r11_pass_verdict_records_the_authenticated_association(self):
        verdict = verify(two_prs(run_for(PR_B, 100)), pr_number=PR_B)
        self.assertPass(verdict)
        self.assertEqual(verdict["run"]["pr_association"],
                         {"number": PR_B, "head_ref": BRANCH,
                          "head_sha": REAL_SHA, "base_ref": BASE_B})
        self.assertEqual(verdict["pull_request"]["base_ref"], BASE_B)

    def test_r12_the_handoff_refuses_another_prs_ci(self):
        api = two_prs(run_for(PR_A, 100))
        refused = handoff(hci.HostedCiVerifier, api, PR_B)
        self.assertFalse(refused["handoff_complete"])
        self.assertFalse(refused["hosted_ci_success"])
        self.assertEqual(refused["hosted_ci_verdict"]["reason_code"],
                         "no_ci_run")
        accepted = handoff(hci.HostedCiVerifier, api, PR_A)
        self.assertTrue(accepted["handoff_complete"])

    def test_r12b_the_handoff_revalidates_the_association_in_the_verdict(self):
        def tampered(change):
            class Tampered(hci.HostedCiVerifier):
                def verify(self, expected_sha, *, pinned_run_id=None):
                    verdict = super().verify(expected_sha,
                                             pinned_run_id=pinned_run_id)
                    change(verdict)
                    return verdict
            return Tampered

        def run_of(verdict):
            return verdict["run"]
        api = two_prs(run_for(PR_B, 100))
        for label, change in (
                ("association names another PR",
                 lambda v: run_of(v)["pr_association"].update(number=PR_A)),
                ("association base is not the PR's",
                 lambda v: run_of(v)["pr_association"].update(base_ref=BASE_A)),
                ("association head is not the PR's",
                 lambda v: run_of(v)["pr_association"].update(head_ref="x")),
                ("association head sha is not the PR's",
                 lambda v: run_of(v)["pr_association"].update(
                     head_sha=fakes.OTHER_SHA)),
                ("pull_request run without association",
                 lambda v: run_of(v).update(pr_association=None)),
                ("run branch is not the PR's",
                 lambda v: run_of(v).update(head_branch="x")),
                ("unknown event",
                 lambda v: run_of(v).update(event="push"))):
            result = handoff(tampered(change), api, PR_B)
            self.assertFalse(result["handoff_complete"], label)
            self.assertEqual(result["hosted_ci_verdict"]["reason_code"],
                             "verdict_mismatch", label)
        self.assertTrue(handoff(tampered(lambda v: None), api,
                                PR_B)["handoff_complete"])

    def test_r12c_the_handoff_accepts_and_revalidates_a_dispatch_run(self):
        api = two_prs()
        api.add_run(fakes.ci_run(200, REAL_SHA, BRANCH,
                                 event="workflow_dispatch"))
        self.assertTrue(handoff(hci.HostedCiVerifier, api,
                                PR_B)["handoff_complete"])

        class WrongBranch(hci.HostedCiVerifier):
            def verify(self, expected_sha, *, pinned_run_id=None):
                verdict = super().verify(expected_sha,
                                         pinned_run_id=pinned_run_id)
                verdict["run"]["head_branch"] = "x"
                return verdict
        result = handoff(WrongBranch, api, PR_B)
        self.assertFalse(result["handoff_complete"])
        self.assertEqual(result["hosted_ci_verdict"]["reason_code"],
                         "verdict_mismatch")

    # -- the real wire path -------------------------------------------------
    def test_r13_end_to_end_over_the_real_http_client(self):
        def verify_cli(pr):
            out = Path(tempfile.mkdtemp()) / "verdict.json"
            with fakes.HttpEmulator(two_prs(run_for(PR_A, 100))) as http:
                rc, text = run_cli(hci.main, verify_argv(out, pr=str(pr)),
                                   environ=cli_env())
            self.assertEqual(http.hosts(), ["api.github.com"])
            return rc, text, json.loads(out.read_text())
        rc, text, verdict = verify_cli(PR_A)
        self.assertEqual((rc, verdict["verdict"], verdict["run"]["id"]),
                         (0, "PASS", 100), text)
        rc, text, verdict = verify_cli(PR_B)
        self.assertEqual((rc, verdict["verdict"], verdict["reason_code"]),
                         (3, "BLOCKED", "no_ci_run"), text)

    def test_r14_the_live_pr_324_run_belongs_to_pr_324_and_only_to_it(self):
        # Identifiers of the authentic hosted run for the reviewed head.
        api = FakeCiApi()
        api.pulls = {
            fakes.LIVE_PR: fakes.pull(fakes.LIVE_PR, fakes.LIVE_SHA,
                                      fakes.LIVE_BRANCH),
            325: fakes.pull(325, fakes.LIVE_SHA, fakes.LIVE_BRANCH,
                            base_ref=BASE_B)}
        api.add_run(fakes.ci_run(fakes.LIVE_RUN_ID, fakes.LIVE_SHA,
                                 fakes.LIVE_BRANCH, pr=fakes.LIVE_PR))
        verdict = verify(api, fakes.LIVE_SHA, pr_number=fakes.LIVE_PR)
        self.assertPass(verdict)
        self.assertEqual(verdict["run"]["pr_association"]["number"],
                         fakes.LIVE_PR)
        self.assertBlocked(verify(api, fakes.LIVE_SHA, pr_number=325),
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

    def test_doc_describes_the_run_to_pr_association(self):
        text = DOC.read_text(encoding="utf-8")
        for needle in ("pull_requests", "pr_association_missing",
                       "pr_association_ambiguous", "pr_association_mismatch",
                       "`other_pr`", "`run.pr_association`",
                       "can neither authorize nor supersede",
                       "anchored by the exact head and the PR's head branch",
                       "`verdict_mismatch`"):
            self.assertIn(needle, text, needle)
        source = (ROOT / "scripts" / "hosted_ci_verification.py").read_text(
            encoding="utf-8")
        for code in ("pr_association_missing", "pr_association_ambiguous",
                     "pr_association_mismatch"):
            self.assertIn(code, source, code)

    def test_doc_describes_the_trust_anchors(self):
        text = DOC.read_text(encoding="utf-8")
        for needle in ("Zutfen-LLC/inferswarm", "https://api.github.com",
                       "repository_not_canonical", "pr_binding_missing",
                       "pr_not_open", "pr_branch_drift", "pr_identity_drift",
                       "`--pr` is required", "diagnostic"):
            self.assertIn(needle, text, needle)


if __name__ == "__main__":
    unittest.main()
