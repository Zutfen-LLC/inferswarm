"""Offline GitHub Actions API fake for hosted-CI verification tests (Issue #323).

Pure test support: no network, no secrets.  The "genuine" world is built from
AUTHENTIC read-only metadata of ordinary PR CI run 38693435694 (head
``c23f6c2d``, workflow ``CI`` / ``.github/workflows/ci.yml`` / id 342883623,
20 jobs ending in ``CI Gate``), trimmed to the fields the verifier reads.  The
``[skip ci]`` world is the authentic shape of Final CPU Validation run
38087287752 (run #23): head ``0e78097b`` whose commit message ends in
``[skip ci]`` has ZERO ``ci.yml`` runs and its only check run is the Final CPU
Validation job itself.

Tests mutate the world (``api.runs[0]["conclusion"] = ...``) to build the
adversarial controls; the fake records every call so a test can prove the
verifier is read-only and deterministic.
"""
from __future__ import annotations

import copy
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import hosted_ci_verification as hci  # noqa: E402

REPO = "Zutfen-LLC/inferswarm"
CI_WORKFLOW_ID = 342883623
FCV_WORKFLOW_ID = 362130467

# --- authentic genuine PR CI run (read-only API metadata) ------------------
REAL_RUN_ID = 38693435694
REAL_SHA = "c23f6c2df6fd8df9e88144354f1eea7ea3112902"
REAL_BRANCH = "integrate/moe-native-cache"
REAL_JOBS = [
    (116284407433, "Plan CI (impact selection)"),
    (116284512234, "Group issue-117-133"),
    (116284512319, "Group repo-integrity (always-on)"),
    (116284512327, "Group issue-83-95"),
    (116284512330, "Group issue-213-gate-ordering"),
    (116284512338, "Group moe-overlap-prototype"),
    (116284512410, "Group issue-109-110"),
    (116284512414, "Group r8-qwen-lineage"),
    (116284512428, "Group issue-209-r7b"),
    (116284512441, "Group issue-187-r7a"),
    (116284512445, "Group issue-74-79"),
    (116284512475, "Group r8i-qwen-qualification shard 2"),
    (116284512482, "Group issue-115-cleanup"),
    (116284512486, "Group issue-222-r7c"),
    (116284512501, "Group r8i-qwen-qualification shard 3"),
    (116284512503, "Group r8i-qwen-qualification shard 1"),
    (116284512513, "Group r8i-qwen-qualification shard 5"),
    (116284512614, "Group r8i-qwen-qualification shard 4"),
    (116284512814, "Group issue-99-103"),
    (116287395457, "CI Gate"),
]
GATE_JOB_ID = 116287395457

# --- authentic [skip ci] head (run #23) ------------------------------------
SKIP_CI_SHA = "0e78097bb8aa8c9bdf32e32cc8d05ca3cf3e632b"
SKIP_CI_BRANCH = "feat/issue299-profiled-q8"
SKIP_CI_FCV_RUN_ID = 38087287752

OTHER_SHA = "b" * 40


def ci_workflow() -> dict:
    return {"id": CI_WORKFLOW_ID, "name": "CI",
            "path": ".github/workflows/ci.yml", "state": "active"}


def ci_run(run_id: int = REAL_RUN_ID, sha: str = REAL_SHA,
           branch: str = REAL_BRANCH, event: str = "pull_request",
           attempt: int = 1, status: str = "completed",
           conclusion: str | None = "success", repo: str = REPO) -> dict:
    return {
        "id": run_id, "name": "CI", "path": ".github/workflows/ci.yml",
        "workflow_id": CI_WORKFLOW_ID, "event": event, "status": status,
        "conclusion": conclusion, "head_sha": sha, "head_branch": branch,
        "run_attempt": attempt, "run_number": 875,
        "created_at": "2026-10-15T06:36:38Z",
        "updated_at": "2026-10-15T06:45:56Z",
        "html_url": f"https://github.com/{repo}/actions/runs/{run_id}",
        "repository": {"full_name": repo},
        "head_repository": {"full_name": repo},
        "pull_requests": [],
    }


def ci_jobs(run_id: int = REAL_RUN_ID, sha: str = REAL_SHA,
            attempt: int = 1, repo: str = REPO) -> list[dict]:
    return [{"id": jid, "name": name, "status": "completed",
             "conclusion": "success", "head_sha": sha, "run_id": run_id,
             "run_attempt": attempt, "workflow_name": "CI",
             "html_url": f"https://github.com/{repo}/actions/runs/{run_id}"
                         f"/job/{jid}"}
            for jid, name in REAL_JOBS]


