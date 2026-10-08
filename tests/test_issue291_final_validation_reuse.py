#!/usr/bin/env python3
"""Issue #291 — verified exact-head receipt reuse for hosted Final CPU Validation.

Adversarial controls for ``scripts/final_validation_reuse.py``, the
envelope ``execution`` block in ``scripts/issue213_gate_orchestration.py``
and the real ``.github/workflows/final-cpu-validation.yml``.

The hosted workflow's concurrency group serializes same-SHA dispatches but
does not stop a later dispatch from re-running the 3,000+ test suite on a
fresh runner.  The fix is a read-only, fail-closed lookup of a previously
SUCCESSFUL hosted Final CPU Validation for the same immutable head; a
verified match is recorded as ``verified_prior_execution`` and the suite is
not run a second time.  Everything else — any doubt at all — runs the suite.

Control map:

* W — the REAL workflow: untrusted inputs never interpolated into inline
  Python/shell source, minimum ``actions: read`` permission, lookup placed
  after exact-SHA checkout/doctor and BEFORE the suite, the suite step
  conditional on the lookup, finalizer/status steps unconditional, the PASS
  receipt artifact minted only on success while diagnostics are always kept.
* I — strict input validation (expected_sha / pr_number).
* R — RED/GREEN: two hosted dispatches for one head execute the canonical
  suite exactly once and the second gate records authenticated reuse.
* N — every ineligible source (changed configuration/environment, failed /
  cancelled / pending / skipped / wrong-head / tampered / forged / recursive
  / malformed ...) results in a FULL execution, never reuse.
* A — Actions API outage / rate limit / permission loss / malformed
  payloads / candidate floods are bounded and fail closed.
* E — the envelope ``execution`` block (schema), handoff equivalence and
  legacy-envelope compatibility.
* H — the HTTP client never sends the token to a redirect target.
"""
from __future__ import annotations

import copy
import hashlib
import http.server
import io
import json
import os
import re
import sys
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import issue213_gate_orchestration as gate  # noqa: E402
import final_validation_reuse as reuse  # noqa: E402

WORKFLOW = ROOT / ".github" / "workflows" / "final-cpu-validation.yml"
SHA = "a" * 40
OTHER_SHA = "b" * 40
REPO = "Zutfen-LLC/inferswarm"
SUITE_STEP = "Run canonical full CPU suite (serial/executed identity required)"


