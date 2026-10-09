#!/usr/bin/env python3
"""Verified exact-head receipt reuse for hosted Final CPU Validation (Issue #291).

The hosted workflow (``.github/workflows/final-cpu-validation.yml``) runs
the canonical 3,000+ test suite on a fresh runner per dispatch.  Its
concurrency group serializes same-SHA dispatches but does not stop a later
dispatch from re-running the whole suite.  This module is the workflow's
repository-owned helper that

* strictly validates the untrusted dispatch inputs (they reach this code
  through environment variables, never through spliced source text);
* performs a READ-ONLY, FAIL-CLOSED lookup for a previously SUCCESSFUL hosted
  Final CPU Validation of the same immutable head whose receipt artifact is
  independently verified (:func:`lookup_verified_prior_execution`);
* composes the new run's gate result, either from a verified source
  (``verified_prior_execution``) or from a fresh canonical execution.

Trust model (reuse is a CACHE of one specific kind of proof, never a bypass):

* only a ``workflow_dispatch`` run of this repository's own
  ``final-cpu-validation.yml`` whose workflow DEFINITION is the validated
  head itself (run ``head_sha == expected_sha`` and the reusing run's
  ``GITHUB_SHA == expected_sha``) is a candidate — a branch cannot supply a
  forged-workflow receipt for a different tree;
* the run must be completed/success, the artifact unexpired, bound by the
  Actions API to that run and head, its bytes must match the API-reported
  sha256 digest, and the archive must contain exactly the one receipt member;
* the receipt must validate through the existing #226 validators, belong to
  that run id/attempt, record a PHYSICAL execution (``mode == executed``;
  reuse receipts are never sources, so chains cannot form), and its embedded
  #213 suite receipt must match the current head's independently derived
  suite configuration, population digests, count and environment authority;
* anything else — including every API error — means: run the full suite;
* the lookup's decision file is only a HINT naming a source.  Composition
  (the step that mints the gate result after the suite was skipped)
  re-authenticates that source itself against the Actions API — successful
  run identity, attempt, artifact metadata and digest, execution mode and
  the exact-head suite receipt — and embeds only API-authenticated bytes.
  If that is impossible (outage, expiry, changed attempt, any mismatch) the
  gate FAILS: it never mints PASS and never claims an execution that did
  not happen.

Ordinary CI is never a source.  ``pr_number`` is audit-only.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue213_gate_orchestration as gate  # noqa: E402

WORKFLOW_FILE = "final-cpu-validation.yml"
WORKFLOW_PATH = ".github/workflows/" + WORKFLOW_FILE
WORKFLOW_NAME = "Final CPU Validation"
RECEIPT_ARTIFACT_NAME = "final-cpu-validation-receipt"
RECEIPT_MEMBER = "final-validation-receipt.json"
DECISION_SCHEMA = "final-validation-reuse-decision/1"

# Bounds: the lookup is advisory dedup and must stay cheap and finite.
RUNS_PER_PAGE = 50
MAX_RUN_PAGES = 3
MAX_CANDIDATES = 8
MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
MAX_MEMBER_BYTES = 4 * 1024 * 1024
MAX_JSON_BYTES = 4 * 1024 * 1024
HTTP_TIMEOUT_SECONDS = 20

_SHA_RE = re.compile(r"[0-9a-f]{40}")
_PR_RE = re.compile(r"[1-9][0-9]{0,8}")
_RUN_ID_RE = re.compile(r"[1-9][0-9]{0,18}")
_REPO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


class ReuseError(RuntimeError):
    """A fail-closed reuse verification/composition failure."""


class InputError(ReuseError):
    """An untrusted workflow input is malformed (the job must fail)."""


class ApiUnavailable(ReuseError):
    """The read-only Actions API could not answer (outage, limit, 403 ...)."""


# ---------------------------------------------------------------------------
# Input validation (untrusted dispatch inputs)
# ---------------------------------------------------------------------------

def validate_expected_sha(value: object) -> str:
    if not isinstance(value, str) or not _SHA_RE.fullmatch(value):
        raise InputError(
            f"expected_sha is not an exact 40-hex git SHA: {value!r}")
    return value


def validate_pr_number(value: object) -> int | None:
    """``pr_number`` is audit-only: empty/None -> None, else a plain int."""
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not _PR_RE.fullmatch(value) \
            or not value.isascii():
        raise InputError(f"pr_number is not a plain positive integer: "
                         f"{value!r}")
    return int(value)


# ---------------------------------------------------------------------------
# Strict JSON
# ---------------------------------------------------------------------------

def _reject_duplicates(pairs: list) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ReuseError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_constant(name: str):
    raise ReuseError(f"non-finite JSON constant {name}")


def parse_strict_json(data: bytes) -> dict:
    try:
        parsed = json.loads(data.decode("utf-8"),
                            object_pairs_hook=_reject_duplicates,
                            parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise ReuseError(f"receipt is not valid JSON: {error}") from error
    if not isinstance(parsed, dict):
        raise ReuseError("receipt JSON is not an object")
    return parsed


def canonical_sha256(obj: object) -> str:
    return hashlib.sha256(json.dumps(
        obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# ---------------------------------------------------------------------------
# Read-only Actions API client
# ---------------------------------------------------------------------------

class _Redirect(Exception):
    def __init__(self, location: str):
        super().__init__(location)
        self.location = location


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # surface 3xx to the caller
        return None


class HttpActionsApi:
    """Minimal read-only GitHub Actions REST client (``actions: read``).

    The token is sent ONLY to the configured API origin; artifact downloads
    are redirected to storage hosts and are fetched WITHOUT credentials.
    """

    def __init__(self, api_url: str, repository: str, token: str, *,
                 timeout: float = HTTP_TIMEOUT_SECONDS,
                 _allow_insecure_loopback: bool = False):
        if not _REPO_RE.fullmatch(repository or ""):
            raise InputError(f"repository is malformed: {repository!r}")
        self.api_url = api_url.rstrip("/")
        self.repository = repository
        self._token = token
        self._timeout = timeout
        self._insecure_ok = _allow_insecure_loopback
        handlers: list = [_NoRedirect()]
        if _allow_insecure_loopback:
            handlers.append(urllib.request.ProxyHandler({}))
        self._opener = urllib.request.build_opener(*handlers)

    # -- transport --------------------------------------------------------
    def _scheme_ok(self, url: str) -> bool:
        return url.startswith("https://") or (
            self._insecure_ok and url.startswith("http://127.0.0.1"))

    def _request(self, url: str, *, auth: bool = True,
                 max_bytes: int = MAX_JSON_BYTES) -> bytes:
        if not self._scheme_ok(url):
            raise ApiUnavailable("refusing non-https URL")
        headers = {"Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28",
                   "User-Agent": "inferswarm-final-validation-reuse"}
        if auth:
            headers["Authorization"] = f"Bearer {self._token}"
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with self._opener.open(request, timeout=self._timeout) as resp:
                body = resp.read(max_bytes + 1)
        except urllib.error.HTTPError as error:
            if error.code in (301, 302, 303, 307, 308):
                location = error.headers.get("Location")
                if location:
                    raise _Redirect(location) from None
            raise ApiUnavailable(f"HTTP {error.code}") from None
        except (urllib.error.URLError, OSError, ValueError) as error:
            raise ApiUnavailable(f"transport error: {error}") from None
        if len(body) > max_bytes:
            raise ApiUnavailable("response exceeds byte bound")
        return body

    def _get_json(self, path: str) -> dict:
        try:
            body = self._request(f"{self.api_url}{path}")
        except _Redirect:
            raise ApiUnavailable("unexpected redirect") from None
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ApiUnavailable(f"malformed API JSON: {error}") from None
        if not isinstance(parsed, dict):
            raise ApiUnavailable("API JSON is not an object")
        return parsed

    # -- read-only surface -------------------------------------------------
    def list_runs(self, page: int, per_page: int) -> dict:
        query = urllib.parse.urlencode({
            "event": "workflow_dispatch", "status": "success",
            "per_page": per_page, "page": page})
        return self._get_json(
            f"/repos/{self.repository}/actions/workflows/"
            f"{WORKFLOW_FILE}/runs?{query}")

    def get_run(self, run_id: int) -> dict:
        return self._get_json(
            f"/repos/{self.repository}/actions/runs/{int(run_id)}")

    def list_artifacts(self, run_id: int) -> dict:
        return self._get_json(
            f"/repos/{self.repository}/actions/runs/{int(run_id)}/"
            "artifacts?per_page=100")

    def _follow_download_redirect(self, location: str,
                                  max_bytes: int) -> bytes:
        if not self._scheme_ok(location):
            raise ApiUnavailable("refusing non-https artifact redirect")
        try:
            return self._request(location, auth=False, max_bytes=max_bytes)
        except _Redirect:
            raise ApiUnavailable("nested artifact redirect") from None

    def download_artifact(self, artifact_id: int, max_bytes: int) -> bytes:
        url = (f"{self.api_url}/repos/{self.repository}/actions/artifacts/"
               f"{int(artifact_id)}/zip")
        try:
            return self._request(url, max_bytes=max_bytes)
        except _Redirect as redirect:
            return self._follow_download_redirect(redirect.location,
                                                  max_bytes)


class _CountingApi:
    def __init__(self, api):
        self._api = api
        self.calls = 0

    def list_runs(self, page, per_page):
        self.calls += 1
        return self._api.list_runs(page, per_page)

    def get_run(self, run_id):
        self.calls += 1
        return self._api.get_run(run_id)

    def list_artifacts(self, run_id):
        self.calls += 1
        return self._api.list_artifacts(run_id)

    def download_artifact(self, artifact_id, max_bytes):
        self.calls += 1
        return self._api.download_artifact(artifact_id, max_bytes)


# ---------------------------------------------------------------------------
# Verification of one candidate
# ---------------------------------------------------------------------------

def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _repo_name(obj: object) -> object:
    return obj.get("full_name") if isinstance(obj, dict) else None


def _check_run(run: object, *, expected_sha: str, current_run_id: int,
               repository: str) -> str | None:
    """Run-level eligibility; returns a rejection reason or ``None``."""
    if not isinstance(run, dict):
        return "run entry is not an object"
    run_id = run.get("id")
    if not _is_int(run_id) or run_id < 1:
        return "run id is malformed"
    if run_id >= current_run_id:
        return "run is not strictly earlier than the reusing run"
    if run.get("status") != "completed":
        return f"run is not completed ({run.get('status')!r})"
    if run.get("conclusion") != "success":
        return f"run conclusion is not success ({run.get('conclusion')!r})"
    if run.get("event") != "workflow_dispatch":
        return "run was not a workflow_dispatch"
    if run.get("path") != WORKFLOW_PATH:
        return "run is not the Final CPU Validation workflow file"
    if run.get("name") != WORKFLOW_NAME:
        return "run workflow name differs"
    if run.get("head_sha") != expected_sha:
        return "run workflow definition is not the validated head"
    if not _is_int(run.get("run_attempt")) or run["run_attempt"] < 1:
        return "run attempt is malformed"
    if _repo_name(run.get("repository")) != repository \
            or _repo_name(run.get("head_repository")) != repository:
        return "run is not from this repository (fork or foreign)"
    return None


def _select_artifact(listing: object, run: dict, *, expected_sha: str) -> dict:
    if not isinstance(listing, dict) \
            or not isinstance(listing.get("artifacts"), list):
        raise ReuseError("artifact listing is malformed")
    named = [a for a in listing["artifacts"]
             if isinstance(a, dict)
             and a.get("name") == RECEIPT_ARTIFACT_NAME]
    if len(named) != 1:
        raise ReuseError(
            f"expected exactly one {RECEIPT_ARTIFACT_NAME!r} artifact, "
            f"found {len(named)}")
    art = named[0]
    if art.get("expired") is not False:
        raise ReuseError("receipt artifact is expired or has no expiry state")
    if not _is_int(art.get("id")) or art["id"] < 1:
        raise ReuseError("artifact id is malformed")
    size = art.get("size_in_bytes")
    if not _is_int(size) or size < 1 or size > MAX_ARTIFACT_BYTES:
        raise ReuseError("artifact size is missing or out of bounds")
    digest = art.get("digest")
    if not isinstance(digest, str) \
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ReuseError("artifact digest is missing or malformed")
    binding = art.get("workflow_run")
    if not isinstance(binding, dict) or binding.get("id") != run["id"] \
            or binding.get("head_sha") != expected_sha:
        raise ReuseError("artifact is not bound to the source run/head")
    repo_id, head_repo_id = (binding.get("repository_id"),
                             binding.get("head_repository_id"))
    if not _is_int(repo_id) or repo_id != head_repo_id:
        raise ReuseError("artifact comes from a fork or unknown repository")
    return art


def _extract_receipt(blob: bytes) -> bytes:
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            infos = archive.infolist()
            if [i.filename for i in infos] != [RECEIPT_MEMBER]:
                raise ReuseError(
                    "archive must contain exactly the one receipt member")
            info = infos[0]
            if info.is_dir() or info.file_size > MAX_MEMBER_BYTES:
                raise ReuseError("receipt member is a directory or too large")
            with archive.open(info) as member:
                data = member.read(MAX_MEMBER_BYTES + 1)
    except zipfile.BadZipFile as error:
        raise ReuseError(f"artifact is not a valid archive: {error}") \
            from error
    if len(data) > MAX_MEMBER_BYTES:
        raise ReuseError("receipt member exceeds its byte bound")
    return data


def verify_source_envelope(envelope: dict, *, expected_sha: str,
                           request: gate.FinalHeadRequest, run_id: int,
                           run_attempt: int) -> None:
    """Independently verify a candidate SOURCE envelope (fail closed).

    Raises ``ReuseError``/``GateOrderingError`` on any defect.  Used at
    lookup time AND again at compose time (the decision file is not
    trusted).
    """
    if not gate.validate_final_validation_receipt(envelope, expected_sha):
        raise ReuseError("receipt is for another head")
    if envelope.get("github_run_id") != str(run_id):
        raise ReuseError("receipt run id does not match the source run")
    if envelope.get("github_run_attempt") != run_attempt:
        raise ReuseError("receipt run attempt does not match the source run")
    if envelope.get("workflow") != WORKFLOW_NAME:
        raise ReuseError("receipt workflow name differs")
    execution = envelope.get("execution")
    if not isinstance(execution, dict):
        raise ReuseError("legacy receipt without an execution block is not "
                         "an eligible source")
    mode = execution.get("mode")
    if mode != gate.EXECUTION_MODE_EXECUTED:
        raise ReuseError(
            f"execution mode {mode!r} is not a physical execution "
            "(reuse receipts are never sources)")
    if execution.get("dispatch_sha") != expected_sha:
        raise ReuseError("source workflow definition was not the validated "
                         "head")
    if not gate.validate_receipt(envelope["suite_receipt"],
                                 request.to_dict()):
        raise ReuseError("suite identity differs from this head's canonical "
                         "request (configuration, population, count or "
                         "environment authority)")


def _verify_candidate(api, run: dict, *, expected_sha: str,
                      request: gate.FinalHeadRequest) -> dict:
    art = _select_artifact(api.list_artifacts(run["id"]), run,
                           expected_sha=expected_sha)
    blob = api.download_artifact(art["id"], MAX_ARTIFACT_BYTES)
    if not isinstance(blob, (bytes, bytearray)) \
            or len(blob) > MAX_ARTIFACT_BYTES:
        raise ReuseError("artifact download is malformed or oversized")
    actual = "sha256:" + hashlib.sha256(blob).hexdigest()
    if actual != art["digest"]:
        raise ReuseError("artifact bytes do not match the API digest")
    envelope = parse_strict_json(_extract_receipt(bytes(blob)))
    verify_source_envelope(envelope, expected_sha=expected_sha,
                           request=request, run_id=run["id"],
                           run_attempt=run["run_attempt"])
    return {
        "run_id": run["id"],
        "run_attempt": run["run_attempt"],
        "run_url": run.get("html_url") if isinstance(
            run.get("html_url"), str) else None,
        "workflow": envelope["workflow"],
        "artifact_id": art["id"],
        "artifact_digest": art["digest"],
        "envelope_sha256": canonical_sha256(envelope),
        "envelope": envelope,
    }


# ---------------------------------------------------------------------------
# The lookup
# ---------------------------------------------------------------------------

def _decision(action: str, reason: str, expected_sha: str, *,
              rejected: list | None = None, source: dict | None = None,
              api_calls: int = 0) -> dict:
    decision: dict = {
        "schema": DECISION_SCHEMA, "action": action, "reason": reason,
        "expected_sha": expected_sha, "rejected": rejected or [],
        "source": None, "api_calls": api_calls,
    }
    if source is not None:
        # The decision is a HINT: it names the source but never carries the
        # bytes composition will embed (those are re-fetched and
        # authenticated at compose time).
        decision["source"] = {k: v for k, v in source.items()
                              if k != "envelope"}
    return decision


def lookup_verified_prior_execution(
        api, *, expected_sha: str, request: gate.FinalHeadRequest,
        current_run_id: int, dispatch_sha: str, repository: str) -> dict:
    """Read-only, bounded, fail-closed search for a verified source.

    Never raises for discovery problems: every failure mode returns a
    ``run`` decision (the caller then executes the canonical suite).  The
    decision records every rejected candidate for audit.
    """
    validate_expected_sha(expected_sha)
    if not _is_int(current_run_id) or current_run_id < 1:
        raise InputError(f"current run id is malformed: {current_run_id!r}")
    if dispatch_sha != expected_sha:
        return _decision(
            "run", "workflow definition (GITHUB_SHA) is not the validated "
            "head; reuse disabled", expected_sha)
    counting = _CountingApi(api)
    rejected: list = []
    candidates = 0
    try:
        for page in range(1, MAX_RUN_PAGES + 1):
            listing = counting.list_runs(page, RUNS_PER_PAGE)
            runs = listing.get("workflow_runs") if isinstance(
                listing, dict) else None
            if not isinstance(runs, list):
                raise ReuseError("run listing is malformed")
            for run in runs:
                if _check_run(run, expected_sha=expected_sha,
                              current_run_id=current_run_id,
                              repository=repository) is not None:
                    continue
                if candidates >= MAX_CANDIDATES:
                    return _decision(
                        "run", "no verified source within the candidate "
                        "bound", expected_sha, rejected=rejected,
                        api_calls=counting.calls)
                candidates += 1
                try:
                    source = _verify_candidate(
                        counting, run, expected_sha=expected_sha,
                        request=request)
                except ApiUnavailable:
                    raise
                except (ReuseError, gate.GateOrderingError, KeyError,
                        TypeError, ValueError) as error:
                    rejected.append({"run_id": run["id"],
                                     "reason": str(error)})
                    continue
                return _decision(
                    "reuse", f"verified prior execution in run {run['id']}",
                    expected_sha, rejected=rejected, source=source,
                    api_calls=counting.calls)
            if len(runs) < RUNS_PER_PAGE:
                break
        return _decision("run", "no verified prior execution found",
                         expected_sha, rejected=rejected,
                         api_calls=counting.calls)
    except ApiUnavailable as error:
        return _decision("run", f"lookup unavailable (fail closed): {error}",
                         expected_sha, rejected=rejected,
                         api_calls=counting.calls)
    except Exception as error:  # noqa: BLE001 — fail closed on anything
        return _decision(
            "run", f"lookup failed (fail closed): "
            f"{type(error).__name__}: {error}", expected_sha,
            rejected=rejected, api_calls=counting.calls)


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------

_SOURCE_POINTER_KEYS = ("run_id", "run_attempt", "artifact_id",
                        "artifact_digest", "envelope_sha256", "workflow")


def authenticate_source(api, pointer: object, *, expected_sha: str,
                        request: gate.FinalHeadRequest, current_run_id: int,
                        repository: str) -> dict:
    """Independently authenticate the source a decision names (fail closed).

    ``pointer`` is the (untrusted) ``source`` object of a decision file.
    Everything it claims is re-derived from the read-only Actions API with
    the same checks the lookup applies — successful earlier run of this
    workflow on this head and repository, matching attempt, unexpired
    artifact bound to that run with a matching API digest, single-member
    archive, executed (never reused) receipt whose suite receipt matches
    this head's independently derived request — and must then equal the
    pointer's artifact id/digest/envelope hash.  Bounded: one run read, one
    artifact listing, one download.  Returns the verified candidate (whose
    ``envelope`` came from the API, not from the decision).
    """
    if not isinstance(pointer, dict):
        raise ReuseError("reuse decision lacks its source")
    if any(key not in pointer for key in _SOURCE_POINTER_KEYS):
        raise ReuseError("reuse decision source is incomplete")
    run_id, attempt = pointer["run_id"], pointer["run_attempt"]
    if not _is_int(run_id) or not _is_int(attempt) \
            or not _is_int(pointer["artifact_id"]):
        raise ReuseError("reuse decision source identity is malformed")
    counting = _CountingApi(api)
    run = counting.get_run(run_id)
    if not isinstance(run, dict) or run.get("id") != run_id:
        raise ReuseError("source run could not be read back from the API")
    reason = _check_run(run, expected_sha=expected_sha,
                        current_run_id=current_run_id,
                        repository=repository)
    if reason is not None:
        raise ReuseError(f"source run is not eligible: {reason}")
    if run["run_attempt"] != attempt:
        raise ReuseError(
            f"source run attempt changed (decision {attempt}, API "
            f"{run['run_attempt']})")
    verified = _verify_candidate(counting, run, expected_sha=expected_sha,
                                 request=request)
    for key, authentic in (("artifact_id", verified["artifact_id"]),
                           ("artifact_digest", verified["artifact_digest"]),
                           ("envelope_sha256", verified["envelope_sha256"]),
                           ("workflow", verified["workflow"])):
        if pointer[key] != authentic:
            raise ReuseError(
                f"decision {key} does not match the API-authenticated "
                "source")
    return verified


def compose_reuse_envelope(decision: dict, *, api, repository: str,
                           request: gate.FinalHeadRequest,
                           expected_sha: str, github_run_id: str,
                           github_run_attempt: int, workflow: str,
                           pr_number: int | None, dispatch_sha: str,
                           finalizer_check: bool,
                           project_status_check: bool) -> dict:
    """Build the NEW run's gate result from an API-authenticated source.

    The decision (a file written by an earlier step) is only a pointer.
    The source is re-authenticated against the read-only Actions API here
    (:func:`authenticate_source`); the embedded suite receipt is the
    API-fetched one.  Any failure — including API unavailability — raises:
    the suite was skipped on the strength of the lookup, so composition
    must either prove the source or FAIL the gate.
    """
    if not isinstance(decision, dict) \
            or decision.get("schema") != DECISION_SCHEMA \
            or decision.get("action") != "reuse":
        raise ReuseError("decision is not a reuse decision")
    if decision.get("expected_sha") != expected_sha:
        raise ReuseError("reuse decision is for another head")
    validate_expected_sha(expected_sha)
    if dispatch_sha != expected_sha:
        raise ReuseError("workflow definition is not the validated head")
    if not isinstance(github_run_id, str) \
            or not _RUN_ID_RE.fullmatch(github_run_id):
        raise ReuseError("reusing run id is not a numeric GitHub run id")
    verified = authenticate_source(
        api, decision.get("source"), expected_sha=expected_sha,
        request=request, current_run_id=int(github_run_id),
        repository=repository)
    envelope = verified["envelope"]
    execution = gate.execution_block_reused(
        dispatch_sha, source_run_id=str(verified["run_id"]),
        source_run_attempt=verified["run_attempt"],
        source_artifact_id=verified["artifact_id"],
        source_artifact_digest=verified["artifact_digest"],
        source_envelope_sha256=verified["envelope_sha256"],
        source_workflow=verified["workflow"])
    return gate.build_final_validation_receipt(
        expected_sha, envelope["suite_receipt"],
        github_run_id=github_run_id, github_run_attempt=github_run_attempt,
        workflow=workflow, pr_number=pr_number,
        finalizer_check=finalizer_check,
        project_status_check=project_status_check, execution=execution)


def check_suite_result_against_request(result: dict,
                                       request: gate.FinalHeadRequest,
                                       expected_sha: str) -> dict:
    """The original inline composition checks, now testable.

    The executed run's suite identity is DERIVED from the runner result and
    compared with the identity independently derived from the checked-out
    tree: a different configuration, population or count cannot validate
    this head.
    """
    suite = gate.suite_identity(result)
    if suite["serial_digest"] != suite["executed_digest"]:
        raise ReuseError("serial/executed identity mismatch")
    if request.git_commit_sha != expected_sha:
        raise ReuseError("final-head request SHA drifted from expected_sha")
    if request.suite["serial_digest"] != suite["serial_digest"]:
        raise ReuseError("executed population digest differs from this "
                         "head's canonical plan")
    if request.suite["count"] != suite["count"]:
        raise ReuseError("executed count differs from this head's "
                         "canonical plan")
    if request.suite["suite_config"] != suite["suite_config"]:
        raise ReuseError("executed suite configuration differs from the "
                         "canonical final-validation configuration")
    return suite


# ---------------------------------------------------------------------------
# CLI (the workflow's two steps)
# ---------------------------------------------------------------------------

def _inputs(environ: Mapping[str, str]) -> tuple[str, int | None]:
    return (validate_expected_sha(environ.get("EXPECTED_SHA")),
            validate_pr_number(environ.get("PR_NUMBER", "")))


def _write_output(environ: Mapping[str, str], key: str, value: str) -> None:
    path = environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{key}={value}\n")


def _cmd_lookup(args, environ, api_factory, request_factory) -> int:
    expected_sha, _ = _inputs(environ)
    request = request_factory(Path(args.repo_root))
    run_id_raw = environ.get("GITHUB_RUN_ID", "")
    token = environ.get("GITHUB_TOKEN", "")
    repository = environ.get("GITHUB_REPOSITORY", "")
    if not _RUN_ID_RE.fullmatch(run_id_raw):
        decision = _decision("run", "GITHUB_RUN_ID is not numeric",
                             expected_sha)
    elif not token or not _REPO_RE.fullmatch(repository):
        decision = _decision(
            "run", "no read-only Actions API credentials; reuse disabled",
            expected_sha)
    else:
        try:
            api = api_factory(
                api_url=environ.get("GITHUB_API_URL",
                                    "https://api.github.com"),
                repository=repository, token=token)
            decision = lookup_verified_prior_execution(
                api, expected_sha=expected_sha, request=request,
                current_run_id=int(run_id_raw),
                dispatch_sha=environ.get("GITHUB_SHA", ""),
                repository=repository)
        except Exception as error:  # noqa: BLE001 — fail closed
            decision = _decision(
                "run", f"lookup unavailable (fail closed): "
                f"{type(error).__name__}: {error}", expected_sha)
    Path(args.out).write_text(json.dumps(decision, indent=1, sort_keys=True),
                              encoding="utf-8")
    reused = decision["action"] == "reuse"
    _write_output(environ, "reuse", "true" if reused else "false")
    print(f"final-validation reuse lookup: {decision['action'].upper()} — "
          f"{decision['reason']}")
    for item in decision["rejected"]:
        print(f"  rejected run {item['run_id']}: {item['reason']}")
    if reused:
        src = decision["source"]
        print(f"  source run {src['run_id']} attempt {src['run_attempt']} "
              f"artifact {src['artifact_id']} {src['artifact_digest']}")
    return 0


def _compose_reuse_authenticated(args, environ, api_factory, *, request,
                                 expected_sha, run_id, attempt, workflow,
                                 pr_number, dispatch_sha) -> dict:
    repository = environ.get("GITHUB_REPOSITORY", "")
    token = environ.get("GITHUB_TOKEN", "")
    if not token or not _REPO_RE.fullmatch(repository):
        raise ReuseError(
            "the suite was skipped for a verified prior execution but no "
            "read-only Actions API credentials are available to "
            "re-authenticate it; the gate fails (re-dispatch to execute)")
    try:
        decision = json.loads(Path(args.decision).read_text("utf-8"))
        api = api_factory(
            api_url=environ.get("GITHUB_API_URL", "https://api.github.com"),
            repository=repository, token=token)
        return compose_reuse_envelope(
            decision, api=api, repository=repository, request=request,
            expected_sha=expected_sha, github_run_id=run_id,
            github_run_attempt=attempt, workflow=workflow,
            pr_number=pr_number, dispatch_sha=dispatch_sha,
            finalizer_check=True, project_status_check=True)
    except (ReuseError, gate.GateOrderingError):
        raise
    except Exception as error:  # noqa: BLE001 — outage, timeout, anything
        raise ReuseError(
            "cannot re-authenticate the reuse source against the Actions "
            f"API ({type(error).__name__}: {error}); the suite was skipped "
            "so the gate fails (re-dispatch to execute)") from error


def _cmd_compose(args, environ, api_factory, request_factory) -> int:
    def die(message: str) -> int:
        print(f"final-validation receipt: FAIL {message}")
        return 1

    expected_sha, pr_number = _inputs(environ)
    run_id = environ.get("GITHUB_RUN_ID", "")
    try:
        attempt = int(environ.get("GITHUB_RUN_ATTEMPT", ""))
    except ValueError:
        return die("GITHUB_RUN_ATTEMPT is not an integer")
    workflow = environ.get("GITHUB_WORKFLOW", WORKFLOW_NAME)
    dispatch_sha = environ.get("GITHUB_SHA", "")
    repo = Path(args.repo_root).resolve()
    try:
        request = request_factory(repo)
    except gate.GateOrderingError as error:
        return die(f"cannot derive the final-head request: {error}")
    if request.git_commit_sha != expected_sha:
        return die("final-head request SHA drifted from expected_sha")

    try:
        if environ.get("REUSE") == "true":
            if Path(args.suite_result).exists():
                return die("a reuse run must not have executed the suite")
            # The suite was skipped on the strength of the lookup: the
            # source must be re-authenticated against the Actions API NOW
            # or the gate FAILS (never PASS, never a claimed execution).
            envelope = _compose_reuse_authenticated(
                args, environ, api_factory, request=request,
                expected_sha=expected_sha, run_id=run_id, attempt=attempt,
                workflow=workflow, pr_number=pr_number,
                dispatch_sha=dispatch_sha)
        else:
            try:
                result = json.load(open(args.suite_result))
            except (OSError, json.JSONDecodeError) as error:
                return die(f"suite result unreadable: {error}")
            check_suite_result_against_request(result, request, expected_sha)
            started = float(Path(args.suite_started).read_text().strip())
            ended = float(Path(args.suite_ended).read_text().strip())
            receipt = gate.build_receipt(repo, result, started, ended)
            if not gate.validate_receipt(receipt.to_dict(),
                                         request.to_dict()):
                return die("suite receipt does not validate against the "
                           "exact head")
            envelope = gate.build_final_validation_receipt(
                expected_sha, receipt.to_dict(),
                github_run_id=run_id, github_run_attempt=attempt,
                workflow=workflow, pr_number=pr_number,
                finalizer_check=True, project_status_check=True,
                execution=gate.execution_block_executed(
                    validate_expected_sha(dispatch_sha)))
    except (ReuseError, gate.GateOrderingError, OSError, ValueError,
            json.JSONDecodeError) as error:
        return die(str(error))
    Path(args.out).write_text(json.dumps(envelope, indent=1, sort_keys=True),
                              encoding="utf-8")
    print("final-validation receipt: OK "
          f"({envelope['execution']['mode']})")
    print(json.dumps(envelope, sort_keys=True)[:2000])
    return 0


def _default_request_factory(root: Path) -> gate.FinalHeadRequest:
    return gate.current_final_head_request(root)


def main(argv: list[str] | None = None, *,
         environ: Mapping[str, str] | None = None,
         api_factory: Callable[..., object] | None = None,
         request_factory: Callable[[Path], gate.FinalHeadRequest] | None = None
         ) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    look = sub.add_parser("lookup", help="read-only verified-source lookup")
    look.add_argument("--out", required=True)
    look.add_argument("--repo-root", default=".")
    comp = sub.add_parser("compose", help="compose + validate the receipt")
    comp.add_argument("--decision", default="/tmp/reuse-decision.json")
    comp.add_argument("--suite-result", default="/tmp/suite-result.json")
    comp.add_argument("--suite-started", default="/tmp/suite-started.unix")
    comp.add_argument("--suite-ended", default="/tmp/suite-ended.unix")
    comp.add_argument("--out", required=True)
    comp.add_argument("--repo-root", default=".")
    args = parser.parse_args(argv)
    environ = os.environ if environ is None else environ
    request_factory = request_factory or _default_request_factory
    try:
        if args.command == "lookup":
            return _cmd_lookup(args, environ, api_factory or HttpActionsApi,
                               request_factory)
        return _cmd_compose(args, environ, api_factory or HttpActionsApi,
                            request_factory)
    except (ReuseError, gate.GateOrderingError) as error:
        print(f"final-validation: FAIL {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