def pull(number: int = 322, sha: str = REAL_SHA,
         ref: str = REAL_BRANCH, repo: str = REPO,
         state: str = "open", base_repo: str = REPO,
         base_ref: str = "main") -> dict:
    return {"number": number, "state": state,
            "head": {"sha": sha, "ref": ref, "repo": {"full_name": repo}},
            "base": {"ref": base_ref, "repo": {"full_name": base_repo}}}


class FakeCiApi:
    """In-memory read-only fake of the GitHub Actions API surface."""

    def __init__(self, repository: str = REPO) -> None:
        # The repository this client is bound to (``HttpActionsApi`` exposes
        # the same attribute); the genuine worlds are all in ``REPO``.
        self.repository = repository
        self.workflow: object = ci_workflow()
        self.runs: list = []
        self.jobs: dict = {}
        self.pulls: dict = {}
        self.errors: dict = {}
        self.calls: list = []
        # Misbehaving-server switches.
        self.ignore_head_filter = False
        self.total_count_override: int | None = None
        self.jobs_total_override: int | None = None
        self.get_run_mutator = None
        self.get_run_calls = 0
        # ``get_pull_mutator(call_number, pull) -> pull`` lets a test change
        # the PR between the first and the final read (call numbers from 1).
        self.get_pull_mutator = None
        self.get_pull_calls = 0

    # -- worlds ----------------------------------------------------------
    @classmethod
    def genuine(cls, repo: str = REPO) -> "FakeCiApi":
        """The authentic PR-CI world; ``repo`` builds the same world, every
        record internally consistent, inside ANOTHER repository (the
        identical-SHA foreign-repository attack)."""
        api = cls(repo)
        api.runs = [ci_run(repo=repo)]
        api.jobs = {REAL_RUN_ID: ci_jobs(repo=repo)}
        api.pulls = {322: pull(repo=repo, base_repo=repo)}
        return api

    @classmethod
    def skip_ci(cls) -> "FakeCiApi":
        """Authentic run-#23 shape: no ordinary CI run exists for the head."""
        api = cls()
        api.runs = []
        api.pulls = {304: pull(304, SKIP_CI_SHA, SKIP_CI_BRANCH)}
        return api

    def add_run(self, run: dict, jobs: list | None = None) -> None:
        self.runs.append(run)
        self.jobs[run["id"]] = (
            jobs if jobs is not None
            else ci_jobs(run["id"], run["head_sha"], run["run_attempt"],
                         run["repository"]["full_name"]))

    # -- API surface -----------------------------------------------------
    def _enter(self, name: str, *args) -> None:
        self.calls.append((name, args))
        if name in self.errors:
            raise self.errors[name]

    def get_workflow(self, workflow_file):
        self._enter("get_workflow", workflow_file)
        return copy.deepcopy(self.workflow)

    def list_workflow_runs(self, workflow_id, head_sha, page, per_page):
        self._enter("list_workflow_runs", workflow_id, head_sha, page,
                    per_page)
        runs = [r for r in self.runs
                if self.ignore_head_filter or r.get("head_sha") == head_sha]
        total = (self.total_count_override
                 if self.total_count_override is not None else len(runs))
        start = (page - 1) * per_page
        return {"total_count": total,
                "workflow_runs": copy.deepcopy(runs[start:start + per_page])}

    def get_run(self, run_id):
        self._enter("get_run", run_id)
        self.get_run_calls += 1
        for run in self.runs:
            if run.get("id") == run_id:
                result = copy.deepcopy(run)
                if self.get_run_mutator is not None:
                    result = self.get_run_mutator(self.get_run_calls, result)
                return result
        raise hci.ApiUnavailable("HTTP 404")

    def list_run_jobs(self, run_id, page, per_page):
        self._enter("list_run_jobs", run_id, page, per_page)
        jobs = self.jobs.get(run_id, [])
        total = (self.jobs_total_override
                 if self.jobs_total_override is not None else len(jobs))
        start = (page - 1) * per_page
        return {"total_count": total,
                "jobs": copy.deepcopy(jobs[start:start + per_page])}

    def get_pull(self, number):
        self._enter("get_pull", number)
        self.get_pull_calls += 1
        if number not in self.pulls:
            raise hci.ApiUnavailable("HTTP 404")
        result = copy.deepcopy(self.pulls[number])
        if self.get_pull_mutator is not None:
            result = self.get_pull_mutator(self.get_pull_calls, result)
        return result

    # -- helpers ---------------------------------------------------------
    def job(self, name: str, run_id: int = REAL_RUN_ID) -> dict:
        return next(j for j in self.jobs[run_id] if j["name"] == name)

    def called(self) -> list:
        return [name for name, _ in self.calls]


