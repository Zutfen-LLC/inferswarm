#!/usr/bin/env python3
"""Authenticated ordinary-CI verification for the exact final PR head (Issue #323).

``issue213_gate_orchestration.validate_hosted_ci_status`` only checks the
SHAPE of a ``hosted-ci-exact-head-status/1`` object; nothing authenticates the
claimed run against GitHub.  A caller-written ``SUCCESS`` therefore satisfied
the ordinary-CI half of the final-head gate even when no ordinary CI run had
ever executed — which is exactly what ``[skip ci]`` produces (authentic
example: Final CPU Validation run #23, head ``0e78097b``: zero ``ci.yml``
runs).  A check implemented inside ``ci.yml`` cannot close that gap, because
the workflow may never start.  This module is the repository-owned,
independent enforcement point: it re-derives ordinary CI success from
read-only GitHub Actions API data and is consumed by
``handoff_gate_status(..., ci_verifier=...)``.

Trust model
-----------
* The expected head SHA is supplied independently by the caller (the
  independently derived final-head identity); nothing the API or a caller
  asserts can change it.  GitHub reports a ``pull_request`` run's ``head_sha``
  as the PR HEAD commit — not the synthetic merge commit the workflow checks
  out — so ``head_sha == expected`` is the exact-head binding.  A
  ``workflow_dispatch`` run's ``head_sha`` is the branch tip it was dispatched
  on.  Only those two events count; a ``push`` run is not PR CI.
* Authority comes only from the API: workflow identity (``ci.yml`` / ``CI`` /
  active, resolved from the workflow endpoint and cross-checked against every
  run), repository (run and head repository both this repository), a
  completed/``success`` run, the latest attempt, and the actual aggregate
  ``CI Gate`` job (completed/``success``) plus the always-required planner and
  repo-integrity jobs.  The newest eligible run for the head decides; every
  considered run is recorded.
* Everything uncertain is BLOCKED, never PASS: no run, pending/cancelled/
  failed, wrong workflow or repository, inconsistent or malformed metadata,
  stale/ambiguous attempts, pagination that cannot be proven complete, API
  errors, permission loss and rate limits.  The run is read twice around the
  job read so a rerun in flight cannot be accepted.
* The verdict (``hosted-ci-verification-verdict/1``) is deterministic,
  secret-free (identities and URLs only) and audit friendly.  Final CPU
  Validation success is never a substitute for it.

The API client is injected (read-only protocol: ``get_workflow``,
``list_workflow_runs``, ``get_run``, ``list_run_jobs``, ``get_pull``); unit
tests use an in-memory fake, the CLI uses ``HttpActionsApi``.  Nothing here
dispatches, reruns or writes anything on GitHub.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable, Mapping

VERDICT_SCHEMA = "hosted-ci-verification-verdict/1"
EVIDENCE_SOURCE = "github-actions-api (read-only)"

CI_WORKFLOW_FILE = "ci.yml"
CI_WORKFLOW_PATH = ".github/workflows/" + CI_WORKFLOW_FILE
CI_WORKFLOW_NAME = "CI"
CI_GATE_JOB_NAME = "CI Gate"
# Always-on jobs the aggregate gate itself requires; an aggregate that
# succeeded without them is not accepted.
REQUIRED_SUCCESS_JOBS = ("Plan CI (impact selection)",
                         "Group repo-integrity (always-on)")
# Only these events are ordinary CI of a PR head.
ALLOWED_EVENTS = ("pull_request", "workflow_dispatch")

PER_PAGE = 100
MAX_PAGES = 5

_SHA_RE = re.compile(r"[0-9a-f]{40}")
_REPO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")

BLOCKED = "BLOCKED"
PASS = "PASS"


class CiApiError(RuntimeError):
    """Base for read-only API failures."""


class ApiUnavailable(CiApiError):
    """The API could not answer (outage, 403, 429, transport ...)."""


class _Blocked(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _require(obj: object, what: str) -> dict:
    if not isinstance(obj, dict):
        raise _Blocked("malformed_response", f"{what} is not an object")
    return obj


def _field(obj: dict, key: str, kind: str, what: str,
           nullable: bool = False):
    if key not in obj:
        raise _Blocked("malformed_response", f"{what} lacks {key!r}")
    value = obj[key]
    if value is None and nullable:
        return None
    if kind == "str":
        ok = isinstance(value, str) and bool(value)
    elif kind == "int":
        ok = _is_int(value) and value >= 1
    else:  # pragma: no cover - programming error
        raise AssertionError(kind)
    if not ok:
        raise _Blocked("malformed_response",
                       f"{what}.{key} is malformed: {value!r}")
    return value


def _repo_of(obj: dict, key: str, what: str) -> str:
    inner = _require(obj.get(key), f"{what}.{key}")
    return _field(inner, "full_name", "str", f"{what}.{key}")


def blocked_verdict(expected_sha: object, code: str, detail: str, *,
                    repository: str | None = None, **evidence) -> dict:
    """A BLOCKED verdict (also used by the handoff for claim-level blocks)."""
    verdict = {
        "schema": VERDICT_SCHEMA,
        "verdict": BLOCKED,
        "reason_code": code,
        "detail": detail,
        "expected_sha": (expected_sha if isinstance(expected_sha, str)
                         else repr(expected_sha)),
        "repository": repository,
        "workflow": evidence.get("workflow"),
        "run": evidence.get("run"),
        "gate_job": evidence.get("gate_job"),
        "pull_request": evidence.get("pull_request"),
        "considered_runs": evidence.get("considered_runs", []),
        "evidence_source": EVIDENCE_SOURCE,
    }
    return verdict


class HostedCiVerifier:
    """Re-derive ordinary CI success for one exact head from the Actions API.

    ``pr_number`` (optional) additionally re-reads the PR and requires its
    current head to still be ``expected_sha`` (a head moved after CI is
    BLOCKED) and the run's branch to be the PR's head branch.
    """

    def __init__(self, api, repository: str, *, pr_number: int | None = None):
        if not isinstance(repository, str) or not _REPO_RE.fullmatch(
                repository):
            raise ValueError(f"repository is malformed: {repository!r}")
        if pr_number is not None and (not _is_int(pr_number)
                                      or pr_number < 1):
            raise ValueError(f"pr_number is malformed: {pr_number!r}")
        self.api = api
        self.repository = repository
        self.pr_number = pr_number

    # -- public --------------------------------------------------------
    def verify(self, expected_sha: str, *,
               pinned_run_id: int | None = None) -> dict:
        evidence: dict = {"considered_runs": []}
        try:
            return self._verify(expected_sha, pinned_run_id, evidence)
        except _Blocked as blocked:
            return blocked_verdict(expected_sha, blocked.code,
                                   blocked.detail,
                                   repository=self.repository, **evidence)
        except CiApiError as error:
            return blocked_verdict(expected_sha, "api_unavailable",
                                   str(error), repository=self.repository,
                                   **evidence)
        except (KeyError, TypeError, ValueError, AttributeError,
                IndexError) as error:
            return blocked_verdict(
                expected_sha, "malformed_response",
                f"unexpected response shape: {error!r}",
                repository=self.repository, **evidence)

    # -- steps ---------------------------------------------------------
    def _verify(self, expected_sha: object, pinned_run_id: object,
                evidence: dict) -> dict:
        if not isinstance(expected_sha, str) \
                or not _SHA_RE.fullmatch(expected_sha):
            raise _Blocked("malformed_input",
                           "expected head is not an exact 40-hex SHA")
        if pinned_run_id is not None and (not _is_int(pinned_run_id)
                                          or pinned_run_id < 1):
            raise _Blocked("malformed_input",
                           f"pinned run id is malformed: {pinned_run_id!r}")

        workflow = self._workflow(evidence)
        pull = self._pull(expected_sha, evidence)
        candidates = self._candidate_runs(workflow, expected_sha, evidence)
        run = self._select(candidates, pinned_run_id)
        evidence["run"] = self._run_summary(run)

        if run["status"] != "completed":
            raise _Blocked("ci_pending",
                           f"run {run['id']} status is {run['status']!r}")
        conclusion = run["conclusion"]
        if conclusion != "success":
            code = ("ci_cancelled" if conclusion == "cancelled" else
                    "ci_failed" if conclusion in ("failure", "timed_out",
                                                  "startup_failure")
                    else "ci_not_success")
            raise _Blocked(code,
                           f"run {run['id']} conclusion is {conclusion!r}")
        if pull is not None and run["head_branch"] != pull["head_ref"]:
            raise _Blocked(
                "branch_mismatch",
                f"run branch {run['head_branch']!r} is not the PR head "
                f"branch {pull['head_ref']!r}")

        run_a = self._read_run(run["id"], workflow, expected_sha)
        if run_a != run:
            raise _Blocked("inconsistent_metadata",
                           "run read disagrees with its listing entry")
        gate = self._jobs(run, expected_sha, evidence)
        run_b = self._read_run(run["id"], workflow, expected_sha)
        if run_b != run_a:
            raise _Blocked(
                "ambiguous_evidence",
                "run changed while its jobs were read (rerun in flight)")

        verdict = blocked_verdict(expected_sha, "", "",
                                  repository=self.repository, **evidence)
        verdict["verdict"] = PASS
        verdict["reason_code"] = None
        verdict["detail"] = (f"ordinary CI run {run['id']} attempt "
                             f"{run['run_attempt']} succeeded on the exact "
                             "head including the CI Gate job")
        verdict["gate_job"] = gate
        return verdict

    def _workflow(self, evidence: dict) -> dict:
        raw = _require(self.api.get_workflow(CI_WORKFLOW_FILE),
                       "workflow response")
        wid = _field(raw, "id", "int", "workflow")
        name = _field(raw, "name", "str", "workflow")
        path = _field(raw, "path", "str", "workflow")
        state = _field(raw, "state", "str", "workflow")
        evidence["workflow"] = {"id": wid, "name": name, "path": path}
        if path != CI_WORKFLOW_PATH or name != CI_WORKFLOW_NAME:
            raise _Blocked(
                "workflow_identity_mismatch",
                f"workflow is {name!r} at {path!r}, not the canonical "
                f"{CI_WORKFLOW_NAME!r} at {CI_WORKFLOW_PATH!r}")
        if state != "active":
            raise _Blocked("workflow_identity_mismatch",
                           f"canonical CI workflow state is {state!r}")
        return {"id": wid, "name": name, "path": path}

    def _pull(self, expected_sha: str, evidence: dict) -> dict | None:
        if self.pr_number is None:
            return None
        raw = _require(self.api.get_pull(self.pr_number), "pull response")
        head = _require(raw.get("head"), "pull.head")
        summary = {
            "number": _field(raw, "number", "int", "pull"),
            "state": _field(raw, "state", "str", "pull"),
            "head_sha": _field(head, "sha", "str", "pull.head"),
            "head_ref": _field(head, "ref", "str", "pull.head"),
        }
        head_repo = _repo_of(head, "repo", "pull.head")
        evidence["pull_request"] = {k: summary[k] for k in
                                    ("number", "state", "head_sha",
                                     "head_ref")}
        if summary["number"] != self.pr_number:
            raise _Blocked("inconsistent_metadata",
                           "pull response is for another PR")
        if head_repo != self.repository:
            raise _Blocked("foreign_repository",
                           f"PR head repository is {head_repo!r}")
        if summary["head_sha"] != expected_sha:
            raise _Blocked(
                "pr_head_moved",
                f"PR head is {summary['head_sha']}, not the reviewed "
                f"{expected_sha}: earlier CI results are stale")
        return summary

    def _collect(self, fetch: Callable[[int, int], object], key: str,
                 what: str) -> list:
        items: list = []
        total = None
        for page in range(1, MAX_PAGES + 1):
            response = _require(fetch(page, PER_PAGE), f"{what} response")
            count = response.get("total_count")
            if not _is_int(count) or count < 0:
                raise _Blocked("malformed_response",
                               f"{what} total_count is malformed: {count!r}")
            if total is not None and count != total:
                raise _Blocked("ambiguous_evidence",
                               f"{what} total changed while paging")
            total = count
            rows = response.get(key)
            if not isinstance(rows, list):
                raise _Blocked("malformed_response",
                               f"{what} lacks a {key!r} list")
            items.extend(rows)
            if len(items) >= total:
                break
            if not rows:
                raise _Blocked("pagination_uncertain",
                               f"{what}: {len(items)} of {total} returned")
        else:
            raise _Blocked("pagination_uncertain",
                           f"{what} exceeds {MAX_PAGES} pages")
        if len(items) != total:
            raise _Blocked("pagination_uncertain",
                           f"{what}: {len(items)} returned for total {total}")
        return items

    def _run(self, raw: object, workflow: dict, what: str) -> dict:
        raw = _require(raw, what)
        run = {
            "id": _field(raw, "id", "int", what),
            "name": _field(raw, "name", "str", what),
            "path": _field(raw, "path", "str", what),
            "workflow_id": _field(raw, "workflow_id", "int", what),
            "event": _field(raw, "event", "str", what),
            "status": _field(raw, "status", "str", what),
            "conclusion": _field(raw, "conclusion", "str", what,
                                 nullable=True),
            "head_sha": _field(raw, "head_sha", "str", what),
            "head_branch": _field(raw, "head_branch", "str", what),
            "run_attempt": _field(raw, "run_attempt", "int", what),
            "html_url": _field(raw, "html_url", "str", what),
            "created_at": _field(raw, "created_at", "str", what),
            "updated_at": _field(raw, "updated_at", "str", what),
            "repository": _repo_of(raw, "repository", what),
            "head_repository": _repo_of(raw, "head_repository", what),
        }
        if (run["workflow_id"] != workflow["id"]
                or run["path"] != CI_WORKFLOW_PATH
                or run["name"] != CI_WORKFLOW_NAME):
            raise _Blocked(
                "workflow_identity_mismatch",
                f"run {run['id']} is {run['name']!r} at {run['path']!r} "
                f"(workflow {run['workflow_id']}), not the canonical CI "
                "workflow")
        if run["repository"] != self.repository \
                or run["head_repository"] != self.repository:
            raise _Blocked(
                "foreign_repository",
                f"run {run['id']} belongs to {run['repository']!r} / head "
                f"{run['head_repository']!r}, not {self.repository!r}")
        return run

    def _candidate_runs(self, workflow: dict, expected_sha: str,
                        evidence: dict) -> list[dict]:
        rows = self._collect(
            lambda page, per: self.api.list_workflow_runs(
                workflow["id"], expected_sha, page, per),
            "workflow_runs", "workflow run listing")
        runs = []
        seen = set()
        for raw in rows:
            run = self._run(raw, workflow, "listed run")
            if run["head_sha"] != expected_sha:
                raise _Blocked(
                    "inconsistent_metadata",
                    f"listing for {expected_sha} returned run {run['id']} "
                    f"at {run['head_sha']}")
            if run["id"] in seen:
                raise _Blocked("ambiguous_evidence",
                               f"run {run['id']} listed twice")
            seen.add(run["id"])
            runs.append(run)
        runs.sort(key=lambda r: r["id"])
        evidence["considered_runs"] = [
            {"id": r["id"], "attempt": r["run_attempt"], "event": r["event"],
             "status": r["status"], "conclusion": r["conclusion"],
             "ignored": r["event"] not in ALLOWED_EVENTS}
            for r in runs]
        return runs

    def _select(self, runs: list[dict], pinned: int | None) -> dict:
        eligible = [r for r in runs if r["event"] in ALLOWED_EVENTS]
        if not eligible:
            raise _Blocked(
                "no_ci_run",
                "no ordinary CI (pull_request / workflow_dispatch) run "
                "exists for the exact head ([skip ci] or CI never ran)")
        newest = eligible[-1]
        if pinned is not None and pinned != newest["id"]:
            if any(r["id"] == pinned for r in eligible):
                raise _Blocked(
                    "stale_run",
                    f"pinned run {pinned} is superseded by run "
                    f"{newest['id']} for the same head")
            raise _Blocked("pinned_run_not_found",
                           f"pinned run {pinned} is not an ordinary CI run "
                           "of the exact head")
        return newest

    @staticmethod
    def _run_summary(run: dict) -> dict:
        return {"id": run["id"], "attempt": run["run_attempt"],
                "event": run["event"], "head_sha": run["head_sha"],
                "head_branch": run["head_branch"], "status": run["status"],
                "conclusion": run["conclusion"],
                "html_url": run["html_url"],
                "created_at": run["created_at"],
                "updated_at": run["updated_at"]}

    def _read_run(self, run_id: int, workflow: dict,
                  expected_sha: str) -> dict:
        run = self._run(self.api.get_run(run_id), workflow, "run read")
        if run["id"] != run_id or run["head_sha"] != expected_sha:
            raise _Blocked("inconsistent_metadata",
                           f"run read for {run_id} returned run {run['id']} "
                           f"at {run['head_sha']}")
        return run

    def _jobs(self, run: dict, expected_sha: str, evidence: dict) -> dict:
        rows = self._collect(
            lambda page, per: self.api.list_run_jobs(run["id"], page, per),
            "jobs", "job listing")
        jobs = []
        for raw in rows:
            raw = _require(raw, "job")
            job = {
                "id": _field(raw, "id", "int", "job"),
                "name": _field(raw, "name", "str", "job"),
                "status": _field(raw, "status", "str", "job"),
                "conclusion": _field(raw, "conclusion", "str", "job",
                                     nullable=True),
                "head_sha": _field(raw, "head_sha", "str", "job"),
                "run_id": _field(raw, "run_id", "int", "job"),
                "run_attempt": _field(raw, "run_attempt", "int", "job"),
            }
            if job["run_id"] != run["id"] or job["head_sha"] != expected_sha:
                raise _Blocked(
                    "inconsistent_metadata",
                    f"job {job['id']} ({job['name']!r}) belongs to run "
                    f"{job['run_id']} at {job['head_sha']}, not run "
                    f"{run['id']} at {expected_sha}")
            if job["run_attempt"] != run["run_attempt"]:
                raise _Blocked(
                    "stale_attempt",
                    f"job {job['id']} ({job['name']!r}) is from attempt "
                    f"{job['run_attempt']}, run is at attempt "
                    f"{run['run_attempt']}")
            jobs.append(job)

        gates = [j for j in jobs if j["name"] == CI_GATE_JOB_NAME]
        if not gates:
            raise _Blocked("gate_job_missing",
                           f"run {run['id']} has no {CI_GATE_JOB_NAME!r} job")
        if len(gates) > 1:
            raise _Blocked("ambiguous_evidence",
                           f"run {run['id']} has {len(gates)} "
                           f"{CI_GATE_JOB_NAME!r} jobs")
        gate = gates[0]
        evidence["gate_job"] = {
            "id": gate["id"], "name": gate["name"], "status": gate["status"],
            "conclusion": gate["conclusion"],
            "run_attempt": gate["run_attempt"]}
        if gate["status"] != "completed" or gate["conclusion"] != "success":
            raise _Blocked(
                "gate_job_not_success",
                f"{CI_GATE_JOB_NAME!r} is {gate['status']!r}/"
                f"{gate['conclusion']!r}")
        for name in REQUIRED_SUCCESS_JOBS:
            named = [j for j in jobs if j["name"] == name]
            if len(named) > 1:
                raise _Blocked("ambiguous_evidence",
                               f"run has {len(named)} {name!r} jobs")
            if (len(named) != 1 or named[0]["status"] != "completed"
                    or named[0]["conclusion"] != "success"):
                raise _Blocked(
                    "required_job_not_success",
                    f"required job {name!r} is missing or did not succeed")
        for job in jobs:
            if job["status"] != "completed" \
                    or job["conclusion"] not in ("success", "skipped"):
                raise _Blocked(
                    "job_not_success",
                    f"job {job['name']!r} is {job['status']!r}/"
                    f"{job['conclusion']!r}")
        return evidence["gate_job"]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def resolve_token(environ: Mapping[str, str], *,
                  allow_gh_fallback: bool) -> str | None:
    """``GITHUB_TOKEN`` / ``GH_TOKEN``; else ``gh auth token`` (operator use)."""
    for key in ("GITHUB_TOKEN", "GH_TOKEN"):
        if environ.get(key):
            return environ[key]
    if allow_gh_fallback:
        try:
            out = subprocess.run(["gh", "auth", "token"], capture_output=True,
                                 text=True, timeout=20, check=True)
            return out.stdout.strip() or None
        except (OSError, subprocess.SubprocessError):
            return None
    return None


def default_api_factory(api_url: str, repository: str, token: str):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from final_validation_reuse import HttpActionsApi  # lazy: avoids a cycle
    return HttpActionsApi(api_url, repository, token)


def main(argv: list[str] | None = None, *,
         environ: Mapping[str, str] | None = None,
         api_factory: Callable[..., object] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    ver = sub.add_parser("verify", help="verify ordinary CI on an exact head")
    ver.add_argument("--repo", required=True, help="OWNER/REPO")
    ver.add_argument("--sha", required=True, help="exact 40-hex head SHA")
    ver.add_argument("--pr", type=int, default=None,
                     help="PR number: also require its CURRENT head == --sha")
    ver.add_argument("--run-id", type=int, default=None,
                     help="require this run to be the deciding CI run")
    ver.add_argument("--out", required=True, help="verdict JSON path")
    args = parser.parse_args(argv)
    env = os.environ if environ is None else environ
    if not _SHA_RE.fullmatch(args.sha) or not _REPO_RE.fullmatch(args.repo):
        print("hosted-ci: usage error: --sha must be an exact 40-hex SHA "
              "and --repo OWNER/REPO")
        return 2
    token = resolve_token(env, allow_gh_fallback=api_factory is None
                          and environ is None)
    if not token:
        print("hosted-ci: usage error: set GITHUB_TOKEN (read-only) or log "
              "in with gh")
        return 2
    api_url = env.get("GITHUB_API_URL", "https://api.github.com")
    api = (api_factory or default_api_factory)(api_url, args.repo, token)
    verdict = HostedCiVerifier(api, args.repo, pr_number=args.pr).verify(
        args.sha, pinned_run_id=args.run_id)
    Path(args.out).write_text(
        json.dumps(verdict, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    print(" ".join(part for part in ("hosted-ci:", verdict["verdict"],
                                      verdict["reason_code"],
                                      verdict["detail"]) if part))
    return 0 if verdict["verdict"] == PASS else 3


if __name__ == "__main__":
    raise SystemExit(main())
