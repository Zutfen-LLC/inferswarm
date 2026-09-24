"""Fail-closed maintainer dispatch verification for physical R8-I3 runs.

The verifier authorizes only an open PR on the current exact commit, while
Issue #241 remains open, and a latest OWNER/MEMBER top-level PR conversation
comment explicitly containing the dispatch phrase and the exact head SHA.
It performs read-only GitHub API requests; it never launches a model or
touches a GPU.

This repository has exactly one human maintainer, who is also the PR author.
GitHub structurally prevents a PR author from approving their own PR, so an
independent APPROVED-review gate is unrealizable here by construction.
Dispatch authority is therefore an exact-head top-level PR conversation
comment (Issue #241 maintainer authorization doctrine; maintainer correction
comment on PR #242, 2026-09-24). GitHub review state — including APPROVED —
is NOT part of this gate, and the PR author MAY be the authorizing
commenter.

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
# Schema /2 (2026-09-24): dispatch authority changed from pull-request
# review submissions (review_id/reviewer/review_commit_id/submitted_at,
# requiring state == APPROVED) to top-level PR conversation comments
# (comment_id/commenter/commenter_association/created_at). Review-only
# fields were removed, not retained as placeholders; receipts carrying
# schema /1 or legacy review-* fields are rejected.
AUTHORITY_SCHEMA = "inferswarm.issue241.dispatch-authority/2"
LEGACY_AUTHORITY_KEYS = frozenset({
    "review_id", "reviewer", "reviewer_association", "review_commit_id",
    "submitted_at",
})
# Issue-comments are fetched paginated; a valid authorization comment must
# never be missed because a caller assumed a single page.
COMMENTS_PER_PAGE = 100
MAX_COMMENT_PAGES = 30


def _require_sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or SHA40.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase 40-character commit SHA")
    return value


def _parse_timestamp(value: Any) -> dt.datetime:
    if not isinstance(value, str):
        raise ValueError("dispatch comment requires created_at")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("dispatch comment created_at is malformed") from exc
    if parsed.tzinfo is None:
        raise ValueError("dispatch comment created_at must include a timezone")
    return parsed.astimezone(dt.timezone.utc)


def _exact_lines(body: str) -> set[str]:
    return {line.strip() for line in body.splitlines()}


def validate_dispatch_authority(
    pr: dict[str, Any],
    issue: dict[str, Any],
    comments: list[dict[str, Any]],
    expected_head: str,
) -> dict[str, Any]:
    """Validate live PR/issue/PR-conversation-comment responses for dispatch.

    ``comments`` must be the TOP-LEVEL PR conversation comments (the issue
    comments of the PR), never pull-request review submissions, inline
    review comments, or commit comments. GitHub review state is irrelevant:
    no review — APPROVED or otherwise — can authorize or contribute to
    authorization.
    """
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
    if not isinstance(comments, list):
        raise ValueError("PR conversation comments response must be a list")

    pr_number = pr.get("number")
    if not isinstance(pr_number, int) or isinstance(pr_number, bool):
        raise ValueError("PR response must carry an integer PR number")

    candidates: list[tuple[dt.datetime, int, dict[str, Any], str]] = []
    for comment in comments:
        if not isinstance(comment, dict):
            raise ValueError("PR conversation comment entries must be objects")
        # A comment minted on another issue/PR is not a PR #<pr> dispatch
        # comment even if its body carries the phrase. Real GitHub
        # issue-comment responses always carry issue_url; requiring it
        # (and rejecting pull_request_url) structurally excludes inline
        # review comments, which live on /pulls/{n}/comments.
        issue_url = comment.get("issue_url")
        if (not isinstance(issue_url, str)
                or not issue_url.rstrip("/").endswith(f"/issues/{pr_number}")
                or comment.get("pull_request_url") is not None):
            continue
        association = comment.get("author_association")
        if association not in AUTHORIZED_ASSOCIATIONS:
            continue
        body = comment.get("body")
        if not isinstance(body, str):
            continue
        lines = _exact_lines(body)
        if (DISPATCH_PHRASE not in lines
                or f"head={expected_head}" not in lines):
            continue
        comment_id = comment.get("id")
        if (not isinstance(comment_id, int) or isinstance(comment_id, bool)
                or comment_id <= 0):
            continue
        user = comment.get("user")
        login = user.get("login") if isinstance(user, dict) else None
        if not isinstance(login, str) or not login:
            continue
        # Review submissions carry no created_at; requiring it here also
        # structurally rejects review-shaped documents passed as comments.
        created = _parse_timestamp(comment.get("created_at"))
        candidates.append((created, comment_id, comment, login))

    if not candidates:
        raise ValueError(
            "no current OWNER/MEMBER top-level PR conversation comment "
            "explicitly dispatches this exact head")
    # Deterministic selection: latest timestamp, then highest comment ID.
    created, comment_id, comment, login = max(
        candidates, key=lambda item: (item[0], item[1]))
    return {
        "schema": AUTHORITY_SCHEMA,
        "repository": REPO,
        "issue_number": ISSUE_NUMBER,
        "pr_number": pr_number,
        "pr_state": pr["state"],
        "merged_at": pr.get("merged_at"),
        "base_ref": BASE_REF,
        "head_sha": expected_head,
        "comment_id": comment_id,
        "commenter": login,
        "commenter_association": comment["author_association"],
        "created_at": created.isoformat().replace("+00:00", "Z"),
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


def _fetch_all_pr_comments(api: str, pr_number: int,
                           opener: Callable[..., Any]) -> list[dict[str, Any]]:
    """Fetch every top-level PR conversation comment, across pages.

    Fail closed: pagination continues until a short page; hitting the page
    bound with a full page is an error, never a silent truncation that
    could miss a valid authorization comment.
    """
    comments: list[dict[str, Any]] = []
    for page in range(1, MAX_COMMENT_PAGES + 1):
        batch = _get_json(
            f"{api}/repos/{REPO}/issues/{pr_number}/comments"
            f"?per_page={COMMENTS_PER_PAGE}&page={page}", opener)
        if not isinstance(batch, list):
            raise ValueError("PR conversation comments response must be a list")
        comments.extend(batch)
        if len(batch) < COMMENTS_PER_PAGE:
            return comments
    raise ValueError(
        "PR conversation comments exceeded the bounded page fetch; "
        "refusing to authorize on a possibly-truncated comment list")


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
    comments = _fetch_all_pr_comments(api, pr_number, opener)
    authority = validate_dispatch_authority(pr, issue, comments, head)
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