def authenticated_ci(sha: str, *, branch: str = "feature/x",
                     run_id: int = 9001, pr_number: int | None = 7):
    """A ``HostedCiVerifier`` over a genuine-shaped CI world for ``sha``.

    Positive-control helper for tests of the handoff boundary: the verifier
    authenticates against an in-memory fake exactly like production code
    authenticates against GitHub.  PR ``7`` is the head's PR and the
    verifier is bound to it by default: an authoritative handoff requires
    current-PR binding (a verifier without ``pr_number`` is a diagnostic).
    """
    api = FakeCiApi()
    api.add_run(ci_run(run_id, sha, branch))
    api.pulls = {7: pull(7, sha, branch)}
    return hci.HostedCiVerifier(api, REPO, pr_number=pr_number)


class HttpEmulator:
    """Serve a ``FakeCiApi`` world over the REAL ``HttpActionsApi`` wire path.

    Patches ``urllib.request.OpenerDirector.open`` so the production client
    code (URL construction, headers, JSON parsing) runs with no socket.  Like
    a spoofed HTTPS endpoint it answers ANY origin with the same internally
    consistent successful records, and it records every request, so a test
    can prove which origin a bearer token was (not) sent to.

    ``requests`` holds ``(url, authorization header or None)`` per request.
    """

    _ROUTES = (
        (re.compile(r"^/repos/([^/]+/[^/]+)/actions/workflows/([^/]+)$"),
         "workflow"),
        (re.compile(r"^/repos/([^/]+/[^/]+)/actions/workflows/(\d+)/runs$"),
         "workflow_runs"),
        (re.compile(r"^/repos/([^/]+/[^/]+)/actions/runs/(\d+)$"), "run"),
        (re.compile(r"^/repos/([^/]+/[^/]+)/actions/runs/(\d+)/jobs$"),
         "jobs"),
        (re.compile(r"^/repos/([^/]+/[^/]+)/pulls/(\d+)$"), "pull"),
    )

    def __init__(self, world: FakeCiApi) -> None:
        self.world = world
        self.requests: list = []
        self.redirect_to: str | None = None
        self._patch = None

    def __enter__(self) -> "HttpEmulator":
        self._patch = mock.patch.object(urllib.request.OpenerDirector, "open",
                                        self._open)
        self._patch.start()
        return self

    def __exit__(self, *exc) -> bool:
        self._patch.stop()
        return False

    def hosts(self) -> list:
        return sorted({urllib.parse.urlsplit(url).netloc
                       for url, _ in self.requests})

    # -- transport -------------------------------------------------------
    def _open(self, request, data=None, timeout=None):
        url = request.full_url
        self.requests.append((url, request.get_header("Authorization")))
        if self.redirect_to:
            raise urllib.error.HTTPError(
                url, 302, "Found", {"Location": self.redirect_to}, None)
        parts = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qs(parts.query)
        for pattern, kind in self._ROUTES:
            match = pattern.match(parts.path)
            if match:
                break
        else:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        try:
            body = self._serve(kind, match, query)
        except hci.ApiUnavailable:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        return _Response(json.dumps(body).encode("utf-8"))

    def _serve(self, kind, match, query):
        page = int(query.get("page", ["1"])[0])
        per_page = int(query.get("per_page", ["100"])[0])
        if kind == "workflow":
            return self.world.get_workflow(match.group(2))
        if kind == "workflow_runs":
            return self.world.list_workflow_runs(
                int(match.group(2)), query["head_sha"][0], page, per_page)
        if kind == "run":
            return self.world.get_run(int(match.group(2)))
        if kind == "jobs":
            return self.world.list_run_jobs(int(match.group(2)), page,
                                            per_page)
        return self.world.get_pull(int(match.group(2)))


class _Response:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def read(self, size: int = -1) -> bytes:
        return self._body if size < 0 else self._body[:size]