def _load_workflow() -> dict:
    import yaml
    with open(WORKFLOW, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def make_suite(serial: str = "f" * 64, count: int = 3237,
               plan_digest: str = "a" * 64, jobs: int = 4) -> dict:
    return {
        "runner_schema": gate.RUNNER_SCHEMA,
        "suite_command": list(gate.FULL_SUITE_COMMAND),
        "suite_config": {
            "schema": gate.SUITE_CONFIG_SCHEMA, "tests_dir": "tests",
            "jobs": jobs, "plan_digest": plan_digest, "timeout": 1800.0,
            "retain_dir": None},
        "serial_digest": serial, "executed_digest": serial, "count": count,
    }


def make_request(sha: str = SHA, **suite_kw) -> gate.FinalHeadRequest:
    return gate.FinalHeadRequest(
        git_commit_sha=sha, suite=make_suite(**suite_kw),
        environment={rel: "e" * 64 for rel in gate.ENV_AUTHORITY_FILES})


def suite_receipt_for(request: gate.FinalHeadRequest) -> dict:
    return {"schema": gate.RECEIPT_SCHEMA,
            "git_commit_sha": request.git_commit_sha,
            "suite": copy.deepcopy(request.suite),
            "environment": copy.deepcopy(request.environment),
            "result": "PASS", "count": request.suite["count"],
            "started_unix": 1000.0, "ended_unix": 2000.0}


def executed_envelope(request: gate.FinalHeadRequest, run_id: int,
                      attempt: int = 1, **overrides) -> dict:
    envelope = gate.build_final_validation_receipt(
        request.git_commit_sha, suite_receipt_for(request),
        github_run_id=str(run_id), github_run_attempt=attempt,
        finalizer_check=True, project_status_check=True,
        execution=gate.execution_block_executed(request.git_commit_sha))
    envelope.update(overrides)
    return envelope


def make_run(run_id: int, sha: str = SHA, **over) -> dict:
    run = {
        "id": run_id, "name": "Final CPU Validation",
        "path": reuse.WORKFLOW_PATH, "event": "workflow_dispatch",
        "status": "completed", "conclusion": "success",
        "head_sha": sha, "run_attempt": 1,
        "repository": {"full_name": REPO},
        "head_repository": {"full_name": REPO},
    }
    run.update(over)
    return run


def zip_bytes(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def dumps(envelope: dict) -> bytes:
    return json.dumps(envelope, sort_keys=True).encode()


class FakeApi:
    """In-memory Actions API (read-only surface the lookup may use)."""

    def __init__(self):
        self.runs: list[dict] = []
        self.artifacts: dict[int, list[dict]] = {}
        self.blobs: dict[int, bytes] = {}
        self.calls: list[tuple] = []
        self.fail: dict[str, Exception] = {}
        self._artifact_ids = iter(range(5000, 10**6))

    def add(self, run: dict, *, envelope: dict | None = None,
            blob: bytes | None = None, members: dict | None = None,
            artifact: dict | None = None, digest: str | None = None,
            with_artifact: bool = True) -> dict | None:
        self.runs.insert(0, run)  # newest first
        if not with_artifact:
            return None
        if blob is None:
            if members is None:
                members = {reuse.RECEIPT_MEMBER: dumps(envelope)}
            blob = zip_bytes(members)
        art_id = next(self._artifact_ids)
        art = {
            "id": art_id, "name": reuse.RECEIPT_ARTIFACT_NAME,
            "size_in_bytes": len(blob), "expired": False,
            "digest": digest or "sha256:" + hashlib.sha256(blob).hexdigest(),
            "workflow_run": {"id": run["id"], "repository_id": 1,
                             "head_repository_id": 1,
                             "head_sha": run["head_sha"]},
        }
        art.update(artifact or {})
        self.artifacts.setdefault(run["id"], []).append(art)
        self.blobs[art_id] = blob
        return art

    # --- API surface -----------------------------------------------------
    def _maybe_fail(self, name):
        if name in self.fail:
            raise self.fail[name]

    def list_runs(self, page, per_page):
        self.calls.append(("list_runs", page))
        self._maybe_fail("list_runs")
        start = (page - 1) * per_page
        return {"total_count": len(self.runs),
                "workflow_runs": self.runs[start:start + per_page]}

    def list_artifacts(self, run_id):
        self.calls.append(("list_artifacts", run_id))
        self._maybe_fail("list_artifacts")
        arts = self.artifacts.get(run_id, [])
        return {"total_count": len(arts), "artifacts": arts}

    def download_artifact(self, artifact_id, max_bytes):
        self.calls.append(("download", artifact_id))
        self._maybe_fail("download")
        data = self.blobs[artifact_id]
        if len(data) > max_bytes:
            raise reuse.ApiUnavailable("artifact exceeds byte bound")
        return data

    def count(self, kind):
        return sum(1 for c in self.calls if c[0] == kind)


def lookup(api, request=None, *, expected_sha=SHA, current_run_id=9000,
           dispatch_sha=None, **kw):
    return reuse.lookup_verified_prior_execution(
        api, expected_sha=expected_sha, request=request or make_request(),
        current_run_id=current_run_id,
        dispatch_sha=dispatch_sha or expected_sha, repository=REPO, **kw)


class HostedSim:
    """The workflow's decision flow, driven by the REAL modules.

    ``dispatch`` mirrors the workflow: lookup; if no verified source, one
    physical canonical-suite execution (counted) and an executed envelope;
    otherwise a reuse envelope.  The run's receipt artifact is published
    exactly like the upload step on success.
    """

    def __init__(self):
        self.api = FakeApi()
        self.executions = 0
        self.next_run_id = 1000

    def dispatch(self, request=None, *, expected_sha=SHA, dispatch_sha=None,
                 pr_number=None):
        request = request or make_request(expected_sha)
        run_id = self.next_run_id
        self.next_run_id += 1
        decision = reuse.lookup_verified_prior_execution(
            self.api, expected_sha=expected_sha, request=request,
            current_run_id=run_id, dispatch_sha=dispatch_sha or expected_sha,
            repository=REPO)
        if decision["action"] == "reuse":
            envelope = reuse.compose_reuse_envelope(
                decision, request=request, expected_sha=expected_sha,
                github_run_id=str(run_id), github_run_attempt=1,
                workflow="Final CPU Validation", pr_number=pr_number,
                dispatch_sha=dispatch_sha or expected_sha,
                finalizer_check=True, project_status_check=True)
        else:
            self.executions += 1   # the ONE physical suite execution
            envelope = gate.build_final_validation_receipt(
                expected_sha, suite_receipt_for(request),
                github_run_id=str(run_id), github_run_attempt=1,
                pr_number=pr_number, finalizer_check=True,
                project_status_check=True,
                execution=gate.execution_block_executed(
                    dispatch_sha or expected_sha))
        self.api.add(make_run(run_id, expected_sha), envelope=envelope)
        return envelope, decision


# ---------------------------------------------------------------------------
# W — the real workflow
# ---------------------------------------------------------------------------

class WorkflowControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = _load_workflow()
        cls.text = WORKFLOW.read_text(encoding="utf-8")
        cls.steps = cls.doc["jobs"]["final-cpu-validation"]["steps"]
        cls.names = [s.get("name", "") for s in cls.steps]

    def step(self, needle):
        return next(s for s in self.steps if needle in s.get("name", ""))

    def test_w1_no_expression_interpolation_into_run_blocks(self):
        # Untrusted dispatch inputs (and everything else) reach scripts
        # only through quoted environment bindings, never by being spliced
        # into inline Python/shell source.
        for step in self.steps:
            if "run" in step:
                self.assertNotIn(
                    "${{", step["run"],
                    f"step {step.get('name')!r} interpolates an expression "
                    "into script source")

    def test_w2_inputs_only_flow_through_env_checkout_and_concurrency(self):
        for step in self.steps:
            for key, value in (step.get("with") or {}).items():
                if "inputs." in str(value):
                    self.assertEqual(
                        (step["uses"].split("@")[0], key),
                        ("actions/checkout", "ref"))
        for step in self.steps:
            for key, value in (step.get("env") or {}).items():
                if "inputs." in str(value):
                    self.assertIn(key, {"EXPECTED_SHA", "PR_NUMBER"})
        self.assertEqual(
            self.doc["concurrency"],
            {"group": "final-cpu-validation-${{ inputs.expected_sha }}",
             "cancel-in-progress": False})

    def test_w3_minimum_permissions_read_only(self):
        self.assertEqual(self.doc["permissions"],
                         {"contents": "read", "actions": "read"})
        self.assertNotIn("secrets.", self.text)
        self.assertNotRegex(self.text, r"(?m)^\s+[a-z-]+:\s*write\b")

    def test_w4_lookup_after_checkout_doctor_before_suite(self):
        order = self.names
        lookup_i = next(i for i, n in enumerate(order)
                        if "prior execution" in n.lower())
        self.assertGreater(lookup_i, order.index(
            "Mechanically require HEAD == expected_sha"))
        self.assertGreater(lookup_i, next(
            i for i, n in enumerate(order) if n.startswith("Doctor")))
        self.assertLess(lookup_i, order.index(SUITE_STEP))
        lookup_step = self.steps[lookup_i]
        self.assertIn("final_validation_reuse.py", lookup_step["run"])
        self.assertIn("id", lookup_step)
        env = lookup_step["env"]
        self.assertEqual(env["EXPECTED_SHA"], "${{ inputs.expected_sha }}")
        self.assertEqual(env["GITHUB_TOKEN"], "${{ github.token }}")

    def test_w5_suite_step_skipped_only_by_verified_reuse(self):
        lookup_step = self.step("prior execution")
        suite = self.step("Run canonical full CPU suite")
        condition = suite.get("if", "")
        self.assertIn(f"steps.{lookup_step['id']}.outputs.reuse", condition)
        self.assertIn("!= 'true'", condition)
        # the suite command itself is unchanged (canonical, no overrides)
        self.assertIn("scripts/run_full_cpu_suite.py --json", suite["run"])
        self.assertIn("exit $suite_rc", suite["run"])

    def test_w6_finalizer_status_and_compose_always_run_on_this_head(self):
        for needle in ("finalizer", "project-status", "Compose"):
            step = self.step(needle)
            self.assertNotIn("if", step,
                             f"{needle} step must be unconditional")

    def test_w7_compose_binds_run_identity_via_env(self):
        compose = self.step("Compose")
        self.assertIn("final_validation_reuse.py compose", compose["run"])
        env = compose["env"]
        for key in ("EXPECTED_SHA", "PR_NUMBER", "GITHUB_RUN_ID",
                    "GITHUB_RUN_ATTEMPT"):
            self.assertIn(key, env)
        self.assertEqual(env["GITHUB_RUN_ID"], "${{ github.run_id }}")
        self.assertEqual(env["GITHUB_RUN_ATTEMPT"],
                         "${{ github.run_attempt }}")

    def test_w8_pass_receipt_only_on_success_diagnostics_always(self):
        uploads = [s for s in self.steps
                   if "upload-artifact" in s.get("uses", "")]
        by_name = {s["with"]["name"]: s for s in uploads}
        receipt = by_name["final-cpu-validation-receipt"]
        self.assertEqual(receipt["if"], "success()")
        self.assertEqual(receipt["with"]["path"].strip(),
                         "/tmp/final-validation-receipt.json")
        self.assertEqual(receipt["with"]["if-no-files-found"], "error")
        diag = by_name["final-cpu-validation-diagnostics"]
        self.assertEqual(diag["if"], "always()")
        self.assertNotIn("final-validation-receipt.json",
                         diag["with"]["path"],
                         "a failed run must never carry a PASS receipt")
        self.assertIn("/tmp/suite-result.json", diag["with"]["path"])

    def test_w9_exact_sha_authority_unchanged(self):
        checkout = self.step("Check out")
        self.assertEqual(checkout["with"]["ref"],
                         "${{ inputs.expected_sha }}")
        self.assertIn("rev-parse HEAD", self.step("Mechanically")["run"])
        self.assertNotIn("github.ref", self.text)

    def test_w10_first_step_validates_inputs_strictly_from_env(self):
        first = self.steps[0]
        self.assertIn("EXPECTED_SHA", first["env"])
        self.assertIn("PR_NUMBER", first["env"])
        self.assertIn("os.environ", first["run"])
        self.assertIn("fullmatch", first["run"])


# ---------------------------------------------------------------------------
# I — input validation
# ---------------------------------------------------------------------------

class InputValidation(unittest.TestCase):
    def test_expected_sha_strict(self):
        self.assertEqual(reuse.validate_expected_sha(SHA), SHA)
        for bad in ("", SHA.upper(), "a" * 39, "a" * 41, SHA + "\n",
                    " " + SHA, "g" * 40, '"; touch /tmp/pwn; "',
                    "a" * 40 + "\\", "$(id)" + "a" * 35, None, 5):
            with self.subTest(bad=bad), self.assertRaises(
                    reuse.InputError):
                reuse.validate_expected_sha(bad)

    def test_pr_number_strict_audit_only(self):
        self.assertIsNone(reuse.validate_pr_number(""))
        self.assertIsNone(reuse.validate_pr_number(None))
        self.assertEqual(reuse.validate_pr_number("290"), 290)
        for bad in ("0", "-1", "01", "29 0", "290\n", " 290", "2.9",
                    "abc", "1" * 12, "290; rm -rf /", "٣٠٠", "0x10"):
            with self.subTest(bad=bad), self.assertRaises(
                    reuse.InputError):
                reuse.validate_pr_number(bad)


# ---------------------------------------------------------------------------
# R — duplicate dispatch executes the suite once
# ---------------------------------------------------------------------------

class DuplicateDispatch(unittest.TestCase):
    def test_r1_second_dispatch_reuses_first_one_physical_execution(self):
        sim = HostedSim()
        first, d1 = sim.dispatch(pr_number=290)
        second, d2 = sim.dispatch(pr_number=291)  # pr_number is audit-only
        self.assertEqual(d1["action"], "run")
        self.assertEqual(d2["action"], "reuse")
        self.assertEqual(sim.executions, 1,
                         "two hosted dispatches must execute the canonical "
                         "suite exactly once")
        self.assertEqual(first["execution"]["mode"], "executed")
        ex = second["execution"]
        self.assertEqual(ex["mode"], "verified_prior_execution")
        self.assertEqual(ex["source_run_id"], first["github_run_id"])
        self.assertEqual(ex["source_run_attempt"], 1)
        self.assertEqual(ex["dispatch_sha"], SHA)
        self.assertRegex(ex["source_artifact_digest"],
                         r"^sha256:[0-9a-f]{64}$")
        self.assertRegex(ex["source_envelope_sha256"], r"^[0-9a-f]{64}$")
        # a NEW gate result: its own run identity, the exact head, the
        # source's suite receipt (full suite identity) — not a copy of the
        # source envelope's run identity.
        self.assertNotEqual(second["github_run_id"], first["github_run_id"])
        self.assertEqual(second["git_commit_sha"], SHA)
        self.assertEqual(second["suite_receipt"], first["suite_receipt"])
        self.assertEqual(second["pr_number"], 291)

    def test_r2_reuse_envelope_satisfies_the_existing_handoff_gate(self):
        sim = HostedSim()
        sim.dispatch()
        second, _ = sim.dispatch()
        request = make_request()
        ci = gate.build_hosted_ci_status(SHA, "ci-1")
        status = gate.handoff_gate_status(
            request, None, ci, True, final_validation_receipt=second)
        self.assertTrue(status["handoff_complete"])
        self.assertEqual(status["full_suite_proof"],
                         "hosted-final-validation")
        # other-head requests are still refused
        other = make_request(OTHER_SHA)
        with self.assertRaises(gate.GateOrderingError):
            gate.handoff_gate_status(
                other, None, gate.build_hosted_ci_status(OTHER_SHA, "c"),
                True, final_validation_receipt=second)

    def test_r3_third_dispatch_never_chains_through_a_reuse_receipt(self):
        sim = HostedSim()
        sim.dispatch()
        sim.dispatch()
        third, decision = sim.dispatch()
        self.assertEqual(decision["action"], "reuse")
        # source is the EXECUTED run (1000), never the reuse run (1001)
        self.assertEqual(third["execution"]["source_run_id"], "1000")
        self.assertEqual(sim.executions, 1)

    def test_r4_changed_head_or_configuration_runs_again(self):
        sim = HostedSim()
        sim.dispatch()
        _, d = sim.dispatch(make_request(OTHER_SHA), expected_sha=OTHER_SHA)
        self.assertEqual(d["action"], "run")
        _, d = sim.dispatch(make_request(plan_digest="c" * 64))
        self.assertEqual(d["action"], "run")
        self.assertEqual(sim.executions, 3)

    def test_r5_reuse_decision_records_audit_fields(self):
        sim = HostedSim()
        sim.dispatch()
        _, d = sim.dispatch()
        self.assertEqual(d["schema"], reuse.DECISION_SCHEMA)
        self.assertEqual(d["source"]["run_id"], 1000)
        self.assertEqual(d["source"]["run_attempt"], 1)
        self.assertEqual(d["rejected"], [])
        self.assertLessEqual(d["api_calls"], 4)


# ---------------------------------------------------------------------------
# N — ineligible sources always run the full suite
# ---------------------------------------------------------------------------

def _mutate_envelope(mutator):
    def build(request, run_id):
        envelope = executed_envelope(request, run_id)
        mutator(envelope)
        return envelope
    return build


class IneligibleSources(unittest.TestCase):
    """Each case installs ONE otherwise-valid prior run with ONE defect."""

    request = make_request()

    def install(self, *, run=None, envelope=None, **kw):
        api = FakeApi()
        run_obj = make_run(500, **(run or {}))
        env = envelope if envelope is not None else \
            executed_envelope(self.request, 500)
        api.add(run_obj, envelope=env, **kw)
        return api

    def assert_runs(self, api, expected_reason=None, **kw):
        decision = lookup(api, self.request, **kw)
        self.assertEqual(decision["action"], "run", decision)
        self.assertIsNone(decision.get("source"))
        if expected_reason:
            self.assertIn(expected_reason,
                          json.dumps(decision["rejected"]) +
                          decision["reason"])
        return decision

    def test_n0_control_positive(self):
        api = self.install()
        self.assertEqual(lookup(api, self.request)["action"], "reuse")

    def test_n1_run_level_defects(self):
        cases = {
            "failure": {"conclusion": "failure"},
            "cancelled": {"conclusion": "cancelled"},
            "skipped": {"conclusion": "skipped"},
            "neutral": {"conclusion": "neutral"},
            "pending": {"status": "in_progress", "conclusion": None},
            "queued": {"status": "queued", "conclusion": None},
            "no-conclusion": {"conclusion": None},
            "wrong-head": {"head_sha": OTHER_SHA},
            "wrong-event": {"event": "push"},
            "wrong-workflow-path": {"path": ".github/workflows/ci.yml"},
            "wrong-name": {"name": "CI"},
            "fork-head": {"head_repository": {"full_name": "evil/inferswarm"}},
            "foreign-repo": {"repository": {"full_name": "evil/inferswarm"}},
            "missing-repo": {"repository": None},
            "self-reference": {"id": 9000},
            "future-run": {"id": 9001},
            "bad-attempt": {"run_attempt": 0},
            "string-id": {"id": "500"},
        }
        for name, over in cases.items():
            with self.subTest(case=name):
                api = FakeApi()
                run = make_run(500, **over)
                rid = run["id"] if isinstance(run["id"], int) else 500
                api.add(run, envelope=executed_envelope(self.request, rid))
                self.assert_runs(api)

    def test_n2_artifact_level_defects(self):
        good = lambda: executed_envelope(self.request, 500)  # noqa: E731
        cases = {
            "expired": {"artifact": {"expired": True}},
            "wrong-name": {"artifact": {"name": "ci-receipt"}},
            "wrong-run-binding": {"artifact": {
                "workflow_run": {"id": 501, "repository_id": 1,
                                 "head_repository_id": 1,
                                 "head_sha": SHA}}},
            "wrong-head-binding": {"artifact": {
                "workflow_run": {"id": 500, "repository_id": 1,
                                 "head_repository_id": 1,
                                 "head_sha": OTHER_SHA}}},
            "fork-binding": {"artifact": {
                "workflow_run": {"id": 500, "repository_id": 1,
                                 "head_repository_id": 2,
                                 "head_sha": SHA}}},
            "missing-digest": {"artifact": {"digest": None}},
            "malformed-digest": {"artifact": {"digest": "md5:abc"}},
            "tampered-digest": {"digest": "sha256:" + "0" * 64},
            "oversized": {"artifact": {
                "size_in_bytes": reuse.MAX_ARTIFACT_BYTES + 1}},
        }
        for name, kw in cases.items():
            with self.subTest(case=name):
                api = FakeApi()
                api.add(make_run(500), envelope=good(), **kw)
                self.assert_runs(api)
        with self.subTest(case="no-artifact"):
            api = FakeApi()
            api.add(make_run(500), with_artifact=False)
            self.assert_runs(api)
        with self.subTest(case="duplicate-artifacts"):
            api = FakeApi()
            api.add(make_run(500), envelope=good())
            api.add(make_run(500), envelope=good())
            api.runs.pop(0)
            self.assert_runs(api)

    def test_n3_archive_content_defects(self):
        env = executed_envelope(self.request, 500)
        good = dumps(env)
        cases = {
            "not-a-zip": {"blob": b"PK\x03\x04 not really"},
            "empty-zip": {"members": {}},
            "wrong-member": {"members": {"other.json": good}},
            "extra-member": {"members": {reuse.RECEIPT_MEMBER: good,
                                         "extra.txt": b"x"}},
            "path-traversal": {"members": {"../receipt.json": good}},
            "nested-member": {"members": {"d/" + reuse.RECEIPT_MEMBER: good}},
            "not-json": {"members": {reuse.RECEIPT_MEMBER: b"{nope"}},
            "json-array": {"members": {reuse.RECEIPT_MEMBER: b"[1]"}},
            "nan-constant": {"members": {
                reuse.RECEIPT_MEMBER: good.replace(b"1000.0", b"NaN")}},
            "duplicate-keys": {"members": {reuse.RECEIPT_MEMBER:
                good[:-1] + b', "workflow": "CI"}'}},
            "zip-bomb": {"members": {reuse.RECEIPT_MEMBER:
                b" " * (reuse.MAX_MEMBER_BYTES + 1)}},
        }
        for name, kw in cases.items():
            with self.subTest(case=name):
                api = FakeApi()
                api.add(make_run(500), **kw)
                self.assert_runs(api)

    def test_n4_receipt_semantics(self):
        req = self.request
        cases = {
            "partial-no-suite-receipt": lambda e: e.pop("suite_receipt"),
            "not-pass": lambda e: e["suite_receipt"].update(
                {"result": "FAIL"}),
            "finalizer-false": lambda e: e.update({"finalizer_check": False}),
            "status-false": lambda e: e.update(
                {"project_status_check": False}),
            "forged-run-id": lambda e: e.update({"github_run_id": "123"}),
            "mismatched-attempt": lambda e: e.update(
                {"github_run_attempt": 2}),
            "wrong-sha": lambda e: e.update({"git_commit_sha": OTHER_SHA}),
            "embedded-other-head": lambda e: e["suite_receipt"].update(
                {"git_commit_sha": OTHER_SHA}),
            "wrong-schema": lambda e: e.update(
                {"schema": "hosted-final-validation-receipt/0"}),
            "wrong-workflow": lambda e: e.update({"workflow": "CI"}),
            "legacy-no-execution-block": lambda e: e.pop("execution"),
            "unknown-execution-mode": lambda e: e["execution"].update(
                {"mode": "assumed"}),
            "other-contract": lambda e: e["execution"].update(
                {"reuse_contract": "final-validation-reuse/0"}),
            "dispatch-sha-differs": lambda e: e["execution"].update(
                {"dispatch_sha": OTHER_SHA}),
            "extra-execution-key": lambda e: e["execution"].update(
                {"trust_me": True}),
        }
        for name, mut in cases.items():
            with self.subTest(case=name):
                api = FakeApi()
                env = executed_envelope(req, 500)
                mut(env)
                api.add(make_run(500), envelope=env)
                self.assert_runs(api)

    def test_n5_suite_identity_drift_runs_full(self):
        # the SOURCE ran a different canonical identity than the CURRENT
        # head derives: configuration, population, count, environment.
        drifts = {
            "plan-digest": make_request(plan_digest="9" * 64),
            "jobs": make_request(jobs=2),
            "serial-digest": make_request(serial="1" * 64),
            "count": make_request(count=3000),
        }
        for name, source_request in drifts.items():
            with self.subTest(case=name):
                api = FakeApi()
                api.add(make_run(500),
                        envelope=executed_envelope(source_request, 500))
                self.assert_runs(api)
        with self.subTest(case="environment-authority"):
            other_env = gate.FinalHeadRequest(
                SHA, make_suite(),
                {rel: "d" * 64 for rel in gate.ENV_AUTHORITY_FILES})
            api = FakeApi()
            api.add(make_run(500),
                    envelope=executed_envelope(other_env, 500))
            self.assert_runs(api)

    def test_n6_recursive_reuse_receipt_is_never_a_source(self):
        sim = HostedSim()
        sim.dispatch()                   # run 1000: executed
        sim.dispatch()                   # run 1001: reuse
        # remove the executed run: only the reuse receipt remains
        sim.api.runs = [r for r in sim.api.runs if r["id"] != 1000]
        decision = lookup(sim.api, make_request(), current_run_id=1002)
        self.assertEqual(decision["action"], "run")
        self.assertIn("verified_prior_execution",
                      json.dumps(decision["rejected"]))

    def test_n7_dispatch_ref_other_than_expected_disables_reuse(self):
        api = self.install()
        decision = lookup(api, self.request, dispatch_sha=OTHER_SHA)
        self.assertEqual(decision["action"], "run")
        self.assertEqual(api.calls, [], "no lookup when the workflow "
                                        "definition is not the validated head")

    def test_n8_bad_candidate_does_not_hide_a_later_good_one_but_never_leaks(self):
        api = FakeApi()
        api.add(make_run(400), envelope=executed_envelope(self.request, 400))
        bad = executed_envelope(self.request, 450)
        bad["suite_receipt"]["result"] = "FAIL"
        api.add(make_run(450), envelope=bad)
        decision = lookup(api, self.request)
        self.assertEqual(decision["action"], "reuse")
        self.assertEqual(decision["source"]["run_id"], 400)
        self.assertEqual([r["run_id"] for r in decision["rejected"]], [450])

    def test_n9_pending_duplicate_in_flight_is_not_a_source(self):
        api = FakeApi()
        api.add(make_run(500, status="in_progress", conclusion=None),
                envelope=executed_envelope(self.request, 500))
        self.assert_runs(api)


# ---------------------------------------------------------------------------
# A — API failure modes are bounded and fail closed
# ---------------------------------------------------------------------------

class ApiFailureModes(unittest.TestCase):
    request = make_request()

    def good_api(self):
        api = FakeApi()
        api.add(make_run(500), envelope=executed_envelope(self.request, 500))
        return api

    def test_a1_outage_rate_limit_permission_loss_run_full_suite(self):
        for label, err in (
                ("outage", reuse.ApiUnavailable("HTTP 503")),
                ("rate-limit", reuse.ApiUnavailable("HTTP 429")),
                ("permission", reuse.ApiUnavailable("HTTP 403")),
                ("timeout", TimeoutError("timed out")),
                ("os", OSError("connection reset")),
                ("surprise", RuntimeError("unexpected"))):
            for stage in ("list_runs", "list_artifacts", "download"):
                with self.subTest(label=label, stage=stage):
                    api = self.good_api()
                    api.fail[stage] = err
                    decision = lookup(api, self.request)
                    self.assertEqual(decision["action"], "run")
                    self.assertTrue(decision["reason"])

    def test_a2_malformed_payloads_run_full_suite(self):
        class Bad(FakeApi):
            def list_runs(self, page, per_page):
                return self.payload

        for payload in (None, [], "x", {}, {"workflow_runs": "no"},
                        {"workflow_runs": [None, 3, "x"]},
                        {"workflow_runs": [{"id": True}]}):
            with self.subTest(payload=payload):
                api = Bad()
                api.payload = payload
                self.assertEqual(lookup(api, self.request)["action"], "run")

        class BadArtifacts(FakeApi):
            def list_artifacts(self, run_id):
                return {"artifacts": [None, 1, {"id": "x"}]}

        api = BadArtifacts()
        api.add(make_run(500), envelope=executed_envelope(self.request, 500))
        self.assertEqual(lookup(api, self.request)["action"], "run")

    def test_a3_candidate_flood_is_bounded(self):
        api = FakeApi()
        for rid in range(1, 400):
            api.add(make_run(rid, conclusion="failure"), with_artifact=False)
        decision = lookup(api, self.request)
        self.assertEqual(decision["action"], "run")
        self.assertLessEqual(api.count("list_runs"), reuse.MAX_RUN_PAGES)
        # eligible-looking but unusable candidates are probed boundedly
        api = FakeApi()
        for rid in range(1, 400):
            api.add(make_run(rid), blob=b"junk")
        lookup(api, self.request)
        self.assertLessEqual(api.count("download"), reuse.MAX_CANDIDATES)
        self.assertLessEqual(api.count("list_runs"), reuse.MAX_RUN_PAGES)

    def test_a4_lookup_never_raises_to_the_caller(self):
        class Exploding(FakeApi):
            def list_runs(self, page, per_page):
                raise ZeroDivisionError()

        decision = lookup(Exploding(), self.request)
        self.assertEqual(decision["action"], "run")
        self.assertIn("lookup failed", decision["reason"])

    def test_a5_reuse_is_never_the_default_without_a_source(self):
        decision = lookup(FakeApi(), self.request)
        self.assertEqual(decision["action"], "run")
        self.assertIsNone(decision["source"])

    def test_a6_concurrent_duplicate_is_deterministic(self):
        # Two same-head dispatches: the concurrency group runs them one
        # after the other, so the later one starts after the earlier one
        # published its artifact (reuse); a cancelled pending run is never
        # a PASS and never a source.
        sim = HostedSim()
        sim.dispatch()
        sim.api.add(make_run(1500, conclusion="cancelled"),
                    envelope=executed_envelope(make_request(), 1500))
        _, d = sim.dispatch()
        self.assertEqual(d["action"], "reuse")
        self.assertEqual(sim.executions, 1)


# ---------------------------------------------------------------------------
# E — envelope schema and equivalence
# ---------------------------------------------------------------------------

class EnvelopeExecutionBlock(unittest.TestCase):
    request = make_request()

    def reused(self, **over):
        block = gate.execution_block_reused(
            SHA, source_run_id="500", source_run_attempt=1,
            source_artifact_id=77,
            source_artifact_digest="sha256:" + "d" * 64,
            source_envelope_sha256="c" * 64,
            source_workflow="Final CPU Validation")
        block.update(over)
        return block

    def build(self, execution, run_id="900"):
        return gate.build_final_validation_receipt(
            SHA, suite_receipt_for(self.request), github_run_id=run_id,
            github_run_attempt=1, finalizer_check=True,
            project_status_check=True, execution=execution)

    def test_e1_legacy_envelope_without_execution_still_valid(self):
        envelope = gate.build_final_validation_receipt(
            SHA, suite_receipt_for(self.request), github_run_id="run-226",
            github_run_attempt=1, finalizer_check=True,
            project_status_check=True)
        self.assertNotIn("execution", envelope)
        self.assertTrue(
            gate.validate_final_validation_receipt(envelope, SHA))

    def test_e2_valid_blocks(self):
        self.assertEqual(self.build(
            gate.execution_block_executed(SHA))["execution"]["mode"],
            "executed")
        self.assertEqual(self.build(self.reused())["execution"]["mode"],
                         "verified_prior_execution")

    def test_e3_malformed_blocks_rejected(self):
        bad = {
            "not-object": "reuse",
            "unknown-mode": self.reused(mode="cached"),
            "bad-contract": self.reused(reuse_contract="x"),
            "bad-dispatch-sha": self.reused(dispatch_sha="zz"),
            "dispatch-differs-from-head": self.reused(dispatch_sha=OTHER_SHA),
            "missing-source-run": {k: v for k, v in self.reused().items()
                                   if k != "source_run_id"},
            "non-digit-source-run": self.reused(source_run_id="run-1"),
            "self-source": self.reused(source_run_id="900"),
            "future-source": self.reused(source_run_id="901"),
            "bad-attempt": self.reused(source_run_attempt=0),
            "bool-attempt": self.reused(source_run_attempt=True),
            "bad-artifact-id": self.reused(source_artifact_id=0),
            "bad-digest": self.reused(source_artifact_digest="sha256:12"),
            "bad-envelope-digest": self.reused(source_envelope_sha256="g"),
            "extra-key": self.reused(extra=1),
            "executed-with-source": {
                **gate.execution_block_executed(SHA), "source_run_id": "5"},
        }
        for name, block in bad.items():
            with self.subTest(case=name), self.assertRaises(
                    gate.GateOrderingError):
                self.build(block)

    def test_e4_reuse_requires_a_valid_embedded_suite_receipt(self):
        envelope = self.build(self.reused())
        for mutate in (
                lambda e: e["suite_receipt"].update({"result": "FAIL"}),
                lambda e: e["suite_receipt"].update(
                    {"git_commit_sha": OTHER_SHA}),
                lambda e: e.pop("suite_receipt")):
            broken = copy.deepcopy(envelope)
            mutate(broken)
            with self.assertRaises(gate.GateOrderingError):
                gate.validate_final_validation_receipt(broken, SHA)


# ---------------------------------------------------------------------------
# C — compose-time re-verification (the decision file is not trusted)
# ---------------------------------------------------------------------------

class ComposeReverifies(unittest.TestCase):
    def reuse_decision(self):
        sim = HostedSim()
        sim.dispatch()
        _, d = sim.dispatch()
        return d

    def compose(self, decision, request=None, **kw):
        args = dict(request=request or make_request(), expected_sha=SHA,
                    github_run_id="2000", github_run_attempt=1,
                    workflow="Final CPU Validation", pr_number=None,
                    dispatch_sha=SHA, finalizer_check=True,
                    project_status_check=True)
        args.update(kw)
        return reuse.compose_reuse_envelope(decision, **args)

    def test_c1_roundtrip_ok(self):
        self.compose(self.reuse_decision())

    def test_c2_tampered_decisions_rejected(self):
        for name, mutate in {
                "run-action": lambda d: d.update({"action": "run"}),
                "no-source": lambda d: d.update({"source": None}),
                "no-envelope": lambda d: d.pop("source_envelope"),
                "source-envelope-fail": lambda d: d["source_envelope"][
                    "suite_receipt"].update({"result": "FAIL"}),
                "envelope-digest": lambda d: d["source"].update(
                    {"envelope_sha256": "0" * 64}),
                "self-source": lambda d: d["source"].update(
                    {"run_id": 2000}),
                }.items():
            with self.subTest(case=name), self.assertRaises(
                    (reuse.ReuseError, gate.GateOrderingError)):
                d = copy.deepcopy(self.reuse_decision())
                mutate(d)
                self.compose(d)

    def test_c3_request_drift_since_lookup_rejected(self):
        with self.assertRaises((reuse.ReuseError, gate.GateOrderingError)):
            self.compose(self.reuse_decision(),
                         request=make_request(plan_digest="2" * 64))

    def test_c4_dispatch_sha_must_equal_expected(self):
        with self.assertRaises((reuse.ReuseError, gate.GateOrderingError)):
            self.compose(self.reuse_decision(), dispatch_sha=OTHER_SHA)


class SuiteResultAgainstRequest(unittest.TestCase):
    def runner_result(self, request):
        suite = copy.deepcopy(request.suite)
        return {"ok": True, **suite}

    def test_s1_equivalent_to_the_original_inline_checks(self):
        request = make_request()
        suite = reuse.check_suite_result_against_request(
            self.runner_result(request), request, SHA)
        self.assertEqual(suite["serial_digest"], "f" * 64)

    def test_s2_mismatches_fail_closed(self):
        request = make_request()
        base = self.runner_result(request)
        cases = {
            "executed-digest": lambda r: r.update(
                {"executed_digest": "0" * 64}),
            "serial-digest": lambda r: r.update(
                {"serial_digest": "0" * 64, "executed_digest": "0" * 64}),
            "count": lambda r: r.update({"count": 1}),
            "config": lambda r: r["suite_config"].update({"jobs": 99}),
        }
        for name, mutate in cases.items():
            with self.subTest(case=name), self.assertRaises(
                    (reuse.ReuseError, gate.GateOrderingError)):
                broken = copy.deepcopy(base)
                mutate(broken)
                reuse.check_suite_result_against_request(
                    broken, request, SHA)
        with self.assertRaises(reuse.ReuseError):
            reuse.check_suite_result_against_request(
                base, make_request(OTHER_SHA), SHA)


# ---------------------------------------------------------------------------
# CLI glue
# ---------------------------------------------------------------------------

class CliLookup(unittest.TestCase):
    def run_cli(self, api_factory, env_over=None, request=None):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "decision.json"
            gh_out = Path(tmp) / "github_output"
            gh_out.write_text("")
            environ = {
                "EXPECTED_SHA": SHA, "PR_NUMBER": "",
                "GITHUB_SHA": SHA, "GITHUB_RUN_ID": "9000",
                "GITHUB_REPOSITORY": REPO, "GITHUB_TOKEN": "t",
                "GITHUB_API_URL": "https://api.github.com",
                "GITHUB_OUTPUT": str(gh_out)}
            environ.update(env_over or {})
            rc = reuse.main(
                ["lookup", "--out", str(out), "--repo-root", str(ROOT)],
                environ=environ, api_factory=api_factory,
                request_factory=lambda root: request or make_request())
            decision = json.loads(out.read_text())
            return rc, decision, gh_out.read_text()

    def test_l1_reuse_sets_output_true(self):
        sim = HostedSim()
        sim.dispatch()
        rc, decision, gh_out = self.run_cli(lambda **kw: sim.api)
        self.assertEqual(rc, 0)
        self.assertEqual(decision["action"], "reuse")
        self.assertIn("reuse=true", gh_out)

    def test_l2_outage_sets_output_false_and_still_succeeds(self):
        def factory(**kw):
            raise reuse.ApiUnavailable("HTTP 503")
        rc, decision, gh_out = self.run_cli(factory)
        self.assertEqual(rc, 0)
        self.assertEqual(decision["action"], "run")
        self.assertIn("reuse=false", gh_out)

    def test_l3_missing_token_runs_full(self):
        rc, decision, gh_out = self.run_cli(
            lambda **kw: FakeApi(), {"GITHUB_TOKEN": ""})
        self.assertEqual((rc, decision["action"]), (0, "run"))
        self.assertIn("reuse=false", gh_out)

    def test_l4_invalid_input_fails_the_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc = reuse.main(
                ["lookup", "--out", str(Path(tmp) / "d.json"),
                 "--repo-root", str(ROOT)],
                environ={"EXPECTED_SHA": "nope", "PR_NUMBER": ""},
                api_factory=lambda **kw: FakeApi(),
                request_factory=lambda root: make_request())
            self.assertNotEqual(rc, 0)

    def test_l5_request_derivation_failure_fails_the_job(self):
        def boom(root):
            raise gate.GateOrderingError("dirty worktree")
        with tempfile.TemporaryDirectory() as tmp:
            gh_out = Path(tmp) / "o"
            rc = reuse.main(
                ["lookup", "--out", str(Path(tmp) / "d.json"),
                 "--repo-root", str(ROOT)],
                environ={"EXPECTED_SHA": SHA, "PR_NUMBER": "",
                         "GITHUB_OUTPUT": str(gh_out)},
                api_factory=lambda **kw: FakeApi(), request_factory=boom)
            self.assertNotEqual(rc, 0)


# ---------------------------------------------------------------------------
# H — HTTP client
# ---------------------------------------------------------------------------

class _Handler(http.server.BaseHTTPRequestHandler):
    log: list = []
    redirect_to: str = ""

    def log_message(self, *a):  # silence
        pass

    def do_GET(self):  # noqa: N802
        type(self).log.append((self.server.server_address[1], self.path,
                               self.headers.get("Authorization")))
        if self.path.startswith("/repos/") and self.path.endswith("/zip"):
            self.send_response(302)
            self.send_header("Location", type(self).redirect_to)
            self.end_headers()
        elif self.path == "/blob":
            body = b"ZIPBYTES"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/rate":
            self.send_response(429)
            self.end_headers()
        elif self.path.startswith("/repos/") and "/runs" in self.path:
            body = json.dumps({"workflow_runs": []}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


class HttpClient(unittest.TestCase):
    def setUp(self):
        _Handler.log = []
        self.servers = []
        for _ in range(2):
            srv = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            self.servers.append(srv)
        self.addCleanup(lambda: [s.shutdown() or s.server_close()
                                 for s in self.servers])
        self.api_port = self.servers[0].server_address[1]
        self.blob_port = self.servers[1].server_address[1]
        _Handler.redirect_to = f"http://127.0.0.1:{self.blob_port}/blob"

    def client(self):
        return reuse.HttpActionsApi(
            f"http://127.0.0.1:{self.api_port}", REPO, "secret-token",
            _allow_insecure_loopback=True, timeout=5)

    def test_h1_token_sent_to_api_but_never_to_redirect_target(self):
        data = self.client().download_artifact(42, 1024)
        self.assertEqual(data, b"ZIPBYTES")
        by_port = {p: auth for p, _, auth in _Handler.log}
        self.assertEqual(by_port[self.api_port], "Bearer secret-token")
        self.assertIsNone(by_port[self.blob_port])

    def test_h2_http_errors_become_api_unavailable(self):
        api = self.client()
        with self.assertRaises(reuse.ApiUnavailable):
            api._request(f"http://127.0.0.1:{self.api_port}/rate")

    def test_h3_download_is_size_bounded(self):
        with self.assertRaises(reuse.ApiUnavailable):
            self.client().download_artifact(42, 4)

    def test_h4_plain_http_refused_without_test_seam(self):
        api = reuse.HttpActionsApi(
            f"http://127.0.0.1:{self.api_port}", REPO, "t")
        with self.assertRaises(reuse.ApiUnavailable):
            api.list_runs(1, 10)

    def test_h5_redirect_to_non_https_is_refused(self):
        api = reuse.HttpActionsApi(
            "https://api.github.com", REPO, "t")
        with self.assertRaises(reuse.ApiUnavailable):
            api._follow_download_redirect("http://example.invalid/x", 10)


if __name__ == "__main__":
    unittest.main()
