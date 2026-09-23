"""Fail-closed maintainer dispatch verification for physical R8-I3 runs.

The verifier authorizes only an open PR on the current exact commit, while
Issue #241 remains open, and a latest OWNER/MEMBER approval explicitly
containing the dispatch phrase and head SHA. It performs read-only GitHub
API requests; it never launches a model or touches a GPU.

No physical R8-I3 execution may occur without this authority (Issue #241:
the operator performs the hardware swap; retained physical measurements
require explicit maintainer dispatch on the exact frozen producer head).
"""
from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

REPO = "Zutfen-LLC/inferswarm"
ISSUE_NUMBER = 241
BASE_REF = "main"
DISPATCH_PHRASE = "R8I3 PHYSICAL DISPATCH #241"
AUTHORIZED_ASSOCIATIONS = frozenset({"OWNER", "MEMBER"})
SHA40 = re.compile(r"^[0-9a-f]{40}$")
AUTHORITY_SCHEMA = "inferswarm.issue241.dispatch-authority/1"


def _require_sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or SHA40.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase 40-character commit SHA")
    return value


def _parse_timestamp(value: Any) -> dt.datetime:
    if not isinstance(value, str):
        raise ValueError("dispatch review requires submitted_at")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("dispatch review submitted_at is malformed") from exc
    if parsed.tzinfo is None:
        raise ValueError("dispatch review submitted_at must include a timezone")
    return parsed.astimezone(dt.timezone.utc)


def validate_dispatch_authority(
    pr: dict[str, Any],
    issue: dict[str, Any],
    reviews: list[dict[str, Any]],
    expected_head: str,
) -> dict[str, Any]:
    """Validate a live PR/issue/review response for an explicit dispatch."""
    expected_head = _require_sha(expected_head, "expected_head")
    if not isinstance(pr, dict) or not isinstance(issue, dict):
        raise ValueError("PR and issue responses must be objects")
    if pr.get("state") != "open" or pr.get("merged_at") is not None:
        raise ValueError("dispatch requires an open, unmerged PR")
    if pr.get("base", {}).get("ref") != BASE_REF:
        raise ValueError(f"dispatch PR must target {BASE_REF}")
    if pr.get("head", {}).get("sha") != expected_head:
        raise ValueError("dispatch PR head does not match the exact producer commit")
    if issue.get("number") != ISSUE_NUMBER or issue.get("state") != "open":
        raise ValueError(f"Issue #{ISSUE_NUMBER} must remain open for physical dispatch")
    if not isinstance(reviews, list):
        raise ValueError("PR reviews response must be a list")

    latest_by_login: dict[str, dict[str, Any]] = {}
    for review in reviews:
        if not isinstance(review, dict):
            raise ValueError("PR review entries must be objects")
        user = review.get("user")
        login = user.get("login") if isinstance(user, dict) else None
        if isinstance(login, str) and login:
            latest_by_login[login] = review

    candidates: list[tuple[dt.datetime, dict[str, Any], str]] = []
    for login, review in latest_by_login.items():
        association = review.get("author_association")
        body = review.get("body")
        if (review.get("state") != "APPROVED" or
                association not in AUTHORIZED_ASSOCIATIONS or
                review.get("commit_id") != expected_head or
                not isinstance(body, str)):
            continue
        lines = {line.strip() for line in body.splitlines()}
        if DISPATCH_PHRASE not in lines or f"head={expected_head}" not in lines:
            continue
        review_id = review.get("id")
        if not isinstance(review_id, int) or isinstance(review_id, bool) or review_id <= 0:
            continue
        submitted = _parse_timestamp(review.get("submitted_at"))
        candidates.append((submitted, review, login))

    if not candidates:
        raise ValueError(
            "no current OWNER/MEMBER approval explicitly dispatches this exact head")
    submitted, review, login = max(candidates, key=lambda item: item[0])
    return {
        "schema": AUTHORITY_SCHEMA,
        "repository": REPO,
        "issue_number": ISSUE_NUMBER,
        "pr_number": pr.get("number"),
        "pr_state": pr["state"],
        "merged_at": pr.get("merged_at"),
        "base_ref": BASE_REF,
        "head_sha": expected_head,
        "review_id": review["id"],
        "reviewer": login,
        "reviewer_association": review["author_association"],
        "review_commit_id": review["commit_id"],
        "submitted_at": submitted.isoformat().replace("+00:00", "Z"),
        "dispatch_phrase": DISPATCH_PHRASE,
    }


def _get_json(url: str, opener: Callable[..., Any] = urllib.request.urlopen) -> Any:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.github+json",
                 "User-Agent": "inferswarm-issue241-dispatch-verifier"},
        method="GET",
    )
    try:
        with opener(request, timeout=20) as response:
            status = getattr(response, "status", 200)
            if status != 200:
                raise ValueError(f"GitHub API returned HTTP {status} for dispatch lookup")
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise ValueError(f"GitHub API dispatch lookup failed with HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ValueError("GitHub API dispatch lookup was unavailable") from exc


def fetch_dispatch_authority(
    pr_number: int,
    expected_head: str,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    """Fetch public GitHub state and validate the exact-head dispatch."""
    if not isinstance(pr_number, int) or isinstance(pr_number, bool) or pr_number <= 0:
        raise ValueError("pr_number must be a positive integer")
    head = _require_sha(expected_head, "expected_head")
    api = "https://api.github.com"
    pr = _get_json(f"{api}/repos/{REPO}/pulls/{pr_number}", opener)
    issue = _get_json(f"{api}/repos/{REPO}/issues/{ISSUE_NUMBER}", opener)
    reviews = _get_json(f"{api}/repos/{REPO}/pulls/{pr_number}/reviews?per_page=100", opener)
    authority = validate_dispatch_authority(pr, issue, reviews, head)
    if authority["pr_number"] != pr_number:
        raise ValueError("GitHub returned a different PR number")
    authority["verified_via"] = "public-github-api"
    return authority


def current_clean_git_head(repo_root: Path) -> str:
    """Return HEAD only when the producer checkout is clean and verifiable."""
    repo_root = Path(repo_root).resolve()
    head = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--verify", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    _require_sha(head, "git HEAD")
    status = subprocess.run(
        ["git", "-C", str(repo_root), "status", "--porcelain", "--untracked-files=all"],
        check=True, capture_output=True, text=True,
    ).stdout
    if status:
        raise ValueError("physical execution requires a clean producer worktree")
    return head


def require_live_dispatch(repo_root: Path, pr_number: int) -> dict[str, Any]:
    """Enforce exact clean HEAD and live maintainer dispatch before launch."""
    head = current_clean_git_head(repo_root)
    return fetch_dispatch_authority(pr_number, head)


def require_exact_producer_dispatch(repo_root: Path, pr_number: int,
                                    producer_commit: str) -> dict[str, Any]:
    """Require the caller's frozen producer SHA to equal live authorized HEAD."""
    requested = _require_sha(producer_commit, "producer_commit")
    authority = require_live_dispatch(repo_root, pr_number)
    if not isinstance(authority, dict):
        raise ValueError("live dispatch returned no authority record")
    authorized = _require_sha(authority.get("head_sha"), "dispatch head_sha")
    if requested != authorized:
        raise ValueError("producer_commit does not match dispatched exact HEAD")
    return authority
